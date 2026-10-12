#!/usr/bin/env python3
"""Schreibt die sprachneutrale Schnittstellen-Beschreibung nach docs/api/ (OpenAPI + MCP-Werkzeuge).

    scripts/export-spec.py          schreiben
    scripts/export-spec.py --check  nur prüfen (Exit 1, wenn die Dateien nicht zum Code passen)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from avmatrix.docs import openapi  # noqa: E402
from avmatrix.mcp import INSTRUCTIONS, PROTOCOL_VERSIONS, TOOLS, WRITE_TOOLS  # noqa: E402

EXAMPLE = {"urls": [{"label": "Beispiel", "url": "http://matrixpi.local:8088/"}]}


def build() -> dict[str, str]:
    mcp = {
        "transport": "Streamable HTTP, POST /mcp, JSON-RPC 2.0, zustandslos (keine Sitzung, kein Server-Stream)",
        "protocolVersions": list(PROTOCOL_VERSIONS),
        "serverInfo": {"name": "av-matrix", "title": "Strelle AV Matrix (Kreuzschiene)"},
        "auth": "Lesende Werkzeuge ohne Schlüssel. Schreibende mit 'Authorization: Bearer <Zugangsschlüssel>'; "
        "fehlt er: Ergebnis mit isError=true. Ist er falsch: HTTP 401.",
        "writeTools": sorted(WRITE_TOOLS),
        "instructions": INSTRUCTIONS,
        "tools": TOOLS,
    }
    dump = lambda data: json.dumps(data, ensure_ascii=False, indent=2) + "\n"  # noqa: E731
    return {"openapi.json": dump(openapi(EXAMPLE)), "mcp-tools.json": dump(mcp)}


def main() -> int:
    target = ROOT / "docs" / "api"
    stale = []
    for name, text in build().items():
        path = target / name
        if "--check" in sys.argv:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            target.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print("geschrieben:", path.relative_to(ROOT))
    if stale:
        print("nicht aktuell:", ", ".join(stale), "→ scripts/export-spec.py ausführen")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
