"""Linked display logic with a mocked hass."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.av_matrix.display import async_drive_display, display_state

CFG = {"entity_id": "media_player.lobby_tv", "input": "HDMI 2", "auto_on": True, "off_on_none": True}


def fake_hass(states):
    """states: list of (state, source) returned by successive hass.states.get calls (last one repeats)."""
    seq = list(states)
    hass = MagicMock()

    def get(entity_id):
        st, src = seq.pop(0) if len(seq) > 1 else seq[0]
        return SimpleNamespace(state=st, attributes={"source": src, "source_list": ["HDMI 1", "HDMI 2"]})

    hass.states.get.side_effect = get
    hass.services.async_call = AsyncMock()
    return hass


def services(hass):
    return [(c.args[1], c.args[2]) for c in hass.services.async_call.call_args_list]


async def test_turns_on_waits_and_selects_input():
    hass = fake_hass([("off", None), ("off", None), ("on", "HDMI 1")])
    err = await async_drive_display(hass, CFG, "A (B)", poll_interval=0)
    assert err is None
    assert services(hass) == [
        ("turn_on", {"entity_id": "media_player.lobby_tv"}),
        ("select_source", {"entity_id": "media_player.lobby_tv", "source": "HDMI 2"}),
    ]


async def test_already_on_and_on_input_does_nothing():
    hass = fake_hass([("on", "HDMI 2")])
    assert await async_drive_display(hass, CFG, "A (B)") is None
    assert services(hass) == []


async def test_timeout_reports_error_without_raising():
    hass = fake_hass([("off", None)])
    err = await async_drive_display(hass, CFG, "A (B)", timeout=0.01, poll_interval=0.005)
    assert "did not turn on" in err
    assert services(hass) == [("turn_on", {"entity_id": "media_player.lobby_tv"})]


async def test_service_error_is_caught():
    hass = fake_hass([("on", "HDMI 1")])
    hass.services.async_call.side_effect = RuntimeError("TV said no")
    assert await async_drive_display(hass, CFG, "A (B)") == "TV said no"


async def test_none_turns_off_only_if_configured():
    hass = fake_hass([("on", "HDMI 2")])
    await async_drive_display(hass, CFG, None)
    assert services(hass) == [("turn_off", {"entity_id": "media_player.lobby_tv"})]
    hass = fake_hass([("on", "HDMI 2")])
    await async_drive_display(hass, {**CFG, "off_on_none": False}, None)
    assert services(hass) == []


async def test_auto_on_disabled():
    hass = fake_hass([("off", None)])
    await async_drive_display(hass, {**CFG, "auto_on": False}, "A (B)")
    assert services(hass) == []


def test_display_state():
    hass = fake_hass([("on", "HDMI 2")])
    st = display_state(hass, CFG, None)
    assert st["entity_id"] == "media_player.lobby_tv"
    assert st["state"] == "on" and st["source"] == "HDMI 2" and st["configured_input"] == "HDMI 2"
    assert display_state(hass, None) is None
