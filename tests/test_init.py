"""Integration tests inside a real (test) Home Assistant."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.av_matrix.const import DOMAIN, EVENT_ROUTED
from custom_components.av_matrix.diagnostics import async_get_config_entry_diagnostics
from custom_components.av_matrix.drivers import DRIVERS, CannotConnect, InvalidAuth
from custom_components.av_matrix.drivers.magewell import MagewellProConvert
from custom_components.av_matrix.hub import DATA_HUB
from custom_components.av_matrix.models import DestinationStatus, DeviceInfo, SourceSighting


class FakeDecoder(MagewellProConvert):
    """Magewell-shaped driver without network; state shared per host."""

    devices: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def state(cls, host: str) -> dict[str, Any]:
        return cls.devices.setdefault(
            host,
            {
                "serial": f"SN-{host}",
                "name": f"PC-{host.rsplit('.', 1)[-1]}",
                "sources": [
                    SourceSighting("STUDIO-PC (Slides)", "192.0.2.50:5961"),
                    SourceSighting("CAM (1)", "192.0.2.51:5961"),
                ],
                "current": "OLD-PC (Gone)",
                "connected": True,
                "fail": None,
                "routes": [],
            },
        )

    def _s(self) -> dict[str, Any]:
        s = self.state(self.host)
        if s["fail"] is not None:
            raise s["fail"]
        return s

    async def async_get_info(self) -> DeviceInfo:
        s = self._s()
        return DeviceInfo(
            name=s["name"],
            manufacturer="Magewell",
            model="Pro Convert NDI to AIO",
            firmware="1.3.24",
            serial=s["serial"],
        )

    async def async_get_sources(self):
        return list(self._s()["sources"])

    async def async_get_current(self, destination):
        s = self._s()
        current = s["current"]
        if s.get("gate") is not None:  # simulate a slow poll that started before a route
            await s["gate"].wait()
        return current

    async def async_get_status(self, destination):
        s = self._s()
        if s.get("settling", 0) > 0:  # device still switching: connected, but no video yet
            s["settling"] -= 1
            return DestinationStatus(connected=True)
        return DestinationStatus(
            connected=s["connected"] if s["current"] else False, resolution="1920x1080p50" if s["connected"] else None
        )

    async def async_route(self, destination, source, address=None):
        s = self._s()
        s["routes"].append(source)
        s["current"] = source
        s["settling"] = s.get("settle_polls", 0)

    async def async_poll(self):
        return await super(MagewellProConvert, self).async_poll()


@pytest.fixture(autouse=True)
def fake_env(hass: HomeAssistant):
    FakeDecoder.devices = {}
    hass.config.components.update({"frontend", "zeroconf"})
    with (
        patch.dict(DRIVERS, {"magewell": FakeDecoder}),
        patch("custom_components.av_matrix.discovery.NdiMdnsBrowser.async_start", AsyncMock()),
        patch("custom_components.av_matrix.discovery.NdiMdnsBrowser.async_stop", AsyncMock()),
        patch("custom_components.av_matrix._async_register_card", AsyncMock()),
    ):
        yield


async def add_device(
    hass: HomeAssistant, host: str = "192.0.2.20", title: str = "Lobby", options=None
) -> MockConfigEntry:
    FakeDecoder.state(host)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id=f"magewell-sn-{host}",
        data={"driver": "magewell", "host": host, "username": "Admin", "password": "topsecret"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ------------------------------------------------------------------ config flow
async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"driver": "magewell"})
    assert result["step_id"] == "device"
    with patch("custom_components.av_matrix.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": " 192.0.2.20 ", "port": 80.0, "username": "Admin", "password": "pw"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "PC-20"
    assert result["data"] == {
        "driver": "magewell",
        "host": "192.0.2.20",
        "port": 80,
        "username": "Admin",
        "password": "pw",
    }
    assert result["result"].unique_id == "magewell-sn-192.0.2.20"


@pytest.mark.parametrize(("exc", "error"), [(InvalidAuth("x"), "invalid_auth"), (CannotConnect("x"), "cannot_connect")])
async def test_config_flow_errors(hass: HomeAssistant, exc, error) -> None:
    FakeDecoder.state("192.0.2.21")["fail"] = exc
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"driver": "magewell"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.21", "username": "Admin", "password": "x"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_config_flow_already_configured(hass: HomeAssistant) -> None:
    await add_device(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"driver": "magewell"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.20", "username": "Admin", "password": "x"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_birddog_form_is_built_from_driver_fields(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"driver": "birddog"})
    keys = [str(k) for k in result["data_schema"].schema]
    assert keys == ["host", "port", "password", "channels", "name"]


# -------------------------------------------------------------------- entities
async def test_entities_and_options(hass: HomeAssistant) -> None:
    entry = await add_device(hass)
    assert entry.state is ConfigEntryState.LOADED
    hub = hass.data[DATA_HUB]
    await hub.async_evaluate()
    await hass.async_block_till_done()
    state = hass.states.get("select.lobby_source")
    assert state is not None
    # current source is not sent any more but still an option
    assert state.attributes["options"] == ["None", "CAM (1)", "STUDIO-PC (Slides)", "OLD-PC (Gone)"]
    assert state.state == "OLD-PC (Gone)"
    assert state.attributes["source_live"] is False
    assert hass.states.get("sensor.lobby_connection").state == "connected"
    assert hass.states.get("sensor.lobby_resolution").state == "1920x1080p50"
    assert hass.states.get("binary_sensor.lobby_connected").state == "on"
    assert hass.states.get("button.lobby_refresh_sources") is not None
    assert hass.states.get("switch.lobby_route_lock").state == "off"
    device = dr.async_get(hass).async_get(er.async_get(hass).async_get("select.lobby_source").device_id)
    assert device.manufacturer == "Magewell" and device.sw_version == "1.3.24"


async def test_select_routes_fires_event_and_undo(hass: HomeAssistant) -> None:
    await add_device(hass)
    events = async_capture_events(hass, EVENT_ROUTED)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.lobby_source", "option": "CAM (1)"}, blocking=True
    )
    await hass.async_block_till_done()
    assert FakeDecoder.state("192.0.2.20")["routes"] == ["CAM (1)"]
    assert hass.states.get("select.lobby_source").state == "CAM (1)"
    assert events[0].data["source"] == "CAM (1)" and events[0].data["previous_source"] == "OLD-PC (Gone)"
    assert events[0].data["entity_id"] == "select.lobby_source"

    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.lobby_source", "source": "None"}, blocking=True
    )
    assert FakeDecoder.state("192.0.2.20")["routes"][-1] is None
    await hass.services.async_call(DOMAIN, "undo", {"entity_id": "select.lobby_source"}, blocking=True)
    assert FakeDecoder.state("192.0.2.20")["routes"][-1] == "CAM (1)"
    await hass.services.async_call(DOMAIN, "undo", {"entity_id": "select.lobby_source"}, blocking=True)
    assert FakeDecoder.state("192.0.2.20")["routes"][-1] == "OLD-PC (Gone)"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "undo", {"entity_id": "select.lobby_source"}, blocking=True)


async def test_routed_event_carries_user_context(hass: HomeAssistant, hass_admin_user) -> None:
    """The card's history shows who switched: the event must carry the caller's context."""
    await add_device(hass)
    events = async_capture_events(hass, EVENT_ROUTED)
    ctx = Context(user_id=hass_admin_user.id)
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.lobby_source", "source": "CAM (1)"}, blocking=True, context=ctx
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.lobby_source", "option": "STUDIO-PC (Slides)"},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.services.async_call(
        DOMAIN,
        "salvo",
        {"routes": [{"destination": "select.lobby_source", "source": "None"}]},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.services.async_call(
        DOMAIN, "undo", {"entity_id": "select.lobby_source"}, blocking=True, context=Context(user_id=hass_admin_user.id)
    )
    await hass.async_block_till_done()
    assert [e.data["origin"] for e in events] == ["service", "select", "salvo", "undo"]
    assert all(e.context.user_id == hass_admin_user.id for e in events)


async def test_lock_blocks_routing_and_persists(hass: HomeAssistant, hass_storage) -> None:
    await add_device(hass)
    await hass.services.async_call(DOMAIN, "lock", {"entity_id": "select.lobby_source"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("switch.lobby_route_lock").state == "on"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": "select.lobby_source", "option": "CAM (1)"}, blocking=True
        )
    assert FakeDecoder.state("192.0.2.20")["routes"] == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert hass_storage[DOMAIN]["data"]["locks"] == ["magewell-sn-192.0.2.20_main"]
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.lobby_route_lock"}, blocking=True)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.lobby_source", "option": "CAM (1)"}, blocking=True
    )
    assert FakeDecoder.state("192.0.2.20")["routes"] == ["CAM (1)"]


async def test_salvo_and_device_target(hass: HomeAssistant) -> None:
    await add_device(hass)
    second = await add_device(hass, "192.0.2.22", "Stage")
    await hass.services.async_call(
        DOMAIN,
        "salvo",
        {
            "routes": [
                {"destination": "select.lobby_source", "source": "CAM (1)"},
                {"destination": "select.stage_source", "source": "STUDIO-PC (Slides)"},
            ]
        },
        blocking=True,
    )
    assert FakeDecoder.state("192.0.2.20")["routes"] == ["CAM (1)"]
    assert FakeDecoder.state("192.0.2.22")["routes"] == ["STUDIO-PC (Slides)"]
    # a locked destination makes the whole salvo fail before anything is switched
    await hass.services.async_call(DOMAIN, "lock", {"entity_id": "select.stage_source"}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "salvo",
            {
                "routes": [
                    {"destination": "select.lobby_source", "source": "None"},
                    {"destination": "select.stage_source", "source": "None"},
                ]
            },
            blocking=True,
        )
    assert FakeDecoder.state("192.0.2.20")["routes"] == ["CAM (1)"]
    device = dr.async_get(hass).async_get(er.async_get(hass).async_get("select.stage_source").device_id)
    assert (DOMAIN, second.unique_id) in device.identifiers
    await hass.services.async_call(DOMAIN, "unlock", {"device_id": device.id}, blocking=True)
    await hass.services.async_call(DOMAIN, "route", {"device_id": device.id, "source": "CAM (1)"}, blocking=True)
    assert FakeDecoder.state("192.0.2.22")["routes"][-1] == "CAM (1)"


async def test_route_error_is_reported(hass: HomeAssistant) -> None:
    await add_device(hass)
    FakeDecoder.state("192.0.2.20")["fail"] = CannotConnect("timeout")
    with pytest.raises(HomeAssistantError, match="timeout"):
        await hass.services.async_call(
            DOMAIN, "route", {"entity_id": "select.lobby_source", "source": "CAM (1)"}, blocking=True
        )


async def test_offline_backoff_and_recovery(hass: HomeAssistant) -> None:
    entry = await add_device(hass)
    coordinator = entry.runtime_data.coordinator
    FakeDecoder.state("192.0.2.20")["fail"] = CannotConnect("timeout")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.lobby_connection").state == "offline"
    assert hass.states.get("select.lobby_source").state == "unavailable"
    assert coordinator.update_interval == timedelta(seconds=10)
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(seconds=30)  # capped
    FakeDecoder.state("192.0.2.20")["fail"] = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.update_interval == timedelta(seconds=5)
    assert hass.states.get("sensor.lobby_connection").state == "connected"


async def test_resolution_follows_up_after_route(hass: HomeAssistant) -> None:
    """Live-test regression: after switching the resolution must not stay unknown until the next
    regular poll (here 60 s) - follow-up polls run until the device reports it."""
    await add_device(hass, options={"scan_interval": 60})
    state = FakeDecoder.state("192.0.2.20")
    state["settle_polls"] = 2  # immediate poll + first follow-up see no video yet
    assert hass.states.get("sensor.lobby_resolution").state == "1920x1080p50"
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.lobby_source", "source": "CAM (1)"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.lobby_resolution").state == "unknown"  # not the old stream's value
    now = dt_util.utcnow()
    async_fire_time_changed(hass, now + timedelta(seconds=1.6))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.lobby_resolution").state == "unknown"
    async_fire_time_changed(hass, now + timedelta(seconds=3.1))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.lobby_resolution").state == "1920x1080p50"
    assert hass.states.get("sensor.lobby_connection").state == "connected"
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    assert coordinator._followup is None  # settled → no more follow-ups


async def test_poll_started_before_route_does_not_undo_it(hass: HomeAssistant) -> None:
    entry = await add_device(hass, options={"scan_interval": 60})
    coordinator = entry.runtime_data.coordinator
    state = FakeDecoder.state("192.0.2.20")
    gate = state["gate"] = asyncio.Event()
    slow = asyncio.ensure_future(coordinator.async_refresh())  # reads "OLD-PC (Gone)", then waits
    for _ in range(3):
        await asyncio.sleep(0)
    state["gate"] = None
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.lobby_source", "source": "CAM (1)"}, blocking=True
    )
    await hass.async_block_till_done()
    gate.set()  # the slow poll finishes after the route with the old answer
    await slow
    await hass.async_block_till_done()
    assert hass.states.get("select.lobby_source").state == "CAM (1)"
    await coordinator.async_refresh()  # a poll started after the route is the truth again
    state["current"] = "STUDIO-PC (Slides)"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("select.lobby_source").state == "STUDIO-PC (Slides)"


async def test_auth_failure_starts_reauth(hass: HomeAssistant) -> None:
    entry = await add_device(hass)
    FakeDecoder.state("192.0.2.20")["fail"] = InvalidAuth("nope")
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)
    flow = next(f for f in flows if f["context"]["source"] == "reauth")
    FakeDecoder.state("192.0.2.20")["fail"] = None
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"username": "Admin", "password": "new"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new"


async def test_setup_retry_when_offline(hass: HomeAssistant) -> None:
    FakeDecoder.state("192.0.2.23")["fail"] = CannotConnect("timeout")
    entry = MockConfigEntry(
        domain=DOMAIN, title="X", unique_id="u", data={"driver": "magewell", "host": "192.0.2.23", "password": "x"}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


# ------------------------------------------------------------- linked display
async def test_options_flow_and_linked_display(hass: HomeAssistant) -> None:
    entry = await add_device(hass)
    hass.states.async_set("media_player.lobby_tv", "off", {"source_list": ["HDMI 1", "HDMI 2"]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 7})
    assert result["step_id"] == "display"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entity_id": "media_player.lobby_tv", "auto_on": True, "off_on_none": True}
    )
    assert result["step_id"] == "display_input"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"input": "HDMI 2"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "scan_interval": 7,
        "displays": {
            "main": {"entity_id": "media_player.lobby_tv", "auto_on": True, "off_on_none": True, "input": "HDMI 2"}
        },
    }
    await hass.async_block_till_done()  # reload

    turn_on = async_mock_service(hass, "media_player", "turn_on")
    select_source = async_mock_service(hass, "media_player", "select_source")
    turn_off = async_mock_service(hass, "media_player", "turn_off")
    hass.states.async_set("media_player.lobby_tv", "on", {"source": "HDMI 1", "source_list": ["HDMI 1", "HDMI 2"]})
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.lobby_source", "source": "CAM (1)"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(turn_on) == 0
    assert select_source[0].data == {"entity_id": "media_player.lobby_tv", "source": "HDMI 2"}
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.lobby_source", "source": "None"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(turn_off) == 1


# ------------------------------------------------------------------ websocket
async def test_websocket_state_subscribe_label(hass: HomeAssistant, hass_ws_client) -> None:
    await add_device(hass)
    hub = hass.data[DATA_HUB]
    await hub.async_evaluate()
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "av_matrix/state"})
    msg = await client.receive_json()
    assert msg["success"]
    ndi = msg["result"]["protocols"]["ndi"]
    manifest = json.loads((Path(__file__).parents[1] / "custom_components/av_matrix/manifest.json").read_text())
    assert msg["result"]["version"] == manifest["version"]  # bumped by every release
    assert ndi["title"] == "NDI®"
    assert {s["id"]: s["live"] for s in ndi["sources"]} == {
        "CAM (1)": True,
        "OLD-PC (Gone)": False,
        "STUDIO-PC (Slides)": True,
    }
    dest = ndi["destinations"][0]
    assert dest["entity_id"] == "select.lobby_source"
    assert dest["current_source"] == "OLD-PC (Gone)" and dest["current_source_live"] is False
    assert dest["status"] == "connected" and dest["locked"] is False and dest["display"] is None
    assert dest["device_name"] == "Lobby" and dest["protocol"] == "ndi" and dest["resolution"] == "1920x1080p50"

    await client.send_json({"id": 2, "type": "av_matrix/subscribe"})
    sub_id = 2
    msg = await client.receive_json()
    assert msg["success"]
    msg = await client.receive_json()
    assert msg["type"] == "event" and msg["id"] == sub_id

    await client.send_json(
        {
            "id": 3,
            "type": "av_matrix/label",
            "protocol": "ndi",
            "source": "CAM (1)",
            "label": "Camera 1",
            "tags": ["cams"],
        }
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"] == {"label": "Camera 1", "tags": ["cams"]}
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    msg = await client.receive_json()
    assert msg["type"] == "event"
    cam = next(s for s in msg["event"]["protocols"]["ndi"]["sources"] if s["id"] == "CAM (1)")
    assert cam["name"] == "Camera 1" and cam["tags"] == ["cams"]
    await hass.async_block_till_done()
    # the label is used in the select and resolved back when routing
    assert "Camera 1" in hass.states.get("select.lobby_source").attributes["options"]
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.lobby_source", "option": "Camera 1"}, blocking=True
    )
    assert FakeDecoder.state("192.0.2.20")["routes"] == ["CAM (1)"]


async def test_diagnostics_redacts_password(hass: HomeAssistant) -> None:
    entry = await add_device(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"]["password"] == "**REDACTED**"
    assert "topsecret" not in str(diag)


async def test_unload(hass: HomeAssistant) -> None:
    entry = await add_device(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.data[DATA_HUB].destinations == {}
