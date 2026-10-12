#!/usr/bin/env bash
# Spiegelt die gemeinsamen Teile aus der Home-Assistant-Variante (../custom_components/av_matrix) in den Server:
# Treiber, Protokolle, Datenmodelle, Geräte-Grafiken, Schriften, die Karte und die Treiber-Tests.
# Die gespiegelten Dateien stehen in .gitignore – Quelle der Wahrheit bleibt die Integration.
# Läuft automatisch vor den Tests (tests/conftest.py) und vor jedem Ausrollen (deploy/deploy.sh).
set -euo pipefail
SERVER="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$SERVER/.." && pwd)"
SRC="$ROOT/custom_components/av_matrix"
DST="$SERVER/avmatrix"
[ -d "$SRC" ] || { echo "nicht gefunden: $SRC" >&2; exit 1; }
mkdir -p "$DST/drivers" "$DST/protocols" "$DST/translations" "$DST/static/devices" "$DST/static/fonts"
cp "$SRC/models.py" "$SRC/device_icons.py" "$DST/"
cp "$SRC"/drivers/*.py "$DST/drivers/"
cp "$SRC"/protocols/*.py "$DST/protocols/"
cp "$SRC/translations/de.json" "$SRC/translations/en.json" "$DST/translations/"
cp "$SRC/frontend/av-matrix-card.js" "$DST/static/"
cp "$SRC"/frontend/devices/*.svg "$DST/static/devices/"
cp "$SRC"/frontend/fonts/* "$DST/static/fonts/"
# Illustrationen, die nur der Server kennt (Encoder, Testbild, neutrale NDI-Quelle)
cp "$DST"/static/devices-extra/*.svg "$DST/static/devices/"
for f in dante_sim fake_http test_dante_protocol test_device_icons test_registry test_magewell test_birddog; do
  sed -e 's/custom_components\.av_matrix/avmatrix/g' \
      -e 's#custom_components/av_matrix/frontend/devices#avmatrix/static/devices#' \
      -e 's#parents\[1\] / "avmatrix/static/devices"#parents[1] / "avmatrix/static/devices"#' \
      "$ROOT/tests/$f.py" > "$SERVER/tests/$f.py"
done
python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$SRC/manifest.json" > "$DST/SHARED_FROM"
[ "${1:-}" = "-q" ] || echo "gespiegelt aus der Integration v$(cat "$DST/SHARED_FROM")"
