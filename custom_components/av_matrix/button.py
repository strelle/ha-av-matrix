"""Refresh-sources button per device."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import AvMatrixConfigEntry, AvMatrixCoordinator
from .drivers import DriverError
from .drivers.base import short
from .entity import AvMatrixDeviceEntity
from .hub import DATA_HUB, AvMatrixHub

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: AvMatrixConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([RefreshSourcesButton(hass.data[DATA_HUB], entry.runtime_data.coordinator)])


async def async_refresh_device(hub: AvMatrixHub, coordinator: AvMatrixCoordinator) -> None:
    """Let the device rebuild its source list and forget cached source knowledge."""
    try:
        await coordinator.driver.async_refresh_sources()
    except DriverError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="refresh_failed", translation_placeholders={"error": short(err)}
        ) from err
    hub.registry(coordinator.driver.PROTOCOL).forget()
    await coordinator.async_refresh()
    await hub.async_evaluate()
    hub.async_notify()


class RefreshSourcesButton(AvMatrixDeviceEntity, ButtonEntity):
    """Rebuild the device's source list."""

    _attr_translation_key = "refresh_sources"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: AvMatrixHub, coordinator: AvMatrixCoordinator) -> None:
        super().__init__(coordinator, "refresh_sources")
        self.hub = hub

    async def async_press(self) -> None:
        await async_refresh_device(self.hub, self.coordinator)
