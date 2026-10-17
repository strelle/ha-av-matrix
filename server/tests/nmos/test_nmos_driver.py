"""Der Treiber gegen die Simulation (echtes HTTP auf 127.0.0.1): finden, Modell, schalten, trennen, Fehler."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from avmatrix.drivers import nmos as nmos_driver
from avmatrix.drivers.base import RouteFailed
from avmatrix.drivers.nmos import NmosNetwork
from avmatrix.models import ConnectionState
from avmatrix.protocols import nmos
from nmos_sim import blackmagic
from nmos_sim.network import SimNetwork
from nmos_sim.node import IP10, Port, Spec, Video

from .conftest import BIDI, DECK, MINI, PRES, QUAD, MakeNet, driver_for

HDMI = f"{MINI}:HDMI Out"
BIDI_OUT = f"{BIDI}:SDI Out"
BIDI_IN = f"SDI In@{BIDI}"
PC = f"PC In@{PRES}"


def quad_in(n: int) -> str:
    return f"SDI In {n}@{QUAD}"


async def poll(driver: NmosNetwork, times: int = 1):
    result = None
    for _ in range(times):
        result = await driver.async_poll()
    return result


# ---------------------------------------------------------------------- Modell
async def test_five_devices_become_sources_and_destinations(studio) -> None:
    net, driver = studio
    result = await poll(driver)
    assert [s.name for s in result.sources] == [
        quad_in(1), quad_in(2), quad_in(3), quad_in(4), BIDI_IN, PC, f"Output 1@{DECK}", f"Output 2@{DECK}",
    ]  # fmt: skip
    assert sorted(result.destinations) == sorted(
        [f"{QUAD}:SDI Out {n}" for n in (1, 2, 3, 4)]
        + [BIDI_OUT, HDMI, f"{PRES}:Program Out", f"{DECK}:Input 1", f"{DECK}:Input 2"]
    )
    assert all(
        state.current is None and state.status.state is ConnectionState.NO_SOURCE for state in result.destinations.values()
    )
    assert all(s.address and s.address.startswith("127.0.0.1:") for s in result.sources)


async def test_multi_channel_device_has_four_named_inputs_and_outputs(studio) -> None:
    _, driver = studio
    infos = [d for d in driver.destinations() if d.device == QUAD]
    assert [d.name for d in infos] == ["SDI Out 1", "SDI Out 2", "SDI Out 3", "SDI Out 4"]
    assert list(driver.device_for(QUAD).sources) == ["SDI In 1", "SDI In 2", "SDI In 3", "SDI In 4"]
    # ein Gerät mit nur einem Ausgang braucht keinen Kanalnamen: das Ziel heißt wie das Gerät
    assert [d.name for d in driver.destinations() if d.device == MINI] == [None]


async def test_four_channel_device_as_four_nodes_gets_stable_distinct_names(make_net: MakeNet, session) -> None:
    net = await make_net(blackmagic.converter_4x12g_as_four_nodes())
    names = []
    for order in (net.nodes, list(reversed(net.nodes))):  # Reihenfolge des Findens darf nichts ändern
        driver = driver_for(session, static_hosts=[f"127.0.0.1:{n.port}" for n in order])
        await poll(driver)
        names.append(sorted(driver.devices))
    assert names[0] == names[1] == [f"2110-converter-4x12g-{n}" for n in (1, 2, 3, 4)]
    assert sorted(d.id for d in driver.destinations()) == [f"2110-converter-4x12g-{n}:SDI Out {n}" for n in (1, 2, 3, 4)]


async def test_device_metadata(studio) -> None:
    _, driver = studio
    types = {n.name: (n.manufacturer, n.model, n.device_type, n.icon_key) for n in driver.visible_devices()}
    assert types[MINI] == ("Blackmagic Design", MINI, "converter", "st2110_converter")
    assert types[PRES] == ("Blackmagic Design", PRES, "presentation", "st2110_presentation")
    assert types[BIDI] == ("Blackmagic Design", BIDI, "converter", "st2110_converter")
    assert types[QUAD] == ("Blackmagic Design", QUAD, "multi", "st2110_multi")
    assert types[DECK] == ("Blackmagic Design", "Blackmagic DeckLink IP/SDI HD", "card", "st2110_card")
    assert driver.destination_host(HDMI) == "127.0.0.1"
    assert driver.device_for(MINI).ptp == {
        "locked": True,
        "grandmaster": "7c-2e-0d-ff-fe-00-00-01",
        "traceable": False,
        "is_grandmaster": False,
    }
    info = await driver.async_get_info()
    assert info.model == "ST-2110-Netzwerk (NMOS)"


async def test_web_url_only_if_the_device_really_serves_a_page(make_net: MakeNet, session, monkeypatch) -> None:
    """Blackmagic-Konverter haben keine dokumentierte Weboberfläche → None. Geprüft wird, nicht geraten."""
    net = await make_net([blackmagic.mini_ip_to_hdmi()])
    driver = driver_for(session, net)
    await poll(driver)
    assert driver.destination_url(HDMI) is None and driver.configuration_url is None

    spec = blackmagic.mini_bidirect_12g("Gerät mit Web")
    spec.quirks.add("web_ui")
    net = await make_net([spec])
    real_get = session.get
    # die Prüfung fragt Port 80; in der Simulation liegt die "Weboberfläche" auf dem Port des Nodes
    monkeypatch.setattr(
        session, "get", lambda url, **kw: real_get(url.replace("http://127.0.0.1/", f"{net.nodes[0].url}/"), **kw)
    )
    driver = driver_for(session, net)
    await poll(driver)
    assert driver.destination_url("Gerät mit Web:SDI Out") == "http://127.0.0.1/"


async def test_source_info_says_no_preview_and_compressed(studio) -> None:
    _, driver = studio
    ip10 = driver.source_info(quad_in(4))
    assert ip10["preview"] == "none" and "keine Vorschau" in ip10["preview_reason"]
    assert ip10["compressed"] is True and ip10["format"] == "3840x2160p60 · Blackmagic IP10"
    assert ip10["essences"] == ["video", "audio", "data"] and ip10["grouped_by"] == "bcp-002-01"
    raw = driver.source_info(quad_in(1))
    assert raw["compressed"] is False and raw["audio_format"] == "48 kHz · 16 Kanäle"
    assert driver.source_info("gibt es nicht@x")["preview"] == "none"


async def test_grouping_without_hints_uses_labels(make_net: MakeNet, session) -> None:
    spec = blackmagic.converter_4x12g("Quad ohne Tags")
    spec.quirks.add("no_grouphint")
    net = await make_net([spec])
    driver = driver_for(session, net)
    await poll(driver)
    node = driver.device_for("Quad ohne Tags")
    assert list(node.sources) == [f"SDI In {n} Video" for n in (1, 2, 3, 4)]
    assert all(g.kinds() == ["video", "audio", "data"] and not g.hinted for g in node.sources.values())
    await driver.async_route("Quad ohne Tags:SDI Out 2 Video", "SDI In 3 Video@Quad ohne Tags")
    assert net.nodes[0].active("SDI Out 2 Audio")["sender_id"] == net.nodes[0].sender("SDI In 3 Audio")["id"]


# -------------------------------------------------------------------- Schalten
async def test_route_switches_video_audio_and_anc_together(studio) -> None:
    net, driver = studio
    await driver.async_route(HDMI, BIDI_IN)
    mini, bidi = net.node(MINI), net.node(BIDI)
    for essence in ("Video", "Audio", "ANC"):
        active = mini.active(f"HDMI Out {essence}")
        assert active["master_enable"] is True
        assert active["sender_id"] == bidi.sender(f"SDI In {essence}")["id"]
        assert active["transport_file"]["data"] == bidi.sdp[active["sender_id"]]  # das SDP des Senders, unverändert
        assert active["transport_file"]["type"] == "application/sdp"
    # genau ein PATCH je Ebene, mit sofortiger Aktivierung
    assert [(label, body["activation"]) for label, body in mini.patches] == [
        (f"HDMI Out {e}", {"mode": "activate_immediate"}) for e in ("Video", "Audio", "ANC")
    ]
    result = await poll(driver)
    state = result.destinations[HDMI]
    assert state.current == BIDI_IN
    assert state.status.state is ConnectionState.CONNECTED and state.status.connected is True
    assert state.status.resolution == "1920x1080p50"
    assert state.status.extra["layers"] == {"video": BIDI_IN, "audio": BIDI_IN, "data": BIDI_IN}
    assert state.status.extra["breakaway"] is False and state.status.extra["preview"] == "none"


async def test_node_reached_over_an_unadvertised_control_port_is_switched_there(make_net: MakeNet, session) -> None:
    """Blackmagic 4x12G: its control port serves the NMOS nodes of the four media ports, but every node names only
    its media address (10.0.0.5x) in ``self``, ``controls`` and ``manifest_href`` – unreachable from the control
    network. Reached by hand over the control port, the driver must switch and fetch SDPs over that port too."""
    specs = blackmagic.studio()
    for spec in specs:
        spec.advertise_host = "10.255.255.1"  # nirgends erreichbar
    net = await make_net(specs)
    driver = driver_for(session, net, timeout=1.0)
    result = await poll(driver, 2)
    assert HDMI in result.destinations and BIDI_IN in [s.name for s in result.sources]
    await driver.async_route(HDMI, BIDI_IN)
    mini, bidi = net.node(MINI), net.node(BIDI)
    for essence in ("Video", "Audio", "ANC"):
        active = mini.active(f"HDMI Out {essence}")
        assert active["sender_id"] == bidi.sender(f"SDI In {essence}")["id"]
        assert active["transport_file"]["data"] == bidi.sdp[active["sender_id"]]
    assert (await poll(driver)).destinations[HDMI].current == BIDI_IN
    assert all(node.advertised == {"10.255.255.1"} and node.host == "127.0.0.1" for node in driver.devices.values())


async def test_route_switches_inactive_senders_on(studio) -> None:
    """Blackmagic-Sender senden erst nach ``master_enable`` (Forum) – der Treiber schaltet sie mit ein."""
    net, driver = studio
    bidi = net.node(BIDI)
    assert bidi.active("SDI In Video")["master_enable"] is False
    await driver.async_route(HDMI, BIDI_IN)
    assert all(bidi.active(f"SDI In {e}")["master_enable"] for e in ("Video", "Audio", "ANC"))
    assert [name for name, _ in driver.switched_on] == [BIDI] * 3


async def test_enable_senders_can_be_turned_off(make_net: MakeNet, session) -> None:
    net = await make_net()
    driver = driver_for(session, net, enable_senders=False)
    await poll(driver)
    await driver.async_route(HDMI, BIDI_IN)
    assert net.node(BIDI).active("SDI In Video")["master_enable"] is False
    state = (await poll(driver)).destinations[HDMI]
    assert state.current == BIDI_IN and state.status.state is ConnectionState.SOURCE_LOST
    assert "ausgeschaltet" in state.status.extra["detail"]


async def test_disconnect(studio) -> None:
    net, driver = studio
    await driver.async_route(HDMI, BIDI_IN)
    await driver.async_route(HDMI, None)
    for essence in ("Video", "Audio", "ANC"):
        active = net.node(MINI).active(f"HDMI Out {essence}")
        assert active["master_enable"] is False and active["sender_id"] is None
    state = (await poll(driver)).destinations[HDMI]
    assert state.current is None and state.status.state is ConnectionState.NO_SOURCE


async def test_restore_previous_source_for_undo(studio) -> None:
    """Undo im Kern = die vorherige Quelle erneut schalten: A → B → zurück zu A → zurück zu „nichts“."""
    net, driver = studio
    await poll(driver)
    history = [await driver.async_get_current(HDMI)]
    for source in (BIDI_IN, quad_in(2)):
        await driver.async_route(HDMI, source)
        await poll(driver)
        history.append(await driver.async_get_current(HDMI))
    assert history == [None, BIDI_IN, quad_in(2)]
    await driver.async_route(HDMI, history[1])
    await poll(driver)
    assert await driver.async_get_current(HDMI) == BIDI_IN
    assert net.node(MINI).active("HDMI Out Audio")["sender_id"] == net.node(BIDI).sender("SDI In Audio")["id"]
    await driver.async_route(HDMI, history[0])
    await poll(driver)
    assert await driver.async_get_current(HDMI) is None


async def test_state_follows_changes_made_by_another_controller(studio) -> None:
    net, driver = studio
    sender = net.node(QUAD).sender("SDI In 1 Video")["id"]
    net.node(MINI).connect("HDMI Out Video", sender)
    state = (await poll(driver)).destinations[HDMI]
    assert state.current == quad_in(1)
    assert state.status.extra["partial"] is True  # nur das Bild wurde von außen verbunden
    assert state.status.extra["layers"] == {"video": quad_in(1), "audio": None, "data": None}


async def test_connection_to_unknown_sender_is_shown_and_can_be_restored(studio) -> None:
    """Steht ein Empfänger auf einem Sender, den niemand im Netz anbietet, bleibt das sichtbar – und Undo führt dorthin zurück."""
    net, driver = studio
    foreign = "99999999-9999-4999-8999-999999999999"
    sdp = "v=0\r\no=- 1 1 IN IP4 192.0.2.99\r\ns=Fremd\r\nt=0 0\r\nm=video 5004 RTP/AVP 96\r\nc=IN IP4 239.9.9.9/64\r\na=rtpmap:96 raw/90000\r\n"
    net.node(MINI).connect("HDMI Out Video", foreign, sdp)
    state = (await poll(driver, 2)).destinations[HDMI]
    assert state.current == f"sender:{foreign}"
    assert state.status.connected is None and state.status.state is None  # ob er sendet, wissen wir nicht
    await driver.async_route(HDMI, BIDI_IN)
    await poll(driver)
    await driver.async_route(HDMI, f"sender:{foreign}")
    active = net.node(MINI).active("HDMI Out Video")
    assert active["sender_id"] == foreign and active["transport_file"]["data"] == sdp and active["master_enable"] is True

    with pytest.raises(RouteFailed, match="nicht wiederherstellen"):
        await driver.async_route(BIDI_OUT, "sender:12345678-1234-4234-8234-123456789012")


async def test_receiver_set_up_with_bare_sdp_is_external(studio) -> None:
    net, driver = studio
    sdp = "v=0\r\ns=Manuell\r\nm=video 5004 RTP/AVP 96\r\nc=IN IP4 239.9.9.9/64\r\na=rtpmap:96 raw/90000\r\n"
    net.node(MINI).connect("HDMI Out Video", None, sdp)
    await poll(driver, 2)
    rid = net.node(MINI).receiver("HDMI Out Video")["id"]
    assert await driver.async_get_current(HDMI) == f"ext:{rid}"
    await driver.async_route(HDMI, None)
    await driver.async_route(HDMI, f"ext:{rid}")
    active = net.node(MINI).active("HDMI Out Video")
    assert (active["sender_id"], active["master_enable"], active["transport_file"]["data"]) == (None, True, sdp)


# ------------------------------------------------------ getrennt / unvollständig
async def test_audio_breakaway(make_net: MakeNet, session) -> None:
    net = await make_net()
    driver = driver_for(session, net, audio_breakaway=True)
    await poll(driver)
    audio_dest = f"{HDMI}/audio"
    infos = {d.id: d.name for d in driver.destinations()}
    assert infos[audio_dest] == "HDMI Out · nur Ton" and infos[HDMI] is None
    await driver.async_route(HDMI, BIDI_IN)
    await driver.async_route(audio_dest, PC)  # Ton aus dem Präsentationswandler unter das Bild vom BiDirect
    mini = net.node(MINI)
    assert mini.active("HDMI Out Video")["sender_id"] == net.node(BIDI).sender("SDI In Video")["id"]
    assert mini.active("HDMI Out Audio")["sender_id"] == net.node(PRES).sender("PC In Audio")["id"]
    result = await poll(driver)
    assert result.destinations[HDMI].current == BIDI_IN
    assert result.destinations[HDMI].status.extra["breakaway"] is True
    assert result.destinations[HDMI].status.extra["layers"]["audio"] == PC
    assert result.destinations[audio_dest].current == PC
    assert result.destinations[audio_dest].status.resolution == "48 kHz"
    # Ton allein trennen lässt das Bild stehen
    await driver.async_route(audio_dest, None)
    assert mini.active("HDMI Out Video")["master_enable"] is True and mini.active("HDMI Out Audio")["master_enable"] is False
    # das Hauptziel neu schalten nimmt den Ton wieder mit
    await driver.async_route(HDMI, quad_in(1))
    assert mini.active("HDMI Out Audio")["sender_id"] == net.node(QUAD).sender("SDI In 1 Audio")["id"]


async def test_source_without_audio_disconnects_audio_layer(make_net: MakeNet, session) -> None:
    silent = Spec("Stumme Kamera", ports=[Port("Out", "tx", audio_channels=0, anc=False)])
    net = await make_net([blackmagic.mini_ip_to_hdmi(), blackmagic.mini_bidirect_12g(), silent])
    driver = driver_for(session, net)
    await poll(driver)
    await driver.async_route(HDMI, BIDI_IN)
    steps = driver.plan(HDMI, "Out@Stumme Kamera")
    assert [(s.layer[0], s.sender is not None, s.note) for s in steps] == [
        ("video", True, None), ("audio", False, "Quelle hat keinen Ton"), ("data", False, "Quelle hat keine Zusatzdaten"),
    ]  # fmt: skip
    await driver.async_route(HDMI, "Out@Stumme Kamera")
    mini = net.node(MINI)
    assert mini.active("HDMI Out Video")["master_enable"] is True
    assert mini.active("HDMI Out Audio")["master_enable"] is False  # nicht den Ton der alten Quelle stehen lassen
    state = (await poll(driver)).destinations[HDMI]
    assert state.current == "Out@Stumme Kamera" and state.status.extra["partial"] is True


async def test_audio_only_source_cannot_go_to_a_video_destination(make_net: MakeNet, session) -> None:
    mics = Spec("Stagebox", ports=[Port("Mics", "tx", video=None, anc=False)])
    net = await make_net([blackmagic.mini_ip_to_hdmi(), mics])
    driver = driver_for(session, net, audio_breakaway=True)
    await poll(driver)
    with pytest.raises(RouteFailed, match="Quelle hat kein Bild"):
        await driver.async_route(HDMI, "Mics@Stagebox")
    assert net.node(MINI).patches == []
    await driver.async_route(f"{HDMI}/audio", "Mics@Stagebox")  # auf das Ton-Ziel geht es
    assert net.node(MINI).active("HDMI Out Audio")["master_enable"] is True


# ------------------------------------------------------------------- Ablehnung
async def test_incompatible_format_is_refused_before_anything_is_sent(studio) -> None:
    net, driver = studio
    deck = f"{DECK}:Input 1"
    with pytest.raises(RouteFailed, match="Ziel kann Blackmagic IP10 nicht empfangen"):
        await driver.async_route(deck, quad_in(4))  # 2160p60 mit IP10 auf die HD-Karte
    with pytest.raises(RouteFailed, match="Auflösung"):
        await driver.async_route(deck, quad_in(3))  # 2160p50 unkomprimiert auf die HD-Karte
    assert net.node(DECK).patches == [] and net.node(QUAD).patches == []  # auch kein Sender wurde eingeschaltet
    await driver.async_route(deck, quad_in(1))  # 1080p50 passt
    await driver.async_route(HDMI, quad_in(4))  # und IP10 auf ein Gerät, das IP10 kann
    assert net.node(MINI).active("HDMI Out Video")["sender_id"] == net.node(QUAD).sender("SDI In 4 Video")["id"]


async def test_incompatible_audio_is_left_out_with_a_reason(make_net: MakeNet, session) -> None:
    stereo = Spec("Stereo-Monitor", ports=[Port("Out", "rx", max_audio_channels=2)])
    net = await make_net([stereo, blackmagic.mini_bidirect_12g()])
    driver = driver_for(session, net)
    await poll(driver)
    steps = driver.plan("Stereo-Monitor:Out", BIDI_IN)
    assert steps[0].sender is not None and steps[1].sender is None and "Kanalzahl" in steps[1].note
    await driver.async_route("Stereo-Monitor:Out", BIDI_IN)
    assert net.node("Stereo-Monitor").active("Out Video")["master_enable"] is True
    assert net.node("Stereo-Monitor").active("Out Audio")["master_enable"] is False


async def test_check_can_be_disabled_then_the_device_decides(make_net: MakeNet, session) -> None:
    net = await make_net()
    driver = driver_for(session, net, check_compat=False)
    await poll(driver)
    await driver.async_route(f"{DECK}:Input 1", quad_in(1))  # danach ist bekannt, wie das Gerät Verbindungen annimmt
    await driver.async_route(f"{DECK}:Input 1", None)
    with pytest.raises(RouteFailed) as err:
        await driver.async_route(f"{DECK}:Input 1", quad_in(4))
    assert "lehnt ab (400)" in str(err.value) and "unsupported media type" in str(err.value)
    assert net.node(DECK).active("Input 1 Video")["master_enable"] is False


async def test_unknown_names(studio) -> None:
    _, driver = studio
    for dest, source, words in [
        ("Gibtsnicht:Out", BIDI_IN, "unbekanntes ST-2110-Gerät"),
        (f"{MINI}:Falsch", BIDI_IN, "hat keinen Ausgang"),
        ("ohne-doppelpunkt", BIDI_IN, "kein ST-2110-Ziel"),
        (HDMI, "Nix@Nirgends", "ist nicht im Netz"),
        (HDMI, "kein-at", "ist nicht im Netz"),
    ]:
        with pytest.raises(RouteFailed, match=words):
            await driver.async_route(dest, source)
    assert await driver.async_get_current("Gibtsnicht:Out") is None
    assert (await driver.async_get_status("Gibtsnicht:Out")).state is None
    assert driver.destination_host("Gibtsnicht:Out") is None and driver.destination_available("kaputt") is False


# ----------------------------------------------------------- Geräte-Eigenheiten
async def one_device(make_net: MakeNet, session, *quirks: str, delay: float = 0.0, timeout: float = 3.0, **options):
    target = blackmagic.mini_ip_to_hdmi()
    target.quirks |= set(quirks)
    target.delay = delay
    net = await make_net([target, blackmagic.mini_bidirect_12g()])
    driver = driver_for(session, net, timeout=timeout, **options)
    await poll(driver)
    return net, driver


async def test_device_refuses(make_net: MakeNet, session) -> None:
    net, driver = await one_device(make_net, session, "reject")
    with pytest.raises(RouteFailed, match=r"lehnt ab \(500\): internal error"):
        await driver.async_route(HDMI, BIDI_IN)
    assert (await poll(driver)).destinations[HDMI].current is None
    # der für diesen Versuch eingeschaltete Sender ist wieder aus: nach einem Fehlschlag bleibt nichts verändert zurück
    assert net.node(BIDI).active("SDI In Video")["master_enable"] is False and driver.switched_on == []


async def test_device_locked_by_another_controller(make_net: MakeNet, session) -> None:
    net, driver = await one_device(make_net, session, "locked", enable_senders=False)
    with pytest.raises(RouteFailed, match="gesperrt"):
        await driver.async_route(HDMI, BIDI_IN)
    assert len(net.node(MINI).patches) == 1  # bei 423 wird nicht weiterprobiert


async def test_timeout(make_net: MakeNet, session) -> None:
    net, driver = await one_device(make_net, session)
    net.node(MINI).spec.quirks.add("slow")
    net.node(MINI).spec.delay = 1.0
    driver.timeout = aiohttp.ClientTimeout(total=0.2)
    with pytest.raises(RouteFailed, match="Zeitüberschreitung"):
        await driver.async_route(HDMI, BIDI_IN)


async def test_device_accepts_but_never_activates(make_net: MakeNet, session) -> None:
    net, driver = await one_device(make_net, session, "ignore")
    with pytest.raises(RouteFailed, match="nicht aktiviert"):
        await driver.async_route(HDMI, BIDI_IN)
    # alle drei Arten wurden versucht (SDP, Parameter, nur Kennung)
    kinds = [("transport_file" in body, "transport_params" in body) for _, body in net.node(MINI).patches]
    assert kinds == [(True, False), (False, True), (False, False)]


async def test_all_or_nothing_when_a_later_layer_fails(make_net: MakeNet, session) -> None:
    """Bild angenommen, Ton abgelehnt → das Bild wird auf den alten Stand zurückgestellt."""
    net, driver = await one_device(make_net, session)
    await driver.async_route(HDMI, BIDI_IN)
    spec = blackmagic.converter_4x12g()
    other = SimNetwork([spec], mdns=None)
    await other.start()
    try:
        driver.add_host("127.0.0.1", other.nodes[0].port)
        await poll(driver)
        net.node(MINI).spec.quirks.add("audio_reject")
        with pytest.raises(RouteFailed, match="audio receiver is not available.*zurückgestellt"):
            await driver.async_route(HDMI, quad_in(1))
        mini = net.node(MINI)
        assert mini.active("HDMI Out Video")["sender_id"] == net.node(BIDI).sender("SDI In Video")["id"]
        assert mini.active("HDMI Out Audio")["sender_id"] == net.node(BIDI).sender("SDI In Audio")["id"]
        assert (await poll(driver)).destinations[HDMI].current == BIDI_IN
    finally:
        await other.stop()


async def test_receiver_that_only_takes_transport_params(make_net: MakeNet, session) -> None:
    net, driver = await one_device(make_net, session, "params_only")
    await driver.async_route(HDMI, BIDI_IN)
    mini, bidi = net.node(MINI), net.node(BIDI)
    params = mini.active("HDMI Out Video")["transport_params"][0]
    info = nmos.parse_sdp(bidi.sdp[bidi.sender("SDI In Video")["id"]])
    assert (params["multicast_ip"], params["destination_port"], params["source_ip"]) == (info.destination, 16388, "127.0.0.1")
    assert driver.device_for(MINI).patch_mode == "params"
    before = len(mini.patches)
    await driver.async_route(HDMI, BIDI_IN)  # beim nächsten Mal nur noch die Art, die funktioniert hat
    assert len(mini.patches) - before == 3 and all("transport_file" not in body for _, body in mini.patches[before:])


async def test_receiver_that_insists_on_sdp_and_sender_without_manifest(make_net: MakeNet, session) -> None:
    target, source = blackmagic.mini_ip_to_hdmi(), blackmagic.mini_bidirect_12g()
    target.quirks.add("sdp_required")
    source.quirks.add("no_manifest")  # SDP nur über IS-05 /transportfile
    net = await make_net([target, source])
    driver = driver_for(session, net)
    await poll(driver)
    await driver.async_route(HDMI, BIDI_IN)
    assert net.node(MINI).active("HDMI Out Video")["transport_file"]["data"].startswith("v=0")
    assert driver.device_for(MINI).patch_mode == "sdp"


async def test_is04_subscription_that_lags_behind(make_net: MakeNet, session) -> None:
    """Zeigt IS-04 den Schaltzustand nicht, liest der Treiber ihn über IS-05 – und merkt sich das."""
    net, driver = await one_device(make_net, session, "stale_is04")
    await driver.async_route(HDMI, BIDI_IN)
    result = await poll(driver)
    assert result.destinations[HDMI].current == BIDI_IN
    assert driver.device_for(MINI).is04_unreliable is True
    net.node(MINI).connect("HDMI Out Video", None)  # jemand anderes trennt; IS-04 zeigt es wieder nicht
    assert (await poll(driver)).destinations[HDMI].current is None


async def test_connection_api_on_its_own_port(make_net: MakeNet, session) -> None:
    net, driver = await one_device(make_net, session, "split_ports")
    assert net.node(MINI).connection_port != net.node(MINI).port
    await driver.async_route(HDMI, BIDI_IN)
    assert net.node(MINI).active("HDMI Out Video")["master_enable"] is True


async def test_device_without_connection_api(make_net: MakeNet, session, monkeypatch) -> None:
    net, driver = await one_device(make_net, session)
    for device in driver.device_for(MINI).data.devices.values():
        device.connection_href = None
    with pytest.raises(RouteFailed, match="keine Schaltschnittstelle"):
        await driver.async_route(HDMI, BIDI_IN)


# --------------------------------------------------------------------- Offline
async def test_node_goes_offline_and_comes_back(studio, monkeypatch) -> None:
    net, driver = studio
    monkeypatch.setattr(nmos_driver, "OFFLINE_RETRY_EVERY", 1)
    await driver.async_route(HDMI, BIDI_IN)
    await poll(driver)
    net.node(BIDI).down = True
    result = await poll(driver)  # ein verlorener Abruf macht noch kein "offline"
    assert driver.device_for(BIDI).online is True
    result = await poll(driver)
    node = driver.device_for(BIDI)
    assert node.online is False and node.last_error
    assert BIDI_IN not in [s.name for s in result.sources]  # die Quelle fällt aus der Liste der sendenden
    assert driver.destination_available(BIDI_OUT) is False and BIDI_OUT in result.destinations  # das Ziel bleibt, als offline
    assert driver.destination_available(HDMI) is True
    state = result.destinations[HDMI]
    assert state.current == BIDI_IN and state.status.state is ConnectionState.SOURCE_LOST
    assert state.status.extra["detail"] == f"{BIDI} ist offline"
    with pytest.raises(RouteFailed, match="ist offline"):
        await driver.async_route(BIDI_OUT, quad_in(1))
    with pytest.raises(RouteFailed, match="ist offline"):
        await driver.async_route(f"{PRES}:Program Out", BIDI_IN)
    net.node(BIDI).down = False
    result = await poll(driver)
    assert driver.device_for(BIDI).online is True and BIDI_IN in [s.name for s in result.sources]
    assert result.destinations[HDMI].status.state is ConnectionState.CONNECTED


async def test_offline_nodes_are_retried_rarely(studio) -> None:
    net, driver = studio
    net.node(DECK).down = True
    await poll(driver, 2)
    assert driver.device_for(DECK).online is False
    before = net.node(DECK).requests
    await poll(driver, 8)
    assert (
        net.node(DECK).requests - before <= 4
    )  # zwei Versuche in acht Abfragen (aiohttp wiederholt einen abgebrochenen GET einmal)


async def test_unreachable_static_host_is_harmless(session) -> None:
    driver = driver_for(session, static_hosts=["127.0.0.1:9"])  # dort hört niemand
    result = await poll(driver, 2)
    assert result.sources == [] and result.destinations == {} and driver.devices == {}


async def test_dead_address_is_retried_with_growing_pauses(make_net: MakeNet, session, monkeypatch) -> None:
    """Eine Adresse, die nie antwortet, darf nicht jede Abfrage aufhalten: Versuche bei Abfrage 1, 2, 4, 8, 16 …"""
    net = await make_net([blackmagic.mini_ip_to_hdmi()])
    driver = driver_for(session, net, static_hosts=[f"127.0.0.1:{net.nodes[0].port}", "127.0.0.1:9"])
    tried: list[int] = []
    identify = driver._identify

    async def spy(host, port, info):
        if port == 9:
            tried.append(driver._polls)
        await identify(host, port, info)

    monkeypatch.setattr(driver, "_identify", spy)
    await poll(driver, 20)
    assert tried == [1, 2, 4, 8, 16] and len(driver.devices) == 1
    await driver.async_refresh_sources()  # „Quellen neu einlesen“ versucht es sofort wieder
    await poll(driver)
    assert tried[-1] == 21


async def test_garbage_answers_do_not_break_the_poll(make_net: MakeNet, session, monkeypatch) -> None:
    net = await make_net([blackmagic.mini_ip_to_hdmi(), blackmagic.mini_bidirect_12g()])
    driver = driver_for(session, net)
    await poll(driver)
    mini = net.node(MINI)
    monkeypatch.setattr(mini, "_collection", lambda what: {"x": {"das": "ist kein Receiver"}} if what == "receivers" else None)
    result = await poll(driver)  # /receivers liefert Unsinn: Zustand bleibt, nichts stürzt ab
    assert HDMI in result.destinations and driver.device_for(MINI).full_due is True
    result = await poll(driver, 2)  # jetzt scheitert der volle Abruf (andere Listen: 404) → offline, der Rest läuft
    assert driver.device_for(MINI).online is False and driver.device_for(BIDI).online is True
    assert BIDI_IN in [s.name for s in result.sources]


async def test_host_that_is_not_nmos_is_ignored(session) -> None:
    from aiohttp import web

    async def printer(_: web.Request) -> web.Response:
        return web.Response(text="<html>Drucker</html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/{tail:.*}", printer)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        driver = driver_for(session, static_hosts=[f"127.0.0.1:{port}"])
        await poll(driver, 2)
        assert driver.devices == {}
    finally:
        await runner.cleanup()


# ------------------------------------------------------------- Finden / Pflege
async def test_new_node_appears_without_restart(make_net: MakeNet, session) -> None:
    net = await make_net([blackmagic.mini_ip_to_hdmi()])
    driver = driver_for(session, net)
    assert len((await poll(driver)).destinations) == 1
    later = await make_net([blackmagic.mini_bidirect_12g()])
    driver.add_host("127.0.0.1", later.nodes[0].port, {"api_proto": "http"}, mdns=True)
    result = await poll(driver)
    assert sorted(result.destinations) == [BIDI_OUT, HDMI] and [s.name for s in result.sources] == [BIDI_IN]
    assert driver.device_for(BIDI).via_mdns is True and driver.device_for(MINI).static is True


async def test_static_host_without_port_probes_the_usual_ports(make_net: MakeNet, session, monkeypatch) -> None:
    net = await make_net([blackmagic.mini_ip_to_hdmi()])
    monkeypatch.setattr(nmos_driver, "PROBE_PORTS", (9, net.nodes[0].port))
    driver = driver_for(session, static_hosts=["127.0.0.1"])
    await poll(driver)
    assert driver.device_for(MINI).port == net.nodes[0].port
    assert nmos_driver.split_host("http://192.0.2.7:8090/x-nmos") == ("192.0.2.7", 8090)
    assert nmos_driver.split_host("192.0.2.7") == ("192.0.2.7", None)


async def test_registry_lists_nodes(make_net: MakeNet, session) -> None:
    net = await make_net(registry=True)
    driver = driver_for(session, registries=[net.registry.url])
    result = await poll(driver)
    assert len(driver.devices) == 5 and len(result.sources) == 8
    assert all(n.via_registry and not n.static for n in driver.devices.values())
    assert driver.registries[net.registry.url]["version"] == "v1.3"


async def test_registry_that_does_not_answer(session) -> None:
    driver = driver_for(session, registries=["http://127.0.0.1:9"])
    await poll(driver)
    assert driver.registries["http://127.0.0.1:9"]["error"] and driver.devices == {}


async def test_node_demanding_authorization_is_not_touched(make_net: MakeNet, session) -> None:
    net = await make_net([blackmagic.mini_ip_to_hdmi()])
    driver = driver_for(session)
    driver.add_host("127.0.0.1", net.nodes[0].port, {"api_auth": "true"}, mdns=True)
    await poll(driver)
    assert driver.devices == {} and net.nodes[0].requests == 0


async def test_rename_in_setup_tool_renames_device(studio) -> None:
    net, driver = studio
    net.node(MINI).spec.label = "Regie Monitor"
    await driver.async_refresh_sources()
    result = await poll(driver)
    assert "Regie Monitor:HDMI Out" in result.destinations and HDMI not in result.destinations
    assert driver.device_for("Regie Monitor").model == MINI  # die Beschreibung nennt weiter das Produkt


async def test_hidden_devices(make_net: MakeNet, session) -> None:
    net = await make_net()
    driver = driver_for(session, net, hidden_devices=[DECK])
    result = await poll(driver, 2)
    assert not any(DECK in d for d in result.destinations) and not any(DECK in s.name for s in result.sources)


async def test_a_quiet_poll_costs_one_request_per_node(studio) -> None:
    """Keine Dauerlast: zwischen den vollen Abrufen genau ein kleiner GET je Gerät."""
    net, driver = studio
    await poll(driver)
    before = {n.spec.label: n.requests for n in net.nodes}
    await poll(driver, 5)
    assert {n.spec.label: n.requests - before[n.spec.label] for n in net.nodes} == dict.fromkeys(before, 5)


async def test_mdns_change_counter_triggers_full_read(studio) -> None:
    net, driver = studio
    node = driver.device_for(MINI)
    driver.add_host("127.0.0.1", node.port, {"ver_rcv": "1"}, mdns=True)
    await poll(driver)
    assert node.full_due is False
    driver.add_host("127.0.0.1", node.port, {"ver_rcv": "2"}, mdns=True)
    assert node.full_due is True


async def test_snapshot_and_restore_put_everything_back(studio) -> None:
    net, driver = studio
    await driver.async_route(HDMI, BIDI_IN)
    snapshot = await driver.async_snapshot(HDMI)
    await driver.async_route(HDMI, quad_in(2))
    await driver.async_restore(HDMI, snapshot)
    assert net.node(MINI).active("HDMI Out Audio")["sender_id"] == net.node(BIDI).sender("SDI In Audio")["id"]
    await driver.async_set_sender(BIDI, net.node(BIDI).sender("SDI In Video")["id"], False)
    assert net.node(BIDI).active("SDI In Video")["master_enable"] is False


async def test_diagnostics_are_json_and_free_of_surprises(studio) -> None:
    import json

    _, driver = studio
    text = json.dumps(driver.diagnostics())
    assert IP10 in text and "st2110_multi" in text


async def test_concurrent_routes_to_one_device_are_serialised(studio) -> None:
    net, driver = studio
    await asyncio.gather(
        driver.async_route(f"{QUAD}:SDI Out 1", BIDI_IN),
        driver.async_route(f"{QUAD}:SDI Out 2", PC),
        driver.async_route(f"{QUAD}:SDI Out 3", f"Output 1@{DECK}"),
    )
    result = await poll(driver)
    assert [result.destinations[f"{QUAD}:SDI Out {n}"].current for n in (1, 2, 3)] == [BIDI_IN, PC, f"Output 1@{DECK}"]


def test_urls_with_mdns_names_are_pinned_to_the_node_address() -> None:
    pin = nmos_driver._pin_host
    assert (
        pin("http://2110-mini.local:8090/x-nmos/connection/v1.1", "192.0.2.7") == "http://192.0.2.7:8090/x-nmos/connection/v1.1"
    )
    assert pin("http://2110-mini.local/x", "192.0.2.7") == "http://192.0.2.7/x"
    assert pin("http://10.0.0.9:8090/x", "192.0.2.7") == "http://10.0.0.9:8090/x"  # echte Adressen bleiben (zweite Schnittstelle)
    assert pin("kein-url", "192.0.2.7") == "kein-url"


def test_video_helper_media_types() -> None:
    assert Video(codec="ip10").media_type == IP10 and Video().media_type == "video/raw"


# ------------------------------------------------- zweiter Controller, Registry, Switch (Blackmagic Ethernet Switch)
SWITCH = "Blackmagic Ethernet Switch 360P"


async def test_foreign_controller_switch_shows_with_the_next_poll_and_is_reported(studio, session) -> None:
    """Am Switch (oder einem anderen NMOS-Controller) wird umgeschaltet: nächste Abfrage zeigt es, eine Anfrage je Gerät."""
    from nmos_sim.controller import ForeignController

    net, driver = studio
    await poll(driver)
    assert driver.pop_external_changes() == []
    foreign = ForeignController(session)
    done = await foreign.take(net.node(MINI).url, "HDMI Out", net.node(QUAD).url, "SDI In 2")
    assert done == ["HDMI Out Video", "HDMI Out Audio", "HDMI Out ANC"]
    before = net.node(MINI).requests
    state = (await poll(driver)).destinations[HDMI]
    assert net.node(MINI).requests == before + 1  # weiterhin nur die eine kleine Abfrage
    assert state.current == quad_in(2) and state.status.extra["partial"] is False
    assert driver.pop_external_changes() == [(HDMI, None, quad_in(2))]
    assert driver.pop_external_changes() == []

    await foreign.take(net.node(MINI).url, "HDMI Out", None)  # am Switch getrennt
    assert (await poll(driver)).destinations[HDMI].current is None
    assert driver.pop_external_changes() == [(HDMI, quad_in(2), None)]


async def test_own_switches_renames_and_offline_are_not_foreign(studio, monkeypatch) -> None:
    monkeypatch.setattr(nmos_driver, "OFFLINE_RETRY_EVERY", 1)
    net, driver = studio
    await poll(driver)
    await driver.async_route(HDMI, BIDI_IN)
    await poll(driver, 2)
    await driver.async_route(HDMI, None)
    await poll(driver, 2)
    assert driver.pop_external_changes() == []
    await driver.async_route(HDMI, BIDI_IN)
    net.node(BIDI).spec.label = "Kamera 1"  # Quelle umbenannt: andere Kennung, aber niemand hat geschaltet
    await driver.async_refresh_sources()
    assert (await poll(driver, 2)).destinations[HDMI].current == "SDI In@Kamera 1"
    net.node(MINI).down = True
    await poll(driver, 3)
    net.node(MINI).down = False
    await poll(driver, 2)
    assert driver.pop_external_changes() == []


async def test_foreign_switch_is_seen_at_once_when_only_the_version_moves(make_net: MakeNet, session) -> None:
    """Gerät zieht in IS-04 nur den Versionsstempel nach, nicht ``subscription``: IS-05 wird sofort gefragt."""
    spec = blackmagic.mini_ip_to_hdmi()
    spec.quirks.add("stale_subscription")
    net = await make_net([spec, blackmagic.mini_bidirect_12g()])
    driver = driver_for(session, net)
    await poll(driver, 2)
    net.node(MINI).connect("HDMI Out Video", net.node(BIDI).sender("SDI In Video")["id"])
    assert (await poll(driver)).destinations[HDMI].current == BIDI_IN
    assert driver.device_for(MINI).is04_unreliable is True
    assert driver.pop_external_changes() == [(HDMI, None, BIDI_IN)]


async def test_registry_and_peer_to_peer_side_by_side_give_no_duplicates(make_net: MakeNet, session) -> None:
    net = await make_net(blackmagic.studio_with_switch(), registry=True)
    driver = driver_for(session, net, registries=[net.registry.url])  # jede Node doppelt bekannt: direkt und gelistet
    result = await poll(driver, 2)
    assert len(driver.devices) == 6 and len(result.sources) == 9 and len(result.destinations) == 10
    assert all(n.via_registry for n in driver.devices.values())
    assert driver.registries[net.registry.url]["nodes"] == 6 and driver.diagnostics()["pending"] == []
    before = sum(n.requests for n in net.nodes)
    await poll(driver, nmos_driver.REGISTRY_EVERY)  # die Registry wird wieder gefragt: nichts wird neu gelesen
    assert sum(n.requests for n in net.nodes) == before + 6 * nmos_driver.REGISTRY_EVERY
    assert net.registry.requests == 2


async def test_registry_lists_several_addresses_and_one_is_unreachable(make_net: MakeNet, session) -> None:
    """Ein Gerät mit Medien- und Steueranschluss nennt beide Adressen; von hier ist nur eine erreichbar."""
    spec = blackmagic.converter_4x12g()
    spec.extra_endpoints = [("127.0.0.1", 9)]  # dort antwortet nichts
    net = await make_net([spec], registry=True)
    driver = driver_for(session, registries=[net.registry.url])
    await poll(driver, 2)
    node = driver.device_for(QUAD)
    assert node.online and node.port == net.node(QUAD).port and len(node.dests) == 4
    await poll(driver, nmos_driver.REGISTRY_EVERY)
    assert driver.diagnostics()["pending"] == [] and len(driver.devices) == 1


async def test_same_node_under_a_second_address_is_one_device(make_net: MakeNet, session) -> None:
    """mDNS nennt eine Adresse, eine feste Angabe eine andere (zweite Schnittstelle): ein Gerät, kein Hin und Her."""
    net = await make_net([blackmagic.mini_ip_to_hdmi()])
    port = net.node(MINI).port
    driver = driver_for(session, static_hosts=[f"127.0.0.1:{port}"])
    await poll(driver)
    driver.add_host("localhost", port, {"api_proto": "http"}, mdns=True)
    await poll(driver, 2)
    node = driver.device_for(MINI)
    assert len(driver.devices) == 1 and (node.host, node.via_mdns) == ("127.0.0.1", True)
    assert node.as_dict()["other_addresses"] == [f"localhost:{port}"]
    before = net.node(MINI).requests
    driver.add_host("localhost", port, {"api_proto": "http"}, mdns=True)  # erneut angekündigt: schon bekannt
    await poll(driver)
    assert net.node(MINI).requests == before + 1 and driver.diagnostics()["pending"] == []


async def test_registry_gone_keeps_the_devices(make_net: MakeNet, session) -> None:
    net = await make_net(registry=True)
    driver = driver_for(session, registries=[net.registry.url])
    await poll(driver, 2)
    net.registry.down = True
    result = await poll(driver, nmos_driver.REGISTRY_EVERY)
    assert driver.registries[net.registry.url]["error"] and len(result.sources) == 8
    assert all(n.online for n in driver.devices.values())


async def test_registry_address_without_scheme(session) -> None:
    driver = driver_for(session, registries=["192.0.2.5:8010", "http://192.0.2.6:8010/"])
    assert list(driver.registries) == ["http://192.0.2.5:8010", "http://192.0.2.6:8010"]
    driver.add_registration("http://192.0.2.5:3210")
    assert driver.diagnostics()["registrations"] == ["http://192.0.2.5:3210"]


async def test_switch_is_a_device_of_its_own_kind_with_status_picture_and_monitor_output(make_net: MakeNet, session) -> None:
    net = await make_net(blackmagic.studio_with_switch())
    driver = driver_for(session, net)
    result = await poll(driver)
    node = driver.device_for(SWITCH)
    assert (node.manufacturer, node.model, node.device_type, node.icon_key, node.device_type_title) == (
        "Blackmagic Design",
        "Blackmagic Ethernet Switch 360P",
        "switch",
        "st2110_switch",
        "Netzwerk-Switch",
    )
    assert (node.tx_count, node.rx_count) == (1, 1)
    assert f"Status@{SWITCH}" in [s.name for s in result.sources] and f"{SWITCH}:Monitor SDI" in result.destinations
    assert driver.source_info(f"Status@{SWITCH}")["essences"] == ["video"]
    # der Monitorausgang ist ein gewöhnliches Ziel; eine Quelle mit Ton verbindet nur das Bild
    await driver.async_route(f"{SWITCH}:Monitor SDI", BIDI_IN)
    assert net.node(SWITCH).active("Monitor SDI")["sender_id"] == net.node(BIDI).sender("SDI In Video")["id"]
    # das Statusbild geht auf jeden Empfänger; Ton und Zusatzdaten des Ziels werden dabei getrennt
    await driver.async_route(HDMI, f"Status@{SWITCH}")
    state = (await poll(driver)).destinations[HDMI]
    assert state.current == f"Status@{SWITCH}" and state.status.extra["layers"]["audio"] is None


async def test_clock_summary_names_the_switch_as_grandmaster(make_net: MakeNet, session) -> None:
    specs = blackmagic.studio_with_switch()
    net = await make_net(specs)
    driver = driver_for(session, net)
    await poll(driver)
    clock = driver.clock_summary()
    assert clock["same"] is True and clock["unlocked"] == [] and clock["no_ptp"] == []
    assert [(m["device"], len(m["followers"])) for m in clock["grandmasters"]] == [(SWITCH, 6)]
    assert driver.device_for(SWITCH).ptp["is_grandmaster"] is True and driver.device_for(MINI).ptp["is_grandmaster"] is False

    net.node(BIDI).spec.gmid = "7c-2e-0d-ff-fe-0a-0b-03"  # der Wandler hält sich selbst für den Taktgeber
    net.node(DECK).spec.ptp_locked = False
    await driver.async_refresh_sources()
    await poll(driver)
    clock = driver.clock_summary()
    assert clock["same"] is False and clock["unlocked"] == [DECK]
    assert [(m["device"], len(m["followers"])) for m in clock["grandmasters"]] == [(SWITCH, 5), (BIDI, 1)]


def test_registry_endpoints_ipv4_first_and_href_fallback() -> None:
    raw = {"api": {"endpoints": [{"host": "box.local", "port": 80}, {"host": "fe80::1", "port": 80}, {"host": "192.0.2.7", "port": 8090, "protocol": "http"}]}}  # fmt: skip
    assert nmos_driver._node_endpoints(raw) == [("192.0.2.7", 8090, "http"), ("box.local", 80, "http")]
    assert nmos_driver._node_endpoints({"href": "https://192.0.2.8:8443/"}) == [("192.0.2.8", 8443, "https")]
    assert nmos_driver._node_endpoints("unsinn") == [] and nmos_driver._node_endpoints({"api": {"endpoints": [{"host": 1}]}}) == []
