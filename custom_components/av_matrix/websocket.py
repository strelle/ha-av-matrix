"""WebSocket API for the matrix card (documented in docs/frontend-api.md)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .hub import DATA_HUB

PUSH_DEBOUNCE = 0.2


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_state)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_label)


@websocket_api.websocket_command({vol.Required("type"): "av_matrix/state"})
@callback
def ws_state(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return the complete matrix state once."""
    connection.send_result(msg["id"], hass.data[DATA_HUB].snapshot())


@websocket_api.websocket_command({vol.Required("type"): "av_matrix/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the complete state now and again on every change (debounced)."""
    hub = hass.data[DATA_HUB]
    msg_id = msg["id"]
    pending: CALLBACK_TYPE | None = None
    last: dict[str, Any] | None = None

    @callback
    def send(_now: object = None) -> None:
        nonlocal pending, last
        pending = None
        snapshot = hub.snapshot()
        if snapshot != last:
            last = snapshot
            connection.send_message(websocket_api.event_message(msg_id, snapshot))

    @callback
    def changed() -> None:
        nonlocal pending
        if pending is None:
            pending = async_call_later(hass, PUSH_DEBOUNCE, send)

    remove_listener = hub.async_add_listener(changed)

    @callback
    def unsubscribe() -> None:
        remove_listener()
        if pending is not None:
            pending()

    connection.subscriptions[msg_id] = unsubscribe
    connection.send_result(msg_id)
    send()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "av_matrix/label",
        vol.Optional("kind", default="source"): vol.In(["source", "destination"]),
        vol.Optional("protocol"): str,
        vol.Optional("source"): str,
        vol.Optional("destination"): str,
        vol.Optional("label"): vol.Any(None, str),
        vol.Optional("tags"): vol.Any(None, [str]),
    }
)
@websocket_api.require_admin
@callback
def ws_label(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Set (or clear) the display label and tags of a source or a destination."""
    hub = hass.data[DATA_HUB]
    if msg["kind"] == "destination":
        uid = msg.get("destination")
        if not uid or uid not in hub.destinations:
            connection.send_error(msg["id"], "unknown_destination", f"Unknown destination {uid}")
            return
        hub.async_set_destination_label(uid, msg.get("label"), msg.get("tags"))
        connection.send_result(msg["id"], hub.destination_label(uid))
        return
    protocol, source = msg.get("protocol"), msg.get("source")
    if protocol not in hub.registries:
        connection.send_error(msg["id"], "unknown_protocol", f"Unknown protocol {protocol}")
        return
    if not source:
        connection.send_error(msg["id"], "invalid_format", "source is required")
        return
    hub.async_set_label(protocol, source, msg.get("label"), msg.get("tags"))
    connection.send_result(msg["id"], hub.label(protocol, source))
