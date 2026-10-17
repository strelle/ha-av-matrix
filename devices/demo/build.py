#!/usr/bin/env python3
"""Baut demo/index.html aus einem Projekt: Racks (Vorlagen) samt Abwandlungen auflösen, Profile einbetten.

    python3 devices/demo/build.py [projects/<projekt>.json] [ausgabe.html]

Abwandlungen je Rack im Projekt (`overrides`):
  remove:  [Instanz-IDs]                 – Gerät aus dem Rack herauslösen (mit allen seinen Kabeln)
  add:     {instances: [...], cables: [...]} – Gerät/Kabel an das Rack anbauen
  modules: {Instanz-ID: {Steckplatz: Modulprofil}} – Modul tauschen
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def resolve(project: dict) -> dict:
    """Racks auflösen: Vorlage + Abwandlungen → flaches Projekt mit Herkunftsangaben."""
    out = copy.deepcopy(project)
    out["instances"], out["cables"], out["racks"], out["changes"] = list(project["instances"]), list(project["cables"]), [], []
    out.setdefault("generic", {})
    for ref in project.get("racks", []):
        rack = load(ROOT / "racks" / f"{ref['ref']}.json")
        ov = ref.get("overrides") or {}
        removed = set(ov.get("remove", []))
        members = []
        for inst in rack["instances"]:
            if inst["id"] in removed:
                out["changes"].append({"rack": rack["name"], "kind": "removed", "id": inst["id"], "name": inst["name"]})
                continue
            inst = copy.deepcopy(inst)
            if inst["id"] in (ov.get("modules") or {}):
                old = dict(inst.get("modules") or {})
                inst["modules"] = {**old, **ov["modules"][inst["id"]]}
                out["changes"].append({"rack": rack["name"], "kind": "modules", "id": inst["id"], "name": inst["name"], "from": old, "to": inst["modules"]})
            members.append(inst)
        for inst in (ov.get("add") or {}).get("instances", []):
            members.append({**inst, "added": True})
            out["changes"].append({"rack": rack["name"], "kind": "added", "id": inst["id"], "name": inst["name"]})
        ids = {m["id"] for m in members}
        out["instances"] += members
        out["cables"] += [{**c, "fixed": True} for c in rack["cables"] if c["from"].split(":")[0] in ids and c["to"].split(":")[0] in ids]
        out["cables"] += (ov.get("add") or {}).get("cables", [])
        out["generic"].update(rack.get("generic", {}))
        out["racks"].append({"id": ref["ref"], "name": rack["name"], "version": rack.get("version"), "members": sorted(ids), "ports": rack.get("ports", [])})
    # Kabel zu herausgelösten Geräten fallen weg
    present = {i["id"] for i in out["instances"]}
    out["cables"] = [c for c in out["cables"] if c["from"].split(":")[0] in present and c["to"].split(":")[0] in present]
    out["flows"] = [f for f in project.get("flows", []) if f["from"].split(":")[0] in present and f["to"].split(":")[0] in present]
    out["routes"] = [r for r in project.get("routes", []) if r["device"] in present]
    return out


def main() -> None:
    src = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "projects/oegsw-krems-2026.json")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "demo/index.html"
    project = resolve(load(src))
    profiles = {d["id"]: d for d in (load(f) for f in (ROOT / "profiles").glob("*.json"))}
    needed = {i["profile"] for i in project["instances"]} | {m for i in project["instances"] for m in (i.get("modules") or {}).values()}
    data = {"project": project, "profiles": {k: v for k, v in profiles.items() if k in needed}}
    missing = sorted(n for n in needed if n not in profiles and n not in project["generic"])
    html = (ROOT / "demo/template.html").read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    page = '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>\n' + html + "\n</body></html>"
    dst.write_text(page, encoding="utf-8")
    dst.with_name(dst.stem + "-artifact.html").write_text(html, encoding="utf-8")
    print("geschrieben:", dst, "| Geräte:", len(project["instances"]), "| Profile:", len(data["profiles"]), "| Abwandlungen:", len(project["changes"]), "| fehlend:", missing or "keine")


if __name__ == "__main__":
    main()
