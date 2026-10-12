#!/usr/bin/env bash
# Installiert die NDI®-Laufzeitbibliothek (libndi) für die Vorschau ins Benutzerverzeichnis des Pi – ohne sudo.
#
#   deploy/install-ndi-sdk.sh --accept-license      (lädt und installiert auf dem Zielrechner aus local/deploy.env)
#   AVM_TARGET=benutzer@rechner deploy/install-ndi-sdk.sh --accept-license
#
# Das NDI SDK ist Eigentum der Vizrt NDI AB und steht unter dem "NDI SDK License Agreement"
# (https://ndi.video/for-developers/ndi-sdk/ – Text liegt nach der Installation neben der Bibliothek).
# Es wird direkt vom Hersteller geladen und gehört NICHT ins Git-Repo. Mit --accept-license bestätigst du,
# die Lizenz gelesen zu haben und ihr zuzustimmen.
#
# Abgelegt wird nach ~/.local/share/av-matrix/ndi/:
#   libndi.so.6            aus dem offiziellen SDK (aarch64-rpi4)
#   libavahi-client.so.3   aus dem Debian-Paket libavahi-client3 (LGPL), falls sie nicht systemweit
#                          installiert ist – libndi verlangt sie
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/local/deploy.env" ] && set -a && . "$ROOT/local/deploy.env" && set +a
TARGET="${AVM_TARGET:-}"
URL="${AVM_NDI_SDK_URL:-https://downloads.ndi.tv/SDK/NDI_SDK_Linux/Install_NDI_SDK_v6_Linux.tar.gz}"
if [ "${1:-}" != "--accept-license" ]; then
  sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
  echo; echo "Abbruch: bitte mit --accept-license aufrufen."; exit 2
fi
[ -n "$TARGET" ] || { echo "Ziel fehlt: AVM_TARGET setzen oder local/deploy.env anlegen"; exit 2; }
ssh "$TARGET" URL="'$URL'" bash -s <<'REMOTE'
set -euo pipefail
DEST="$HOME/.local/share/av-matrix/ndi"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$DEST"; cd "$TMP"
case "$(uname -m)" in
  aarch64) ARCH=aarch64-rpi4-linux-gnueabi ;;
  x86_64)  ARCH=x86_64-linux-gnu ;;
  *) echo "nicht unterstützte Architektur: $(uname -m)"; exit 1 ;;
esac
echo "→ lade NDI SDK vom Hersteller"
curl -fsSL -m 300 -o sdk.tar.gz "$URL"
tar xzf sdk.tar.gz
INSTALLER="$(ls Install_NDI_SDK_*_Linux.sh | head -1)"
LINE="$(awk '/^__NDI_ARCHIVE_BEGIN__/ { print NR+1; exit 0; }' "$INSTALLER")"
tail -n+"$LINE" "$INSTALLER" | tar xz
SDK="NDI SDK for Linux"
LIB="$(ls "$SDK/lib/$ARCH"/libndi.so.6.* | head -1)"
install -m 755 "$LIB" "$DEST/"
ln -sf "$(basename "$LIB")" "$DEST/libndi.so.6"
cp "$SDK/NDI SDK License Agreement.txt" "$SDK/licenses/libndi_licenses.txt" "$SDK/Version.txt" "$DEST/" 2>/dev/null || true
if ! /sbin/ldconfig -p 2>/dev/null | grep -q libavahi-client.so.3; then
  echo "→ libavahi-client.so.3 fehlt systemweit: hole das Debian-Paket (ohne Installation)"
  apt-get download libavahi-client3 >/dev/null
  dpkg-deb -x libavahi-client3_*.deb deb
  cp -P deb/usr/lib/*/libavahi-client.so.3* "$DEST/"
fi
echo "→ installiert in $DEST:"; ls -l "$DEST"
cat "$DEST/Version.txt" 2>/dev/null || true
systemctl --user restart av-matrix.service 2>/dev/null && echo "→ Dienst neu gestartet" || true
REMOTE
