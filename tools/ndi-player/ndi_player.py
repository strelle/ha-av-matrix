#!/usr/bin/env python3
"""NDI-Player mit Einblendungen: spielt ein Video als NDI-Quelle in Schleife (ohne Ton) und legt Overlays darüber.

    PYTHONPATH=server server/.venv/bin/python tools/ndi-player/ndi_player.py "<video>" "<NDI-Name>" [--port 8099]

Steuerung im Browser: http://<rechner>:8099/  (Countdown, Text, Aus; Vorschau). Zustand in overlay_state.json neben dem Skript.
Overlay-Arten:
  countdown: {type, label, until "HH:MM", after_text, hide_at "HH:MM"} – zählt bis `until`, danach `after_text`, ab `hide_at` aus
  text:      {type, title, subtitle, hide_at?}
  off
"""
import ctypes as C, io, json, subprocess, sys, threading, time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from avmatrix.preview import _SendCreate, _VideoFrame, find_library

W, H, FPS = 1920, 1080, 25
FOURCC_BGRA = ord("B") | ord("G") << 8 | ord("R") << 16 | ord("A") << 24
FFMPEG = "/Users/strelle/.local/bin/ffmpeg"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
STATE = HERE / "overlay_state.json"
FONT = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
NAVY, BLUE, ORANGE, WHITE = (6, 34, 70), (110, 190, 240), (243, 146, 0), (240, 246, 252)

lock = threading.Lock()
cfg = json.loads(STATE.read_text()) if STATE.exists() else {"type": "off"}
last_frame = None


def font(px): return ImageFont.truetype(FONT, px)


def hm(s):
    h, m = map(int, s.split(":")); n = datetime.now(); return n.replace(hour=h, minute=m, second=0, microsecond=0)


def phase(c):
    """Was gerade gezeigt wird: (art, titel, untertitel) oder None."""
    now = datetime.now()
    if c.get("hide_at") and now >= hm(c["hide_at"]):
        return None
    if c.get("type") == "countdown":
        until = hm(c["until"]); left = int((until - now).total_seconds())
        if left > 0:
            m, s = divmod(left, 60); h, m = divmod(m, 60)
            return ("count", (c.get("label") or "Pause").upper(), f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}", f"Weiter um {c['until']} Uhr")
        return ("text", (c.get("after_text") or "Es geht gleich weiter").upper(), "", "")
    if c.get("type") == "text":
        return ("text", (c.get("title") or "").upper(), "", c.get("subtitle") or "")
    return None


import importlib
import design
_design_mtime = 0.0


def render(ph):
    """Aussehen kommt aus design.py; ändert sich die Datei, wird sie neu geladen (ohne Neustart)."""
    global _design_mtime
    m = Path(design.__file__).stat().st_mtime
    if m != _design_mtime:
        _design_mtime = m
        try:
            importlib.reload(design)
        except Exception as e:  # Fehler im Design: altes Design weiterverwenden
            print("design.py fehlerhaft:", e, flush=True)
    return design.render(ph)


class Overlay:
    def __init__(self): self.key, self.ov = None, None

    def get(self):
        with lock:
            ph = phase(cfg)
        m = Path(design.__file__).stat().st_mtime
        if ph != self.key or m != getattr(self, "m", None):
            self.key, self.m, self.ov = ph, m, render(ph)
        return self.ov


def player(path, name):
    global last_frame
    lib = C.CDLL(str(find_library()))
    lib.NDIlib_initialize.restype = C.c_bool
    lib.NDIlib_send_create.restype = C.c_void_p; lib.NDIlib_send_create.argtypes = [C.POINTER(_SendCreate)]
    lib.NDIlib_send_send_video_v2.argtypes = [C.c_void_p, C.POINTER(_VideoFrame)]
    lib.NDIlib_send_get_no_connections.restype = C.c_int; lib.NDIlib_send_get_no_connections.argtypes = [C.c_void_p, C.c_uint32]
    lib.NDIlib_initialize()
    send = lib.NDIlib_send_create(C.byref(_SendCreate(name.encode(), None, True, False)))
    if not send:
        sys.exit("NDI-Sender konnte nicht angelegt werden (Name schon vergeben?)")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", path, "-an",
           "-vf", f"scale={W}:{H}:flags=bicubic,fps={FPS},format=bgra", "-f", "rawvideo", "-"]
    size = W * H * 4; proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=size * 2)
    ov, n = Overlay(), 0
    print(f"NDI-Quelle '{name}' läuft, Steuerung auf Port {PORT}", flush=True)
    while True:
        data = proc.stdout.read(size)
        if len(data) < size:
            sys.exit(f"ffmpeg beendet ({proc.poll()})")
        fr = np.frombuffer(data, dtype=np.uint8).reshape(H, W, 4).copy()
        o = ov.get()
        if o:
            x0, y0, pre, inv = o; h, w = pre.shape[:2]
            reg = fr[y0:y0 + h, x0:x0 + w, :3].astype(np.float32)
            fr[y0:y0 + h, x0:x0 + w, :3] = (reg * inv + pre).astype(np.uint8)
        buf = fr.ctypes.data_as(C.c_void_p).value
        lib.NDIlib_send_send_video_v2(send, C.byref(_VideoFrame(W, H, FOURCC_BGRA, FPS * 1000, 1000, W / H, 1, 0x7FFFFFFFFFFFFFFF, buf, W * 4, None, 0)))
        n += 1
        if n % 5 == 0:
            last_frame = fr
        if n % (FPS * 60) == 0:
            print(f"{n} Bilder, Empfänger: {lib.NDIlib_send_get_no_connections(send, 0)}, Overlay: {ov.key[0] if ov.key else 'aus'}", flush=True)


PAGE = (HERE / "control.html").read_text(encoding="utf-8") if (HERE / "control.html").exists() else "<p>control.html fehlt</p>"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (HERE / "control.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if self.path.startswith("/api/state"):
            with lock:
                c = dict(cfg)
            ph = phase(c)
            return self._send(200, json.dumps({"overlay": c, "showing": ph, "now": datetime.now().strftime("%H:%M:%S")}, ensure_ascii=False))
        if self.path.startswith("/api/preview.jpg"):
            fr = last_frame
            if fr is None:
                return self._send(503, b"{}")
            im = Image.fromarray(fr[..., [2, 1, 0]]).resize((640, 360)); out = io.BytesIO(); im.save(out, "JPEG", quality=80)
            return self._send(200, out.getvalue(), "image/jpeg")
        self._send(404, b"{}")

    def do_POST(self):
        global cfg
        if self.path != "/api/overlay":
            return self._send(404, b"{}")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            new = json.loads(self.rfile.read(n) or b"{}")
            if new.get("type") not in ("off", "countdown", "text"):
                raise ValueError("type")
            for k in ("until", "hide_at"):
                if new.get(k):
                    hm(new[k])
        except Exception as e:
            return self._send(400, json.dumps({"error": str(e)}))
        with lock:
            cfg = new
            STATE.write_text(json.dumps(cfg, ensure_ascii=False))
        self._send(200, json.dumps({"ok": True, "overlay": cfg}, ensure_ascii=False))


if __name__ == "__main__":
    path, name = sys.argv[1], sys.argv[2]
    PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8099
    def serve():  # Port evtl. noch vom Vorgänger belegt: warten, bis er frei wird
        while True:
            try:
                ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
            except OSError:
                time.sleep(2)
    threading.Thread(target=serve, daemon=True).start()
    player(path, name)
