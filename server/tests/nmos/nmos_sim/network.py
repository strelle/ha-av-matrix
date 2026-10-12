"""Mehrere Mock-Nodes starten, per mDNS ankündigen, optional eine Registry (IS-04 Query- und Registration-API) dazu.

Betriebsarten wie im echten Netz:

* Peer-to-Peer (Vorgabe): jeder Node kündigt sich per mDNS an, mit Änderungszählern ``ver_*``.
* mit Registry (``registry=True``): zusätzlich listet die Registry alle Nodes; sie kündigt ``_nmos-query._tcp`` und
  ``_nmos-register._tcp`` an. ``registered=True``: die Nodes verhalten sich wie angemeldete Nodes (IS-04: dann
  ohne ``ver_*``-Zähler). ``p2p=False``: die Nodes kündigen sich gar nicht an – nur die Registry kennt sie
  (anderes Netz/VLAN).

mDNS läuft **nur auf der Loopback-Schnittstelle**, solange nicht ausdrücklich eine andere Adresse verlangt wird:
Die Phantomgeräte dürfen im Studionetz nicht auftauchen (dort läuft die echte Kreuzschiene).
"""

from __future__ import annotations

import socket
from typing import Any

from aiohttp import web
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from .node import NODE_VERSIONS, MockNode, Spec

NODE_TYPE = "_nmos-node._tcp.local."
QUERY_TYPE = "_nmos-query._tcp.local."
REGISTER_TYPE = "_nmos-register._tcp.local."
LOOPBACK = "127.0.0.1"
RESOURCES = ("nodes", "devices", "sources", "flows", "senders", "receivers")


class Registry:
    """Kleine Registry: Query API (alle sechs Listen, immer der aktuelle Stand der Nodes) und der Rahmen der
    Registration API (nimmt Anmeldungen und Lebenszeichen an). ``down = True``: antwortet nicht mehr."""

    def __init__(self, nodes: list[MockNode], host: str = LOOPBACK, port: int = 0) -> None:
        self.nodes = nodes
        self.host = host
        self.port = port
        self.requests = 0  # Abrufe der Node-Liste
        self.registered: list[dict[str, Any]] = []  # was per Registration API ankam
        self.down = False
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application(middlewares=[self._middleware])
        r = app.router
        r.add_get("/x-nmos/query/", self._versions)
        r.add_get("/x-nmos/query/{ver}/", self._base)
        r.add_get("/x-nmos/query/{ver}/{what}", self._list)
        r.add_get("/x-nmos/query/{ver}/{what}/{id}", self._item)
        r.add_get("/x-nmos/registration/", self._versions)
        r.add_get("/x-nmos/registration/{ver}/", self._registration_base)
        r.add_post("/x-nmos/registration/{ver}/resource", self._register)
        r.add_post("/x-nmos/registration/{ver}/health/nodes/{id}", self._health)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    @web.middleware
    async def _middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        if self.down:
            if request.transport is not None:
                request.transport.close()
            raise web.HTTPServiceUnavailable
        return await handler(request)

    def _items(self, what: str) -> list[dict[str, Any]]:
        if what == "nodes":
            return [n._node_self() for n in self.nodes if not n.down]
        out: list[dict[str, Any]] = []
        for node in self.nodes:
            if not node.down:
                out.extend((node._collection(what) or {}).values())
        return out

    async def _versions(self, request: web.Request) -> web.Response:
        return web.json_response([f"{v}/" for v in NODE_VERSIONS])

    async def _base(self, request: web.Request) -> web.Response:
        return web.json_response([f"{w}/" for w in RESOURCES] + ["subscriptions/"])

    async def _list(self, request: web.Request) -> web.Response:
        what = request.match_info["what"]
        if request.match_info["ver"] not in NODE_VERSIONS or what not in RESOURCES:
            raise web.HTTPNotFound
        if what == "nodes":
            self.requests += 1
        return web.json_response(self._items(what))

    async def _item(self, request: web.Request) -> web.Response:
        what = request.match_info["what"]
        if what not in RESOURCES:
            raise web.HTTPNotFound
        item = next((i for i in self._items(what) if i["id"] == request.match_info["id"]), None)
        if item is None:
            raise web.HTTPNotFound
        return web.json_response(item)

    async def _registration_base(self, request: web.Request) -> web.Response:
        return web.json_response(["resource/", "health/"])

    async def _register(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.registered.append(body)
        return web.json_response(body.get("data", {}), status=201)

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"health": "0"})

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class SimNetwork:
    def __init__(
        self,
        specs: list[Spec],
        *,
        host: str = LOOPBACK,
        base_port: int = 0,
        mdns: str | None = LOOPBACK,
        registry: bool = False,
        registered: bool = False,
        p2p: bool = True,
    ) -> None:
        self.host = host
        self.nodes = [MockNode(spec, host, base_port + i if base_port else 0) for i, spec in enumerate(specs)]
        self.registry = Registry(self.nodes, host, base_port + len(specs) if base_port else 0) if registry else None
        self.registered = registered and registry
        self.p2p = p2p
        self._mdns_interface = mdns
        self._aiozc: AsyncZeroconf | None = None
        self._infos: dict[str, AsyncServiceInfo] = {}

    def node(self, label: str) -> MockNode:
        return next(n for n in self.nodes if n.spec.label == label)

    async def start(self) -> None:
        for node in self.nodes:
            await node.start()
        if self.registry is not None:
            await self.registry.start()
        if self._mdns_interface:
            self._aiozc = AsyncZeroconf(interfaces=[self._mdns_interface], ip_version=IPVersion.V4Only)
            for node in self.nodes if self.p2p else []:
                await self.announce(node)
            if self.registry is not None:
                props = {"api_proto": "http", "api_ver": ",".join(NODE_VERSIONS), "api_auth": "false", "pri": "100"}
                for key, service_type in (("registry", QUERY_TYPE), ("registration", REGISTER_TYPE)):
                    info = self._info(service_type, "sim-registry", self.registry.port, props)
                    await self._aiozc.async_register_service(info)
                    self._infos[key] = info

    def _info(self, service_type: str, name: str, port: int, props: dict[str, str]) -> AsyncServiceInfo:
        return AsyncServiceInfo(
            service_type, f"{name}.{service_type}", addresses=[socket.inet_aton(self.host)], port=port, properties=props,
            server=f"{name}.local.",
        )  # fmt: skip

    async def announce(self, node: MockNode) -> None:
        if self._aiozc is None:
            return
        props: dict[str, Any] = {"api_proto": "http", "api_ver": ",".join(NODE_VERSIONS), "api_auth": "false"}
        if not self.registered:  # IS-04: ein an der Registry angemeldeter Node lässt die Zähler weg
            props.update({f"ver_{k}": "1" for k in ("slf", "src", "flw", "dvc", "snd", "rcv")})
        info = self._info(NODE_TYPE, f"nmos-sim-{node.node_id[:8]}", node.port, props)
        await self._aiozc.async_register_service(info)
        self._infos[node.node_id] = info

    async def withdraw(self, node: MockNode) -> None:
        """mDNS-Abmeldung (Gerät wird ausgesteckt)."""
        info = self._infos.pop(node.node_id, None)
        if info is not None and self._aiozc is not None:
            await self._aiozc.async_unregister_service(info)

    async def stop(self) -> None:
        if self._aiozc is not None:
            await self._aiozc.async_unregister_all_services()
            await self._aiozc.async_close()
            self._aiozc = None
        self._infos.clear()
        for node in self.nodes:
            await node.stop()
        if self.registry is not None:
            await self.registry.stop()
