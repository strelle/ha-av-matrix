"""The integration-wide hub: source registries, destinations, routing, locks, undo, labels."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .const import (
    CONF_DISPLAYS,
    CONNECTING_GRACE,
    DOMAIN,
    EVENT_ROUTED,
    HISTORY_SIZE,
    NONE_OPTION,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .display import async_drive_display, display_state
from .drivers import DriverError
from .drivers.base import short
from .models import ConnectionState
from .protocols import PROTOCOLS, SourceRegistry, tcp_probe

if TYPE_CHECKING:
    from .coordinator import AvMatrixCoordinator

_LOGGER = logging.getLogger(__name__)

EVALUATE_INTERVAL = timedelta(seconds=5)


@dataclass(slots=True, eq=False)
class Destination:
    """One routable destination (a decoder output, a receiver channel …)."""

    uid: str
    dest_id: str
    protocol: str
    coordinator: AvMatrixCoordinator
    channel_name: str | None = None
    entity_id: str | None = None
    last_route: float = 0.0
    display_error: str | None = None

    @property
    def entry_id(self) -> str:
        return self.coordinator.config_entry.entry_id

    @property
    def device_name(self) -> str:
        return self.coordinator.device_name

    @property
    def name(self) -> str:
        return f"{self.device_name} · {self.channel_name}" if self.channel_name else self.device_name


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts else None


class AvMatrixHub:
    """State shared by all config entries of the integration."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.version = "unknown"  # set from manifest.json in async_setup
        self.registries: dict[str, SourceRegistry] = {
            key: proto.registry(tcp_probe) for key, proto in PROTOCOLS.items()
        }
        self.destinations: dict[str, Destination] = {}
        self.locks: set[str] = set()
        self.labels: dict[str, dict[str, dict[str, Any]]] = {}
        self.history: dict[str, deque[str | None]] = {}
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._eval_pending = False
        self._browsers: list[Any] = []

    # ---------------------------------------------------------------- lifecycle
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.locks = set(data.get("locks", []))
        self.labels = data.get("labels", {})

    async def async_start(self) -> None:
        """Start discovery and periodic liveness evaluation (first config entry)."""
        if self._unsubs:
            return
        from .discovery import NdiMdnsBrowser  # noqa: PLC0415 - needs the zeroconf component

        browser = NdiMdnsBrowser(self.hass, self.registries["ndi"], self.schedule_evaluate)  # type: ignore[arg-type]
        try:
            await browser.async_start()
            self._browsers.append(browser)
        except Exception as err:  # noqa: BLE001 - discovery is optional, device lists still work
            _LOGGER.warning("mDNS discovery of NDI sources unavailable: %s", short(err))
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_periodic, EVALUATE_INTERVAL, cancel_on_shutdown=True)
        )

    async def async_stop(self) -> None:
        """Stop discovery (last config entry unloaded)."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for browser in self._browsers:
            await browser.async_stop()
        self._browsers.clear()

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"locks": sorted(self.locks), "labels": self.labels}, 1)

    # ---------------------------------------------------------- notifications
    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def async_notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ------------------------------------------------------------- registries
    async def _async_periodic(self, _now: datetime) -> None:
        await self.async_evaluate()

    async def async_evaluate(self) -> None:
        changed = False
        for registry in self.registries.values():
            changed |= await registry.async_evaluate()
        if changed:
            self.async_notify()

    @callback
    def schedule_evaluate(self) -> None:
        """Debounced re-evaluation of all registries (after polls, discovery events)."""
        if self._eval_pending:
            return
        self._eval_pending = True

        async def run() -> None:
            await asyncio.sleep(0)
            self._eval_pending = False
            await self.async_evaluate()

        self.hass.async_create_task(run(), "av_matrix evaluate", eager_start=False)

    # ----------------------------------------------------------- destinations
    @callback
    def add_destination(self, dest: Destination) -> None:
        self.destinations[dest.uid] = dest
        self.history.setdefault(dest.uid, deque(maxlen=HISTORY_SIZE))

    @callback
    def remove_destination(self, uid: str) -> None:
        self.destinations.pop(uid, None)

    def destination_for_entity(self, entity_id: str) -> Destination | None:
        return next((d for d in self.destinations.values() if d.entity_id == entity_id), None)

    def registry(self, protocol: str) -> SourceRegistry:
        return self.registries[protocol]

    # ---------------------------------------------------------------- naming
    def label(self, protocol: str, source_id: str) -> dict[str, Any]:
        return self.labels.get(protocol, {}).get(source_id, {})

    def display_name(self, protocol: str, source_id: str | None) -> str:
        if source_id is None:
            return NONE_OPTION
        return self.label(protocol, source_id).get("label") or source_id

    def resolve_source(self, protocol: str, text: str | None) -> str | None:
        """Map an option / user input to a source id. None/"None"/"" → None (= off)."""
        if text is None or text.strip() == "" or text.strip().casefold() in {"none", NONE_OPTION.casefold()}:
            return None
        if self.registries[protocol].get(text):
            return text
        for source_id, lab in self.labels.get(protocol, {}).items():
            if lab.get("label") == text:
                return source_id
        return text  # unknown names are allowed (source may not be discovered yet)

    def options(self, dest: Destination) -> list[str]:
        registry = self.registries[dest.protocol]
        names = [self.display_name(dest.protocol, r.id) for r in registry.sources]
        current = self.current_source(dest)
        if current is not None and current not in {r.id for r in registry.sources}:
            names.append(self.display_name(dest.protocol, current))
        seen: set[str] = set()
        return [NONE_OPTION] + [n for n in names if not (n in seen or seen.add(n))]

    # ------------------------------------------------------------------ state
    def current_source(self, dest: Destination) -> str | None:
        data = dest.coordinator.data
        state = data.destinations.get(dest.dest_id) if data else None
        if state is None:
            return None
        return self.registries[dest.protocol].real_name(dest.entry_id, state.current)

    def resolution(self, dest: Destination) -> str | None:
        data = dest.coordinator.data
        state = data.destinations.get(dest.dest_id) if data else None
        return state.status.resolution if state and dest.coordinator.last_update_success else None

    def status_extra(self, dest: Destination) -> dict[str, Any]:
        data = dest.coordinator.data
        state = data.destinations.get(dest.dest_id) if data else None
        return dict(state.status.extra) if state and dest.coordinator.last_update_success else {}

    def connection_state(self, dest: Destination) -> ConnectionState:
        coordinator = dest.coordinator
        data = coordinator.data
        if not coordinator.last_update_success or data is None or dest.dest_id not in data.destinations:
            return ConnectionState.OFFLINE
        current = self.current_source(dest)
        if current is None:
            return ConnectionState.NO_SOURCE
        connected = data.destinations[dest.dest_id].status.connected
        if connected is True:
            return ConnectionState.CONNECTED
        live = self.registries[dest.protocol].is_live(current)
        recent = time.monotonic() - dest.last_route < max(CONNECTING_GRACE, coordinator.driver.SETTLE_TIME)
        if connected is False:
            return ConnectionState.CONNECTING if live or recent else ConnectionState.SOURCE_LOST
        # device cannot tell (e.g. BirdDog without /decodestatus): derive from the registry
        if live:
            return ConnectionState.CONNECTED
        return ConnectionState.CONNECTING if recent else ConnectionState.SOURCE_LOST

    def display_config(self, dest: Destination) -> dict[str, Any] | None:
        return dest.coordinator.config_entry.options.get(CONF_DISPLAYS, {}).get(dest.dest_id)

    # ---------------------------------------------------------------- actions
    def _get(self, uid: str) -> Destination:
        dest = self.destinations.get(uid)
        if dest is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_destination",
                translation_placeholders={"destination": uid},
            )
        return dest

    def _check_unlocked(self, dest: Destination) -> None:
        if dest.uid in self.locks:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="destination_locked",
                translation_placeholders={"destination": dest.name},
            )

    async def async_route(
        self, uid: str, source: str | None, *, record_history: bool = True, origin: str = "service"
    ) -> None:
        """Route ``source`` (registry id, None = off) to destination ``uid``."""
        dest = self._get(uid)
        self._check_unlocked(dest)
        await self._async_route(dest, source, record_history=record_history, origin=origin)

    async def _async_route(self, dest: Destination, source: str | None, *, record_history: bool, origin: str) -> None:
        coordinator = dest.coordinator
        registry = self.registries[dest.protocol]
        previous = self.current_source(dest)
        device_source = registry.device_name(dest.entry_id, source) if source else None
        address = registry.address_for(dest.entry_id, source) if source else None
        try:
            await coordinator.driver.async_route(dest.dest_id, device_source, address)
        except DriverError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="route_failed",
                translation_placeholders={"destination": dest.name, "error": short(err)},
            ) from err
        dest.last_route = time.monotonic()
        coordinator.set_current(dest.dest_id, device_source)
        if record_history and previous != source:
            self.history[dest.uid].append(previous)
        _LOGGER.debug("Routed %s → %s (%s)", source, dest.name, origin)
        self.hass.bus.async_fire(
            EVENT_ROUTED,
            {
                "entity_id": dest.entity_id,
                "destination": dest.uid,
                "destination_name": dest.name,
                "protocol": dest.protocol,
                "source": source,
                "previous_source": previous,
                "origin": origin,
            },
        )
        coordinator.async_refresh_after_route()
        cfg = self.display_config(dest)
        if cfg:
            self.hass.async_create_background_task(
                self._async_display(dest, cfg, source), f"av_matrix display {dest.uid}"
            )
        self.async_notify()

    async def _async_display(self, dest: Destination, cfg: dict[str, Any], source: str | None) -> None:
        dest.display_error = await async_drive_display(self.hass, cfg, source)
        self.async_notify()

    async def async_salvo(self, routes: Iterable[tuple[str, str | None]]) -> None:
        """Validate all routes first (unknown/locked → nothing is switched), then execute.

        Destinations of different devices switch in parallel, same device sequentially.
        """
        plan = [(self._get(uid), source) for uid, source in routes]
        for dest, _ in plan:
            self._check_unlocked(dest)
        groups: dict[str, list[tuple[Destination, str | None]]] = {}
        for dest, source in plan:
            groups.setdefault(dest.entry_id, []).append((dest, source))

        async def run(items: list[tuple[Destination, str | None]]) -> list[str]:
            errors = []
            for dest, source in items:
                try:
                    await self._async_route(dest, source, record_history=True, origin="salvo")
                except HomeAssistantError as err:
                    errors.append(f"{dest.name}: {err}")
            return errors

        results = await asyncio.gather(*(run(items) for items in groups.values()))
        errors = [e for group in results for e in group]
        if errors:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="salvo_failed",
                translation_placeholders={"errors": "; ".join(errors)},
            )

    async def async_undo(self, uid: str) -> None:
        dest = self._get(uid)
        self._check_unlocked(dest)
        history = self.history.get(uid)
        if not history:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="nothing_to_undo",
                translation_placeholders={"destination": dest.name},
            )
        previous = history.pop()
        try:
            await self._async_route(dest, previous, record_history=False, origin="undo")
        except HomeAssistantError:
            history.append(previous)
            raise

    @callback
    def async_set_lock(self, uid: str, locked: bool) -> None:
        self._get(uid)
        if locked:
            self.locks.add(uid)
        else:
            self.locks.discard(uid)
        self._save()
        self.async_notify()

    @callback
    def async_set_label(self, protocol: str, source_id: str, label: str | None, tags: list[str] | None) -> None:
        if protocol not in self.registries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_protocol")
        entry: dict[str, Any] = {}
        if label and label.strip():
            entry["label"] = label.strip()
        if tags:
            entry["tags"] = sorted({t.strip() for t in tags if t and t.strip()})
        labels = self.labels.setdefault(protocol, {})
        if entry:
            labels[source_id] = entry
        else:
            labels.pop(source_id, None)
        self._save()
        self.async_notify()

    # --------------------------------------------------------------- snapshot
    def snapshot(self) -> dict[str, Any]:
        """Complete state for the frontend (WebSocket API, see docs/frontend-api.md)."""
        ent_reg = er.async_get(self.hass)
        out: dict[str, Any] = {"version": self.version, "protocols": {}}
        for key, proto in PROTOCOLS.items():
            registry = self.registries[key]
            dests = [d for d in self.destinations.values() if d.protocol == key]
            sources: dict[str, dict[str, Any]] = {}
            for rec in registry.sources:
                sources[rec.id] = self._source_dict(key, rec.id, rec.live, rec.address, rec.last_seen, rec.first_seen)
            destinations = []
            for dest in sorted(dests, key=lambda d: d.name.casefold()):
                current = self.current_source(dest)
                if current is not None and current not in sources:
                    sources[current] = self._source_dict(key, current, False, None, None, None)
                ent = ent_reg.async_get(dest.entity_id) if dest.entity_id else None
                destinations.append(
                    {
                        "id": dest.uid,
                        "entity_id": dest.entity_id,
                        "name": dest.name,
                        "channel": dest.channel_name,
                        "device_name": dest.device_name,
                        "device_id": ent.device_id if ent else None,
                        "entry_id": dest.entry_id,
                        "driver": dest.coordinator.driver.KEY,
                        "protocol": key,
                        "current_source": current,
                        "current_source_live": registry.is_live(current),
                        "status": self.connection_state(dest).value,
                        "resolution": self.resolution(dest),
                        "available": dest.coordinator.last_update_success,
                        "locked": dest.uid in self.locks,
                        "can_undo": bool(self.history.get(dest.uid)),
                        "display": display_state(self.hass, self.display_config(dest), dest.display_error),
                    }
                )
            if destinations or sources:
                out["protocols"][key] = {
                    "title": proto.title,
                    "sources": sorted(sources.values(), key=lambda s: s["name"].casefold()),
                    "destinations": destinations,
                }
        return out

    def _source_dict(
        self,
        protocol: str,
        source_id: str,
        live: bool,
        address: str | None,
        last_seen: float | None,
        first_seen: float | None,
    ) -> dict[str, Any]:
        lab = self.label(protocol, source_id)
        host = address.rsplit(":", 1)[0] if address and ":" in address else address
        return {
            "id": source_id,
            "name": lab.get("label") or source_id,
            "label": lab.get("label"),
            "tags": list(lab.get("tags", [])),
            "live": live,
            "host": host,
            "address": address,
            "last_seen": _iso(last_seen),
            "first_seen": _iso(first_seen),
        }


DATA_HUB: HassKey[AvMatrixHub] = HassKey(DOMAIN)
