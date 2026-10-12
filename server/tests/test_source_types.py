"""Gerätetyp von NDI-Quellen: nachvollziehbare Regeln, kein Raten, Handwahl hat Vorrang."""

from __future__ import annotations

import pytest

from avmatrix.hub import MatrixError
from avmatrix.source_types import RULES, TYPES, classify, split_name


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("ZOWIECAM (ZowieCAM-12345)", "camera"),
        ("BIRDDOG-P200 (CAM)", "camera"),
        ("STUDIO (PTZ 2)", "camera"),
        ("192.0.2.227 (AUX2)", "encoder"),  # Gerät meldet sich mit seiner IP (LinkPi/TBS)
        ("192.0.2.50 (HDMI)", "encoder"),
        ("TBS2603 (Main)", "encoder"),
        ("MACBOOK-REGIE (Test Patterns)", "computer"),
        ("REGIE-PC (Scan Converter)", "computer"),
        ("DESKTOP-AB12 (irgendwas)", "computer"),
        ("MATRIXPI (Strelle AV Matrix Testbild)", "testpattern"),
        ("FOYER (Bühne links)", "unknown"),  # nichts erkennbar → neutral, nicht "Rechner"
        ("192.0.2.9 (Regie)", "unknown"),
        ("NUR-EIN-NAME", "unknown"),
    ],
)
def test_classify(source, expected):
    assert classify(source) == expected


def test_web_interface_can_identify_a_device():
    assert classify("192.0.2.9 (Regie)", "LinkPi Encoder nginx") == "encoder"
    assert classify("FOYER (Bühne links)", "ZowieBox camera") == "camera"


def test_table_is_consistent():
    assert split_name("A.B (C (D))") == ("A.B", "C (D)")
    assert {r.type for r in RULES} <= set(TYPES) and all(r.where in ("machine", "channel", "web", "ip_machine") for r in RULES)
    from pathlib import Path

    for _label, icon in TYPES.values():
        assert (Path(__file__).parents[1] / "avmatrix" / "static" / "devices" / f"{icon}.svg").is_file(), icon


async def test_snapshot_carries_type_and_manual_choice_wins(env):
    hub = env.hub
    source = next(s for s in hub.snapshot()["protocols"]["ndi"]["sources"] if s["id"] == "CAM (A)")
    assert source["device_type"] == "camera" and source["icon_key"] == "ndi_camera" and source["device_type_manual"] is False
    mac = next(s for s in hub.snapshot()["protocols"]["ndi"]["sources"] if s["id"] == "MAC (Schnitt)")
    assert mac["device_type"] == "computer"
    hub.set_source_type("ndi", "CAM (A)", "encoder")
    hub.set_label("ndi", "CAM (A)", "Totale", None)  # ein Label ändert die Handwahl nicht
    source = next(s for s in hub.snapshot()["protocols"]["ndi"]["sources"] if s["id"] == "CAM (A)")
    assert (source["device_type"], source["device_type_auto"], source["icon_key"], source["device_type_manual"]) == ("encoder", "camera", "ndi_encoder", True)
    hub.set_source_type("ndi", "CAM (A)", "auto")
    assert next(s for s in hub.snapshot()["protocols"]["ndi"]["sources"] if s["id"] == "CAM (A)")["device_type"] == "camera"
    assert hub.label("ndi", "CAM (A)") == {"label": "Totale"}
    with pytest.raises(MatrixError):
        hub.set_source_type("ndi", "CAM (A)", "toaster")


async def test_ip_named_source_is_followed_to_its_new_address(env):
    """Encoder mit IP im Namen wechselt die Adresse: ein Eintrag, Presets und alte Namen bleiben gültig."""
    hub = env.hub
    registry = hub.registries["ndi"]
    old, new = "192.0.2.50 (AUX1)", "192.0.2.77 (AUX1)"
    registry.set_discovered(old, "192.0.2.50:5961")
    await hub.evaluate()
    hub.save_preset("Encoder", [{"destination": "Monitor-1", "source": old}])
    hub.set_label("ndi", old, "Bühne", None)
    registry.remove_discovered(old)
    registry.set_discovered(new, "192.0.2.77:5961")
    await hub.evaluate()
    ids = [r.id for r in registry.sources]
    assert new in ids and old not in ids
    assert hub.presets["encoder"]["routes"][0]["source"] == new and hub.label("ndi", new)["label"] == "Bühne"
    assert hub.resolve_source("ndi", old) == new and hub.choices()["aliases"] == {old: new}
    # zwei Geräte mit demselben Kanalnamen werden NICHT zusammengelegt
    registry.set_discovered("192.0.2.90 (AUX1)", "192.0.2.90:5961")
    await hub.evaluate()
    assert {new, "192.0.2.90 (AUX1)"} <= {r.id for r in registry.sources}


async def test_forget_offline_source(env):
    hub = env.hub
    registry = hub.registries["ndi"]
    registry.set_discovered("GAST (Laptop)", "192.0.2.60:5961")
    await hub.evaluate()
    with pytest.raises(MatrixError):
        hub.forget_source("ndi", "GAST (Laptop)")  # sendet noch
    registry.remove_discovered("GAST (Laptop)")
    await hub.evaluate()
    assert any(r.id == "GAST (Laptop)" and not r.live for r in registry.sources)  # bleibt als offline stehen
    hub.forget_source("ndi", "GAST (Laptop)")
    assert all(r.id != "GAST (Laptop)" for r in registry.sources)
    with pytest.raises(MatrixError):
        hub.forget_source("ndi", "CAM (A)")
