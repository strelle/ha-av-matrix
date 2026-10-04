"""Connected binary sensor per destination."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


from .coordinator import AvMatrixConfigEntry
from .entity import AvMatrixDestinationEntity
from .hub import DATA_HUB, AvMatrixHub, Destination
from .models import ConnectionState

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: AvMatrixConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = hass.data[DATA_HUB]
    async_add_entities(ConnectedSensor(hub, dest) for dest in entry.runtime_data.destinations)


class ConnectedSensor(AvMatrixDestinationEntity, BinarySensorEntity):
    """On while the destination receives its source."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, hub: AvMatrixHub, dest: Destination) -> None:
        super().__init__(hub, dest, "connected")

    @property
    def is_on(self) -> bool:
        return self.hub.connection_state(self.dest) is ConnectionState.CONNECTED
