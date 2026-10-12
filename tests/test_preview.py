"""NDI® preview relay: a fake Strelle AV Matrix server on localhost, Home Assistant's real HTTP stack in front."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from homeassistant import config_entries
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.av_matrix import source_types
from custom_components.av_matrix.const import DOMAIN
from custom_components.av_matrix.hub import DATA_HUB
from custom_components.av_matrix.preview import InvalidPreviewUrl, normalize_url

from .test_init import add_device, fake_env  # noqa: F401 - fake_env is an autouse fixture

ROOT = Path(__file__).parents[1]
JPEG = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 1200 + b"\xff\xd9"  # 300 kB: arrives in many pieces
STILL = "/api/av_matrix/preview.jpg"
STREAM = "/api/av_matrix/preview.mjpeg"
STATUS = "/api/av_matrix/preview"


class FakeServer:
    """The part of the server interface the integration uses (server/docs/SCHNITTSTELLE.md)."""

    def __init__(self) -> None:
        self.hits: list[tuple[str, dict[str, str]]] = []
        self.delay = 0.0
        self.is_matrix = True
        self.stream_closed = asyncio.Event()
        self.stream_frames = 0
        self.sources: list[dict[str, Any]] = [
            {
                "id": "STUDIO-PC (Slides)",
                "live": True,
                "device_type": "camera",
                "icon_key": "ndi_camera",
                "web_url": "http://192.0.2.50/",
            },
            {"id": "192.0.2.99 (AUX1)", "device_type": "encoder", "icon_key": "ndi_encoder", "web_url": None},
        ]
        self.aliases = {"192.0.2.7 (AUX1)": "192.0.2.99 (AUX1)"}
        self.url = ""

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/api/info", self.info)
        app.router.add_get("/api/state", self.state)
        app.router.add_get("/api/choices", self.choices)
        app.router.add_get("/api/preview", self.status)
        app.router.add_get("/api/preview.jpg", self.still)
        app.router.add_get("/api/preview.mjpeg", self.stream)
        return app

    async def info(self, request: web.Request) -> web.Response:
        if not self.is_matrix:
            return web.Response(text="<html>some other device</html>", content_type="text/html")
        return web.json_response({"name": "Strelle AV Matrix", "version": "1.0.0", "hostname": "matrix"})

    async def state(self, request: web.Request) -> web.Response:
        return web.json_response({"version": "1.0.0", "protocols": {"ndi": {"title": "NDI®", "sources": self.sources}}})

    async def choices(self, request: web.Request) -> web.Response:
        return web.json_response({"destinations": [], "sources": [], "presets": [], "aliases": self.aliases})

    async def status(self, request: web.Request) -> web.Response:
        self.hits.append(("status", dict(request.query)))
        data: dict[str, Any] = {"available": True, "reason": None, "hx_decoder": True, "live": []}
        if "source" in request.query:
            data["source"] = {"id": request.query["source"], "state": "ok"}
        return web.json_response(data)

    @staticmethod
    def _error(status: int, state: str) -> web.Response:
        return web.json_response(
            {"ok": False, "error": state, "message": "Klartext"}, status=status, headers={"X-Preview-State": state}
        )

    async def still(self, request: web.Request) -> web.Response:
        self.hits.append(("still", dict(request.query)))
        if self.delay:
            await asyncio.sleep(self.delay)
        source = request.query.get("source")
        errors = {"OFF (1)": (404, "offline"), "NOPE (1)": (404, "unknown_source"), "DARK (1)": (503, "no_signal")}
        errors |= {"HX (1)": (415, "unsupported_codec"), "NOSDK (1)": (501, "unavailable")}
        if source in errors:
            return self._error(*errors[source])
        if source == "BROKEN (1)":
            return web.Response(status=500, text="boom")
        headers = {"X-Preview-State": "ok", "X-Preview-Age": "1.2", "X-Preview-Size": "640x360"}
        headers["X-Preview-Origin"] = "device" if source == "192.0.2.99 (AUX1)" else "ndi"
        return web.Response(body=JPEG, content_type="image/jpeg", headers=headers)

    async def stream(self, request: web.Request) -> web.StreamResponse:
        self.hits.append(("stream", dict(request.query)))
        if request.query.get("source") == "OFF (1)":
            return self._error(404, "offline")
        resp = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=avmframe"})
        await resp.prepare(request)
        try:
            for _ in range(400):  # until the viewer leaves (at most 20 s)
                head = f"--avmframe\r\nContent-Type: image/jpeg\r\nContent-Length: {len(JPEG)}\r\n\r\n".encode()
                await resp.write(head + JPEG + b"\r\n")
                self.stream_frames += 1
                await asyncio.sleep(0.05)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.stream_closed.set()
        return resp


@pytest.fixture
async def server(socket_enabled, aiohttp_server) -> FakeServer:
    fake = FakeServer()
    running = await aiohttp_server(fake.app())
    fake.url = f"http://127.0.0.1:{running.port}"
    return fake


async def configure(hass: HomeAssistant, server: FakeServer) -> None:
    """One decoder plus the preview server (set the way the options flow does it)."""
    await add_device(hass)
    hass.data[DATA_HUB].async_set_preview_server(server.url)
    await hass.async_block_till_done(wait_background_tasks=True)


# ------------------------------------------------------------------ address
@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("", None),
        (None, None),
        ("  ", None),
        ("192.0.2.8", "http://192.0.2.8:8088"),
        ("matrix.local", "http://matrix.local:8088"),
        ("192.0.2.8:9000", "http://192.0.2.8:9000"),
        (" http://192.0.2.8:8088/ ", "http://192.0.2.8:8088"),
        ("http://matrix.local", "http://matrix.local"),
        ("https://matrix.example.org/av/", "https://matrix.example.org/av"),
    ],
)
def test_normalize_url(text, url) -> None:
    assert normalize_url(text) == url


@pytest.mark.parametrize(
    "text", ["ftp://192.0.2.8", "http://", "http://user:pw@192.0.2.8", "http://a b", "x:y:z", "http://h?x=1"]
)
def test_normalize_url_rejects(text) -> None:
    with pytest.raises(InvalidPreviewUrl):
        normalize_url(text)


# ------------------------------------------------------------------ device types
def test_rule_table_is_the_servers() -> None:
    """One rule table for both variants: the integration ships an identical copy of the server's file."""
    ours = (ROOT / "custom_components/av_matrix/source_types.py").read_text()
    assert ours == (ROOT / "server/avmatrix/source_types.py").read_text()
    for _label, icon in source_types.TYPES.values():
        assert (ROOT / f"custom_components/av_matrix/frontend/devices/{icon}.svg").is_file()
    for extra in (ROOT / "server/avmatrix/static/devices-extra").glob("*.svg"):
        assert (ROOT / "custom_components/av_matrix/frontend/devices" / extra.name).read_bytes() == extra.read_bytes()
    for mark in ("wortmarke-hell.svg", "wortmarke-dunkel.svg", "strelle-icon.svg"):  # original marks, unchanged
        ours_mark = ROOT / "custom_components/av_matrix/frontend/brand" / mark
        assert ours_mark.read_bytes() == (ROOT / "server/avmatrix/static/brand" / mark).read_bytes()


async def test_snapshot_without_preview_server(hass: HomeAssistant) -> None:
    await add_device(hass)
    snap = hass.data[DATA_HUB].snapshot()
    assert snap["preview"]["configured"] is False and snap["preview"]["protocols"] == []
    assert snap["preview"]["reachable"] is None
    ndi = snap["protocols"]["ndi"]
    assert ndi["video"] is True and ndi["preview"] is False
    kinds = {s["id"]: (s["device_type"], s["icon_key"], s["web_url"]) for s in ndi["sources"]}
    assert kinds["CAM (1)"] == ("camera", "ndi_camera", None)
    assert kinds["STUDIO-PC (Slides)"] == ("unknown", "ndi_source", None)


async def test_snapshot_uses_what_the_server_knows(hass: HomeAssistant, server: FakeServer, hass_storage) -> None:
    await configure(hass, server)
    hub = hass.data[DATA_HUB]
    snap = hub.snapshot()
    assert snap["preview"] == {
        "configured": True,
        "reachable": True,
        "available": True,
        "reason": None,
        "hx_decoder": True,
        "server": {"name": "Strelle AV Matrix", "version": "1.0.0"},
        "protocols": ["ndi"],
        "still_url": STILL,
        "stream_url": STREAM,
        "status_url": STATUS,
    }
    ndi = snap["protocols"]["ndi"]
    assert ndi["preview"] is True
    kinds = {s["id"]: (s["device_type"], s["icon_key"], s["web_url"]) for s in ndi["sources"]}
    assert kinds["STUDIO-PC (Slides)"] == ("camera", "ndi_camera", "http://192.0.2.50/")  # the server knows better
    assert kinds["CAM (1)"] == ("camera", "ndi_camera", None)  # unknown to the server: our own rules
    assert hub.preview.meta("192.0.2.7 (AUX1)")["device_type"] == "encoder"  # former name of a renamed source
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert hass_storage[DOMAIN]["data"]["preview_server"] == server.url


async def test_server_down_keeps_matrix_and_device_types(hass: HomeAssistant, socket_enabled, aiohttp_server) -> None:
    fake = FakeServer()
    running = await aiohttp_server(fake.app())
    fake.url = f"http://127.0.0.1:{running.port}"
    await configure(hass, fake)
    hub = hass.data[DATA_HUB]
    await running.close()
    await hub.preview.async_refresh()
    snap = hub.snapshot()
    assert snap["preview"]["configured"] is True and snap["preview"]["reachable"] is False
    kinds = {s["id"]: s["device_type"] for s in snap["protocols"]["ndi"]["sources"]}
    assert kinds["STUDIO-PC (Slides)"] == "camera"  # kept, the icons do not jump
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.lobby_source", "source": "CAM (1)"}, blocking=True
    )
    assert hub.snapshot()["protocols"]["ndi"]["destinations"][0]["current_source"] == "CAM (1)"


# ------------------------------------------------------------------ options flow
async def test_options_flow_sets_and_clears_the_server(hass: HomeAssistant, server: FakeServer) -> None:
    entry = await add_device(hass)
    hub = hass.data[DATA_HUB]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init" and "preview_server" in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 5, "preview_server": server.url + "/"}
    )
    assert result["step_id"] == "display"
    assert hub.preview.url == server.url
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hub.snapshot()["preview"]["reachable"] is True

    # the stored address is offered again; emptying the field removes it
    result = await hass.config_entries.options.async_init(entry.entry_id)
    key = next(k for k in result["data_schema"].schema if k == "preview_server")
    assert key.description == {"suggested_value": server.url}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 5})
    assert hub.preview.url is None
    assert hub.snapshot()["preview"]["configured"] is False


async def test_options_flow_rejects_wrong_addresses(hass: HomeAssistant, server: FakeServer, unused_tcp_port) -> None:
    entry = await add_device(hass)
    hub = hass.data[DATA_HUB]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]
    result = await hass.config_entries.options.async_configure(
        flow_id, {"scan_interval": 9, "preview_server": "ftp://x"}
    )
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"preview_server": "preview_invalid_url"}
    assert next(iter(result["data_schema"].schema)).default() == 9  # what was entered is kept
    result = await hass.config_entries.options.async_configure(
        flow_id, {"scan_interval": 9, "preview_server": f"http://127.0.0.1:{unused_tcp_port}"}
    )
    assert result["errors"] == {"preview_server": "preview_cannot_connect"}
    server.is_matrix = False
    result = await hass.config_entries.options.async_configure(
        flow_id, {"scan_interval": 9, "preview_server": server.url}
    )
    assert result["errors"] == {"preview_server": "preview_not_matrix"}
    assert hub.preview.url is None


async def test_server_found_by_zeroconf_is_suggested(hass: HomeAssistant) -> None:
    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.8"),
        ip_addresses=[ip_address("192.0.2.8")],
        hostname="matrix.local.",
        name="Strelle AV Matrix._http._tcp.local.",
        port=8088,
        type="_http._tcp.local.",
        properties={"path": "/", "product": "av-matrix-server", "version": "1.0.0"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "preview_server_found"
    entry = await add_device(hass)  # the announcement came before the first device: still offered
    assert hass.data[DATA_HUB].preview.url is None  # nothing is set by itself
    result = await hass.config_entries.options.async_init(entry.entry_id)
    key = next(k for k in result["data_schema"].schema if k == "preview_server")
    assert key.description == {"suggested_value": "http://192.0.2.8:8088"}


# ------------------------------------------------------------------ relays
async def test_still_is_relayed_with_its_headers(hass: HomeAssistant, server: FakeServer, hass_client) -> None:
    await configure(hass, server)
    client = await hass_client()
    resp = await client.get(STILL, params={"source": "STUDIO-PC (Slides)", "w": "320"})
    assert resp.status == 200 and resp.content_type == "image/jpeg"
    assert await resp.read() == JPEG
    assert resp.headers["X-Preview-State"] == "ok" and resp.headers["X-Preview-Origin"] == "ndi"
    assert resp.headers["X-Preview-Age"] == "1.2" and resp.headers["X-Preview-Size"] == "640x360"
    assert resp.headers["Cache-Control"] == "no-store"
    assert server.hits[-1] == ("still", {"source": "STUDIO-PC (Slides)", "w": "320"})  # the exact NDI name

    resp = await client.get(STILL, params={"source": "192.0.2.99 (AUX1)", "w": "9999"})
    assert resp.headers["X-Preview-Origin"] == "device"
    assert server.hits[-1][1]["w"] == "640"  # clamped to what the server accepts


@pytest.mark.parametrize(
    ("source", "status", "state"),
    [
        ("OFF (1)", 404, "offline"),
        ("NOPE (1)", 404, "unknown_source"),
        ("DARK (1)", 503, "no_signal"),
        ("HX (1)", 415, "unsupported_codec"),
        ("NOSDK (1)", 501, "unavailable"),
        ("BROKEN (1)", 502, "bad_response"),
    ],
)
async def test_still_errors_keep_their_state(
    hass: HomeAssistant, server: FakeServer, hass_client, source, status, state
) -> None:
    await configure(hass, server)
    client = await hass_client()
    resp = await client.get(STILL, params={"source": source})
    assert resp.status == status
    assert resp.headers["X-Preview-State"] == state
    assert (await resp.json())["error"] == state
    assert resp.headers["Cache-Control"] == "no-store"


async def test_still_without_server_source_or_login(
    hass: HomeAssistant, server: FakeServer, hass_client, hass_client_no_auth
) -> None:
    await add_device(hass)
    client = await hass_client()
    resp = await client.get(STILL, params={"source": "CAM (1)"})
    assert resp.status == 404 and resp.headers["X-Preview-State"] == "not_configured"
    hass.data[DATA_HUB].async_set_preview_server(server.url)
    resp = await client.get(STILL)
    assert resp.status == 400 and resp.headers["X-Preview-State"] == "invalid"
    anonymous = await hass_client_no_auth()
    for path in (STILL, STREAM, STATUS):
        assert (await anonymous.get(path, params={"source": "CAM (1)"})).status == 401
    assert not [hit for hit in server.hits if hit[0] != "status"]


async def test_unreachable_server_is_reported(hass: HomeAssistant, hass_client, unused_tcp_port) -> None:
    await add_device(hass)
    hub = hass.data[DATA_HUB]
    hub.async_set_preview_server(f"http://127.0.0.1:{unused_tcp_port}")
    await hass.async_block_till_done(wait_background_tasks=True)
    client = await hass_client()
    for path in (STILL, STREAM, STATUS):
        resp = await client.get(path, params={"source": "CAM (1)"})
        assert resp.status == 502 and resp.headers["X-Preview-State"] == "unreachable"
    assert hub.snapshot()["preview"]["reachable"] is False


async def test_same_still_for_two_dashboards_asks_the_server_once(
    hass: HomeAssistant, server: FakeServer, hass_client
) -> None:
    await configure(hass, server)
    client = await hass_client()
    server.delay = 0.15
    server.hits.clear()
    params = {"source": "STUDIO-PC (Slides)", "w": "320"}
    first, second = await asyncio.gather(client.get(STILL, params=params), client.get(STILL, params=params))
    assert first.status == second.status == 200
    assert await first.read() == await second.read() == JPEG
    assert len([hit for hit in server.hits if hit[0] == "still"]) == 1


async def test_status_is_relayed(hass: HomeAssistant, server: FakeServer, hass_client) -> None:
    await configure(hass, server)
    client = await hass_client()
    resp = await client.get(STATUS, params={"source": "STUDIO-PC (Slides)"})
    data = await resp.json()
    assert resp.status == 200 and data["source"] == {"id": "STUDIO-PC (Slides)", "state": "ok"} and data["live"] == []


async def test_stream_through_a_signed_path_ends_when_the_viewer_leaves(
    hass: HomeAssistant, server: FakeServer, hass_client_no_auth
) -> None:
    """An <img> cannot send a token: the card signs the path. Closing the picture must free the server's receiver."""
    await configure(hass, server)
    client = await hass_client_no_auth()
    path = async_sign_path(hass, f"{STREAM}?source=STUDIO-PC+%28Slides%29&w=640&fps=12.5", timedelta(seconds=30))
    resp = await client.get(path)
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "multipart/x-mixed-replace; boundary=avmframe"
    assert server.hits[-1] == ("stream", {"source": "STUDIO-PC (Slides)", "w": "640", "fps": "12.5"})
    data = b""
    while data.count(JPEG) < 3:
        data += await asyncio.wait_for(resp.content.readany(), 5)
    assert b"--avmframe\r\nContent-Type: image/jpeg" in data
    assert not server.stream_closed.is_set()
    resp.close()  # the viewer closes the live preview
    await asyncio.wait_for(server.stream_closed.wait(), 5)

    # an error before the first picture comes back as the server's state, not as a broken stream
    path = async_sign_path(hass, f"{STREAM}?source=OFF+%281%29", timedelta(seconds=30))
    resp = await client.get(path)
    assert resp.status == 404 and resp.headers["X-Preview-State"] == "offline"


def test_translations_are_complete_and_without_urls() -> None:
    """hassfest refuses URLs in translations (the example address is a placeholder); all three files match."""
    import json
    import re

    base = ROOT / "custom_components/av_matrix"
    files = [base / "strings.json", base / "translations/en.json", base / "translations/de.json"]

    def keys(node: Any, prefix: str = "") -> set[str]:
        if not isinstance(node, dict):
            return {prefix}
        return set().union(*(keys(value, f"{prefix}.{key}") for key, value in node.items()))

    data = [json.loads(path.read_text()) for path in files]
    assert keys(data[0]) == keys(data[1]) == keys(data[2])
    for path in files:
        assert not re.search(r"(https?|ftp)://|www\.", path.read_text()), path.name
    for lang in data:
        for step in ("init", "network"):
            assert "{preview_example}" in lang["options"]["step"][step]["data_description"]["preview_server"]
