#!/usr/bin/env python3
"""Erzeugt die zwei Companion-Seiten als Import-Dateien (.companionconfig, Format von Companion 5):

* ``Strelle AV Matrix``          – Beispieltasten: je NDI-Decoder "Quelle auf Ziel", Presets, Undo (mit Rückmeldung)
* ``Strelle AV Matrix – Zugang`` – die Adressen der Browser-Ansicht, groß lesbar

Die Tasten verweisen auf die Companion-Verbindung des Moduls "Strelle: AV Matrix".
    companion/make_pages.py --server http://matrixpi.local:8088 --companion http://matrixpi.local:8000 --out /tmp/seiten
Importiert wird in Companion unter Import / Export → Datei wählen → Zielseite "neue Seite" (hinten angehängt).
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import string
import urllib.request
from pathlib import Path

ALPHABET = string.ascii_letters + string.digits + "_-"
RED, AMBER, BLUE = 0xFF4B42, 0xFFB020, 0x2F6FD0
DARK, PANEL, WHITE, BLACK, MUTED = 0x121212, 0x24262B, 0xFFFFFF, 0x000000, 0xA3A19C
OFF = "__off__"


def nid() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(21))


def val(value):
    return {"value": value, "isExpression": False}


def get(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.load(resp)


def layers(text: str, *, bg: int = DARK, color: int = WHITE, size: float = 23.3) -> list[dict]:
    """Schriftgröße in Prozent der Tastenhöhe (wie Companion 5 sie speichert), schrumpft bei Bedarf."""
    geometry = {"enabled": val(True), "opacity": val(100), "x": val(0), "y": val(0), "width": val(100), "height": val(100), "rotation": val(0)}
    return [
        {"id": "canvas", "name": "Canvas", "usage": "auto", "type": "canvas", "decoration": val("border"), "showStatusIcons": val("default")},
        {"id": "box0", "name": "Background", "usage": "auto", "type": "box", **geometry, "color": val(bg), "borderWidth": val(0),
         "borderColor": val(0), "borderPosition": val("inside")},
        {"id": "text0", "name": "Text", "usage": "auto", "type": "text", **geometry, "text": val(text), "color": val(color),
         "halign": val("center"), "valign": val("center"), "fontsize": val(size), "fontsizeAllowShrink": val(True),
         "font": val("companion-sans"), "outlineColor": val(0xFF000000)},
    ]  # fmt: skip


def button(text: str, *, actions: list[dict] | None = None, feedbacks: list[dict] | None = None, **style) -> dict:
    return {
        "type": "button-layered",
        "style": {"layers": layers(text, **style)},
        "options": {"stepProgression": "auto", "stepExpression": "", "rotaryActions": False, "canModifyStyleInApis": False, "notes": ""},
        "feedbacks": feedbacks or [],
        "steps": {"0": {"action_sets": {"down": actions or [], "up": []}, "options": {"runWhileHeld": []}}},
        "localVariables": [],
    }


def action(conn: str, definition: str, **options) -> dict:
    return {"type": "action", "id": nid(), "definitionId": definition, "connectionId": conn,
            "options": {k: val(v) for k, v in options.items()}, "upgradeIndex": -1}  # fmt: skip


def feedback(conn: str, definition: str, *, bg: int = RED, color: int = BLACK, **options) -> dict:
    """Boolesche Rückmeldung: solange wahr, wird die Taste umgefärbt (Vorgabe rot = aktiv)."""
    return {
        "type": "feedback", "id": nid(), "definitionId": definition, "connectionId": conn,
        "options": {k: val(v) for k, v in options.items()}, "upgradeIndex": -1, "isInverted": val(False),
        "styleOverrides": [
            {"overrideId": nid(), "elementId": "box0", "elementProperty": "color", "override": val(bg)},
            {"overrideId": nid(), "elementId": "text0", "elementProperty": "color", "override": val(color)},
        ],
    }  # fmt: skip


def fit(text: str) -> float:
    """Schriftgröße, bei der die längste Zeile ohne Umbruch auf die Taste passt."""
    longest = max(len(line) for line in text.split("\n"))
    lines = text.count("\n") + 1
    size = 30 if longest <= 6 else 23.3 if longest <= 8 else 19 if longest <= 10 else 16 if longest <= 12 else 14
    return min(size, {1: 30, 2: 30, 3: 23.3}.get(lines, 17))


def page(name: str, grid: dict[tuple[int, int], dict], columns: int = 8, rows: int = 4) -> dict:
    controls: dict[str, dict[str, dict]] = {}
    for (row, col), ctl in sorted(grid.items()):
        controls.setdefault(str(row), {})[str(col)] = ctl
    return {"id": nid(), "name": name, "controls": controls,
            "gridSize": {"minColumn": 0, "maxColumn": columns - 1, "minRow": 0, "maxRow": rows - 1}}  # fmt: skip


def short(name: str) -> str:
    m = re.search(r"\(([^)]+)\)\s*$", name)
    return m.group(1) if m else name


def wrap(text: str, width: int = 9) -> str:
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return "\n".join([*out, line])


def matrix_page(conn: str, choices: dict, columns: int = 8) -> dict:
    grid: dict[tuple[int, int], dict] = {}
    dests = [d for d in choices["destinations"] if d["protocol"] == "ndi" and not d["protected"]][:2]
    sources = [s for s in choices["sources"] if s["protocol"] == "ndi"][: columns - 3]
    for row, dest in enumerate(dests):
        grid[(row, 0)] = button(wrap(f"ZIEL {dest['name']}"), bg=PANEL, color=MUTED, size=23.3)
        for col, src in enumerate([*sources, None], start=1):
            sid = src["id"] if src else OFF
            label = wrap(short(src["name"])) if src else "AUS"
            grid[(row, col)] = button(
                f"{label}\n→ {dest['name']}" if src else f"AUS\n→ {dest['name']}",
                actions=[action(conn, "route", dest=dest["id"], source=sid)],
                feedbacks=[feedback(conn, "route_active", dest=dest["id"], source=sid)],
                size=23.3,
            )
    grid[(2, 0)] = button("PRESETS", bg=PANEL, color=MUTED, size=23.3)
    for col, preset in enumerate(choices["presets"][: columns - 2], start=1):
        grid[(2, col)] = button(
            f"PRESET\n{wrap(preset['name'])}",
            actions=[action(conn, "preset_recall", preset=preset["id"])],
            feedbacks=[feedback(conn, "preset_active", preset=preset["id"])],
            size=23.3,
        )
    grid[(2, columns - 1)] = button("UNDO\nletzte\nAktion", actions=[action(conn, "undo_last")], bg=PANEL, color=AMBER, size=23.3)
    grid[(3, 0)] = button("STRELLE\nAV MATRIX", bg=BLUE, color=WHITE, size=19)
    grid[(3, 1)] = button("Rot =\naktiv", bg=RED, color=BLACK, size=23.3)
    grid[(3, 2)] = button("Tasten\nkopieren,\nZiel/Quelle\nwählen", bg=DARK, color=MUTED, size=17)
    grid[(3, columns - 3)] = {"type": "pageup"}
    grid[(3, columns - 2)] = {"type": "pagenum"}
    grid[(3, columns - 1)] = {"type": "pagedown"}
    return page("Strelle AV Matrix", grid, columns)


def access_page(info: dict, columns: int = 8) -> dict:
    port = f":{info['port']}"
    grid: dict[tuple[int, int], dict] = {}

    def row(r: int, title: str, parts: list[str], bg: int = DARK) -> None:
        grid[(r, 0)] = button(title, bg=PANEL, color=AMBER, size=23.3)
        grid[(r, 1)] = button("http://", bg=bg, color=MUTED, size=23.3)
        for col, part in enumerate(parts, start=2):
            grid[(r, col)] = button(part, bg=bg, color=WHITE, size=fit(part))

    grid[(0, 0)] = button("STRELLE\nAV MATRIX", bg=BLUE, color=WHITE, size=19)
    grid[(0, 1)] = button("ZUGANG", bg=BLUE, color=WHITE, size=23.3)
    grid[(0, 2)] = button("Im Browser\nöffnen\n(PC, Tablet,\nHandy)", bg=DARK, color=WHITE, size=17)
    grid[(0, 3)] = button("Adresse\nje Zeile\nvon links\nnach rechts", bg=DARK, color=MUTED, size=17)
    grid[(0, columns - 3)] = {"type": "pageup"}
    grid[(0, columns - 2)] = {"type": "pagenum"}
    grid[(0, columns - 1)] = {"type": "pagedown"}
    host, dot, rest = info["mdns_name"].partition(".")
    row(1, "STUDIO\nName", [host, dot + rest, port])
    if info.get("lan_ip"):
        a, b, c, d = info["lan_ip"].split(".")
        row(2, "STUDIO\nIP", [f"{a}.{b}.", f"{c}.{d}", port])
    if info.get("tailscale_name"):
        host, _, rest = info["tailscale_name"].partition(".")
        net, _, tld = rest.partition(".")
        row(3, "TAIL-\nSCALE", [host + ".", net, "." + tld, port])
        if info.get("tailscale_ip"):
            a, b, c, d = info["tailscale_ip"].split(".")
            grid[(3, 6)] = button("oder IP", bg=PANEL, color=MUTED, size=23.3)
            grid[(3, 7)] = button(f"{a}.{b}.\n{c}.{d}\n{port}", bg=DARK, color=WHITE, size=19)
    return page("Strelle AV Matrix – Zugang", grid, columns)


def export(page_data: dict, conn: str, instance: dict | None, build: str) -> dict:
    return {
        "version": 12, "type": "page", "companionBuild": build, "page": page_data,
        "instances": {conn: instance} if instance else {}, "connectionCollections": [], "oldPageNumber": 1,
        "imageLibrary": [], "imageLibraryCollections": [],
    }  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:8088", help="Strelle AV Matrix Server")
    ap.add_argument("--companion", default="http://127.0.0.1:8000", help="Companion (Admin-Port)")
    ap.add_argument("--label", default="avmatrix", help="Name der Companion-Verbindung des Moduls")
    ap.add_argument("--out", default=".", help="Zielordner")
    args = ap.parse_args()
    info, choices = get(f"{args.server}/api/info"), get(f"{args.server}/api/choices")
    conn = next((c for c in get(f"{args.companion}/api/connections") if c["label"] == args.label), None)
    if conn is None:
        raise SystemExit(f"Companion-Verbindung {args.label!r} nicht gefunden – zuerst das Modul 'Strelle: AV Matrix' hinzufügen.")
    instance = {"moduleInstanceType": "connection", "moduleId": conn["moduleId"], "moduleVersionId": "1.0.0", "sortOrder": 99,
                "label": conn["label"], "isFirstInit": False, "config": {"host": "127.0.0.1", "port": 8088}, "secrets": {},
                "lastUpgradeIndex": -1, "enabled": True}  # fmt: skip
    build = "5.0.7+9763-stable-cec2f88e6f"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("av-matrix", matrix_page(conn["id"], choices)), ("av-matrix-zugang", access_page(info))):
        path = out / f"{name}.companionconfig"
        path.write_text(json.dumps(export(data, conn["id"], instance if name == "av-matrix" else None, build), ensure_ascii=False, indent="\t"))
        print(path, f"({sum(len(r) for r in data['controls'].values())} Tasten)")


if __name__ == "__main__":
    main()
