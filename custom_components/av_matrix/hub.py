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

from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
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
    PROTOCOL_DANTE,
    RECENT_SIZE,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .device_icons import icon_key
from .display import async_drive_display, display_state
from .drivers import DriverError
from .drivers.base import short
from .models import ConnectionState
from .protocols import PROTOCOLS, SourceRegistry, tcp_probe
from .protocols.base import natural_key

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
    #: Sub-device of a network entry (Dante: the Dante device name), None = the entry's device.
    device_key: str | None = None
    entity_id: str | None = None
    last_route: float = 0.0
    display_error: str | None = None

    @property
    def entry_id(self) -> str:
        return self.coordinator.config_entry.entry_id

    @property
    def device_name(self) -> str:
        return self.device_key or self.coordinator.device_name

    @property
    def available(self) -> bool:
        """Device reachable (network entries: the sub-device of this destination)."""
        return self.coordinator.last_update_success and self.coordinator.driver.destination_available(self.dest_id)

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
        #: user labels of destinations, by destination id
        self.destination_labels: dict[str, dict[str, Any]] = {}
        self.history: dict[str, deque[str | None]] = {}
        #: recently seen/assigned sources per destination (Dante: offline sources stay selectable)
        self.recent: dict[str, deque[str]] = {}
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._eval_pending = False
        self._browsers: list[Any] = []
        # one route at a time per destination (double taps, salvo + service …): keeps "previous",
        # the undo history and BirdDog's read-back verification consistent
        self._route_locks: dict[str, asyncio.Lock] = {}

    # ---------------------------------------------------------------- lifecycle
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.locks = set(data.get("locks", []))
        self.labels = data.get("labels", {})
        self.destination_labels = data.get("destination_labels", {})

    async def async_start(self) -> None:
        """Start discovery and periodic liveness evaluation (first config entry)."""
        if self._unsubs:
            return
        from .discovery import NdiMdnsBrowser

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
        self._store.async_delay_save(
            lambda: {
                "locks": sorted(self.locks),
                "labels": self.labels,
                "destination_labels": self.destination_labels,
            },
            1,
        )

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
        self._route_locks.pop(uid, None)
        self.recent.pop(uid, None)

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
        text = text.strip()
        if protocol == PROTOCOL_DANTE:
            # Dante subscribes to unknown/offline devices too (state "unresolved"), but the format must fit
            channel, sep, device = text.rpartition("@")
            if not sep or not channel.strip() or not device.strip() or "@" in channel:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_dante_source",
                    translation_placeholders={"source": text},
                )
        return text  # unknown names are allowed (source may not be discovered yet / offline)

    def remember(self, dest: Destination, source: str | None) -> None:
        """Keep ``source`` selectable for ``dest`` even after it left the registry."""
        if source is None:
            return
        recent = self.recent.setdefault(dest.uid, deque(maxlen=RECENT_SIZE))
        if source in recent:
            recent.remove(source)
        recent.append(source)

    def recent_sources(self, dest: Destination) -> list[str]:
        """Sources offered for ``dest`` beyond the registry: current, recently seen/assigned, undo history."""
        known = {r.id for r in self.registries[dest.protocol].sources}
        current = self.current_source(dest)
        extra = [current] if current is not None else []
        if dest.protocol == PROTOCOL_DANTE:
            self.remember(dest, current)
            extra += reversed(self.recent.get(dest.uid, ()))
            extra += [s for s in reversed(self.history.get(dest.uid, ())) if s is not None]
        seen: set[str] = set()
        return [s for s in extra if s not in known and not (s in seen or seen.add(s))]

    def options(self, dest: Destination) -> list[str]:
        registry = self.registries[dest.protocol]
        names = [self.display_name(dest.protocol, r.id) for r in registry.sources]
        names += [self.display_name(dest.protocol, s) for s in self.recent_sources(dest)]
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
        return state.status.resolution if state and dest.available else None

    def status_extra(self, dest: Destination) -> dict[str, Any]:
        data = dest.coordinator.data
        state = data.destinations.get(dest.dest_id) if data else None
        return dict(state.status.extra) if state and dest.available else {}

    def connection_state(self, dest: Destination) -> ConnectionState:
        coordinator = dest.coordinator
        data = coordinator.data
        if not dest.available or data is None or dest.dest_id not in data.destinations:
            return ConnectionState.OFFLINE
        current = self.current_source(dest)
        if current is None:
            return ConnectionState.NO_SOURCE
        status = data.destinations[dest.dest_id].status
        connected = status.connected
        recent = time.monotonic() - dest.last_route < max(CONNECTING_GRACE, coordinator.driver.SETTLE_TIME)
        if status.state is not None:  # the device tells us exactly (Dante subscription status)
            if status.state in (ConnectionState.SOURCE_LOST, ConnectionState.ERROR) and recent:
                return ConnectionState.CONNECTING
            if status.state is ConnectionState.NO_SOURCE:  # poll predates the route
                return ConnectionState.CONNECTING
            return status.state
        if connected is True:
            return ConnectionState.CONNECTED
        live = self.registries[dest.protocol].is_live(current)
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
        self,
        uid: str,
        source: str | None,
        *,
        record_history: bool = True,
        origin: str = "service",
        context: Context | None = None,
    ) -> None:
        """Route ``source`` (registry id, None = off) to destination ``uid``."""
        dest = self._get(uid)
        self._check_unlocked(dest)
        await self._async_route(dest, source, record_history=record_history, origin=origin, context=context)

    async def _async_route(
        self,
        dest: Destination,
        source: str | None,
        *,
        record_history: bool,
        origin: str,
        context: Context | None = None,
    ) -> None:
        async with self._route_locks.setdefault(dest.uid, asyncio.Lock()):
            await self._async_route_locked(dest, source, record_history=record_history, origin=origin, context=context)

    async def _async_route_locked(
        self,
        dest: Destination,
        source: str | None,
        *,
        record_history: bool,
        origin: str,
        context: Context | None = None,
    ) -> None:
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
        if dest.protocol == PROTOCOL_DANTE:
            self.remember(dest, previous)
            self.remember(dest, source)
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
            context=context,
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

    async def async_salvo(
        self, routes: Iterable[tuple[str, str | None]], *, origin: str = "salvo", context: Context | None = None
    ) -> None:
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
                    await self._async_route(dest, source, record_history=True, origin=origin, context=context)
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

    async def async_undo(self, uid: str, *, context: Context | None = None) -> None:
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
            await self._async_route(dest, previous, record_history=False, origin="undo", context=context)
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

    @staticmethod
    def _label_entry(label: str | None, tags: list[str] | None) -> dict[str, Any]:
        entry: dict[str, Any] = {}
        if label and label.strip():
            entry["label"] = label.strip()
        if tags:
            entry["tags"] = sorted({t.strip() for t in tags if t and t.strip()})
        return entry

    @callback
    def async_set_label(self, protocol: str, source_id: str, label: str | None, tags: list[str] | None) -> None:
        if protocol not in self.registries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_protocol")
        entry = self._label_entry(label, tags)
        labels = self.labels.setdefault(protocol, {})
        if entry:
            labels[source_id] = entry
        else:
            labels.pop(source_id, None)
        self._save()
        self.async_notify()

    def destination_label(self, uid: str) -> dict[str, Any]:
        return self.destination_labels.get(uid, {})

    @callback
    def async_set_destination_label(self, uid: str, label: str | None, tags: list[str] | None) -> None:
        """Set (or clear) the user label of a destination. Entity names are not touched."""
        self._get(uid)
        entry = self._label_entry(label, tags)
        if entry:
            self.destination_labels[uid] = entry
        else:
            self.destination_labels.pop(uid, None)
        self._save()
        self.async_notify()

    def destination_icon(self, dest: Destination) -> str:
        """Illustration key of the device behind ``dest`` (see device_icons.py)."""
        manufacturer, model = self._device_model(dest.coordinator, dest.device_key)
        return icon_key(
            protocol=dest.protocol,
            driver=dest.coordinator.driver.KEY,
            manufacturer=manufacturer,
            model=model,
            name=dest.device_name,
        )

    def source_icon(self, protocol: str, source_id: str, group: str | None) -> str:
        """Illustration key of a source (Dante: its TX device; NDI: guessed from the name)."""
        manufacturer = model = None
        if group:
            for dest in self.destinations.values():
                if dest.protocol == protocol and hasattr(dest.coordinator.driver, "device_for"):
                    manufacturer, model = self._device_model(dest.coordinator, group)
                    break
        return icon_key(
            protocol=protocol,
            manufacturer=manufacturer,
            model=model,
            name=group or source_id,
            role="source",
        )

    @staticmethod
    def _device_model(coordinator: AvMatrixCoordinator, device_key: str | None) -> tuple[str | None, str | None]:
        if device_key is not None:
            driver = coordinator.driver
            dev = driver.device_for(device_key) if hasattr(driver, "device_for") else None
            return (dev.manufacturer, dev.model) if dev else (None, None)
        info = coordinator.info
        return info.manufacturer, info.model

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
            for dest in sorted(dests, key=lambda d: (natural_key(d.device_name), natural_key(d.name))):
                current = self.current_source(dest)
                if current is not None and current not in sources:
                    sources[current] = self._source_dict(key, current, False, None, None, None)
                ent = ent_reg.async_get(dest.entity_id) if dest.entity_id else None
                lab = self.destination_label(dest.uid)
                manufacturer, model = self._device_model(dest.coordinator, dest.device_key)
                destinations.append(
                    {
                        "id": dest.uid,
                        "entity_id": dest.entity_id,
                        "name": lab.get("label") or dest.name,
                        "label": lab.get("label"),
                        "original_name": dest.name,
                        "tags": list(lab.get("tags", [])),
                        "channel": dest.channel_name,
                        "device_name": dest.device_name,
                        "group": dest.device_key,
                        "device_id": ent.device_id if ent else None,
                        "entry_id": dest.entry_id,
                        "driver": dest.coordinator.driver.KEY,
                        "manufacturer": manufacturer,
                        "model": model,
                        "icon_key": self.destination_icon(dest),
                        "protocol": key,
                        "current_source": current,
                        "current_source_live": registry.is_live(current),
                        "status": self.connection_state(dest).value,
                        "resolution": self.resolution(dest),
                        "subscription": self._subscription(dest),
                        "available": dest.available,
                        "locked": dest.uid in self.locks,
                        "can_undo": bool(self.history.get(dest.uid)),
                        "display": display_state(self.hass, self.display_config(dest), dest.display_error),
                    }
                )
            if destinations or sources:
                out["protocols"][key] = {
                    "title": proto.title,
                    "sources": sorted(
                        sources.values(),
                        key=lambda s: registry.sort_key(s["id"]) if registry.grouped else natural_key(s["name"]),
                    ),
                    "destinations": destinations,
                }
        return out

    def _subscription(self, dest: Destination) -> dict[str, Any] | None:
        """Dante: state/code/status/detail of the RX subscription; None for other protocols."""
        extra = self.status_extra(dest)
        if "subscription" not in extra:
            return None
        return {
            "state": extra["subscription"],
            "code": extra.get("subscription_code"),
            "status": extra.get("subscription_status"),
            "detail": extra.get("subscription_detail"),
        }

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
        described = self.registries[protocol].describe(source_id)
        return {
            "id": source_id,
            **described,
            "name": lab.get("label") or source_id,
            "label": lab.get("label"),
            "original_name": source_id,
            "icon_key": self.source_icon(protocol, source_id, described.get("group")),
            "tags": list(lab.get("tags", [])),
            "live": live,
            "host": host,
            "address": address,
            "last_seen": _iso(last_seen),
            "first_seen": _iso(first_seen),
        }


DATA_HUB: HassKey[AvMatrixHub] = HassKey(DOMAIN)
