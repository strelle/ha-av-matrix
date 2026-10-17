"""SMPTE ST 2110 network driver (AMWA NMOS IS-04 / IS-05): all NMOS nodes of the network behind one entry.

* Nodes are announced via mDNS (``_nmos-node._tcp``, fed in by ``protocols.nmos_mdns.NmosBrowser``), listed by an
  IS-04 registry (Query API) if one exists, or configured as static hosts. NMOS has no login in this setup
  (nodes that demand HTTPS client auth are listed as "not supported").
* Every sender group of every online node is a source (``"<group>@<device>"``), every receiver group a
  destination (``"<device>:<group>"``); see ``protocols/nmos.py`` for how groups are formed.
* Routing PATCHes the receivers' ``/staged`` endpoint with ``activate_immediate`` and reads ``/active`` back.

The driver only talks to the control plane (HTTP). It never joins a media stream, so there is no preview.
Light on a Raspberry Pi: one small GET per node and poll, a full re-read once a minute or when mDNS says
something changed.

Other controllers (a Blackmagic Ethernet Switch, a Videohub panel, the devices' own menus) may switch the same
receivers at any time. Their changes show up with the next poll; ``pop_external_changes()`` tells the hub which
destinations were switched by someone else, so that it can log them and keep undo consistent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

import aiohttp

from ..models import (
    ConnectionState,
    DestinationInfo,
    DestinationState,
    DestinationStatus,
    DeviceInfo,
    DevicePoll,
    SourceSighting,
)
from ..protocols import nmos
from .base import CannotConnect, Driver, RouteFailed, short

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 3.0
#: Nodes polled in parallel.
MAX_PARALLEL = 4
#: Every N polls everything is read again (labels, senders, flows, IS-05 state); in between only ``/receivers``.
FULL_EVERY = 12
#: Offline nodes are retried every N polls.
OFFLINE_RETRY_EVERY = 4
#: A node counts as offline after this many failed polls in a row (one lost request is not "offline").
OFFLINE_AFTER = 2
#: Hosts that never answered are retried at most every N polls (and with a short timeout).
PENDING_MAX_WAIT = 12
PROBE_TIMEOUT = 1.5
#: A registry is asked for its node list every N polls.
REGISTRY_EVERY = 6
#: Pauses before reading ``/active`` back after a PATCH.
VERIFY_DELAYS = (0.0, 0.3, 1.0)
#: Seconds between two checks whether a node has a web UI.
WEB_RECHECK = 3600.0
#: Ports tried for a manually entered host without a port. 8090: where users found the NMOS API of Blackmagic
#: 2110 converters (forum report, not documented); 80: most other hardware; 3212: nmos-cpp; 8080: software nodes.
PROBE_PORTS = (8090, 80, 3212, 8080)
#: Ways to tell a receiver what to receive, tried in this order until the device accepts one:
#: sender id + SDP (the normal case) · sender id + explicit transport parameters · sender id alone.
PATCH_MODES = ("sdp", "params", "id")

CONF_STATIC_HOSTS = "static_hosts"
CONF_HIDDEN_DEVICES = "hidden_devices"
CONF_AUDIO_BREAKAWAY = "audio_breakaway"
CONF_CHECK_COMPAT = "check_compat"
CONF_ENABLE_SENDERS = "enable_senders"
CONF_REGISTRIES = "registries"

IMMEDIATE = {"mode": "activate_immediate"}


def split_host(text: str) -> tuple[str, int | None]:
    """``"192.0.2.7:8080"`` → ``("192.0.2.7", 8080)``; also accepts a full ``http://…`` URL."""
    text = text.strip().removeprefix("http://").removeprefix("https://").split("/")[0]
    host, sep, port = text.rpartition(":")
    if sep and port.isdigit():
        return host, int(port)
    return text, None


@dataclass(slots=True)
class Conn:
    """What a receiver is connected to (IS-05 ``active``, or IS-04 ``subscription`` between full reads)."""

    sender_id: str | None = None
    enabled: bool = False
    sdp: str | None = None
    params: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class Step:
    """One layer of a route: connect ``receiver`` to ``sender`` (None = disconnect) or restore ``restore``."""

    layer: tuple[str, int]
    receiver: nmos.Receiver
    sender: nmos.Sender | None = None
    sender_node: NmosNode | None = None
    restore: Conn | None = None
    note: str | None = None  # why this layer is disconnected although a source was routed


@dataclass(slots=True, eq=False)
class NmosNode:
    """What we know about one NMOS node (= one physical device)."""

    node_id: str
    name: str
    host: str
    port: int
    scheme: str = "http"
    api_version: str = "v1.3"
    label: str = ""
    hostname: str = ""
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    device_type: str = "device"
    web_url: str | None = None
    web_checked: float = 0.0
    via_mdns: bool = False
    via_registry: bool = False
    static: bool = False
    online: bool = False
    polls: int = 0
    failures: int = 0
    last_error: str | None = None
    last_seen: float = 0.0
    full_due: bool = True
    txt: dict[str, str] = field(default_factory=dict)
    #: further addresses the same node answers on (second interface, registry lists another one than mDNS)
    alt: set[tuple[str, int]] = field(default_factory=set)
    #: hosts the node itself lists in IS-04 ``self.api.endpoints``. If ``host`` is not among them, we reach the
    #: node over an address it does not advertise (a control port that forwards to the media ports, as on the
    #: Blackmagic 4x12G): then its control and manifest URLs are rewritten to ``host`` (see ``_reach``).
    advertised: set[str] = field(default_factory=set)
    data: nmos.NodeModel | None = None
    sources: dict[str, nmos.Group] = field(default_factory=dict)
    dests: dict[str, nmos.Group] = field(default_factory=dict)
    conn: dict[str, Conn] = field(default_factory=dict)
    #: IS-04 ``subscription`` disagreed with IS-05 ``active``: read IS-05 on every poll for this node.
    is04_unreliable: bool = False
    #: which of PATCH_MODES this device accepted last
    patch_mode: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def base(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def node_api(self) -> str:
        return f"{self.base}/x-nmos/node/{self.api_version}"

    # the hub's device overview reads these (same names as the Dante driver's devices)
    @property
    def tx_count(self) -> int:
        return len(self.sources)

    @property
    def rx_count(self) -> int:
        return len(self.dests)

    @property
    def sample_rate(self) -> int | None:
        return None

    @property
    def icon_key(self) -> str:
        """Device illustration (``devices/<icon_key>.svg``) for this node's device type."""
        return nmos.DEVICE_TYPES[self.device_type][1]

    @property
    def device_type_title(self) -> str:
        return nmos.DEVICE_TYPES[self.device_type][0]

    @property
    def ptp(self) -> dict[str, Any] | None:
        """PTP state as the node reports it (IS-04 clocks): locked? to which grandmaster? is that this device?"""
        for clock in self.data.clocks if self.data else []:
            if clock.ref_type == "ptp":
                return {
                    "locked": clock.locked,
                    "grandmaster": clock.gmid,
                    "traceable": clock.traceable,
                    "is_grandmaster": nmos.is_own_clock(clock.gmid, self.data.macs if self.data else []),
                }
        return None

    def answers_on(self, host: str, port: int | None) -> bool:
        if self.host == host and (port is None or self.port == port):
            return True
        return any(h == host and (port is None or p == port) for h, p in self.alt)

    def as_dict(self) -> dict[str, Any]:
        """Diagnostics / ``nmos-check --json``."""
        data = self.data
        return {
            "name": self.name,
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "api": f"{self.scheme} IS-04 {self.api_version}",
            "label": self.label,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "device_type": self.device_type,
            "icon_key": self.icon_key,
            "web_url": self.web_url,
            "online": self.online,
            "mdns": self.via_mdns,
            "registry": self.via_registry,
            "static": self.static,
            "other_addresses": sorted(f"{h}:{p}" for h, p in self.alt),
            "last_error": self.last_error,
            "ptp": self.ptp,
            "patch_mode": self.patch_mode,
            "is04_subscription_reliable": not self.is04_unreliable,
            "sources": {name: _group_dict(g) for name, g in self.sources.items()},
            "destinations": {name: _group_dict(g) for name, g in self.dests.items()},
            "senders": [
                {
                    "id": s.id,
                    "label": s.label,
                    "kind": s.kind,
                    "format": s.flow.text if s.flow else None,
                    "media_type": s.flow.media_type if s.flow else None,
                    "active": s.active,
                    "grouphint": s.tags.get(nmos.GROUPHINT_TAG),
                }
                for s in (data.senders.values() if data else [])
            ],  # fmt: skip
            "receivers": [
                {
                    "id": r.id,
                    "label": r.label,
                    "kind": r.kind,
                    "media_types": r.caps.get("media_types"),
                    "constraint_sets": len(r.caps.get("constraint_sets") or []),
                    "sender_id": self.conn.get(r.id, Conn()).sender_id,
                    "enabled": self.conn.get(r.id, Conn()).enabled,
                    "grouphint": r.tags.get(nmos.GROUPHINT_TAG),
                }
                for r in (data.receivers.values() if data else [])
            ],  # fmt: skip
        }


def _group_dict(group: nmos.Group) -> dict[str, Any]:
    return {
        "layers": {f"{kind}{index + 1 if index else ''}": rid for (kind, index), rid in group.ordered()},
        "hinted": group.hinted,
    }


class NmosNetwork(Driver):
    """All NMOS nodes (SMPTE ST 2110 devices) of the network (one config entry)."""

    KEY = "nmos"
    PROTOCOL = nmos.PROTOCOL
    TITLE = "network – all ST 2110 devices (NMOS), found automatically"
    MANUFACTURER = "SMPTE ST 2110"
    DEFAULT_PORT = None
    CONFIG_FIELDS = ()
    TRUSTED_SOURCE_LIST = True
    SETTLE_TIME = 2.0
    NETWORK: ClassVar[bool] = True
    #: a device with more destinations gets its entities disabled by default (Home Assistant variant)
    LARGE_DEVICE_RX: ClassVar[int] = 32
    #: shown in the device overview instead of a model
    NETWORK_MODEL: ClassVar[str] = "ST-2110-Netzwerk (NMOS)"

    def __init__(
        self,
        session: aiohttp.ClientSession | None,
        config: Mapping[str, Any],
        timeout: float = REQUEST_TIMEOUT,
        *,
        options: Mapping[str, Any] | None = None,
    ) -> None:
        self._session = session
        self._own_session = False
        self.config = dict(config)
        self.host = "nmos"
        self.port = None
        self.request_timeout = min(float(timeout), REQUEST_TIMEOUT)
        self.timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        options = options or {}
        self.hidden: set[str] = set(options.get(CONF_HIDDEN_DEVICES, []))
        self.static_hosts: list[str] = [h for h in options.get(CONF_STATIC_HOSTS, []) if h]
        self.audio_breakaway = bool(options.get(CONF_AUDIO_BREAKAWAY, False))
        self.check_compat = bool(options.get(CONF_CHECK_COMPAT, True))
        self.enable_senders = bool(options.get(CONF_ENABLE_SENDERS, True))
        self.devices: dict[str, NmosNode] = {}  # by name
        #: registries (IS-04 Query API): base URL → {"mdns", "version", "error", "nodes": listed nodes | None}
        self.registries: dict[str, dict[str, Any]] = {
            _registry_url(url): {"mdns": False, "version": None, "error": None, "nodes": None}
            for url in options.get(CONF_REGISTRIES, [])
            if url
        }
        #: registries seen only by their Registration API announcement (``_nmos-register._tcp``); not queried
        self.registrations: set[str] = set()
        self._registry_ids: dict[str, set[str]] = {}  # registry URL → node ids it listed last time
        #: destination id → ((sender id, enabled) of its primary receiver, matrix source) as of the last poll
        self._seen: dict[str, tuple[tuple[str | None, bool], str | None]] = {}
        self._own: set[str] = set()  # receivers this driver switched itself since the last poll
        self._external: list[tuple[str, str | None, str | None]] = []
        self._pending: dict[tuple[str, int | None], dict[str, Any]] = {}
        self._senders: dict[str, tuple[NmosNode, str]] = {}  # sender id → (node, source group name)
        self._remembered: dict[str, Conn] = {}  # placeholder source id → connection to restore it
        #: senders this driver switched on because a route needed them: (device name, sender id)
        self.switched_on: list[tuple[str, str]] = []
        self._polls = 0
        self._registry_due = False
        self._poll_lock = asyncio.Lock()

    # ----------------------------------------------------------------- basics
    @property
    def configuration_url(self) -> str | None:
        return None  # the network itself has no web UI; see destination_url for the devices

    def destination_host(self, destination: str) -> str | None:
        node = self._node_of(destination)
        return node.host if node else None

    def destination_url(self, destination: str) -> str | None:
        """Only set if the device answered with a web page (checked read-only); never guessed."""
        node = self._node_of(destination)
        return node.web_url if node else None

    def close(self) -> None:
        if self._own_session and self._session is not None:
            session, self._session = self._session, None
            try:
                asyncio.get_running_loop().create_task(session.close())
            except RuntimeError:
                pass

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
            self._own_session = True
        return self._session

    def _node_of(self, destination: str) -> NmosNode | None:
        try:
            return self.devices.get(nmos.split_dest(destination)[0])
        except ValueError:
            return None

    def device_for(self, name: str) -> NmosNode | None:
        return self.devices.get(name)

    def visible_devices(self) -> list[NmosNode]:
        return sorted((d for d in self.devices.values() if d.name not in self.hidden), key=lambda d: nmos.natural_key(d.name))

    # ------------------------------------------------------------- discovery
    def add_host(
        self,
        host: str,
        port: int | None = None,
        props: Mapping[str, str] | None = None,
        *,
        mdns: bool = False,
        registry: bool = False,
        node_id: str | None = None,
    ) -> None:
        """A node was announced (mDNS), listed (registry) or configured (static). It is read on the next poll."""
        props = dict(props or {})
        for node in self.devices.values():
            if node.answers_on(host, port):
                node.via_mdns = node.via_mdns or mdns
                node.via_registry = node.via_registry or registry
                if mdns and props and any(props.get(k) != node.txt.get(k) for k in props if k.startswith("ver_")):
                    node.full_due = True  # peer-to-peer mDNS: a ver_* counter moved = something changed
                    node.polls = 0
                node.txt = props or node.txt
                if not node.online:
                    node.polls = 0  # announced again: try right away
                return
        entry = self._pending.setdefault((host, port), {"props": props, "mdns": False, "registry": False})
        entry["mdns"] |= mdns
        entry["registry"] |= registry
        entry["props"] = props or entry["props"]
        entry["node_id"] = node_id or entry.get("node_id")
        if mdns:
            entry["next"] = 0  # announced (again): try right away

    def mdns_removed(self, host: str | None, port: int | None = None) -> None:
        """mDNS goodbye: the node is checked on the next poll (and goes offline if it does not answer)."""
        self._pending.pop((host or "", port), None)
        for node in self.devices.values():
            if host and node.answers_on(host, port):
                node.via_mdns = False
                node.polls = 0

    def add_registry(self, url: str, *, mdns: bool = True) -> None:
        url = _registry_url(url)
        if url not in self.registries:
            self.registries[url] = {"mdns": mdns, "version": None, "error": None, "nodes": None}
            self._registry_due = True  # ask it with the next poll, not only when its turn comes

    def remove_registry(self, url: str) -> None:
        url = _registry_url(url)
        if self.registries.get(url, {}).get("mdns"):
            self.registries.pop(url, None)
            if self._registry_ids.pop(url, None) is not None:
                self._mark_registered()

    def add_registration(self, url: str) -> None:
        """A registry announced its Registration API (mDNS). Only noted: the matrix reads via the Query API."""
        self.registrations.add(_registry_url(url))

    def remove_registration(self, url: str) -> None:
        self.registrations.discard(_registry_url(url))

    # ------------------------------------------------------------------ HTTP
    async def _get(self, url: str, *, text: bool = False, timeout: float | None = None) -> Any:
        try:
            async with self._http().get(url, timeout=aiohttp.ClientTimeout(total=timeout or self.request_timeout)) as resp:
                if resp.status != 200:
                    raise CannotConnect(f"HTTP {resp.status} von {_where(url)}")
                body = await resp.text()
        except TimeoutError:
            raise CannotConnect(f"{_where(url)} antwortet nicht (Zeitüberschreitung)") from None
        except (aiohttp.ClientError, OSError, UnicodeDecodeError) as err:
            raise CannotConnect(f"{_where(url)}: {short(err)}") from err
        if text:
            return body
        try:
            return json.loads(body)
        except ValueError:
            raise CannotConnect(f"{_where(url)} antwortet kein JSON") from None

    async def _patch(self, url: str, body: dict[str, Any]) -> tuple[int, Any]:
        """→ ``(status, parsed body)``. Raises RouteFailed only if the device cannot be reached."""
        try:
            async with self._http().request("PATCH", url, json=body, timeout=self.timeout) as resp:
                raw = await resp.text()
                status = resp.status
        except TimeoutError:
            raise RouteFailed(f"{_where(url)} antwortet nicht (Zeitüberschreitung)") from None
        except (aiohttp.ClientError, OSError, UnicodeDecodeError) as err:
            raise RouteFailed(f"{_where(url)}: {short(err)}") from err
        try:
            return status, json.loads(raw) if raw.strip() else None
        except ValueError:
            return status, None

    # --------------------------------------------------------------- reading
    async def _identify(self, host: str, port: int | None, info: dict[str, Any]) -> None:
        """First contact with a host: find the Node API, read ``self``, create or update the node."""
        props: dict[str, str] = info["props"]
        scheme = "https" if props.get("api_proto") == "https" else "http"
        last: Exception | None = None
        for candidate in [port] if port else PROBE_PORTS:
            try:
                offered = await self._get(f"{scheme}://{host}:{candidate}/x-nmos/node/", timeout=PROBE_TIMEOUT)
                version = nmos.pick_version(offered, nmos.NODE_API_VERSIONS)
                if version is None:
                    raise CannotConnect(f"{host}: keine unterstützte IS-04-Version ({offered})")
                me = await self._get(f"{scheme}://{host}:{candidate}/x-nmos/node/{version}/self")
                if not isinstance(me, dict) or not nmos.is_uuid(me.get("id")):
                    raise CannotConnect(f"{host}: keine NMOS-Node")
            except CannotConnect as err:
                last = err
                continue
            self._pending.pop((host, port), None)
            node = next((n for n in self.devices.values() if n.node_id == me["id"]), None)
            if node is None:
                node = NmosNode(node_id=me["id"], name=f"\x00{me['id']}", host=host, port=candidate)
                node.label, node.hostname = str(me.get("label") or ""), _hostname(me)
                self.devices[node.name] = node
                _LOGGER.info("NMOS node %s found at %s:%s", node.label or host, host, candidate)
            node.via_mdns |= info["mdns"]
            node.via_registry |= info["registry"]
            node.static |= not (info["mdns"] or info["registry"])
            if node.online and (node.host, node.port) != (host, candidate):
                # the same device under a second address (mDNS and registry name different interfaces): the
                # address that works stays, the other one is remembered – no duplicate, no flip-flopping
                node.alt.add((host, candidate))
                return
            node.alt.discard((host, candidate))
            node.host, node.port, node.scheme, node.api_version = host, candidate, scheme, version
            node.txt = props or node.txt
            node.full_due, node.polls = True, 0
            self._drop_registry_candidates(node.node_id)
            return
        _LOGGER.debug("NMOS host %s does not answer: %s", host, last)

    def _drop_registry_candidates(self, node_id: str) -> None:
        """A node is read: the other addresses a registry listed for it need not be tried any more."""
        for key in [k for k, info in self._pending.items() if info.get("node_id") == node_id and not info["mdns"]]:
            del self._pending[key]

    def _free_name(self, node: NmosNode) -> str:
        """Name of a node = its label. Nodes that share a label are told apart by host name, else by their id.

        The result does not depend on the order in which nodes were found: *every* node with a non-unique label
        gets the longer name.
        """
        base = nmos.clean_name(node.label, "") or nmos.clean_name(node.hostname, "") or node.host
        others = [n for n in self.devices.values() if n is not node]
        if all(
            (nmos.clean_name(n.label, "") or nmos.clean_name(n.hostname, "") or n.host).casefold() != base.casefold()
            for n in others
        ):
            return base
        hostname = nmos.clean_name(node.hostname, "")
        if hostname and all(nmos.clean_name(n.hostname, "").casefold() != hostname.casefold() for n in others):
            return hostname
        return f"{base} ({node.node_id[-4:]})"

    def _name_all(self) -> None:
        nodes = list(self.devices.values())
        names = [self._free_name(node) for node in nodes]
        for node, name in zip(nodes, names, strict=True):
            if name != node.name:
                if not node.name.startswith("\x00"):
                    _LOGGER.info("NMOS node %s is now called %s", node.name, name)
                node.name = name
        self.devices = {node.name: node for node in nodes}

    async def _discover_pending(self) -> None:
        for text in self.static_hosts:
            host, port = split_host(text)
            known = any(n.host == host and (port is None or n.port == port) for n in self.devices.values())
            if host and not known:
                self._pending.setdefault((host, port), {"props": {}, "mdns": False, "registry": False})
        # a host that does not answer is retried after 1, 2, 4 … polls, at most every PENDING_MAX_WAIT polls:
        # one dead address must not slow every poll down
        due = {key: info for key, info in self._pending.items() if info.get("next", 0) <= self._polls}
        if not due:
            return
        sem = asyncio.Semaphore(MAX_PARALLEL)

        async def one(key: tuple[str, int | None], info: dict[str, Any]) -> None:
            async with sem:
                if info["props"].get("api_auth") == "true":
                    if not info.get("tries"):
                        _LOGGER.info("NMOS node at %s demands authorization (not supported)", key[0])
                else:
                    await self._identify(key[0], key[1], info)
            if key in self._pending:  # still not identified
                info["tries"] = info.get("tries", 0) + 1
                info["next"] = self._polls + min(2 ** (info["tries"] - 1), PENDING_MAX_WAIT)

        await asyncio.gather(*(one(key, info) for key, info in due.items()))
        self._name_all()

    async def _poll_registries(self) -> None:
        for url, state in list(self.registries.items()):
            try:
                if state["version"] is None:
                    state["version"] = nmos.pick_version(await self._get(f"{url}/x-nmos/query/"), nmos.QUERY_API_VERSIONS)
                    if state["version"] is None:
                        raise CannotConnect("keine unterstützte Query-API-Version")
                nodes = await self._get(f"{url}/x-nmos/query/{state['version']}/nodes?paging.limit=100")
            except CannotConnect as err:
                state["error"], state["version"] = short(err), None
                continue
            listed = [raw for raw in nodes if isinstance(raw, dict)] if isinstance(nodes, list) else []
            state["error"], state["nodes"] = None, len(listed)
            self._registry_ids[url] = {raw["id"] for raw in listed if nmos.is_uuid(raw.get("id"))}
            known = {node.node_id: node for node in self.devices.values()}
            for raw in listed:
                node = known.get(raw.get("id") or "")
                if node is not None and node.online:
                    self._drop_registry_candidates(node.node_id)
                    continue  # already read (found via mDNS or by hand): the registry adds nothing but its mark
                for host, port, proto in _node_endpoints(raw):  # every address it lists: one of them is reachable
                    if node is None or not node.answers_on(host, port):
                        self.add_host(host, port, {"api_proto": proto}, registry=True, node_id=raw.get("id"))
        self._mark_registered()

    def _mark_registered(self) -> None:
        """``via_registry`` = a registry lists the node right now (not: has listed it at some point)."""
        listed: set[str] = set().union(*self._registry_ids.values())
        for node in self.devices.values():
            node.via_registry = node.node_id in listed

    async def _read_all(self, node: NmosNode) -> None:
        """Full read: the six IS-04 lists, groups, then the IS-05 ``active`` state of every receiver."""
        api = node.node_api
        me = await self._get(f"{api}/self")
        if not isinstance(me, dict) or me.get("id") != node.node_id:
            raise CannotConnect(f"{node.host}: dort antwortet jetzt ein anderes Gerät")
        lists = [await self._get(f"{api}/{what}") for what in ("devices", "sources", "flows", "senders", "receivers")]
        try:
            data = nmos.parse_node(me, *lists, host=node.host)
        except nmos.NmosError as err:
            raise CannotConnect(f"{node.host}: {err}") from err
        node.data = data
        node.advertised = {host for host, _port, _proto in _node_endpoints(me)}
        node.label, node.hostname = data.label, _hostname(me)
        node.manufacturer, node.model, node.device_type = nmos.classify_device(data)
        node.sources = {g.name: g for g in nmos.build_groups(data, "sender")}
        node.dests = {g.name: g for g in nmos.build_groups(data, "receiver")}
        previous = node.conn
        node.conn = {}
        mismatch = False
        for receiver in data.receivers.values():
            is04 = Conn(receiver.sender_id, receiver.active)
            try:
                node.conn[receiver.id] = active = await self._read_active(node, receiver)
            except CannotConnect as err:
                _LOGGER.debug("IS-05 active of %s/%s unreadable: %s", node.name, receiver.label, err)
                node.conn[receiver.id] = _keep_sdp(is04, previous.get(receiver.id))
                continue
            if (active.sender_id, active.enabled) != (is04.sender_id, is04.enabled):
                mismatch = True
        if mismatch and not node.is04_unreliable:
            _LOGGER.info("%s: IS-04 subscription differs from IS-05 active; reading IS-05 on every poll", node.name)
        node.is04_unreliable = mismatch
        node.full_due = False
        if time.monotonic() - node.web_checked > WEB_RECHECK or not node.web_checked:
            await self._probe_web(node)

    async def _read_fast(self, node: NmosNode) -> None:
        """Cheap poll: only ``/receivers`` (IS-04 mirrors the connection state in ``subscription``)."""
        assert node.data is not None
        raw = await self._get(f"{node.node_api}/receivers")
        if not isinstance(raw, list):
            raise CannotConnect(f"{node.host}: receivers ist keine Liste")
        seen: set[str] = set()
        touched: list[nmos.Receiver] = []
        for item in raw:
            if not isinstance(item, dict) or not nmos.is_uuid(item.get("id")):
                continue
            seen.add(item["id"])
            known = node.data.receivers.get(item["id"])
            if known is None or known.label != str(item.get("label") or ""):
                node.full_due = True  # a receiver appeared or was renamed
                continue
            fresh = nmos.parse_receiver(item)
            if fresh.version != known.version and (fresh.sender_id, fresh.active) == (known.sender_id, known.active):
                touched.append(known)  # the resource changed, its subscription did not: ask IS-05 what happened
            known.sender_id, known.active, known.version = fresh.sender_id, fresh.active, fresh.version
            if not node.is04_unreliable:
                node.conn[known.id] = _keep_sdp(Conn(fresh.sender_id, fresh.active), node.conn.get(known.id))
        if seen != set(node.data.receivers):
            node.full_due = True
        for receiver in touched if not node.is04_unreliable else []:
            try:
                active = await self._read_active(node, receiver)
            except CannotConnect:
                continue
            if (active.sender_id, active.enabled) != (receiver.sender_id, receiver.active):
                # someone switched, the device raised the version but left ``subscription`` as it was
                _LOGGER.info("%s: IS-04 subscription lags behind IS-05 active; reading IS-05 on every poll", node.name)
                node.conn[receiver.id] = active
                node.is04_unreliable = True
        if node.is04_unreliable:
            for receiver in node.data.receivers.values():
                try:
                    node.conn[receiver.id] = await self._read_active(node, receiver)
                except CannotConnect:
                    continue

    async def _read_active(self, node: NmosNode, receiver: nmos.Receiver) -> Conn:
        base = self._connection_base(node, receiver.device_id)
        if base is None:
            raise CannotConnect(f"{node.name}: keine IS-05-Schnittstelle")
        raw = await self._get(f"{base}/single/receivers/{receiver.id}/active")
        if not isinstance(raw, dict):
            raise CannotConnect(f"{node.name}: active ist kein Objekt")
        sender_id = raw.get("sender_id")
        tfile = raw.get("transport_file") if isinstance(raw.get("transport_file"), dict) else {}
        params = raw.get("transport_params")
        return Conn(
            sender_id=sender_id if nmos.is_uuid(sender_id) else None,
            enabled=bool(raw.get("master_enable")),
            sdp=tfile.get("data") if nmos.is_sdp(tfile.get("data")) else None,
            params=params if isinstance(params, list) else None,
        )

    @staticmethod
    def _connection_base(node: NmosNode, device_id: str) -> str | None:
        device = node.data.devices.get(device_id) if node.data else None
        return _reach(device.connection_href, node) if device and device.connection_href else None

    async def _probe_web(self, node: NmosNode) -> None:
        """Does the device serve a web page on port 80? One read-only GET; JSON (the NMOS API itself) does not count."""
        node.web_checked = time.monotonic()
        node.web_url = None
        try:
            async with self._http().get(f"http://{node.host}/", timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                if resp.status < 400 and "html" in resp.headers.get("Content-Type", "").lower():
                    node.web_url = f"http://{node.host}/"
        except (aiohttp.ClientError, TimeoutError, OSError):
            pass

    async def _poll_node(self, node: NmosNode) -> None:
        try:
            if node.full_due or node.data is None or not node.online:
                await self._read_all(node)
            else:
                await self._read_fast(node)
        except CannotConnect as err:
            node.failures += 1
            node.last_error = short(err)
            if node.online and node.failures >= OFFLINE_AFTER:
                _LOGGER.info("NMOS node %s went offline: %s", node.name, node.last_error)
                node.online = False
            elif node.data is None:
                node.online = False
            if not node.online and node.alt:  # the device has another address: try that one next time
                other = sorted(node.alt)[0]
                node.alt.discard(other)
                node.alt.add((node.host, node.port))
                node.host, node.port = other
                node.full_due, node.polls = True, 0
            return
        if not node.online and node.failures:
            _LOGGER.info("NMOS node %s is back online", node.name)
        node.online, node.failures, node.last_error, node.last_seen = True, 0, None, time.time()

    def _reindex(self) -> None:
        self._senders = {}
        for node in self.devices.values():
            if node.data is None:
                continue
            for group in node.sources.values():
                for _, sender_id in group.ordered():
                    self._senders[sender_id] = (node, group.name)

    # ------------------------------------------------------------- interface
    async def async_get_info(self) -> DeviceInfo:
        return DeviceInfo(name="ST 2110", manufacturer=self.MANUFACTURER, model=self.NETWORK_MODEL)

    async def async_get_sources(self) -> list[SourceSighting]:
        return [
            SourceSighting(nmos.source_id(group, node.name), f"{node.host}:{node.port}")
            for node in self.visible_devices()
            if node.online
            for group in node.sources
        ]

    def destinations(self) -> list[DestinationInfo]:
        out = []
        for node in self.visible_devices():
            single = len(node.dests) == 1
            for group in node.dests.values():
                out.append(DestinationInfo(nmos.dest_id(node.name, group.name), None if single else group.name, device=node.name))
                if self.audio_breakaway and nmos.AUDIO in group.kinds() and group.primary != nmos.AUDIO:
                    out.append(
                        DestinationInfo(
                            nmos.dest_id(node.name, group.name, audio=True), f"{group.name} · nur Ton", device=node.name
                        )
                    )
        return out

    def destination_available(self, destination: str) -> bool:
        node = self._node_of(destination)
        return bool(node and node.online)

    def _dest(self, destination: str) -> tuple[NmosNode, nmos.Group, bool]:
        try:
            name, group_name, audio = nmos.split_dest(destination)
        except ValueError as err:
            raise RouteFailed(str(err)) from err
        node = self.devices.get(name)
        if node is None:
            raise RouteFailed(f"unbekanntes ST-2110-Gerät {name}")
        group = node.dests.get(group_name)
        if group is None:
            raise RouteFailed(f"{name} hat keinen Ausgang {group_name!r}")
        return node, group, audio

    def _targets(self, group: nmos.Group, audio: bool) -> list[tuple[tuple[str, int], str]]:
        return [(layer, rid) for layer, rid in group.ordered() if not audio or layer[0] == nmos.AUDIO]

    def _source_of(self, node: NmosNode, receiver_id: str) -> str | None:
        """Matrix source id of what ``receiver_id`` is connected to (None = nothing)."""
        conn = node.conn.get(receiver_id)
        if conn is None or not conn.enabled:
            return None
        if conn.sender_id is None:
            return f"{nmos.EXTERNAL_PREFIX}{receiver_id}"
        hit = self._senders.get(conn.sender_id)
        if hit is None:
            return f"{nmos.UNKNOWN_SENDER_PREFIX}{conn.sender_id}"
        return nmos.source_id(hit[1], hit[0].name)

    def _current(self, node: NmosNode, group: nmos.Group, audio: bool) -> str | None:
        targets = self._targets(group, audio)
        return self._source_of(node, targets[0][1]) if targets else None

    async def async_get_current(self, destination: str) -> str | None:
        try:
            node, group, audio = self._dest(destination)
        except RouteFailed:
            return None
        return self._current(node, group, audio)

    def _status(self, node: NmosNode, group: nmos.Group, audio: bool) -> DestinationStatus:
        targets = self._targets(group, audio)
        layers: dict[str, str | None] = {}
        for (kind, index), rid in targets:
            layers[f"{kind}{index + 1 if index else ''}"] = self._source_of(node, rid)
        current = next(iter(layers.values()), None)
        extra: dict[str, Any] = {
            "layers": layers,
            # other layers follow another source than the primary one (audio breakaway) …
            "breakaway": any(v is not None and v != current for v in layers.values()),
            # … or are not connected at all although the primary layer is (e.g. the source has no audio)
            "partial": current is not None and any(v is None for v in layers.values()),
            "preview": "none",
            "ptp": node.ptp,
        }
        if current is None:
            return DestinationStatus(connected=False, state=ConnectionState.NO_SOURCE, extra=extra)
        conn = node.conn[targets[0][1]]
        hit = self._senders.get(conn.sender_id or "")
        if hit is None:
            # connected by someone else to a sender we do not know: we cannot tell whether it is alive
            return DestinationStatus(connected=None, resolution="ST 2110", extra=extra)
        sender_node = hit[0]
        sender = sender_node.data.senders[conn.sender_id] if sender_node.data else None  # type: ignore[index]
        flow = sender.flow if sender else None
        extra["format"] = flow.text if flow else None
        extra["media_type"] = flow.media_type if flow else None
        resolution = (flow.resolution if flow else None) or "ST 2110"
        if not sender_node.online:
            extra["detail"] = f"{sender_node.name} ist offline"
            return DestinationStatus(connected=False, resolution=resolution, state=ConnectionState.SOURCE_LOST, extra=extra)
        if sender is not None and sender.active is False:
            extra["detail"] = "Der Sender ist ausgeschaltet (sendet nicht)"
            return DestinationStatus(connected=False, resolution=resolution, state=ConnectionState.SOURCE_LOST, extra=extra)
        return DestinationStatus(connected=True, resolution=resolution, state=ConnectionState.CONNECTED, extra=extra)

    async def async_get_status(self, destination: str) -> DestinationStatus:
        try:
            node, group, audio = self._dest(destination)
        except RouteFailed:
            return DestinationStatus()
        return self._status(node, group, audio)

    async def async_refresh_sources(self) -> None:
        """Re-read everything on the next poll (also retries offline nodes)."""
        for info in self._pending.values():
            info["next"] = 0
        for node in self.devices.values():
            node.full_due, node.polls = True, 0

    async def async_poll(self) -> DevicePoll:
        async with self._poll_lock:
            if self.registries and (self._registry_due or self._polls % REGISTRY_EVERY == 0):
                self._registry_due = False
                await self._poll_registries()
            self._polls += 1
            await self._discover_pending()
            sem = asyncio.Semaphore(MAX_PARALLEL)

            async def one(node: NmosNode) -> None:
                async with sem:
                    if not node.online and node.polls > 0 and node.polls % OFFLINE_RETRY_EVERY:
                        node.polls += 1  # offline: retry only every few polls
                        return
                    if node.polls and node.polls % FULL_EVERY == 0:
                        node.full_due = True
                    node.polls += 1
                    async with node.lock:
                        await self._poll_node(node)

            await asyncio.gather(*(one(n) for n in list(self.devices.values()) if n.name not in self.hidden))
            self._name_all()  # labels may have changed (renamed in the device's setup tool)
            self._reindex()
            self._note_external()
        poll = DevicePoll(sources=await self.async_get_sources())
        for info in self.destinations():
            node, group, audio = self._dest(info.id)
            poll.destinations[info.id] = DestinationState(self._current(node, group, audio), self._status(node, group, audio))
        return poll

    def _note_external(self) -> None:
        """Which destinations were switched since the last poll by someone else (another NMOS controller, the
        device's own menu)? Compared is the primary receiver's ``(sender, enabled)``, never names – a renamed
        device or a sender that only now became known is not a switch."""
        seen: dict[str, tuple[tuple[str | None, bool], str | None]] = {}
        for info in self.destinations():
            node, group, audio = self._dest(info.id)
            targets = self._targets(group, audio)
            conn = node.conn.get(targets[0][1]) if targets else None
            if conn is None or not node.online:
                if info.id in self._seen:
                    seen[info.id] = self._seen[info.id]  # offline: nothing is known, nothing changed
                continue
            rid = targets[0][1]
            key = (conn.sender_id if conn.enabled else None, conn.enabled)
            source = self._source_of(node, rid)
            before = self._seen.get(info.id)
            if before is not None and before[0] != key and rid not in self._own:
                self._external.append((info.id, before[1], source))
                _LOGGER.info("%s was switched by another controller: %s → %s", info.id, before[1], source)
            seen[info.id] = (key, source)
        self._seen = seen
        self._own.clear()
        del self._external[:-64]

    def pop_external_changes(self) -> list[tuple[str, str | None, str | None]]:
        """``(destination id, source before, source now)`` for every switch this driver did not make itself,
        since the last call. The hub logs them (origin "extern") and keeps its undo history in step."""
        changes, self._external = self._external, []
        return changes

    def clock_summary(self) -> dict[str, Any]:
        """PTP as the devices report it (IS-04 ``clocks``): who is the grandmaster, do all follow the same one?"""
        online = [n for n in self.visible_devices() if n.online]
        reporting = [(n, n.ptp) for n in online if n.ptp]
        masters: dict[str, dict[str, Any]] = {}
        for node, ptp in reporting:
            cid = nmos.clock_id(ptp["grandmaster"])
            if cid is None:
                continue
            entry = masters.setdefault(cid, {"id": ptp["grandmaster"], "device": None, "followers": []})
            entry["followers"].append(node.name)
        for cid, entry in masters.items():  # is the grandmaster one of the devices we see?
            owner = next((n for n in online if n.data and nmos.is_own_clock(cid, n.data.macs)), None)
            entry["device"] = owner.name if owner else None
        return {
            "grandmasters": sorted(masters.values(), key=lambda m: -len(m["followers"])),
            # None = fewer than two devices report a grandmaster: nothing to compare
            "same": (len(masters) == 1) if sum(len(m["followers"]) for m in masters.values()) >= 2 else None,
            "unlocked": [n.name for n, ptp in reporting if ptp["locked"] is False],
            "no_ptp": [n.name for n in online if not n.ptp],
            "no_grandmaster": [n.name for n, ptp in reporting if nmos.clock_id(ptp["grandmaster"]) is None],
        }

    # --------------------------------------------------------------- routing
    def find_source(self, source: str) -> tuple[NmosNode, nmos.Group] | None:
        try:
            group_name, device = nmos.split_source(source)
        except ValueError:
            return None
        node = self.devices.get(device)
        group = node.sources.get(group_name) if node else None
        return (node, group) if node and group else None

    def source_info(self, source: str) -> dict[str, Any]:
        """Details of a source for user interfaces: essences, format, compressed?, and: no preview."""
        info: dict[str, Any] = {"preview": "none", "preview_reason": "ST 2110 wird nicht empfangen – keine Vorschau verfügbar"}
        hit = self.find_source(source)
        if hit is None or hit[0].data is None:
            return info
        node, group = hit
        senders = [node.data.senders[sid] for _, sid in group.ordered() if sid in node.data.senders]
        video = next((s.flow for s in senders if s.kind in (nmos.VIDEO, nmos.MUX) and s.flow), None)
        audio = next((s.flow for s in senders if s.kind == nmos.AUDIO and s.flow), None)
        info.update(
            {
                "essences": group.kinds(),
                "format": video.text if video else (audio.text if audio else None),
                "audio_format": audio.text if audio else None,
                "media_type": video.media_type if video else None,
                "compressed": nmos.is_compressed(video.media_type) if video else None,
                "grouped_by": "bcp-002-01" if group.hinted else "labels",
                "device_type": node.device_type,
            }
        )
        return info

    def plan(self, destination: str, source: str | None) -> list[Step]:
        """What routing ``source`` to ``destination`` would do, layer by layer. Raises RouteFailed with the reason."""
        node, group, audio = self._dest(destination)
        if node.data is None:
            raise RouteFailed(f"{node.name} ist noch nicht gelesen")
        targets = self._targets(group, audio)
        if not targets:
            raise RouteFailed(f"{node.name} hat an diesem Ausgang keinen Ton-Empfänger")
        receivers = node.data.receivers
        if source is None:
            return [Step(layer, receivers[rid]) for layer, rid in targets]
        if source.startswith((nmos.UNKNOWN_SENDER_PREFIX, nmos.EXTERNAL_PREFIX)):
            remembered = self._remembered.get(f"{targets[0][1]}|{source}")
            if remembered is None:
                raise RouteFailed(
                    "Diese fremde Verbindung lässt sich nicht wiederherstellen (ihre Daten sind nicht mehr bekannt)"
                )
            return [Step(targets[0][0], receivers[targets[0][1]], restore=remembered)]
        hit = self.find_source(source)
        if hit is None or hit[0].data is None:
            raise RouteFailed(f"Quelle {source} ist nicht im Netz")
        sender_node, sgroup = hit
        if not sender_node.online:
            raise RouteFailed(f"Quelle {source}: {sender_node.name} ist offline")
        steps: list[Step] = []
        for position, (layer, rid) in enumerate(targets):
            receiver = receivers[rid]
            title = nmos.KIND_TITLE.get(layer[0], layer[0])
            sender = sender_node.data.senders.get(sgroup.layers.get(layer, ""))
            reason = None
            if sender is None:
                reason = (
                    f"Quelle hat {'kein' if layer[0] == nmos.VIDEO else 'keine' if layer[0] == nmos.DATA else 'keinen'} {title}"
                )
            elif self.check_compat:
                reason = nmos.check_compat(sender, receiver)
            if reason and position == 0:  # the primary layer decides: nothing is switched
                raise RouteFailed(reason if sender is None else f"passt nicht: {reason}")
            if reason:
                steps.append(Step(layer, receiver, note=reason))  # this layer is disconnected, with a reason
            else:
                steps.append(Step(layer, receiver, sender=sender, sender_node=sender_node))
        return steps

    async def async_route(self, destination: str, source: str | None, address: str | None = None) -> None:
        node, _, _ = self._dest(destination)
        if not node.online:
            raise RouteFailed(f"{node.name} ist offline")
        async with node.lock:
            steps = self.plan(destination, source)
            before: dict[str, Conn | None] = {}
            for step in steps:
                try:
                    before[step.receiver.id] = await self._read_active(node, step.receiver)
                except CannotConnect:
                    before[step.receiver.id] = None
            self._remember(node, before)
            done: list[Step] = []
            switched = len(self.switched_on)
            try:
                for step in steps:
                    await self._apply(node, step)
                    done.append(step)
                    if step.note:
                        _LOGGER.info("%s: %s not connected (%s)", destination, step.layer[0], step.note)
            except RouteFailed as err:
                node.full_due = True
                for device, sender_id in self.switched_on[switched:]:  # leave senders as we found them
                    try:
                        await self.async_set_sender(device, sender_id, False)
                    except RouteFailed:
                        pass
                del self.switched_on[switched:]
                if done:  # all or nothing: put the layers back that were already switched
                    restored = await self._rollback(node, done, before)
                    raise RouteFailed(
                        f"{short(err, 92)} – {'zurückgestellt' if restored else 'Zurückstellen fehlgeschlagen'}"
                    ) from err
                raise
            node.full_due = True  # the next poll re-reads IS-05 ``active`` of all receivers

    def _remember(self, node: NmosNode, before: Mapping[str, Conn | None]) -> None:
        """Keep the data of connections we could not rebuild from the network (for undo)."""
        for rid, conn in before.items():
            if conn is None or not conn.enabled or (conn.sender_id and conn.sender_id in self._senders):
                continue
            node.conn[rid] = conn
            placeholder = self._source_of(node, rid)
            if placeholder:
                self._remembered[f"{rid}|{placeholder}"] = conn

    async def _rollback(self, node: NmosNode, done: list[Step], before: Mapping[str, Conn | None]) -> bool:
        ok = True
        for step in reversed(done):
            previous = before.get(step.receiver.id)
            if previous is None:
                ok = False
                continue
            try:
                await self._apply(node, Step(step.layer, step.receiver, restore=previous))
            except RouteFailed as err:
                _LOGGER.warning("%s: could not restore %s: %s", node.name, step.receiver.label, err)
                ok = False
        return ok

    async def _apply(self, node: NmosNode, step: Step) -> None:
        receiver = step.receiver
        base = self._connection_base(node, receiver.device_id)
        if base is None:
            raise RouteFailed(f"{node.name} hat keine Schaltschnittstelle (IS-05)")
        url = f"{base}/single/receivers/{receiver.id}"
        if step.restore is not None:
            conn = step.restore
            body: dict[str, Any] = {"sender_id": conn.sender_id, "master_enable": conn.enabled, "activation": IMMEDIATE}
            if conn.sdp:
                body["transport_file"] = {"data": conn.sdp, "type": "application/sdp"}
            elif conn.params and conn.enabled:
                body["transport_params"] = conn.params
            await self._send(node, receiver, url, [("restore", body)], conn.sender_id, conn.enabled)
            return
        if step.sender is None:
            body = {"sender_id": None, "master_enable": False, "activation": IMMEDIATE}
            await self._send(node, receiver, url, [("off", body)], None, False)
            return
        sender, sender_node = step.sender, step.sender_node
        assert sender_node is not None
        await self._ensure_sending(sender_node, sender)
        sdp = await self._sdp(sender_node, sender)
        attempts: list[tuple[str, dict[str, Any]]] = []
        # Once a device has accepted one way of describing a connection, only that way is used: from then on a
        # rejection is a real "no" and must not be worked around. Before that, all ways are tried in order.
        modes = (node.patch_mode,) if node.patch_mode else PATCH_MODES
        for mode in modes:
            body = {"sender_id": sender.id, "master_enable": True, "activation": IMMEDIATE}
            if mode == "sdp":
                if not sdp:
                    continue
                body["transport_file"] = {"data": sdp, "type": "application/sdp"}
            elif mode == "params":
                params = await self._params_from_sdp(url, sdp) if sdp else None
                if not params:
                    continue
                body["transport_params"] = params
            attempts.append((mode, body))
        mode = await self._send(node, receiver, url, attempts, sender.id, True)
        if mode in PATCH_MODES and mode != node.patch_mode:
            _LOGGER.info("%s accepts connections as %r", node.name, mode)
            node.patch_mode = mode

    async def _send(
        self,
        node: NmosNode,
        receiver: nmos.Receiver,
        url: str,
        attempts: list[tuple[str, dict[str, Any]]],
        sender_id: str | None,
        enabled: bool,
    ) -> str:
        """PATCH ``/staged`` (one attempt after the other until one is accepted **and** became active)."""
        problem = "keine passende Art, die Verbindung zu beschreiben"
        for mode, body in attempts:
            status, payload = await self._patch(f"{url}/staged", body)
            if status == 423:
                raise RouteFailed(f"{node.name} ist gerade gesperrt (ein anderer Controller schaltet)")
            if status not in (200, 202):
                problem = f"{node.name} lehnt ab ({status}): {_error_text(payload)}"
                continue
            for delay in VERIFY_DELAYS:
                await asyncio.sleep(delay)
                try:
                    active = await self._read_active(node, receiver)
                except CannotConnect as err:
                    problem = f"{node.name}: Zustand nicht lesbar ({short(err, 60)})"
                    continue
                if active.enabled == enabled and (not enabled or active.sender_id == sender_id):
                    self._own.add(receiver.id)
                    node.conn[receiver.id] = active
                    receiver.sender_id, receiver.active = active.sender_id, active.enabled
                    return mode
                problem = f"{node.name} hat die Verbindung angenommen, aber nicht aktiviert"
        raise RouteFailed(problem)

    async def _ensure_sending(self, node: NmosNode, sender: nmos.Sender) -> None:
        """A sender whose ``master_enable`` is off sends nothing: switch it on (option ``enable_senders``)."""
        if sender.active is True or not self.enable_senders:
            return
        base = self._connection_base(node, sender.device_id)
        if base is None:
            return
        url = f"{base}/single/senders/{sender.id}"
        try:
            active = await self._get(f"{url}/active")
        except CannotConnect:
            return
        if not isinstance(active, dict) or active.get("master_enable") is not False:
            sender.active = True if isinstance(active, dict) and active.get("master_enable") else sender.active
            return
        status, payload = await self._patch(f"{url}/staged", {"master_enable": True, "activation": IMMEDIATE})
        if status not in (200, 202):
            raise RouteFailed(
                f"{node.name}: Sender {sender.label} ist aus und lässt sich nicht einschalten ({_error_text(payload)})"
            )
        sender.active = True
        self.switched_on.append((node.name, sender.id))
        _LOGGER.info("%s: sender %s switched on", node.name, sender.label)

    async def async_set_sender(self, device: str, sender_id: str, enabled: bool) -> None:
        """Switch a sender's ``master_enable`` (used by ``nmos-check`` to put things back after a test)."""
        node = self.devices.get(device)
        sender = node.data.senders.get(sender_id) if node and node.data else None
        base = self._connection_base(node, sender.device_id) if node and sender else None
        if node is None or sender is None or base is None:
            raise RouteFailed(f"unbekannter Sender {sender_id} an {device}")
        status, payload = await self._patch(
            f"{base}/single/senders/{sender.id}/staged", {"master_enable": enabled, "activation": IMMEDIATE}
        )
        if status not in (200, 202):
            raise RouteFailed(f"{node.name}: Sender {sender.label} lässt sich nicht umschalten ({_error_text(payload)})")
        sender.active = enabled

    async def async_snapshot(self, destination: str) -> dict[str, Conn]:
        """Exact IS-05 state of every receiver behind ``destination`` (to restore it later, see ``async_restore``)."""
        node, group, audio = self._dest(destination)
        assert node.data is not None
        return {rid: await self._read_active(node, node.data.receivers[rid]) for _, rid in self._targets(group, audio)}

    async def async_restore(self, destination: str, snapshot: Mapping[str, Conn]) -> None:
        """Put the receivers behind ``destination`` back exactly as ``async_snapshot`` found them."""
        node, group, audio = self._dest(destination)
        assert node.data is not None
        async with node.lock:
            for layer, rid in self._targets(group, audio):
                if rid in snapshot:
                    await self._apply(node, Step(layer, node.data.receivers[rid], restore=snapshot[rid]))
            node.full_due = True

    async def _sdp(self, node: NmosNode, sender: nmos.Sender) -> str | None:
        """The sender's transport file (SDP): IS-04 ``manifest_href``, else the IS-05 ``/transportfile``."""
        urls = [_reach(sender.manifest_href, node)] if sender.manifest_href else []
        base = self._connection_base(node, sender.device_id)
        if base:
            urls.append(f"{base}/single/senders/{sender.id}/transportfile")
        for url in urls:
            try:
                text = await self._get(url, text=True)
            except CannotConnect:
                continue
            if nmos.is_sdp(text):
                return text
        return None

    async def _params_from_sdp(self, receiver_url: str, sdp: str) -> list[dict[str, Any]] | None:
        """Explicit IS-05 transport parameters for devices that do not read SDP files."""
        info = nmos.parse_sdp(sdp)
        if not info.destination or not info.port:
            return None
        try:
            staged = await self._get(f"{receiver_url}/staged")
        except CannotConnect:
            return None
        legs = len(staged.get("transport_params") or []) if isinstance(staged, dict) else 0
        multicast = info.destination.split(".")[0].isdigit() and 224 <= int(info.destination.split(".")[0]) <= 239
        first = {
            "rtp_enabled": True,
            "destination_port": info.port,
            "multicast_ip": info.destination if multicast else None,
            "source_ip": info.source if multicast else info.destination,
            "interface_ip": "auto",
        }
        return [first] + [{"rtp_enabled": False} for _ in range(max(legs, 1) - 1)]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "devices": [node.as_dict() for node in self.visible_devices()],
            "registries": self.registries,
            "registrations": sorted(self.registrations),
            "clock": self.clock_summary(),
            "pending": [f"{host}:{port or '?'}" for host, port in self._pending],
            "options": {
                CONF_AUDIO_BREAKAWAY: self.audio_breakaway,
                CONF_CHECK_COMPAT: self.check_compat,
                CONF_ENABLE_SENDERS: self.enable_senders,
                CONF_STATIC_HOSTS: self.static_hosts,
            },
        }


def _pin_host(url: str, host: str) -> str:
    """Devices may give URLs with their mDNS name (``http://box.local:8090/…``), which a Raspberry Pi cannot
    always resolve. A name is replaced by the address the node answers on; literal IP addresses stay as they are."""
    scheme, sep, rest = url.partition("://")
    netloc, slash, path = rest.partition("/")
    name, colon, port = netloc.rpartition(":") if ":" in netloc else (netloc, "", "")
    if not sep or name.replace(".", "").isdigit() or name.startswith("["):
        return url
    return f"{scheme}://{host}{colon}{port}{slash}{path}"


def _reach(url: str, node: NmosNode) -> str:
    """A URL the node gave us, made reachable: names become ``node.host`` (``_pin_host``); and when we talk to
    the node over an address it does not advertise itself (its control port), a URL pointing at one of its
    advertised media addresses is redirected to ``node.host`` too – the port stays as given."""
    url = _pin_host(url, node.host)
    if not node.advertised or node.host in node.advertised:
        return url
    scheme, sep, rest = url.partition("://")
    netloc, slash, path = rest.partition("/")
    name, colon, port = netloc.rpartition(":") if ":" in netloc else (netloc, "", "")
    if not sep or name not in node.advertised:
        return url
    return f"{scheme}://{node.host}{colon}{port}{slash}{path}"


def _hostname(me: dict[str, Any]) -> str:
    return str(me.get("hostname") or "").removesuffix(".").removesuffix(".local")


def _keep_sdp(new: Conn, old: Conn | None) -> Conn:
    if old is not None and old.sender_id == new.sender_id and old.enabled == new.enabled:
        new.sdp, new.params = old.sdp, old.params
    return new


def _where(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def _error_text(payload: Any) -> str:
    """IS-05 errors are ``{"code", "error", "debug"}``; show the device's own words."""
    if isinstance(payload, dict):
        return short(payload.get("error") or payload.get("debug") or "ohne Begründung", 70)
    return "ohne Begründung"


def _registry_url(url: Any) -> str:
    """``"192.0.2.5:8010"`` or ``"http://192.0.2.5:8010/"`` → ``"http://192.0.2.5:8010"``."""
    text = str(url).strip().rstrip("/")
    return text if text.startswith(("http://", "https://")) else f"http://{text}"


def _node_endpoints(raw: Any) -> list[tuple[str, int, str]]:
    """Every address of a node as a registry lists it (``api.endpoints``; IPv4 literals first, no IPv6).

    A device with several interfaces (media ports and a control port) lists them all, and not every one is
    reachable from here – so all are tried. ``href`` is the fallback for registries that leave ``api`` out."""
    if not isinstance(raw, dict):
        return []
    endpoints = (raw.get("api") or {}).get("endpoints") if isinstance(raw.get("api"), dict) else None
    out: list[tuple[str, int, str]] = []
    for ep in endpoints if isinstance(endpoints, list) else []:
        if not isinstance(ep, dict) or not ep.get("host") or not ep.get("port") or ":" in str(ep["host"]):
            continue
        try:
            candidate = (str(ep["host"]), int(ep["port"]), str(ep.get("protocol") or "http"))
        except (TypeError, ValueError):
            continue
        if candidate not in out:
            out.append(candidate)
    out.sort(key=lambda c: not c[0].replace(".", "").isdigit())
    if not out and isinstance(raw.get("href"), str):
        host, port = split_host(raw["href"])
        if host:
            out.append((host, port or 80, "https" if raw["href"].startswith("https") else "http"))
    return out[:8]
