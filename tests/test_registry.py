"""Source registry: dedupe, liveness, hysteresis, placeholder (umlaut) mapping."""

from __future__ import annotations

from custom_components.av_matrix.models import SourceSighting as S
from custom_components.av_matrix.protocols.ndi import NdiSourceRegistry, ndi_name_from_mdns


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(alive=()):
    probed = []

    async def probe(addr):
        probed.append(addr)
        return addr in alive

    clock = Clock()
    return NdiSourceRegistry(probe, clock=clock), clock, probed


def names(reg, live_only=False):
    return [r.id for r in reg.sources if r.live or not live_only]


def test_mdns_name():
    assert (
        ndi_name_from_mdns("MACHINE.LOCALDOMAIN (Test Patterns)._ndi._tcp.local.")
        == "MACHINE.LOCALDOMAIN (Test Patterns)"
    )
    assert ndi_name_from_mdns("A (B)._ndi._tcp.local") == "A (B)"


async def test_dedupe_by_name():
    reg, _, _ = make()
    reg.set_discovered("A (1)", "192.0.2.1:5961")
    reg.set_device_sightings("mw1", [S("A (1)", "192.0.2.1:5961"), S("B (2)", "192.0.2.2:5961")], trusted=True)
    reg.set_device_sightings("mw2", [S("B (2)", "192.0.2.2:5961")], trusted=True)
    assert await reg.async_evaluate()
    assert names(reg) == ["A (1)", "B (2)"]
    assert reg.get("B (2)").seen_by == {"mw1", "mw2"}
    assert not await reg.async_evaluate()  # unchanged


async def test_untrusted_needs_tcp_answer():
    reg, _, probed = make(alive={"192.0.2.9:5961"})
    reg.set_device_sightings("bd", [S("LIVE (x)", "192.0.2.9:5961"), S("GHOST (y)", "192.0.2.8:5961")], trusted=False)
    await reg.async_evaluate()
    assert names(reg) == ["LIVE (x)"]
    assert sorted(probed) == ["192.0.2.8:5961", "192.0.2.9:5961"]


async def test_untrusted_address_occupied_by_other_live_name():
    """Port reuse: BirdDog still lists an old name on an address a different source uses now."""
    reg, _, probed = make(alive={"192.0.2.9:5961"})
    reg.set_discovered("NEW (foyer)", "192.0.2.9:5961")
    reg.set_device_sightings("bd", [S("OLD (resolume)", "192.0.2.9:5961")], trusted=False)
    await reg.async_evaluate()
    assert names(reg) == ["NEW (foyer)"]
    assert probed == []


async def test_probe_cache():
    reg, clock, probed = make(alive={"192.0.2.9:5961"})
    reg.set_device_sightings("bd", [S("X (y)", "192.0.2.9:5961")], trusted=False)
    await reg.async_evaluate()
    await reg.async_evaluate()
    assert len(probed) == 1
    clock.t += 9
    await reg.async_evaluate()
    assert len(probed) == 2


async def test_hysteresis_two_minutes():
    reg, clock, _ = make()
    reg.set_discovered("A (1)", "192.0.2.1:5961")
    await reg.async_evaluate()
    reg.remove_discovered("A (1)")
    clock.t += 60
    assert await reg.async_evaluate()  # live flag changed
    assert names(reg) == ["A (1)"] and not reg.is_live("A (1)")
    clock.t += 59
    await reg.async_evaluate()
    assert names(reg) == ["A (1)"]
    clock.t += 2
    assert await reg.async_evaluate()
    assert names(reg) == []


async def test_placeholder_mapped_by_address():
    reg, _, _ = make()
    reg.set_discovered("STUDIO (Präsentation)", "192.0.2.7:5963")
    reg.set_device_sightings("bd", [S("NDI_0A1B2C3D4E", "192.0.2.7:5963")], trusted=False)
    await reg.async_evaluate()
    assert names(reg) == ["STUDIO (Präsentation)"]
    assert reg.real_name("bd", "NDI_0A1B2C3D4E") == "STUDIO (Präsentation)"
    assert reg.device_name("bd", "STUDIO (Präsentation)") == "NDI_0A1B2C3D4E"
    # other devices use the real name
    assert reg.device_name("mw", "STUDIO (Präsentation)") == "STUDIO (Präsentation)"
    # mapping survives a short mDNS gap
    reg.remove_discovered("STUDIO (Präsentation)")
    await reg.async_evaluate()
    assert reg.real_name("bd", "NDI_0A1B2C3D4E") == "STUDIO (Präsentation)"


async def test_unmapped_placeholder_is_its_own_source():
    reg, _, _ = make(alive={"192.0.2.7:5963"})
    reg.set_device_sightings("bd", [S("NDI_0A1B2C3D4E", "192.0.2.7:5963")], trusted=False)
    await reg.async_evaluate()
    assert names(reg) == ["NDI_0A1B2C3D4E"]


async def test_remove_device_and_forget():
    reg, _, _ = make()
    reg.set_device_sightings("mw", [S("A (1)", "192.0.2.1:1")], trusted=True)
    await reg.async_evaluate()
    reg.remove_device("mw")
    await reg.async_evaluate()
    assert names(reg) == ["A (1)"] and not reg.is_live("A (1)")  # held
    reg.forget()
    assert names(reg) == []
