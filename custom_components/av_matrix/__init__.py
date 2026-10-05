"""AV Matrix - smart crosspoint router for NDI® decoders, Dante® devices (and more) in Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARD_FILENAME, CONF_DRIVER, DOMAIN, REQUEST_TIMEOUT, URL_BASE
from .coordinator import AvMatrixConfigEntry, AvMatrixCoordinator, AvMatrixRuntime
from .drivers import DRIVERS
from .hub import DATA_HUB, AvMatrixHub, Destination
from .services import async_setup_services
from .websocket import async_setup_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration-wide parts: hub, services, WebSocket API, Lovelace card."""
    hub = AvMatrixHub(hass)
    hub.version = str((await async_get_integration(hass, DOMAIN)).version or "unknown")
    await hub.async_load()
    hass.data[DATA_HUB] = hub
    async_setup_services(hass)
    async_setup_websocket(hass)
    await _async_register_card(hass, hub.version)
    return True


async def _async_register_card(hass: HomeAssistant, version: str) -> None:
    """Serve the card from the integration and load it on every dashboard (no manual resource)."""
    if hass.http is None:  # e.g. in tests without the http component
        return
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(Path(__file__).parent / "frontend"), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}?v={version}")


async def async_setup_entry(hass: HomeAssistant, entry: AvMatrixConfigEntry) -> bool:
    """Set up one device (or, for network drivers like Dante, one network)."""
    hub = hass.data[DATA_HUB]
    driver_cls = DRIVERS[entry.data[CONF_DRIVER]]
    if driver_cls.NETWORK:
        driver = driver_cls(async_get_clientsession(hass), entry.data, timeout=REQUEST_TIMEOUT, options=entry.options)  # type: ignore[call-arg]
    else:
        driver = driver_cls(async_get_clientsession(hass), entry.data, timeout=REQUEST_TIMEOUT)
    coordinator = AvMatrixCoordinator(hass, entry, driver, hub)
    runtime = AvMatrixRuntime(coordinator)
    await hub.async_start()
    if driver_cls.NETWORK:
        await _async_start_network_discovery(hass, runtime)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await _async_stop_network(runtime)
        if not hub.destinations:  # nothing else uses discovery → do not leave it running
            await hub.async_stop()
        raise

    _sync_destinations(hub, entry, runtime)
    if driver_cls.NETWORK:
        runtime.devices = {d.name for d in driver.visible_devices()}  # type: ignore[attr-defined]
        runtime.hub_device_id = (
            dr.async_get(hass)
            .async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, str(entry.unique_id))},
                name=entry.title,
                manufacturer=driver.MANUFACTURER,
                model=coordinator.info.model,
            )
            .id
        )
    entry.runtime_data = runtime
    entry.async_on_unload(coordinator.async_add_listener(hub.async_notify))
    if driver_cls.NETWORK:
        entry.async_on_unload(coordinator.async_add_listener(lambda: _async_network_updated(hass, entry)))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.async_notify()
    return True


def _sync_destinations(hub: AvMatrixHub, entry: AvMatrixConfigEntry, runtime: AvMatrixRuntime) -> list[Destination]:
    """Create hub destinations for destinations the driver reports and we do not know yet."""
    coordinator = runtime.coordinator
    known = {d.dest_id: d for d in runtime.destinations}
    new: list[Destination] = []
    for info in coordinator.driver.destinations():
        if info.id in known:
            known[info.id].channel_name = info.name  # renamed RX channel
            continue
        dest = Destination(
            uid=f"{entry.unique_id}_{info.id}",
            dest_id=info.id,
            protocol=coordinator.driver.PROTOCOL,
            coordinator=coordinator,
            channel_name=info.name,
            device_key=info.device,
        )
        runtime.destinations.append(dest)
        hub.add_destination(dest)
        new.append(dest)
    return new


@callback
def _async_network_updated(hass: HomeAssistant, entry: AvMatrixConfigEntry) -> None:
    """After every poll of a network entry: add devices/destinations that appeared."""
    from .entity import signal_new_destinations, signal_new_devices

    runtime = entry.runtime_data
    new = _sync_destinations(hass.data[DATA_HUB], entry, runtime)
    driver = runtime.coordinator.driver
    devices = {d.name for d in driver.visible_devices()}  # type: ignore[attr-defined]
    new_devices = sorted(devices - runtime.devices)
    runtime.devices |= devices
    if new_devices:
        async_dispatcher_send(hass, signal_new_devices(entry.entry_id), new_devices)
    if new:
        async_dispatcher_send(hass, signal_new_destinations(entry.entry_id), new)
        hass.data[DATA_HUB].async_notify()


async def _async_start_network_discovery(hass: HomeAssistant, runtime: AvMatrixRuntime) -> None:
    from .discovery import DanteMdnsBrowser

    coordinator = runtime.coordinator

    @callback
    def changed() -> None:
        hass.async_create_task(coordinator.async_request_refresh(), eager_start=False)

    browser = DanteMdnsBrowser(hass, coordinator.driver, changed)  # type: ignore[arg-type]
    try:
        await browser.async_start()
        runtime.browser = browser
    except Exception as err:  # noqa: BLE001 - static hosts still work
        _LOGGER.warning("mDNS discovery of Dante devices unavailable: %s", err)


async def _async_stop_network(runtime: AvMatrixRuntime) -> None:
    if runtime.browser is not None:
        await runtime.browser.async_stop()
        runtime.browser = None
    runtime.coordinator.driver.close()


async def _async_options_updated(hass: HomeAssistant, entry: AvMatrixConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AvMatrixConfigEntry) -> bool:
    """Unload one device (or network)."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hub = hass.data[DATA_HUB]
        for dest in entry.runtime_data.destinations:
            hub.remove_destination(dest.uid)
        hub.registry(entry.runtime_data.coordinator.driver.PROTOCOL).remove_device(entry.entry_id)
        await _async_stop_network(entry.runtime_data)
        if not hub.destinations:
            await hub.async_stop()
        hub.schedule_evaluate()
        hub.async_notify()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: AvMatrixConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting Dante devices that left the network (not the entry's own device)."""
    driver = entry.runtime_data.coordinator.driver
    if not driver.NETWORK:
        return False
    for domain, ident in device_entry.identifiers:
        if domain != DOMAIN or ident == entry.unique_id:
            continue
        name = ident.removeprefix(f"{entry.unique_id}_")
        dev = driver.device_for(name)  # type: ignore[attr-defined]
        return dev is None or not dev.online
    return False
