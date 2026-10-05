"""Connection state and resolution per destination; Dante®: subscription per RX channel, device sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfFrequency
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
from .protocols.dante import SUBSCRIPTION_STATES

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: AvMatrixConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = hass.data[DATA_HUB]
    coordinator = entry.runtime_data.coordinator

    def for_dest(dest: Destination) -> list[SensorEntity]:
        if dest.protocol == "dante":
            return [SubscriptionSensor(hub, dest)]
        return [ConnectionSensor(hub, dest), ResolutionSensor(hub, dest)]

    async_setup_destination_entities(hass, entry, async_add_entities, for_dest)
    async_setup_subdevice_entities(
        hass,
        entry,
        async_add_entities,
        lambda name: [
            DanteDeviceSensor(coordinator, name, "tx_channels"),
            DanteDeviceSensor(coordinator, name, "rx_channels"),
            DanteDeviceSensor(coordinator, name, "sample_rate"),
        ],
    )
    if coordinator.driver.NETWORK:
        async_add_entities([NetworkDevicesSensor(coordinator)])


class ConnectionSensor(AvMatrixDestinationEntity, SensorEntity):
    """connected / connecting / no_source / source_lost / offline (/ error)."""

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


class SubscriptionSensor(AvMatrixDestinationEntity, SensorEntity):
    """Dante RX channel: none / subscribed / self / in_progress / unresolved / idle / warning / error."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, hub: AvMatrixHub, dest: Destination) -> None:
        super().__init__(hub, dest, "subscription")
        self._attr_options = list(SUBSCRIPTION_STATES)

    @property
    def native_value(self) -> str | None:
        return self.hub.status_extra(self.dest).get("subscription")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        extra = self.hub.status_extra(self.dest)
        return {
            "source": self.hub.current_source(self.dest),
            "connection": self.hub.connection_state(self.dest).value,
            "status": extra.get("subscription_status"),
            "code": extra.get("subscription_code"),
            "detail": extra.get("subscription_detail"),
            "rx_number": extra.get("rx_number"),
            "sample_rate": extra.get("sample_rate"),
        }


class DanteDeviceSensor(AvMatrixDeviceEntity, SensorEntity):
    """Channel counts and sample rate of a Dante device."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AvMatrixCoordinator, device: str, key: str) -> None:
        super().__init__(coordinator, f"{device}_{key}", device)
        self.device = device
        self.key = key
        self._attr_translation_key = key
        if key == "sample_rate":
            self._attr_device_class = SensorDeviceClass.FREQUENCY
            self._attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
            self._attr_suggested_unit_of_measurement = UnitOfFrequency.KILOHERTZ
            self._attr_suggested_display_precision = 1
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    def _dev(self) -> Any:
        return self.coordinator.driver.device_for(self.device)  # type: ignore[attr-defined]

    @property
    def available(self) -> bool:
        dev = self._dev()
        return bool(dev and dev.online and self.coordinator.last_update_success)

    @property
    def native_value(self) -> int | None:
        dev = self._dev()
        if dev is None:
            return None
        return {"tx_channels": dev.tx_count, "rx_channels": dev.rx_count, "sample_rate": dev.sample_rate}[self.key]


class NetworkDevicesSensor(AvMatrixDeviceEntity, SensorEntity):
    """Number of Dante devices online (attributes: all known devices)."""

    _attr_translation_key = "devices_online"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: AvMatrixCoordinator) -> None:
        super().__init__(coordinator, "devices_online")

    @property
    def native_value(self) -> int:
        return sum(1 for d in self.coordinator.driver.visible_devices() if d.online)  # type: ignore[attr-defined]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "devices": {
                d.name: {"host": d.host, "online": d.online, "tx": d.tx_count, "rx": d.rx_count}
                for d in self.coordinator.driver.visible_devices()  # type: ignore[attr-defined]
            }
        }
