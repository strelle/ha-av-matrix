"""Base entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AvMatrixCoordinator
from .hub import AvMatrixHub, Destination


class AvMatrixDeviceEntity(CoordinatorEntity[AvMatrixCoordinator]):
    """Entity belonging to a device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AvMatrixCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        info = coordinator.info
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            connections={(CONNECTION_NETWORK_MAC, format_mac(info.mac))} if info.mac else set(),
            name=coordinator.device_name,
            manufacturer=info.manufacturer or coordinator.driver.MANUFACTURER,
            model=info.model,
            sw_version=info.firmware,
            serial_number=info.serial,
            configuration_url=coordinator.driver.configuration_url,
        )


class AvMatrixDestinationEntity(AvMatrixDeviceEntity):
    """Entity belonging to one destination of a device."""

    def __init__(self, hub: AvMatrixHub, dest: Destination, key: str) -> None:
        super().__init__(dest.coordinator, f"{dest.dest_id}_{key}")
        self.hub = hub
        self.dest = dest
        if dest.channel_name:
            self._attr_translation_key = f"{key}_channel"
            self._attr_translation_placeholders = {"channel": dest.channel_name}
        else:
            self._attr_translation_key = key

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hub.async_add_listener(self._hub_changed))

    def _hub_changed(self) -> None:
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()
