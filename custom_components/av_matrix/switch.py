"""Route lock per destination (protects a destination against accidental switching)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


from .coordinator import AvMatrixConfigEntry
from .entity import AvMatrixDestinationEntity
from .hub import DATA_HUB, AvMatrixHub, Destination

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: AvMatrixConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = hass.data[DATA_HUB]
    async_add_entities(RouteLockSwitch(hub, dest) for dest in entry.runtime_data.destinations)


class RouteLockSwitch(AvMatrixDestinationEntity, SwitchEntity):
    """On = the destination cannot be switched (persists across restarts)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: AvMatrixHub, dest: Destination) -> None:
        super().__init__(hub, dest, "lock")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.dest.uid in self.hub.locks

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hub.async_set_lock(self.dest.uid, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hub.async_set_lock(self.dest.uid, False)
