"""mDNS: Quellen/Geräte finden und den Server selbst ankündigen (python-zeroconf, ohne Root).

* NDI®: ``_ndi._tcp.local.`` – jede Instanz ist eine Quelle.
* Dante®: ``_netaudio-arc._udp.local.`` – jede Instanz ist ein Gerät (Kanäle werden per ARC gelesen).
* ``_http._tcp.local.`` – Webserver im Netz; neue Adressen werden einmal (nur lesend) gefragt, ob sie ein
  unterstützter Decoder sind (Magewell meldet sich so) → "neuer Empfänger gefunden" im Panel.
* Ankündigung: ``<Name>._http._tcp.local.`` auf dem eigenen Port, damit das Panel per Bonjour auffindbar ist.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from typing import Any

from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from .drivers.dante import DanteNetwork
from .protocols.base import SourceRegistry
from .protocols.dante import ARC_SERVICE_TYPE
from .protocols.ndi import NDI_SERVICE_TYPE, ndi_name_from_mdns

_LOGGER = logging.getLogger(__name__)
HTTP_SERVICE_TYPE = "_http._tcp.local."


def _txt(props: dict[bytes, bytes | None]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in props.items():
        try:
            out[key.decode()] = value.decode() if value is not None else ""
        except (AttributeError, UnicodeDecodeError):
            continue
    return out


class Discovery:
    def __init__(
        self,
        *,
        interface: str | None,
        ndi_registry: SourceRegistry,
        on_change: Callable[[], None],
        dante: Callable[[], DanteNetwork | None],
        on_http_host: Callable[[str, str], Awaitable[None]] | None = None,
        nmos: Callable[[], Any] | None = None,
    ) -> None:
        self._nmos = nmos
        self.nmos_browser: Any = None
        self._interface = interface
        self._ndi = ndi_registry
        self._on_change = on_change
        self._dante = dante
        self._on_http_host = on_http_host
        self._aiozc: AsyncZeroconf | None = None
        self._browser: AsyncServiceBrowser | None = None
        self._announced: AsyncServiceInfo | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        #: Dante-Geräte, die mDNS gemeldet hat, bevor das Dante-Netzwerk eingerichtet war
        self.dante_seen: dict[str, tuple[int | None, dict[str, str]]] = {}
        self._http_seen: set[str] = set()
        #: wird gerufen, wenn sich bei den NMOS-Geräten etwas tut (der Start weckt damit den Poller)
        self.on_nmos_change: Callable[[], None] | None = None

    async def start(self) -> None:
        kwargs: dict[str, Any] = {"ip_version": IPVersion.V4Only}
        if self._interface:
            kwargs["interfaces"] = [self._interface]
        self._aiozc = AsyncZeroconf(**kwargs)
        types = [NDI_SERVICE_TYPE, ARC_SERVICE_TYPE] + ([HTTP_SERVICE_TYPE] if self._on_http_host else [])
        self._browser = AsyncServiceBrowser(self._aiozc.zeroconf, types, handlers=[self._handler])
        if self._nmos is not None:  # ST 2110: NMOS-Nodes und -Registries (_nmos-node._tcp, _nmos-query._tcp)
            try:
                from .protocols.nmos_mdns import NmosBrowser

                self.nmos_browser = NmosBrowser(self._aiozc.zeroconf, self._nmos, self._on_nmos_change)
                await self.nmos_browser.async_start()
            except Exception as err:  # noqa: BLE001 - ohne NMOS-Suche läuft alles andere weiter
                _LOGGER.warning("NMOS-Suche nicht verfügbar: %s", err)
                self.nmos_browser = None

    def _on_nmos_change(self) -> None:
        self._on_change()
        if self.on_nmos_change is not None:
            self.on_nmos_change()

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self.nmos_browser is not None:
            try:
                await self.nmos_browser.async_stop()
            except Exception:  # noqa: BLE001
                pass
        if self._aiozc is None:
            return
        if self._browser is not None:
            await self._browser.async_cancel()
        if self._announced is not None:
            try:
                await self._aiozc.async_unregister_service(self._announced)
            except Exception:  # noqa: BLE001
                pass
        await self._aiozc.async_close()
        self._aiozc = None

    async def announce(self, name: str, port: int, hostname: str, address: str, properties: dict[str, str]) -> None:
        """``<name>._http._tcp.local.`` ankündigen (Bonjour / DNS-SD)."""
        if self._aiozc is None:
            return
        info = AsyncServiceInfo(
            HTTP_SERVICE_TYPE,
            f"{name}.{HTTP_SERVICE_TYPE}",
            addresses=[socket.inet_aton(address)],
            port=port,
            properties=properties,
            server=f"{hostname}.local.",
        )
        await self._aiozc.async_register_service(info, allow_name_change=True)
        self._announced = info
        _LOGGER.info("mDNS: %s auf Port %s angekündigt", info.name, port)

    def feed_dante(self, driver: DanteNetwork) -> None:
        """Bereits gesehene Dante-Geräte an einen (neu gestarteten) Treiber übergeben."""
        for host, (port, props) in self.dante_seen.items():
            driver.add_host(host, port, props, mdns=True)

    def _spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _handler(self, zeroconf: object, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if service_type == NDI_SERVICE_TYPE:
            ndi_name = ndi_name_from_mdns(name, service_type)
            if state_change is ServiceStateChange.Removed:
                self._ndi.remove_discovered(ndi_name)
                self._on_change()
                return
            self._ndi.mark_discovered(ndi_name)
            self._on_change()
            self._spawn(self._resolve_ndi(service_type, name, ndi_name))
        elif service_type == ARC_SERVICE_TYPE:
            device = name.removesuffix("." + service_type)
            if state_change is ServiceStateChange.Removed:
                driver = self._dante()
                if driver is not None:
                    driver.mdns_removed(None, device)
                    self._on_change()
                return
            self._spawn(self._resolve_dante(service_type, name))
        elif service_type == HTTP_SERVICE_TYPE and state_change is not ServiceStateChange.Removed:
            self._spawn(self._resolve_http(service_type, name))

    async def _info(self, service_type: str, name: str) -> AsyncServiceInfo | None:
        if self._aiozc is None:
            return None
        info = AsyncServiceInfo(service_type, name)
        try:
            if not await info.async_request(self._aiozc.zeroconf, 3000):
                return None
        except Exception as err:  # noqa: BLE001 - Discovery darf nie abstürzen
            _LOGGER.debug("Konnte %s nicht auflösen: %s", name, err)
            return None
        return info

    async def _resolve_ndi(self, service_type: str, name: str, ndi_name: str) -> None:
        info = await self._info(service_type, name)
        if info is None:
            return
        addresses = info.parsed_addresses(IPVersion.V4Only) or info.parsed_addresses()
        # eine Quelle auf diesem Rechner (eigenes Testbild) meldet auch 127.0.0.1: die Netzadresse bevorzugen
        addresses = [a for a in addresses if not a.startswith("127.")] or addresses
        self._ndi.set_discovered(ndi_name, f"{addresses[0]}:{info.port}" if addresses and info.port else None)
        self._on_change()

    async def _resolve_dante(self, service_type: str, name: str) -> None:
        info = await self._info(service_type, name)
        if info is None:
            return
        addresses = info.parsed_addresses(IPVersion.V4Only)
        if not addresses:
            return
        props = _txt(info.properties or {})
        self.dante_seen[addresses[0]] = (info.port, props)
        driver = self._dante()
        if driver is not None:
            driver.add_host(addresses[0], info.port, props, mdns=True)
            self._on_change()

    async def _resolve_http(self, service_type: str, name: str) -> None:
        info = await self._info(service_type, name)
        if info is None or self._on_http_host is None:
            return
        for address in info.parsed_addresses(IPVersion.V4Only):
            if address in self._http_seen:
                continue
            self._http_seen.add(address)
            try:
                await self._on_http_host(address, name.removesuffix("." + service_type))
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Prüfung von %s fehlgeschlagen", address, exc_info=True)
