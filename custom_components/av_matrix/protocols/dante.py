"""Dante® protocol: identities, source registry and the ARC wire format.

Source = one TX channel of a Dante device, identity ``"<tx channel>@<device>"`` (the notation of
Dante Controller, e.g. ``"Mic 3@STAGEBOX-01"``). Destination = one RX channel of a device.
Routing = setting (or clearing) the subscription of an RX channel.

The control protocol ("ARC", UDP 4440) is not public. The packet layouts below follow the
reverse-engineering work of the netaudio project by Christopher Ritsen
(https://github.com/chris-ritsen/network-audio-controller, released into the public domain under
the Unlicense) and were checked against real devices. The logic is re-implemented here; no code
was copied. See NOTICE.

Dante® is a registered trademark of Audinate Group Pty Ltd. This is an unofficial, unaffiliated
implementation.

No Home Assistant imports here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from .base import SourceRegistry, natural_key

ARC_SERVICE_TYPE = "_netaudio-arc._udp.local."
ARC_PORT = 4440

#: Protocol id of the classic ARC requests (understood by every device we know).
PROTOCOL_LEGACY = 0x27FF
#: ARC revisions that require the paged subscription command (0x3410) for writes.
MODERN_PROTOCOLS = (0x2809, 0x280C, 0x280F)

OP_CHANNEL_COUNT = 0x1000
OP_DEVICE_NAME = 0x1002
OP_TX_CHANNELS = 0x2000
OP_TX_FRIENDLY_NAMES = 0x2010
OP_RX_CHANNELS = 0x3000
OP_SUBSCRIPTION_ADD = 0x3010
OP_SUBSCRIPTION_REMOVE = 0x3014
OP_SUBSCRIPTION_PAGE = 0x3410

RESULT_SUCCESS = 0x0001
RESULT_MORE_PAGES = 0x8112
RESULTS_OK = (RESULT_SUCCESS, RESULT_MORE_PAGES)

HEADER_SIZE = 10  # protocol, length, sequence, opcode, result (request: 0)
RX_PER_PAGE = 16
TX_PER_PAGE = 32
RX_RECORD = 20
TX_RECORD = 8
TX_FRIENDLY_RECORD = 6
LEGACY_SUBSCRIPTION_BATCH = 16
SUBSCRIPTION_PAGE_CAPACITY = 32
MEDIA_AUDIO = 3


class ArcError(Exception):
    """Malformed or unexpected ARC packet."""


# ------------------------------------------------------------------- identities
def source_id(channel: str, device: str) -> str:
    """``("Mic 3", "STAGEBOX")`` → ``"Mic 3@STAGEBOX"``."""
    return f"{channel}@{device}"


def split_source(source: str) -> tuple[str, str]:
    """``"Mic 3@STAGEBOX"`` → ``("Mic 3", "STAGEBOX")``. Dante device names cannot contain ``@``."""
    channel, sep, device = source.rpartition("@")
    if not sep or not channel or not device:
        raise ValueError(f"not a Dante source (expected 'channel@device'): {source!r}")
    return channel, device


class DanteSourceRegistry(SourceRegistry):
    """Dante source registry: a TX channel is live while its device answers ARC queries."""

    protocol = "dante"
    placeholder_re = None
    grouped = True

    def sort_key(self, source_id: str) -> Any:
        """By device, then channel (CH2 before CH10)."""
        channel, _, device = source_id.rpartition("@")
        return (natural_key(device), natural_key(channel))

    def describe(self, source_id: str) -> dict[str, str]:
        try:
            channel, device = split_source(source_id)
        except ValueError:
            return {}
        return {"group": device, "channel": channel}


def arc_protocol_id(version: str | None) -> int:
    """``arcp_vers`` from the mDNS TXT record (e.g. ``"2.8.9"``) → ARC protocol id (``0x2809``).

    Unknown/old versions → the legacy id. Newer revisions are capped at the highest known one.
    """
    try:
        major, minor, patch = (int(p) for p in str(version).split("."))
    except (TypeError, ValueError):
        return PROTOCOL_LEGACY
    if not (0 <= major <= 15 and 0 <= minor <= 15 and 0 <= patch <= 255):
        return PROTOCOL_LEGACY
    value = (major << 12) | (minor << 8) | patch
    known = [p for p in MODERN_PROTOCOLS if p <= value]
    return known[-1] if known else PROTOCOL_LEGACY


def is_modern(protocol_id: int) -> bool:
    return protocol_id in MODERN_PROTOCOLS


# ---------------------------------------------------------------------- framing
def build_packet(protocol_id: int, opcode: int, seq: int, body: bytes) -> bytes:
    """ARC request: protocol, total length, sequence, opcode, then the body."""
    length = 8 + len(body)
    if length > 0xFFFF:
        raise ArcError("packet too large")
    return struct.pack(">HHHH", protocol_id, length, seq & 0xFFFF, opcode) + body


@dataclass(frozen=True, slots=True)
class Response:
    protocol_id: int
    seq: int
    opcode: int
    result: int
    data: bytes  # the whole packet - string pointers are absolute offsets into it

    @property
    def ok(self) -> bool:
        return self.result in RESULTS_OK

    @property
    def more(self) -> bool:
        return self.result == RESULT_MORE_PAGES


def parse_header(data: bytes) -> Response:
    if len(data) < HEADER_SIZE:
        raise ArcError("short packet")
    protocol_id, length, seq, opcode, result = struct.unpack_from(">HHHHH", data)
    if length != len(data):
        raise ArcError("length mismatch")
    return Response(protocol_id, seq, opcode, result, bytes(data))


def _u16(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise ArcError("truncated packet")
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ArcError("truncated packet")
    return struct.unpack_from(">I", data, offset)[0]


def _string(data: bytes, pointer: int) -> str | None:
    """Zero-terminated UTF-8 string at an absolute offset (0 = no string)."""
    if pointer == 0:
        return None
    if pointer >= len(data):
        raise ArcError("string pointer out of range")
    end = data.find(b"\0", pointer)
    if end < 0:
        raise ArcError("unterminated string")
    return data[pointer:end].decode("utf-8", errors="replace")


def _sample_rate(data: bytes, pointer: int) -> int | None:
    """Channel format block (sample rate u32, then encoding …) - None if absent/odd."""
    if pointer == 0 or pointer + 8 > len(data):
        return None
    rate = _u32(data, pointer)
    return rate if 8000 <= rate <= 384000 else None


def page_query(start: int, end: int = 0) -> bytes:
    """Body of a paged channel query: ``0000 0001 <first channel> <last channel|0>``."""
    return struct.pack(">HHHH", 0, 1, start, end)


# ------------------------------------------------------------------- requests
def req_device_name(seq: int) -> bytes:
    return build_packet(PROTOCOL_LEGACY, OP_DEVICE_NAME, seq, b"\0\0")


def req_channel_count(seq: int) -> bytes:
    return build_packet(PROTOCOL_LEGACY, OP_CHANNEL_COUNT, seq, b"\0\0")


def req_tx_channels(seq: int, page: int) -> bytes:
    return build_packet(PROTOCOL_LEGACY, OP_TX_CHANNELS, seq, page_query(page * TX_PER_PAGE + 1))


def req_tx_friendly_names(seq: int, page: int, tx_count: int) -> bytes:
    start = page * TX_PER_PAGE + 1
    return build_packet(
        PROTOCOL_LEGACY, OP_TX_FRIENDLY_NAMES, seq, page_query(start, min(tx_count, start + TX_PER_PAGE - 1))
    )


def req_rx_channels(seq: int, page: int) -> bytes:
    return build_packet(PROTOCOL_LEGACY, OP_RX_CHANNELS, seq, page_query(page * RX_PER_PAGE + 1))


def _check_subscription(rx: int, channel: str, device: str) -> None:
    if not 1 <= rx <= 0xFFFF:
        raise ArcError("invalid RX channel")
    if not channel or not device or "\0" in channel + device:
        raise ArcError("invalid subscription target")
    if len(channel.encode()) > 31 or len(device.encode()) > 31:
        raise ArcError("Dante names are limited to 31 bytes")


def req_subscribe_legacy(seq: int, routes: list[tuple[int, str, str]]) -> bytes:
    """Classic subscription (0x3010): up to 16 ``(rx channel, tx channel, tx device)`` in one packet."""
    if not 1 <= len(routes) <= LEGACY_SUBSCRIPTION_BATCH:
        raise ArcError("1-16 subscriptions per packet")
    records = 4 + 6 * len(routes)
    table = 8 + max(records, 44)  # string table starts at an absolute offset >= 52
    strings = bytearray()
    body = bytearray(struct.pack(">HBB", 0, 0x02, len(routes)))
    for rx, channel, device in routes:
        _check_subscription(rx, channel, device)
        if rx > 0xFF:
            raise ArcError("RX channel out of range for this device")
        ch_ptr = table + len(strings)
        strings += channel.encode() + b"\0"
        dev_ptr = table + len(strings)
        strings += device.encode() + b"\0"
        body += struct.pack(">BBHH", 0, rx, ch_ptr, dev_ptr)
    body += bytes(table - 8 - len(body))
    return build_packet(PROTOCOL_LEGACY, OP_SUBSCRIPTION_ADD, seq, bytes(body + strings))


def req_unsubscribe_legacy(seq: int, rx_channels: list[int]) -> bytes:
    """Classic removal (0x3014): count + one u32 per RX channel."""
    if not rx_channels:
        raise ArcError("no channels")
    body = struct.pack(">I", len(rx_channels)) + b"".join(struct.pack(">I", rx) for rx in rx_channels)
    return build_packet(PROTOCOL_LEGACY, OP_SUBSCRIPTION_REMOVE, seq, body)


def req_subscription_page(
    seq: int,
    protocol_id: int,
    capacity: int,
    records: list[tuple[int, str | None, str | None]],
    media: int = MEDIA_AUDIO,
) -> bytes:
    """Paged subscription (0x3410, ARC 2.8.9+). ``(rx, None, None)`` clears the RX channel.

    Layout: 8 zero bytes, ``0x0800``, capacity, count, then ``capacity`` records of
    ``rx u16, media u16, tx channel ptr, tx device ptr``, then the string table.
    """
    if not is_modern(protocol_id):
        raise ArcError("paged subscriptions need ARC 2.8.9 or newer")
    capacity = max(1, min(capacity, SUBSCRIPTION_PAGE_CAPACITY))
    if not 1 <= len(records) <= capacity:
        raise ArcError("too many subscriptions for one page")
    table = 20 + capacity * 8
    strings = bytearray()
    offsets: dict[str, int] = {}

    def intern(text: str) -> int:
        if protocol_id == 0x280F and text in offsets:
            return offsets[text]
        offsets[text] = table + len(strings)
        strings.extend(text.encode() + b"\0")
        return offsets[text]

    body = bytearray(bytes(8) + struct.pack(">HBB", 0x0800, capacity, len(records)))
    seen: set[int] = set()
    for rx, channel, device in records:
        if rx in seen:
            raise ArcError("RX channel twice in one page")
        seen.add(rx)
        if channel is None or device is None:
            body += struct.pack(">HHHH", rx, media, 0, 0)
            continue
        _check_subscription(rx, channel, device)
        body += struct.pack(">HHHH", rx, media, intern(channel), intern(device))
    body += bytes(table - 8 - len(body))
    return build_packet(protocol_id, OP_SUBSCRIPTION_PAGE, seq, bytes(body + strings))


# ------------------------------------------------------------------ responses
def _expect(resp: Response, opcode: int) -> None:
    if resp.opcode != opcode:
        raise ArcError(f"unexpected opcode {resp.opcode:#06x}")
    if not resp.ok:
        raise ArcError(f"device answered {resp.result:#06x}")


def parse_device_name(resp: Response) -> str:
    _expect(resp, OP_DEVICE_NAME)
    name = _string(resp.data, HEADER_SIZE)
    if not name:
        raise ArcError("empty device name")
    return name


def parse_channel_count(resp: Response) -> tuple[int, int]:
    """→ ``(tx count, rx count)``."""
    _expect(resp, OP_CHANNEL_COUNT)
    return _u16(resp.data, 12), _u16(resp.data, 14)


@dataclass(slots=True)
class TxChannel:
    number: int
    name: str  # default name, e.g. "01" / "CH1"
    friendly_name: str | None = None  # label set in Dante Controller
    sample_rate: int | None = None

    @property
    def label(self) -> str:
        """Name used in subscriptions (the label if set)."""
        return self.friendly_name or self.name


def parse_tx_channels(resp: Response) -> list[TxChannel]:
    """TX channel page (0x2000): ``count/count`` header + 8-byte records ``number, flags, format ptr, name ptr``."""
    _expect(resp, OP_TX_CHANNELS)
    data = resp.data
    body = HEADER_SIZE
    count = data[body + 1] if len(data) > body + 1 else 0
    channels: list[TxChannel] = []
    framed = data[body : body + 2] != b"\0\0"
    for i in range(count if framed else TX_PER_PAGE):
        rec = body + 2 + i * TX_RECORD
        number = _u16(data, rec)
        if number == 0:
            break
        name = _string(data, _u16(data, rec + 6))
        if name is None:
            raise ArcError("TX channel without a name")
        channels.append(TxChannel(number, name, sample_rate=_sample_rate(data, _u16(data, rec + 4))))
    return channels


def parse_tx_friendly_names(resp: Response) -> dict[int, str]:
    """Labels page (0x2010): header ``max/named`` + 6-byte records ``?, number, name ptr`` (only labelled channels)."""
    _expect(resp, OP_TX_FRIENDLY_NAMES)
    data = resp.data
    body = HEADER_SIZE
    if len(data) < body + 2:
        return {}
    named = data[body + 1]
    out: dict[int, str] = {}
    for i in range(named):
        rec = body + 2 + i * TX_FRIENDLY_RECORD
        number = _u16(data, rec + 2)
        name = _string(data, _u16(data, rec + 4))
        if number and name:
            out[number] = name
    return out


@dataclass(slots=True)
class RxChannel:
    number: int
    name: str
    tx_channel: str | None = None
    tx_device: str | None = None  # "." = this device (local loopback)
    rx_status: int = 0
    status: int = 0  # subscription status code
    flags: int = 0
    sample_rate: int | None = None

    @property
    def subscribed(self) -> bool:
        return bool(self.tx_channel and self.tx_device)

    @property
    def can_subscribe_self(self) -> bool:
        return bool(self.flags & 0x0008)


def parse_rx_channels(resp: Response) -> list[RxChannel]:
    """RX channel page (0x3000): ``max/count`` header + 20-byte records
    ``number, flags, format ptr, tx channel ptr, tx device ptr, rx name ptr, rx status, subscription status, …``.
    """
    _expect(resp, OP_RX_CHANNELS)
    data = resp.data
    body = HEADER_SIZE
    if len(data) < body + 2:
        raise ArcError("truncated RX page")
    count = data[body + 1]
    channels: list[RxChannel] = []
    for i in range(count):
        rec = body + 2 + i * RX_RECORD
        number = _u16(data, rec)
        if number == 0:
            break
        name = _string(data, _u16(data, rec + 10))
        if name is None:
            raise ArcError("RX channel without a name")
        channels.append(
            RxChannel(
                number=number,
                name=name,
                flags=_u16(data, rec + 2),
                sample_rate=_sample_rate(data, _u16(data, rec + 4)),
                tx_channel=_string(data, _u16(data, rec + 6)),
                tx_device=_string(data, _u16(data, rec + 8)),
                rx_status=_u16(data, rec + 12),
                status=_u16(data, rec + 14),
            )
        )
    return channels


# --------------------------------------------------------- subscription status
#: Our states (sensor values) of an RX subscription.
SUB_NONE = "none"
SUB_SUBSCRIBED = "subscribed"
SUB_SELF = "self"
SUB_IN_PROGRESS = "in_progress"
SUB_UNRESOLVED = "unresolved"
SUB_IDLE = "idle"
SUB_WARNING = "warning"
SUB_ERROR = "error"
SUBSCRIPTION_STATES = (
    SUB_NONE,
    SUB_SUBSCRIBED,
    SUB_SELF,
    SUB_IN_PROGRESS,
    SUB_UNRESOLVED,
    SUB_IDLE,
    SUB_WARNING,
    SUB_ERROR,
)

# code → (Dante name, our state, explanation). Names/explanations after Dante Controller's wording
# as collected by the netaudio project.
_STATUS: dict[int, tuple[str, str, str]] = {
    0x00: ("NONE", SUB_NONE, "No subscription"),
    0x02: ("RESOLVED", SUB_IN_PROGRESS, "Source found, not yet processed"),
    0x03: ("RESOLVE_FAIL", SUB_ERROR, "Error while resolving the channel name"),
    0x04: ("SUBSCRIBE_SELF", SUB_SELF, "Subscribed to a channel of this device (local loopback)"),
    0x05: ("RESOLVED_NONE", SUB_UNRESOLVED, "The source channel does not exist on the network"),
    0x07: ("IDLE", SUB_IDLE, "Flow configured, but not enough information to connect"),
    0x08: ("IN_PROGRESS", SUB_IN_PROGRESS, "Setting up the flow"),
    0x09: ("DYNAMIC", SUB_SUBSCRIBED, "Subscribed (unicast)"),
    0x0A: ("STATIC", SUB_SUBSCRIBED, "Subscribed (multicast)"),
    0x0E: ("MANUAL", SUB_SUBSCRIBED, "Manually configured flow"),
    0x0F: ("NO_CONNECTION", SUB_ERROR, "Could not reach the transmitter"),
    0x10: ("CHANNEL_FORMAT", SUB_ERROR, "Channel formats do not match"),
    0x11: ("BUNDLE_FORMAT", SUB_ERROR, "Flow formats do not match"),
    0x12: ("NO_RX", SUB_ERROR, "Receiver is out of flows"),
    0x13: ("RX_FAIL", SUB_ERROR, "Receiver could not set up the flow"),
    0x14: ("NO_TX", SUB_ERROR, "Transmitter is out of flows"),
    0x15: ("TX_FAIL", SUB_ERROR, "Transmitter could not set up the flow"),
    0x16: ("QOS_FAIL_RX", SUB_ERROR, "Receiver bandwidth exceeded"),
    0x17: ("QOS_FAIL_TX", SUB_ERROR, "Transmitter bandwidth exceeded"),
    0x18: ("TX_REJECTED_ADDR", SUB_ERROR, "Transmitter rejected the receiver's address"),
    0x19: ("INVALID_MSG", SUB_ERROR, "Transmitter rejected the request"),
    0x1A: ("CHANNEL_LATENCY", SUB_ERROR, "Source needs more latency than the receiver supports"),
    0x1B: ("CLOCK_DOMAIN", SUB_ERROR, "Transmitter and receiver are in different clock domains"),
    0x1C: ("UNSUPPORTED", SUB_ERROR, "Feature not supported by the device"),
    0x1D: ("RX_LINK_DOWN", SUB_ERROR, "Receiver link is down"),
    0x1E: ("TX_LINK_DOWN", SUB_ERROR, "Transmitter link is down"),
    0x1F: ("DYNAMIC_PROTOCOL", SUB_ERROR, "No suitable protocol for a dynamic connection"),
    0x20: ("INVALID_CHANNEL", SUB_ERROR, "Channel does not exist"),
    0x21: ("TX_SCHEDULER_FAILURE", SUB_ERROR, "Transmitter scheduler failure"),
    0x22: ("SUBSCRIBE_SELF_POLICY", SUB_ERROR, "This device does not allow subscriptions to itself"),
    0x23: ("TX_NOT_READY", SUB_WARNING, "External issue with the TX channel"),
    0x24: ("RX_NOT_READY", SUB_WARNING, "External issue with the RX channel"),
    0x25: ("TX_FANOUT_LIMIT_REACHED", SUB_ERROR, "Transmitter cannot supply more unicast flows"),
    0x26: ("TX_CHANNEL_ENCRYPTED", SUB_ERROR, "Receiver does not support the signal encryption"),
    0x27: ("TX_RESPONSE_UNEXPECTED", SUB_ERROR, "Unexpected response from the transmitter"),
    0xFF: ("SYSTEM_FAIL", SUB_ERROR, "Unexpected system failure"),
}


@dataclass(frozen=True, slots=True)
class SubscriptionStatus:
    state: str
    code: int
    name: str
    detail: str
    extra: dict[str, str] = field(default_factory=dict)


def subscription_status(rx: RxChannel) -> SubscriptionStatus:
    """Decode the subscription status of an RX channel."""
    if not rx.subscribed:
        return SubscriptionStatus(SUB_NONE, rx.status, "NONE", "No subscription")
    if rx.tx_device == "." and rx.status in (0x01, 0x04, 0x09):
        return SubscriptionStatus(SUB_SELF, rx.status, "SUBSCRIBE_SELF", _STATUS[0x04][2])
    if rx.status == 0x01:  # meaning depends on the receiver status
        if rx.rx_status == 0x0101:
            return SubscriptionStatus(SUB_SUBSCRIBED, rx.status, "DYNAMIC", "Subscribed (unicast)")
        return SubscriptionStatus(
            SUB_UNRESOLVED, rx.status, "UNRESOLVED", "The transmitting device is not on the network"
        )
    name, state, detail = _STATUS.get(rx.status, (f"UNKNOWN_{rx.status:#06x}", SUB_ERROR, "Unknown status"))
    return SubscriptionStatus(state, rx.status, name, detail)


def format_sample_rate(rate: int | None) -> str | None:
    """``48000`` → ``"48 kHz"``, ``44100`` → ``"44.1 kHz"``."""
    if not rate:
        return None
    return f"{rate / 1000:g} kHz"
