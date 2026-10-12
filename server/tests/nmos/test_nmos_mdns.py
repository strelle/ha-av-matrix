"""Finden per mDNS / DNS-SD – ausschließlich auf der Loopback-Schnittstelle (nichts davon erreicht das Studionetz)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncZeroconf

from avmatrix.drivers import nmos as nmos_driver
from avmatrix.drivers.nmos import NmosNetwork
from avmatrix.protocols.nmos_mdns import NmosBrowser, txt
from nmos_sim import blackmagic

from .conftest import BIDI, MINI, MakeNet, driver_for

LOOP = "127.0.0.1"


@pytest.fixture
async def zc() -> AsyncIterator[AsyncZeroconf]:
    aiozc = AsyncZeroconf(interfaces=[LOOP], ip_version=IPVersion.V4Only)
    yield aiozc
    await aiozc.async_close()


async def until(condition: Callable[[], bool], seconds: float = 8.0) -> None:
    for _ in range(int(seconds / 0.05)):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Bedingung nicht erreicht")


async def test_nodes_are_found_appear_later_and_go_offline(make_net: MakeNet, session, zc, monkeypatch) -> None:
    monkeypatch.setattr(nmos_driver, "OFFLINE_RETRY_EVERY", 1)
    await make_net([blackmagic.mini_ip_to_hdmi()], mdns=LOOP)
    driver = driver_for(session)
    changes: list[int] = []
    browser = NmosBrowser(zc.zeroconf, lambda: driver, lambda: changes.append(1))
    await browser.async_start()
    try:
        await until(lambda: len(browser.nodes) == 1)
        result = await driver.async_poll()
        assert list(result.destinations) == [f"{MINI}:HDMI Out"]
        node = driver.device_for(MINI)
        assert node.via_mdns and not node.static and node.txt["api_ver"] == "v1.0,v1.1,v1.2,v1.3" and changes

        # ein zweites Gerät wird eingesteckt: erscheint ohne Neustart
        later = await make_net([blackmagic.mini_bidirect_12g()], mdns=LOOP)
        await until(lambda: len(browser.nodes) == 2)
        result = await driver.async_poll()
        assert [s.name for s in result.sources] == [f"SDI In@{BIDI}"] and len(result.destinations) == 2

        # das zweite Gerät wird ausgesteckt: mDNS-Abmeldung, Gerät antwortet nicht mehr → offline, Ziel bleibt
        later.nodes[0].down = True
        await later.withdraw(later.nodes[0])
        await until(lambda: len(browser.nodes) == 1)
        assert driver.device_for(BIDI).via_mdns is False
        await driver.async_poll()
        result = await driver.async_poll()
        assert driver.device_for(BIDI).online is False
        assert result.sources == [] and f"{BIDI}:SDI Out" in result.destinations
        assert driver.destination_available(f"{BIDI}:SDI Out") is False and driver.destination_available(f"{MINI}:HDMI Out")
    finally:
        await browser.async_stop()


async def test_driver_started_after_discovery_is_fed(make_net: MakeNet, session, zc) -> None:
    """Die Suche läuft schon, das ST-2110-Netz wird erst später eingerichtet (wie Dante im Server)."""
    await make_net(mdns=LOOP)
    holder: dict[str, NmosNetwork] = {}
    browser = NmosBrowser(zc.zeroconf, lambda: holder.get("driver"))
    await browser.async_start()
    try:
        await until(lambda: len(browser.nodes) == 5)
        holder["driver"] = driver = driver_for(session)
        browser.feed(driver)
        result = await driver.async_poll()
        assert len(driver.devices) == 5 and len(result.destinations) == 9
    finally:
        await browser.async_stop()


async def test_registry_announced_via_mdns(make_net: MakeNet, session, zc) -> None:
    net = await make_net([blackmagic.mini_ip_to_hdmi()], mdns=LOOP, registry=True)
    driver = driver_for(session)
    browser = NmosBrowser(zc.zeroconf, lambda: driver)
    await browser.async_start()
    try:
        await until(lambda: len(browser.registries) == 1 and len(browser.nodes) == 1)
        assert list(driver.registries) == [net.registry.url]
        await driver.async_poll()
        assert driver.device_for(MINI).via_registry and driver.device_for(MINI).via_mdns
        assert net.registry.requests == 1
    finally:
        await browser.async_stop()


def test_txt_decoding() -> None:
    assert txt({b"api_proto": b"http", b"flag": None, b"bad": b"\xff\xfe"}) == {"api_proto": "http", "flag": ""}
    assert txt(None) == {}


async def test_registered_nodes_registry_announces_both_services(make_net: MakeNet, session, zc) -> None:
    """Betrieb mit Registry: Query- und Registration-API sind angekündigt, die Geräte ohne Änderungszähler."""
    net = await make_net(blackmagic.studio_with_switch(), mdns=LOOP, registry=True, registered=True)
    driver = driver_for(session)
    browser = NmosBrowser(zc.zeroconf, lambda: driver)
    await browser.async_start()
    try:
        await until(lambda: len(browser.registries) == 1 and len(browser.registrations) == 1 and len(browser.nodes) == 6)
        assert list(driver.registries) == [net.registry.url] and driver.registrations == {net.registry.url}
        result = await driver.async_poll()
        assert len(driver.devices) == 6 and len(result.destinations) == 10  # beide Wege, jedes Gerät einmal
        assert all(n.via_mdns and n.via_registry and "ver_rcv" not in n.txt for n in driver.devices.values())
    finally:
        await browser.async_stop()


async def test_devices_only_known_to_the_registry_and_registry_found_by_itself(make_net: MakeNet, session, zc) -> None:
    """Die Geräte kündigen sich nicht selbst an (anderes Netz): die per mDNS gefundene Registry reicht."""
    net = await make_net(mdns=LOOP, registry=True, p2p=False)
    driver = driver_for(session)
    browser = NmosBrowser(zc.zeroconf, lambda: driver)
    await browser.async_start()
    try:
        await until(lambda: len(browser.registries) == 1)
        assert browser.nodes == {}
        await driver.async_poll()  # die neu gefundene Registry wird sofort gefragt, nicht erst nach einer halben Minute
        assert len(driver.devices) == 5 and all(n.via_registry and not n.via_mdns for n in driver.devices.values())
        assert driver.registries[net.registry.url] == {"mdns": True, "version": "v1.3", "error": None, "nodes": 5}
    finally:
        await browser.async_stop()
