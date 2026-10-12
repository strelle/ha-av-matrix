"""Gemeinsame Testhelfer: Hub mit simuliertem Dante-Netz (wie im Studio) und einem falschen NDI-Decoder."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

# Treiber, Karte und Treiber-Tests kommen aus der Home-Assistant-Variante (eine Quelle): vor dem Import spiegeln
subprocess.run([str(Path(__file__).parents[1] / "scripts" / "sync-shared.sh"), "-q"], check=True)

import pytest

from avmatrix.drivers.base import Driver, RouteFailed
from avmatrix.guard import GuardedDanteNetwork
from avmatrix.hub import Entry, Hub
from avmatrix.models import DestinationState, DestinationStatus, DeviceInfo, DevicePoll, SourceSighting
from avmatrix.protocols import dante as arc
from avmatrix.store import JsonFile, TokenFile

from .dante_sim import FakeDanteDevice, FakeRx, FakeTransport, studio_network

AVIO = "AVIOAES3-0d0e0f"
DA = "DA-22UC-0a0b0c"
AVIO_HOST = "192.0.2.31"  # Beispieladressen (RFC 5737)
DA_HOST = "192.0.2.32"
WING = "PULT-WING"
WING_HOST = "192.0.2.33"
#: Sperrliste dieser Test-Anlage: der AES3-Adapter ganz, am Pult nur die Empfangskanäle 61/62
RULES = [
    {"protocol": "dante", "host": AVIO_HOST, "device": "AVIOAES3*", "channels": None, "reason": "AES3-Adapter: Pult-Zuordnung 61/62"},
    {"protocol": "dante", "host": WING_HOST, "device": WING, "channels": [61, 62], "reason": "Pult-Empfang 61/62 vom AES3-Adapter"},
]
TXT = {"arcp_vers": "2.8.9", "mf": "Audinate", "model": "DIOAES3", "router_vers": "4.3.0"}


@pytest.fixture
def session():
    from .fake_http import FakeSession

    return FakeSession()


class FakeDecoder(Driver):
    """NDI-Decoder im Speicher."""

    KEY = "magewell"
    PROTOCOL = "ndi"
    TITLE = "Fake"
    MANUFACTURER = "Magewell"
    SETTLE_TIME = 0.0

    def __init__(self, session: Any, config: dict[str, Any], timeout: float = 3.0) -> None:
        self._session = session
        self.config = dict(config)
        self.host = config["host"]
        self.port = 80
        self.current: str | None = config.get("initial")
        self.sources = ["CAM (A)", "CAM (B)", "MAC (Schnitt)"]
        self.routes: list[str | None] = []
        self.fail = False
        self.offline = False

    async def async_get_info(self) -> DeviceInfo:
        return DeviceInfo(name=self.config.get("name"), manufacturer="Magewell", model="NDI to AIO", serial=self.host)

    async def async_get_sources(self) -> list[SourceSighting]:
        return [SourceSighting(s, "192.0.2.9:5961") for s in self.sources]

    async def async_get_current(self, destination: str) -> str | None:
        return self.current

    async def async_route(self, destination: str, source: str | None, address: str | None = None) -> None:
        if self.fail:
            raise RouteFailed("device answered status 5")
        self.routes.append(source)
        self.current = source

    async def async_poll(self) -> DevicePoll:
        if self.offline:
            from avmatrix.drivers.base import CannotConnect

            raise CannotConnect("timeout")
        return DevicePoll(
            sources=await self.async_get_sources(),
            destinations={"main": DestinationState(self.current, DestinationStatus(connected=True, resolution="1920x1080p50"))},
        )


def studio_sim() -> dict[str, FakeDanteDevice]:
    """Studio-Netz der HA-Tests plus ein 64-Kanal-Pult, dessen RX 61/62 vom AVIO-Adapter kommen."""
    network = studio_network()
    rx = [FakeRx(f"{n:02d}") for n in range(1, 65)]
    rx[60] = FakeRx("61", "CH1", AVIO, 0x09, 0x0101)
    rx[61] = FakeRx("62", "CH2", AVIO, 0x09, 0x0101)
    network[WING] = FakeDanteDevice(WING, [f"{n:02d}" for n in range(1, 9)], rx, network=network)
    return network


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """Hub mit Dante-Netz (AVIO, DA-22UC, WING) und zwei NDI-Decodern; Abfragen laufen von Hand."""
    network = studio_sim()
    FakeTransport.hosts = {AVIO_HOST: network[AVIO], DA_HOST: network[DA], WING_HOST: network[WING]}
    monkeypatch.setattr("avmatrix.drivers.dante.VERIFY_DELAYS", (0.0,))
    monkeypatch.setattr("avmatrix.hub.FOLLOWUP_DELAYS", ())
    decoders: dict[str, FakeDecoder] = {}

    def factory(entry: Entry) -> Driver:
        if entry.driver == "dante":
            driver = GuardedDanteNetwork(None, entry.data, options=entry.options, transport=FakeTransport())
            for host, dev in FakeTransport.hosts.items():
                if dev.mdns:
                    driver.add_host(host, arc.ARC_PORT, TXT, mdns=True)
            return driver
        decoders[entry.id] = FakeDecoder(None, entry.data)
        return decoders[entry.id]

    config = JsonFile(tmp_path / "cfg" / "config.json")
    config.data = {
        "protected": RULES,
        "devices": [
            {"id": "dante", "driver": "dante", "title": "Dante-Netzwerk", "data": {"host": "dante"}},
            {"id": "magewell-s2", "driver": "magewell", "title": "Monitor-1", "data": {"host": "192.0.2.20", "initial": "CAM (A)"}},
            {"id": "magewell-tv", "driver": "magewell", "title": "TV", "data": {"host": "192.0.2.21"}},
        ]
    }
    config.save_now()
    hub = Hub(config, JsonFile(tmp_path / "data" / "state.json"), driver_factory=factory)
    hub.load()
    await hub.start()
    await settle(hub)

    class Env:
        pass

    e = Env()
    e.hub, e.network, e.decoders, e.tmp = hub, network, decoders, tmp_path
    e.token = TokenFile(tmp_path / "cfg" / "token")
    yield e
    await hub.stop()


async def settle(hub: Hub) -> None:
    """Alle Geräte einmal abfragen und die Quellenregister auswerten."""
    for _ in range(2):
        await asyncio.gather(*(p.refresh() for p in hub.pollers.values()))
        await hub.evaluate()
        await asyncio.sleep(0)
