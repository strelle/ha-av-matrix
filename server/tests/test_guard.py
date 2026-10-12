"""Die feste Sperrliste: geschützte Ziele (hier ein AES3-Adapter und zwei Pult-Kanäle) verändert KEIN Weg."""

from __future__ import annotations

import pytest

from avmatrix.drivers.base import RouteFailed
from avmatrix.guard import DEFAULT_RULES, Guard, ProtectionRule
from avmatrix.hub import Hub, MatrixError
from avmatrix.protocols import dante as arc
from avmatrix.store import JsonFile

from .conftest import AVIO, AVIO_HOST, DA, DA_HOST, RULES, WING, WING_HOST, settle

AVIO_1 = f"dante_{AVIO}:1"
AVIO_2 = f"dante_{AVIO}:2"
DA_1 = f"dante_{DA}:1"
WING_61 = f"dante_{WING}:61"
WING_60 = f"dante_{WING}:60"
WRITES = (arc.OP_SUBSCRIPTION_ADD, arc.OP_SUBSCRIPTION_REMOVE, arc.OP_SUBSCRIPTION_PAGE)


def writes(dev) -> list[bytes]:
    """Abo-Pakete (Schreibzugriffe), die das simulierte Gerät bekommen hat."""
    return [p for p in dev.requests if int.from_bytes(p[6:8], "big") in WRITES]


def test_rules_match_by_address_or_name():
    guard = Guard.from_config(RULES)
    assert guard.rule_for("dante", AVIO_HOST, "irgendein-name", 1)  # über die Adresse
    assert guard.rule_for("dante", "198.51.100.5", "AVIOAES3-aabbcc", 2)  # über den Namen (andere Adresse)
    assert guard.rule_for("dante", WING_HOST, WING, 61)
    assert guard.rule_for("dante", WING_HOST, WING, 62)
    assert guard.rule_for("dante", WING_HOST, WING, 60) is None
    assert guard.rule_for("dante", DA_HOST, "DA-22UC-ddeeff", 1) is None
    assert guard.rule_for("ndi", "192.0.2.20", "Decoder", None) is None


def test_no_rules_without_configuration():
    assert DEFAULT_RULES == [] and Guard.from_config(None).rules == []


def test_rules_are_configurable():
    assert Guard.from_config([]).rules == []
    guard = Guard.from_config([{"device": "stagebox*", "channels": [3], "reason": "x"}])
    assert guard.rule_for("dante", None, "STAGEBOX-01", 3)
    assert guard.rule_for("dante", None, "STAGEBOX-01", 4) is None
    assert guard.rule_for("dante", None, "STAGEBOX-01", None)  # Kanal unbekannt → im Zweifel geschützt
    with pytest.raises(ValueError):
        ProtectionRule.from_dict({"reason": "ohne Ziel"})


async def test_rules_come_from_the_config_file(env, tmp_path):
    assert [r.host for r in env.hub.guard.rules] == [AVIO_HOST, WING_HOST]
    fresh = Hub(JsonFile(tmp_path / "neu" / "config.json"), JsonFile(tmp_path / "neu" / "state.json"))
    fresh.load()  # neue Anlage: Schlüssel wird angelegt, damit man ihn in der Datei findet
    assert fresh.config.data["protected"] == [] and fresh.guard.rules == []


async def test_snapshot_marks_protected_destinations(env):
    dests = {d["id"]: d for d in env.hub.snapshot()["protocols"]["dante"]["destinations"]}
    for uid in (AVIO_1, AVIO_2, WING_61):
        assert dests[uid]["protected"] and dests[uid]["locked"] and not dests[uid]["can_undo"]
    assert dests[DA_1]["protected"] is None and dests[DA_1]["locked"] is False
    assert dests[WING_60]["protected"] is None


async def test_no_path_changes_the_adapter(env):
    """Schalten, Trennen, Salve, Undo, Entsperren, Preset: alles abgelehnt, kein einziges Abo-Paket geht raus."""
    hub = env.hub
    avio, wing = env.network[AVIO], env.network[WING]
    before = [(c.tx_channel, c.tx_device) for c in avio.rx]
    before_wing = (wing.rx[60].tx_channel, wing.rx[60].tx_device)

    for uid in (AVIO_1, AVIO_2, WING_61):
        with pytest.raises(MatrixError) as err:
            await hub.route(uid, f"CH1@{DA}")
        assert err.value.code == "protected" and err.value.status == 403
        with pytest.raises(MatrixError) as err:
            await hub.route(uid, None)  # trennen
        assert err.value.code == "protected"
        with pytest.raises(MatrixError) as err:
            await hub.undo(uid)
        assert err.value.code == "protected"
        with pytest.raises(MatrixError) as err:
            hub.set_lock(uid, False)  # "entsperren" hebt den Schutz nicht auf
        assert err.value.code == "protected"

    # Salve: ein geschütztes Ziel → gar nichts wird geschaltet, auch das erlaubte nicht
    da_before = [(c.tx_channel, c.tx_device) for c in env.network[DA].rx]
    with pytest.raises(MatrixError) as err:
        await hub.salvo([(DA_1, f"CH1@{AVIO}"), (AVIO_1, f"CH1@{DA}")])
    assert err.value.code == "protected"
    assert [(c.tx_channel, c.tx_device) for c in env.network[DA].rx] == da_before

    # Presets mit geschütztem Ziel lassen sich nicht einmal anlegen
    with pytest.raises(MatrixError) as err:
        hub.save_preset("böse", [{"destination": AVIO_2, "source": None}])
    assert err.value.code == "protected"
    with pytest.raises(MatrixError):
        hub.snapshot_preset("böse", [WING_61])

    # ein von Hand in den Zustand geschmuggeltes Preset wird beim Abruf komplett abgelehnt
    hub.presets["x"] = {"id": "x", "name": "x", "routes": [{"destination": DA_1, "source": None}, {"destination": AVIO_1, "source": None}]}
    with pytest.raises(MatrixError) as err:
        await hub.recall_preset("x")
    assert err.value.code == "protected"

    await settle(hub)
    assert [(c.tx_channel, c.tx_device) for c in avio.rx] == before
    assert (wing.rx[60].tx_channel, wing.rx[60].tx_device) == before_wing
    assert writes(avio) == [] and writes(wing) == []


async def test_driver_refuses_even_if_the_hub_is_bypassed(env):
    """Zweite Ebene: der Dante-Treiber selbst schickt kein Abo-Paket an geschützte Kanäle."""
    driver = env.hub.pollers["dante"].driver
    avio = env.network[AVIO]
    with pytest.raises(RouteFailed, match="gesperrt"):
        await driver.async_route(f"{AVIO}:1", f"CH1@{DA}")
    with pytest.raises(RouteFailed, match="gesperrt"):
        await driver.async_route(f"{AVIO}:2", None)
    with pytest.raises(RouteFailed, match="gesperrt"):
        await driver.async_route(f"{WING}:62", None)
    assert writes(avio) == [] and writes(env.network[WING]) == []
    # … und selbst wenn die Hub-Prüfung ausfiele, hält die Treiber-Ebene
    env.hub._check_writable = lambda dest: None  # type: ignore[method-assign]
    with pytest.raises(MatrixError) as err:
        await env.hub.route(AVIO_1, None)
    assert err.value.code == "route_failed" and "gesperrt" in err.value.message
    assert writes(avio) == []


async def test_renamed_adapter_stays_protected_by_address(env):
    """Umbenennen in Dante Controller ändert den Namen – die Adresse in der Regel schützt weiter."""
    hub = env.hub
    env.network[AVIO].name = "Regie-AES"
    env.network[AVIO].captured.clear()
    hub.pollers["dante"].driver._full_refresh = True
    await settle(hub)
    assert "dante_Regie-AES:1" in hub.destinations
    with pytest.raises(MatrixError) as err:
        await hub.route("dante_Regie-AES:1", None)
    assert err.value.code == "protected"
    assert writes(env.network[AVIO]) == []


async def test_unprotected_destination_still_routes(env):
    """Gegenprobe: das unkritische Ziel lässt sich schalten und zurückstellen."""
    hub, da = env.hub, env.network[DA]
    start = hub.current_source(hub.destinations[DA_1])
    await hub.route(DA_1, f"CH2@{AVIO}")
    assert (da.rx[0].tx_channel, da.rx[0].tx_device) == ("CH2", AVIO)
    assert len(writes(da)) == 1
    await hub.undo(DA_1)
    await settle(hub)
    assert hub.current_source(hub.destinations[DA_1]) == start
    assert AVIO_HOST in {d.host for d in hub.pollers["dante"].driver.devices.values()}
