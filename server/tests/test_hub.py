"""Hub: Schalten, Undo, Sperre, Presets, Schnappschuss."""

from __future__ import annotations

import pytest

from avmatrix.hub import MatrixError

from .conftest import AVIO, DA, settle

S2 = "magewell-s2_main"
TV = "magewell-tv_main"
DA_1 = f"dante_{DA}:1"
DA_2 = f"dante_{DA}:2"


async def test_snapshot_has_both_protocols(env):
    snap = env.hub.snapshot()
    ndi, dante = snap["protocols"]["ndi"], snap["protocols"]["dante"]
    assert [d["name"] for d in ndi["destinations"]] == ["Monitor-1", "TV"]
    s2 = ndi["destinations"][0]
    assert s2["current_source"] == "CAM (A)" and s2["status"] == "connected" and s2["host"] == "192.0.2.20"
    assert s2["web_url"] == "http://192.0.2.20" and s2["resolution"] == "1920x1080p50"
    assert {s["id"] for s in ndi["sources"]} == {"CAM (A)", "CAM (B)", "MAC (Schnitt)"}
    assert len(dante["destinations"]) == 2 + 2 + 64
    da = next(d for d in dante["destinations"] if d["id"] == DA_1)
    assert da["group"] == DA and da["host"] == "192.0.2.32" and da["web_url"] is None


async def test_route_undo_and_history(env):
    hub = env.hub
    event = await hub.route(S2, "CAM (B)")
    assert event["previous_source"] == "CAM (A)" and env.decoders["magewell-s2"].routes == ["CAM (B)"]
    assert hub.current_source(hub.destinations[S2]) == "CAM (B)"
    assert hub.snapshot()["can_undo"]
    await hub.undo(S2)
    assert env.decoders["magewell-s2"].current == "CAM (A)"
    with pytest.raises(MatrixError) as err:
        await hub.undo(S2)
    assert err.value.code == "nothing_to_undo"
    assert [e["origin"] for e in hub.events] == ["undo", "api"]


async def test_route_off_and_resolve_names(env):
    hub = env.hub
    assert hub.resolve_destination("monitor-1").uid == S2
    assert hub.resolve_destination(f"{DA}:1").uid == DA_1
    assert hub.resolve_source("ndi", "Aus") is None and hub.resolve_source("ndi", "") is None
    assert hub.resolve_source("ndi", "cam (b)") == "CAM (B)"
    hub.set_label("ndi", "MAC (Schnitt)", "Schnittplatz", None)
    assert hub.resolve_source("ndi", "Schnittplatz") == "MAC (Schnitt)"
    hub.set_destination_label(TV, "Fernseher", ["regie"])
    assert hub.resolve_destination("Fernseher").uid == TV
    with pytest.raises(MatrixError) as err:
        hub.resolve_destination("gibt es nicht")
    assert err.value.code == "unknown_destination"
    with pytest.raises(MatrixError):
        hub.resolve_source("dante", "kein-dante-name")
    await hub.route(S2, None)
    assert env.decoders["magewell-s2"].current is None
    assert hub.snapshot()["protocols"]["ndi"]["destinations"][0]["status"] == "no_source"


async def test_lock_blocks_everything(env):
    hub = env.hub
    hub.set_lock(S2, True)
    for call in (hub.route(S2, "CAM (B)"), hub.salvo([(TV, "CAM (B)"), (S2, "CAM (B)")])):
        with pytest.raises(MatrixError) as err:
            await call
        assert err.value.code == "locked" and err.value.status == 423
    assert env.decoders["magewell-tv"].routes == []  # Salve: nichts geschaltet
    hub.set_lock(S2, False)
    await hub.route(S2, "CAM (B)")


async def test_device_error_is_reported(env):
    env.decoders["magewell-s2"].fail = True
    with pytest.raises(MatrixError) as err:
        await env.hub.route(S2, "CAM (B)")
    assert err.value.code == "route_failed" and err.value.status == 502
    assert env.hub.current_source(env.hub.destinations[S2]) == "CAM (A)"


async def test_preset_lifecycle(env):
    hub = env.hub
    preset = hub.save_preset("Schnitt auf Regie", [{"destination": "Monitor-1", "source": "MAC (Schnitt)"}, {"destination": TV, "source": "CAM (B)"}])
    assert preset["id"] == "schnitt-auf-regie" and not preset["active"]
    assert [r["matches"] for r in preset["routes"]] == [False, False]
    with pytest.raises(MatrixError):
        hub.save_preset("schnitt auf regie", [{"destination": TV, "source": None}])  # Name vergeben
    with pytest.raises(MatrixError):
        hub.save_preset("leer", [])
    with pytest.raises(MatrixError):
        hub.save_preset("doppelt", [{"destination": TV, "source": None}, {"destination": "TV", "source": None}])

    result = await hub.recall_preset("Schnitt auf Regie")
    assert set(result["switched"]) == {S2, TV}
    assert env.decoders["magewell-s2"].current == "MAC (Schnitt)" and env.decoders["magewell-tv"].current == "CAM (B)"
    assert hub.presets_view()[0]["active"] and hub.status()["presets"] == {"schnitt-auf-regie": True}

    await hub.route(TV, "CAM (A)")  # Ist-Zustand weicht ab → nicht mehr aktiv
    assert not hub.presets_view()[0]["active"]

    hub.save_preset("Regie", [{"destination": TV, "source": "CAM (A)"}], preset_id="schnitt-auf-regie")  # ändern + umbenennen
    assert hub.get_preset("regie")["id"] == "schnitt-auf-regie" and hub.presets_view()[0]["active"]

    snap = hub.snapshot_preset("Ist", [S2, DA_1])  # aus dem Ist-Zustand
    assert snap["active"] and {r["destination"] for r in snap["routes"]} == {S2, DA_1}

    hub.delete_preset("Ist")
    with pytest.raises(MatrixError) as err:
        await hub.recall_preset("Ist")
    assert err.value.code == "unknown_preset"


async def test_undo_last_takes_back_a_whole_preset(env):
    hub = env.hub
    hub.save_preset("P", [{"destination": S2, "source": "CAM (B)"}, {"destination": DA_1, "source": f"CH2@{AVIO}"}])
    da_before = hub.current_source(hub.destinations[DA_1])
    await hub.recall_preset("P")
    await settle(hub)
    assert hub.presets_view()[0]["active"]
    result = await hub.undo_last()
    await settle(hub)
    assert result["undone"] == "preset" and len(result["restored"]) == 2
    assert env.decoders["magewell-s2"].current == "CAM (A)"
    assert hub.current_source(hub.destinations[DA_1]) == da_before
    assert not hub.snapshot()["can_undo"]
    with pytest.raises(MatrixError):
        await hub.undo_last()


async def test_preset_skips_offline_device_and_reports_it(env):
    hub = env.hub
    hub.save_preset("P", [{"destination": S2, "source": "CAM (B)"}, {"destination": TV, "source": "CAM (B)"}])
    env.decoders["magewell-tv"].offline = True
    await settle(hub)
    result = await hub.recall_preset("P")
    assert result["switched"] == [S2] and result["skipped_offline"] == [TV]
    assert not hub.presets_view()[0]["active"]


async def test_state_survives_restart(env):
    hub = env.hub
    hub.set_lock(TV, True)
    hub.set_label("ndi", "CAM (A)", "Totale", ["kamera"])
    hub.save_preset("P", [{"destination": S2, "source": "CAM (B)"}])
    hub.state.save_now()
    from avmatrix.hub import Hub
    from avmatrix.store import JsonFile

    again = Hub(JsonFile(hub.config.path), JsonFile(hub.state.path), driver_factory=lambda e: None)
    again.load()
    assert again.locks == {TV} and again.labels["ndi"]["CAM (A)"]["label"] == "Totale" and "p" in again.presets
    assert set(again.entries) == {"dante", "magewell-s2", "magewell-tv"}


async def test_devices_overview_has_no_secrets(env):
    env.hub.entries["magewell-s2"].data["password"] = "geheim"
    text = str(env.hub.devices())
    assert "geheim" not in text and "Monitor-1" in text and AVIO in text


def test_live_source_has_no_last_seen_so_polls_do_not_change_the_snapshot() -> None:
    """Ein live gemeldeter Zeitstempel änderte den Stand bei jeder Abfrage – das Panel baute sich dauernd neu auf."""
    import pathlib
    import tempfile

    from avmatrix.hub import Hub
    from avmatrix.store import JsonFile
    d = pathlib.Path(tempfile.mkdtemp())
    hub = Hub(JsonFile(d / "c.json"), JsonFile(d / "s.json"))
    assert hub._source_dict("ndi", "X (Y)", True, "192.0.2.1:5961", 1000.0, 900.0)["last_seen"] is None
    assert hub._source_dict("ndi", "X (Y)", False, None, 1000.0, 900.0)["last_seen"]
