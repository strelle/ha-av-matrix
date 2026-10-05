"""Dante® network driver: all Dante devices of the network behind one config entry.

* Devices are announced via mDNS (``_netaudio-arc._udp``, fed in by ``discovery.DanteMdnsBrowser``)
  or configured as static hosts. Dante control has no login (Dante Domain Manager aside).
* Every TX channel of every online device is a source (``"<channel>@<device>"``),
  every RX channel is a destination (``"<device>:<rx number>"``).
* Routing sets / clears the subscription of an RX channel via ARC (UDP 4440).

Unofficial implementation of a reverse-engineered protocol (see protocols/dante.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..models import (
    ConnectionState,
    DestinationInfo,
    DestinationState,
    DestinationStatus,
    DeviceInfo,
    DevicePoll,
    SourceSighting,
)
from ..protocols import dante as arc
from .base import CannotConnect, Driver, RouteFailed, short

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 1.0
RETRIES = 1
#: Minimum gap between two requests to the same device (be gentle with small embedded devices).
REQUEST_SPACING = 0.01
#: Devices polled in parallel.
MAX_PARALLEL = 6
#: Re-read channel names/counts every N polls (subscriptions are read every poll).
NAMES_EVERY = 6
#: Offline devices are retried every N polls.
OFFLINE_RETRY_EVERY = 4
CONF_STATIC_HOSTS = "static_hosts"
CONF_HIDDEN_DEVICES = "hidden_devices"
CONF_ONLY_SELECTED = "only_selected"
CONF_RX_SELECTED = "rx_selected"
#: Pauses before reading a subscription back after writing it.
VERIFY_DELAYS = (0.0, 0.3)
#: Devices with more RX channels get their entities disabled by default.
LARGE_DEVICE_RX = 32


def dest_id(device: str, rx: int) -> str:
    return f"{device}:{rx}"


def split_dest(dest: str) -> tuple[str, int]:
    device, _, number = dest.rpartition(":")
    try:
        return device, int(number)
    except ValueError as err:
        raise RouteFailed(f"unknown destination {dest!r}") from err


# ------------------------------------------------------------------- transport
class ArcTransport(asyncio.DatagramProtocol):
    """One UDP socket for all devices; answers are matched by sequence number."""

    def __init__(self) -> None:
        self._transport: asyncio.DatagramTransport | None = None
        self._waiting: dict[int, asyncio.Future[arc.Response]] = {}
        self._seq = 0
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._start_lock = asyncio.Lock()

    async def async_start(self) -> None:
        async with self._start_lock:
            if self._transport is None:
                loop = asyncio.get_running_loop()
                await loop.create_datagram_endpoint(lambda: self, local_addr=("0.0.0.0", 0))

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        for fut in self._waiting.values():
            if not fut.done():
                fut.cancel()
        self._waiting.clear()

    # asyncio.DatagramProtocol
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def connection_lost(self, exc: Exception | None) -> None:
        self._transport = None

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            resp = arc.parse_header(data)
        except arc.ArcError:
            return
        fut = self._waiting.get(resp.seq)
        if fut is not None and not fut.done():
            fut.set_result(resp)

    def next_seq(self) -> int:
        """16-bit sequence numbers, never 0, never one that is still waiting for an answer."""
        for _ in range(0x10000):
            self._seq = self._seq % 0xFFFF + 1
            if self._seq not in self._waiting:
                return self._seq
        raise CannotConnect("no free sequence number")

    async def request(
        self,
        host: str,
        port: int,
        build: Callable[[int], bytes],
        *,
        opcode: int,
        timeout: float = REQUEST_TIMEOUT,
        retries: int = RETRIES,
    ) -> arc.Response:
        """Send a request (built for a fresh sequence number), wait for the matching answer."""
        await self.async_start()
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:  # one request in flight per device + small spacing (rate limit)
            gap = REQUEST_SPACING - (time.monotonic() - self._last.get(host, 0.0))
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                for attempt in range(retries + 1):
                    seq = self.next_seq()
                    fut: asyncio.Future[arc.Response] = asyncio.get_running_loop().create_future()
                    self._waiting[seq] = fut
                    try:
                        if self._transport is None:
                            raise CannotConnect("UDP socket closed")
                        self._transport.sendto(build(seq), (host, port))
                        resp = await asyncio.wait_for(fut, timeout)
                    except TimeoutError:
                        if attempt == retries:
                            raise CannotConnect(f"{host}: no answer") from None
                        continue
                    except OSError as err:
                        raise CannotConnect(f"{host}: {short(err)}") from err
                    finally:
                        self._waiting.pop(seq, None)
                    if resp.opcode != opcode:
                        raise CannotConnect(f"{host}: unexpected answer {resp.opcode:#06x}")
                    return resp
            finally:
                self._last[host] = time.monotonic()
        raise CannotConnect(f"{host}: no answer")  # pragma: no cover


# ---------------------------------------------------------------------- device
@dataclass(slots=True)
class DanteDevice:
    """What we know about one Dante device."""

    name: str
    host: str
    port: int = arc.ARC_PORT
    protocol_id: int = arc.PROTOCOL_LEGACY
    protocol_known: bool = False  # from mDNS (static hosts: learnt on the first write)
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    via_mdns: bool = False
    online: bool = False
    tx_count: int = 0
    rx_count: int = 0
    tx: list[arc.TxChannel] = field(default_factory=list)
    rx: list[arc.RxChannel] = field(default_factory=list)
    sample_rate: int | None = None
    polls: int = 0
    failures: int = 0
    last_error: str | None = None
    last_seen: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """Diagnostics."""
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "arc_protocol": f"{self.protocol_id:#06x}",
            "manufacturer": self.manufacturer,
            "model": self.model,
            "firmware": self.firmware,
            "mdns": self.via_mdns,
            "online": self.online,
            "tx_count": self.tx_count,
            "rx_count": self.rx_count,
            "sample_rate": self.sample_rate,
            "tx": [{"n": c.number, "name": c.name, "label": c.friendly_name} for c in self.tx],
            "rx": [
                {
                    "n": c.number,
                    "name": c.name,
                    "tx_channel": c.tx_channel,
                    "tx_device": c.tx_device,
                    "status": f"{c.status:#06x}",
                    "rx_status": f"{c.rx_status:#06x}",
                }
                for c in self.rx
            ],
            "failures": self.failures,
            "last_error": self.last_error,
        }


def model_from_txt(props: Mapping[str, str]) -> str | None:
    """mDNS TXT ``model`` (sometimes a cryptic id like ``_0000000020240403``) or ``router_info``."""
    model = props.get("model")
    if model and not model.startswith("_"):
        return model
    return props.get("router_info") or model


class DanteNetwork(Driver):
    """All Dante devices of the network (one config entry)."""

    KEY = "dante"
    PROTOCOL = "dante"
    TITLE = "network – all devices, found automatically"
    MANUFACTURER = "Audinate"
    DEFAULT_PORT = arc.ARC_PORT
    CONFIG_FIELDS = ()
    TRUSTED_SOURCE_LIST = True
    SETTLE_TIME = 3.0
    #: One config entry for a whole network instead of one per device.
    NETWORK: ClassVar[bool] = True
    LARGE_DEVICE_RX: ClassVar[int] = LARGE_DEVICE_RX

    def __init__(
        self,
        session: Any,
        config: Mapping[str, Any],
        timeout: float = REQUEST_TIMEOUT,
        *,
        options: Mapping[str, Any] | None = None,
        transport: ArcTransport | None = None,
    ) -> None:
        self._session = session
        self.config = dict(config)
        self.host = "dante"
        self.port = arc.ARC_PORT
        self.timeout = timeout  # type: ignore[assignment]
        self.request_timeout = min(float(timeout), REQUEST_TIMEOUT)
        options = options or {}
        self.hidden: set[str] = set(options.get(CONF_HIDDEN_DEVICES, []))
        self.only_selected = bool(options.get(CONF_ONLY_SELECTED, False))
        self.selected: set[str] = set(options.get(CONF_RX_SELECTED, []))
        self.static_hosts: list[str] = [h for h in options.get(CONF_STATIC_HOSTS, []) if h]
        self.transport = transport or ArcTransport()
        self.devices: dict[str, DanteDevice] = {}
        self._pending_hosts: dict[str, tuple[int, dict[str, str], bool]] = {}
        self._full_refresh = True
        self._poll_lock = asyncio.Lock()

    @property
    def configuration_url(self) -> str | None:
        return None

    def close(self) -> None:
        self.transport.close()

    # ------------------------------------------------------------- discovery
    def add_host(
        self, host: str, port: int | None = None, props: Mapping[str, str] | None = None, *, mdns: bool
    ) -> None:
        """A device was announced (mDNS) or configured (static). Its name is read on the next poll."""
        props = dict(props or {})
        for dev in self.devices.values():
            if dev.host == host:
                dev.port = port or dev.port
                dev.via_mdns = dev.via_mdns or mdns
                self._apply_txt(dev, props)
                return
        self._pending_hosts[host] = (port or arc.ARC_PORT, props, mdns)

    def mdns_removed(self, host: str | None, name: str | None) -> None:
        """mDNS goodbye: the device is checked on the next poll (and goes offline if it does not answer)."""
        for dev in self.devices.values():
            if dev.name == name or (host and dev.host == host):
                dev.via_mdns = False
                dev.polls = 0  # poll it right away

    @staticmethod
    def _apply_txt(dev: DanteDevice, props: Mapping[str, str]) -> None:
        if not props:
            return
        if props.get("arcp_vers"):
            dev.protocol_id = arc.arc_protocol_id(props.get("arcp_vers"))
            dev.protocol_known = True
        dev.manufacturer = props.get("mf") or dev.manufacturer
        dev.model = model_from_txt(props) or dev.model
        dev.firmware = props.get("router_vers") or dev.firmware

    # ------------------------------------------------------------- requests
    async def _req(self, dev_host: str, port: int, build: Callable[[int], bytes], opcode: int) -> arc.Response:
        resp = await self.transport.request(dev_host, port, build, opcode=opcode, timeout=self.request_timeout)
        if not resp.ok:
            raise CannotConnect(f"{dev_host}: device answered {resp.result:#06x} to {opcode:#06x}")
        return resp

    async def _read_name(self, host: str, port: int) -> str:
        try:
            return arc.parse_device_name(await self._req(host, port, arc.req_device_name, arc.OP_DEVICE_NAME))
        except arc.ArcError as err:
            raise CannotConnect(f"{host}: {err}") from err

    async def _read_names(self, dev: DanteDevice) -> None:
        resp = await self._req(dev.host, dev.port, arc.req_channel_count, arc.OP_CHANNEL_COUNT)
        dev.tx_count, dev.rx_count = arc.parse_channel_count(resp)
        tx: list[arc.TxChannel] = []
        page = 0
        while len(tx) < dev.tx_count and page < 64:
            resp = await self._req(dev.host, dev.port, lambda s, p=page: arc.req_tx_channels(s, p), arc.OP_TX_CHANNELS)
            chunk = arc.parse_tx_channels(resp)
            if not chunk:
                break
            labels_resp = await self._req(
                dev.host,
                dev.port,
                lambda s, p=page: arc.req_tx_friendly_names(s, p, dev.tx_count),
                arc.OP_TX_FRIENDLY_NAMES,
            )
            labels = arc.parse_tx_friendly_names(labels_resp)
            for ch in chunk:
                ch.friendly_name = labels.get(ch.number)
            tx += chunk
            page += 1
        dev.tx = tx
        rates = [c.sample_rate for c in tx if c.sample_rate]
        if rates:
            dev.sample_rate = rates[0]

    async def _read_rx(self, dev: DanteDevice) -> None:
        rx: list[arc.RxChannel] = []
        page = 0
        while len(rx) < dev.rx_count and page < 64:
            resp = await self._req(dev.host, dev.port, lambda s, p=page: arc.req_rx_channels(s, p), arc.OP_RX_CHANNELS)
            chunk = arc.parse_rx_channels(resp)
            if not chunk:
                break
            rx += chunk
            page += 1
            if not resp.more and len(chunk) < arc.RX_PER_PAGE:
                break
        dev.rx = rx
        if not dev.sample_rate:
            rates = [c.sample_rate for c in rx if c.sample_rate]
            dev.sample_rate = rates[0] if rates else None

    async def _poll_device(self, dev: DanteDevice, full: bool) -> None:
        try:
            if full or not dev.online:
                name = await self._read_name(dev.host, dev.port)
                if name != dev.name:  # renamed in Dante Controller
                    _LOGGER.info("Dante device %s is now called %s", dev.name, name)
                    self.devices.pop(dev.name, None)
                    dev.name = name
                    self.devices[name] = dev
                await self._read_names(dev)
            await self._read_rx(dev)
        except (CannotConnect, arc.ArcError) as err:
            dev.failures += 1
            dev.last_error = short(err)
            if dev.online:
                _LOGGER.info("Dante device %s went offline: %s", dev.name, dev.last_error)
            dev.online = False
            return
        if not dev.online and dev.failures:
            _LOGGER.info("Dante device %s is back online", dev.name)
        dev.online = True
        dev.failures = 0
        dev.last_error = None
        dev.last_seen = time.time()

    async def _discover_pending(self) -> None:
        pending = dict(self._pending_hosts)
        for host in self.static_hosts:
            if host not in pending and all(d.host != host for d in self.devices.values()):
                pending[host] = (arc.ARC_PORT, {}, False)
        sem = asyncio.Semaphore(MAX_PARALLEL)

        async def one(host: str, port: int, props: dict[str, str], mdns: bool) -> None:
            async with sem:
                try:
                    name = await self._read_name(host, port)
                except CannotConnect as err:
                    _LOGGER.debug("Dante host %s does not answer: %s", host, err)
                    return
            self._pending_hosts.pop(host, None)
            dev = self.devices.get(name)
            if dev is None:
                dev = self.devices[name] = DanteDevice(name=name, host=host, port=port)
            dev.host, dev.port, dev.via_mdns = host, port, dev.via_mdns or mdns
            self._apply_txt(dev, props)

        await asyncio.gather(*(one(h, *args) for h, args in pending.items()))

    # ------------------------------------------------------------- interface
    async def async_get_info(self) -> DeviceInfo:
        return DeviceInfo(name="Dante network", manufacturer="Audinate", model="Dante® network")

    async def async_get_sources(self) -> list[SourceSighting]:
        return [
            SourceSighting(arc.source_id(ch.label, dev.name), f"{dev.host}:{dev.port}")
            for dev in self.visible_devices()
            if dev.online
            for ch in dev.tx
        ]

    def visible_devices(self) -> list[DanteDevice]:
        return sorted((d for d in self.devices.values() if d.name not in self.hidden), key=lambda d: d.name.casefold())

    def destinations(self) -> list[DestinationInfo]:
        out = []
        for dev in self.visible_devices():
            for ch in dev.rx:
                did = dest_id(dev.name, ch.number)
                if self.only_selected and did not in self.selected:
                    continue
                out.append(DestinationInfo(did, ch.name, device=dev.name))
        return out

    def destination_available(self, destination: str) -> bool:
        dev = self.devices.get(split_dest(destination)[0])
        return bool(dev and dev.online)

    def device_for(self, name: str) -> DanteDevice | None:
        return self.devices.get(name)

    def _rx(self, destination: str) -> tuple[DanteDevice, arc.RxChannel]:
        name, number = split_dest(destination)
        dev = self.devices.get(name)
        if dev is None:
            raise RouteFailed(f"unknown Dante device {name}")
        ch = next((c for c in dev.rx if c.number == number), None)
        if ch is None:
            raise RouteFailed(f"{name} has no RX channel {number}")
        return dev, ch

    @staticmethod
    def _current(dev: DanteDevice, ch: arc.RxChannel) -> str | None:
        if not ch.subscribed:
            return None
        device = dev.name if ch.tx_device == "." else ch.tx_device
        return arc.source_id(ch.tx_channel or "", device or "")

    async def async_get_current(self, destination: str) -> str | None:
        try:
            dev, ch = self._rx(destination)
        except RouteFailed:
            return None
        return self._current(dev, ch)

    def _status(self, dev: DanteDevice, ch: arc.RxChannel) -> DestinationStatus:
        sub = arc.subscription_status(ch)
        state = {
            arc.SUB_SUBSCRIBED: ConnectionState.CONNECTED,
            arc.SUB_SELF: ConnectionState.CONNECTED,
            arc.SUB_NONE: ConnectionState.NO_SOURCE,
            arc.SUB_IN_PROGRESS: ConnectionState.CONNECTING,
            arc.SUB_IDLE: ConnectionState.CONNECTING,
            arc.SUB_WARNING: ConnectionState.CONNECTING,
            arc.SUB_UNRESOLVED: ConnectionState.SOURCE_LOST,
            arc.SUB_ERROR: ConnectionState.ERROR,
        }[sub.state]
        return DestinationStatus(
            connected=state is ConnectionState.CONNECTED,
            resolution=arc.format_sample_rate(ch.sample_rate or dev.sample_rate),
            state=state,
            extra={
                "subscription": sub.state,
                "subscription_code": f"{sub.code:#06x}",
                "subscription_status": sub.name,
                "subscription_detail": sub.detail,
                "rx_channel": ch.name,
                "rx_number": ch.number,
                "sample_rate": ch.sample_rate or dev.sample_rate,
            },
        )

    async def async_get_status(self, destination: str) -> DestinationStatus:
        try:
            dev, ch = self._rx(destination)
        except RouteFailed:
            return DestinationStatus()
        return self._status(dev, ch)

    async def async_refresh_sources(self) -> None:
        """Re-read names and channels of every device on the next poll (also retries offline ones)."""
        self._full_refresh = True
        for dev in self.devices.values():
            dev.polls = 0

    async def async_poll(self) -> DevicePoll:
        async with self._poll_lock:
            await self._discover_pending()
            full = self._full_refresh
            self._full_refresh = False
            sem = asyncio.Semaphore(MAX_PARALLEL)

            async def one(dev: DanteDevice) -> None:
                async with sem:
                    names_due = full or not dev.tx or dev.polls % NAMES_EVERY == 0
                    if not dev.online and dev.polls % OFFLINE_RETRY_EVERY and dev.polls > 0:
                        dev.polls += 1  # offline: retry only every few polls
                        return
                    dev.polls += 1
                    await self._poll_device(dev, names_due)

            await asyncio.gather(*(one(d) for d in list(self.devices.values()) if d.name not in self.hidden))
        poll = DevicePoll(sources=await self.async_get_sources())
        for dev in self.visible_devices():
            for ch in dev.rx:
                poll.destinations[dest_id(dev.name, ch.number)] = DestinationState(
                    current=self._current(dev, ch), status=self._status(dev, ch)
                )
        return poll

    async def async_route(self, destination: str, source: str | None, address: str | None = None) -> None:
        dev, ch = self._rx(destination)
        if not dev.online:
            raise RouteFailed(f"{dev.name} is offline")
        if source is None:
            tx_channel = tx_device = None
        else:
            try:
                tx_channel, tx_device = arc.split_source(source)
            except ValueError as err:
                raise RouteFailed(str(err)) from err
        if dev.protocol_known:
            await self._write(dev, ch.number, tx_channel, tx_device, dev.protocol_id)
        else:
            # static host without mDNS data: classic command first, paged command (ARC 2.8.9+) if ignored
            try:
                await self._write(dev, ch.number, tx_channel, tx_device, arc.PROTOCOL_LEGACY)
                await self._verify(dev, destination, source)
                dev.protocol_known = True
                return
            except RouteFailed:
                await self._write(dev, ch.number, tx_channel, tx_device, arc.MODERN_PROTOCOLS[0])
                dev.protocol_id, dev.protocol_known = arc.MODERN_PROTOCOLS[0], True
        await self._verify(dev, destination, source)

    async def _write(
        self, dev: DanteDevice, rx: int, tx_channel: str | None, tx_device: str | None, protocol_id: int
    ) -> None:
        try:
            if arc.is_modern(protocol_id):
                capacity = min(max(dev.rx_count, 1), arc.SUBSCRIPTION_PAGE_CAPACITY)
                resp = await self.transport.request(
                    dev.host,
                    dev.port,
                    lambda s: arc.req_subscription_page(s, protocol_id, capacity, [(rx, tx_channel, tx_device)]),
                    opcode=arc.OP_SUBSCRIPTION_PAGE,
                    timeout=self.request_timeout,
                )
            elif tx_channel is None or tx_device is None:
                resp = await self.transport.request(
                    dev.host,
                    dev.port,
                    lambda s: arc.req_unsubscribe_legacy(s, [rx]),
                    opcode=arc.OP_SUBSCRIPTION_REMOVE,
                    timeout=self.request_timeout,
                )
            else:
                resp = await self.transport.request(
                    dev.host,
                    dev.port,
                    lambda s: arc.req_subscribe_legacy(s, [(rx, tx_channel, tx_device)]),
                    opcode=arc.OP_SUBSCRIPTION_ADD,
                    timeout=self.request_timeout,
                )
        except arc.ArcError as err:
            raise RouteFailed(str(err)) from err
        except CannotConnect as err:
            raise RouteFailed(short(err)) from err
        if not resp.ok:
            raise RouteFailed(f"{dev.name} refused the subscription ({resp.result:#06x})")

    async def _verify(self, dev: DanteDevice, destination: str, source: str | None) -> None:
        # read back: the device stores the subscription at once (resolving the source takes longer)
        for delay in VERIFY_DELAYS:
            await asyncio.sleep(delay)
            try:
                await self._read_rx(dev)
            except (CannotConnect, arc.ArcError) as err:
                _LOGGER.debug("Read-back of %s failed: %s", destination, err)
                return
            _, after = self._rx(destination)
            if self._current(dev, after) == source:
                return
        raise RouteFailed(f"{dev.name} did not apply the subscription")
