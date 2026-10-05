"""Connected binary sensor per destination; online sensor per Dante® device."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AvMatrixConfigEntry, AvMatrixCoordinator
from .entity import (
    AvMatrixDestinationEntity,
    AvMatrixDeviceEntity,
    async_setup_destination_entities,
    async_setup_subdevice_entities,
)
from .hub import DATA_HUB, AvMatrixHub, Destination
from .models import ConnectionState

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: AvMatrixConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = hass.data[DATA_HUB]
    coordinator = entry.runtime_data.coordinator
    async_setup_destination_entities(
        hass,
        entry,
        async_add_entities,
        lambda dest: [] if coordinator.driver.NETWORK else [ConnectedSensor(hub, dest)],
    )
    async_setup_subdevice_entities(hass, entry, async_add_entities, lambda name: [OnlineSensor(coordinator, name)])


class ConnectedSensor(AvMatrixDestinationEntity, BinarySensorEntity):
    """On while the destination receives its source."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, hub: AvMatrixHub, dest: Destination) -> None:
        super().__init__(hub, dest, "connected")

    @property
    def is_on(self) -> bool:
        return self.hub.connection_state(self.dest) is ConnectionState.CONNECTED


class OnlineSensor(AvMatrixDeviceEntity, BinarySensorEntity):
    """Dante device answers control requests."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "online"

    def __init__(self, coordinator: AvMatrixCoordinator, device: str) -> None:
        super().__init__(coordinator, f"{device}_online", device)
        self.device = device

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        dev = self.coordinator.driver.device_for(self.device)  # type: ignore[attr-defined]
        return bool(dev and dev.online and self.coordinator.last_update_success)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        dev = self.coordinator.driver.device_for(self.device)  # type: ignore[attr-defined]
        if dev is None:
            return {}
        return {"host": dev.host, "mdns": dev.via_mdns, "last_error": dev.last_error}
