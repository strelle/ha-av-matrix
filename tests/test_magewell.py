"""Magewell Pro Convert driver against mocked /mwapi answers (structures from a real device, anonymised)."""

from __future__ import annotations

import hashlib
import re

import pytest

from custom_components.av_matrix.drivers import CannotConnect, InvalidAuth, RouteFailed
from custom_components.av_matrix.drivers.magewell import MagewellProConvert

BASE = "http://192.0.2.20/mwapi"
API = re.compile(r"^http://192\.0\.2\.20/mwapi\?method=(?P<m>[a-z-]+).*$")

SUMMARY = {
    "status": 0,
    "device": {
        "name": "PRO-CONVERT-LOBBY",
        "model": "NDI to AIO",
        "product-id": 1057,
        "auth-type": 4,
        "serial-no": "A123456789",
        "hw-revision": "A",
        "fw-version": "1.3.24",
        "up-to-date": True,
        "output-state": "connected",
    },
    "ethernet": {"state": "1000m", "mac-addr": "00:11:22:33:44:55", "ip-addr": "192.0.2.20"},
    "ndi": {
        "connected": True,
        "name": "STUDIO-PC (Slides)",
        "video-width": 1920,
        "video-height": 1080,
        "video-scan": "progressive",
        "video-field-rate": 50,
        "video-bit-rate": 120000,
        "video-drop-frames": 0,
    },
}


def driver(session, **cfg):
    return MagewellProConvert(session, {"host": "192.0.2.20", "username": "Admin", "password": "secret", **cfg})


def methods(session):
    return [API.match(url).group("m") for (method, url, kw) in session.calls]


def urls(session):
    return [url for (method, url, kw) in session.calls]


async def test_login_and_info(session):
    session.get_(
        f"{BASE}?method=login&id=Admin&pass={hashlib.md5(b'secret').hexdigest()}",
        payload={"status": 0},
        headers={"Set-Cookie": "sid=abc123; path=/"},
    )
    session.get_(API, payload=SUMMARY)
    info = await driver(session).async_get_info()
    assert info.name == "PRO-CONVERT-LOBBY"
    assert info.model == "Pro Convert NDI to AIO"
    assert info.firmware == "1.3.24"
    assert info.serial == "A123456789"
    assert info.mac == "00:11:22:33:44:55"


async def test_sid_cookie_is_sent(session):
    d = driver(session)
    session.get_(API, payload={"status": 0}, headers={"Set-Cookie": "sid=s1; path=/"})
    session.get_(API, payload={"status": 0, "name": "", "ndi-name": True})
    await d.async_get_current("main")
    assert d._sid == "s1"
    # second request (get-channel) carried the cookie
    assert session.calls[1][2]["headers"]["Cookie"] == "sid=s1"


async def test_wrong_password_raises_invalid_auth(session):
    session.get_(API, payload={"status": 36})
    with pytest.raises(InvalidAuth):
        await driver(session).async_get_info()


async def test_not_logged_in_relogs_once(session):
    d = driver(session)
    d._sid = "expired"
    session.get_(API, payload={"status": 37})  # get-channel -> not logged in
    session.get_(API, payload={"status": 0}, headers={"Set-Cookie": "sid=new"})  # login
    session.get_(API, payload={"status": 0, "name": "STUDIO-PC (Slides)", "ndi-name": True})
    current = await d.async_get_current("main")
    assert current == "STUDIO-PC (Slides)"
    assert methods(session) == ["get-channel", "login", "get-channel"]
    assert d._sid == "new"


async def test_sources_and_current(session):
    d = driver(session)
    d._sid = "x"
    session.get_(
        API,
        payload={
            "status": 0,
            "sources": [
                {"ndi-name": "HOST.LOCALDOMAIN (Test Patterns)", "ip-addr": "192.0.2.50:5961"},
                {"ndi-name": "", "ip-addr": "192.0.2.51:5961"},
            ],
        },
    )
    session.get_(API, payload={"status": 0, "name": "HOST (Old stream)", "ndi-name": True})
    sources = await d.async_get_sources()
    current = await d.async_get_current("main")
    assert [(s.name, s.address) for s in sources] == [("HOST.LOCALDOMAIN (Test Patterns)", "192.0.2.50:5961")]
    # current source is reported even though it is not in the source list any more
    assert current == "HOST (Old stream)"


async def test_route_url_encodes_name(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload={"status": 0})
    await d.async_route("main", "STUDIO-PC (Slides & Notes) Ü")
    url = urls(session)[0]
    assert "method=set-channel" in url
    assert "ndi-name=true" in url
    assert "name=STUDIO-PC%20%28Slides%20%26%20Notes%29%20%C3%9C" in url


async def test_route_none_sends_empty_name(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload={"status": 0})
    await d.async_route("main", None)
    assert urls(session)[0].endswith("name=")


async def test_route_error_status(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload={"status": 5})
    with pytest.raises(RouteFailed):
        await d.async_route("main", "X (Y)")


async def test_status_resolution(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload=SUMMARY)
    session.get_(API, payload={"status": 0, "signal-info-types": []})
    status = await d.async_get_status("main", "STUDIO-PC (Slides)")
    assert status.connected is True
    assert status.resolution == "1920x1080p50"
    assert status.extra == {"bitrate_kbps": 120000, "dropped_frames": 0}


SIGNAL_INFO = {
    "status": 0,
    "signal-info-types": ["video-info"],
    "video-info": {
        "codec": "shq2",
        "width": 1920,
        "height": 1080,
        "scan": "progressive",
        "color-depth": 8,
        "field-rate": 30.0,
        "quant-range": "limited",
        "sat-range": "limited",
        "frame-struct": "2d",
        "aspect-ratio": "16:9",
        "color-format": "bt.709",
        "sampling": "4:2:2",
    },
}
# FW 1.3.24 as observed live: no "ndi" block, connection from device.output-state
SUMMARY_FW1324 = {
    "status": 0,
    "device": {**SUMMARY["device"], "output-state": "connected"},
    "ethernet": SUMMARY["ethernet"],
}


async def test_status_fw1324_output_state_and_signal_info(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload=SUMMARY_FW1324)
    session.get_(API, payload=SIGNAL_INFO)
    status = await d.async_get_status("main")
    assert methods(session) == ["get-summary-info", "get-signal-info"]
    assert status.connected is True
    assert status.resolution == "1920x1080p30"
    assert status.extra == {
        "codec": "shq2",
        "color_format": "bt.709",
        "sampling": "4:2:2",
        "color_depth": 8,
        "aspect_ratio": "16:9",
        "quant_range": "limited",
    }


async def test_status_interlaced(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload=SUMMARY_FW1324)
    session.get_(
        API,
        payload={"status": 0, "video-info": {"width": 1920, "height": 1080, "scan": "interlaced", "field-rate": 50.0}},
    )
    assert (await d.async_get_status("main")).resolution == "1920x1080i50"


async def test_status_not_connected_skips_signal_info(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload={"status": 0, "device": {"output-state": "disconnected"}})
    status = await d.async_get_status("main")
    assert status.connected is False
    assert status.resolution is None
    assert methods(session) == ["get-summary-info"]


async def test_status_defensive_unknown_fields(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload={"status": 0})
    session.get_(API, payload={"status": 0, "video-info": "garbage"})
    status = await d.async_get_status("main")
    assert status.connected is None
    assert status.resolution is None


async def test_poll(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload={"status": 0, "sources": [{"ndi-name": "A (B)", "ip-addr": "192.0.2.5:5961"}]})
    session.get_(API, payload={"status": 0, "name": "STUDIO-PC (Slides)", "ndi-name": True})
    session.get_(API, payload=SUMMARY)
    session.get_(API, payload=SIGNAL_INFO)
    poll = await d.async_poll()
    assert poll.destinations["main"].current == "STUDIO-PC (Slides)"
    assert poll.destinations["main"].status.connected is True
    # get-signal-info describes the decoded stream and wins over the summary
    assert poll.destinations["main"].status.resolution == "1920x1080p30"
    assert poll.destinations["main"].status.extra["codec"] == "shq2"


# --- regression: resolution "unknown" after switching (live test, FW 1.3.24, "HOST (Test Patterns)")
# The real summary carries an "ndi" block (name, connected, video-width/-height/-scan/-field-rate …).
SUMMARY_LIVE = {
    "status": 0,
    "device": {**SUMMARY["device"], "output-state": "connected"},
    "ethernet": SUMMARY["ethernet"],
    "ndi": {
        "name": "HOST (Test Patterns)",
        "url": "",
        "connected": True,
        "video-drop-frames": 0,
        "video-bit-rate": 113414,
        "video-width": 1920,
        "video-height": 1080,
        "video-scan": "progressive",
        "video-field-rate": 30.0,
    },
}


def _summary(**ndi):
    return {**SUMMARY_LIVE, "ndi": {**SUMMARY_LIVE["ndi"], **ndi}}


async def test_switch_in_progress_reports_connecting_without_old_resolution(session):
    """Right after set-channel the summary still describes the previous stream."""
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload=_summary(name="OLD-PC (Program)", **{"video-width": 3840, "video-height": 2160}))
    status = await d.async_get_status("main", "HOST (Test Patterns)")
    assert status.connected is False  # → "connecting", follow-up polls continue
    assert status.resolution is None
    assert methods(session) == ["get-summary-info"]


async def test_connected_but_no_video_yet_then_resolution(session):
    """Connected, summary without video values, signal-info without video-info → None (no signal yet),
    the next poll reports the resolution - nothing sticks at an old or 'unknown' value."""
    d = driver(session)
    d._sid = "x"
    no_video = _summary(**{"video-width": 0, "video-height": 0, "video-field-rate": 0.0})
    session.get_(API, payload=no_video)
    session.get_(API, payload={"status": 0, "signal-info-types": []})
    first = await d.async_get_status("main", "HOST (Test Patterns)")
    assert first.connected is True
    assert first.resolution is None
    session.get_(API, payload=no_video)
    session.get_(API, payload=SIGNAL_INFO)
    second = await d.async_get_status("main", "HOST (Test Patterns)")
    assert second.resolution == "1920x1080p30"


async def test_signal_info_types_without_video_ignores_stale_video_info(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload=SUMMARY_FW1324)
    session.get_(API, payload={**SIGNAL_INFO, "signal-info-types": ["audio-info"]})
    status = await d.async_get_status("main")
    assert status.resolution is None
    assert "codec" not in status.extra


async def test_summary_ndi_block_interlaced_and_live_keys(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload=_summary(**{"video-scan": "interlaced", "video-field-rate": 50.0}))
    session.get_(API, payload={"status": 0, "signal-info-types": []})
    status = await d.async_get_status("main", "host (test patterns)")  # name compare ignores case
    assert status.resolution == "1920x1080i50"
    assert status.extra == {"bitrate_kbps": 113414, "dropped_frames": 0}


async def test_preset_channel_is_not_treated_as_switching(session):
    d = driver(session)
    d._sid = "x"
    session.get_(API, payload={"status": 0, "sources": []})
    session.get_(API, payload={"status": 0, "name": "Stage", "ndi-name": False})
    session.get_(API, payload=SUMMARY_LIVE)
    session.get_(API, payload=SIGNAL_INFO)
    poll = await d.async_poll()
    assert poll.destinations["main"].current == "[preset] Stage"
    assert poll.destinations["main"].status.connected is True
    assert poll.destinations["main"].status.resolution == "1920x1080p30"


async def test_connection_error_text_never_contains_password_hash(session):
    import aiohttp

    digest = hashlib.md5(b"secret").hexdigest()
    session.get_(API, exception=aiohttp.InvalidURL(f"{BASE}?method=login&id=Admin&pass={digest}"))
    with pytest.raises(CannotConnect) as err:
        await driver(session).async_get_info()
    assert digest not in str(err.value)


async def test_unreachable(session):
    session.get_(API, exception=TimeoutError())
    with pytest.raises(CannotConnect):
        await driver(session).async_get_info()


async def test_not_a_magewell(session):
    session.get_(API, body="<html>hello</html>")
    with pytest.raises(CannotConnect):
        await driver(session).async_get_info()
