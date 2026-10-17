"""Aussehen der Einblendungen (Bauchbinde im Stil des ÖGSW-Trailers). Wird vom Player bei jeder Änderung dieser Datei
neu geladen – Design anpassen ohne Neustart und ohne Unterbrechung des NDI-Bilds."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
NAVY, BLUE, ORANGE, WHITE = (6, 34, 70), (110, 190, 240), (243, 146, 0), (240, 246, 252)
LOGO = Path(__file__).with_name("logo.png")


def font(px): return ImageFont.truetype(FONT, px)


def render(ph):
    """ph = (art, titel, groß, untertitel) → (x0, y0, vormultipliziert BGR, 1-alpha) oder None."""
    if not ph:
        return None
    kind, title, big, sub = ph
    bw, bh, x0, y0 = 1460, 190, 230, 820
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=10, fill=NAVY + (232,))
    d.rectangle([0, 0, 14, bh - 1], fill=ORANGE + (255,))
    ls = bh - 30
    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA").resize((ls, ls), Image.LANCZOS)
        img.alpha_composite(logo, (bw - ls - 15, 15))
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
    a = np.asarray(img, dtype=np.float32)
    alpha = a[..., 3:4] / 255.0
    return (x0, y0, a[..., [2, 1, 0]] * alpha, 1.0 - alpha)
