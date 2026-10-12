"""SMPTE ST 2110 via AMWA NMOS: data model, grouping, compatibility and the source registry.

Pure logic, no I/O and no Home Assistant imports. The network side lives in ``drivers/nmos.py``.

* **IS-04** (Node API) describes what a device has: Node → Devices → Sources → Flows → Senders, and Receivers.
* **IS-05** (Connection API) connects a Receiver to a Sender.
* **BCP-002-01** ("Natural Grouping") says which Senders/Receivers of a device belong together
  (tag ``urn:x-nmos:tag:grouphint/v1.0`` = ``"<group name>:<role>[:<scope>]"``).
* **BCP-004-01** (Receiver Capabilities) says which formats a Receiver accepts (``caps.constraint_sets``).

What the operator sees
----------------------
One **source** of the matrix is a *group of senders* (video + its audio + ancillary data) and one **destination**
is a *group of receivers*. Routing a source to a destination connects every layer the two have in common. Identity
of a source is ``"<group>@<device>"`` (like Dante's ``"<channel>@<device>"``), of a destination
``"<device>:<group>"``; ``"<device>:<group>/audio"`` is the audio layer of that destination on its own
(audio breakaway).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from .base import SourceRegistry, natural_key

PROTOCOL = "st2110"
NODE_SERVICE_TYPE = "_nmos-node._tcp.local."
QUERY_SERVICE_TYPE = "_nmos-query._tcp.local."
#: IS-04 versions this implementation understands, best first (v1.0 has no receiver caps worth using).
NODE_API_VERSIONS = ("v1.3", "v1.2", "v1.1")
#: IS-05 versions, best first.
CONNECTION_API_VERSIONS = ("v1.1", "v1.0")
QUERY_API_VERSIONS = NODE_API_VERSIONS

GROUPHINT_TAG = "urn:x-nmos:tag:grouphint/v1.0"
TAG_MANUFACTURER = "urn:x-nmos:tag:asset:manufacturer/v1.0"  # BCP-002-02, optional
TAG_PRODUCT = "urn:x-nmos:tag:asset:product/v1.0"
CONTROL_CONNECTION = "urn:x-nmos:control:sr-ctrl/"

VIDEO, AUDIO, DATA, MUX = "video", "audio", "data", "mux"
_FORMATS = {
    "urn:x-nmos:format:video": VIDEO,
    "urn:x-nmos:format:audio": AUDIO,
    "urn:x-nmos:format:data": DATA,
    "urn:x-nmos:format:mux": MUX,
}
#: Order in which layers are switched and shown; the first one a destination has is its primary layer.
KIND_ORDER = (VIDEO, MUX, AUDIO, DATA)
KIND_TITLE = {VIDEO: "Bild", AUDIO: "Ton", DATA: "Zusatzdaten", MUX: "Bild+Ton (SDI-Strom)"}

MEDIA_TITLES = {
    "video/raw": "unkomprimiert",
    "video/jxsv": "JPEG XS",
    "video/smpte291": "ANC",
    "video/smpte2022-6": "ST 2022-6",
    "audio/L16": "PCM 16 Bit",
    "audio/L24": "PCM 24 Bit",
    "audio/am824": "AES3 (ST 2110-31)",
}
#: Blackmagic IP10 codec (10:8, ST 2110-22). The RTP encoding name ``vnd.blackmagic-design.ip10`` is documented
#: (Blackmagic IP10 Codec v1.1); that IS-04 reports it as this media type is an assumption until seen on a device.
IP10_MEDIA_TYPE = "video/vnd.blackmagic-design.ip10"
IP10_HINT = re.compile(r"ip10|blackmagic", re.IGNORECASE)

AUDIO_SUFFIX = "/audio"
#: Placeholder source ids for connections this driver did not make itself.
UNKNOWN_SENDER_PREFIX = "sender:"  # receiver is connected to a sender no known node offers
EXTERNAL_PREFIX = "ext:"  # receiver was set up with a bare SDP / manual parameters, no sender id

#: IEEE OUIs → manufacturer (only used when the node does not name its manufacturer itself).
#: 7C-2E-0D is Blackmagic Design's only block in the IEEE registry (checked 2026-10-12).
OUI_MANUFACTURERS = {"7c2e0d": "Blackmagic Design"}

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class NmosError(Exception):
    """A node answered something that is not NMOS."""


# ------------------------------------------------------------------ identities
def source_id(group: str, device: str) -> str:
    """``("SDI 1", "Studio-4x12G")`` → ``"SDI 1@Studio-4x12G"``."""
    return f"{group}@{device}"


def split_source(source: str) -> tuple[str, str]:
    group, sep, device = source.rpartition("@")
    if not sep or not group or not device:
        raise ValueError(f"keine ST-2110-Quelle (erwartet 'Eingang@Gerät'): {source!r}")
    return group, device


def dest_id(device: str, group: str, audio: bool = False) -> str:
    """``("Studio-4x12G", "SDI 1")`` → ``"Studio-4x12G:SDI 1"``; ``audio=True`` appends ``/audio``."""
    return f"{device}:{group}{AUDIO_SUFFIX if audio else ''}"


def split_dest(dest: str) -> tuple[str, str, bool]:
    """→ ``(device, group, audio_only)``. Device names never contain ``:`` (see ``clean_name``)."""
    audio = dest.endswith(AUDIO_SUFFIX)
    core = dest[: -len(AUDIO_SUFFIX)] if audio else dest
    device, sep, group = core.partition(":")
    if not sep or not device or not group:
        raise ValueError(f"kein ST-2110-Ziel (erwartet 'Gerät:Ausgang'): {dest!r}")
    return device, group, audio


def clean_name(text: Any, fallback: str = "") -> str:
    """Names become part of ids: single line, no ``@`` / ``:`` (they separate device and group)."""
    out = " ".join(str(text or "").replace("@", " at ").replace(":", " ").split())
    return out[:60].strip() or fallback


def is_uuid(text: Any) -> bool:
    return isinstance(text, str) and bool(_UUID.match(text))


# ---------------------------------------------------------------------- helpers
def rational(value: Any) -> Fraction | None:
    """``{"numerator": 60000, "denominator": 1001}`` (or a plain number) → Fraction."""
    try:
        if isinstance(value, dict):
            den = value.get("denominator")
            num, den = int(value["numerator"]), 1 if den is None else int(den)
            return Fraction(num, den) if den else None
        if isinstance(value, bool) or value is None:
            return None
        return Fraction(str(value))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def rate_text(rate: Fraction | None) -> str:
    if rate is None:
        return ""
    return f"{float(rate):.2f}".rstrip("0").rstrip(".")


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _tags(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): [str(x) for x in v] for k, v in raw.items() if isinstance(v, list)}


def media_title(media_type: str | None) -> str:
    if not media_type:
        return "unbekanntes Format"
    if media_type in MEDIA_TITLES:
        return MEDIA_TITLES[media_type]
    if IP10_HINT.search(media_type):
        return "Blackmagic IP10"
    return media_type


def is_compressed(media_type: str | None) -> bool | None:
    """True for compressed video (JPEG XS, IP10 …), False for ``video/raw``, None if unknown / not video."""
    if not media_type or not media_type.startswith("video/") or media_type in ("video/smpte291", "video/smpte2022-6"):
        return None
    return media_type != "video/raw"


# ------------------------------------------------------------------- resources
@dataclass(slots=True)
class Flow:
    id: str
    kind: str | None = None
    media_type: str | None = None
    width: int | None = None
    height: int | None = None
    interlaced: bool | None = None
    interlace_mode: str | None = None
    rate: Fraction | None = None
    sampling: str | None = None  # "YCbCr-4:2:2", "RGB" …
    depth: int | None = None
    colorspace: str | None = None
    transfer: str | None = None
    sample_rate: Fraction | None = None
    channels: int | None = None

    @property
    def text(self) -> str:
        """Short description for the operator: ``1920x1080p50 · unkomprimiert`` / ``48 kHz · 2 Kanäle``."""
        if self.kind == VIDEO:
            res = ""
            if self.width and self.height:
                res = f"{self.width}x{self.height}{'i' if self.interlaced else 'p'}{rate_text(self.rate)}"
            return " · ".join(p for p in (res, media_title(self.media_type)) if p)
        if self.kind == AUDIO:
            parts = []
            if self.sample_rate:
                parts.append(f"{float(self.sample_rate) / 1000:g} kHz")
            if self.channels:
                parts.append(f"{self.channels} Kanäle" if self.channels != 1 else "1 Kanal")
            return " · ".join(parts) or media_title(self.media_type)
        return media_title(self.media_type)

    @property
    def resolution(self) -> str | None:
        if self.kind == VIDEO and self.width and self.height:
            return f"{self.width}x{self.height}{'i' if self.interlaced else 'p'}{rate_text(self.rate)}"
        if self.kind == AUDIO and self.sample_rate:
            return f"{float(self.sample_rate) / 1000:g} kHz"
        return None


@dataclass(slots=True)
class Sender:
    id: str
    label: str
    device_id: str
    kind: str | None  # from the flow / source; None if the sender has no flow (no input signal)
    transport: str | None = None
    manifest_href: str | None = None
    tags: dict[str, list[str]] = field(default_factory=dict)
    flow: Flow | None = None
    active: bool | None = None  # IS-04 subscription.active (= IS-05 master_enable), None if not reported
    version: str | None = None


@dataclass(slots=True)
class Receiver:
    id: str
    label: str
    device_id: str
    kind: str | None
    transport: str | None = None
    caps: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, list[str]] = field(default_factory=dict)
    sender_id: str | None = None  # IS-04 subscription
    active: bool = False
    version: str | None = None


@dataclass(slots=True)
class Device:
    id: str
    label: str
    type: str | None = None
    tags: dict[str, list[str]] = field(default_factory=dict)
    connection_href: str | None = None  # base of the IS-05 API incl. version, no trailing slash
    connection_version: str | None = None


@dataclass(slots=True)
class Clock:
    name: str
    ref_type: str | None = None  # "ptp" | "internal"
    locked: bool | None = None
    gmid: str | None = None
    traceable: bool | None = None


@dataclass(slots=True)
class NodeModel:
    """Everything IS-04 tells about one node, already cross-linked."""

    id: str
    label: str = ""
    hostname: str | None = None
    description: str = ""
    tags: dict[str, list[str]] = field(default_factory=dict)
    macs: list[str] = field(default_factory=list)
    clocks: list[Clock] = field(default_factory=list)
    devices: dict[str, Device] = field(default_factory=dict)
    senders: dict[str, Sender] = field(default_factory=dict)
    receivers: dict[str, Receiver] = field(default_factory=dict)


_KIND_WORDS = ((AUDIO, r"audio|\bton\b"), (DATA, r"\banc\b|ancillary|\bdata\b|smpte ?291|-40\b"), (VIDEO, r"video|\bbild\b"))


def _kind_from_words(tags: dict[str, list[str]], label: str) -> str | None:
    """A sender without a flow (no input signal) does not say what it carries; its group role or label may."""
    hint = parse_grouphint(tags)
    for text in (hint[1] if hint else "", label):
        for kind, pattern in _KIND_WORDS:
            if text and re.search(pattern, text, re.IGNORECASE):
                return kind
    return None


def _kind(urn: Any) -> str | None:
    return _FORMATS.get(urn) if isinstance(urn, str) else None


def _sampling(components: Any) -> tuple[str | None, int | None]:
    """IS-04 ``components`` → (``"YCbCr-4:2:2"``, bit depth)."""
    if not isinstance(components, list) or not components:
        return None, None
    comp = {str(c.get("name")): c for c in components if isinstance(c, dict)}
    depth = _int(next(iter(comp.values()), {}).get("bit_depth"))
    names = set(comp)
    if {"R", "G", "B"} <= names:
        return "RGB", depth
    if {"Y", "Cb", "Cr"} <= names:
        yw, yh = _int(comp["Y"].get("width")), _int(comp["Y"].get("height"))
        cw, ch = _int(comp["Cb"].get("width")), _int(comp["Cb"].get("height"))
        if yw and cw and yh and ch:
            if cw == yw and ch == yh:
                return "YCbCr-4:4:4", depth
            if cw * 2 == yw and ch == yh:
                return "YCbCr-4:2:2", depth
            if cw * 2 == yw and ch * 2 == yh:
                return "YCbCr-4:2:0", depth
        return "YCbCr", depth
    return None, depth


def parse_flow(raw: dict[str, Any], source: dict[str, Any] | None) -> Flow:
    kind = _kind(raw.get("format")) or (_kind(source.get("format")) if source else None)
    flow = Flow(id=str(raw.get("id") or ""), kind=kind, media_type=_str(raw.get("media_type")))
    if kind == VIDEO:
        flow.width, flow.height = _int(raw.get("frame_width")), _int(raw.get("frame_height"))
        flow.interlace_mode = _str(raw.get("interlace_mode"))
        flow.interlaced = flow.interlace_mode not in (None, "progressive")
        flow.sampling, flow.depth = _sampling(raw.get("components"))
        flow.colorspace, flow.transfer = _str(raw.get("colorspace")), _str(raw.get("transfer_characteristic"))
    elif kind == AUDIO:
        flow.sample_rate = rational(raw.get("sample_rate"))
        flow.depth = _int(raw.get("bit_depth"))
        channels = source.get("channels") if source else None
        flow.channels = len(channels) if isinstance(channels, list) and channels else None
    flow.rate = rational(raw.get("grain_rate")) or (rational(source.get("grain_rate")) if source else None)
    return flow


def _list(raw: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise NmosError(f"{what}: keine Liste")
    return [r for r in raw if isinstance(r, dict) and is_uuid(r.get("id"))]


def pick_version(offered: Any, supported: tuple[str, ...]) -> str | None:
    """Best common API version. ``offered``: ``["v1.0/", "v1.3/"]`` as the API base lists them, or a CSV string."""
    if isinstance(offered, str):
        offered = offered.split(",")
    if not isinstance(offered, list):
        return None
    have = {str(v).strip().strip("/") for v in offered}
    return next((v for v in supported if v in have), None)


def connection_control(controls: Any, prefer_host: str | None = None) -> tuple[str | None, str | None]:
    """IS-05 base URL (``…/x-nmos/connection/v1.1``) and version from a device's ``controls``."""
    best: tuple[int, int, str, str] | None = None
    for ctrl in controls if isinstance(controls, list) else []:
        if not isinstance(ctrl, dict):
            continue
        ctype, href = str(ctrl.get("type") or ""), str(ctrl.get("href") or "").rstrip("/")
        if not ctype.startswith(CONTROL_CONNECTION) or not href.startswith(("http://", "https://")):
            continue
        version = ctype[len(CONTROL_CONNECTION) :]
        if version not in CONNECTION_API_VERSIONS:
            continue
        rank = (CONNECTION_API_VERSIONS.index(version), 0 if prefer_host and f"//{prefer_host}" in href else 1)
        if best is None or rank < best[:2]:
            best = (*rank, href, version)
    return (best[2], best[3]) if best else (None, None)


def parse_node(
    node: Any, devices: Any, sources: Any, flows: Any, senders: Any, receivers: Any, *, host: str | None = None
) -> NodeModel:
    """Build a ``NodeModel`` from the six Node API lists. Broken entries are skipped, not fatal."""
    if not isinstance(node, dict) or not is_uuid(node.get("id")):
        raise NmosError("self: keine NMOS-Node-Beschreibung")
    model = NodeModel(
        id=node["id"],
        label=str(node.get("label") or ""),
        hostname=_str(node.get("hostname")),
        description=str(node.get("description") or ""),
        tags=_tags(node.get("tags")),
    )
    for iface in node.get("interfaces") if isinstance(node.get("interfaces"), list) else []:
        mac = str(iface.get("port_id") or "").lower() if isinstance(iface, dict) else ""
        if re.fullmatch(r"([0-9a-f]{2}-){5}[0-9a-f]{2}", mac):
            model.macs.append(mac.replace("-", ":"))
    for clk in node.get("clocks") if isinstance(node.get("clocks"), list) else []:
        if isinstance(clk, dict):
            locked = clk.get("locked")
            model.clocks.append(
                Clock(
                    name=str(clk.get("name") or ""),
                    ref_type=_str(clk.get("ref_type")),
                    locked=locked if isinstance(locked, bool) else None,
                    gmid=_str(clk.get("gmid")),
                    traceable=clk.get("traceable") if isinstance(clk.get("traceable"), bool) else None,
                )
            )
    for raw in _list(devices, "devices"):
        href, version = connection_control(raw.get("controls"), host)
        model.devices[raw["id"]] = Device(
            id=raw["id"],
            label=str(raw.get("label") or ""),
            type=_str(raw.get("type")),
            tags=_tags(raw.get("tags")),
            connection_href=href,
            connection_version=version,
        )
    src = {r["id"]: r for r in _list(sources, "sources")}
    flw = {r["id"]: r for r in _list(flows, "flows")}
    for raw in _list(senders, "senders"):
        flow_raw = flw.get(raw.get("flow_id") or "")
        source_raw = src.get(flow_raw.get("source_id") or "") if flow_raw else None
        flow = parse_flow(flow_raw, source_raw) if flow_raw else None
        sub = raw.get("subscription") if isinstance(raw.get("subscription"), dict) else {}
        tags = _tags(raw.get("tags"))
        if GROUPHINT_TAG not in tags and source_raw and GROUPHINT_TAG in _tags(source_raw.get("tags")):
            tags[GROUPHINT_TAG] = _tags(source_raw.get("tags"))[GROUPHINT_TAG]
        label = str(raw.get("label") or "")
        model.senders[raw["id"]] = Sender(
            id=raw["id"],
            label=label,
            device_id=str(raw.get("device_id") or ""),
            kind=flow.kind if flow and flow.kind else _kind_from_words(tags, label),
            transport=_str(raw.get("transport")),
            manifest_href=_str(raw.get("manifest_href")),
            tags=tags,
            flow=flow,
            active=sub.get("active") if isinstance(sub.get("active"), bool) else None,
            version=_str(raw.get("version")),
        )
    for raw in _list(receivers, "receivers"):
        model.receivers[raw["id"]] = parse_receiver(raw)
    return model


def parse_receiver(raw: dict[str, Any]) -> Receiver:
    sub = raw.get("subscription") if isinstance(raw.get("subscription"), dict) else {}
    sender_id = sub.get("sender_id")
    return Receiver(
        id=raw["id"],
        label=str(raw.get("label") or ""),
        device_id=str(raw.get("device_id") or ""),
        kind=_kind(raw.get("format")),
        transport=_str(raw.get("transport")),
        caps=raw.get("caps") if isinstance(raw.get("caps"), dict) else {},
        tags=_tags(raw.get("tags")),
        sender_id=sender_id if is_uuid(sender_id) else None,
        active=bool(sub.get("active")),
        version=_str(raw.get("version")),
    )


# -------------------------------------------------------------------- grouping
@dataclass(slots=True)
class Group:
    """Senders (a source of the matrix) or receivers (a destination) that belong together."""

    name: str
    #: layer → sender / receiver id. A layer is ``(kind, index)``: ``("audio", 0)`` is the first audio stream.
    layers: dict[tuple[str, int], str] = field(default_factory=dict)
    #: True = the device said so (BCP-002-01), False = derived from labels / device structure.
    hinted: bool = False

    def kinds(self) -> list[str]:
        return [k for k in KIND_ORDER if any(kind == k for kind, _ in self.layers)]

    def ordered(self) -> list[tuple[tuple[str, int], str]]:
        return sorted(self.layers.items(), key=lambda item: (KIND_ORDER.index(item[0][0]), item[0][1]))

    @property
    def primary(self) -> str | None:
        kinds = self.kinds()
        return kinds[0] if kinds else None


def parse_grouphint(tags: dict[str, list[str]]) -> tuple[str, str, str] | None:
    """First usable hint → ``(group, role, scope)``; scope is ``device`` (default) or ``node``."""
    for hint in tags.get(GROUPHINT_TAG, []):
        parts = hint.split(":")
        if len(parts) in (2, 3) and parts[0].strip() and parts[1].strip():
            scope = parts[2].strip().lower() if len(parts) == 3 else "device"
            return parts[0].strip(), parts[1].strip(), scope if scope in ("device", "node") else "device"
    return None


_NUMBER = re.compile(r"(\d+)")


def _label_number(label: str) -> int | None:
    """The channel number in a label: ``"SDI 2 Audio"`` → 2. Format numbers (2110, 12G) are ignored."""
    text = re.sub(r"\b(2110|2022|12g|6g|3g|4k|8k|\d+x\d+g?|\d{3,4}[pi]\d*)\b", " ", label, flags=re.IGNORECASE)
    numbers = _NUMBER.findall(text)
    return int(numbers[-1]) if numbers else None


def build_groups(model: NodeModel, role: str) -> list[Group]:
    """Group the senders (``role="sender"``) or receivers (``"receiver"``) of a node.

    1. BCP-002-01 group hints, if the device has them.
    2. A device with at most one video (or mux) stream is one group.
    3. Several video streams: streams whose labels carry the same channel number belong together.
    4. Whatever is left stands alone (never paired by guessing).
    """
    items: dict[str, Any] = model.senders if role == "sender" else model.receivers
    usable = [it for it in items.values() if it.kind in KIND_ORDER]
    groups: dict[tuple[str, str], Group] = {}
    roles: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    rest: dict[str, list[Any]] = {}
    for item in usable:
        hint = parse_grouphint(item.tags)
        if hint is None:
            rest.setdefault(item.device_id, []).append(item)
            continue
        name, hint_role, scope = hint
        key = (model.id if scope == "node" else item.device_id, name)
        groups.setdefault(key, Group(clean_name(name, "Gruppe"), hinted=True))
        roles.setdefault(key, []).append((item.kind, hint_role, item.id))
    for key, members in roles.items():
        # several streams of one kind: order by role name ("audio 1" before "audio 2")
        for kind in KIND_ORDER:
            same = sorted((m for m in members if m[0] == kind), key=lambda m: natural_key(m[1]))
            for index, (_, _, item_id) in enumerate(same):
                groups[key].layers[(kind, index)] = item_id

    out = list(groups.values())
    for device_id, members in rest.items():
        device = model.devices.get(device_id)
        base = clean_name(device.label if device else "", "") or clean_name(model.label, "Gerät")
        main = [m for m in members if m.kind in (VIDEO, MUX)]
        if len(main) <= 1:
            if len(model.devices) > 1:
                name = base
            else:
                name = clean_name(main[0].label, "") if main else ""
                name = name or ("Eingang" if role == "sender" else "Ausgang")
            out.append(_group_of(name, members))
            continue
        numbered: dict[int, list[Any]] = {}
        alone: list[Any] = []
        main_numbers = [_label_number(m.label) for m in main]
        unique = None not in main_numbers and len(set(main_numbers)) == len(main_numbers)
        for member in members:
            number = _label_number(member.label) if unique else None
            if number is not None and number in main_numbers:
                numbered.setdefault(number, []).append(member)
            else:
                alone.append(member)
        for number in sorted(numbered):
            head = next(m for m in numbered[number] if m.kind in (VIDEO, MUX))
            out.append(_group_of(clean_name(head.label, f"Kanal {number}"), numbered[number]))
        for member in alone:
            out.append(_group_of(clean_name(member.label, member.id[:8]), [member]))
    return _unique_names(out)


def _group_of(name: str, members: list[Any]) -> Group:
    group = Group(name)
    for kind in KIND_ORDER:
        same = sorted((m for m in members if m.kind == kind), key=lambda m: natural_key(m.label))
        for index, member in enumerate(same):
            group.layers[(kind, index)] = member.id
    return group


def _unique_names(groups: list[Group]) -> list[Group]:
    groups.sort(key=lambda g: natural_key(g.name))
    seen: dict[str, int] = {}
    for group in groups:
        count = seen.get(group.name.casefold(), 0) + 1
        seen[group.name.casefold()] = count
        if count > 1:
            group.name = f"{group.name} ({count})"
    return groups


# --------------------------------------------------------------- compatibility
_CAP = "urn:x-nmos:cap:format:"


def _flow_value(flow: Flow, param: str) -> Any:
    return {
        "media_type": flow.media_type,
        "frame_width": flow.width,
        "frame_height": flow.height,
        "grain_rate": flow.rate,
        "interlace_mode": flow.interlace_mode,
        "color_sampling": flow.sampling,
        "component_depth": flow.depth if flow.kind == VIDEO else None,
        "colorspace": flow.colorspace,
        "transfer_characteristic": flow.transfer,
        "channel_count": flow.channels,
        "sample_rate": flow.sample_rate,
        "sample_depth": flow.depth if flow.kind == AUDIO else None,
    }.get(param)


def _satisfies(value: Any, constraint: Any) -> bool:
    """BCP-004-01 parameter constraint: ``enum`` and/or ``minimum`` / ``maximum``."""
    if value is None or not isinstance(constraint, dict):
        return True  # nothing known about the stream, or no constraint: do not block
    is_number = isinstance(value, (int, Fraction)) and not isinstance(value, bool)
    if "enum" in constraint and isinstance(constraint["enum"], list):
        allowed = constraint["enum"]
        if is_number:
            if not any(rational(a) == Fraction(value) for a in allowed):
                return False
        elif value not in allowed:
            return False
    if is_number:
        low, high = rational(constraint.get("minimum")), rational(constraint.get("maximum"))
        if low is not None and Fraction(value) < low:
            return False
        if high is not None and Fraction(value) > high:
            return False
    return True


_WHY = {
    "media_type": "dieses Format",
    "frame_width": "diese Auflösung",
    "frame_height": "diese Auflösung",
    "grain_rate": "diese Bildrate",
    "interlace_mode": "Halbbilder",
    "color_sampling": "diese Farbabtastung",
    "component_depth": "diese Bittiefe",
    "colorspace": "diesen Farbraum",
    "transfer_characteristic": "diese Übertragungskennlinie (HDR/SDR)",
    "channel_count": "diese Kanalzahl",
    "sample_rate": "diese Abtastrate",
    "sample_depth": "diese Bittiefe",
}


def _transport_base(transport: str | None) -> tuple[str, str]:
    text = (transport or "").removeprefix("urn:x-nmos:transport:")
    base, _, sub = text.partition(".")
    return base, sub


def check_compat(sender: Sender, receiver: Receiver) -> str | None:
    """Why ``sender`` cannot be connected to ``receiver`` – or ``None`` if nothing speaks against it.

    Checks stream kind, transport, media type and the receiver's constraint sets (BCP-004-01). Unknown values
    never block: a sender without a flow (no input signal) or a receiver without caps is accepted.
    """
    if sender.kind and receiver.kind and sender.kind != receiver.kind:
        return f"Quelle liefert {KIND_TITLE.get(sender.kind, sender.kind)}, das Ziel nimmt {KIND_TITLE.get(receiver.kind, receiver.kind)}"
    s_base, s_sub = _transport_base(sender.transport)
    r_base, r_sub = _transport_base(receiver.transport)
    if s_base and r_base and (s_base != r_base or (r_sub and s_sub and r_sub != s_sub)):
        return f"anderer Transport ({sender.transport} → {receiver.transport})"
    flow = sender.flow
    if flow is None:
        return None
    media_types = receiver.caps.get("media_types")
    if isinstance(media_types, list) and media_types and flow.media_type and flow.media_type not in media_types:
        can = ", ".join(sorted({media_title(m) for m in media_types}))
        return f"Ziel kann {media_title(flow.media_type)} nicht empfangen (nur {can})"
    sets = receiver.caps.get("constraint_sets")
    sets = (
        [s for s in sets if isinstance(s, dict) and s.get("urn:x-nmos:cap:meta:enabled", True)] if isinstance(sets, list) else []
    )
    if not sets:
        return None
    fewest: list[str] | None = None
    for cset in sets:
        failed = [
            key[len(_CAP) :]
            for key, constraint in cset.items()
            if key.startswith(_CAP) and not _satisfies(_flow_value(flow, key[len(_CAP) :]), constraint)
        ]
        if not failed:
            return None
        if fewest is None or len(failed) < len(fewest):
            fewest = failed
    reasons = list(dict.fromkeys(_WHY.get(p, p) for p in fewest or []))
    return f"Ziel kann {' und '.join(reasons[:2])} nicht ({flow.text})"


# ------------------------------------------------------------------------- SDP
@dataclass(slots=True)
class SdpInfo:
    """The few SDP facts worth showing (diagnostics, ``nmos-check``) and needed as a fallback."""

    media: str | None = None  # video | audio
    port: int | None = None
    payload: int | None = None
    encoding: str | None = None  # raw, L24, smpte291, jxsv …
    destination: str | None = None  # multicast group or unicast address
    source: str | None = None  # source filter (SSM)
    fmtp: dict[str, str] = field(default_factory=dict)
    ptp: str | None = None  # ts-refclk
    legs: int = 0  # number of m= lines (2 = ST 2022-7 redundancy)

    @property
    def media_type(self) -> str | None:
        return f"{self.media}/{self.encoding}" if self.media and self.encoding else None


def parse_sdp(text: str) -> SdpInfo:
    """Minimal SDP reader (first media section). Never raises on odd input."""
    info = SdpInfo()
    session_conn: str | None = None
    in_first = False
    for line in text.replace("\r", "").split("\n"):
        key, _, value = line.partition("=")
        value = value.strip()
        if key == "m":
            info.legs += 1
            in_first = info.legs == 1
            if in_first:
                parts = value.split()
                info.media = parts[0] if parts else None
                info.port = _int(parts[1].split("/")[0]) if len(parts) > 1 else None
                info.payload = _int(parts[3]) if len(parts) > 3 else None
            continue
        if info.legs and not in_first:
            continue
        if key == "c":
            address = value.split()[-1].split("/")[0] if value else None
            if info.legs:
                info.destination = address
            else:
                session_conn = address
        elif key == "a":
            name, _, arg = value.partition(":")
            if name == "rtpmap":
                info.encoding = arg.split()[-1].split("/")[0] if arg.split() else None
            elif name == "fmtp":
                for pair in arg.partition(" ")[2].split(";"):
                    k, _, v = pair.strip().partition("=")
                    if k:
                        info.fmtp[k] = v
            elif name == "source-filter":
                parts = arg.split()
                info.source = parts[-1] if len(parts) >= 5 else None
            elif name == "ts-refclk" and info.ptp is None:
                info.ptp = arg
    info.destination = info.destination or session_conn
    return info


def is_sdp(text: Any) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("v=0")


# ------------------------------------------------------- what kind of device?
#: Device types of the matrix (label, illustration under ``devices/<icon>.svg``).
DEVICE_TYPES: dict[str, tuple[str, str]] = {
    "converter": ("Konverter", "st2110_converter"),
    "presentation": ("Präsentationswandler", "st2110_presentation"),
    "multi": ("Mehrkanal-Konverter", "st2110_multi"),
    "card": ("I/O-Karte", "st2110_card"),
    "device": ("ST-2110-Gerät", "st2110_device"),
}
_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("presentation", r"presentation"),
    ("multi", r"\b4\s*x\s*12g|\b8\s*x\s*12g|\b3\s*x\s*3g"),
    ("card", r"decklink|\bcard\b|karte"),
    ("converter", r"\bmini\b|bidirect|ip to hdmi|hdmi to ip|converter|konverter|opengear"),
)
_MODEL_HINT = re.compile(r"blackmagic|2110 ip|decklink", re.IGNORECASE)


def classify_device(model: NodeModel) -> tuple[str | None, str | None, str]:
    """→ ``(manufacturer, model name, device type)``. Only what the node itself tells; nothing is guessed.

    Manufacturer: BCP-002-02 asset tag, else the IEEE OUI of an interface. Model: asset tag, else a node /
    device label or description that names a product. Type: product words, else the structure of the device
    (several video groups = multi-channel converter), else the neutral ``device``.
    """
    tags = dict(model.tags)
    for device in model.devices.values():
        for key, value in device.tags.items():
            tags.setdefault(key, value)
    manufacturer = next(iter(tags.get(TAG_MANUFACTURER, [])), None)
    if not manufacturer:
        manufacturer = next(
            (OUI_MANUFACTURERS[m.replace(":", "")[:6]] for m in model.macs if m.replace(":", "")[:6] in OUI_MANUFACTURERS), None
        )
    texts = [model.description, model.label, *(d.label for d in model.devices.values()), model.hostname or ""]
    product = next(iter(tags.get(TAG_PRODUCT, [])), None)
    if not product:
        product = next((" ".join(t.split()) for t in texts if t and _MODEL_HINT.search(t)), None)
    if product and not manufacturer and re.search(r"blackmagic|decklink", product, re.IGNORECASE):
        manufacturer = "Blackmagic Design"
    haystack = " ".join(filter(None, [product, *texts]))
    for kind, pattern in _TYPE_RULES:
        if re.search(pattern, haystack, re.IGNORECASE):
            return manufacturer, product, kind
    video_tx = sum(1 for s in model.senders.values() if s.kind in (VIDEO, MUX))
    video_rx = sum(1 for r in model.receivers.values() if r.kind in (VIDEO, MUX))
    if max(video_tx, video_rx) >= 2:
        return manufacturer, product, "multi"
    return manufacturer, product, "device"


# -------------------------------------------------------------------- registry
class NmosSourceRegistry(SourceRegistry):
    """ST 2110 sources: a sender group is live while its node answers the Node API."""

    protocol = PROTOCOL
    placeholder_re = None
    grouped = True
    #: The server never receives ST 2110 media (uncompressed video does not fit a Raspberry Pi with 1 GbE):
    #: there is no preview for these sources. That is a property, not an error.
    preview = False

    def sort_key(self, source_id: str) -> Any:
        group, _, device = source_id.rpartition("@")
        return (natural_key(device), natural_key(group))

    def describe(self, source_id: str) -> dict[str, str]:
        try:
            group, device = split_source(source_id)
        except ValueError:
            return {"preview": "none"}
        return {"group": device, "channel": group, "preview": "none"}
