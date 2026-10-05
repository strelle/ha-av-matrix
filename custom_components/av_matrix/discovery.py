"""Discovery via Home Assistant's shared zeroconf instance.

* NDI®: ``_ndi._tcp.local.`` - every instance is a source.
* Dante®: ``_netaudio-arc._udp.local.`` - every instance is a device (its channels are read via ARC).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.components import zeroconf
from homeassistant.core import HomeAssistant, callback
from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from .protocols.dante import ARC_SERVICE_TYPE
from .protocols.ndi import NDI_SERVICE_TYPE, NdiSourceRegistry, ndi_name_from_mdns

if TYPE_CHECKING:
    from .drivers.dante import DanteNetwork

_LOGGER = logging.getLogger(__name__)


class NdiMdnsBrowser:
    """Browse ``_ndi._tcp.local.`` and feed the NDI source registry."""

    def __init__(self, hass: HomeAssistant, registry: NdiSourceRegistry, on_change: Callable[[], None]) -> None:
        self.hass = hass
        self.registry = registry
        self._on_change = on_change
        self._browser: AsyncServiceBrowser | None = None
        self._zc = None

    async def async_start(self) -> None:
        aiozc = await zeroconf.async_get_async_instance(self.hass)
        self._zc = aiozc.zeroconf
        self._browser = AsyncServiceBrowser(self._zc, [NDI_SERVICE_TYPE], handlers=[self._handler])

    async def async_stop(self) -> None:
        if self._browser is not None:
            await self._browser.async_cancel()
            self._browser = None

    def _handler(
        self,
        zeroconf: object,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        # python-zeroconf calls handlers from its event loop (HA's loop); be safe anyway
        self.hass.loop.call_soon_threadsafe(self._async_handle, service_type, name, state_change)

    @callback
    def _async_handle(self, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        ndi_name = ndi_name_from_mdns(name, service_type)
        if state_change is ServiceStateChange.Removed:
            self.registry.remove_discovered(ndi_name)
            self._on_change()
            return
        self.registry.mark_discovered(ndi_name)
        self._on_change()
        self.hass.async_create_background_task(
            self._async_resolve(service_type, name, ndi_name), f"av_matrix resolve {ndi_name}"
        )

    async def _async_resolve(self, service_type: str, name: str, ndi_name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        try:
            if not await info.async_request(self._zc, 3000):
                return
        except Exception as err:  # noqa: BLE001 - discovery must never crash
            _LOGGER.debug("Could not resolve %s: %s", ndi_name, err)
            return
        addresses = info.parsed_addresses(IPVersion.V4Only) or info.parsed_addresses()
        address = f"{addresses[0]}:{info.port}" if addresses and info.port else None
        self.registry.set_discovered(ndi_name, address)
        self._on_change()


def _txt(props: dict[bytes, bytes | None]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in props.items():
        try:
            out[key.decode()] = value.decode() if value is not None else ""
        except (AttributeError, UnicodeDecodeError):
            continue
    return out


class DanteMdnsBrowser:
    """Browse ``_netaudio-arc._udp.local.`` and hand every Dante device to the network driver."""

    def __init__(self, hass: HomeAssistant, driver: DanteNetwork, on_change: Callable[[], None]) -> None:
        self.hass = hass
        self.driver = driver
        self._on_change = on_change
        self._browser: AsyncServiceBrowser | None = None
        self._zc = None

    async def async_start(self) -> None:
        aiozc = await zeroconf.async_get_async_instance(self.hass)
        self._zc = aiozc.zeroconf
        self._browser = AsyncServiceBrowser(self._zc, [ARC_SERVICE_TYPE], handlers=[self._handler])

    async def async_stop(self) -> None:
        if self._browser is not None:
            await self._browser.async_cancel()
            self._browser = None

    def _handler(
        self,
        zeroconf: object,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        self.hass.loop.call_soon_threadsafe(self._async_handle, service_type, name, state_change)

    @callback
    def _async_handle(self, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        device = name.removesuffix("." + service_type).removesuffix("." + service_type.rstrip("."))
        if state_change is ServiceStateChange.Removed:
            self.driver.mdns_removed(None, device)
            self._on_change()
            return
        self.hass.async_create_background_task(
            self._async_resolve(service_type, name, device), f"av_matrix resolve dante {device}"
        )

    async def _async_resolve(self, service_type: str, name: str, device: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        try:
            if not await info.async_request(self._zc, 3000):
                return
        except Exception as err:  # noqa: BLE001 - discovery must never crash
            _LOGGER.debug("Could not resolve Dante device %s: %s", device, err)
            return
        addresses = info.parsed_addresses(IPVersion.V4Only)
        if not addresses:
            return
        self.driver.add_host(addresses[0], info.port, _txt(info.properties or {}), mdns=True)
        self._on_change()
