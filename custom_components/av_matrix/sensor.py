"""Connection state and resolution per destination."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
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
    entities: list[SensorEntity] = []
    for dest in entry.runtime_data.destinations:
        entities += [ConnectionSensor(hub, dest), ResolutionSensor(hub, dest)]
    async_add_entities(entities)


class ConnectionSensor(AvMatrixDestinationEntity, SensorEntity):
    """connected / connecting / no_source / source_lost / offline."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, hub: AvMatrixHub, dest: Destination) -> None:
        super().__init__(hub, dest, "connection")
        self._attr_options = [s.value for s in ConnectionState]

    @property
    def available(self) -> bool:
        return True  # "offline" is a state, not unavailability

    @property
    def native_value(self) -> str:
        return self.hub.connection_state(self.dest).value


class ResolutionSensor(AvMatrixDestinationEntity, SensorEntity):
    """Video format of the decoded stream, e.g. 1920x1080p50 (where the device reports it)."""

    def __init__(self, hub: AvMatrixHub, dest: Destination) -> None:
        super().__init__(hub, dest, "resolution")

    @property
    def native_value(self) -> str | None:
        return self.hub.resolution(self.dest)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details where the device reports them (Magewell: codec, color_format, sampling …)."""
        return self.hub.status_extra(self.dest)
