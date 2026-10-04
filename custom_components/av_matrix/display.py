"""Linked displays: power on a TV/projector and switch its input when a destination is routed.

Works with any ``media_player`` entity (e.g. LG webOS, Samsung, Sony Bravia, Android TV).
Failures never fail the route itself - they are logged and reported as an attribute.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DISPLAY_AUTO_ON,
    CONF_DISPLAY_ENTITY,
    CONF_DISPLAY_INPUT,
    CONF_DISPLAY_OFF_ON_NONE,
    DISPLAY_ON_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

MP_DOMAIN = "media_player"
OFF_STATES = {STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE, STATE_UNKNOWN}


def display_state(
    hass: HomeAssistant, cfg: Mapping[str, Any] | None, error: str | None = None
) -> dict[str, Any] | None:
    """State of a linked display for the WebSocket API (None = no display linked)."""
    if not cfg or not cfg.get(CONF_DISPLAY_ENTITY):
        return None
    entity_id = cfg[CONF_DISPLAY_ENTITY]
    state = hass.states.get(entity_id)
    return {
        "entity_id": entity_id,
        "state": state.state if state else None,
        "source": state.attributes.get("source") if state else None,
        "source_list": list(state.attributes.get("source_list") or []) if state else [],
        "configured_input": cfg.get(CONF_DISPLAY_INPUT) or None,
        "auto_on": bool(cfg.get(CONF_DISPLAY_AUTO_ON, True)),
        "off_on_none": bool(cfg.get(CONF_DISPLAY_OFF_ON_NONE, False)),
        "error": error,
    }


async def async_drive_display(
    hass: HomeAssistant,
    cfg: Mapping[str, Any] | None,
    source: str | None,
    *,
    timeout: float = DISPLAY_ON_TIMEOUT,
    poll_interval: float = 0.5,
) -> str | None:
    """Apply the linked-display rules after a route. Returns an error text or None."""
    if not cfg or not cfg.get(CONF_DISPLAY_ENTITY):
        return None
    entity_id: str = cfg[CONF_DISPLAY_ENTITY]
    try:
        if source is None:
            if cfg.get(CONF_DISPLAY_OFF_ON_NONE):
                state = hass.states.get(entity_id)
                if state is not None and state.state not in OFF_STATES:
                    await hass.services.async_call(MP_DOMAIN, "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True)
            return None
        if not cfg.get(CONF_DISPLAY_AUTO_ON, True):
            return None
        state = hass.states.get(entity_id)
        if state is None:
            return f"{entity_id} not found"
        if state.state in OFF_STATES:
            await hass.services.async_call(MP_DOMAIN, "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True)
            waited = 0.0
            while waited < timeout:
                state = hass.states.get(entity_id)
                if state is not None and state.state not in OFF_STATES:
                    break
                await asyncio.sleep(poll_interval)
                waited += poll_interval
            else:
                return f"{entity_id} did not turn on within {timeout:.0f} s"
        wanted = cfg.get(CONF_DISPLAY_INPUT)
        if wanted and (state is None or state.attributes.get("source") != wanted):
            await hass.services.async_call(
                MP_DOMAIN, "select_source", {ATTR_ENTITY_ID: entity_id, "source": wanted}, blocking=True
            )
    except Exception as err:  # noqa: BLE001 - a display problem must never break routing
        _LOGGER.warning("Linked display %s: %s", entity_id, err)
        return str(err)[:120] or err.__class__.__name__
    return None
