"""Services: route, salvo, lock, unlock, undo, refresh_sources."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    ATTR_DESTINATION,
    ATTR_ROUTES,
    ATTR_SOURCE,
    DOMAIN,
    SERVICE_LOCK,
    SERVICE_REFRESH,
    SERVICE_ROUTE,
    SERVICE_SALVO,
    SERVICE_UNDO,
    SERVICE_UNLOCK,
)
from .hub import DATA_HUB, AvMatrixHub, Destination

TARGET_FIELDS = {
    vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids,
    vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
    # destination ids from the WebSocket snapshot (e.g. Dante RX channels whose entities are disabled)
    vol.Optional(ATTR_DESTINATION): vol.All(cv.ensure_list, [cv.string]),
}
ROUTE_SCHEMA = vol.Schema({**TARGET_FIELDS, vol.Required(ATTR_SOURCE): vol.Any(None, cv.string)})
TARGET_SCHEMA = vol.Schema(TARGET_FIELDS)
SALVO_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ROUTES): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {vol.Required(ATTR_DESTINATION): cv.string, vol.Required(ATTR_SOURCE): vol.Any(None, cv.string)}
                )
            ],
        )
    }
)


def _destinations(hass: HomeAssistant, hub: AvMatrixHub, call: ServiceCall) -> list[Destination]:
    """Resolve entity_id / device_id targets to destinations (a device = all its destinations)."""
    entity_ids: set[str] = set(call.data.get(ATTR_ENTITY_ID) or [])
    device_ids: set[str] = set(call.data.get(ATTR_DEVICE_ID) or [])
    if device_ids:
        ent_reg = er.async_get(hass)
        for device_id in device_ids:
            entity_ids.update(e.entity_id for e in er.async_entries_for_device(ent_reg, device_id))
    uids: set[str] = set(call.data.get(ATTR_DESTINATION) or [])
    found: list[Destination] = []
    for dest in hub.destinations.values():
        if dest.entity_id in entity_ids or dest.uid in uids:
            found.append(dest)
    if not found:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_destination")
    return found


def _dest_for_entity(hub: AvMatrixHub, entity_id: str) -> Destination:
    """Salvo destination: a select entity id or a destination id."""
    dest = hub.destination_for_entity(entity_id) or hub.destinations.get(entity_id)
    if dest is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_destination",
            translation_placeholders={"destination": entity_id},
        )
    return dest


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration services (once, in async_setup)."""

    def hub() -> AvMatrixHub:
        return hass.data[DATA_HUB]

    async def route(call: ServiceCall) -> None:
        h = hub()
        dests = _destinations(hass, h, call)
        await h.async_salvo(
            [(d.uid, h.resolve_source(d.protocol, call.data[ATTR_SOURCE])) for d in dests],
            origin="service",
            context=call.context,
        )

    async def salvo(call: ServiceCall) -> None:
        h = hub()
        plan = []
        for item in call.data[ATTR_ROUTES]:
            dest = _dest_for_entity(h, item[ATTR_DESTINATION])
            plan.append((dest.uid, h.resolve_source(dest.protocol, item[ATTR_SOURCE])))
        await h.async_salvo(plan, context=call.context)

    async def lock(call: ServiceCall) -> None:
        for dest in _destinations(hass, hub(), call):
            hub().async_set_lock(dest.uid, True)

    async def unlock(call: ServiceCall) -> None:
        for dest in _destinations(hass, hub(), call):
            hub().async_set_lock(dest.uid, False)

    async def undo(call: ServiceCall) -> None:
        for dest in _destinations(hass, hub(), call):
            await hub().async_undo(dest.uid, context=call.context)

    async def refresh(call: ServiceCall) -> None:
        from .button import async_refresh_device

        done = set()
        for dest in _destinations(hass, hub(), call):
            if dest.entry_id not in done:
                done.add(dest.entry_id)
                await async_refresh_device(hub(), dest.coordinator)

    hass.services.async_register(DOMAIN, SERVICE_ROUTE, route, schema=ROUTE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SALVO, salvo, schema=SALVO_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_LOCK, lock, schema=TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UNLOCK, unlock, schema=TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UNDO, undo, schema=TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=TARGET_SCHEMA)
