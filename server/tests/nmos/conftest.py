"""Gemeinsame Testhelfer: simulierte NMOS-Geräte auf 127.0.0.1 und ein Treiber, der sie über echtes HTTP anspricht."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import aiohttp
import pytest

from avmatrix.drivers import nmos as nmos_driver
from avmatrix.drivers.nmos import NmosNetwork
from nmos_sim import blackmagic
from nmos_sim.network import SimNetwork
from nmos_sim.node import Spec

MINI = "Blackmagic 2110 IP Mini IP to HDMI"
PRES = "Blackmagic 2110 IP Presentation Converter"
BIDI = "Blackmagic 2110 IP Mini BiDirect 12G"
QUAD = "Blackmagic 2110 IP Converter 4x12G PWR"
DECK = "DeckLink IP/SDI HD"


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nmos_driver, "VERIFY_DELAYS", (0.0,))


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as s:
        yield s


MakeNet = Callable[..., Awaitable[SimNetwork]]


@pytest.fixture
async def make_net() -> AsyncIterator[MakeNet]:
    nets: list[SimNetwork] = []

    async def make(specs: list[Spec] | None = None, **kwargs: Any) -> SimNetwork:
        kwargs.setdefault("mdns", None)
        net = SimNetwork(specs if specs is not None else blackmagic.studio(), **kwargs)
        await net.start()
        nets.append(net)
        return net

    yield make
    for net in nets:
        await net.stop()


def hosts(net: SimNetwork) -> list[str]:
    return [f"127.0.0.1:{n.port}" for n in net.nodes]


def driver_for(
    session: aiohttp.ClientSession, net: SimNetwork | None = None, timeout: float = 3.0, **options: Any
) -> NmosNetwork:
    if net is not None:
        options.setdefault("static_hosts", hosts(net))
    return NmosNetwork(session, {"host": "nmos"}, timeout=timeout, options=options)


@pytest.fixture
async def studio(make_net: MakeNet, session: aiohttp.ClientSession) -> tuple[SimNetwork, NmosNetwork]:
    """Die fünf Blackmagic-Geräte, einmal abgefragt."""
    net = await make_net()
    driver = driver_for(session, net)
    await driver.async_poll()
    return net, driver
