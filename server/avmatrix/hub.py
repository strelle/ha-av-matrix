"""Der Kern: Geräte, Quellenregister, Ziele, Schalten, Sperren, Undo, Labels, Presets, Sperrliste.

Portiert aus ``hub.py`` / ``coordinator.py`` der Home-Assistant-Variante, von Home Assistant gelöst. Der Schnappschuss (``snapshot``) hat dasselbe Format wie dort
(docs/frontend-api.md), erweitert um ``protected``, ``presets`` und ``server``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import aiohttp

from . import __version__
from .device_icons import icon_key as _icon_key
from .drivers import DRIVERS, Driver, DriverError, InvalidAuth
from .drivers.base import short
from .drivers.dante import CONF_STATIC_HOSTS, split_dest
from .guard import Guard, GuardedDanteNetwork, ProtectionRule
from .models import ConnectionState, DestinationState, DestinationStatus, DeviceInfo, DevicePoll
from .protocols import PROTOCOLS, SourceRegistry, tcp_probe
from .protocols.base import natural_key
from .source_types import IPV4, classify, split_name
from .source_types import TYPES as SOURCE_TYPES
from .store import JsonFile

_LOGGER = logging.getLogger(__name__)

NONE_OPTION = "None"
HISTORY_SIZE = 10
RECENT_SIZE = 5
ACTIONS_SIZE = 20
EVENTS_SIZE = 50
CONNECTING_GRACE = 10.0
EVALUATE_INTERVAL = 5.0
DEFAULT_SCAN_INTERVAL = 5.0
MIN_SCAN_INTERVAL = 2.0
MAX_SCAN_INTERVAL = 60.0
MAX_BACKOFF = 30.0
REQUEST_TIMEOUT = 3.0
#: Abstände der Nach-Abfragen nach dem Schalten (→ 1,5 / 3 / 5 / 8 / 12 s), bis das Gerät "verbunden" meldet.
FOLLOWUP_DELAYS: tuple[float, ...] = (1.5, 1.5, 2.0, 3.0, 4.0)
PROTOCOL_DANTE = "dante"
#: Optionen von Netzwerk-Einträgen, die über die Schnittstelle sichtbar und änderbar sind
NETWORK_OPTIONS = ("static_hosts", "registries", "audio_breakaway", "check_compat", "enable_senders", "hidden_devices", "scan_interval")


class MatrixError(Exception):
    """Fehler mit Code (für HTTP-Status / MCP) und deutschem Klartext."""

    STATUS = {
        "unknown_destination": 404,
        "unknown_preset": 404,
        "unknown_device": 404,
        "ambiguous": 409,
        "locked": 423,
        "protected": 403,
        "offline": 503,
        "route_failed": 502,
        "nothing_to_undo": 409,
        "invalid": 400,
    }

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def status(self) -> int:
        return self.STATUS.get(self.code, 400)


@lru_cache(maxsize=2048)
def _icon_cached(protocol: str, driver: str | None, manufacturer: str | None, model: str | None, name: str | None, role: str) -> str:
    return _icon_key(protocol=protocol, driver=driver, manufacturer=manufacturer, model=model, name=name, role=role)


def icon_key(*, protocol: str, driver: str | None = None, manufacturer: str | None = None, model: str | None = None,
             name: str | None = None, role: str = "destination") -> str:  # fmt: skip
    """Wie ``device_icons.icon_key``, aber gemerkt (die Regeln sind reguläre Ausdrücke und laufen sonst je Abfrage)."""
    return _icon_cached(protocol, driver, manufacturer, model, name, role)


def slugify(text: str, fallback: str = "x") -> str:
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = text.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or fallback


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts else None


@dataclass(slots=True)
class Entry:
    """Ein eingerichtetes Gerät (oder ein ganzes Netzwerk, z. B. Dante)."""

    id: str
    driver: str
    title: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "driver": self.driver, "title": self.title, "data": self.data, "options": self.options}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Entry:
        return cls(
            id=str(raw["id"]),
            driver=str(raw["driver"]),
            title=raw.get("title") or None,
            data=dict(raw.get("data") or {}),
            options=dict(raw.get("options") or {}),
        )


class Poller:
    """Fragt ein Gerät regelmäßig ab; wartet länger (bis 30 s), solange es nicht antwortet."""

    def __init__(self, hub: Hub, entry: Entry, driver: Driver) -> None:
        self.hub = hub
        self.entry = entry
        self.driver = driver
        self.info = DeviceInfo()
        self.info_ok = False
        self.data: DevicePoll | None = None
        self.last_update_success = False
        self.last_error: str | None = None
        self.auth_failed = False
        interval = float(entry.options.get("scan_interval") or hub.scan_interval)
        self.interval = max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, interval))
        self.polls = 0
        self.last_poll = 0.0  # Zeitpunkt der letzten Abfrage (time.time)
        self._failures = 0
        self._task: asyncio.Task[None] | None = None
        self._followup: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._settling: set[str] = set()
        self._route_seq = 0
        self._optimistic: dict[str, tuple[int, str | None]] = {}

    @property
    def device_name(self) -> str:
        return self.entry.title or self.info.name or self.driver.host

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"avm poll {self.entry.id}")

    async def stop(self) -> None:
        for task in (self._task, self._followup):
            if task is not None:
                task.cancel()
        for task in (self._task, self._followup):
            if task is not None:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = self._followup = None
        self.driver.close()

    async def _run(self) -> None:
        while True:
            await self.refresh()
            delay = min(MAX_BACKOFF, self.interval * (2**self._failures)) if self._failures else self.interval
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except TimeoutError:
                pass
            self._wake.clear()

    def wake(self) -> None:
        self._wake.set()

    async def refresh(self) -> None:
        async with self._lock:
            registry = self.hub.registries[self.driver.PROTOCOL]
            seq = self._route_seq
            self.polls += 1
            self.last_poll = time.time()
            try:
                if not self.info_ok:
                    self.info = await self.driver.async_get_info()
                    self.info_ok = True
                poll = await self.driver.async_poll()
            except Exception as err:  # noqa: BLE001 - ein Gerät darf den Server nie mitreißen
                if not isinstance(err, DriverError):
                    _LOGGER.exception("Unerwarteter Fehler bei %s", self.device_name)
                changed = self.last_update_success or self.last_error is None
                if self.last_update_success:
                    _LOGGER.info("%s antwortet nicht mehr: %s", self.device_name, short(err))
                self.auth_failed = isinstance(err, InvalidAuth)
                self._failures = min(self._failures + 1, 6)
                self.last_update_success = False
                self.last_error = short(err)
                registry.remove_device(self.entry.id)
                self.hub.schedule_evaluate()
                if changed:
                    self.hub.notify()
                return
            if self._failures:
                _LOGGER.info("%s ist wieder erreichbar", self.device_name)
            self._failures = 0
            self.auth_failed = False
            self.last_error = None
            for dest_id, (route_seq, device_source) in list(self._optimistic.items()):
                if route_seq <= seq:  # diese Abfrage begann nach dem Schalten → sie ist die Wahrheit
                    del self._optimistic[dest_id]
                    continue
                state = poll.destinations.setdefault(dest_id, DestinationState())
                if state.current != device_source:
                    state.current = device_source
                    state.status = DestinationStatus(connected=False)
            self.data = poll
            self.last_update_success = True
            registry.set_device_sightings(self.entry.id, poll.sources, self.driver.TRUSTED_SOURCE_LIST)
            self.hub.sync_destinations(self)
            self.hub.schedule_evaluate()
            self.hub.notify()

    def set_current(self, dest_id: str, device_source: str | None) -> None:
        """Optimistische Aktualisierung direkt nach erfolgreichem Schalten."""
        self._route_seq += 1
        self._optimistic[dest_id] = (self._route_seq, device_source)
        self._settling.add(dest_id)
        if self.data is None:
            return
        state = self.data.destinations.setdefault(dest_id, DestinationState())
        state.current = device_source
        state.status = DestinationStatus(connected=False)

    def _settled(self) -> bool:
        if not self.last_update_success or self.data is None:
            return False
        for dest_id in self._settling:
            state = self.data.destinations.get(dest_id)
            if state is None:
                return False
            if state.current is not None and not (state.status.connected and state.status.resolution):
                return False
        return True

    def refresh_after_route(self) -> None:
        if self._followup is not None:
            self._followup.cancel()
        self._followup = asyncio.create_task(self._followups(), name=f"avm settle {self.entry.id}")

    async def _followups(self) -> None:
        try:
            await self.refresh()
            for delay in FOLLOWUP_DELAYS:
                await asyncio.sleep(delay)
                await self.refresh()
                if self._settled():
                    break
            self._settling.clear()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Nach-Abfrage von %s fehlgeschlagen", self.device_name)


@dataclass(slots=True, eq=False)
class Destination:
    """Ein schaltbares Ziel (Decoder-Ausgang, Empfangskanal …)."""

    uid: str
    dest_id: str
    protocol: str
    poller: Poller
    channel_name: str | None = None
    device_key: str | None = None  # Dante: Name des Dante-Geräts
    last_route: float = 0.0

    @property
    def entry_id(self) -> str:
        return self.poller.entry.id

    @property
    def device_name(self) -> str:
        return self.device_key or self.poller.device_name

    @property
    def available(self) -> bool:
        return self.poller.last_update_success and self.poller.driver.destination_available(self.dest_id)

    @property
    def name(self) -> str:
        return f"{self.device_name} · {self.channel_name}" if self.channel_name else self.device_name

    @property
    def host(self) -> str | None:
        return self.poller.driver.destination_host(self.dest_id)

    @property
    def web_url(self) -> str | None:
        return self.poller.driver.destination_url(self.dest_id)

    @property
    def channel_number(self) -> int | None:
        if self.protocol == PROTOCOL_DANTE:
            try:
                return split_dest(self.dest_id)[1]
            except DriverError:
                return None
        return int(self.dest_id) if self.dest_id.isdigit() else None


class Hub:
    """Gemeinsamer Zustand aller Geräte."""

    def __init__(
        self,
        config: JsonFile,
        state: JsonFile,
        *,
        session: aiohttp.ClientSession | None = None,
        driver_factory: Callable[[Entry], Driver] | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.version = __version__
        self.session = session
        self._driver_factory = driver_factory
        self.registries: dict[str, SourceRegistry] = {key: proto.registry(tcp_probe) for key, proto in PROTOCOLS.items()}
        self.entries: dict[str, Entry] = {}
        self.pollers: dict[str, Poller] = {}
        self.destinations: dict[str, Destination] = {}
        self.guard = Guard()
        self.scan_interval = DEFAULT_SCAN_INTERVAL
        self.locks: set[str] = set()
        self.labels: dict[str, dict[str, dict[str, Any]]] = {}
        self.destination_labels: dict[str, dict[str, Any]] = {}
        self.presets: dict[str, dict[str, Any]] = {}
        self.history: dict[str, deque[str | None]] = {}
        self.recent: dict[str, deque[str]] = {}
        #: letzte Aktionen (eine Aktion = eine oder mehrere Umschaltungen) für "letzte Aktion rückgängig"
        self.actions: deque[dict[str, Any]] = deque(maxlen=ACTIONS_SIZE)
        self.events: deque[dict[str, Any]] = deque(maxlen=EVENTS_SIZE)
        self._listeners: list[Callable[[], None]] = []
        self._event_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._eval_pending = False
        self._eval_task: asyncio.Task[None] | None = None
        self._route_locks: dict[str, asyncio.Lock] = {}
        self._action_seq = 0
        #: zählt jede Änderung; Schnappschüsse werden je Stand nur einmal gebaut und von allen Zuhörern geteilt
        self.revision = 0
        #: Weboberflächen der Quellgeräte: Adresse → {url, hint, at}; füllt ``probe_source_hosts``
        self.source_web: dict[str, dict[str, Any]] = {}
        #: früherer Name → heutiger Name von Quellen, deren Gerätename nur ihre IP-Adresse ist
        self.source_aliases: dict[str, str] = {}
        self._memo: dict[str, Any] = {}
        self.started = time.time()
        #: Haken für die mDNS-Suche: neu gestartete Treiber bekommen bereits gesehene Geräte
        self.on_poller: Callable[[Poller], None] | None = None
        #: liefert den Abschnitt ``preview`` des Schnappschusses (setzt der Start, wenn es eine Vorschau gibt)
        self.preview_info: Callable[[], dict[str, Any]] | None = None

    # ---------------------------------------------------------------- lifecycle
    def load(self) -> None:
        cfg = self.config.load()
        st = self.state.load()
        self.guard = Guard.from_config(cfg.get("protected"))
        if "protected" not in cfg:  # Schlüssel sichtbar machen, damit man die Sperrliste in der Datei findet
            cfg["protected"] = []
            self.config.save_now()
        for rule in self.guard.rules:
            _LOGGER.info("Sperrliste: %s", rule.reason)
        if not self.guard.rules:
            _LOGGER.info("Sperrliste: keine Regeln (config.json → protected)")
        self.scan_interval = float(cfg.get("scan_interval") or DEFAULT_SCAN_INTERVAL)
        self.entries = {}
        for raw in cfg.get("devices") or []:
            try:
                entry = Entry.from_dict(raw)
            except (KeyError, TypeError) as err:
                _LOGGER.error("Ungültiger Geräteeintrag übersprungen: %s", err)
                continue
            if entry.driver in DRIVERS:
                self.entries[entry.id] = entry
        # ST 2110 „einstecken und es ist da“: der Netzwerk-Eintrag wird einmal von selbst angelegt. Ohne Geräte
        # kostet er nichts und bleibt unsichtbar. Wer ihn entfernt, bekommt ihn nicht wieder (Merker).
        if "nmos" in DRIVERS and "nmos" not in self.entries and cfg.get("nmos_auto", True) is True:
            self.entries["nmos"] = Entry("nmos", "nmos", "ST 2110", {"host": "nmos"}, {})
            cfg["nmos_auto"] = "angelegt"
            self._save_config()
        self.locks = set(st.get("locks") or [])
        self.labels = st.get("labels") or {}
        self.destination_labels = st.get("destination_labels") or {}
        self.presets = {p["id"]: p for p in st.get("presets") or [] if isinstance(p, dict) and p.get("id")}
        self.source_aliases = dict(st.get("source_aliases") or {})
        hold = cfg.get("source_hold_seconds")
        if hold:  # so lange bleiben verschwundene Quellen als "offline" in den Listen (Vorgabe 120 s)
            for registry in self.registries.values():
                registry.hold_time = float(hold)

    async def start(self) -> None:
        for entry in self.entries.values():
            self._start_entry(entry)
        self._eval_task = asyncio.create_task(self._periodic(), name="avm evaluate")

    async def stop(self) -> None:
        if self._eval_task is not None:
            self._eval_task.cancel()
        await asyncio.gather(*(p.stop() for p in self.pollers.values()), return_exceptions=True)
        self.pollers.clear()
        for store in (self.config, self.state):
            if store._handle is not None:
                store.save_now()

    def _make_driver(self, entry: Entry) -> Driver:
        if self._driver_factory is not None:
            driver = self._driver_factory(entry)
        elif entry.driver == PROTOCOL_DANTE:
            driver = GuardedDanteNetwork(self.session, entry.data, options=entry.options)
        elif DRIVERS[entry.driver].NETWORK:  # jeder Netzwerk-Treiber (z. B. NMOS / ST 2110) bekommt seine Optionen
            driver = DRIVERS[entry.driver](self.session, entry.data, options=entry.options)  # type: ignore[call-arg]
        else:
            driver = DRIVERS[entry.driver](self.session, entry.data, timeout=REQUEST_TIMEOUT)  # type: ignore[arg-type]
        if isinstance(driver, GuardedDanteNetwork):
            driver.guard = self.guard
        return driver

    def _start_entry(self, entry: Entry) -> Poller:
        poller = Poller(self, entry, self._make_driver(entry))
        self.pollers[entry.id] = poller
        if self.on_poller is not None:
            self.on_poller(poller)
        self.sync_destinations(poller)
        poller.start()
        return poller

    def _save_config(self) -> None:
        self.config.data["devices"] = [e.as_dict() for e in self.entries.values()]
        self.config.save()

    def _save_state(self) -> None:
        self.state.data.update(
            {
                "locks": sorted(self.locks),
                "labels": self.labels,
                "destination_labels": self.destination_labels,
                "presets": list(self.presets.values()),
                "source_aliases": self.source_aliases,
            }
        )
        self.state.save()

    # ---------------------------------------------------------- notifications
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def add_event_listener(self, listener: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._event_listeners.append(listener)

        def remove() -> None:
            if listener in self._event_listeners:
                self._event_listeners.remove(listener)

        return remove

    def notify(self) -> None:
        self.revision += 1
        self._memo.clear()
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Listener fehlgeschlagen")

    # ------------------------------------------------------------- registries
    async def _periodic(self) -> None:
        while True:
            await asyncio.sleep(EVALUATE_INTERVAL)
            try:
                await self.evaluate()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Quellenprüfung fehlgeschlagen")

    async def evaluate(self) -> None:
        changed = False
        for registry in self.registries.values():
            changed |= await registry.async_evaluate()
        if self.follow_renamed_sources() or changed:
            self.notify()
        await self.probe_source_hosts()

    def follow_renamed_sources(self) -> bool:
        """Geräte, die ihre IP als Namen tragen („192.0.2.7 (AUX1)“), heißen nach einem Adresswechsel anders.

        Erscheint so eine Quelle unter neuer Adresse und ist die mit demselben Kanalnamen unter der alten nicht
        mehr da, gilt sie als dasselbe Gerät: Presets und Labels ziehen um, der alte Name bleibt als Alias gültig
        (Companion-Tasten, HTTP, MCP), der alte Eintrag verschwindet.
        """
        registry = self.registries["ndi"]
        by_channel: dict[str, list[Any]] = {}
        for rec in registry.sources:
            machine, channel = split_name(rec.id)
            if channel and IPV4.match(machine):
                by_channel.setdefault(channel.casefold(), []).append(rec)
        changed = False
        for records in by_channel.values():
            live = [r for r in records if r.live]
            gone = [r for r in records if not r.live]
            if len(live) != 1 or not gone:
                continue  # mehrere Geräte mit demselben Kanalnamen: nichts zusammenlegen
            new = live[0].id
            for old in (r.id for r in gone):
                self.source_aliases[old] = new
                for alias, target in list(self.source_aliases.items()):
                    if target == old:
                        self.source_aliases[alias] = new
                for preset in self.presets.values():
                    for route in preset.get("routes", []):
                        if route.get("source") == old:
                            route["source"] = new
                labels = self.labels.get("ndi", {})
                if old in labels and new not in labels:
                    labels[new] = labels.pop(old)
                registry._records.pop(old, None)
                _LOGGER.info("Quelle %s heißt jetzt %s (gleiches Gerät, neue Adresse)", old, new)
                changed = True
        self.source_aliases.pop(next((a for a, t in self.source_aliases.items() if a == t), ""), None)
        if changed:
            self._save_state()
        return changed

    def forget_source(self, protocol: str, source_id: str) -> None:
        """Eine Quelle, die nicht mehr sendet, sofort aus den Listen nehmen."""
        registry = self.registries.get(protocol)
        if registry is None:
            raise MatrixError("invalid", f"Unbekanntes Protokoll {protocol!r}")
        record = registry.get(source_id)
        if record is not None and record.live:
            raise MatrixError("invalid", "Diese Quelle sendet gerade – sie lässt sich nicht vergessen.")
        users = [self.dest_title(d) for d in self.destinations.values() if d.protocol == protocol and self.current_source(d) == source_id]
        if users:
            raise MatrixError("invalid", f"Noch zugewiesen an: {', '.join(users)} – dort zuerst eine andere Quelle wählen.")
        registry._records.pop(source_id, None)
        registry._discovered.pop(source_id, None)
        self.labels.get(protocol, {}).pop(source_id, None)
        self._save_state()
        self.notify()

    async def probe_source_hosts(self) -> None:
        """Hat das Gerät hinter einer NDI-Quelle eine Weboberfläche? Einmal je Adresse fragen (nur lesend)."""
        if self.session is None:
            return
        now = time.monotonic()
        own = {"127.0.0.1"} | {str(e.data.get("host")) for e in self.entries.values()}
        hosts = {r.host for r in self.registries["ndi"].sources if r.live and r.host and r.host not in own}
        todo = [h for h in hosts if h not in self.source_web or now - self.source_web[h]["at"] > 900]
        if not todo:
            return
        for host in todo:
            self.source_web[host] = {"url": None, "hint": None, "at": now}
        results = await asyncio.gather(*(self._probe_web(h) for h in todo[:8]), return_exceptions=True)
        if any(r is True for r in results):
            self.notify()

    async def _probe_web(self, host: str) -> bool:
        try:
            async with self.session.get(f"http://{host}/", timeout=aiohttp.ClientTimeout(total=2.5), allow_redirects=True, max_redirects=3) as resp:
                if resp.status >= 400:
                    return False
                body = (await resp.content.read(4096)).decode("utf-8", errors="replace")
                title = re.search(r"<title[^>]*>([^<]{1,80})", body, re.IGNORECASE)
                hint = " ".join(filter(None, [title.group(1).strip() if title else "", resp.headers.get("Server", "")]))[:120]
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError):
            return False
        self.source_web[host].update({"url": f"http://{host}/", "hint": hint or None})
        return True

    def schedule_evaluate(self) -> None:
        if self._eval_pending:
            return
        self._eval_pending = True

        async def run() -> None:
            await asyncio.sleep(0)
            self._eval_pending = False
            await self.evaluate()

        try:
            asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            self._eval_pending = False

    # ----------------------------------------------------------- devices
    def sync_destinations(self, poller: Poller) -> None:
        """Ziele eines Geräts mit dem abgleichen, was der Treiber gerade kennt (Dante: ändert sich laufend)."""
        wanted = {f"{poller.entry.id}_{d.id}": d for d in poller.driver.destinations()}
        for uid in [u for u, d in self.destinations.items() if d.poller is poller and u not in wanted]:
            if poller.driver.NETWORK:  # Einzelgeräte behalten ihre Ziele, auch wenn sie offline sind
                self.destinations.pop(uid, None)
                self._route_locks.pop(uid, None)
        for uid, info in wanted.items():
            dest = self.destinations.get(uid)
            if dest is None:
                self.destinations[uid] = Destination(
                    uid, info.id, poller.driver.PROTOCOL, poller, info.name, device_key=info.device
                )
                self.history.setdefault(uid, deque(maxlen=HISTORY_SIZE))
            else:
                dest.channel_name = info.name

    def configured_hosts(self) -> set[str]:
        return {str(e.data.get("host", "")).strip().lower() for e in self.entries.values() if e.data.get("host")}

    def unique_entry_id(self, base: str) -> str:
        base = slugify(base, "geraet")
        candidate, n = base, 2
        while candidate in self.entries:
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    async def validate_device(self, driver_key: str, data: dict[str, Any]) -> DeviceInfo:
        """Verbindung testen (wirft InvalidAuth / CannotConnect)."""
        driver = DRIVERS[driver_key](self.session, data, timeout=REQUEST_TIMEOUT)  # type: ignore[arg-type]
        try:
            return await driver.async_get_info()
        finally:
            driver.close()

    def add_entry(
        self,
        driver_key: str,
        data: dict[str, Any],
        *,
        title: str | None = None,
        options: dict[str, Any] | None = None,
        info: DeviceInfo | None = None,
    ) -> Entry:
        if driver_key not in DRIVERS:
            raise MatrixError("invalid", f"Unbekannter Gerätetyp {driver_key!r}")
        cls = DRIVERS[driver_key]
        if cls.NETWORK:
            entry_id = driver_key
            if entry_id in self.entries:
                raise MatrixError("invalid", "Dieses Netzwerk ist bereits eingerichtet.")
        else:
            host = str(data.get("host") or "").strip()
            if not host:
                raise MatrixError("invalid", "Adresse (host) fehlt")
            if host.lower() in self.configured_hosts():
                raise MatrixError("invalid", "Dieses Gerät ist bereits eingerichtet.")
            serial = (info.serial if info else None) or host
            entry_id = self.unique_entry_id(f"{driver_key}-{serial}")
        entry = Entry(entry_id, driver_key, title or (info.name if info else None), dict(data), dict(options or {}))
        self.entries[entry.id] = entry
        self._save_config()
        poller = self._start_entry(entry)
        if info is not None and not cls.NETWORK:
            poller.info, poller.info_ok = info, True
        self.notify()
        return entry

    async def remove_entry(self, entry_id: str) -> None:
        entry = self.entries.pop(entry_id, None)
        if entry is None:
            raise MatrixError("unknown_device", f"Unbekanntes Gerät {entry_id!r}")
        poller = self.pollers.pop(entry_id, None)
        if poller is not None:
            await poller.stop()
            for uid in [u for u, d in self.destinations.items() if d.poller is poller]:
                self.destinations.pop(uid, None)
                self._route_locks.pop(uid, None)
                self.recent.pop(uid, None)
        self.registries[DRIVERS[entry.driver].PROTOCOL].remove_device(entry_id)
        self._save_config()
        self.schedule_evaluate()
        self.notify()

    async def update_entry(self, entry_id: str, *, title: Any = ..., options: dict[str, Any] | None = None) -> Entry:
        entry = self.entries.get(entry_id)
        if entry is None:
            raise MatrixError("unknown_device", f"Unbekanntes Gerät {entry_id!r}")
        if title is not ...:
            entry.title = (str(title).strip() or None) if title else None
        if options is not None:
            entry.options.update(options)
            poller = self.pollers.pop(entry_id, None)  # Optionen wirken beim Neustart des Treibers
            if poller is not None:
                await poller.stop()
                for uid in [u for u, d in self.destinations.items() if d.poller is poller]:
                    self.destinations.pop(uid, None)
            self._start_entry(entry)
        self._save_config()
        self.notify()
        return entry

    def forget_network_device(self, entry_id: str, name: str) -> None:
        """Ein Gerät eines Netzwerk-Eintrags (Dante, ST 2110) aus der Liste nehmen, solange es nicht antwortet.

        Meldet es sich wieder (mDNS, Registry), erscheint es von selbst erneut; eine von Hand eingetragene
        Adresse wird mit entfernt.
        """
        poller = self.pollers.get(entry_id)
        entry = self.entries.get(entry_id)
        if poller is None or entry is None or not poller.driver.NETWORK:
            raise MatrixError("unknown_device", f"Unbekanntes Netzwerk {entry_id!r}")
        devices = getattr(poller.driver, "devices", {})
        dev = devices.get(name)
        if dev is None:
            raise MatrixError("unknown_device", f"Unbekanntes Gerät {name!r}")
        if dev.online:
            raise MatrixError("invalid", f"{name} antwortet gerade – es lässt sich nicht vergessen.")
        devices.pop(name, None)
        if hasattr(poller.driver, "_reindex"):
            poller.driver._reindex()
        hosts = [h for h in entry.options.get(CONF_STATIC_HOSTS, []) if h.split(":")[0] != dev.host]
        if hosts != list(entry.options.get(CONF_STATIC_HOSTS, [])):
            entry.options[CONF_STATIC_HOSTS] = hosts
            if hasattr(poller.driver, "static_hosts"):
                poller.driver.static_hosts = hosts
            self._save_config()
        # seine Quellen ("Kanal@Gerät") gleich mit aus den Listen nehmen, sonst bleiben sie als "sendet nicht" stehen
        registry = self.registries.get(poller.driver.PROTOCOL)
        if registry is not None:
            in_use = {self.current_source(d) for d in self.destinations.values() if d.protocol == poller.driver.PROTOCOL}
            for source_id in [s for s in list(registry._records) if s.endswith(f"@{name}") and s not in in_use]:
                registry._records.pop(source_id, None)
                registry._discovered.pop(source_id, None)
            self._save_state()
        self.sync_destinations(poller)
        self.notify()

    def refresh_sources(self) -> None:
        for registry in self.registries.values():
            registry.forget()
        for poller in self.pollers.values():
            asyncio.get_running_loop().create_task(self._refresh_one(poller))

    async def _refresh_one(self, poller: Poller) -> None:
        try:
            await poller.driver.async_refresh_sources()
        except DriverError:
            pass
        poller.wake()

    def devices(self) -> list[dict[str, Any]]:
        """Geräteübersicht für Panel, HTTP und MCP (ohne Zugangsdaten)."""
        out: list[dict[str, Any]] = []
        for entry in self.entries.values():
            poller = self.pollers.get(entry.id)
            cls = DRIVERS[entry.driver]
            base = {
                "id": entry.id,
                "driver": entry.driver,
                "driver_title": cls.TITLE,
                "protocol": cls.PROTOCOL,
                "network": cls.NETWORK,
                "title": entry.title,
                "name": poller.device_name if poller else entry.title,
                "host": entry.data.get("host"),
                "port": entry.data.get("port"),
                "scan_interval": poller.interval if poller else None,
            }
            if poller is None:
                out.append({**base, "online": False})
                continue
            if cls.NETWORK and hasattr(poller.driver, "visible_devices"):
                subs = []
                for dev in poller.driver.visible_devices():
                    rule = self.guard.rule_for(cls.PROTOCOL, dev.host, dev.name, None)
                    subs.append(
                        {
                            "name": dev.name,
                            "host": dev.host,
                            "manufacturer": dev.manufacturer,
                            "model": dev.model,
                            "firmware": dev.firmware,
                            "online": dev.online,
                            "tx_count": dev.tx_count,
                            "rx_count": dev.rx_count,
                            "sample_rate": dev.sample_rate,
                            "mdns": dev.via_mdns,
                            "found_via": "mdns"
                            if dev.via_mdns
                            else "registry"
                            if getattr(dev, "via_registry", False)
                            else "static"
                            if any(str(h).split(":")[0] == dev.host for h in (entry.options.get("static_hosts") or []))
                            else "remembered",
                            "last_error": dev.last_error,
                            # der Treiber kennt den Gerätetyp ggf. besser (Aufbau des Geräts) als die Namensregeln
                            "icon_key": getattr(dev, "icon_key", None)
                            or icon_key(protocol=cls.PROTOCOL, manufacturer=dev.manufacturer, model=dev.model, name=dev.name),
                            "device_type": getattr(dev, "device_type", None),
                            "device_type_title": getattr(dev, "device_type_title", None),
                            "web_url": getattr(dev, "web_url", None),
                            "ptp": getattr(dev, "ptp", None),
                            "protected": rule.reason if rule else None,
                        }
                    )
                out.append(
                    {
                        **base,
                        "online": True,
                        "manufacturer": cls.MANUFACTURER,
                        "model": getattr(cls, "NETWORK_MODEL", "Dante®-Netzwerk"),
                        "protocol_title": PROTOCOLS[cls.PROTOCOL].title,
                        "static_hosts": list(entry.options.get(CONF_STATIC_HOSTS, [])),
                        "options": {k: v for k, v in entry.options.items() if k in NETWORK_OPTIONS},
                        "registries": [
                            {"url": url, **{k: v for k, v in info.items() if k in ("mdns", "version", "error")}}
                            for url, info in getattr(poller.driver, "registries", {}).items()
                        ],
                        "devices": subs,
                    }
                )
                continue
            out.append(
                {
                    **base,
                    "online": poller.last_update_success,
                    "auth_failed": poller.auth_failed,
                    "last_error": poller.last_error,
                    "manufacturer": poller.info.manufacturer or cls.MANUFACTURER,
                    "model": poller.info.model,
                    "firmware": poller.info.firmware,
                    "serial": poller.info.serial,
                    "mac": poller.info.mac,
                    "web_url": poller.driver.configuration_url,
                    "icon_key": icon_key(
                        protocol=cls.PROTOCOL,
                        driver=entry.driver,
                        manufacturer=poller.info.manufacturer or cls.MANUFACTURER,
                        model=poller.info.model,
                        name=poller.device_name,
                    ),
                    "destinations": [u for u, d in self.destinations.items() if d.poller is poller],
                }
            )
        return out

    # ---------------------------------------------------------------- naming
    def label(self, protocol: str, source_id: str) -> dict[str, Any]:
        return self.labels.get(protocol, {}).get(source_id, {})

    def destination_label(self, uid: str) -> dict[str, Any]:
        return self.destination_labels.get(uid, {})

    def source_name(self, protocol: str, source_id: str | None) -> str:
        if source_id is None:
            return "Aus"
        return self.label(protocol, source_id).get("label") or source_id

    def dest_title(self, dest: Destination) -> str:
        return self.destination_label(dest.uid).get("label") or dest.name

    def resolve_destination(self, text: str | None) -> Destination:
        """Ziel-ID, Label oder Name → Ziel (Groß-/Kleinschreibung egal, muss eindeutig sein)."""
        text = (text or "").strip()
        if not text:
            raise MatrixError("invalid", "Ziel fehlt")
        if text in self.destinations:
            return self.destinations[text]
        want = text.casefold()
        hits = [
            d
            for d in self.destinations.values()
            if want
            in {
                d.uid.casefold(),
                d.name.casefold(),
                self.dest_title(d).casefold(),
                d.dest_id.casefold() if d.poller.driver.NETWORK else d.device_name.casefold(),
            }
        ]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise MatrixError("ambiguous", f"Ziel {text!r} ist nicht eindeutig: " + ", ".join(d.uid for d in hits))
        raise MatrixError("unknown_destination", f"Unbekanntes Ziel {text!r}")

    def resolve_source(self, protocol: str, text: str | None) -> str | None:
        """Quellen-ID oder Label → Quellen-ID. None / "" / "None" / "Aus" → None (= aus)."""
        if text is None or text.strip() == "" or text.strip().casefold() in {"none", "aus", "off"}:
            return None
        registry = self.registries[protocol]
        text = self.source_aliases.get(text.strip(), text) if protocol == "ndi" else text
        if registry.get(text):
            return text
        for source_id, lab in self.labels.get(protocol, {}).items():
            if lab.get("label") == text:
                return source_id
        text = text.strip()
        want = text.casefold()
        hits = [r.id for r in registry.sources if r.id.casefold() == want]
        hits += [s for s, lab in self.labels.get(protocol, {}).items() if str(lab.get("label", "")).casefold() == want]
        if len(set(hits)) == 1:
            return hits[0]
        if protocol == PROTOCOL_DANTE:
            channel, sep, device = text.rpartition("@")
            if not sep or not channel.strip() or not device.strip() or "@" in channel:
                raise MatrixError("invalid", f"Keine Dante-Quelle (erwartet 'Kanal@Gerät'): {text!r}")
        return text  # unbekannte Namen sind erlaubt (Quelle evtl. noch nicht gefunden / offline)

    def remember(self, dest: Destination, source: str | None) -> None:
        if source is None:
            return
        recent = self.recent.setdefault(dest.uid, deque(maxlen=RECENT_SIZE))
        if source in recent:
            recent.remove(source)
        recent.append(source)

    # ------------------------------------------------------------------ state
    def current_source(self, dest: Destination) -> str | None:
        data = dest.poller.data
        state = data.destinations.get(dest.dest_id) if data else None
        if state is None:
            return None
        return self.registries[dest.protocol].real_name(dest.entry_id, state.current)

    def _dest_state(self, dest: Destination) -> DestinationState | None:
        data = dest.poller.data
        return data.destinations.get(dest.dest_id) if data else None

    def connection_state(self, dest: Destination) -> ConnectionState:
        state = self._dest_state(dest)
        if not dest.available or state is None:
            return ConnectionState.OFFLINE
        current = self.current_source(dest)
        if current is None:
            return ConnectionState.NO_SOURCE
        status = state.status
        recent = time.monotonic() - dest.last_route < max(CONNECTING_GRACE, dest.poller.driver.SETTLE_TIME)
        if status.state is not None:
            if status.state in (ConnectionState.SOURCE_LOST, ConnectionState.ERROR) and recent:
                return ConnectionState.CONNECTING
            if status.state is ConnectionState.NO_SOURCE:
                return ConnectionState.CONNECTING
            return status.state
        if status.connected is True:
            return ConnectionState.CONNECTED
        live = self.registries[dest.protocol].is_live(current)
        if status.connected is False:
            return ConnectionState.CONNECTING if live or recent else ConnectionState.SOURCE_LOST
        if live:
            return ConnectionState.CONNECTED
        return ConnectionState.CONNECTING if recent else ConnectionState.SOURCE_LOST

    # ------------------------------------------------------------- protection
    def protection(self, dest: Destination) -> ProtectionRule | None:
        return self.guard.rule_for(dest.protocol, dest.host, dest.device_name, dest.channel_number)

    def _check_writable(self, dest: Destination) -> None:
        rule = self.protection(dest)
        if rule is not None:
            raise MatrixError("protected", f"{self.dest_title(dest)} ist fest gesperrt ({rule.reason}).")
        if dest.uid in self.locks:
            raise MatrixError("locked", f"{self.dest_title(dest)} ist gesperrt.")

    # ---------------------------------------------------------------- actions
    def _get(self, uid: str) -> Destination:
        dest = self.destinations.get(uid)
        if dest is None:
            raise MatrixError("unknown_destination", f"Unbekanntes Ziel {uid!r}")
        return dest

    def _new_action(self, origin: str) -> dict[str, Any]:
        self._action_seq += 1
        return {"id": self._action_seq, "origin": origin, "time": time.time(), "changes": []}

    async def route(self, uid: str, source: str | None, *, origin: str = "api") -> dict[str, Any]:
        """``source`` (Quellen-ID, None = aus) auf Ziel ``uid`` schalten."""
        dest = self._get(uid)
        self._check_writable(dest)
        action = self._new_action(origin)
        result = await self._route(dest, source, record_history=True, origin=origin, action=action)
        if action["changes"]:
            self.actions.append(action)
        return result

    async def _route(
        self, dest: Destination, source: str | None, *, record_history: bool, origin: str, action: dict[str, Any] | None
    ) -> dict[str, Any]:
        async with self._route_locks.setdefault(dest.uid, asyncio.Lock()):
            # zweite Prüfung unmittelbar vor dem Treiber: kein Weg führt an der Sperrliste vorbei
            self._check_writable(dest)
            poller = dest.poller
            registry = self.registries[dest.protocol]
            previous = self.current_source(dest)
            device_source = registry.device_name(dest.entry_id, source) if source else None
            address = registry.address_for(dest.entry_id, source) if source else None
            try:
                await poller.driver.async_route(dest.dest_id, device_source, address)
            except DriverError as err:
                raise MatrixError("route_failed", f"{self.dest_title(dest)}: {short(err)}") from err
            dest.last_route = time.monotonic()
            poller.set_current(dest.dest_id, device_source)
            if record_history and previous != source:
                self.history.setdefault(dest.uid, deque(maxlen=HISTORY_SIZE)).append(previous)
                if action is not None:
                    action["changes"].append((dest.uid, previous, source))
            if registry.grouped:  # Dante, ST 2110: zuletzt benutzte Quellen je Ziel merken
                self.remember(dest, previous)
                self.remember(dest, source)
            _LOGGER.info("Geschaltet: %s → %s (%s)", source, dest.name, origin)
            event = {
                "entity_id": None,
                "destination": dest.uid,
                "destination_name": self.dest_title(dest),
                "protocol": dest.protocol,
                "source": source,
                "previous_source": previous,
                "origin": origin,
                "time": datetime.now(UTC).isoformat(),
            }
            self.events.appendleft(event)
            for listener in list(self._event_listeners):
                listener(event)
            poller.refresh_after_route()
            self.notify()
            return event

    async def salvo(
        self, routes: Iterable[tuple[str, str | None]], *, origin: str = "salvo", skip_offline: bool = False
    ) -> dict[str, Any]:
        """Erst alle Ziele prüfen (unbekannt/gesperrt → nichts wird geschaltet), dann ausführen.

        Ziele verschiedener Geräte schalten parallel, dieselben nacheinander.
        """
        plan = [(self._get(uid), source) for uid, source in routes]
        for dest, _ in plan:
            self._check_writable(dest)
        skipped = [dest.uid for dest, _ in plan if skip_offline and not dest.available]
        plan = [(d, s) for d, s in plan if d.uid not in skipped]
        groups: dict[str, list[tuple[Destination, str | None]]] = {}
        for dest, source in plan:
            groups.setdefault(dest.entry_id, []).append((dest, source))
        action = self._new_action(origin)

        async def run(items: list[tuple[Destination, str | None]]) -> list[str]:
            errors = []
            for dest, source in items:
                try:
                    await self._route(dest, source, record_history=True, origin=origin, action=action)
                except MatrixError as err:
                    errors.append(err.message)
            return errors

        results = await asyncio.gather(*(run(items) for items in groups.values()))
        if action["changes"]:
            self.actions.append(action)
        errors = [e for group in results for e in group]
        if errors:
            raise MatrixError("route_failed", "; ".join(errors))
        return {"switched": [d.uid for d, _ in plan], "skipped_offline": skipped}

    async def undo(self, uid: str) -> dict[str, Any]:
        """Vorherige Quelle eines Ziels wiederherstellen."""
        dest = self._get(uid)
        self._check_writable(dest)
        history = self.history.get(uid)
        if not history:
            raise MatrixError("nothing_to_undo", f"Für {self.dest_title(dest)} gibt es nichts rückgängig zu machen.")
        previous = history.pop()
        try:
            result = await self._route(dest, previous, record_history=False, origin="undo", action=None)
        except MatrixError:
            history.append(previous)
            raise
        for action in reversed(self.actions):  # dieselbe Umschaltung nicht ein zweites Mal zurücknehmen
            for change in reversed(action["changes"]):
                if change[0] == uid:
                    action["changes"].remove(change)
                    break
            else:
                continue
            break
        return result

    async def undo_last(self) -> dict[str, Any]:
        """Die letzte Aktion (Einzelschaltung, Salve oder Preset) komplett zurücknehmen."""
        while self.actions and not self.actions[-1]["changes"]:
            self.actions.pop()
        if not self.actions:
            raise MatrixError("nothing_to_undo", "Es gibt nichts rückgängig zu machen.")
        action = self.actions[-1]
        plan = [(self._get(uid), previous) for uid, previous, _ in action["changes"] if uid in self.destinations]
        for dest, _ in plan:
            self._check_writable(dest)
        self.actions.pop()
        restored, errors = [], []
        for dest, previous in reversed(plan):
            try:
                await self._route(dest, previous, record_history=False, origin="undo", action=None)
            except MatrixError as err:
                errors.append(err.message)
                continue
            history = self.history.get(dest.uid)
            if history and history[-1] == previous:
                history.pop()
            restored.append({"destination": dest.uid, "source": previous})
        if errors:
            raise MatrixError("route_failed", "; ".join(errors))
        return {"undone": action["origin"], "restored": restored}

    def set_lock(self, uid: str, locked: bool) -> None:
        dest = self._get(uid)
        rule = self.protection(dest)
        if rule is not None and not locked:
            raise MatrixError("protected", f"{self.dest_title(dest)} ist fest gesperrt ({rule.reason}).")
        if locked:
            self.locks.add(uid)
        else:
            self.locks.discard(uid)
        self._save_state()
        self.notify()

    @staticmethod
    def _label_entry(label: str | None, tags: list[str] | None) -> dict[str, Any]:
        entry: dict[str, Any] = {}
        if label and label.strip():
            entry["label"] = label.strip()
        if tags:
            entry["tags"] = sorted({t.strip() for t in tags if t and t.strip()})
        return entry

    def set_label(self, protocol: str, source_id: str, label: str | None, tags: list[str] | None) -> dict[str, Any]:
        if protocol not in self.registries:
            raise MatrixError("invalid", f"Unbekanntes Protokoll {protocol!r}")
        entry = self._label_entry(label, tags)
        kept = self.label(protocol, source_id).get("type")  # von Hand festgelegter Gerätetyp bleibt erhalten
        if kept:
            entry["type"] = kept
        labels = self.labels.setdefault(protocol, {})
        if entry:
            labels[source_id] = entry
        else:
            labels.pop(source_id, None)
        self._save_state()
        self.notify()
        return entry

    def set_source_type(self, protocol: str, source_id: str, device_type: str | None) -> dict[str, Any]:
        """Gerätetyp einer Quelle von Hand festlegen (``None`` / ``"auto"`` = wieder automatisch)."""
        if protocol not in self.registries:
            raise MatrixError("invalid", f"Unbekanntes Protokoll {protocol!r}")
        if device_type in (None, "", "auto"):
            device_type = None
        elif device_type not in SOURCE_TYPES:
            raise MatrixError("invalid", f"Unbekannter Gerätetyp {device_type!r} (erlaubt: {', '.join(SOURCE_TYPES)}, auto)")
        labels = self.labels.setdefault(protocol, {})
        entry = dict(labels.get(source_id, {}))
        entry.pop("type", None)
        if device_type:
            entry["type"] = device_type
        if entry:
            labels[source_id] = entry
        else:
            labels.pop(source_id, None)
        self._save_state()
        self.notify()
        return entry

    def set_destination_label(self, uid: str, label: str | None, tags: list[str] | None) -> dict[str, Any]:
        self._get(uid)
        entry = self._label_entry(label, tags)
        if entry:
            self.destination_labels[uid] = entry
        else:
            self.destination_labels.pop(uid, None)
        self._save_state()
        self.notify()
        return entry

    # ---------------------------------------------------------------- presets
    def _preset_routes(self, routes: Any) -> list[dict[str, Any]]:
        if not isinstance(routes, list) or not routes:
            raise MatrixError("invalid", "Ein Preset braucht mindestens eine Verbindung.")
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in routes:
            if not isinstance(item, dict):
                raise MatrixError("invalid", "Verbindung muss ein Objekt {destination, source} sein.")
            dest = self.resolve_destination(str(item.get("destination") or ""))
            rule = self.protection(dest)
            if rule is not None:
                raise MatrixError("protected", f"{self.dest_title(dest)} ist fest gesperrt ({rule.reason}).")
            if dest.uid in seen:
                raise MatrixError("invalid", f"{self.dest_title(dest)} kommt im Preset doppelt vor.")
            seen.add(dest.uid)
            source = item.get("source")
            source = self.resolve_source(dest.protocol, source if isinstance(source, str) else None)
            out.append({"destination": dest.uid, "source": source})
        return out

    def save_preset(self, name: str, routes: Any, *, preset_id: str | None = None) -> dict[str, Any]:
        """Preset anlegen (``preset_id`` None) oder ändern. ``routes``: ``[{destination, source}]``."""
        name = (name or "").strip()
        if not name:
            raise MatrixError("invalid", "Name fehlt")
        if len(name) > 60:
            raise MatrixError("invalid", "Name ist zu lang (höchstens 60 Zeichen).")
        clean = self._preset_routes(routes)
        for other in self.presets.values():
            if other["name"].casefold() == name.casefold() and other["id"] != preset_id:
                raise MatrixError("invalid", f"Ein Preset namens {name!r} gibt es schon.")
        now = datetime.now(UTC).isoformat()
        if preset_id is None:
            base = slugify(name, "preset")
            preset_id, n = base, 2
            while preset_id in self.presets:
                preset_id, n = f"{base}-{n}", n + 1
            preset = {"id": preset_id, "name": name, "routes": clean, "created": now, "updated": now}
        else:
            preset = self.get_preset(preset_id)
            preset.update({"name": name, "routes": clean, "updated": now})
        self.presets[preset_id] = preset
        self._save_state()
        self.notify()
        return self.preset_view(preset)

    def snapshot_preset(self, name: str, destinations: Iterable[str], *, preset_id: str | None = None) -> dict[str, Any]:
        """Preset aus dem Ist-Zustand der genannten Ziele."""
        routes = []
        for text in destinations:
            dest = self.resolve_destination(text)
            routes.append({"destination": dest.uid, "source": self.current_source(dest)})
        return self.save_preset(name, routes, preset_id=preset_id)

    def get_preset(self, text: str) -> dict[str, Any]:
        """Preset über ID oder Name."""
        text = (text or "").strip()
        if text in self.presets:
            return self.presets[text]
        hits = [p for p in self.presets.values() if p["name"].casefold() == text.casefold()]
        if len(hits) == 1:
            return hits[0]
        raise MatrixError("unknown_preset", f"Unbekanntes Preset {text!r}")

    def delete_preset(self, text: str) -> None:
        preset = self.get_preset(text)
        del self.presets[preset["id"]]
        self._save_state()
        self.notify()

    async def recall_preset(self, text: str, *, origin: str = "preset") -> dict[str, Any]:
        """Alle Verbindungen des Presets schalten. Unbekannte/gesperrte Ziele → nichts wird geschaltet."""
        preset = self.get_preset(text)
        result = await self.salvo(
            [(r["destination"], r["source"]) for r in preset["routes"]], origin=origin, skip_offline=True
        )
        return {"preset": preset["id"], "name": preset["name"], **result}

    def preset_active(self, preset: dict[str, Any]) -> bool:
        """Aktiv = der Ist-Zustand jedes Ziels entspricht dem Preset."""
        routes = preset.get("routes") or []
        if not routes:
            return False
        for route in routes:
            dest = self.destinations.get(route["destination"])
            if dest is None or self._dest_state(dest) is None or self.current_source(dest) != route["source"]:
                return False
        return True

    def preset_view(self, preset: dict[str, Any]) -> dict[str, Any]:
        routes = []
        for route in preset.get("routes") or []:
            dest = self.destinations.get(route["destination"])
            current = self.current_source(dest) if dest else None
            routes.append(
                {
                    "destination": route["destination"],
                    "destination_name": self.dest_title(dest) if dest else route["destination"],
                    "protocol": dest.protocol if dest else None,
                    "source": route["source"],
                    "source_name": self.source_name(dest.protocol, route["source"]) if dest else route["source"],
                    "known": dest is not None,
                    "available": bool(dest and dest.available),
                    "locked": bool(dest and (dest.uid in self.locks or self.protection(dest))),
                    "matches": bool(dest and self._dest_state(dest) is not None and current == route["source"]),
                }
            )
        return {
            "id": preset["id"],
            "name": preset["name"],
            "routes": routes,
            "active": self.preset_active(preset),
            "updated": preset.get("updated"),
        }

    def presets_view(self) -> list[dict[str, Any]]:
        return [self.preset_view(p) for p in sorted(self.presets.values(), key=lambda p: natural_key(p["name"]))]

    # --------------------------------------------------------------- snapshot
    def _device_model(self, poller: Poller, device_key: str | None) -> tuple[str | None, str | None]:
        if device_key is not None:
            driver = poller.driver
            dev = driver.device_for(device_key) if hasattr(driver, "device_for") else None
            return (dev.manufacturer, dev.model) if dev else (None, None)
        return poller.info.manufacturer or poller.driver.MANUFACTURER, poller.info.model

    def _sub_icon(self, poller: Poller, device_key: str | None) -> str | None:
        """Symbol, das der Treiber für ein Untergerät selbst bestimmt (NMOS: aus dem Aufbau des Geräts)."""
        if device_key is None or not hasattr(poller.driver, "device_for"):
            return None
        return getattr(poller.driver.device_for(device_key), "icon_key", None)

    def _protocol_driver(self, protocol: str, attr: str) -> Any:
        return next((p.driver for p in self.pollers.values() if p.driver.PROTOCOL == protocol and hasattr(p.driver, attr)), None)

    def _source_icon(self, protocol: str, source_id: str, group: str | None) -> str:
        manufacturer = model = None
        if group:
            for poller in self.pollers.values():
                if poller.driver.PROTOCOL == protocol and hasattr(poller.driver, "device_for"):
                    own = self._sub_icon(poller, group)
                    if own:
                        return own
                    manufacturer, model = self._device_model(poller, group)
                    break
        return icon_key(protocol=protocol, manufacturer=manufacturer, model=model, name=group or source_id, role="source")

    def _source_dict(
        self, protocol: str, source_id: str, live: bool, address: str | None, last_seen: float | None, first_seen: float | None
    ) -> dict[str, Any]:
        lab = self.label(protocol, source_id)
        host = address.rsplit(":", 1)[0] if address and ":" in address else address
        described = self.registries[protocol].describe(source_id)
        extra: dict[str, Any] = {}
        icon = None
        if protocol == "ndi":  # Gerätetyp: von Hand festgelegt > Regeln (source_types.py) > unbekannt
            web = self.source_web.get(host or "") or {}
            auto = classify(source_id, web.get("hint"))
            kind = lab.get("type") if lab.get("type") in SOURCE_TYPES else auto
            icon = SOURCE_TYPES[kind][1]
            extra = {"device_type": kind, "device_type_auto": auto, "device_type_manual": kind != auto or bool(lab.get("type")), "web_url": web.get("url")}
        else:  # Treiber mit eigenen Angaben zur Quelle (ST 2110: Format, Ebenen, „keine Vorschau“)
            driver = self._protocol_driver(protocol, "source_info")
            if driver is not None:
                extra = dict(driver.source_info(source_id))
        return {
            "id": source_id,
            **described,
            **extra,
            "name": lab.get("label") or source_id,
            "label": lab.get("label"),
            "original_name": source_id,
            "icon_key": icon or self._source_icon(protocol, source_id, described.get("group")),
            "tags": list(lab.get("tags", [])),
            "live": live,
            "host": host,
            "address": address,
            "last_seen": _iso(last_seen),
            "first_seen": _iso(first_seen),
        }

    @staticmethod
    def _layer_fields(dest: Destination, state: DestinationState | None) -> dict[str, Any]:
        """ST 2110: ein Ziel ist ein Bündel aus Ebenen (Bild, Ton, Zusatzdaten) – was liegt auf welcher?"""
        extra = state.status.extra if state and dest.available else {}
        if "layers" not in extra:
            return {}
        return {
            "layers": extra["layers"],
            "breakaway": bool(extra.get("breakaway")),
            "partial": bool(extra.get("partial")),
            "format": extra.get("format"),
            "detail": extra.get("detail"),
        }

    def _subscription(self, dest: Destination) -> dict[str, Any] | None:
        state = self._dest_state(dest)
        extra = dict(state.status.extra) if state and dest.available else {}
        if "subscription" not in extra:
            return None
        return {
            "state": extra["subscription"],
            "code": extra.get("subscription_code"),
            "status": extra.get("subscription_status"),
            "detail": extra.get("subscription_detail"),
        }

    def destination_dict(self, dest: Destination, registry: SourceRegistry | None = None) -> dict[str, Any]:
        registry = registry or self.registries[dest.protocol]
        current = self.current_source(dest)
        lab = self.destination_label(dest.uid)
        manufacturer, model = self._device_model(dest.poller, dest.device_key)
        state = self._dest_state(dest)
        rule = self.protection(dest)
        return {
            "id": dest.uid,
            "entity_id": None,
            "name": lab.get("label") or dest.name,
            "label": lab.get("label"),
            "original_name": dest.name,
            "tags": list(lab.get("tags", [])),
            "channel": dest.channel_name,
            "device_name": dest.device_name,
            "group": dest.device_key,
            "device_id": None,
            "entry_id": dest.entry_id,
            "driver": dest.poller.driver.KEY,
            "manufacturer": manufacturer,
            "model": model,
            "icon_key": self._sub_icon(dest.poller, dest.device_key)
            or icon_key(protocol=dest.protocol, driver=dest.poller.driver.KEY, manufacturer=manufacturer, model=model, name=dest.device_name),
            "host": dest.host,
            "web_url": dest.web_url,
            "protocol": dest.protocol,
            "current_source": current,
            "current_source_live": registry.is_live(current),
            # das Gerät ist noch auf einen früheren Namen der Quelle eingestellt → neu zuweisen
            "current_source_renamed_to": self.source_aliases.get(current) if current else None,
            "status": self.connection_state(dest).value,
            "resolution": state.status.resolution if state and dest.available else None,
            "subscription": self._subscription(dest),
            **self._layer_fields(dest, state),
            "available": dest.available,
            # fest geschützte Ziele erscheinen in der Karte als gesperrt (und lassen sich nicht entsperren)
            "locked": dest.uid in self.locks or rule is not None,
            "protected": rule.reason if rule else None,
            "can_undo": bool(self.history.get(dest.uid)) and rule is None,
            "display": None,
        }

    def snapshot(self) -> dict[str, Any]:
        """Kompletter Zustand (Format wie die HA-Integration, siehe docs/frontend-api.md). Nicht verändern: geteilt."""
        if "snapshot" not in self._memo:
            self._memo["snapshot"] = self._snapshot()
        return self._memo["snapshot"]

    def _snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {"version": self.version, "protocols": {}}
        for key, proto in PROTOCOLS.items():
            registry = self.registries[key]
            dests = [d for d in self.destinations.values() if d.protocol == key]
            sources: dict[str, dict[str, Any]] = {}
            for rec in registry.sources:
                sources[rec.id] = self._source_dict(key, rec.id, rec.live, rec.address, rec.last_seen, rec.first_seen)
            destinations = []
            for dest in sorted(dests, key=lambda d: (natural_key(d.device_name), natural_key(d.name))):
                item = self.destination_dict(dest, registry)
                current = item["current_source"]
                if current is not None and current not in sources:
                    sources[current] = self._source_dict(key, current, False, None, None, None)
                destinations.append(item)
            if destinations or sources:
                out["protocols"][key] = {
                    "title": proto.title,
                    # trägt Bild? gibt es dafür eine Vorschau? (ST 2110: Bild ja, Vorschau nein)
                    "video": bool(getattr(proto, "video", key == "ndi")),
                    "preview": key == "ndi",
                    "grouped": registry.grouped,
                    "sources": sorted(
                        sources.values(),
                        key=lambda s: registry.sort_key(s["id"]) if registry.grouped else natural_key(s["name"]),
                    ),
                    "destinations": destinations,
                }
        # Vorschau: die Karte holt die Bilder selbst (docs/SCHNITTSTELLE.md); hier steht nur, wo und ob überhaupt
        out["preview"] = self.preview_info() if self.preview_info else {"configured": False}
        out["presets"] = self.presets_view()
        out["can_undo"] = any(a["changes"] for a in self.actions)
        out["protected"] = [r.as_dict() for r in self.guard.rules]
        return out

    def status(self) -> dict[str, Any]:
        """Kompakter Zustand für Companion und einfache Abfragen."""
        if "status" not in self._memo:
            self._memo["status"] = self._status()
        return self._memo["status"]

    def _status(self) -> dict[str, Any]:
        routes = {}
        for dest in self.destinations.values():
            routes[dest.uid] = self.current_source(dest) if self._dest_state(dest) is not None else None
        return {
            "routes": routes,
            "presets": {p["id"]: self.preset_active(p) for p in self.presets.values()},
            "can_undo": any(a["changes"] for a in self.actions),
        }

    def choices(self) -> dict[str, Any]:
        """Auswahllisten für Companion (Ziele, Quellen, Presets)."""
        if "choices" not in self._memo:
            self._memo["choices"] = self._choices()
        return self._memo["choices"]

    def _choices(self) -> dict[str, Any]:
        dests, sources = [], []
        for dest in sorted(self.destinations.values(), key=lambda d: (d.protocol, natural_key(self.dest_title(d)))):
            dests.append(
                {
                    "id": dest.uid,
                    "name": self.dest_title(dest),
                    "protocol": dest.protocol,
                    "protected": self.protection(dest) is not None,
                }
            )
        for key, registry in self.registries.items():
            seen = {r.id for r in registry.sources}
            extra = {self.current_source(d) for d in self.destinations.values() if d.protocol == key} - seen - {None}
            for sid in [r.id for r in registry.sources] + sorted(extra):  # type: ignore[arg-type]
                sources.append({"id": sid, "name": self.source_name(key, sid), "protocol": key})
        presets = [{"id": p["id"], "name": p["name"]} for p in sorted(self.presets.values(), key=lambda p: p["name"])]
        return {"destinations": dests, "sources": sources, "presets": presets, "aliases": dict(self.source_aliases)}
