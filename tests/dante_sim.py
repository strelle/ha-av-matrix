"""Dante® test helpers: real (anonymised) ARC answers and a small device simulator.

Captures
--------
``STUDIO_*``: answers of two real devices (Audinate AVIO AES3 adapter and an HDCVT ULTIMOX2 Dante
interface, both ARC 2.8.9, router 4.3.0), recorded 2026-10-05 with read-only queries. Device names
were replaced by strings of the same length (pointers stay valid), nothing else was changed.

``NETAUDIO_*``: pages from the fixtures of the netaudio project
(github.com/chris-ritsen/network-audio-controller, tests/fixtures/issue_59/later_pages.json,
public domain / Unlicense): a 64-channel device; channel and device strings there were replaced by
``X`` by the netaudio authors.

The simulator below answers like those devices (same record layouts) and applies subscriptions.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from custom_components.av_matrix.drivers.base import CannotConnect
from custom_components.av_matrix.drivers.dante import ArcTransport
from custom_components.av_matrix.protocols import dante as arc

H = bytes.fromhex

# --- studio device "AVIOAES3-0d0e0f" (RX 1/2 subscribed to 61/62@Example-WING-Fullsize, which is offline)
STUDIO_AVIO_NAME = H("27ff001a123c100200014156494f414553332d30643065306600")
STUDIO_AVIO_COUNT = H(
    "27ff0030123d100000010df9000200020000000200080002000200020001000100000000000000000000000000000000"
)
STUDIO_AVIO_TX = H(
    "27ff0034123f20000001020200010007001c002c00020007001c00300000bb8001010018040000180018000e4348310043483200"
)
STUDIO_AVIO_TX_LABELS = H("27ff001c124020100001020000000000001c002c00020007001c0030")
STUDIO_AVIO_RX = H(
    "27ff006b1241300000010202000100060050003400370060000000010000000000020006005000640037006700000001000000003631"
    "004578616d706c652d57494e472d46756c6c73697a65000000000000bb8001010018040000180018000e4348310036320043483200"
)
# --- studio device "DA-22UC-0a0b0c" (RX 1/2 subscribed to CH1/CH2@DA11AEN-010203, offline)
STUDIO_DA_NAME = H("27ff001912351002000144412d323255432d30613062306300")
STUDIO_DA_RX = H(
    "27ff0064123a3000000102020001000600480034003800580000000100000000000200060048005c003800600000000100000000"
    "434831004441313141454e2d30313032303300350000bb8001010018040000180018000e434831004348320043483200"
)
# answer of a modern device to a paged subscription (0x3410), from netaudio's tests
MODERN_SUBSCRIPTION_OK = H("280900144a263410000100000000000001000000")

# --- netaudio fixtures (64 channel device)
NETAUDIO_RX_PAGE_17 = H(
    "27ff01d700033000811210100011000f0164014c014f017401010009000000000012000f01640177014f017a01010009000000000013"
    "000f0164017d014f018001010009000000000014000f01640183014f018601010009000000000015000f01640189014f018c010100090"
    "00000000016000f0164018f014f019201010009000000000017000f01640195014f019801010009000000000018000f0164019b014f01"
    "9e01010009000000000019000f016401a1014f01a40101000900000000001a000f016401a7014f01aa0101000900000000001b000f0164"
    "01ad014f01b00101000900000000001c000f016401b3014f01b60101000900000000001d000f016401b9014f01bc010100090000000000"
    "1e000f016401bf014f01c20101000900000000001f000f016401c5014f01c801010009000000000020000f016401cb014f01ce01010009"
    "000000005858005858585858585858585858585858585858580000000000bb8001010018040000180018000c58580058580058580058"
    "5800585800585800585800585800585800585800585800585800585800585800585800585800585800585800585800585800585800585"
    "800585800585800585800585800585800585800585800585800585800333300333300"
)
NETAUDIO_RX_PAGE_49 = H(
    "27ff018c00053000000110100031000f014c00000000015c00000000000000000032000f014c00000000015f000000000000000000330"
    "00f014c00000000016200000000000000000034000f014c00000000016500000000000000000035000f014c0000000001680000000000"
    "0000000036000f014c00000000016b00000000000000000037000f014c00000000016e00000000000000000038000f014c00000000017"
    "100000000000000000039000f014c0000000001740000000000000000003a000f014c0000000001770000000000000000003b000f014c"
    "00000000017a0000000000000000003c000f014c00000000017d0000000000000000003d000f014c0000000001800000000000000000"
    "003e000f014c0000000001830000000000000000003f000f014c00000000018600000000000000000040000f014c0000000001890000"
    "0000000000000000bb8001010018040000180018000c58580058580058580058580058580058580058580058580058580058580058580"
    "0585800585800585800585800585800"
)
NETAUDIO_TX_PAGE_33 = H(
    "27ff017c000920000001202000210107010c011c00220107010c011f00230107010c012200240107010c012500250107010c0128002601"
    "07010c012b00270107010c012e00280107010c013100290107010c0134002a0107010c0137002b0107010c013a002c0107010c013d002d"
    "0107010c0140002e0107010c0143002f0107010c014600300107010c014900310107010c014c00320107010c014f00330107010c015200"
    "340107010c015500350107010c015800360107010c015b00370107010c015e00380107010c016100390107010c0164003a0107010c0167"
    "003b0107010c016a003c0107010c016d003d0107010c0170003e0107010c0173003f0107010c017600400107010c01790000bb800101001"
    "8040000180018000c58580058580058580058580058580058580058580058580058580058580058580058580058580058580058580058"
    "5800585800585800585800585800585800585800585800585800585800585800585800585800585800585800585800585800"
)

FORMAT_48K = H("0000bb8001010018040000180018000e")  # sample rate 48000, 24 bit …


def _strings(base: int, texts: list[str]) -> tuple[dict[str, int], bytes]:
    """Lay out zero-terminated strings starting at absolute offset ``base``."""
    offsets: dict[str, int] = {}
    blob = bytearray()
    for text in texts:
        if text not in offsets:
            offsets[text] = base + len(blob)
            blob += text.encode() + b"\0"
    return offsets, bytes(blob)


def _answer(protocol: int, seq: int, opcode: int, result: int, body: bytes) -> bytes:
    return struct.pack(">HHHHH", protocol, 10 + len(body), seq, opcode, result) + body


@dataclass
class FakeRx:
    name: str
    tx_channel: str | None = None
    tx_device: str | None = None
    status: int = 0
    rx_status: int = 0


@dataclass
class FakeDanteDevice:
    """Answers ARC requests like a Dante device (layouts as in the captures above)."""

    name: str
    tx: list[str]
    rx: list[FakeRx]
    labels: dict[int, str] = field(default_factory=dict)
    network: dict[str, FakeDanteDevice] | None = None
    online: bool = True
    mdns: bool = True  # announced via mDNS (else: only reachable as a static host)
    refuse: bool = False
    ignore_writes: bool = False
    requests: list[bytes] = field(default_factory=list)
    captured: dict[int, bytes] = field(default_factory=dict)  # opcode → real answer (until a write)

    def resolve(self, ch: FakeRx) -> None:
        if not ch.tx_channel:
            ch.status, ch.rx_status = 0, 0
            return
        dev = (self.network or {}).get(ch.tx_device or "")
        if ch.tx_device in (".", self.name):
            ch.status, ch.rx_status = 0x04, 0x0101
        elif dev is not None and dev.online and ch.tx_channel in dev.tx_labels():
            ch.status, ch.rx_status = 0x09, 0x0101
        else:
            ch.status, ch.rx_status = 0x01, 0x0000

    def tx_labels(self) -> list[str]:
        return [self.labels.get(i + 1, n) for i, n in enumerate(self.tx)]

    def handle(self, pkt: bytes) -> bytes:
        self.requests.append(pkt)
        protocol, _length, seq, opcode = struct.unpack_from(">HHHH", pkt)
        if opcode in self.captured:
            data = bytearray(self.captured[opcode])
            data[4:6] = struct.pack(">H", seq)
            return bytes(data)
        if opcode == arc.OP_DEVICE_NAME:
            return _answer(protocol, seq, opcode, 1, self.name.encode() + b"\0")
        if opcode == arc.OP_CHANNEL_COUNT:
            body = struct.pack(">HHH", 0x0DF9, len(self.tx), len(self.rx)) + bytes(32)
            return _answer(protocol, seq, opcode, 1, body)
        if opcode == arc.OP_TX_CHANNELS:
            return self._tx_page(protocol, seq, struct.unpack_from(">H", pkt, 12)[0])
        if opcode == arc.OP_TX_FRIENDLY_NAMES:
            return self._tx_labels(protocol, seq, *struct.unpack_from(">HH", pkt, 12))
        if opcode == arc.OP_RX_CHANNELS:
            return self._rx_page(protocol, seq, struct.unpack_from(">H", pkt, 12)[0])
        if opcode in (arc.OP_SUBSCRIPTION_PAGE, arc.OP_SUBSCRIPTION_ADD, arc.OP_SUBSCRIPTION_REMOVE):
            if self.refuse:
                return _answer(protocol, seq, opcode, 0x0022, b"")
            if not self.ignore_writes:
                self._write(opcode, pkt)
            self.captured.clear()
            return _answer(protocol, seq, opcode, 1, bytes(10))
        return _answer(protocol, seq, opcode, 0x0022, b"")

    def _write(self, opcode: int, pkt: bytes) -> None:
        def text(ptr: int) -> str | None:
            return None if ptr == 0 else pkt[ptr : pkt.index(b"\0", ptr)].decode()

        if opcode == arc.OP_SUBSCRIPTION_PAGE:
            count = pkt[19]
            for i in range(count):
                rx, _media, ch_ptr, dev_ptr = struct.unpack_from(">HHHH", pkt, 20 + 8 * i)
                self._set(rx, text(ch_ptr), text(dev_ptr))
        elif opcode == arc.OP_SUBSCRIPTION_ADD:
            for i in range(pkt[11]):
                _zero, rx, ch_ptr, dev_ptr = struct.unpack_from(">BBHH", pkt, 12 + 6 * i)
                self._set(rx, text(ch_ptr), text(dev_ptr))
        else:
            (count,) = struct.unpack_from(">I", pkt, 8)
            for i in range(count):
                self._set(struct.unpack_from(">I", pkt, 12 + 4 * i)[0], None, None)

    def _set(self, rx: int, channel: str | None, device: str | None) -> None:
        ch = self.rx[rx - 1]
        ch.tx_channel, ch.tx_device = channel, device
        self.resolve(ch)

    def _tx_page(self, protocol: int, seq: int, start: int) -> bytes:
        names = self.tx[start - 1 : start - 1 + arc.TX_PER_PAGE]
        n = len(names)
        fmt_ptr = 10 + 2 + 8 * n
        offsets, blob = _strings(fmt_ptr + 16, names)
        body = bytearray(bytes([n, n]))
        for i, name in enumerate(names):
            body += struct.pack(">HHHH", start + i, 0x0007, fmt_ptr, offsets[name])
        more = start - 1 + n < len(self.tx)
        return _answer(protocol, seq, arc.OP_TX_CHANNELS, 0x8112 if more else 1, bytes(body) + FORMAT_48K + blob)

    def _tx_labels(self, protocol: int, seq: int, start: int, end: int) -> bytes:
        nums = [k for k in sorted(self.labels) if start <= k <= (end or len(self.tx))]
        offsets, blob = _strings(10 + 2 + 6 * len(nums), [self.labels[k] for k in nums])
        body = bytearray(bytes([min(arc.TX_PER_PAGE, len(self.tx)), len(nums)]))
        for k in nums:
            body += struct.pack(">HHH", 0, k, offsets[self.labels[k]])
        return _answer(protocol, seq, arc.OP_TX_FRIENDLY_NAMES, 1, bytes(body) + blob)

    def _rx_page(self, protocol: int, seq: int, start: int) -> bytes:
        chans = self.rx[start - 1 : start - 1 + arc.RX_PER_PAGE]
        n = len(chans)
        fmt_ptr = 10 + 2 + 20 * n
        texts = [t for c in chans for t in (c.name, c.tx_channel, c.tx_device) if t]
        offsets, blob = _strings(fmt_ptr + 16, texts)
        body = bytearray(bytes([n, n]))
        for i, c in enumerate(chans):
            body += struct.pack(
                ">HHHHHHHHI",
                start + i,
                0x0006,
                fmt_ptr,
                offsets[c.tx_channel] if c.tx_channel else 0,
                offsets[c.tx_device] if c.tx_device else 0,
                offsets[c.name],
                c.rx_status,
                c.status,
                0,
            )
        more = start - 1 + n < len(self.rx)
        return _answer(protocol, seq, arc.OP_RX_CHANNELS, 0x8112 if more else 1, bytes(body) + FORMAT_48K + blob)


class FakeTransport(ArcTransport):
    """ArcTransport without sockets: requests go to simulated devices by host."""

    hosts: dict[str, FakeDanteDevice] = {}  # noqa: RUF012 - shared test state, reset per test

    async def async_start(self) -> None:
        return

    async def request(self, host, port, build, *, opcode, timeout=1.0, retries=1):  # type: ignore[override]
        dev = self.hosts.get(host)
        if dev is None or not dev.online:
            raise CannotConnect(f"{host}: no answer")
        seq = self.next_seq()
        resp = arc.parse_header(dev.handle(build(seq)))
        assert resp.seq == seq
        if resp.opcode != opcode:
            raise CannotConnect("unexpected answer")
        return resp


def studio_network() -> dict[str, FakeDanteDevice]:
    """Two devices like in the studio, answering with the captured packets until something is written."""
    network: dict[str, FakeDanteDevice] = {}
    avio = FakeDanteDevice(
        "AVIOAES3-0d0e0f",
        ["CH1", "CH2"],
        [FakeRx("CH1", "61", "Example-WING-Fullsize", 1, 0), FakeRx("CH2", "62", "Example-WING-Fullsize", 1, 0)],
        network=network,
        captured={
            arc.OP_DEVICE_NAME: STUDIO_AVIO_NAME,
            arc.OP_CHANNEL_COUNT: STUDIO_AVIO_COUNT,
            arc.OP_TX_CHANNELS: STUDIO_AVIO_TX,
            arc.OP_TX_FRIENDLY_NAMES: STUDIO_AVIO_TX_LABELS,
            arc.OP_RX_CHANNELS: STUDIO_AVIO_RX,
        },
    )
    da = FakeDanteDevice(
        "DA-22UC-0a0b0c",
        ["CH1", "CH2"],
        [FakeRx("CH1", "CH1", "DA11AEN-010203", 1, 0), FakeRx("CH2", "CH2", "DA11AEN-010203", 1, 0)],
        network=network,
        captured={arc.OP_DEVICE_NAME: STUDIO_DA_NAME, arc.OP_RX_CHANNELS: STUDIO_DA_RX},
    )
    network[avio.name] = avio
    network[da.name] = da
    return network
