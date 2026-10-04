"""Source selector per destination - the crosspoint."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
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
    async_add_entities(AvMatrixSourceSelect(hub, dest) for dest in entry.runtime_data.destinations)


class AvMatrixSourceSelect(AvMatrixDestinationEntity, SelectEntity):
    """Select the source routed to a destination. Works with HomeKit Bridge (as input selector)."""

    def __init__(self, hub: AvMatrixHub, dest: Destination) -> None:
        super().__init__(hub, dest, "source")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.dest.entity_id = self.entity_id

    async def async_will_remove_from_hass(self) -> None:
        if self.dest.entity_id == self.entity_id:
            self.dest.entity_id = None
        await super().async_will_remove_from_hass()

    @property
    def options(self) -> list[str]:
        return self.hub.options(self.dest)

    @property
    def current_option(self) -> str | None:
        return self.hub.display_name(self.dest.protocol, self.hub.current_source(self.dest))

    async def async_select_option(self, option: str) -> None:
        await self.hub.async_route(
            self.dest.uid, self.hub.resolve_source(self.dest.protocol, option), origin="select", context=self._context
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        current = self.hub.current_source(self.dest)
        registry = self.hub.registry(self.dest.protocol)
        record = registry.get(current) if current else None
        return {
            "protocol": self.dest.protocol,
            "source_id": current,
            "source_live": registry.is_live(current),
            "source_address": record.address if record else None,
            "locked": self.dest.uid in self.hub.locks,
            "can_undo": bool(self.hub.history.get(self.dest.uid)),
            "display_error": self.dest.display_error,
        }
