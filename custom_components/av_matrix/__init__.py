"""AV Matrix - smart crosspoint router for NDI® decoders (and more) in Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
    from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(Path(__file__).parent / "frontend"), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}?v={version}")


async def async_setup_entry(hass: HomeAssistant, entry: AvMatrixConfigEntry) -> bool:
    """Set up one device."""
    hub = hass.data[DATA_HUB]
    driver_cls = DRIVERS[entry.data[CONF_DRIVER]]
    driver = driver_cls(async_get_clientsession(hass), entry.data, timeout=REQUEST_TIMEOUT)
    coordinator = AvMatrixCoordinator(hass, entry, driver, hub)
    await hub.async_start()
    await coordinator.async_config_entry_first_refresh()

    runtime = AvMatrixRuntime(coordinator)
    for info in driver.destinations():
        dest = Destination(
            uid=f"{entry.unique_id}_{info.id}",
            dest_id=info.id,
            protocol=driver.PROTOCOL,
            coordinator=coordinator,
            channel_name=info.name,
        )
        runtime.destinations.append(dest)
        hub.add_destination(dest)
    entry.runtime_data = runtime
    entry.async_on_unload(coordinator.async_add_listener(hub.async_notify))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.async_notify()
    return True


async def _async_options_updated(hass: HomeAssistant, entry: AvMatrixConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AvMatrixConfigEntry) -> bool:
    """Unload one device."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hub = hass.data[DATA_HUB]
        for dest in entry.runtime_data.destinations:
            hub.remove_destination(dest.uid)
        hub.registry(entry.runtime_data.coordinator.driver.PROTOCOL).remove_device(entry.entry_id)
        if not hub.destinations:
            await hub.async_stop()
        hub.schedule_evaluate()
        hub.async_notify()
    return unloaded
