"""Mehrere Mock-Nodes starten, per mDNS ankündigen, optional eine Registry (IS-04 Query API) dazu.

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
LOOPBACK = "127.0.0.1"


class Registry:
    """Winzige Registry: beantwortet nur ``GET /x-nmos/query/<ver>/nodes``."""

    def __init__(self, nodes: list[MockNode], host: str = LOOPBACK) -> None:
        self.nodes = nodes
        self.host = host
        self.port = 0
        self.requests = 0
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/x-nmos/query/", self._versions)
        app.router.add_get("/x-nmos/query/{ver}/nodes", self._nodes)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    async def _versions(self, request: web.Request) -> web.Response:
        return web.json_response([f"{v}/" for v in NODE_VERSIONS])

    async def _nodes(self, request: web.Request) -> web.Response:
        self.requests += 1
        return web.json_response([n._node_self() for n in self.nodes])

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class SimNetwork:
    def __init__(
        self, specs: list[Spec], *, host: str = LOOPBACK, base_port: int = 0, mdns: str | None = LOOPBACK, registry: bool = False
    ) -> None:
        self.host = host
        self.nodes = [MockNode(spec, host, base_port + i if base_port else 0) for i, spec in enumerate(specs)]
        self.registry = Registry(self.nodes, host) if registry else None
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
            for node in self.nodes:
                await self.announce(node)
            if self.registry is not None:
                info = self._info(
                    QUERY_TYPE,
                    "sim-registry",
                    self.registry.port,
                    {"api_proto": "http", "api_ver": ",".join(NODE_VERSIONS), "api_auth": "false", "pri": "100"},
                )
                await self._aiozc.async_register_service(info)
                self._infos["registry"] = info

    def _info(self, service_type: str, name: str, port: int, props: dict[str, str]) -> AsyncServiceInfo:
        return AsyncServiceInfo(
            service_type, f"{name}.{service_type}", addresses=[socket.inet_aton(self.host)], port=port, properties=props,
            server=f"{name}.local.",
        )  # fmt: skip

    async def announce(self, node: MockNode) -> None:
        if self._aiozc is None:
            return
        props: dict[str, Any] = {"api_proto": "http", "api_ver": ",".join(NODE_VERSIONS), "api_auth": "false"}
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
