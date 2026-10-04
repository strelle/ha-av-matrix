"""BirdDog driver against mocked REST answers (structure from BirdDog PLAY FW 1.0.14; device untested here)."""

from __future__ import annotations

import json

import pytest

from custom_components.av_matrix.drivers import CannotConnect, InvalidAuth, RouteFailed
from custom_components.av_matrix.drivers.birddog import BirdDogDecoder

B = "http://192.0.2.30:8080"


@pytest.fixture(autouse=True)
def fast_verify(monkeypatch):
    monkeypatch.setattr(BirdDogDecoder, "VERIFY_DELAY", 0)


def driver(session, **cfg):
    return BirdDogDecoder(session, {"host": "192.0.2.30", **cfg})


def calls(session):
    return [(method, url, kw.get("json")) for method, url, kw in session.calls]


async def test_info(session):
    session.get_(
        f"{B}/about",
        payload={
            "FirmwareVersion": "1.0.14",
            "HostName": "LOBBY-PLAY.local",
            "SerialNumber": "BD1234",
            "IPAddress": "192.0.2.30",
        },
    )
    info = await driver(session).async_get_info()
    assert info.name == "LOBBY-PLAY"
    assert info.firmware == "1.0.14"
    assert info.serial == "BD1234"


async def test_info_not_birddog(session):
    session.get_(f"{B}/about", status=404)
    with pytest.raises(CannotConnect):
        await driver(session).async_get_info()


async def test_list_skips_none_keeps_placeholders(session):
    session.get_(
        f"{B}/List",
        payload={"STUDIO-PC (Slides)": "192.0.2.40:5961", "NDI_0A1B2C3D4E": "192.0.2.41:5962", "None": "None"},
    )
    sources = await driver(session).async_get_sources()
    assert [(s.name, s.address) for s in sources] == [
        ("STUDIO-PC (Slides)", "192.0.2.40:5961"),
        ("NDI_0A1B2C3D4E", "192.0.2.41:5962"),
    ]


async def test_empty_list(session):
    session.get_(f"{B}/List", payload={"None": "None"})
    assert await driver(session).async_get_sources() == []


async def test_current_none(session):
    session.get_(f"{B}/connectTo", payload={"sourceName": "None"})
    assert await driver(session).async_get_current("1") is None


async def test_route_verifies(session):
    session.post_(f"{B}/connectTo", payload={"sourceName": "STUDIO-PC (Slides)"})
    session.get_(f"{B}/connectTo", payload={"sourceName": "STUDIO-PC (Slides)"})
    await driver(session).async_route("1", "STUDIO-PC (Slides)")
    assert ("POST", f"{B}/connectTo", {"sourceName": "STUDIO-PC (Slides)"}) in calls(session)


async def test_route_retries_once_then_succeeds(session):
    session.post_(f"{B}/connectTo", payload={}, repeat=True)
    session.get_(f"{B}/connectTo", payload={"sourceName": "OLD (X)"})
    session.get_(f"{B}/connectTo", payload={"sourceName": "NEW (Y)"})
    await driver(session).async_route("1", "NEW (Y)")
    assert sum(1 for c in calls(session) if c[0] == "POST") == 2


async def test_route_fails_after_retry(session):
    session.post_(f"{B}/connectTo", payload={}, repeat=True)
    session.get_(f"{B}/connectTo", payload={"sourceName": "OLD (X)"}, repeat=True)
    with pytest.raises(RouteFailed):
        await driver(session).async_route("1", "NEW (Y)")


async def test_multichannel_sends_chnum(session):
    d = driver(session, channels=2)
    assert [x.id for x in d.destinations()] == ["1", "2"]
    session.post_(f"{B}/connectTo", payload={})
    session.get_(f"{B}/connectTo?ChNum=2", payload={"sourceName": "A (B)"})
    await d.async_route("2", "A (B)")
    assert ("POST", f"{B}/connectTo", {"sourceName": "A (B)", "ChNum": 2}) in calls(session)


async def test_refresh_falls_back_to_get(session):
    session.post_(f"{B}/refresh", status=405)
    session.get_(f"{B}/refresh", body="ok")
    await driver(session).async_refresh_sources()
    assert [c[0] for c in calls(session)] == ["POST", "GET"]


async def test_401_triggers_login_and_retry(session):
    d = driver(session, password="pw")
    session.get_(f"{B}/about", status=401)
    session.post_(
        "http://192.0.2.30/login", status=302, headers={"Set-Cookie": "BirdDogSession=tok; Path=/", "Location": "/"}
    )
    session.get_(f"{B}/about", payload={"HostName": "X.local"})
    info = await d.async_get_info()
    assert info.name == "X"
    assert d._cookie == "tok"


async def test_401_without_password(session):
    session.get_(f"{B}/about", status=401)
    with pytest.raises(InvalidAuth):
        await driver(session).async_get_info()


async def test_decodestatus_parsing(session):
    session.get_(
        f"{B}/decodestatus", body=json.dumps({"Status": "Connected", "Resolution": "1920x1080p", "FrameRate": "50"})
    )
    status = await driver(session).async_get_status("1")
    assert status.connected is True
    assert status.resolution == "1920x1080p@50"


async def test_decodestatus_unsupported(session):
    d = driver(session)
    session.get_(f"{B}/decodestatus", status=404)
    status = await d.async_get_status("1")
    assert status.connected is None
    status = await d.async_get_status("1")  # not asked again
    assert len(calls(session)) == 1


async def test_missing_endpoint_is_a_driver_error(session):
    """HTTP 404 on a core endpoint must surface as CannotConnect (handled by coordinator / route)."""
    session.get_(f"{B}/List", status=404)
    with pytest.raises(CannotConnect):
        await driver(session).async_get_sources()
