"""ST 2110 im Server: gemischte Presets, HTTP-/MCP-Wege, „ST 2110 prüfen“, Vergessen, Systemanzeige."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from avmatrix.drivers.base import Driver
from avmatrix.flows import FlowManager
from avmatrix.hub import Entry, Hub, MatrixError
from avmatrix.models import DestinationState, DestinationStatus, DeviceInfo, DevicePoll, SourceSighting
from avmatrix.store import JsonFile, TokenFile
from avmatrix.web import create_app
from nmos_sim import blackmagic
from nmos_sim.network import SimNetwork

MINI = "Blackmagic 2110 IP Mini IP to HDMI"
BIDI = "Blackmagic 2110 IP Mini BiDirect 12G"
QUAD = "Blackmagic 2110 IP Converter 4x12G PWR"
DECK = "DeckLink IP/SDI HD"
PRES = "Blackmagic 2110 IP Presentation Converter"
HDMI = f"nmos_{MINI}:HDMI Out"
INFO = {"hostname": "matrixpi", "port": 8088, "name": "Strelle AV Matrix", "mdns_name": "matrixpi.local", "lan_ip": None, "urls": []}


class Decoder(Driver):
    """Ein NDI-Decoder im Speicher, damit Presets über Protokolle hinweg geprüft werden können."""

    KEY, PROTOCOL, TITLE, MANUFACTURER, SETTLE_TIME = "magewell", "ndi", "Fake", "Magewell", 0.0

    def __init__(self, session, config, timeout=3.0):
        self.config, self.host, self.port, self.current = dict(config), config["host"], 80, "CAM (A)"

    async def async_get_info(self):
        return DeviceInfo(name="Monitor", serial=self.host)

    async def async_get_sources(self):
        return [SourceSighting("CAM (A)", "192.0.2.9:5961"), SourceSighting("CAM (B)", "192.0.2.9:5962")]

    async def async_get_current(self, destination):
        return self.current

    async def async_route(self, destination, source, address=None):
        self.current = source

    async def async_poll(self):
        return DevicePoll(await self.async_get_sources(), {"main": DestinationState(self.current, DestinationStatus(connected=True))})


async def settle(hub: Hub) -> None:
    for _ in range(3):
        await asyncio.gather(*(p.refresh() for p in hub.pollers.values()))
        await hub.evaluate()
        await asyncio.sleep(0)


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setattr("avmatrix.hub.FOLLOWUP_DELAYS", ())
    monkeypatch.setattr("avmatrix.drivers.nmos.VERIFY_DELAYS", (0.0,))
    net = SimNetwork(blackmagic.studio(), mdns=None)
    await net.start()
    config = JsonFile(tmp_path / "config.json")
    config.data = {
        "nmos_auto": False,
        "protected": [{"protocol": "st2110", "device": DECK, "reason": "Aufzeichnung läuft"}],
        "devices": [
            {"id": "nmos", "driver": "nmos", "title": "ST 2110", "data": {"host": "nmos"},
             "options": {"static_hosts": [f"127.0.0.1:{n.port}" for n in net.nodes]}},
            {"id": "magewell-m", "driver": "magewell", "title": "Monitor", "data": {"host": "192.0.2.20"}},
        ],
    }  # fmt: skip
    config.save_now()
    session = aiohttp.ClientSession()
    hub = Hub(config, JsonFile(tmp_path / "state.json"), session=session)
    hub._make_driver_real = hub._make_driver
    hub._make_driver = lambda entry: Decoder(None, entry.data) if entry.driver == "magewell" else hub._make_driver_real(entry)  # type: ignore[method-assign]
    hub.load()
    await hub.start()
    await settle(hub)
    token = TokenFile(tmp_path / "token")
    token.load_or_create()
    app = create_app(hub, token, FlowManager(hub, lambda: ""), lambda: INFO, lambda: {"localhost"})
    async with TestClient(TestServer(app)) as client:
        client.hub, client.net, client.token = hub, net, token
        yield client
    await hub.stop()
    await session.close()
    await net.stop()


async def test_snapshot_marks_st2110_as_picture_protocol_without_preview(env):
    snap = await (await env.get("/api/state")).json()
    st = snap["protocols"]["st2110"]
    assert (st["title"], st["video"], st["preview"], st["grouped"]) == ("ST 2110", True, False, True)
    assert snap["protocols"]["ndi"]["preview"] is True
    quad = [d for d in st["destinations"] if d["group"] == QUAD]
    assert [d["channel"] for d in quad] == ["SDI Out 1", "SDI Out 2", "SDI Out 3", "SDI Out 4"]  # Mehrkanalgerät: vier Ausgänge
    assert {d["icon_key"] for d in st["destinations"]} == {"st2110_multi", "st2110_converter", "st2110_presentation", "st2110_card"}
    source = next(s for s in st["sources"] if s["id"] == f"SDI In 4@{QUAD}")
    assert source["preview"] == "none" and "IP10" in source["format"] and source["essences"] == ["video", "audio", "data"]
    resp = await env.get("/api/preview.jpg", params={"source": source["id"]})
    assert resp.status == 404 and (await resp.json())["error"] == "no_preview"  # keine Vorschau ist kein Fehler der Quelle


async def test_route_undo_and_readable_rejection_over_http(env):
    resp = await env.get("/api/route", params={"dest": f"{MINI}:HDMI Out", "source": f"SDI In@{BIDI}"})
    assert resp.status == 200
    await settle(env.hub)
    dest = next(d for d in (await (await env.get("/api/state")).json())["protocols"]["st2110"]["destinations"] if d["id"] == HDMI)
    assert dest["status"] == "connected" and dest["layers"] == {k: f"SDI In@{BIDI}" for k in ("video", "audio", "data")}
    bad = await env.get("/api/route", params={"dest": f"{MINI}:HDMI Out", "source": "gibt es nicht@Nirgends"})
    assert bad.status == 502 and (await bad.json())["error"] == "route_failed"
    assert (await env.get("/api/undo", params={"dest": HDMI})).status == 200
    await settle(env.hub)
    assert (await (await env.get("/api/status")).json())["routes"][HDMI] is None


async def test_mixed_preset_across_ndi_and_st2110(env):
    hub = env.hub
    preset = hub.save_preset("Sendung", [{"destination": "Monitor", "source": "CAM (B)"}, {"destination": HDMI, "source": f"PC In@{PRES}"}])
    assert {r["protocol"] for r in preset["routes"]} == {"ndi", "st2110"} and not preset["active"]
    await hub.recall_preset("Sendung")
    await settle(hub)
    assert hub.presets_view()[0]["active"] is True
    await hub.undo_last()  # nimmt beide Protokolle gemeinsam zurück
    await settle(hub)
    status = hub.status()["routes"]
    assert status["magewell-m_main"] == "CAM (A)" and status[HDMI] is None


async def test_protection_list_applies_to_st2110(env):
    resp = await env.get("/api/route", params={"dest": f"{DECK}:Input 1", "source": f"SDI In@{BIDI}"})
    assert resp.status == 403 and (await resp.json())["error"] == "protected"
    with pytest.raises(MatrixError):
        env.hub.save_preset("x", [{"destination": f"nmos_{DECK}:Input 2", "source": None}])


async def test_mcp_lists_formats_and_says_no_preview(env):
    async def tool(name, args, key=None):
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
        return (await (await env.post("/mcp", json=body, headers=headers)).json())["result"]

    sources = (await tool("list_sources", {"protocol": "st2110"}))["structuredContent"]["sources"]
    assert len(sources) == 8 and all(s["preview"] == "none" and s["format"] for s in sources)
    assert (await tool("get_preview_url", {"source": f"SDI In@{BIDI}"}))["structuredContent"]["state"] == "no_preview"
    done = await tool("set_route", {"destination": f"{MINI}:HDMI Out", "source": f"SDI In@{BIDI}"}, env.token.token)
    assert done["isError"] is False
    await settle(env.hub)
    dests = (await tool("list_destinations", {"protocol": "st2110"}))["structuredContent"]["destinations"]
    assert next(d for d in dests if d["id"] == HDMI)["layers"]["video"] == f"SDI In@{BIDI}"


async def test_check_reads_without_switching_and_offers_raw_data(env):
    before = (await (await env.get("/api/status")).json())["routes"]
    result = await (await env.get("/api/nmos/check")).json()
    assert len(result["devices"]) == 5 and result["findings"][0]["level"] == "ok" and "nichts geschaltet" in result["note"]
    quad = next(d for d in result["devices"] if d["name"] == QUAD)
    assert quad["device_type"] == "multi" and len(quad["sources"]) == 4 and quad["ptp"]["locked"] is True
    raw = await env.get("/api/nmos/check", params={"raw": "1"})
    assert "attachment" in raw.headers["Content-Disposition"] and "senders" in (await raw.text())
    assert (await (await env.get("/api/status")).json())["routes"] == before


async def test_offline_device_is_shown_can_be_forgotten_and_system_lists_nodes(env):
    hub = env.hub
    system = await (await env.get("/api/system")).json()
    rows = {d["name"]: d for d in system["activity"]["devices"]}
    assert rows[MINI]["online"] is True and "PTP eingerastet" in rows[MINI]["detail"]
    assert (await env.post("/api/devices/nmos/forget", json={"device": MINI})).status == 400  # antwortet noch
    await next(n for n in env.net.nodes if n.spec.label == MINI).stop()
    for _ in range(4):
        await settle(hub)
    devices = (await (await env.get("/api/devices")).json())["devices"]
    mini = next(s for d in devices if d["driver"] == "nmos" for s in d["devices"] if s["name"] == MINI)
    assert mini["online"] is False and mini["device_type"] == "converter"
    assert (await env.post("/api/devices/nmos/forget", json={"device": MINI})).status == 200
    devices = (await (await env.get("/api/devices")).json())["devices"]
    assert all(s["name"] != MINI for d in devices if d["driver"] == "nmos" for s in d["devices"])
    assert HDMI not in hub.destinations
    # ein vergessenes Gerät nimmt auch seine Quellen mit – es bleibt nichts als "sendet nicht" stehen
    await next(n for n in env.net.nodes if n.spec.label == BIDI).stop()
    for _ in range(4):
        await settle(hub)
    assert (await env.post("/api/devices/nmos/forget", json={"device": BIDI})).status == 200
    sources = (await (await env.get("/api/state")).json())["protocols"]["st2110"]["sources"]
    assert all(not s["id"].endswith(f"@{BIDI}") for s in sources) and any(s["id"].endswith(f"@{QUAD}") for s in sources)


async def test_options_can_be_set_by_hand_for_another_vlan(env):
    resp = await env.patch("/api/devices/nmos", json={"static_hosts": "192.0.2.31, 192.0.2.32:8090", "registries": "http://192.0.2.5:8010", "audio_breakaway": True})
    assert resp.status == 200
    entry = env.hub.entries["nmos"]
    assert entry.options["static_hosts"] == ["192.0.2.31", "192.0.2.32:8090"] and entry.options["registries"] == ["http://192.0.2.5:8010"]
    assert entry.options["audio_breakaway"] is True and env.hub.pollers["nmos"].driver.audio_breakaway is True


async def test_no_devices_stays_quiet(tmp_path):
    """Noch keine NMOS-Geräte im Netz: Eintrag wird angelegt, das Protokoll bleibt unsichtbar, nichts warnt."""
    session = aiohttp.ClientSession()
    hub = Hub(JsonFile(tmp_path / "c.json"), JsonFile(tmp_path / "s.json"), session=session)
    hub.load()
    assert isinstance(hub.entries["nmos"], Entry) and hub.config.data["nmos_auto"] == "angelegt"
    await hub.start()
    await settle(hub)
    assert "st2110" not in hub.snapshot()["protocols"]
    await hub.remove_entry("nmos")
    hub.config.save_now()
    again = Hub(JsonFile(tmp_path / "c.json"), JsonFile(tmp_path / "s.json"), session=session)
    again.load()
    assert "nmos" not in again.entries  # wer ihn entfernt, bekommt ihn nicht wieder
    await hub.stop()
    await session.close()
