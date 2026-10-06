"""Which device illustration the card shows for a destination or source (``icon_key``).

The card ships one SVG per key in ``frontend/devices/<key>.svg``. The rules below map what
we know about a device (driver, manufacturer, model, device/source name) to such a key.
To add a device: draw ``frontend/devices/<key>.svg`` and add a rule here (first match wins,
put specific rules above generic ones) plus a test case in ``tests/test_device_icons.py``.

No Home Assistant imports here, so the mapping is trivial to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: fallbacks when no rule matches
GENERIC_NDI_DECODER = "ndi_decoder"
GENERIC_NDI_CAMERA = "ndi_camera"
GENERIC_NDI_COMPUTER = "ndi_computer"
GENERIC_DANTE = "dante_device"
DISPLAY = "display"


@dataclass(frozen=True, slots=True)
class IconRule:
    """``pattern`` (case-insensitive regex) is searched in the model, then the name.

    ``drivers`` / ``protocols`` restrict a rule; ``manufacturer`` (regex) must match the manufacturer if set.
    ``match_name=False`` checks the model only (for words that are too common in user-chosen names).
    """

    key: str
    pattern: str
    drivers: frozenset[str] = field(default_factory=frozenset)
    protocols: frozenset[str] = field(default_factory=frozenset)
    manufacturer: str | None = None
    match_name: bool = True


def _rule(key: str, pattern: str, **kwargs: object) -> IconRule:
    for attr in ("drivers", "protocols"):
        if attr in kwargs:
            kwargs[attr] = frozenset(kwargs[attr])  # type: ignore[arg-type]
    return IconRule(key, pattern, **kwargs)  # type: ignore[arg-type]


# Dante default device names are "<model prefix>-<last 6 hex digits of the MAC>", e.g. AVIOAES3-0a1b2c.
ICON_RULES: tuple[IconRule, ...] = (
    # --- Audinate AVIO adapters
    _rule("avio_aes3", r"avio[\s_-]*aes3|\bd?aes3\b|adp-aes3", protocols={"dante"}),
    _rule("avio_usb", r"avio[\s_-]*usb|\bdiousb|adp-usb", protocols={"dante"}),
    _rule("avio_analog_out", r"avio[\s_-]*(ao\d|analog[\s_-]*out|output)|\bdao\d\b|adp-dao", protocols={"dante"}),
    _rule("avio_analog_in", r"avio[\s_-]*(ai\d|analog[\s_-]*in|input)|\bdai\d\b|adp-dai", protocols={"dante"}),
    _rule("avio_analog_in", r"\bavio", protocols={"dante"}),  # other AVIO adapters
    # --- small two-channel Dante converters (HDCVT DA-22UC, Neutrik NA2-IO-DPRO, Ultimo based boxes)
    _rule("dante_converter", r"da-?22uc|na2-io|\bultimo", protocols={"dante"}),
    _rule("dante_converter", r".", protocols={"dante"}, manufacturer=r"hdcvt"),
    # --- consoles
    _rule("wing", r"^wing\b|\bwing[\s_-]|\bwing$", protocols={"dante"}),
    # --- NDI decoders
    _rule("magewell_ndi_aio", r"\baio\b", drivers={"magewell"}),
    _rule("magewell_pro_convert", r".", drivers={"magewell"}),
    _rule("magewell_ndi_aio", r"\baio\b", manufacturer=r"magewell"),
    _rule("magewell_pro_convert", r"pro\s*convert", manufacturer=r"magewell"),
    _rule("birddog_play", r"\bplay\b", drivers={"birddog"}, match_name=False),
    _rule("birddog_play", r"birddog[\s_-]*play"),
    _rule(GENERIC_NDI_DECODER, r".", drivers={"birddog"}),
)

#: NDI source names are "MACHINE (Stream)": camera-like words → camera, everything else → computer
_CAMERA = re.compile(
    r"\b(cam|camera|kamera|ptz|p\d{3}|p4k|eyes|x\d{1,2}|ue\d{2,3}|aw-?ue\d+)\b|cam\d|ptz", re.IGNORECASE
)


def _search(pattern: str, *texts: str | None) -> bool:
    return any(t and re.search(pattern, t, re.IGNORECASE) for t in texts)


def icon_key(
    *,
    protocol: str,
    driver: str | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    name: str | None = None,
    role: str = "destination",
) -> str:
    """Icon key for a device. ``role`` is ``destination`` (decoder/receiver) or ``source``."""
    for rule in ICON_RULES:
        if rule.drivers and driver not in rule.drivers:
            continue
        if rule.protocols and protocol not in rule.protocols:
            continue
        if rule.manufacturer and not _search(rule.manufacturer, manufacturer):
            continue
        texts = (model, name) if rule.match_name else (model,)
        if rule.pattern == "." or _search(rule.pattern, *texts):  # "." = driver/manufacturer alone decide
            return rule.key
    if protocol == "dante":
        return GENERIC_DANTE
    if role == "source":
        return GENERIC_NDI_CAMERA if name and _CAMERA.search(name) else GENERIC_NDI_COMPUTER
    return GENERIC_NDI_DECODER
