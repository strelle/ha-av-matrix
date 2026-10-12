"""Eigene NDI®-Quelle „… Testbild“: Logo, Name, Testbild-Elemente, Uhr und der QR-Code zum Verbinden.

Zum Auflegen auf einen Studiobildschirm – wie jede andere Quelle der Kreuzschiene. Sparsam:

* Gesendet wird nur, solange die Quelle eingeschaltet **und** ein Empfänger verbunden ist, dann ein Bild
  je Sekunde (die Uhr ist das Lebenszeichen). Ohne Empfänger wartet ein Thread im NDI-Aufruf – keine Last.
* Ausgeschaltet gibt es weder Sender noch Thread.
* Das Bild (1280×720) wird einmal gezeichnet; je Sekunde kommt nur die Uhr dazu.

Der Zustand (ein/aus) steht in ``state.json`` und übersteht einen Neustart. Ohne NDI SDK bleibt die Quelle aus
(``available: false``); ``/api/testpattern.jpg`` zeigt das Bild trotzdem.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .netinfo import connect_urls
from .preview import PreviewManager
from .store import JsonFile

_LOGGER = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
WIDTH, HEIGHT = 1280, 720
BG, FG, MUTED, LINE = (10, 10, 10), (239, 237, 234), (163, 161, 156), (79, 85, 96)
BARS = [(191, 191, 191), (191, 191, 0), (0, 191, 191), (0, 191, 0), (191, 0, 191), (191, 0, 0), (0, 0, 191), (16, 16, 16)]


def qr_matrix(text: str) -> list[list[bool]]:
    """QR-Code als Matrix (True = dunkel), Fehlerkorrektur M, ohne Ruhezone."""
    import segno

    return [[bool(cell) for cell in row] for row in segno.make(text, error="m", micro=False).matrix]


def qr_svg(text: str, *, border: int = 4) -> str:
    """QR-Code als eigenständiges SVG (schwarz auf weiß, mit Ruhezone)."""
    matrix = qr_matrix(text)
    size = len(matrix) + 2 * border
    path = "".join(f"M{x + border},{y + border}h1v1h-1z" for y, row in enumerate(matrix) for x, cell in enumerate(row) if cell)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges" role="img" '
        f'aria-label="QR-Code: {text}"><rect width="{size}" height="{size}" fill="#fff"/><path d="{path}" fill="#000"/></svg>'
    )


def _font(name: str, size: int, weight: int | None = None) -> Any:
    from PIL import ImageFont

    try:
        font = ImageFont.truetype(str(STATIC / "fonts" / name), size)
        if weight:
            try:
                font.set_variation_by_axes([weight])
            except (OSError, AttributeError):
                pass
        return font
    except OSError:
        return ImageFont.load_default(size)


class TestPattern:
    __test__ = False  # kein pytest-Testfall

    def __init__(self, state: JsonFile, info: Callable[[], dict[str, Any]], preview: PreviewManager) -> None:
        self.state = state
        self.info = info
        self.preview = preview
        self.source_name = "Testbild"
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._base: Any = None
        self._base_key: tuple[Any, ...] | None = None
        self.connections = 0
        self.frames = 0
        self.error: str | None = None

    # ------------------------------------------------------------- state
    @property
    def enabled(self) -> bool:
        return bool((self.state.data.get("testpattern") or {}).get("enabled", False))

    def url(self) -> str | None:
        urls = connect_urls(self.info())
        return urls[0]["url"] if urls else None

    def ndi_name(self) -> str:
        return f"{self.info().get('name') or 'Strelle AV Matrix'} {self.source_name}"

    def set_enabled(self, enabled: bool) -> None:
        self.state.data["testpattern"] = {"enabled": bool(enabled)}
        self.state.save()
        self.apply()

    def apply(self) -> None:
        """Sender starten oder beenden, je nach Zustand."""
        if self.enabled and (self._thread is None or not self._thread.is_alive()):
            if not self.preview.available:
                self.error = "NDI SDK nicht installiert"
                return
            self.error = None
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), name="avm-ndi-testbild", daemon=True)
            self._thread.start()
        elif not self.enabled and self._thread is not None:
            self._stop.set()
            self._thread = None
            self.connections = 0

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(3.0)

    def status(self) -> dict[str, Any]:
        running = bool(self._thread and self._thread.is_alive())
        return {
            "enabled": self.enabled,
            "available": self.preview.available,
            "running": running,
            "source": f"{str(self.info().get('hostname', '')).upper()} ({self.ndi_name()})",
            "connections": self.connections if running else 0,
            "frames_sent": self.frames,
            "size": f"{WIDTH}x{HEIGHT}",
            "url": self.url(),
            "error": self.error,
        }

    # ------------------------------------------------------------ picture
    def _draw_base(self) -> Any:
        from PIL import Image, ImageDraw

        info = self.info()
        url = self.url() or ""
        name = str(info.get("name") or "Strelle AV Matrix")
        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        d = ImageDraw.Draw(img)
        title, text, small = _font("AtkinsonHyperlegibleNext-latin.woff2", 54, 800), _font("AtkinsonHyperlegibleNext-latin.woff2", 28, 500), _font("AtkinsonHyperlegibleMono-latin.woff2", 22)
        mono = _font("AtkinsonHyperlegibleMono-latin.woff2", 34, 700)
        # Bildlage: Rahmen, Ecken, Mittenkreuz
        d.rectangle([24, 24, WIDTH - 25, HEIGHT - 25], outline=LINE, width=2)
        for cx, cy, sx, sy in ((24, 24, 1, 1), (WIDTH - 25, 24, -1, 1), (24, HEIGHT - 25, 1, -1), (WIDTH - 25, HEIGHT - 25, -1, -1)):
            d.line([cx, cy, cx + 60 * sx, cy], fill=FG, width=4)
            d.line([cx, cy, cx, cy + 60 * sy], fill=FG, width=4)
        d.line([WIDTH // 2 - 24, HEIGHT // 2, WIDTH // 2 + 24, HEIGHT // 2], fill=LINE, width=2)
        d.line([WIDTH // 2, HEIGHT // 2 - 24, WIDTH // 2, HEIGHT // 2 + 24], fill=LINE, width=2)
        # Marke (Original-Wortmarke, unverändert) und Name
        try:
            logo = Image.open(STATIC / "brand" / "wortmarke-hell.png").convert("RGBA")
            logo = logo.resize((300, round(logo.height * 300 / logo.width)), Image.LANCZOS)
            img.paste(logo, (72, 78), logo)
        except OSError:
            pass
        d.text((72, 168), name, font=title, fill=FG)
        d.text((74, 240), f"Testbild · {info.get('hostname', '')} · {WIDTH}×{HEIGHT}", font=small, fill=MUTED)
        # Farbbalken (75 %) und Graustufen
        x0, x1, y = 72, 716, 300
        step = (x1 - x0) / len(BARS)
        for i, color in enumerate(BARS):
            d.rectangle([round(x0 + i * step), y, round(x0 + (i + 1) * step) - 1, y + 130], fill=color)
        step = (x1 - x0) / 11
        for i in range(11):
            v = round(255 * i / 10)
            d.rectangle([round(x0 + i * step), y + 138, round(x0 + (i + 1) * step) - 1, y + 190], fill=(v, v, v))
        d.rectangle([x0, y, x1 - 1, y + 190], outline=LINE, width=1)
        d.text((72, 520), "Kreuzschiene am Telefon öffnen", font=text, fill=FG)
        d.text((72, 560), "QR-Code scannen – das Telefon muss im selben Netz sein.", font=small, fill=MUTED)
        # QR-Code: groß, schwarz auf weiß, Adresse als Klartext darunter
        if url:
            matrix = qr_matrix(url)
            box, quiet = 420, 4
            scale = box // (len(matrix) + 2 * quiet)
            side = scale * (len(matrix) + 2 * quiet)
            bx, by = WIDTH - 72 - side, 84
            d.rectangle([bx, by, bx + side - 1, by + side - 1], fill=(255, 255, 255))
            for ry, row in enumerate(matrix):
                for rx, cell in enumerate(row):
                    if cell:
                        px, py = bx + (rx + quiet) * scale, by + (ry + quiet) * scale
                        d.rectangle([px, py, px + scale - 1, py + scale - 1], fill=(0, 0, 0))
            shown = url.removeprefix("http://").rstrip("/")
            width = d.textlength(shown, font=mono)
            d.text((bx + side / 2 - width / 2, by + side + 18), shown, font=mono, fill=FG)
        return img

    def render(self, now: datetime | None = None) -> Any:
        """Das Bild für diesen Augenblick (PIL, RGB)."""
        from PIL import ImageDraw

        info = self.info()
        key = (self.url(), info.get("name"), info.get("hostname"))
        if self._base is None or key != self._base_key:
            self._base, self._base_key = self._draw_base(), key
        now = now or datetime.now()
        img = self._base.copy()
        d = ImageDraw.Draw(img)
        d.text((72, 612), now.strftime("%H:%M:%S"), font=_font("AtkinsonHyperlegibleMono-latin.woff2", 52, 700), fill=FG)
        d.text((340, 632), now.strftime("%d.%m.%Y"), font=_font("AtkinsonHyperlegibleMono-latin.woff2", 26), fill=MUTED)
        if now.second % 2 == 0:  # Lebenszeichen
            d.ellipse([560, 632, 584, 656], fill=(255, 75, 66))
        return img

    def jpeg(self, quality: int = 85) -> bytes:
        out = io.BytesIO()
        self.render().save(out, "JPEG", quality=quality)
        return out.getvalue()

    # ------------------------------------------------------------- sender
    def _run(self, stop: threading.Event) -> None:
        lib = self.preview._load()
        if lib is None:
            return
        try:
            handle = lib.send_open(self.ndi_name())
        except OSError as err:
            self.error = str(err)
            _LOGGER.warning("Testbild: %s", err)
            return
        _LOGGER.info("Testbild-Quelle bereit: %s", self.ndi_name())
        try:
            while not stop.is_set():
                self.connections = lib.send_connections(handle, 1000)  # wartet bis zu 1 s auf einen Empfänger
                if self.connections <= 0:
                    continue
                started = time.monotonic()
                frame = self.render().convert("RGBA")
                lib.send_frame(handle, WIDTH, HEIGHT, frame.tobytes())
                self.frames += 1
                stop.wait(max(0.05, 1.0 - (time.monotonic() - started)))
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Testbild-Sender abgebrochen")
            self.error = "Sender abgebrochen, siehe Protokoll"
        finally:
            lib.send_close(handle)
            self.connections = 0
            _LOGGER.info("Testbild-Quelle beendet")
