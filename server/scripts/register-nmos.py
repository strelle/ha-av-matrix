#!/usr/bin/env python3
"""Hängt den NMOS-Treiber (ST 2110) aus ``server/nmos/`` in die gespiegelten Pakete ein.

``scripts/sync-shared.sh`` ruft das nach dem Spiegeln auf: Treiber, Protokoll und Geräte-Regeln werden in
``avmatrix/drivers/__init__.py``, ``avmatrix/protocols/__init__.py`` und ``avmatrix/device_icons.py``
eingetragen. Mehrfach ausführbar. Entfällt, sobald der Treiber in der Integration liegt (nmos/README.md).

Aufruf: ``register-nmos.py <Pfad zu avmatrix>``
"""

from __future__ import annotations

import sys
from pathlib import Path


def patch(path: Path, edits: list[tuple[str, str]], marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    for old, new in edits:
        if old not in text:
            raise SystemExit(f"{path}: Stelle nicht gefunden: {old!r} – die Integration hat sich geändert, bitte nmos/README.md lesen")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def main(root: Path) -> None:
    patch(
        root / "drivers" / "__init__.py",
        [
            ("from .magewell import MagewellProConvert\n", "from .magewell import MagewellProConvert\nfrom .nmos import NmosNetwork\n"),
            ("        MagewellProConvert,\n", "        MagewellProConvert,\n        NmosNetwork,\n"),
        ],
        "NmosNetwork",
    )
    # ST 2110 trägt Bild (Protocol.video) – eine Vorschau gibt es trotzdem nicht
    video = ", video=True" if "video: bool" in (root / "protocols" / "__init__.py").read_text(encoding="utf-8") else ""
    patch(
        root / "protocols" / "__init__.py",
        [
            ("from .ndi import NdiSourceRegistry\n", "from .ndi import NdiSourceRegistry\nfrom .nmos import NmosSourceRegistry\n"),
            (
                '    "dante": Protocol("dante", "Dante®", DanteSourceRegistry),\n',
                '    "dante": Protocol("dante", "Dante®", DanteSourceRegistry),\n'
                f'    "st2110": Protocol("st2110", "ST 2110", NmosSourceRegistry{video}),\n',
            ),
        ],
        "NmosSourceRegistry",
    )
    patch(
        root / "device_icons.py",
        [
            ('GENERIC_DANTE = "dante_device"\n', 'GENERIC_DANTE = "dante_device"\nGENERIC_ST2110 = "st2110_device"\n'),
            (
                "    # --- NDI decoders\n",
                "    # --- SMPTE ST 2110 (NMOS): der Treiber leitet den Typ zusätzlich aus dem Aufbau des Geräts ab\n"
                '    _rule("st2110_presentation", r"presentation", protocols={"st2110"}),\n'
                '    _rule("st2110_multi", r"\\b[48]\\s*x\\s*12g|\\b3\\s*x\\s*3g", protocols={"st2110"}),\n'
                '    _rule("st2110_card", r"decklink", protocols={"st2110"}),\n'
                '    _rule("st2110_converter", r"\\bmini\\b|bidirect|ip to hdmi|hdmi to ip|converter|konverter", protocols={"st2110"}),\n'
                "    # --- NDI decoders\n",
            ),
            (
                '    if protocol == "dante":\n        return GENERIC_DANTE\n',
                '    if protocol == "dante":\n        return GENERIC_DANTE\n    if protocol == "st2110":\n        return GENERIC_ST2110\n',
            ),
        ],
        "GENERIC_ST2110",
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
