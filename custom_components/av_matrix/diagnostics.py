"""Diagnostics (secrets redacted)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_DRIVER
from .coordinator import AvMatrixConfigEntry
from .drivers import DRIVERS
from .hub import DATA_HUB

ALWAYS_REDACT = {"password", "pass", "username", "serial", "mac", "serial_number"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AvMatrixConfigEntry) -> dict[str, Any]:
    hub = hass.data[DATA_HUB]
    coordinator = entry.runtime_data.coordinator
    driver_cls = DRIVERS[entry.data[CONF_DRIVER]]
    redact = ALWAYS_REDACT | driver_cls.secret_keys()
    data = coordinator.data
    registry = hub.registry(driver_cls.PROTOCOL)
    network = (
        {"dante_devices": [d.as_dict() for d in coordinator.driver.devices.values()]}  # type: ignore[attr-defined]
        if coordinator.driver.NETWORK
        else {}
    )
    return {
        **network,
        "entry": {"data": async_redact_data(dict(entry.data), redact), "options": dict(entry.options)},
        "device": async_redact_data(asdict(coordinator.info), redact),
        "last_update_success": coordinator.last_update_success,
        "update_interval": str(coordinator.update_interval),
        "poll": asdict(data) if data else None,
        "registry": {
            "sources": [
                {"id": r.id, "address": r.address, "live": r.live, "seen_by": sorted(r.seen_by)}
                for r in registry.sources
            ],
        },
        "destinations": [
            {
                "uid": d.uid,
                "entity_id": d.entity_id,
                "current": hub.current_source(d),
                "status": hub.connection_state(d).value,
                "locked": d.uid in hub.locks,
                "history": list(hub.history.get(d.uid, [])),
            }
            for d in entry.runtime_data.destinations
        ],
    }
