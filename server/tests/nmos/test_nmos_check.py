"""Das Kommandozeilen-Werkzeug ``nmos-check`` gegen die Simulation (mDNS nur auf Loopback)."""

from __future__ import annotations

import json

import pytest

from avmatrix import nmos_check
from nmos_sim import blackmagic

from .conftest import BIDI, MINI, QUAD, MakeNet

LOOP = ["--interface", "127.0.0.1"]


def args(*argv: str):
    return nmos_check.build_parser().parse_args([*LOOP, *argv])


async def test_reports_cleanly_when_nothing_is_there(capsys: pytest.CaptureFixture[str]) -> None:
    assert await nmos_check.run(args("--timeout", "1")) == nmos_check.EXIT_OK
    out = capsys.readouterr().out
    assert "Keine NMOS-Geräte gefunden." in out and "solange noch kein ST-2110-Gerät am Netz hängt" in out
    assert "nmos-check --host" in out and "Traceback" not in out


async def test_lists_devices_senders_receivers_and_matrix_view(make_net: MakeNet, capsys: pytest.CaptureFixture[str]) -> None:
    await make_net(mdns="127.0.0.1")
    assert await nmos_check.run(args("--timeout", "6")) == nmos_check.EXIT_OK
    out = capsys.readouterr().out
    assert "5 NMOS-Gerät(e) gefunden, 5 antworten." in out
    for words in (f"■ {QUAD}", "Mehrkanal-Konverter", "Präsentationswandler", "I/O-Karte", "IS-04 v1.3, IS-05 v1.1",
                  "3840x2160p60 · Blackmagic IP10", "Gruppe: SDI In 4:video", "PTP          eingerastet", "keine Vorschau verfügbar",
                  f"SDI In 4@{QUAD}", f"{MINI}:HDMI Out", "Nichts verändert."):  # fmt: skip
        assert words in out
    assert "Weboberfläche keine" in out


async def test_probe_switches_reads_back_and_restores(make_net: MakeNet, capsys: pytest.CaptureFixture[str]) -> None:
    net = await make_net([blackmagic.mini_ip_to_hdmi(), blackmagic.mini_bidirect_12g()], mdns="127.0.0.1")
    mini, bidi = net.node(MINI), net.node(BIDI)
    foreign = "99999999-9999-4999-8999-999999999999"
    sdp = "v=0\r\ns=Vorher\r\nm=video 5004 RTP/AVP 96\r\nc=IN IP4 239.9.9.9/64\r\na=rtpmap:96 raw/90000\r\n"
    mini.connect("HDMI Out Video", foreign, sdp)  # vor der Probe steht dort etwas, das danach wieder dort stehen muss
    code = await nmos_check.run(args("--probe", "--yes", "--hold", "0", "--dest", f"{MINI}:HDMI Out"))
    out = capsys.readouterr().out
    assert code == nmos_check.EXIT_OK, out
    assert "✔ geschaltet und zurückgelesen" in out and "Sender-Kennung + SDP-Datei" in out and "✔ zurückgestellt" in out
    assert "waren ausgeschaltet und wurden für die Probe eingeschaltet" in out
    active = mini.active("HDMI Out Video")
    assert (active["sender_id"], active["master_enable"], active["transport_file"]["data"]) == (foreign, True, sdp)
    assert mini.active("HDMI Out Audio")["master_enable"] is False
    assert all(bidi.active(f"SDI In {e}")["master_enable"] is False for e in ("Video", "Audio", "ANC"))  # Sender wieder aus
    switched = [body.get("sender_id") for label, body in mini.patches if label == "HDMI Out Video"]
    assert switched == [bidi.sender("SDI In Video")["id"], foreign]


async def test_probe_reports_failure_and_still_restores(make_net: MakeNet, capsys: pytest.CaptureFixture[str]) -> None:
    target = blackmagic.mini_ip_to_hdmi()
    target.quirks.add("reject")
    await make_net([target, blackmagic.mini_bidirect_12g()], mdns="127.0.0.1")
    code = await nmos_check.run(args("--probe", "--yes", "--hold", "0", "--dest", f"{MINI}:HDMI Out"))
    out = capsys.readouterr().out
    assert code == nmos_check.EXIT_PROBE_FAILED and "✘ Schalten fehlgeschlagen" in out and "lehnt ab (500)" in out


async def test_probe_needs_confirmation(make_net: MakeNet, capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    net = await make_net([blackmagic.mini_ip_to_hdmi(), blackmagic.mini_bidirect_12g()], mdns="127.0.0.1")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert await nmos_check.run(args("--probe")) == nmos_check.EXIT_PROBE_FAILED
    assert "Bestätigung nötig" in capsys.readouterr().out and net.node(MINI).patches == []


async def test_probe_without_matching_pair(make_net: MakeNet, capsys: pytest.CaptureFixture[str]) -> None:
    await make_net([blackmagic.mini_ip_to_hdmi()], mdns="127.0.0.1")
    assert await nmos_check.run(args("--probe", "--yes")) == nmos_check.EXIT_PROBE_FAILED
    assert "mindestens einen Sender" in capsys.readouterr().out


async def test_direct_host_and_json(make_net: MakeNet, capsys: pytest.CaptureFixture[str]) -> None:
    net = await make_net([blackmagic.converter_4x12g()])  # nicht angekündigt
    code = await nmos_check.run(args("--no-mdns", "--timeout", "0", "--host", f"127.0.0.1:{net.nodes[0].port}", "--json"))
    data = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert code == 0 and data["devices"][0]["device_type"] == "multi" and len(data["devices"][0]["senders"]) == 12
    assert list(data["devices"][0]["destinations"]) == [f"SDI Out {n}" for n in (1, 2, 3, 4)]
