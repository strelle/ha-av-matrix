"""Device illustration mapping (device_icons.py) and the shipped SVG files."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from custom_components.av_matrix.device_icons import ICON_RULES, icon_key

DEVICES = Path(__file__).parents[1] / "custom_components/av_matrix/frontend/devices"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # NDI decoders (destinations)
        ({"protocol": "ndi", "driver": "magewell", "model": "Pro Convert NDI to AIO"}, "magewell_ndi_aio"),
        ({"protocol": "ndi", "driver": "magewell", "model": "Pro Convert NDI to HDMI 4K"}, "magewell_pro_convert"),
        ({"protocol": "ndi", "driver": "magewell", "model": None}, "magewell_pro_convert"),
        ({"protocol": "ndi", "driver": "birddog", "model": "PLAY"}, "birddog_play"),
        ({"protocol": "ndi", "driver": "birddog", "model": "Mini", "name": "Play room"}, "ndi_decoder"),
        ({"protocol": "ndi", "driver": "birddog", "model": None}, "ndi_decoder"),
        ({"protocol": "ndi", "driver": "kiloview"}, "ndi_decoder"),
        # NDI sources
        ({"protocol": "ndi", "name": "CAM (1)", "role": "source"}, "ndi_camera"),
        ({"protocol": "ndi", "name": "BIRDDOG-P200 (CAM)", "role": "source"}, "ndi_camera"),
        ({"protocol": "ndi", "name": "PTZ-STAGE (Ch1)", "role": "source"}, "ndi_camera"),
        ({"protocol": "ndi", "name": "STUDIO-PC (Slides)", "role": "source"}, "ndi_computer"),
        ({"protocol": "ndi", "name": "CAMPUS-PC (Slides)", "role": "source"}, "ndi_computer"),
        # Dante: from mDNS model or the default device name
        ({"protocol": "dante", "name": "AVIOAES3-0a1b2c"}, "avio_aes3"),
        ({"protocol": "dante", "name": "Stage-L", "model": "AVIO AES3"}, "avio_aes3"),
        ({"protocol": "dante", "name": "AVIOUSBC-0a1b2c"}, "avio_usb"),
        ({"protocol": "dante", "name": "AVIOAI2-0a1b2c"}, "avio_analog_in"),
        ({"protocol": "dante", "name": "AVIOAO2-0a1b2c"}, "avio_analog_out"),
        ({"protocol": "dante", "name": "AVIOBT-0a1b2c"}, "avio_analog_in"),
        ({"protocol": "dante", "name": "DA-22UC-0a1b2c"}, "dante_converter"),
        ({"protocol": "dante", "name": "Bar", "model": "ULTIMOX2"}, "dante_converter"),
        ({"protocol": "dante", "name": "Bar", "manufacturer": "HDCVT", "model": "_00000020240403"}, "dante_converter"),
        ({"protocol": "dante", "name": "WING-0a1b2c"}, "wing"),
        ({"protocol": "dante", "name": "FOH WING"}, "wing"),
        ({"protocol": "dante", "name": "WINGMAN"}, "dante_device"),
        ({"protocol": "dante", "name": "STAGEBOX-A", "role": "source"}, "dante_device"),
        ({"protocol": "dante", "name": "Bar", "model": "AVIO AES3", "role": "source"}, "avio_aes3"),
        # Dante words must not leak into NDI
        ({"protocol": "ndi", "name": "WING-PC (Out)", "role": "source"}, "ndi_computer"),
    ],
)
def test_icon_key(kwargs: dict, expected: str) -> None:
    assert icon_key(**kwargs) == expected


def all_keys() -> set[str]:
    return {r.key for r in ICON_RULES} | {
        icon_key(protocol="dante"),
        icon_key(protocol="ndi"),
        icon_key(protocol="ndi", role="source", name="CAM"),
        icon_key(protocol="ndi", role="source", name="PC"),
        "display",
    }


@pytest.mark.parametrize("key", sorted(all_keys()))
def test_every_key_has_a_valid_svg(key: str) -> None:
    path = DEVICES / f"{key}.svg"
    assert path.is_file(), f"missing illustration {path.name}"
    root = ET.fromstring(path.read_text())
    assert root.tag.endswith("svg") and root.get("viewBox") == "0 0 96 64"
    text = path.read_text()
    assert "<script" not in text and 'href="http' not in text
    assert 'class="led"' in text and "--avm-led" in text  # status LED driven by the card
    assert path.stat().st_size < 6000
