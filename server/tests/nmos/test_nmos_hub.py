"""Der ECHTE Hub des Servers (aus ha-av-matrix, unverändert kopiert) mit eingehängtem NMOS-Treiber.

Läuft nur über ``scripts/overlay-test.sh``: dort ist ``avmatrix`` der Server samt Hub, nicht der Spiegel dieses
Repos. Geprüft wird der Vertrag: Schnappschuss, Schalten, Undo, Salve, Preset, Offline, Geräteübersicht.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from avmatrix.drivers import DRIVERS
from avmatrix.drivers.nmos import NmosNetwork
from avmatrix.hub import Entry, Hub, MatrixError
from avmatrix.protocols import PROTOCOLS
from avmatrix.store import JsonFile
from nmos_sim import blackmagic
from nmos_sim.network import SimNetwork

MINI = "Blackmagic 2110 IP Mini IP to HDMI"
BIDI = "Blackmagic 2110 IP Mini BiDirect 12G"
QUAD = "Blackmagic 2110 IP Converter 4x12G PWR"
DECK = "DeckLink IP/SDI HD"
HDMI = f"nmos_{MINI}:HDMI Out"
BIDI_IN = f"SDI In@{BIDI}"


async def settle(hub: Hub) -> None:
    for _ in range(2):
        await asyncio.gather(*(p.refresh() for p in hub.pollers.values()))
        await hub.evaluate()
        await asyncio.sleep(0)


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setattr("avmatrix.hub.FOLLOWUP_DELAYS", ())
    monkeypatch.setattr("avmatrix.drivers.nmos.VERIFY_DELAYS", (0.0,))
    monkeypatch.setattr("avmatrix.drivers.nmos.OFFLINE_RETRY_EVERY", 1)
    net = SimNetwork(blackmagic.studio(), mdns=None)
    await net.start()
    session = aiohttp.ClientSession()
    config = JsonFile(tmp_path / "config.json")
    config.data = {"devices": [{"id": "nmos", "driver": "nmos", "title": "ST 2110", "data": {"host": "nmos"},
                                "options": {"static_hosts": [f"127.0.0.1:{n.port}" for n in net.nodes]}}]}  # fmt: skip
    config.save_now()

    def factory(entry: Entry) -> NmosNetwork:  # so soll Hub._make_driver Netzwerk-Treiber bauen (INTEGRATION.md, Schritt 4)
        return NmosNetwork(session, entry.data, options=entry.options)

    hub = Hub(config, JsonFile(tmp_path / "state.json"), session=session, driver_factory=factory)
    hub.load()
    await hub.start()
    await settle(hub)
    yield hub, net
    await hub.stop()
    await session.close()
    await net.stop()


async def test_registered() -> None:
    assert DRIVERS["nmos"] is NmosNetwork and NmosNetwork.NETWORK and NmosNetwork.PROTOCOL == "st2110"
    assert PROTOCOLS["st2110"].title == "ST 2110"


async def test_snapshot_has_a_third_protocol_group(env) -> None:
    hub, _ = env
    proto = hub.snapshot()["protocols"]["st2110"]
    assert proto["title"] == "ST 2110"
    sources = {s["id"]: s for s in proto["sources"]}
    assert len(sources) == 8
    src = sources[f"SDI In 4@{QUAD}"]
    assert (src["group"], src["channel"], src["live"], src["host"]) == (QUAD, "SDI In 4", True, "127.0.0.1")
    assert src["preview"] == "none"  # keine Vorschau – als Eigenschaft, nicht als Fehler
    dests = {d["id"]: d for d in proto["destinations"]}
    assert len(dests) == 9
    hdmi = dests[HDMI]
    assert (hdmi["name"], hdmi["channel"], hdmi["group"], hdmi["driver"], hdmi["protocol"]) == (
        MINI,
        None,
        MINI,
        "nmos",
        "st2110",
    )
    assert (hdmi["host"], hdmi["web_url"], hdmi["status"], hdmi["available"]) == ("127.0.0.1", None, "no_source", True)
    assert (hdmi["manufacturer"], hdmi["model"]) == ("Blackmagic Design", MINI)
    quad = dests[f"nmos_{QUAD}:SDI Out 3"]
    assert (quad["name"], quad["channel"]) == (f"{QUAD} · SDI Out 3", "SDI Out 3")
    assert hdmi["icon_key"] == "st2110_converter" and quad["icon_key"] == "st2110_multi"


async def test_route_undo_and_status(env) -> None:
    hub, net = env
    event = await hub.route(HDMI, BIDI_IN, origin="test")
    assert (event["protocol"], event["source"], event["previous_source"]) == ("st2110", BIDI_IN, None)
    await settle(hub)
    dest = {d["id"]: d for d in hub.snapshot()["protocols"]["st2110"]["destinations"]}[HDMI]
    assert (dest["current_source"], dest["status"], dest["resolution"], dest["can_undo"]) == (
        BIDI_IN,
        "connected",
        "1920x1080p50",
        True,
    )
    assert net.node(MINI).active("HDMI Out Audio")["master_enable"] is True
    await hub.route(HDMI, f"SDI In 2@{QUAD}")
    await settle(hub)
    assert hub.status()["routes"][HDMI] == f"SDI In 2@{QUAD}"
    await hub.undo(HDMI)
    await settle(hub)
    assert hub.status()["routes"][HDMI] == BIDI_IN
    await hub.undo_last()  # die erste Schaltung zurück → wieder nichts
    await settle(hub)
    assert hub.status()["routes"][HDMI] is None
    assert net.node(MINI).active("HDMI Out Video")["master_enable"] is False


async def test_incompatible_route_is_a_readable_matrix_error(env) -> None:
    hub, net = env
    with pytest.raises(MatrixError) as err:
        await hub.route(f"nmos_{DECK}:Input 1", f"SDI In 4@{QUAD}")
    assert err.value.code == "route_failed" and err.value.status == 502
    assert (
        err.value.message
        == "DeckLink IP/SDI HD · Input 1: passt nicht: Ziel kann Blackmagic IP10 nicht empfangen (nur unkomprimiert)"
    )
    assert net.node(DECK).patches == []


async def test_salvo_preset_lock_and_names(env) -> None:
    hub, net = env
    assert hub.resolve_destination(f"{MINI}").uid == HDMI  # Gerätename genügt bei Geräten mit einem Ausgang
    assert hub.resolve_destination(f"{QUAD} · SDI Out 2").uid == f"nmos_{QUAD}:SDI Out 2"
    assert hub.resolve_source("st2110", BIDI_IN.upper()) == BIDI_IN
    await hub.salvo([(HDMI, BIDI_IN), (f"nmos_{QUAD}:SDI Out 1", BIDI_IN), (f"nmos_{DECK}:Input 2", f"SDI In 1@{QUAD}")])
    await settle(hub)
    preset = hub.snapshot_preset("Probe", [HDMI, f"nmos_{QUAD}:SDI Out 1"])
    assert preset["active"] is True
    await hub.route(HDMI, None)
    await settle(hub)
    assert hub.preset_view(hub.get_preset("Probe"))["active"] is False
    await hub.recall_preset("Probe")
    await settle(hub)
    assert hub.status()["presets"]["probe"] is True
    hub.set_lock(HDMI, True)
    with pytest.raises(MatrixError) as err:
        await hub.route(HDMI, None)
    assert err.value.code == "locked"
    choices = hub.choices()
    assert {"id": HDMI, "name": MINI, "protocol": "st2110", "protected": False} in choices["destinations"]
    assert {"id": BIDI_IN, "name": BIDI_IN, "protocol": "st2110"} in choices["sources"]


async def test_offline_device(env) -> None:
    hub, net = env
    await hub.route(HDMI, BIDI_IN)
    await settle(hub)
    net.node(BIDI).down = True
    await settle(hub)
    proto = hub.snapshot()["protocols"]["st2110"]
    dests = {d["id"]: d for d in proto["destinations"]}
    assert dests[f"nmos_{BIDI}:SDI Out"]["status"] == "offline" and dests[f"nmos_{BIDI}:SDI Out"]["available"] is False
    assert dests[HDMI]["current_source"] == BIDI_IN and dests[HDMI]["current_source_live"] is False
    source = {s["id"]: s for s in proto["sources"]}[BIDI_IN]
    assert source["live"] is False and source["last_seen"]  # bleibt als "offline" in der Liste (Haltezeit)
    with pytest.raises(MatrixError, match="ist offline"):
        await hub.route(f"nmos_{BIDI}:SDI Out", f"SDI In 1@{QUAD}")
    net.node(BIDI).down = False
    await settle(hub)
    assert {d["id"]: d for d in hub.snapshot()["protocols"]["st2110"]["destinations"]}[f"nmos_{BIDI}:SDI Out"][
        "available"
    ] is True


async def test_device_overview(env) -> None:
    hub, _ = env
    (entry,) = hub.devices()
    assert (entry["driver"], entry["protocol"], entry["network"], entry["online"]) == ("nmos", "st2110", True, True)
    subs = {d["name"]: d for d in entry["devices"]}
    assert len(subs) == 5
    assert (subs[QUAD]["tx_count"], subs[QUAD]["rx_count"], subs[QUAD]["host"], subs[QUAD]["online"]) == (4, 4, "127.0.0.1", True)
    assert subs[QUAD]["manufacturer"] == "Blackmagic Design" and subs[QUAD]["icon_key"] == "st2110_multi"
    assert subs[DECK]["icon_key"] == "st2110_card"


# --------------------------------------------------- zweiter Controller (Bedienfeld am Switch, Videohub-Pult …)
async def foreign_take(net: SimNetwork, dest: str, port: str, source: str | None, source_port: str | None = None) -> None:
    """So schaltet ein anderer NMOS-Controller: über HTTP an den Geräten, an der Kreuzschiene vorbei."""
    from nmos_sim.controller import ForeignController

    async with aiohttp.ClientSession() as session:
        await ForeignController(session).take(net.node(dest).url, port, net.node(source).url if source else None, source_port)


async def test_foreign_switch_is_shown_logged_and_undo_stays_sane(env) -> None:
    hub, net = env
    seen: list[dict] = []
    hub.add_event_listener(seen.append)
    await hub.route(HDMI, BIDI_IN, origin="panel")
    await settle(hub)
    revision = hub.revision

    await foreign_take(net, MINI, "HDMI Out", QUAD, "SDI In 2")  # jemand schaltet am Switch
    await hub.pollers["nmos"].refresh()  # eine einzige Abfrage genügt
    assert hub.status()["routes"][HDMI] == f"SDI In 2@{QUAD}" and hub.revision > revision
    event = hub.events[0]
    assert (event["origin"], event["source"], event["previous_source"]) == ("extern", f"SDI In 2@{QUAD}", BIDI_IN)
    assert [e["origin"] for e in seen] == ["panel", "extern"]  # Companion/MCP bekommen dasselbe Ereignis
    dest = {d["id"]: d for d in hub.snapshot()["protocols"]["st2110"]["destinations"]}[HDMI]
    assert dest["current_source"] == f"SDI In 2@{QUAD}" and dest["can_undo"] is True

    # „letzte Aktion rückgängig“ springt nicht über die fremde Schaltung hinweg auf einen veralteten Stand …
    with pytest.raises(MatrixError, match="nichts rückgängig"):
        await hub.undo_last()
    assert hub.status()["routes"][HDMI] == f"SDI In 2@{QUAD}"
    # … „Rückgängig“ am Ziel führt zum Zustand vor der fremden Schaltung, ein zweites Mal zu dem davor
    await hub.undo(HDMI)
    await settle(hub)
    assert hub.status()["routes"][HDMI] == BIDI_IN
    await hub.undo(HDMI)
    await settle(hub)
    assert hub.status()["routes"][HDMI] is None
    assert [e["origin"] for e in seen] == ["panel", "extern", "undo", "undo"]  # eigene Schaltungen gelten nie als fremd


async def test_foreign_switch_leaves_presets_and_other_destinations_alone(env) -> None:
    hub, net = env
    bidi_out = f"nmos_{BIDI}:SDI Out"
    await hub.salvo([(HDMI, BIDI_IN), (bidi_out, f"SDI In 1@{QUAD}")])
    await settle(hub)
    hub.snapshot_preset("Show", [HDMI, bidi_out])
    assert hub.status()["presets"]["show"] is True
    await foreign_take(net, MINI, "HDMI Out", None)  # am Switch getrennt
    await settle(hub)
    assert hub.status()["routes"][HDMI] is None and hub.events[0]["origin"] == "extern"
    assert hub.status()["presets"]["show"] is False  # das Preset selbst bleibt, es ist nur nicht mehr aktiv
    await hub.undo_last()  # nimmt von der Salve nur noch zurück, was niemand sonst angefasst hat
    await settle(hub)
    routes = hub.status()["routes"]
    assert routes[bidi_out] is None and routes[HDMI] is None
    await hub.recall_preset("Show")  # und das Preset stellt beides wieder her
    await settle(hub)
    assert hub.status()["routes"][HDMI] == BIDI_IN and hub.status()["routes"][bidi_out] == f"SDI In 1@{QUAD}"
    assert hub.status()["presets"]["show"] is True
