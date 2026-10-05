"""Base entities and helpers to add entities for destinations that appear at runtime (Dante)."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AvMatrixConfigEntry, AvMatrixCoordinator
from .hub import AvMatrixHub, Destination


def signal_new_destinations(entry_id: str) -> str:
    return f"{DOMAIN}_new_destinations_{entry_id}"


def signal_new_devices(entry_id: str) -> str:
    return f"{DOMAIN}_new_devices_{entry_id}"


@callback
def async_setup_destination_entities(
    hass: HomeAssistant,
    entry: AvMatrixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[Destination], Iterable[Entity]],
) -> None:
    """Add entities for all destinations now and for those a network driver finds later."""

    @callback
    def add(dests: Iterable[Destination]) -> None:
        entities = [e for d in dests for e in factory(d)]
        if entities:
            async_add_entities(entities)

    add(entry.runtime_data.destinations)
    if entry.runtime_data.coordinator.driver.NETWORK:
        entry.async_on_unload(async_dispatcher_connect(hass, signal_new_destinations(entry.entry_id), add))


@callback
def async_setup_subdevice_entities(
    hass: HomeAssistant,
    entry: AvMatrixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[str], Iterable[Entity]],
) -> None:
    """Network drivers: add entities for every sub-device (Dante device), now and later."""
    if not entry.runtime_data.coordinator.driver.NETWORK:
        return

    @callback
    def add(devices: Iterable[str]) -> None:
        entities = [e for d in devices for e in factory(d)]
        if entities:
            async_add_entities(entities)

    add(sorted(entry.runtime_data.devices))
    entry.async_on_unload(async_dispatcher_connect(hass, signal_new_devices(entry.entry_id), add))


def subdevice_info(coordinator: AvMatrixCoordinator, device_key: str) -> DeviceInfo:
    """Device registry entry of a sub-device (Dante device) of a network entry."""
    entry = coordinator.config_entry
    driver = coordinator.driver
    dev = driver.device_for(device_key) if hasattr(driver, "device_for") else None
    info = DeviceInfo(
        identifiers={(DOMAIN, f"{entry.unique_id}_{device_key}")},
        name=device_key,
        manufacturer=(dev.manufacturer if dev else None) or driver.MANUFACTURER,
        model=dev.model if dev else None,
        sw_version=dev.firmware if dev else None,
    )
    hub_device_id = entry.runtime_data.hub_device_id
    if hub_device_id:
        info["via_device_id"] = hub_device_id
    return info


class AvMatrixDeviceEntity(CoordinatorEntity[AvMatrixCoordinator]):
    """Entity belonging to a device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AvMatrixCoordinator, key: str, device_key: str | None = None) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        info = coordinator.info
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        if device_key is not None:
            self._attr_device_info = subdevice_info(coordinator, device_key)
            return
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
        super().__init__(dest.coordinator, f"{dest.dest_id}_{key}", dest.device_key)
        self.hub = hub
        self.dest = dest
        if dest.channel_name:
            self._attr_translation_key = f"{key}_channel"
            self._attr_translation_placeholders = {"channel": dest.channel_name}
        else:
            self._attr_translation_key = key
        driver = dest.coordinator.driver
        if dest.device_key and not getattr(driver, "only_selected", False):
            dev = driver.device_for(dest.device_key) if hasattr(driver, "device_for") else None
            large = getattr(driver, "LARGE_DEVICE_RX", 32)
            if dev is not None and dev.rx_count > large:
                # very large devices (e.g. 64+ RX): entities off by default, the card still routes them
                self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        return self.dest.available

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hub.async_add_listener(self._hub_changed))

    def _hub_changed(self) -> None:
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()
