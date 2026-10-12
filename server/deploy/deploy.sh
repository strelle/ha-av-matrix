#!/usr/bin/env bash
# Rollt den Server auf den Zielrechner aus (rsync über SSH, kein sudo nötig) und startet den Dienst neu.
#   deploy/deploy.sh
# Das Ziel steht in server/local/deploy.env (nicht versioniert, Vorlage: deploy/deploy.env.example) oder in
# der Umgebung (AVM_TARGET=benutzer@rechner). Konfiguration, Zustand und Zugangsschlüssel auf dem Ziel
# bleiben unberührt; nur bei der Erstinstallation wird local/studio.json als config.json hinterlegt.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/local/deploy.env" ] && set -a && . "$ROOT/local/deploy.env" && set +a
: "${AVM_TARGET:?Ziel fehlt: AVM_TARGET=benutzer@rechner setzen oder local/deploy.env anlegen (siehe deploy/deploy.env.example)}"
STUDIO="${AVM_STUDIO_FILE:-local/studio.json}"

echo "→ gemeinsame Teile aus der Integration spiegeln"
"$ROOT/scripts/sync-shared.sh"
echo "→ Tests lokal"
if [ -x "$ROOT/.venv/bin/python" ]; then (cd "$ROOT" && .venv/bin/python -m pytest -q | tail -1); else echo "  (kein .venv – übersprungen)"; fi

echo "→ Dateien nach $AVM_TARGET:av-matrix-server/"
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.ruff_cache/' \
  --exclude 'node_modules/' --exclude 'tests/' --exclude 'local/' --exclude 'pkg/' --exclude '*.tgz' --exclude '.DS_Store' \
  "$ROOT/" "$AVM_TARGET:av-matrix-server/"
if [ -f "$ROOT/$STUDIO" ]; then
  ssh "$AVM_TARGET" 'mkdir -p ~/.config/av-matrix && chmod 700 ~/.config/av-matrix && [ -f ~/.config/av-matrix/config.json ]' \
    || { echo "→ Erstinstallation: $STUDIO wird config.json"; scp -q "$ROOT/$STUDIO" "$AVM_TARGET:.config/av-matrix/config.json"; }
fi

echo "→ Umgebung, Dienst"
ssh "$AVM_TARGET" bash -s <<'REMOTE'
set -euo pipefail
cd ~/av-matrix-server
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt
mkdir -p ~/.config/av-matrix ~/.local/share/av-matrix ~/.config/systemd/user
chmod 700 ~/.config/av-matrix ~/.local/share/av-matrix
[ -f ~/.config/av-matrix/config.json ] && chmod 600 ~/.config/av-matrix/config.json
cp deploy/av-matrix.service ~/.config/systemd/user/av-matrix.service
systemctl --user daemon-reload
systemctl --user enable -q av-matrix.service
systemctl --user restart av-matrix.service
sleep 4
systemctl --user --no-pager --lines=0 status av-matrix.service | head -4
curl -fsS -m 5 http://127.0.0.1:8088/api/info | python3 -c 'import json,sys; d=json.load(sys.stdin); print("läuft:", d["name"], d["version"]); [print("  ", u["label"], u["url"]) for u in d["urls"]]'
REMOTE
