"""HTTP-Schnittstelle, Schutz gegen Fremdseiten, MCP (Streamable HTTP) mit und ohne Zugangsschlüssel."""

from __future__ import annotations

import json
import os

import pytest
from aiohttp.test_utils import TestClient, TestServer

from avmatrix.flows import FlowManager
from avmatrix.web import create_app

from .conftest import AVIO, DA, WING

S2 = "magewell-s2_main"
INFO = {
    "hostname": "matrixpi", "port": 8088, "name": "Strelle AV Matrix", "mdns_name": "matrixpi.local",
    "lan_ip": "192.0.2.8", "tailscale_ip": "100.64.0.8", "tailscale_name": "matrixpi.example.ts.net",
    "urls": [{"kind": "mdns_name", "label": "Studionetz (Name)", "host": "matrixpi.local", "url": "http://matrixpi.local:8088/"}],
}  # fmt: skip


@pytest.fixture
async def client(env):
    env.token.load_or_create()
    app = create_app(env.hub, env.token, FlowManager(env.hub, lambda: "192.0.2.0/24"), lambda: INFO, lambda: {"matrixpi.local", "localhost"})
    async with TestClient(TestServer(app)) as c:
        c.env = env
        yield c


async def rpc(client, method, params=None, *, token=None, msg_id=1):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if msg_id is not None:
        body["id"] = msg_id
    return await client.post("/mcp", json=body, headers=headers)


async def tool(client, name, args=None, *, token=None):
    resp = await rpc(client, "tools/call", {"name": name, "arguments": args or {}}, token=token)
    assert resp.status == 200
    return (await resp.json())["result"]


# ------------------------------------------------------------------ HTTP
async def test_state_status_and_docs(client):
    state = await (await client.get("/api/state")).json()
    assert set(state["protocols"]) == {"ndi", "dante"} and state["presets"] == []
    status = await (await client.get("/api/status")).json()
    assert status["routes"][S2] == "CAM (A)"
    spec = await (await client.get("/openapi.json")).json()
    assert spec["openapi"].startswith("3.1") and "/api/route" in spec["paths"]
    llms = await (await client.get("/llms.txt")).text()
    assert "http://matrixpi.local:8088/mcp" in llms and "protected" in llms
    page = await (await client.get("/")).text()
    assert "av-matrix-card.js" in page and "LLM-Verbindung" in page
    assert (await client.get("/static/av-matrix-card.js")).status == 200
    assert (await client.get("/static/../hub.py")).status in (403, 404)


async def test_route_by_get_and_post_then_undo(client):
    resp = await client.get("/api/route", params={"dest": "Monitor-1", "source": "CAM (B)"})
    assert resp.status == 200 and (await resp.json())["previous_source"] == "CAM (A)"
    resp = await client.post("/api/route", json={"destination": S2, "source": None})
    assert resp.status == 200 and client.env.decoders["magewell-s2"].current is None
    assert (await (await client.post("/api/undo", params={"dest": "Monitor-1"})).json())["restored"][0]["source"] == "CAM (B)"
    assert (await client.get("/api/undo")).status == 200  # letzte Aktion
    assert client.env.decoders["magewell-s2"].current == "CAM (A)"
    assert (await client.get("/api/undo")).status == 409
    resp = await client.get("/api/route", params={"dest": "nix", "source": "x"})
    assert resp.status == 404 and (await resp.json())["error"] == "unknown_destination"


async def test_protected_destination_is_refused_over_http(client):
    for kwargs in (
        {"params": {"dest": f"{AVIO}:1", "source": f"CH1@{DA}"}},
        {"params": {"dest": f"dante_{AVIO}:2", "source": ""}},
    ):
        resp = await client.get("/api/route", **kwargs)
        assert resp.status == 403 and (await resp.json())["error"] == "protected"
    assert (await client.post("/api/unlock", params={"dest": f"{AVIO}:1"})).status == 403
    assert (await client.post("/api/salvo", json={"routes": [{"destination": f"{AVIO}:1", "source": None}]})).status == 403
    resp = await client.post("/api/presets", json={"name": "x", "routes": [{"destination": f"{AVIO}:1", "source": None}]})
    assert resp.status == 403
    assert (await client.post("/api/presets", json={"name": "x", "destinations": [f"{WING}:61"]})).status == 403


async def test_presets_over_http(client):
    resp = await client.post("/api/presets", json={"name": "Regie", "routes": [{"destination": "Monitor-1", "source": "CAM (B)"}]})
    assert resp.status == 200 and (await resp.json())["preset"]["id"] == "regie"
    assert (await client.get("/api/preset/recall", params={"preset": "Regie"})).status == 200
    presets = (await (await client.get("/api/presets")).json())["presets"]
    assert presets[0]["active"] is True
    assert (await client.put("/api/presets/regie", json={"name": "Regie 2"})).status == 200
    assert (await client.post("/api/presets/regie/recall")).status == 200
    assert (await client.delete("/api/presets/regie")).status == 200
    assert (await client.get("/api/preset/recall", params={"preset": "Regie 2"})).status == 404


async def test_lock_over_http(client):
    assert (await client.post("/api/lock", params={"dest": "Monitor-1"})).status == 200
    assert (await client.get("/api/route", params={"dest": "Monitor-1", "source": "CAM (B)"})).status == 423
    assert (await client.post("/api/unlock", params={"dest": "Monitor-1"})).status == 200


async def test_foreign_pages_cannot_switch(client):
    params = {"dest": "Monitor-1", "source": "CAM (B)"}
    assert (await client.get("/api/route", params=params, headers={"Origin": "http://evil.example"})).status == 403
    assert (await client.get("/api/route", params=params, headers={"Sec-Fetch-Site": "cross-site"})).status == 403
    assert (await client.get("/api/state", headers={"Host": "evil.example"})).status == 403  # DNS-Rebinding
    assert (await client.get("/api/state", headers={"Host": "matrixpi.local:8088"})).status == 200
    assert (await client.get("/api/state", headers={"Host": "192.0.2.8:8088"})).status == 200
    assert client.env.decoders["magewell-s2"].routes == []


async def test_token_file_and_endpoints(client):
    env = client.env
    path = env.token.path
    assert oct(os.stat(path).st_mode & 0o777) == "0o600" and len(env.token.token) > 40
    assert (await client.get("/api/token")).status == 400  # ohne Panel-Header
    shown = (await (await client.get("/api/token", headers={"X-AVM-Panel": "1"})).json())["token"]
    assert shown == env.token.token
    new = (await (await client.post("/api/token/rotate", headers={"X-AVM-Panel": "1"})).json())["token"]
    assert new != shown and path.read_text().strip() == new and oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert (await rpc(client, "tools/list", token=shown)).status == 401  # alter Schlüssel gilt nicht mehr


async def test_websocket_speaks_the_card_protocol(client):
    ws = await client.ws_connect("/ws")
    await ws.send_json({"id": 1, "type": "av_matrix/subscribe"})
    assert (await ws.receive_json())["success"] is True
    event = await ws.receive_json(timeout=3)
    assert event["type"] == "event" and "ndi" in event["event"]["protocols"]
    await ws.send_json({"id": 2, "type": "call_service", "domain": "av_matrix", "service": "route",
                        "service_data": {"destination": [S2], "source": "CAM (B)"}})  # fmt: skip
    seen = {}
    while 2 not in seen:
        msg = await ws.receive_json(timeout=3)
        seen[msg["id"]] = msg
    assert seen[2]["success"] is True and client.env.decoders["magewell-s2"].current == "CAM (B)"
    await ws.send_json({"id": 3, "type": "call_service", "domain": "av_matrix", "service": "unlock",
                        "service_data": {"destination": [f"dante_{AVIO}:1"]}})  # fmt: skip
    while 3 not in seen:
        msg = await ws.receive_json(timeout=3)
        seen[msg["id"]] = msg
    assert seen[3]["success"] is False and seen[3]["error"]["code"] == "protected"
    await ws.close()


async def test_add_device_flow_like_home_assistant(client):
    flow = await (await client.post("/api/ha/config/config_entries/flow", json={"handler": "av_matrix"})).json()
    assert flow["type"] == "menu" and flow["menu_options"] == ["scan", "manual"]
    url = f"/api/ha/config/config_entries/flow/{flow['flow_id']}"
    step = await (await client.post(url, json={"next_step_id": "manual"})).json()
    assert step["step_id"] == "manual" and {o["value"] for o in step["data_schema"][0]["selector"]["select"]["options"]} == {"dante", "magewell", "birddog"}
    step = await (await client.post(url, json={"driver": "dante"})).json()
    assert step == {"type": "abort", "flow_id": flow["flow_id"], "handler": "av_matrix", "reason": "already_configured"}
    assert (await client.get(url)).status == 400


# ------------------------------------------------------------------- MCP
async def test_mcp_initialize_and_tools_list(client):
    resp = await rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    result = (await resp.json())["result"]
    assert result["protocolVersion"] == "2025-06-18" and result["serverInfo"]["name"] == "av-matrix" and "tools" in result["capabilities"]
    assert (await rpc(client, "notifications/initialized", msg_id=None)).status == 202
    tools = (await (await rpc(client, "tools/list")).json())["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"list_devices", "list_sources", "list_destinations", "get_routing", "list_presets", "get_preview_url", "get_system_status",
                     "set_route", "recall_preset", "save_preset", "delete_preset", "undo"}  # fmt: skip
    assert all(t["inputSchema"]["type"] == "object" for t in tools)
    assert (await client.get("/mcp")).status == 405
    assert (await (await rpc(client, "gibt/es/nicht")).json())["error"]["code"] == -32601
    assert (await rpc(client, "tools/list", headers=None) if False else await client.post("/mcp", data="kaputt")).status == 400


async def test_mcp_reads_without_key(client):
    routing = (await tool(client, "get_routing", {"protocol": "ndi"}))["structuredContent"]["routing"]
    assert routing[0] == {"destination": S2, "destination_name": "Monitor-1", "protocol": "ndi", "source": "CAM (A)", "status": "connected"}
    dests = (await tool(client, "list_destinations", {"protocol": "dante"}))["structuredContent"]["destinations"]
    assert next(d for d in dests if d["id"] == f"dante_{AVIO}:1")["protected"]
    sources = json.loads((await tool(client, "list_sources", {"live_only": True}))["content"][0]["text"])["sources"]
    assert {"id": "CAM (A)", "name": "CAM (A)", "protocol": "ndi", "live": True, "host": "192.0.2.9"} in sources
    assert (await tool(client, "list_devices"))["isError"] is False
    assert (await tool(client, "list_presets"))["structuredContent"] == {"presets": []}


async def test_mcp_writes_need_the_key(client):
    env = client.env
    args = {"destination": "Monitor-1", "source": "CAM (B)"}
    denied = await tool(client, "set_route", args)
    assert denied["isError"] is True and "Zugangsschlüssel" in denied["content"][0]["text"]
    for name, a in (("recall_preset", {"preset": "x"}), ("save_preset", {"name": "x", "destinations": ["Monitor-1"]}),
                    ("delete_preset", {"preset": "x"}), ("undo", {})):  # fmt: skip
        assert (await tool(client, name, a))["isError"] is True
    assert env.decoders["magewell-s2"].routes == [] and env.hub.presets == {}
    assert (await rpc(client, "tools/call", {"name": "set_route", "arguments": args}, token="falsch")).status == 401
    assert env.decoders["magewell-s2"].routes == []

    key = env.token.token
    ok = await tool(client, "set_route", args, token=key)
    assert ok["isError"] is False and ok["structuredContent"]["previous_source"] == "CAM (A)"
    assert env.decoders["magewell-s2"].current == "CAM (B)"
    saved = await tool(client, "save_preset", {"name": "Jetzt", "destinations": ["Monitor-1"]}, token=key)
    assert saved["structuredContent"]["preset"]["active"] is True
    assert (await tool(client, "undo", {}, token=key))["structuredContent"]["restored"] == [{"destination": S2, "source": "CAM (A)"}]
    assert (await tool(client, "recall_preset", {"preset": "Jetzt"}, token=key))["isError"] is False
    assert env.decoders["magewell-s2"].current == "CAM (B)"
    assert (await tool(client, "delete_preset", {"preset": "jetzt"}, token=key))["isError"] is False


async def test_mcp_cannot_touch_protected_destinations_even_with_key(client):
    key = client.env.token.token
    for args in ({"destination": f"{AVIO}:1", "source": f"CH1@{DA}"}, {"destination": f"dante_{AVIO}:2", "source": None},
                 {"destination": f"{WING}:62", "source": None}):  # fmt: skip
        result = await tool(client, "set_route", args, token=key)
        assert result["isError"] is True and "fest gesperrt" in result["content"][0]["text"] and result["_meta"]["code"] == "protected"
    result = await tool(client, "save_preset", {"name": "x", "routes": [{"destination": f"{AVIO}:1", "source": None}]}, token=key)
    assert result["isError"] is True and client.env.hub.presets == {}
    avio = client.env.network[AVIO]
    assert [(c.tx_channel, c.tx_device) for c in avio.rx] == [("61", "Example-WING-Fullsize"), ("62", "Example-WING-Fullsize")]


# ------------------------------------------ Vorschau, QR, Testbild, System
async def test_preview_reports_state_instead_of_pictures_without_sdk(client):
    status = await (await client.get("/api/preview")).json()
    assert status["available"] is False and status["receivers_open"] == 0
    for path in ("/api/preview.jpg", "/api/preview.mjpeg"):
        resp = await client.get(path, params={"source": "CAM (A)"})
        assert resp.status == 501 and resp.headers["X-Preview-State"] == "unavailable"
        assert (await resp.json())["error"] == "unavailable"
    assert (await client.get("/api/preview.jpg")).status == 400
    # Bilder dürfen von anderen Oberflächen im Studionetz eingebettet werden, Schaltbefehle nicht
    assert (await client.get("/api/preview.jpg", params={"source": "CAM (A)"}, headers={"Sec-Fetch-Site": "cross-site"})).status == 501
    url = (await tool(client, "get_preview_url", {"source": "cam (a)"}))["structuredContent"]
    assert url["state"] == "unavailable" and url["urls"][0]["jpeg"] == "http://matrixpi.local:8088/api/preview.jpg?source=CAM%20%28A%29"


async def test_qr_code_points_to_an_address_a_phone_can_reach(client):
    info = await (await client.get("/api/info")).json()
    assert [c["kind"] for c in info["connect"]] == ["lan_ip", "tailscale_name", "tailscale_ip", "mdns_name"]
    resp = await client.get("/api/qr.svg")
    assert resp.status == 200 and resp.content_type == "image/svg+xml" and resp.headers["X-QR-Url"] == "http://192.0.2.8:8088/"
    assert (await resp.text()).startswith("<svg")
    assert (await client.get("/api/qr.svg", params={"target": "tailscale_name"})).headers["X-QR-Url"] == "http://matrixpi.example.ts.net:8088/"
    assert (await client.get("/api/qr.svg", params={"target": "gibtsnicht"})).status == 400


async def test_testpattern_switch_survives_restart_and_draws_the_qr(client):
    state = await (await client.get("/api/testpattern")).json()
    assert state["enabled"] is False and state["running"] is False and state["url"] == "http://192.0.2.8:8088/"
    on = await (await client.post("/api/testpattern", json={"enabled": True})).json()
    assert on["enabled"] is True and on["running"] is False and on["available"] is False  # ohne SDK wird nicht gesendet
    assert client.env.hub.state.data["testpattern"] == {"enabled": True}  # steht im Zustand → übersteht den Neustart
    picture = await client.get("/api/testpattern.jpg")
    assert picture.status == 200 and picture.content_type == "image/jpeg"
    cv2 = pytest.importorskip("cv2")
    import numpy

    image = cv2.imdecode(numpy.frombuffer(await picture.read(), numpy.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (720, 1280) and cv2.QRCodeDetector().detectAndDecode(image)[0] == "http://192.0.2.8:8088/"
    assert (await (await client.post("/api/testpattern", json={"enabled": False})).json())["enabled"] is False


async def test_system_status_has_no_secrets(client):
    client.env.hub.entries["magewell-s2"].data["password"] = "geheim"
    await client.get("/api/route", params={"dest": "Monitor-1", "source": "CAM (B)"})
    data = await (await client.get("/api/system")).json()
    assert {"host", "processes", "activity", "warnings", "history", "monitor"} <= set(data)
    assert set(data["processes"]) == {"matrix", "companion"} and data["processes"]["matrix"]["rss_mb"] >= 0  # echte Werte nur unter Linux (/proc)
    assert data["activity"]["routes"][0]["origin"] == "http" and data["activity"]["clients"]["panels"] == 0
    assert {d["name"] for d in data["activity"]["devices"]} == {"Dante®-Netzwerk", "Monitor-1", "TV"}
    text = json.dumps(data)
    assert "geheim" not in text and client.env.token.token not in text and "/home/" not in text and "/Users/" not in text
    short = await (await client.get("/api/system", params={"summary": "1"})).json()
    assert set(short) == {"ok", "cpu_percent", "memory_percent", "temperature_c", "warnings"}
    assert (await tool(client, "get_system_status"))["isError"] is False
