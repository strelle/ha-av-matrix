"""Ein simulierter NMOS-Node: IS-04 Node API (v1.0–v1.3) und IS-05 Connection API (v1.0/v1.1) über aiohttp.

Bewusst unabhängig vom Treiber geschrieben (keine gemeinsamen Hilfsfunktionen), nach den AMWA-Spezifikationen:
https://specs.amwa.tv/is-04/ · https://specs.amwa.tv/is-05/ · https://specs.amwa.tv/bcp-002-01/ ·
https://specs.amwa.tv/bcp-004-01/

``quirks`` schaltet Verhaltensweisen ein, die echte Geräte zeigen können (und die der Treiber aushalten muss):

=================  ==================================================================================
``no_grouphint``    keine BCP-002-01-Tags (Gruppierung muss aus Labels/Struktur kommen)
``sdp_required``    PATCH ohne ``transport_file`` wird mit 400 abgelehnt
``params_only``     PATCH mit ``transport_file`` wird mit 400 abgelehnt (nur ``transport_params``)
``stale_is04``      IS-04 ``subscription`` wird nach dem Schalten nicht aktualisiert
``senders_off``     Sender starten mit ``master_enable: false`` (laut Forum so bei Blackmagic)
``ignore``          PATCH wird mit 200 beantwortet, aber nie aktiv
``reject``          jeder PATCH an einen Empfänger → 500
``locked``          jeder PATCH → 423
``audio_reject``    PATCH an Audio-Empfänger → 400 (Bild ja, Ton nein: Rollback-Test)
``slow``            jede Antwort der Connection API kommt erst nach ``delay`` Sekunden
``no_manifest``     Sender ohne ``manifest_href`` (SDP nur über IS-05 ``/transportfile``)
``split_ports``     Connection API auf eigenem Port (``controls`` zeigt dorthin)
``web_ui``          ``GET /`` liefert eine HTML-Seite (Gerät mit Weboberfläche)
=================  ==================================================================================
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

NODE_VERSIONS = ["v1.0", "v1.1", "v1.2", "v1.3"]
CONNECTION_VERSIONS = ["v1.0", "v1.1"]
GROUPHINT = "urn:x-nmos:tag:grouphint/v1.0"
NAMESPACE = uuid.UUID("6f1b6b0e-3a52-4f0e-9d3c-2b5d1c7a9e10")
IP10 = "video/vnd.blackmagic-design.ip10"
UUID_LEN = 36


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "/".join(parts)))


def tai() -> str:
    now = time.time() + 37
    return f"{int(now)}:{int((now % 1) * 1e9)}"


@dataclass(slots=True)
class Video:
    width: int = 1920
    height: int = 1080
    rate: tuple[int, int] = (50, 1)
    interlaced: bool = False
    codec: str = "raw"  # raw | ip10

    @property
    def media_type(self) -> str:
        return IP10 if self.codec == "ip10" else "video/raw"


@dataclass(slots=True)
class Port:
    """Ein Ein- oder Ausgang des Geräts: Bild, dazu Ton und ANC als getrennte Ströme."""

    name: str  # "SDI In 1"
    direction: str  # "tx" (Sender) | "rx" (Empfänger)
    video: Video | None = field(default_factory=Video)
    audio_channels: int = 16  # 0 = kein Ton
    anc: bool = True
    #: Empfänger: höchstes Format und erlaubte Codecs
    max_height: int = 2160
    max_rate: int = 60
    codecs: tuple[str, ...] = ("raw", "ip10")
    max_audio_channels: int = 64
    #: Namen der Ströme (None = "<name> Video" / "<name> Audio" / "<name> ANC")
    labels: dict[str, str] | None = None


@dataclass(slots=True)
class Spec:
    label: str
    description: str = ""
    hostname: str = ""
    mac: str = "7c-2e-0d-00-00-01"
    ports: list[Port] = field(default_factory=list)
    quirks: set[str] = field(default_factory=set)
    delay: float = 0.0
    ptp_locked: bool = True
    gmid: str = "7c-2e-0d-ff-fe-00-00-01"
    tags: dict[str, list[str]] = field(default_factory=dict)


class MockNode:
    """Ein Node mit genau einem Device. ``start()`` öffnet die Ports, ``stop()`` schließt sie."""

    def __init__(self, spec: Spec, host: str = "127.0.0.1", port: int = 0) -> None:
        self.spec = spec
        self.host = host
        self.port = port
        self.connection_port = 0
        self.node_id = uid(spec.label, spec.mac, "node")
        self.device_id = uid(self.node_id, "device")
        self.version = tai()
        self.sources: dict[str, dict[str, Any]] = {}
        self.flows: dict[str, dict[str, Any]] = {}
        self.senders: dict[str, dict[str, Any]] = {}
        self.receivers: dict[str, dict[str, Any]] = {}
        #: IS-05-Zustand je Sender/Empfänger: {"staged": {...}, "active": {...}}
        self.conn: dict[str, dict[str, dict[str, Any]]] = {}
        self.sdp: dict[str, str] = {}
        self.patches: list[tuple[str, dict[str, Any]]] = []  # Protokoll aller PATCH-Aufrufe (für Tests)
        self.requests = 0
        self.down = False  # True: jede Anfrage bricht ab (Gerät "weg", Port bleibt belegt)
        self._runners: list[web.AppRunner] = []
        self._mcast = 0
        self._build()

    # ------------------------------------------------------------------ Aufbau
    def _mcast_addr(self) -> str:
        self._mcast += 1
        seed = uuid.UUID(self.node_id).int
        return f"239.255.{(seed >> 8) % 250 + 1}.{(seed + self._mcast) % 250 + 1}"

    def _tags(self, port: Port, role: str) -> dict[str, list[str]]:
        if "no_grouphint" in self.spec.quirks:
            return {}
        return {GROUPHINT: [f"{port.name}:{role}"]}

    def _label(self, port: Port, what: str) -> str:
        if port.labels and what in port.labels:
            return port.labels[what]
        return f"{port.name} {what}"

    def _build(self) -> None:
        for port in self.spec.ports:
            essences: list[tuple[str, str]] = []
            if port.video is not None:
                essences.append(("video", "Video"))
            if port.audio_channels:
                essences.append(("audio", "Audio"))
            if port.anc:
                essences.append(("data", "ANC"))
            for kind, word in essences:
                label = self._label(port, word)
                if port.direction == "tx":
                    self._add_sender(port, kind, label)
                else:
                    self._add_receiver(port, kind, label)

    def _add_sender(self, port: Port, kind: str, label: str) -> None:
        sid = uid(self.node_id, "sender", port.name, kind)
        source_id, flow_id = uid(sid, "source"), uid(sid, "flow")
        base = {"version": self.version, "description": label, "tags": {}}
        source: dict[str, Any] = {
            **base, "id": source_id, "label": label, "device_id": self.device_id, "parents": [], "clock_name": "clk0",
            "caps": {}, "format": f"urn:x-nmos:format:{kind}",
        }  # fmt: skip
        flow: dict[str, Any] = {
            **base, "id": flow_id, "label": label, "source_id": source_id, "device_id": self.device_id, "parents": [],
            "format": f"urn:x-nmos:format:{kind}",
        }  # fmt: skip
        mcast, ip = self._mcast_addr(), self.host
        ref = f"a=ts-refclk:ptp=IEEE1588-2008:{self.spec.gmid.upper()}:127\r\na=mediaclk:direct=0\r\n"
        head = f"v=0\r\no=- {int(uuid.UUID(sid).int % 10**9)} 1 IN IP4 {ip}\r\ns={port.name}\r\nt=0 0\r\n"
        if kind == "video":
            assert port.video is not None
            v = port.video
            grain = {"numerator": v.rate[0], "denominator": v.rate[1]}
            source["grain_rate"] = grain
            flow.update(
                {
                    "grain_rate": grain, "media_type": v.media_type, "frame_width": v.width, "frame_height": v.height,
                    "interlace_mode": "interlaced_tff" if v.interlaced else "progressive", "colorspace": "BT709",
                    "transfer_characteristic": "SDR",
                    "components": [
                        {"name": "Y", "width": v.width, "height": v.height, "bit_depth": 10},
                        {"name": "Cb", "width": v.width // 2, "height": v.height, "bit_depth": 10},
                        {"name": "Cr", "width": v.width // 2, "height": v.height, "bit_depth": 10},
                    ],
                }
            )  # fmt: skip
            rate = str(v.rate[0]) if v.rate[1] == 1 else f"{v.rate[0]}/{v.rate[1]}"
            common = f"sampling=YCbCr-4:2:2; width={v.width}; height={v.height}; exactframerate={rate}; depth=10; TCS=SDR; colorimetry=BT709; PM=2110GPM; TP=2110TPN; "
            if v.codec == "ip10":
                rtp = f"a=rtpmap:96 vnd.blackmagic-design.ip10/90000\r\na=fmtp:96 {common}SSN=ST2110-22:2022; scheme=10:8; \r\n"
            else:
                rtp = f"a=rtpmap:96 raw/90000\r\na=fmtp:96 {common}SSN=ST2110-20:2017; \r\n"
            body = f"m=video 16388 RTP/AVP 96\r\nc=IN IP4 {mcast}/64\r\na=source-filter: incl IN IP4 {mcast} {ip}\r\n{rtp}{ref}"
        elif kind == "audio":
            n = port.audio_channels
            source["channels"] = [{"label": f"Ch {i + 1}", "symbol": f"U{i + 1:02d}"} for i in range(n)]
            flow.update({"media_type": "audio/L24", "sample_rate": {"numerator": 48000, "denominator": 1}, "bit_depth": 24})
            body = (
                f"m=audio 16390 RTP/AVP 97\r\nc=IN IP4 {mcast}/64\r\na=source-filter: incl IN IP4 {mcast} {ip}\r\n"
                f"a=rtpmap:97 L24/48000/{n}\r\na=ptime:1\r\n{ref}"
            )
        else:
            flow.update({"media_type": "video/smpte291"})
            if port.video is not None:
                grain = {"numerator": port.video.rate[0], "denominator": port.video.rate[1]}
                source["grain_rate"] = flow["grain_rate"] = grain
            body = (
                f"m=video 16392 RTP/AVP 100\r\nc=IN IP4 {mcast}/64\r\na=source-filter: incl IN IP4 {mcast} {ip}\r\n"
                f"a=rtpmap:100 smpte291/90000\r\n{ref}"
            )
        self.sources[source_id], self.flows[flow_id] = source, flow
        self.sdp[sid] = head + body
        enabled = "senders_off" not in self.spec.quirks
        self.senders[sid] = {
            **base, "id": sid, "label": label, "flow_id": flow_id, "transport": "urn:x-nmos:transport:rtp.mcast",
            "device_id": self.device_id, "manifest_href": None, "interface_bindings": ["eth0"],
            "tags": self._tags(port, kind if kind != "data" else "anc"),
            "subscription": {"receiver_id": None, "active": enabled},
        }  # fmt: skip
        params = [
            {"source_ip": ip, "destination_ip": mcast, "source_port": 16388, "destination_port": 16388, "rtp_enabled": True}
        ]
        state = {"receiver_id": None, "master_enable": enabled, "activation": _no_activation(), "transport_params": params}
        self.conn[sid] = {"staged": json.loads(json.dumps(state)), "active": state}

    def _add_receiver(self, port: Port, kind: str, label: str) -> None:
        rid = uid(self.node_id, "receiver", port.name, kind)
        caps: dict[str, Any]
        if kind == "video":
            media = ["video/raw"] if "ip10" not in port.codecs else ["video/raw", IP10]
            rates = [{"numerator": r, "denominator": 1} for r in (25, 30, 50, 60) if r <= port.max_rate]
            rates += [{"numerator": r * 1000, "denominator": 1001} for r in (30, 60) if r <= port.max_rate]
            sets = [
                {
                    "urn:x-nmos:cap:format:frame_width": {"enum": [w]},
                    "urn:x-nmos:cap:format:frame_height": {"enum": [h]},
                    "urn:x-nmos:cap:format:grain_rate": {"enum": rates},
                    "urn:x-nmos:cap:format:color_sampling": {"enum": ["YCbCr-4:2:2"]},
                    "urn:x-nmos:cap:format:component_depth": {"enum": [10]},
                }
                for w, h in ((1280, 720), (1920, 1080), (3840, 2160))
                if h <= port.max_height
            ]
            caps = {"media_types": media, "constraint_sets": sets}
        elif kind == "audio":
            caps = {
                "media_types": ["audio/L24"],
                "constraint_sets": [
                    {
                        "urn:x-nmos:cap:format:channel_count": {"minimum": 1, "maximum": port.max_audio_channels},
                        "urn:x-nmos:cap:format:sample_rate": {"enum": [{"numerator": 48000}]},
                        "urn:x-nmos:cap:format:sample_depth": {"enum": [24]},
                    }
                ],
            }
        else:
            caps = {"media_types": ["video/smpte291"]}
        self.receivers[rid] = {
            "id": rid, "version": self.version, "label": label, "description": label,
            "format": f"urn:x-nmos:format:{kind}", "caps": caps, "transport": "urn:x-nmos:transport:rtp.mcast",
            "device_id": self.device_id, "interface_bindings": ["eth0"],
            "tags": self._tags(port, kind if kind != "data" else "anc"),
            "subscription": {"sender_id": None, "active": False},
        }  # fmt: skip
        params = [
            {"source_ip": None, "multicast_ip": None, "interface_ip": self.host, "destination_port": "auto", "rtp_enabled": True}
        ]
        state = {
            "sender_id": None, "master_enable": False, "activation": _no_activation(),
            "transport_file": {"data": None, "type": None}, "transport_params": params,
        }  # fmt: skip
        self.conn[rid] = {"staged": json.loads(json.dumps(state)), "active": state}

    # ---------------------------------------------------------------- Zustand
    def receiver(self, label: str) -> dict[str, Any]:
        return next(r for r in self.receivers.values() if r["label"] == label)

    def sender(self, label: str) -> dict[str, Any]:
        return next(s for s in self.senders.values() if s["label"] == label)

    def active(self, label: str) -> dict[str, Any]:
        item = next(i for i in [*self.receivers.values(), *self.senders.values()] if i["label"] == label)
        return self.conn[item["id"]]["active"]

    def connect(self, receiver_label: str, sender_id: str | None, sdp: str | None = None) -> None:
        """Verbindung von außen setzen (als hätte ein anderer Controller geschaltet)."""
        rid = self.receiver(receiver_label)["id"]
        enabled = sender_id is not None or sdp is not None
        self.conn[rid]["active"].update(
            {
                "sender_id": sender_id,
                "master_enable": enabled,
                "transport_file": {"data": sdp, "type": "application/sdp" if sdp else None},
            }
        )
        self.conn[rid]["staged"] = json.loads(json.dumps(self.conn[rid]["active"]))
        self._mirror(rid)

    def _mirror(self, item_id: str) -> None:
        """IS-05 → IS-04: ``subscription`` und Versionsstempel nachziehen."""
        if "stale_is04" in self.spec.quirks:
            return
        self.version = tai()
        active = self.conn[item_id]["active"]
        if item_id in self.receivers:
            self.receivers[item_id]["subscription"] = {"sender_id": active["sender_id"], "active": active["master_enable"]}
            self.receivers[item_id]["version"] = self.version
        else:
            self.senders[item_id]["subscription"] = {"receiver_id": active["receiver_id"], "active": active["master_enable"]}
            self.senders[item_id]["version"] = self.version

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def connection_url(self) -> str:
        return f"http://{self.host}:{self.connection_port}"

    # ----------------------------------------------------------------- Server
    async def start(self) -> None:
        split = "split_ports" in self.spec.quirks
        node_app = web.Application(middlewares=[self._middleware])
        self._node_routes(node_app)
        conn_app = web.Application(middlewares=[self._middleware]) if split else node_app
        self._connection_routes(conn_app)
        for app, attr in ((node_app, "port"), (conn_app, "connection_port")) if split else ((node_app, "port"),):
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, self.host, getattr(self, attr))
            await site.start()
            setattr(self, attr, site._server.sockets[0].getsockname()[1])  # type: ignore[union-attr]
            self._runners.append(runner)
        if not split:
            self.connection_port = self.port
        for sid, sender in self.senders.items():
            if "no_manifest" not in self.spec.quirks:
                sender["manifest_href"] = f"{self.connection_url}/x-nmos/connection/v1.1/single/senders/{sid}/transportfile"

    async def stop(self) -> None:
        for runner in self._runners:
            await runner.cleanup()
        self._runners.clear()

    @web.middleware
    async def _middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        self.requests += 1
        if self.down:
            if request.transport is not None:
                request.transport.close()
            raise web.HTTPServiceUnavailable
        if "slow" in self.spec.quirks and "/x-nmos/connection/" in request.path:
            await asyncio.sleep(self.spec.delay)
        try:
            return await handler(request)
        except web.HTTPException as err:
            if err.status >= 400 and err.content_type != "application/json":
                return _error(err.status, err.reason or "error")
            raise

    def _node_self(self) -> dict[str, Any]:
        spec = self.spec
        return {
            "id": self.node_id, "version": self.version, "label": spec.label, "description": spec.description,
            "tags": spec.tags, "href": f"{self.url}/", "hostname": spec.hostname or None,
            "api": {"versions": NODE_VERSIONS, "endpoints": [{"host": self.host, "port": self.port, "protocol": "http"}]},
            "caps": {}, "services": [],
            "clocks": [{"name": "clk0", "ref_type": "ptp", "traceable": False, "version": "IEEE1588-2008", "gmid": spec.gmid, "locked": spec.ptp_locked}],
            "interfaces": [{"name": "eth0", "chassis_id": spec.mac, "port_id": spec.mac}],
        }  # fmt: skip

    def _device(self) -> dict[str, Any]:
        controls = [
            {
                "href": f"{self.connection_url}/x-nmos/connection/{v}/",
                "type": f"urn:x-nmos:control:sr-ctrl/{v}",
                "authorization": False,
            }
            for v in CONNECTION_VERSIONS
        ]
        return {
            "id": self.device_id, "version": self.version, "label": self.spec.label, "description": self.spec.description,
            "tags": {}, "type": "urn:x-nmos:device:generic", "node_id": self.node_id,
            "senders": list(self.senders), "receivers": list(self.receivers), "controls": controls,
        }  # fmt: skip

    def _node_routes(self, app: web.Application) -> None:
        r = app.router
        r.add_get("/", self._root)
        r.add_get("/x-nmos", _static(["node/", "connection/"]))
        r.add_get("/x-nmos/", _static(["node/", "connection/"]))
        r.add_get("/x-nmos/node", _static([f"{v}/" for v in NODE_VERSIONS]))
        r.add_get("/x-nmos/node/", _static([f"{v}/" for v in NODE_VERSIONS]))
        r.add_get("/x-nmos/node/{ver}/", self._node_base)
        r.add_get("/x-nmos/node/{ver}/{what}", self._node_list)
        r.add_get("/x-nmos/node/{ver}/{what}/", self._node_list)
        r.add_get("/x-nmos/node/{ver}/{what}/{id}", self._node_item)

    async def _root(self, request: web.Request) -> web.Response:
        if "web_ui" in self.spec.quirks:
            return web.Response(
                text=f"<html><head><title>{self.spec.label}</title></head><body>Setup</body></html>", content_type="text/html"
            )
        return web.json_response(["x-nmos/"])

    def _check_node_ver(self, request: web.Request) -> None:
        if request.match_info["ver"] not in NODE_VERSIONS:
            raise web.HTTPNotFound

    async def _node_base(self, request: web.Request) -> web.Response:
        self._check_node_ver(request)
        return web.json_response(["self/", "sources/", "flows/", "devices/", "senders/", "receivers/"])

    def _collection(self, what: str) -> dict[str, dict[str, Any]] | None:
        return {
            "devices": {self.device_id: self._device()}, "sources": self.sources, "flows": self.flows,
            "senders": self.senders, "receivers": self.receivers,
        }.get(what)  # fmt: skip

    async def _node_list(self, request: web.Request) -> web.Response:
        self._check_node_ver(request)
        what = request.match_info["what"]
        if what == "self":
            return web.json_response(self._node_self())
        items = self._collection(what)
        if items is None:
            raise web.HTTPNotFound
        return web.json_response(list(items.values()))

    async def _node_item(self, request: web.Request) -> web.Response:
        self._check_node_ver(request)
        items = self._collection(request.match_info["what"]) or {}
        item = items.get(request.match_info["id"])
        if item is None:
            raise web.HTTPNotFound
        return web.json_response(item)

    # --------------------------------------------------------- Connection API
    def _connection_routes(self, app: web.Application) -> None:
        r = app.router
        base = "/x-nmos/connection"
        r.add_get(f"{base}/", _static([f"{v}/" for v in CONNECTION_VERSIONS]))
        r.add_get(f"{base}/{{ver}}/", _static(["bulk/", "single/"]))
        r.add_get(f"{base}/{{ver}}/single/", _static(["senders/", "receivers/"]))
        r.add_get(f"{base}/{{ver}}/single/{{kind}}/", self._conn_list)
        r.add_get(f"{base}/{{ver}}/single/{{kind}}/{{id}}/", self._conn_item)
        r.add_get(f"{base}/{{ver}}/single/{{kind}}/{{id}}/{{what}}", self._conn_get)
        r.add_get(f"{base}/{{ver}}/single/{{kind}}/{{id}}/{{what}}/", self._conn_get)
        r.add_patch(f"{base}/{{ver}}/single/{{kind}}/{{id}}/staged", self._conn_patch)
        r.add_patch(f"{base}/{{ver}}/single/{{kind}}/{{id}}/staged/", self._conn_patch)

    def _conn_items(self, request: web.Request) -> dict[str, dict[str, Any]]:
        if request.match_info["ver"] not in CONNECTION_VERSIONS:
            raise web.HTTPNotFound
        kind = request.match_info["kind"]
        if kind not in ("senders", "receivers"):
            raise web.HTTPNotFound
        return self.senders if kind == "senders" else self.receivers

    async def _conn_list(self, request: web.Request) -> web.Response:
        return web.json_response([f"{i}/" for i in self._conn_items(request)])

    async def _conn_item(self, request: web.Request) -> web.Response:
        items = self._conn_items(request)
        if request.match_info["id"] not in items:
            raise web.HTTPNotFound
        sender = request.match_info["kind"] == "senders"
        return web.json_response(
            ["constraints/", "staged/", "active/", "transporttype/"] + (["transportfile/"] if sender else [])
        )

    async def _conn_get(self, request: web.Request) -> web.Response:
        items = self._conn_items(request)
        item_id, what = request.match_info["id"], request.match_info["what"]
        if item_id not in items:
            raise web.HTTPNotFound
        if what in ("staged", "active"):
            return web.json_response(self.conn[item_id][what])
        if what == "constraints":
            keys = ("source_ip", "destination_ip", "source_port", "destination_port", "rtp_enabled")
            if item_id in self.receivers:
                keys = ("source_ip", "multicast_ip", "interface_ip", "destination_port", "rtp_enabled")
            return web.json_response([{key: {} for key in keys}])
        if what == "transporttype":
            return web.json_response("urn:x-nmos:transport:rtp.mcast")
        if what == "transportfile" and item_id in self.senders:
            return web.Response(text=self.sdp[item_id], content_type="application/sdp")
        raise web.HTTPNotFound

    async def _conn_patch(self, request: web.Request) -> web.Response:
        items = self._conn_items(request)
        item_id = request.match_info["id"]
        if item_id not in items:
            raise web.HTTPNotFound
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "request body is not JSON")
        if not isinstance(body, dict):
            return _error(400, "request body must be an object")
        self.patches.append((items[item_id]["label"], body))
        quirks = self.spec.quirks
        is_receiver = item_id in self.receivers
        if "locked" in quirks:
            return _error(423, "resource is locked by a pending activation")
        if is_receiver and "reject" in quirks:
            return _error(500, "internal error")
        if is_receiver and "audio_reject" in quirks and items[item_id]["format"].endswith(":audio") and body.get("master_enable"):
            return _error(400, "audio receiver is not available")
        allowed = (
            {"sender_id", "master_enable", "activation", "transport_file", "transport_params"}
            if is_receiver
            else {"receiver_id", "master_enable", "activation", "transport_params"}
        )
        unknown = set(body) - allowed
        if unknown:
            return _error(400, f"unknown properties: {', '.join(sorted(unknown))}")
        staged = self.conn[item_id]["staged"]
        if is_receiver:
            problem = self._stage_receiver(items[item_id], staged, body)
            if problem:
                return _error(400, problem)
        else:
            if "receiver_id" in body:
                staged["receiver_id"] = body["receiver_id"]
            if isinstance(body.get("transport_params"), list):
                for leg, new in zip(staged["transport_params"], body["transport_params"], strict=False):
                    leg.update(new)
        if "master_enable" in body:
            if not isinstance(body["master_enable"], bool):
                return _error(400, "master_enable must be boolean")
            staged["master_enable"] = body["master_enable"]
        activation = body.get("activation") or {}
        mode = activation.get("mode") if isinstance(activation, dict) else None
        if mode is None:
            return web.json_response(staged)
        if mode != "activate_immediate":
            return _error(400, f"activation mode {mode} is not supported")
        answer = json.loads(json.dumps(staged))
        answer["activation"] = {"mode": "activate_immediate", "requested_time": None, "activation_time": tai()}
        if "ignore" not in quirks:
            active = json.loads(json.dumps(staged))
            active["activation"] = dict(answer["activation"])
            if is_receiver and not active["master_enable"]:
                pass  # ausgeschaltet: Parameter bleiben stehen, es wird nur nicht empfangen
            self.conn[item_id]["active"] = active
            self._mirror(item_id)
        staged["activation"] = _no_activation()
        return web.json_response(answer)

    def _stage_receiver(self, receiver: dict[str, Any], staged: dict[str, Any], body: dict[str, Any]) -> str | None:
        quirks = self.spec.quirks
        if "sender_id" in body:
            sender_id = body["sender_id"]
            if sender_id is not None and not (isinstance(sender_id, str) and len(sender_id) == UUID_LEN):
                return "sender_id must be a UUID or null"
            staged["sender_id"] = sender_id
        tfile = body.get("transport_file")
        if tfile is not None:
            if not isinstance(tfile, dict) or set(tfile) - {"data", "type"}:
                return "transport_file must be an object {data, type}"
            data = tfile.get("data")
            if data is not None:
                if "params_only" in quirks:
                    return "transport_file is not supported, use transport_params"
                if not isinstance(data, str) or not data.startswith("v=0"):
                    return "transport_file is not a valid SDP"
                problem = self._check_sdp(receiver, data)
                if problem:
                    return problem
                parsed = _sdp_target(data)
                staged["transport_params"][0].update(
                    {"multicast_ip": parsed[0], "destination_port": parsed[1], "source_ip": parsed[2], "rtp_enabled": True}
                )
            staged["transport_file"] = {"data": data, "type": tfile.get("type")}
        if isinstance(body.get("transport_params"), list):
            if len(body["transport_params"]) != len(staged["transport_params"]):
                return "transport_params must have one entry per leg"
            for leg, new in zip(staged["transport_params"], body["transport_params"], strict=True):
                if not isinstance(new, dict) or set(new) - {
                    "source_ip",
                    "multicast_ip",
                    "interface_ip",
                    "destination_port",
                    "rtp_enabled",
                }:
                    return "unknown transport parameter"
                leg.update(new)
        enabling = body.get("master_enable") is True
        if enabling and "sdp_required" in quirks and not (tfile and tfile.get("data")):
            return "a transport_file (SDP) is required to connect this receiver"
        if enabling and not (tfile and tfile.get("data")) and not body.get("transport_params") and "sdp_required" not in quirks:
            # nur die sender_id: ein echter Empfänger könnte den Sender im Peer-to-Peer-Betrieb selbst auflösen;
            # die Simulation tut so, als gelänge das
            pass
        return None

    @staticmethod
    def _check_sdp(receiver: dict[str, Any], sdp: str) -> str | None:
        media = encoding = None
        for line in sdp.replace("\r", "").split("\n"):
            if line.startswith("m=") and media is None:
                media = line[2:].split()[0]
            if line.startswith("a=rtpmap:") and encoding is None:
                encoding = line.split()[-1].split("/")[0]
        offered = f"{media}/{encoding}"
        wanted = receiver["caps"].get("media_types") or []
        if wanted and offered not in wanted:
            return f"unsupported media type {offered}"
        return None


def _sdp_target(sdp: str) -> tuple[str | None, int | None, str | None]:
    mcast = port = source = None
    for line in sdp.replace("\r", "").split("\n"):
        if line.startswith("m=") and port is None:
            port = int(line.split()[1])
        elif line.startswith("c=") and mcast is None:
            mcast = line.split()[-1].split("/")[0]
        elif line.startswith("a=source-filter:"):
            source = line.split()[-1]
    return mcast, port, source


def _static(payload: Any) -> Any:
    async def handler(_: web.Request) -> web.Response:
        return web.json_response(payload)

    return handler


def _no_activation() -> dict[str, Any]:
    return {"mode": None, "requested_time": None, "activation_time": None}


def _error(code: int, message: str) -> web.Response:
    return web.json_response({"code": code, "error": message, "debug": None}, status=code)
