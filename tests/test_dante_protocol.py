"""Dante® ARC packets: parsers against real answers, encoders against reference bytes."""

from __future__ import annotations

import pytest

from custom_components.av_matrix.protocols import dante as arc

from .dante_sim import (
    NETAUDIO_RX_PAGE_17,
    NETAUDIO_RX_PAGE_49,
    NETAUDIO_TX_PAGE_33,
    STUDIO_AVIO_COUNT,
    STUDIO_AVIO_NAME,
    STUDIO_AVIO_RX,
    STUDIO_AVIO_TX,
    STUDIO_AVIO_TX_LABELS,
    STUDIO_DA_RX,
    FakeDanteDevice,
    FakeRx,
)


def test_identity_roundtrip() -> None:
    assert arc.source_id("Mic 3", "STAGEBOX-01") == "Mic 3@STAGEBOX-01"
    assert arc.split_source("Mic 3@STAGEBOX-01") == ("Mic 3", "STAGEBOX-01")
    assert arc.split_source("a@b@DEV") == ("a@b", "DEV")
    for bad in ("Mic 3", "@DEV", "CH1@"):
        with pytest.raises(ValueError):
            arc.split_source(bad)
    assert arc.DanteSourceRegistry().describe("CH1@DEV") == {"group": "DEV", "channel": "CH1"}


@pytest.mark.parametrize(
    ("version", "expected"),
    [("2.8.9", 0x2809), ("2.8.12", 0x280C), ("2.8.20", 0x280F), ("2.7.0", 0x27FF), (None, 0x27FF), ("x", 0x27FF)],
)
def test_arc_protocol_from_mdns(version, expected) -> None:
    assert arc.arc_protocol_id(version) == expected


def test_requests_are_framed_like_dante_controller() -> None:
    assert arc.req_device_name(0x1235).hex() == "27ff000a123510020000"
    assert arc.req_channel_count(7).hex() == "27ff000a000710000000"
    # paged queries as recorded by netaudio (issue 59): first channel 17 / 33
    assert arc.req_rx_channels(3, 1).hex() == "27ff0010000330000000000100110000"
    assert arc.req_tx_channels(9, 1).hex() == "27ff0010000920000000000100210000"
    assert arc.req_tx_friendly_names(1, 0, 2).hex() == "27ff001000012010000000010001" + "0002"


def test_studio_device_answers() -> None:
    assert arc.parse_device_name(arc.parse_header(STUDIO_AVIO_NAME)) == "AVIOAES3-0d0e0f"
    assert arc.parse_channel_count(arc.parse_header(STUDIO_AVIO_COUNT)) == (2, 2)
    tx = arc.parse_tx_channels(arc.parse_header(STUDIO_AVIO_TX))
    assert [(c.number, c.name, c.sample_rate) for c in tx] == [(1, "CH1", 48000), (2, "CH2", 48000)]
    assert arc.parse_tx_friendly_names(arc.parse_header(STUDIO_AVIO_TX_LABELS)) == {}
    rx = arc.parse_rx_channels(arc.parse_header(STUDIO_AVIO_RX))
    assert [(c.number, c.name, c.tx_channel, c.tx_device) for c in rx] == [
        (1, "CH1", "61", "Example-WING-Fullsize"),
        (2, "CH2", "62", "Example-WING-Fullsize"),
    ]
    assert rx[0].sample_rate == 48000
    assert not rx[0].can_subscribe_self
    # subscribed, but the mixer is switched off → status 1 with receiver status 0 = unresolved
    status = arc.subscription_status(rx[0])
    assert (status.state, status.name) == ("unresolved", "UNRESOLVED")
    rx = arc.parse_rx_channels(arc.parse_header(STUDIO_DA_RX))
    assert [(c.tx_channel, c.tx_device) for c in rx] == [("CH1", "DA11AEN-010203"), ("CH2", "DA11AEN-010203")]


def test_netaudio_pages_of_a_64_channel_device() -> None:
    page = arc.parse_header(NETAUDIO_RX_PAGE_17)
    assert page.more  # 0x8112: more pages follow
    rx = arc.parse_rx_channels(page)
    assert [c.number for c in rx] == list(range(17, 33))
    assert all(arc.subscription_status(c).state == "subscribed" for c in rx)
    assert rx[0].tx_channel == "XX" and rx[0].tx_device == "X" * 18
    last = arc.parse_header(NETAUDIO_RX_PAGE_49)
    assert not last.more
    rx = arc.parse_rx_channels(last)
    assert [c.number for c in rx] == list(range(49, 65))
    assert all(not c.subscribed and arc.subscription_status(c).state == "none" for c in rx)
    tx = arc.parse_tx_channels(arc.parse_header(NETAUDIO_TX_PAGE_33))
    assert [c.number for c in tx] == list(range(33, 65))
    assert {c.sample_rate for c in tx} == {48000}


def test_legacy_subscription_packets_match_reference() -> None:
    # reference bytes from netaudio's core_commands_golden.json
    assert (
        arc.req_subscribe_legacy(0, [(1, "mix-hi", "lx-dante")]).hex()
        == "27ff0044000030100000020100010034003b" + "00" * 34 + "6d69782d6869006c782d64616e746500"
    )
    assert (
        arc.req_subscribe_legacy(0, [(1, "a", "dev-one"), (2, "bb", "dev-two"), (5, "ccc", "dev-three")]).hex()
        == "27ff005700003010000002030001003400360002003e004100050049004d"
        + "00" * 22
        + "61006465762d6f6e65006262006465762d74776f00636363006465762d746872656500"
    )
    assert arc.req_unsubscribe_legacy(0, [3]).hex() == "27ff0010000030140000000100000003"
    assert (
        arc.req_unsubscribe_legacy(0, [1, 2, 7, 16]).hex() == "27ff001c000030140000000400000001000000020000000700000010"
    )


def test_modern_subscription_page() -> None:
    pkt = arc.req_subscription_page(5, 0x280C, 3, [(1, "Left", "Sender"), (2, None, None)])
    assert pkt[:2] == bytes.fromhex("280c")
    assert pkt[6:20] == bytes.fromhex("3410000000000000000008000302")
    assert pkt[20:24] == bytes([0, 1, 0, 3])
    assert pkt[28:36] == bytes([0, 2, 0, 3, 0, 0, 0, 0])
    assert pkt[36:44] == bytes(8)
    assert pkt[44:] == b"Left\0Sender\0"
    with pytest.raises(arc.ArcError):
        arc.req_subscription_page(1, 0x27FF, 2, [(1, "a", "b")])
    with pytest.raises(arc.ArcError):
        arc.req_subscription_page(1, 0x2809, 2, [(1, "a", "b"), (1, None, None)])
    with pytest.raises(arc.ArcError):
        arc.req_subscription_page(1, 0x2809, 2, [(1, "x" * 32, "b")])


def test_subscription_states() -> None:
    def st(**kw):
        return arc.subscription_status(arc.RxChannel(1, "In", **kw)).state

    assert st() == "none"
    assert st(tx_channel="A", tx_device="DEV", status=9, rx_status=0x0101) == "subscribed"
    assert st(tx_channel="A", tx_device="DEV", status=1, rx_status=0x0101) == "subscribed"
    assert st(tx_channel="A", tx_device=".", status=4) == "self"
    assert st(tx_channel="A", tx_device="DEV", status=8) == "in_progress"
    assert st(tx_channel="A", tx_device="DEV", status=5) == "unresolved"
    assert st(tx_channel="A", tx_device="DEV", status=0x10) == "error"
    assert st(tx_channel="A", tx_device="DEV", status=0x23) == "warning"
    assert st(tx_channel="A", tx_device="DEV", status=0x77) == "error"
    assert arc.format_sample_rate(44100) == "44.1 kHz"
    assert arc.format_sample_rate(None) is None


def test_garbage_is_rejected() -> None:
    with pytest.raises(arc.ArcError):
        arc.parse_header(b"\x27\xff\x00")
    with pytest.raises(arc.ArcError):
        arc.parse_header(bytes.fromhex("27ff0020123510020001"))  # wrong length
    with pytest.raises(arc.ArcError):
        arc.parse_device_name(arc.parse_header(bytes.fromhex("27ff000c123510020022" + "0000")))  # error result
    with pytest.raises(arc.ArcError):
        arc.parse_rx_channels(arc.parse_header(STUDIO_AVIO_NAME))  # wrong opcode


def test_simulator_matches_captures() -> None:
    """The simulator used by the integration tests produces the same content as the real devices."""
    dev = FakeDanteDevice(
        "AVIOAES3-0d0e0f",
        ["CH1", "CH2"],
        [FakeRx("CH1", "61", "Example-WING-Fullsize", 1, 0), FakeRx("CH2", "62", "Example-WING-Fullsize", 1, 0)],
    )
    real = arc.parse_rx_channels(arc.parse_header(STUDIO_AVIO_RX))
    sim = arc.parse_rx_channels(arc.parse_header(dev.handle(arc.req_rx_channels(1, 0))))
    assert [(c.number, c.name, c.tx_channel, c.tx_device, c.status, c.sample_rate) for c in sim] == [
        (c.number, c.name, c.tx_channel, c.tx_device, c.status, c.sample_rate) for c in real
    ]
