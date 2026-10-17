#!/usr/bin/env python3
"""Baut demo/index.html: Projekt + alle verwendeten Profile werden eingebettet (läuft per Doppelklick, ohne Server).

    python3 devices/demo/build.py [projects/oegsw-krems-2026.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
project = json.loads((ROOT / (sys.argv[1] if len(sys.argv) > 1 else "projects/oegsw-krems-2026.json")).read_text(encoding="utf-8"))
profiles = {}
for f in (ROOT / "profiles").glob("*.json"):
    d = json.loads(f.read_text(encoding="utf-8"))
    profiles[d["id"]] = d
needed = {i["profile"] for i in project["instances"]} | {m for i in project["instances"] for m in (i.get("modules") or {}).values()}
data = {"project": project, "profiles": {k: v for k, v in profiles.items() if k in needed}}
missing = sorted(n for n in needed if n not in profiles and n not in project.get("generic", {}))
html = (ROOT / "demo/template.html").read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
page = '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>\n' + html + "\n</body></html>"
(ROOT / "demo/index.html").write_text(page, encoding="utf-8")
(ROOT / "demo/artifact.html").write_text(html, encoding="utf-8")
print("geschrieben:", ROOT / "demo/index.html", "| Profile eingebettet:", len(data["profiles"]), "| fehlend:", missing or "keine")
