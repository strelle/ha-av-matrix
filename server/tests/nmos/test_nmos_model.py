"""Reine Logik: IS-04 lesen, gruppieren (BCP-002-01), Kompatibilität (BCP-004-01), SDP, Gerätetyp."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest

from avmatrix.device_icons import icon_key
from avmatrix.protocols import nmos
from avmatrix.protocols.nmos import Flow, NmosSourceRegistry, Receiver, Sender

N = "11111111-1111-4111-8111-11111111111"  # + eine Ziffer


def u(n: int) -> str:
    return f"{n:08d}-0000-4000-8000-000000000000"


def sender(n: int, label: str, kind: str, hint: str | None = None, device: str = u(900), **flow: Any) -> Sender:
    tags = {nmos.GROUPHINT_TAG: [hint]} if hint else {}
    return Sender(u(n), label, device, kind, "urn:x-nmos:transport:rtp.mcast", None, tags, Flow(u(n + 500), kind, **flow))


def receiver(
    n: int, label: str, kind: str, hint: str | None = None, device: str = u(900), caps: dict[str, Any] | None = None
) -> Receiver:
    tags = {nmos.GROUPHINT_TAG: [hint]} if hint else {}
    return Receiver(u(n), label, device, kind, "urn:x-nmos:transport:rtp.mcast", caps or {}, tags)


def model(senders: list[Sender] = (), receivers: list[Receiver] = (), devices: int = 1) -> nmos.NodeModel:
    m = nmos.NodeModel(id=u(1), label="Box")
    for i in range(devices):
        m.devices[u(900 + i)] = nmos.Device(u(900 + i), f"Box {i + 1}" if devices > 1 else "Box")
    m.senders = {s.id: s for s in senders}
    m.receivers = {r.id: r for r in receivers}
    return m


# ------------------------------------------------------------------ Kleinkram
@pytest.mark.parametrize(
    ("raw", "want"),
    [({"numerator": 60000, "denominator": 1001}, Fraction(60000, 1001)), ({"numerator": 50}, Fraction(50)), (25, Fraction(25)),
     ({"numerator": 1, "denominator": 0}, None), (None, None), ("x", None), (True, None)],
)  # fmt: skip
def test_rational(raw: Any, want: Fraction | None) -> None:
    assert nmos.rational(raw) == want


def test_ids_roundtrip() -> None:
    assert nmos.split_source(nmos.source_id("SDI 1", "Box")) == ("SDI 1", "Box")
    assert nmos.split_dest(nmos.dest_id("Box", "SDI 1")) == ("Box", "SDI 1", False)
    assert nmos.split_dest(nmos.dest_id("DeckLink IP/SDI HD", "Input 1", audio=True)) == ("DeckLink IP/SDI HD", "Input 1", True)
    for bad in ("ohne-trenner", "@Box", "SDI@"):
        with pytest.raises(ValueError):
            nmos.split_source(bad)
    with pytest.raises(ValueError):
        nmos.split_dest("kein ziel")


def test_clean_name_removes_separators() -> None:
    assert nmos.clean_name("Regie: Monitor@1\n") == "Regie Monitor at 1"
    assert nmos.clean_name("", "x") == "x"


def test_pick_version() -> None:
    assert nmos.pick_version(["v1.0/", "v1.1/", "v1.2/", "v1.3/"], nmos.NODE_API_VERSIONS) == "v1.3"
    assert nmos.pick_version("v1.0,v1.2", nmos.NODE_API_VERSIONS) == "v1.2"
    assert nmos.pick_version(["v1.0/"], nmos.NODE_API_VERSIONS) is None
    assert nmos.pick_version({"nix": 1}, nmos.NODE_API_VERSIONS) is None


def test_connection_control_prefers_newest_version_and_same_host() -> None:
    controls = [
        {"type": "urn:x-nmos:control:sr-ctrl/v1.0", "href": "http://192.0.2.5:8090/x-nmos/connection/v1.0/"},
        {"type": "urn:x-nmos:control:sr-ctrl/v1.1", "href": "http://10.0.0.5:8090/x-nmos/connection/v1.1/"},
        {"type": "urn:x-nmos:control:sr-ctrl/v1.1", "href": "http://192.0.2.5:8090/x-nmos/connection/v1.1/"},
        {"type": "urn:x-nmos:control:events/v1.0", "href": "http://192.0.2.5/x-nmos/events/v1.0/"},
        {"type": "urn:x-nmos:control:sr-ctrl/v1.1", "href": "ftp://quatsch"},
        "kaputt",
    ]
    assert nmos.connection_control(controls, "192.0.2.5") == ("http://192.0.2.5:8090/x-nmos/connection/v1.1", "v1.1")
    assert nmos.connection_control(None) == (None, None)


def test_parse_flow_video_and_audio() -> None:
    video = nmos.parse_flow(
        {
            "id": u(5), "format": "urn:x-nmos:format:video", "media_type": "video/raw", "frame_width": 1920, "frame_height": 1080,
            "interlace_mode": "interlaced_tff", "grain_rate": {"numerator": 25},
            "components": [{"name": "Y", "width": 1920, "height": 1080, "bit_depth": 10}, {"name": "Cb", "width": 960, "height": 1080, "bit_depth": 10},
                           {"name": "Cr", "width": 960, "height": 1080, "bit_depth": 10}],
        },
        None,
    )  # fmt: skip
    assert (video.sampling, video.depth, video.interlaced) == ("YCbCr-4:2:2", 10, True)
    assert video.text == "1920x1080i25 · unkomprimiert"
    assert video.resolution == "1920x1080i25"
    audio = nmos.parse_flow(
        {
            "id": u(6),
            "format": "urn:x-nmos:format:audio",
            "media_type": "audio/L24",
            "sample_rate": {"numerator": 48000},
            "bit_depth": 24,
        },
        {"channels": [{"label": "L"}, {"label": "R"}], "format": "urn:x-nmos:format:audio"},
    )
    assert (audio.channels, audio.text, audio.resolution) == (2, "48 kHz · 2 Kanäle", "48 kHz")


def test_media_titles() -> None:
    assert nmos.media_title(nmos.IP10_MEDIA_TYPE) == "Blackmagic IP10"
    assert nmos.is_compressed(nmos.IP10_MEDIA_TYPE) is True
    assert nmos.is_compressed("video/raw") is False
    assert nmos.is_compressed("video/smpte291") is None
    assert nmos.is_compressed("audio/L24") is None


def test_parse_node_skips_broken_entries() -> None:
    me = {"id": u(1), "label": "Box", "interfaces": [{"port_id": "7c-2e-0d-00-00-01"}, {"port_id": "quatsch"}, 7],
          "clocks": [{"name": "clk0", "ref_type": "ptp", "locked": True, "gmid": "aa"}, "x"]}  # fmt: skip
    devices = [{"id": u(900), "label": "Box", "controls": "kaputt"}, {"id": "keine-uuid"}, 3]
    senders = [
        {"id": u(10), "label": "V", "device_id": u(900), "flow_id": None, "subscription": "kaputt"},
        "x",
        {"label": "ohne id"},
    ]
    receivers = [
        {
            "id": u(20),
            "label": "R",
            "device_id": u(900),
            "format": "urn:x-nmos:format:video",
            "caps": 5,
            "subscription": {"sender_id": "x", "active": 1},
        }
    ]
    m = nmos.parse_node(me, devices, [], [], senders, receivers)
    assert m.macs == ["7c:2e:0d:00:00:01"] and m.clocks[0].locked is True
    assert list(m.devices) == [u(900)] and m.devices[u(900)].connection_href is None
    assert m.senders[u(10)].flow is None and m.senders[u(10)].kind is None
    assert m.receivers[u(20)].caps == {} and m.receivers[u(20)].sender_id is None and m.receivers[u(20)].active is True


@pytest.mark.parametrize("bad", [None, [], {"label": "ohne id"}, "html"])
def test_parse_node_rejects_non_nmos(bad: Any) -> None:
    with pytest.raises(nmos.NmosError):
        nmos.parse_node(bad, [], [], [], [], [])
    with pytest.raises(nmos.NmosError):
        nmos.parse_node({"id": u(1)}, {"kein": "array"}, [], [], [], [])


# ------------------------------------------------------------------ Gruppierung
def test_groups_from_bcp_002_01_hints() -> None:
    m = model(
        [
            sender(1, "A", nmos.VIDEO, "SDI 1:video"), sender(2, "B", nmos.AUDIO, "SDI 1:audio 2"), sender(3, "C", nmos.AUDIO, "SDI 1:audio 1"),
            sender(4, "D", nmos.DATA, "SDI 1:anc"), sender(5, "E", nmos.VIDEO, "SDI 2:video"), sender(6, "F", nmos.AUDIO, "SDI 2:audio:device"),
        ]
    )  # fmt: skip
    groups = {g.name: g for g in nmos.build_groups(m, "sender")}
    assert list(groups) == ["SDI 1", "SDI 2"]
    assert groups["SDI 1"].layers == {("video", 0): u(1), ("audio", 0): u(3), ("audio", 1): u(2), ("data", 0): u(4)}
    assert groups["SDI 1"].hinted and groups["SDI 1"].kinds() == ["video", "audio", "data"] and groups["SDI 1"].primary == "video"
    assert groups["SDI 2"].layers == {("video", 0): u(5), ("audio", 0): u(6)}


def test_same_group_name_on_two_devices_stays_separate_unless_node_scope() -> None:
    m = model([sender(1, "V", nmos.VIDEO, "Main:video", u(900)), sender(2, "A", nmos.AUDIO, "Main:audio", u(901))], devices=2)
    assert [g.name for g in nmos.build_groups(m, "sender")] == ["Main", "Main (2)"]
    m = model(
        [sender(1, "V", nmos.VIDEO, "Main:video:node", u(900)), sender(2, "A", nmos.AUDIO, "Main:audio:node", u(901))], devices=2
    )
    groups = nmos.build_groups(m, "sender")
    assert len(groups) == 1 and len(groups[0].layers) == 2


def test_single_video_device_without_hints_is_one_group() -> None:
    m = model(
        receivers=[
            receiver(1, "HDMI Out Video", nmos.VIDEO),
            receiver(2, "irgendwas", nmos.AUDIO),
            receiver(3, "Daten", nmos.DATA),
        ]
    )
    (group,) = nmos.build_groups(m, "receiver")
    assert group.name == "HDMI Out Video" and not group.hinted
    assert group.kinds() == ["video", "audio", "data"]


def test_audio_only_device_without_hints() -> None:
    m = model([sender(1, "Mic 1", nmos.AUDIO), sender(2, "Mic 2", nmos.AUDIO)])
    (group,) = nmos.build_groups(m, "sender")
    assert group.name == "Eingang" and group.primary == "audio" and len(group.layers) == 2


def test_numbered_labels_group_multi_channel_device_without_hints() -> None:
    m = model(
        [sender(n, f"2110 SDI In {n} Video", nmos.VIDEO) for n in (1, 2, 3, 4)]
        + [sender(10 + n, f"SDI In {n} Audio", nmos.AUDIO) for n in (1, 2, 3, 4)]
        + [sender(20 + n, f"SDI In {n} ANC", nmos.DATA) for n in (1, 2)]
        + [sender(30, "Talkback", nmos.AUDIO)]
    )
    groups = nmos.build_groups(m, "sender")
    assert [g.name for g in groups] == [
        "2110 SDI In 1 Video",
        "2110 SDI In 2 Video",
        "2110 SDI In 3 Video",
        "2110 SDI In 4 Video",
        "Talkback",
    ]
    assert groups[0].layers == {("video", 0): u(1), ("audio", 0): u(11), ("data", 0): u(21)}
    assert groups[2].layers == {("video", 0): u(3), ("audio", 0): u(13)}
    assert groups[4].layers == {("audio", 0): u(30)}  # ohne Nummer: bleibt allein, es wird nicht geraten


def test_unnumbered_multi_video_is_not_paired_by_guessing() -> None:
    m = model([sender(1, "Kamera", nmos.VIDEO), sender(2, "Grafik", nmos.VIDEO), sender(3, "Ton", nmos.AUDIO)])
    groups = nmos.build_groups(m, "sender")
    assert sorted(len(g.layers) for g in groups) == [1, 1, 1]


def test_sender_without_flow_takes_its_kind_from_role_or_label() -> None:
    """Kein Eingangssignal → kein Flow. Der Eingang soll trotzdem als Quelle stehen bleiben."""
    senders = [
        {
            "id": u(10),
            "label": "SDI In 1",
            "device_id": u(900),
            "flow_id": None,
            "tags": {nmos.GROUPHINT_TAG: ["SDI In 1:video"]},
        },
        {"id": u(11), "label": "SDI In 1 Audio", "device_id": u(900), "flow_id": None},
        {"id": u(12), "label": "SDI In 1 ANC", "device_id": u(900), "flow_id": None},
        {"id": u(13), "label": "Irgendwas", "device_id": u(900), "flow_id": None},
    ]
    m = nmos.parse_node({"id": u(1)}, [{"id": u(900), "label": "Box"}], [], [], senders, [])
    assert [m.senders[u(n)].kind for n in (10, 11, 12, 13)] == ["video", "audio", "data", None]


def test_senders_without_flow_are_not_sources() -> None:
    m = model([Sender(u(1), "leer", u(900), None)])
    assert nmos.build_groups(m, "sender") == []


# --------------------------------------------------------------- Kompatibilität
HD_CAPS = {
    "media_types": ["video/raw"],
    "constraint_sets": [
        {
            "urn:x-nmos:cap:format:frame_width": {"enum": [1920]},
            "urn:x-nmos:cap:format:frame_height": {"enum": [1080]},
            "urn:x-nmos:cap:format:grain_rate": {"enum": [{"numerator": 50}, {"numerator": 60000, "denominator": 1001}]},
        },
        {"urn:x-nmos:cap:meta:enabled": False, "urn:x-nmos:cap:format:frame_width": {"enum": [3840]}},
    ],
}


def video(n: int = 1, **kw: Any) -> Sender:
    flow = {"media_type": "video/raw", "width": 1920, "height": 1080, "rate": Fraction(50), "interlace_mode": "progressive", **kw}
    return sender(n, "V", nmos.VIDEO, **flow)


def test_compatible_stream_passes() -> None:
    assert nmos.check_compat(video(), receiver(2, "R", nmos.VIDEO, caps=HD_CAPS)) is None
    assert nmos.check_compat(video(rate=Fraction(60000, 1001)), receiver(2, "R", nmos.VIDEO, caps=HD_CAPS)) is None


def test_receiver_without_caps_accepts_everything() -> None:
    assert nmos.check_compat(video(width=7680, height=4320), receiver(2, "R", nmos.VIDEO)) is None


def test_sender_without_flow_is_not_blocked() -> None:
    assert nmos.check_compat(Sender(u(1), "V", u(900), nmos.VIDEO), receiver(2, "R", nmos.VIDEO, caps=HD_CAPS)) is None


@pytest.mark.parametrize(
    ("flow", "words"),
    [
        ({"media_type": nmos.IP10_MEDIA_TYPE}, ["Blackmagic IP10", "nur unkomprimiert"]),
        ({"width": 3840, "height": 2160}, ["Auflösung", "3840x2160p50"]),
        ({"rate": Fraction(25)}, ["Bildrate"]),
    ],
)
def test_incompatible_video_gets_a_readable_reason(flow: dict[str, Any], words: list[str]) -> None:
    reason = nmos.check_compat(video(**flow), receiver(2, "R", nmos.VIDEO, caps=HD_CAPS))
    assert reason and all(w in reason for w in words)
    assert len(reason) < 110  # der Kern kürzt Fehlertexte bei 120 Zeichen


def test_disabled_constraint_set_does_not_count() -> None:
    assert nmos.check_compat(video(width=3840, height=2160), receiver(2, "R", nmos.VIDEO, caps=HD_CAPS)) is not None


def test_audio_channel_count_range() -> None:
    caps = {
        "constraint_sets": [
            {
                "urn:x-nmos:cap:format:channel_count": {"minimum": 1, "maximum": 8},
                "urn:x-nmos:cap:format:sample_rate": {"enum": [{"numerator": 48000}]},
            }
        ]
    }
    rx = receiver(2, "R", nmos.AUDIO, caps=caps)
    assert nmos.check_compat(sender(1, "A", nmos.AUDIO, channels=8, sample_rate=Fraction(48000)), rx) is None
    assert "Kanalzahl" in (nmos.check_compat(sender(1, "A", nmos.AUDIO, channels=16, sample_rate=Fraction(48000)), rx) or "")
    assert "Abtastrate" in (nmos.check_compat(sender(1, "A", nmos.AUDIO, channels=2, sample_rate=Fraction(96000)), rx) or "")


def test_kind_and_transport_mismatch() -> None:
    assert "Ton" in (nmos.check_compat(sender(1, "A", nmos.AUDIO), receiver(2, "R", nmos.VIDEO)) or "")
    ucast = receiver(2, "R", nmos.VIDEO)
    ucast.transport = "urn:x-nmos:transport:rtp.ucast"
    assert "Transport" in (nmos.check_compat(video(), ucast) or "")
    ucast.transport = "urn:x-nmos:transport:rtp"  # nimmt beides
    assert nmos.check_compat(video(), ucast) is None
    ucast.transport = "urn:x-nmos:transport:mqtt"
    assert "Transport" in (nmos.check_compat(video(), ucast) or "")


# -------------------------------------------------------------------------- SDP
SDP_IP10 = (
    "v=0\r\no=- 1 1 IN IP4 192.0.2.10\r\ns=ATEM 1\r\nt=0 0\r\nm=video 16388 RTP/AVP 96\r\nc=IN IP4 239.255.66.205/64\r\n"
    "a=source-filter: incl IN IP4 239.255.66.205 192.0.2.10\r\na=rtpmap:96 vnd.blackmagic-design.ip10/90000\r\n"
    "a=fmtp:96 sampling=YCbCr-4:2:2; width=3840; height=2160; exactframerate=60; depth=10; SSN=ST2110-22:2022; scheme=10:8; \r\n"
    "a=ts-refclk:ptp=IEEE1588-2008:7C-2E-0D-FF-FE-00-00-01:127\r\na=mediaclk:direct=0\r\n"
)


def test_parse_sdp_ip10() -> None:
    info = nmos.parse_sdp(SDP_IP10)
    assert (info.media, info.port, info.payload, info.encoding) == ("video", 16388, 96, "vnd.blackmagic-design.ip10")
    assert info.media_type == nmos.IP10_MEDIA_TYPE
    assert (info.destination, info.source, info.legs) == ("239.255.66.205", "192.0.2.10", 1)
    assert info.fmtp["width"] == "3840" and info.fmtp["scheme"] == "10:8" and info.ptp.startswith("ptp=IEEE1588-2008")


def test_parse_sdp_audio_session_level_connection_and_two_legs() -> None:
    text = "v=0\nc=IN IP4 239.1.1.1/32\nm=audio 5004 RTP/AVP 97\na=rtpmap:97 L24/48000/16\nm=audio 5004 RTP/AVP 97\nc=IN IP4 239.2.2.2/32\n"
    info = nmos.parse_sdp(text)
    assert (info.media_type, info.destination, info.legs) == ("audio/L24", "239.1.1.1", 2)
    assert nmos.parse_sdp("ganz was anderes").media is None
    assert nmos.is_sdp(text) and not nmos.is_sdp("<html>") and not nmos.is_sdp(None)


# -------------------------------------------------------------------- Gerätetyp
def typed(
    label: str,
    description: str = "",
    macs: tuple[str, ...] = (),
    tags: dict[str, list[str]] | None = None,
    tx: int = 0,
    rx: int = 0,
):
    m = model(
        [sender(n, f"V{n}", nmos.VIDEO) for n in range(1, tx + 1)],
        [receiver(50 + n, f"R{n}", nmos.VIDEO) for n in range(1, rx + 1)],
    )
    m.label, m.description, m.macs, m.tags = label, description, list(macs), tags or {}
    m.devices[u(900)].label = label
    return nmos.classify_device(m)


@pytest.mark.parametrize(
    ("product", "kind", "icon"),
    [
        ("Blackmagic 2110 IP Mini IP to HDMI", "converter", "st2110_converter"),
        ("Blackmagic 2110 IP Presentation Converter", "presentation", "st2110_presentation"),
        ("Blackmagic 2110 IP Mini BiDirect 12G", "converter", "st2110_converter"),
        ("Blackmagic 2110 IP Converter 4x12G PWR", "multi", "st2110_multi"),
        ("DeckLink IP/SDI HD", "card", "st2110_card"),
    ],
)
def test_the_five_ordered_devices_are_recognised_by_name(product: str, kind: str, icon: str) -> None:
    manufacturer, model_name, device_type = typed(product)
    assert (manufacturer, model_name, device_type) == ("Blackmagic Design", product, kind)
    assert nmos.DEVICE_TYPES[kind][1] == icon
    assert icon_key(protocol="st2110", driver="nmos", manufacturer=manufacturer, model=model_name, name=product) == icon


def test_renamed_device_is_not_guessed() -> None:
    """Heißt das Gerät „Regie 1“ und sagt sonst nichts, bleibt der Typ neutral – Hersteller nur über die MAC."""
    assert typed("Regie 1", tx=1, rx=1) == (None, None, "device")
    assert typed("Regie 1", macs=("7c:2e:0d:12:34:56",), tx=1) == ("Blackmagic Design", None, "device")
    assert typed("Regie 1", macs=("00:11:22:33:44:55",)) == (None, None, "device")
    assert icon_key(protocol="st2110", name="Regie 1") == "st2110_device"


def test_structure_tells_a_multi_channel_device() -> None:
    assert typed("Regie 1", tx=4, rx=4)[2] == "multi"


def test_description_and_asset_tags_name_the_product() -> None:
    assert typed("Regie 1", description="Blackmagic 2110 IP Presentation Converter")[1:] == (
        "Blackmagic 2110 IP Presentation Converter",
        "presentation",
    )
    tags = {nmos.TAG_MANUFACTURER: ["Acme"], nmos.TAG_PRODUCT: ["Gateway 4x12G"]}
    assert typed("Regie 1", tags=tags) == ("Acme", "Gateway 4x12G", "multi")


# --------------------------------------------------------------------- Register
def test_registry_describes_sources_and_says_no_preview() -> None:
    registry = NmosSourceRegistry()
    assert registry.protocol == "st2110" and registry.grouped and registry.preview is False
    assert registry.describe("SDI In 2@Box") == {"group": "Box", "channel": "SDI In 2", "preview": "none"}
    assert registry.describe("kaputt") == {"preview": "none"}
    names = ["SDI In 10@Box", "SDI In 2@Box", "Cam@Anlage"]
    assert sorted(names, key=registry.sort_key) == ["Cam@Anlage", "SDI In 2@Box", "SDI In 10@Box"]
