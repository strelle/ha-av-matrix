"""WebSocket API for the matrix card (documented in docs/frontend-api.md)."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import (
    SOURCE_DHCP,
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_SSDP,
    SOURCE_ZEROCONF,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .device_icons import icon_key
from .drivers import DRIVERS
from .hub import DATA_HUB

PUSH_DEBOUNCE = 0.2
DISCOVERY_SOURCES = (SOURCE_DHCP, SOURCE_ZEROCONF, SOURCE_SSDP, SOURCE_INTEGRATION_DISCOVERY)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_state)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_label)
    websocket_api.async_register_command(hass, ws_discovered)


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


@websocket_api.websocket_command({vol.Required("type"): "av_matrix/discovered"})
@websocket_api.require_admin
@callback
def ws_discovered(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Discovered devices waiting for confirmation (config flows started by DHCP / zeroconf)."""
    flows = []
    for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN):
        context = flow.get("context") or {}
        source = context.get("source")
        if source not in DISCOVERY_SOURCES:
            continue
        info = context.get("title_placeholders") or {}
        name = info.get("name") or None
        host = info.get("host") or None
        if host is None and name and (match := _IPV4.search(name)):  # flows started before v0.7.0
            host = match.group(0)
        driver = info.get("driver") or None
        driver_cls = DRIVERS.get(driver) if driver else None
        manufacturer = info.get("manufacturer") or (driver_cls.MANUFACTURER if driver_cls else None)
        model = info.get("model") or None
        flows.append(
            {
                "flow_id": flow["flow_id"],
                "source": source,
                "step_id": flow.get("step_id"),
                "name": name or host,
                "host": host,
                "driver": driver,
                "manufacturer": manufacturer,
                "model": model,
                "icon_key": icon_key(
                    protocol=driver_cls.PROTOCOL if driver_cls else "ndi",
                    driver=driver,
                    manufacturer=manufacturer,
                    model=model,
                    name=name,
                ),
            }
        )
    flows.sort(key=lambda f: (f["name"] or "").casefold())
    connection.send_result(msg["id"], {"flows": flows})
