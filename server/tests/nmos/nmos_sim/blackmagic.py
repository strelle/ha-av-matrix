"""Die fünf bestellten Blackmagic-Geräte als Simulation – so genau, wie die Recherche es hergibt.

Belegt (Handbuch „Blackmagic 2110 IP Converters“ 09/2026, Tech Specs, IP10-Entwicklerdokument, Forum):

* Bild, Ton und Zusatzdaten sind getrennte Ströme (ST 2110-20/-30/-40) mit eigener Multicast-Adresse.
* Ton: 16 Kanäle je Richtung, 48 kHz / 24 Bit (``L24/48000/16``).
* 2160p59,94/60 läuft mit dem IP10-Codec (``vnd.blackmagic-design.ip10``, ST 2110-22), alles darunter
  unkomprimiert. Die DeckLink IP/SDI HD kann höchstens 1080p60 und kein IP10.
* Sender senden erst, wenn sie eingeschaltet wurden (``master_enable``) – Quirk ``senders_off``.
* 4x12G PWR: vier unabhängige Wandler (SDI IN n → Sender, Empfänger → SDI OUT n), je eigener 10G-Port.
* DeckLink IP/SDI HD: 2 Eingänge + 2 Ausgänge über 2110. Mini BiDirect: Talkback liegt in Kanal 15/16,
  kein eigener Strom. Presentation Converter: 1 × rein, 1 × raus.

Annahme (am Liefertag mit ``nmos-check`` prüfen):

* Namen der Geräte, Sender und Empfänger (hier: Produktname bzw. „SDI In 1 Video“).
* Dass BCP-002-01-Gruppen so heißen wie der Ein-/Ausgang, und die Form der Empfänger-Fähigkeiten.
* Ob der 4x12G als EIN Node mit vier Kanälen erscheint (``converter_4x12g``) oder als VIER Nodes
  (``converter_4x12g_as_four_nodes``) – beides ist nachgebildet und getestet.
* IS-04-Medientyp von IP10 (``video/vnd.blackmagic-design.ip10``).
"""

from __future__ import annotations

from .node import Port, Spec, Video

UHD60_IP10 = Video(3840, 2160, (60, 1), codec="ip10")
UHD50 = Video(3840, 2160, (50, 1))
HD50 = Video(1920, 1080, (50, 1))
#: laut Forum: Sender müssen per NMOS eingeschaltet werden
BMD_QUIRKS = {"senders_off"}


def _mac(n: int) -> str:
    return f"7c-2e-0d-0a-0b-{n:02x}"


def mini_ip_to_hdmi(label: str = "Blackmagic 2110 IP Mini IP to HDMI") -> Spec:
    """Nur Empfänger: 2110 → HDMI 2.0 (bis 2160p60, auch IP10)."""
    return Spec(
        label=label, description="Blackmagic 2110 IP Mini IP to HDMI", hostname="2110-mini-ip-to-hdmi.local", mac=_mac(1),
        ports=[Port("HDMI Out", "rx", audio_channels=16)], quirks=set(BMD_QUIRKS),
    )  # fmt: skip


def presentation_converter(label: str = "Blackmagic 2110 IP Presentation Converter") -> Spec:
    """Sender (USB-C/HDMI rein, gemischt mit Mikrofon) und Empfänger (HDMI/SDI/XLR raus)."""
    return Spec(
        label=label, description="Blackmagic 2110 IP Presentation Converter", hostname="2110-presentation.local", mac=_mac(2),
        ports=[Port("PC In", "tx", HD50), Port("Program Out", "rx")], quirks=set(BMD_QUIRKS),
    )  # fmt: skip


def mini_bidirect_12g(label: str = "Blackmagic 2110 IP Mini BiDirect 12G", video: Video = HD50) -> Spec:
    """Bidirektional: SDI rein → Sender, Empfänger → SDI raus (Talkback in Kanal 15/16)."""
    return Spec(
        label=label, description="Blackmagic 2110 IP Mini BiDirect 12G", hostname="2110-mini-bidirect.local", mac=_mac(3),
        ports=[Port("SDI In", "tx", video), Port("SDI Out", "rx")], quirks=set(BMD_QUIRKS),
    )  # fmt: skip


def converter_4x12g(label: str = "Blackmagic 2110 IP Converter 4x12G PWR") -> Spec:
    """Vier Kanäle in EINEM Node. Kanal 4 bekommt 2160p60 und sendet deshalb IP10."""
    videos = [HD50, HD50, UHD50, UHD60_IP10]
    ports = [Port(f"SDI In {n}", "tx", videos[n - 1]) for n in range(1, 5)]
    ports += [Port(f"SDI Out {n}", "rx") for n in range(1, 5)]
    return Spec(
        label=label, description="Blackmagic 2110 IP Converter 4x12G PWR", hostname="2110-converter-4x12g.local", mac=_mac(4),
        ports=ports, quirks=set(BMD_QUIRKS),
    )  # fmt: skip


def converter_4x12g_as_four_nodes(label: str = "Blackmagic 2110 IP Converter 4x12G PWR") -> list[Spec]:
    """Variante: jeder der vier 10G-Ports meldet sich als eigener Node mit gleichem Namen."""
    videos = [HD50, HD50, UHD50, UHD60_IP10]
    return [
        Spec(
            label=label,
            description="Blackmagic 2110 IP Converter 4x12G PWR",
            hostname=f"2110-converter-4x12g-{n}.local",
            mac=_mac(0x40 + n),
            ports=[Port(f"SDI In {n}", "tx", videos[n - 1]), Port(f"SDI Out {n}", "rx")],
            quirks=set(BMD_QUIRKS),
        )  # fmt: skip
        for n in range(1, 5)
    ]


def decklink_ip_sdi_hd(label: str = "DeckLink IP/SDI HD") -> Spec:
    """I/O-Karte: 2 × rein, 2 × raus, höchstens 1080p60, nur unkomprimiert."""
    ports = [Port(f"Output {n}", "tx", HD50) for n in (1, 2)]  # aus Sicht des Rechners: Ausgabe = Sender
    ports += [Port(f"Input {n}", "rx", max_height=1080, codecs=("raw",)) for n in (1, 2)]
    return Spec(
        label=label, description="Blackmagic DeckLink IP/SDI HD", hostname="schnitt-pc.local", mac=_mac(5),
        ports=ports, quirks=set(BMD_QUIRKS),
    )  # fmt: skip


def studio() -> list[Spec]:
    """Die Lieferung vom 10.10.2026."""
    return [mini_ip_to_hdmi(), presentation_converter(), mini_bidirect_12g(), converter_4x12g(), decklink_ip_sdi_hd()]
