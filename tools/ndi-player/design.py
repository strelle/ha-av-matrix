"""Einblendungen (Stil des ÖGSW-Trailers): was gezeigt wird, wie es aussieht und was die Steuerseite setzen darf.
Der Player lädt diese Datei bei jeder Änderung neu – neue Einblendungen und Designänderungen ohne Neustart und
ohne Unterbrechung des NDI-Bilds.

Zustand (overlay_state.json) besteht aus unabhängigen Ebenen:
  main: countdown {type, label, until "HH:MM", after_text, hide_at} | text {type, title, subtitle, hide_at} | {type: off}
  wifi: {on, label, ssid, password, security "WPA"|"WEP"|"nopass", show_password, hidden, hide_at}
"""
from datetime import datetime
from pathlib import Path

import numpy as np
import segno
from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
NAVY, BLUE, ORANGE, WHITE = (6, 34, 70), (110, 190, 240), (243, 146, 0), (240, 246, 252)
LOGO = Path(__file__).with_name("logo.png")


def font(px): return ImageFont.truetype(FONT, px)


def hm(s):
    h, m = map(int, s.split(":")); return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)


def hidden(c): return bool(c.get("hide_at")) and datetime.now() >= hm(c["hide_at"])


# ---------- Zustand ----------

def normalize(cfg):
    """Alter Zustand (nur eine Einblendung auf oberster Ebene) → Ebenen."""
    if "type" in cfg:
        return {"main": cfg}
    return cfg


def validate(section, data):
    """Prüft eine Ebene, die die Steuerseite setzen will; wirft ValueError bei Unsinn."""
    if section == "main":
        if data.get("type") not in ("off", "countdown", "text"):
            raise ValueError("Art der Einblendung unbekannt")
        if data["type"] == "countdown" and not data.get("until"):
            raise ValueError("Countdown braucht eine Uhrzeit")
    elif section == "wifi":
        if data.get("on") and not (data.get("ssid") or "").strip():
            raise ValueError("WLAN-Name fehlt")
        if data.get("security", "WPA") not in ("WPA", "WEP", "nopass"):
            raise ValueError("Verschlüsselung unbekannt")
        if data.get("on") and data.get("security", "WPA") != "nopass" and not data.get("password"):
            raise ValueError("Passwort fehlt (oder Verschlüsselung auf „offen“ stellen)")
    else:
        raise ValueError("Ebene unbekannt")
    for k in ("until", "hide_at"):
        if data.get(k):
            hm(data[k])
    return data


def main_phase(c):
    """(art, titel, groß, untertitel) oder None."""
    if not c or hidden(c):
        return None
    if c.get("type") == "countdown":
        left = int((hm(c["until"]) - datetime.now()).total_seconds())
        if left > 0:
            m, s = divmod(left, 60); h, m = divmod(m, 60)
            return ("count", (c.get("label") or "Pause").upper(), f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}", f"Weiter um {c['until']} Uhr")
        return ("text", (c.get("after_text") or "Es geht gleich weiter").upper(), "", "")
    if c.get("type") == "text":
        return ("text", (c.get("title") or "").upper(), "", c.get("subtitle") or "")
    return None


def wifi_phase(c):
    if not c or not c.get("on") or hidden(c):
        return None
    return ("wifi", c.get("label") or "WLAN", c.get("ssid", ""), c.get("password", ""), c.get("security", "WPA"),
            bool(c.get("show_password", True)), bool(c.get("hidden")))


def showing(cfg):
    """Was gerade sichtbar ist (für Steuerseite und Zwischenspeicher)."""
    cfg = normalize(cfg)
    return {"main": main_phase(cfg.get("main")), "wifi": wifi_phase(cfg.get("wifi"))}


# ---------- Aussehen ----------

def _layer(img, x0, y0):
    a = np.asarray(img, dtype=np.float32); alpha = a[..., 3:4] / 255.0
    return (x0, y0, a[..., [2, 1, 0]] * alpha, 1.0 - alpha)


def _panel(w, h):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=10, fill=NAVY + (232,))
    return img, d


def render_main(ph):
    kind, title, big, sub = ph
    bw, bh = 1460, 190
    img, d = _panel(bw, bh)
    d.rectangle([0, 0, 14, bh - 1], fill=ORANGE + (255,))
    ls = bh - 30
    if LOGO.exists():
        img.alpha_composite(Image.open(LOGO).convert("RGBA").resize((ls, ls), Image.LANCZOS), (bw - ls - 15, 15))
    right = bw - ls - 50
    if kind == "count":
        d.text((60, 30), title, font=font(62), fill=BLUE + (255,))
        d.text((60, 100), sub, font=font(46), fill=WHITE + (235,))
        tw = d.textlength(big, font=font(150))
        d.text((right - tw, 18), big, font=font(150), fill=WHITE + (255,))
    else:
        f = font(96) if not sub else font(84)
        d.text((60, 40 if sub else 50), title, font=f, fill=WHITE + (255,))
        if sub:
            d.text((62, 124), sub, font=font(44), fill=BLUE + (255,))
    return _layer(img, 230, 820)


def wifi_icon(d, cx, base, r, color, width):
    """WLAN-Symbol: drei Bögen und Punkt, Spitze unten bei (cx, base)."""
    for i in (1, 2, 3):
        rr = r * i / 3
        d.arc([cx - rr, base - rr, cx + rr, base + rr], 225, 315, fill=color, width=width)
    d.ellipse([cx - width * 0.9, base - width * 1.8, cx + width * 0.9, base], fill=color)


def _esc(s): return "".join("\\" + ch if ch in '\\;,:"' else ch for ch in s)


def render_wifi(ph):
    _, label, ssid, pw, sec, show_pw, hid = ph
    payload = f"WIFI:T:{sec};S:{_esc(ssid)};" + (f"P:{_esc(pw)};" if sec != "nopass" else "") + ("H:true;" if hid else "") + ";"
    qr = segno.make(payload, error="m")
    q = 300; buf = __import__("io").BytesIO(); qr.save(buf, kind="png", scale=10, border=2); buf.seek(0)
    qimg = Image.open(buf).convert("RGBA").resize((q, q), Image.NEAREST)
    pw_line = pw if (show_pw and sec != "nopass") else ""
    bw = 360; bh = 104 + q + 20 + 52 + (44 if pw_line else 0) + 26
    img, d = _panel(bw, bh)
    d.rectangle([0, 0, bw - 1, 12], fill=ORANGE + (255,))
    wifi_icon(d, 52, 86, 42, WHITE + (255,), 7)
    d.text((104, 34), label.upper(), font=font(56), fill=WHITE + (255,))
    d.rounded_rectangle([(bw - q) // 2 - 6, 98, (bw + q) // 2 + 5, 98 + q + 11], radius=8, fill=(255, 255, 255, 255))
    img.alpha_composite(qimg, ((bw - q) // 2, 104))
    y = 104 + q + 20
    d.text((24, y), ssid, font=font(46), fill=WHITE + (255,))
    if pw_line:
        d.text((24, y + 52), pw_line, font=font(38), fill=BLUE + (255,))
    return _layer(img, 1920 - bw - 40, 40)


def render(show):
    """show = showing(cfg) → Liste von Ebenen (x0, y0, vormultipliziert BGR, 1-alpha)."""
    out = []
    if show.get("main"):
        out.append(render_main(show["main"]))
    if show.get("wifi"):
        out.append(render_wifi(show["wifi"]))
    return out
