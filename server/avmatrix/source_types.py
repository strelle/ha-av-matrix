"""Gerätetyp einer NDI®-Quelle: Kamera, Rechner, Encoder, Testbild – oder unbekannt.

Bestimmt das Symbol in Panel und Mobilansicht (Feld ``device_type`` / ``icon_key`` im Schnappschuss).
Kein Raten: Passt keine Regel, ist die Quelle ``unknown`` und bekommt das neutrale Symbol „NDI-Quelle“.
Wer es besser weiß, legt den Typ im Panel von Hand fest (Geräte → NDI-Quellen); das hat Vorrang.

Ein NDI-Name hat die Form ``MASCHINE (Kanal)``. Die Regeln unten prüfen wahlweise die Maschine, den Kanal
oder – falls bekannt – die Selbstauskunft der Weboberfläche des Geräts (Titel/Server der Startseite).
Die erste passende Regel gewinnt. Neue Geräte: eine Zeile ergänzen, Testfall in ``tests/test_source_types.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Typ → (Bezeichnung, Illustration unter static/devices/<icon>.svg)
TYPES: dict[str, tuple[str, str]] = {
    "camera": ("Kamera", "ndi_camera"),
    "computer": ("Rechner", "ndi_computer"),
    "encoder": ("Encoder / Wandler", "ndi_encoder"),
    "testpattern": ("Testbild", "ndi_testpattern"),
    "unknown": ("NDI-Quelle", "ndi_source"),
}
IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


@dataclass(frozen=True, slots=True)
class Rule:
    type: str
    where: str  # machine | channel | web | ip_machine (Maschine ist eine IP-Adresse; Muster prüft den Kanal)
    pattern: str
    note: str


RULES: tuple[Rule, ...] = (
    # --- eigenes Testbild der Matrix
    Rule("testpattern", "channel", r"\bAV Matrix Testbild$", "Testbild-Quelle dieses Servers"),
    # --- Kameras
    Rule("camera", "machine", r"zowie|birddog[\s_-]*(p\d|a\d|x\d|eyes|mini cam)|obsbot|ptz|\bcam(era)?[\s_-]*\d*$|kamera", "Kamera am Gerätenamen"),
    Rule("camera", "channel", r"zowiecam|\bptz\b|\bcam(era)?[\s_-]*\d*\b|kamera|aw-?ue\d+|\bp4k\b", "Kamera am Kanalnamen"),
    Rule("camera", "web", r"zowie|ptz\s*optics|\bcamera\b", "Weboberfläche nennt eine Kamera"),
    # --- HDMI-/SDI-Encoder und Wandler
    Rule("encoder", "machine", r"\btbs\d*|linkpi|kiloview|\bencoder\b|pro[\s_-]*convert|\bspark\b|\bn[346]0\b", "Encoder am Gerätenamen"),
    Rule("encoder", "ip_machine", r"^(aux|hdmi|sdi|in|ch|enc|stream|mix)[\s_-]*\d*$", "Gerät meldet sich mit seiner IP statt eines Namens (LinkPi/TBS)"),
    Rule("encoder", "web", r"linkpi|\btbs\d|encoder|kiloview", "Weboberfläche nennt einen Encoder"),
    # --- Rechner: nur, wenn erkennbar Software sendet
    Rule("computer", "channel", r"test patterns?|scan converter|screen capture|remote connection|studio monitor|webcam|\bobs\b|vmix|wirecast|mimolive"
         r"|\bloop\b|chrome|powerpoint|keynote|resolve|premiere|after effects|\bzoom\b|teams|skype|\bprogram\b|\boutput\s*\d", "NDI-Tools oder Sendesoftware"),  # fmt: skip
    Rule("computer", "machine", r"^(mac|imac|mbp|macbook|desktop-|laptop-|win-|pc-|workstation)", "Rechnername"),
)
_COMPILED = [(rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in RULES]


def split_name(source_id: str) -> tuple[str, str]:
    """``"MASCHINE (Kanal)"`` → ``("MASCHINE", "Kanal")``; ohne Klammer ist alles Maschine."""
    match = re.match(r"^(.*?)\s*\((.*)\)\s*$", source_id)
    return (match.group(1), match.group(2)) if match else (source_id, "")


def classify(source_id: str, web_hint: str | None = None) -> str:
    """Typ einer Quelle nach den Regeln; ``web_hint`` = Titel/Server ihrer Weboberfläche, falls bekannt."""
    machine, channel = split_name(source_id)
    for rule, regex in _COMPILED:
        if rule.where == "machine":
            text = None if IPV4.match(machine) else machine
        elif rule.where == "channel":
            text = channel
        elif rule.where == "ip_machine":
            text = channel if IPV4.match(machine) else None
        else:
            text = web_hint
        if text and regex.search(text):
            return rule.type
    return "unknown"
