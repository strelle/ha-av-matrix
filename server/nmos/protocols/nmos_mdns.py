"""mDNS / DNS-SD discovery of NMOS nodes and registries (python-zeroconf).

* ``_nmos-node._tcp``  – every instance is a node (IS-04 peer-to-peer mode); TXT: ``api_proto``, ``api_ver``,
  ``api_auth`` and, without a registry, the change counters ``ver_slf`` … ``ver_rcv``.
* ``_nmos-query._tcp`` – an IS-04 registry offering the Query API (optional).

Works with a zeroconf instance of its own (stand-alone server, ``nmos-check``) or a shared one (Home Assistant:
pass ``(await zeroconf.async_get_async_instance(hass)).zeroconf``). Imports nothing but zeroconf, and is only
imported by the code that starts discovery – the driver itself does not need it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Protocol

from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from .nmos import NODE_SERVICE_TYPE, QUERY_SERVICE_TYPE

_LOGGER = logging.getLogger(__name__)
RESOLVE_TIMEOUT_MS = 3000


class NodeSink(Protocol):
    """What the browser needs from the driver (``drivers.nmos.NmosNetwork`` has exactly these)."""

    def add_host(
        self, host: str, port: int | None = None, props: Any = None, *, mdns: bool = False, registry: bool = False
    ) -> None: ...
    def mdns_removed(self, host: str | None, port: int | None = None) -> None: ...
    def add_registry(self, url: str, *, mdns: bool = True) -> None: ...
    def remove_registry(self, url: str) -> None: ...


def txt(props: dict[bytes, bytes | None] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (props or {}).items():
        try:
            out[key.decode()] = value.decode() if value is not None else ""
        except (AttributeError, UnicodeDecodeError):
            continue
    return out


class NmosBrowser:
    """Browse for NMOS nodes and registries and hand them to the driver.

    ``sink`` returns the running driver or ``None`` (network entry not set up yet). Everything seen is kept in
    ``nodes`` / ``registries`` so a driver that starts later gets it via ``feed()``.
    """

    def __init__(
        self, zeroconf: Zeroconf, sink: Callable[[], NodeSink | None], on_change: Callable[[], None] | None = None
    ) -> None:
        self._zc = zeroconf
        self._sink = sink
        self._on_change = on_change or (lambda: None)
        self._browser: AsyncServiceBrowser | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        #: mDNS instance name → (host, port, TXT)
        self.nodes: dict[str, tuple[str, int, dict[str, str]]] = {}
        #: mDNS instance name → base URL
        self.registries: dict[str, str] = {}

    async def async_start(self) -> None:
        self._browser = AsyncServiceBrowser(self._zc, [NODE_SERVICE_TYPE, QUERY_SERVICE_TYPE], handlers=[self._handler])

    async def async_stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._browser is not None:
            await self._browser.async_cancel()
            self._browser = None

    def feed(self, sink: NodeSink) -> None:
        """Hand everything seen so far to a (re)started driver."""
        for host, port, props in self.nodes.values():
            sink.add_host(host, port, props, mdns=True)
        for url in self.registries.values():
            sink.add_registry(url, mdns=True)

    def _handler(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change is ServiceStateChange.Removed:
            sink = self._sink()
            if service_type == NODE_SERVICE_TYPE:
                gone = self.nodes.pop(name, None)
                if gone and sink is not None:
                    sink.mdns_removed(gone[0], gone[1])
            else:
                url = self.registries.pop(name, None)
                if url and sink is not None:
                    sink.remove_registry(url)
            self._on_change()
            return
        task = asyncio.ensure_future(self._resolve(service_type, name))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _resolve(self, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        try:
            if not await info.async_request(self._zc, RESOLVE_TIMEOUT_MS):
                return
        except Exception as err:  # noqa: BLE001 - discovery must never crash
            _LOGGER.debug("Could not resolve %s: %s", name, err)
            return
        addresses = info.parsed_addresses(IPVersion.V4Only)
        addresses = [a for a in addresses if not a.startswith("127.")] or addresses
        if not addresses or not info.port:
            return
        props = txt(info.properties)
        sink = self._sink()
        if service_type == NODE_SERVICE_TYPE:
            self.nodes[name] = (addresses[0], info.port, props)
            if sink is not None:
                sink.add_host(addresses[0], info.port, props, mdns=True)
        else:
            scheme = "https" if props.get("api_proto") == "https" else "http"
            url = f"{scheme}://{addresses[0]}:{info.port}"
            self.registries[name] = url
            if sink is not None:
                sink.add_registry(url, mdns=True)
        self._on_change()
