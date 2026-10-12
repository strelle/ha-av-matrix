#!/usr/bin/env bash
# NDI|HX-Vorschau ohne Root: stellt die FFmpeg-Bibliotheken, die libndi zur Laufzeit lädt
# (libavcodec.so.61, libavutil.so.59), samt fehlender Abhängigkeiten im Benutzerverzeichnis bereit.
#
#   deploy/install-hx-decoder.sh            (Ziel aus local/deploy.env oder AVM_TARGET)
#
# Die Pakete kommen aus den Debian-Quellen des Zielrechners (apt-get download, kein Installieren) und werden
# nach ~/.local/share/av-matrix/ndi/ffmpeg/ entpackt. Der Dienst findet sie dort von selbst.
# FFmpeg steht unter der LGPL/GPL (je nach Paket), die Abhängigkeiten unter ihren jeweiligen Lizenzen – die
# Lizenztexte liegen nach dem Entpacken unter …/ffmpeg/usr/share/doc/. Nichts davon gehört ins Git-Repo.
# Einfacher, wenn Root vorhanden ist:  sudo apt install libavcodec61
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/local/deploy.env" ] && set -a && . "$ROOT/local/deploy.env" && set +a
: "${AVM_TARGET:?Ziel fehlt: AVM_TARGET setzen oder local/deploy.env anlegen}"
ssh "$AVM_TARGET" bash -s <<'REMOTE'
set -uo pipefail
DEST="$HOME/.local/share/av-matrix/ndi/ffmpeg"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
rm -rf "$DEST"; mkdir -p "$DEST" "$TMP/deb"; cd "$TMP/deb"
ARCH="$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || echo aarch64-linux-gnu)"
LIB="$DEST/usr/lib/$ARCH"
want="libavcodec61 libavutil59 libswresample5"; have=""
for round in 1 2 3 4 5 6 7 8; do
  for p in $want; do
    case " $have " in *" $p "*) continue ;; esac
    have="$have $p"
    apt-get download "$p" >/dev/null 2>&1 || continue          # virtuelle Pakete u. ä. überspringen
    deb="$(ls -t "${p}"_*.deb 2>/dev/null | head -1)"; [ -n "$deb" ] && dpkg-deb -x "$deb" "$DEST"
  done
  missing="$(for f in "$LIB/libavcodec.so.61" "$LIB/libavutil.so.59"; do LD_LIBRARY_PATH="$LIB:$LIB/pulseaudio:$LIB/blas:$LIB/lapack" ldd "$f" 2>/dev/null; done | awk '/not found/{print $1}' | sort -u)"
  [ -z "$missing" ] && break
  want=""
  for p in $have; do
    for c in $(apt-cache depends --no-recommends --no-suggests "$p" 2>/dev/null | awk '/Depends:/{print $2}' | tr -d '<>'); do
      dpkg -s "$c" >/dev/null 2>&1 && continue
      case " $have $want " in *" $c "*) ;; *) want="$want $c" ;; esac
    done
  done
  echo "Runde $round: $(echo "$missing" | wc -w) Bibliotheken fehlen noch, hole $(echo $want | wc -w) Pakete"
  [ -z "$want" ] && break
done
if [ -n "${missing:-}" ]; then echo "NICHT AUFGELÖST: $missing"; exit 1; fi
echo "→ bereit in $DEST ($(du -sh "$DEST" | cut -f1), $(echo $have | wc -w) Pakete)"
systemctl --user restart av-matrix.service 2>/dev/null && echo "→ Dienst neu gestartet" || true
REMOTE
