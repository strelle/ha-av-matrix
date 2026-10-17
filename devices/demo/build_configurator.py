#!/usr/bin/env python3
"""Baut demo/configurator.html: Bibliothek (Profile, Racks, Sets) und Beispielprojekte eingebettet, läuft lokal ohne Server."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
load = lambda p: json.loads(p.read_text(encoding="utf-8"))
profiles = {d["id"]: d for d in (load(f) for f in (ROOT / "profiles").glob("*.json"))}
racks = {f.stem: load(f) for f in (ROOT / "racks").glob("*.json")}
kits = {f.stem: load(f) for f in (ROOT / "kits").glob("*.json")}
projects = {"schlank": load(ROOT / "projects/schlank-atem-mini.json"), "krems": load(ROOT / "projects/oegsw-krems-2026.json")}
generic = {}
for src in [*racks.values(), *projects.values()]:
    generic.update(src.get("generic", {}))
for g, d in generic.items():
    d.setdefault("id", g)
data = {"profiles": profiles, "racks": racks, "kits": kits, "projects": projects, "generic": generic}
html = (ROOT / "demo/configurator.template.html").read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
page = '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>\n' + html + "\n</body></html>"
(ROOT / "demo/configurator.html").write_text(page, encoding="utf-8")
(ROOT / "demo/configurator-artifact.html").write_text(html, encoding="utf-8")
print("geschrieben: demo/configurator.html | Profile", len(profiles), "| Racks", len(racks), "| Sets", len(kits))
