"""Die abgelegte Schnittstellen-Beschreibung (docs/api) muss zum Code passen – andere Backends bauen darauf."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_spec_files_are_current():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "export-spec.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_spec_covers_every_route_of_the_server():
    from avmatrix.flows import FlowManager
    from avmatrix.hub import Hub
    from avmatrix.store import JsonFile, TokenFile
    from avmatrix.web import create_app

    tmp = ROOT / ".pytest_cache" / "spec"
    hub = Hub(JsonFile(tmp / "config.json"), JsonFile(tmp / "state.json"))
    app = create_app(hub, TokenFile(tmp / "token"), FlowManager(hub, lambda: ""), dict, set)
    served = {r.resource.canonical for r in app.router.routes()} - {"/", "/static/{path}", "/openapi.json", "/llms.txt"}
    spec = set(json.loads((ROOT / "docs" / "api" / "openapi.json").read_text())["paths"])
    assert served <= spec, f"nicht beschrieben: {sorted(served - spec)}"


def test_panel_is_static_and_only_talks_to_the_interface():
    """Das Panel ist ein eigenständiges statisches Frontend: keine Vorlagen, nur /api, /ws und /static."""
    static = ROOT / "avmatrix" / "static"
    for name in ("index.html", "app.js", "extras.js", "mobile.js"):
        text = (static / name).read_text(encoding="utf-8")
        assert "{{" not in text and "{%" not in text, name
