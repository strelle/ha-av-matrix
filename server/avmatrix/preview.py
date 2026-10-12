"""NDI®-Vorschau: Standbilder und eine Live-Vorschau direkt aus dem NDI-Feed – sparsam.

Empfangen wird mit dem offiziellen NDI SDK (``libndi``, per ctypes), immer in der niedrigsten
Bandbreite (Proxy-Stream, meist 640×360) und nur, solange jemand zuschaut:

* **Standbild**: Empfänger öffnen, erstes Bild nehmen, Empfänger sofort wieder schließen. Ein offener
  Empfänger dekodiert laufend jedes Bild (auf dem Pi 4 rund 20–25 % eines Kerns je Quelle) – darum bleibt
  für Kacheln nie einer offen. Ergebnis wird wenige Sekunden zwischengespeichert und von allen Panels geteilt.
* **Live**: ein Empfänger je Quelle, höchstens ``max_live`` gleichzeitig (Vorgabe 1 – die eine angeklickte
  Quelle). Er schließt, sobald niemand mehr zuschaut (``live_linger`` Sekunden Nachlauf) oder nach
  ``live_max_seconds``.
* Ohne Anfrage läuft nichts: kein Empfänger, kein Thread, keine CPU-Last.

Die SDK-Bibliothek liegt außerhalb des Repos (``deploy/install-ndi-sdk.sh``). Fehlt sie, meldet die
Schnittstelle ``unavailable`` – es werden nie Platzhalterbilder ausgeliefert.

NDI® ist eine eingetragene Marke der Vizrt NDI AB.
"""

from __future__ import annotations

import asyncio
import ctypes as C
import io
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .store import data_dir

_LOGGER = logging.getLogger(__name__)

RECV_BANDWIDTH_LOWEST = 0
RECV_COLOR_RGBX_RGBA = 2
FRAME_NONE, FRAME_VIDEO, FRAME_ERROR = 0, 1, 4

STATE_OK = "ok"
STATE_OFFLINE = "offline"  # Quelle ist nicht im Netz
STATE_NO_SIGNAL = "no_signal"  # Quelle ist da, liefert aber kein Bild
STATE_UNAVAILABLE = "unavailable"  # NDI SDK nicht installiert
STATE_UNKNOWN = "unknown_source"
STATE_UNSUPPORTED = "unsupported_codec"  # NDI|HX (H.264/HEVC) ohne installierten Decoder

MESSAGES = {
    STATE_OFFLINE: "Quelle ist offline",
    STATE_NO_SIGNAL: "Kein Signal",
    STATE_UNAVAILABLE: "NDI-Vorschau nicht verfügbar (NDI SDK ist nicht installiert)",
    STATE_UNKNOWN: "Unbekannte NDI-Quelle",
    STATE_UNSUPPORTED: "Kein Vorschaubild: NDI|HX-Quelle, der Decoder (libavcodec) ist auf diesem Rechner nicht installiert",
}


class _Source(C.Structure):
    _fields_ = [("p_ndi_name", C.c_char_p), ("p_url_address", C.c_char_p)]


class _RecvCreate(C.Structure):
    _fields_ = [
        ("source_to_connect_to", _Source),
        ("color_format", C.c_int),
        ("bandwidth", C.c_int),
        ("allow_video_fields", C.c_bool),
        ("p_ndi_recv_name", C.c_char_p),
    ]


class _VideoFrame(C.Structure):
    _fields_ = [
        ("xres", C.c_int),
        ("yres", C.c_int),
        ("FourCC", C.c_int),
        ("frame_rate_N", C.c_int),
        ("frame_rate_D", C.c_int),
        ("picture_aspect_ratio", C.c_float),
        ("frame_format_type", C.c_int),
        ("timecode", C.c_int64),
        ("p_data", C.c_void_p),
        ("line_stride_in_bytes", C.c_int),
        ("p_metadata", C.c_char_p),
        ("timestamp", C.c_int64),
    ]


class _SendCreate(C.Structure):
    _fields_ = [("p_ndi_name", C.c_char_p), ("p_groups", C.c_char_p), ("clock_video", C.c_bool), ("clock_audio", C.c_bool)]


FOURCC_RGBA = ord("R") | ord("G") << 8 | ord("B") << 16 | ord("A") << 24


@dataclass(slots=True)
class RawFrame:
    width: int
    height: int
    stride: int
    data: bytes


class NdiLib:
    """Dünne ctypes-Hülle um libndi (nur Empfang)."""

    def __init__(self, path: Path) -> None:
        # libndi verlangt libavahi-client; liegt sie neben libndi (Installation ohne Root), zuerst laden
        for helper in sorted(path.parent.glob("libavahi-client.so*")):
            try:
                C.CDLL(str(helper), mode=C.RTLD_GLOBAL)
                break
            except OSError:
                continue
        lib = C.CDLL(str(path))
        lib.NDIlib_initialize.restype = C.c_bool
        lib.NDIlib_version.restype = C.c_char_p
        lib.NDIlib_recv_create_v3.restype = C.c_void_p
        lib.NDIlib_recv_create_v3.argtypes = [C.POINTER(_RecvCreate)]
        lib.NDIlib_recv_capture_v2.restype = C.c_int
        lib.NDIlib_recv_capture_v2.argtypes = [C.c_void_p, C.POINTER(_VideoFrame), C.c_void_p, C.c_void_p, C.c_uint32]
        lib.NDIlib_recv_free_video_v2.argtypes = [C.c_void_p, C.POINTER(_VideoFrame)]
        lib.NDIlib_recv_destroy.argtypes = [C.c_void_p]
        lib.NDIlib_send_create.restype = C.c_void_p
        lib.NDIlib_send_create.argtypes = [C.POINTER(_SendCreate)]
        lib.NDIlib_send_send_video_v2.argtypes = [C.c_void_p, C.POINTER(_VideoFrame)]
        lib.NDIlib_send_get_no_connections.restype = C.c_int
        lib.NDIlib_send_get_no_connections.argtypes = [C.c_void_p, C.c_uint32]
        lib.NDIlib_send_destroy.argtypes = [C.c_void_p]
        if not lib.NDIlib_initialize():
            raise OSError("NDIlib_initialize meldet: diese CPU wird nicht unterstützt")
        self._lib = lib
        self.path = path
        self.version = (lib.NDIlib_version() or b"").decode(errors="replace")

    def open(self, name: str, address: str | None) -> int:
        create = _RecvCreate(
            _Source(name.encode(), address.encode() if address else None),
            RECV_COLOR_RGBX_RGBA,
            RECV_BANDWIDTH_LOWEST,
            False,
            b"Strelle AV Matrix Vorschau",
        )
        handle = self._lib.NDIlib_recv_create_v3(C.byref(create))
        if not handle:
            raise OSError("NDI-Empfänger konnte nicht angelegt werden")
        return handle

    def capture(self, handle: int, timeout_ms: int) -> RawFrame | int:
        """Ein Bild (``RawFrame``) oder der Frame-Typ (0 = nichts, 4 = Verbindung verloren …)."""
        frame = _VideoFrame()
        kind = self._lib.NDIlib_recv_capture_v2(handle, C.byref(frame), None, None, timeout_ms)
        if kind != FRAME_VIDEO:
            return kind
        try:
            if not frame.p_data or frame.xres <= 0 or frame.yres <= 0 or frame.line_stride_in_bytes < frame.xres * 4:
                return FRAME_NONE
            data = C.string_at(frame.p_data, frame.line_stride_in_bytes * frame.yres)
            return RawFrame(frame.xres, frame.yres, frame.line_stride_in_bytes, data)
        finally:
            self._lib.NDIlib_recv_free_video_v2(handle, C.byref(frame))

    def close(self, handle: int) -> None:
        self._lib.NDIlib_recv_destroy(handle)

    # ---- Senden (nur für die eigene Testbild-Quelle)
    def send_open(self, name: str) -> int:
        handle = self._lib.NDIlib_send_create(C.byref(_SendCreate(name.encode(), None, False, False)))
        if not handle:
            raise OSError("NDI-Sender konnte nicht angelegt werden (Name schon vergeben?)")
        return handle

    def send_connections(self, handle: int, timeout_ms: int) -> int:
        return int(self._lib.NDIlib_send_get_no_connections(handle, timeout_ms))

    def send_frame(self, handle: int, width: int, height: int, rgba: bytes) -> None:
        buffer = C.create_string_buffer(rgba, len(rgba))
        frame = _VideoFrame(width, height, FOURCC_RGBA, 25000, 1000, width / height, 1, 0x7FFFFFFFFFFFFFFF,
                            C.cast(buffer, C.c_void_p).value, width * 4, None, 0)  # fmt: skip
        self._lib.NDIlib_send_send_video_v2(handle, C.byref(frame))  # kehrt zurück, wenn das Bild übergeben ist

    def send_close(self, handle: int) -> None:
        self._lib.NDIlib_send_destroy(handle)


def hx_decoder_available() -> bool:
    """NDI|HX (H.264/HEVC) dekodiert libndi unter Linux nur mit FFmpeg: libavcodec.so.61 und libavutil.so.59."""
    for name in ("libavcodec.so.61", "libavutil.so.59"):
        try:
            C.CDLL(name)
        except OSError:
            return False
    return True


def is_decoder_placeholder(frame: RawFrame) -> bool:
    """libndi liefert statt eines HX-Bildes eine Hinweistafel („Video decoder not found“): volle Größe, fast schwarz."""
    if frame.width < 960:
        return False  # der Proxy-Stream echter Quellen ist klein
    data, total, dark = frame.data, 0, 0
    for offset in range(0, len(data) - 4, 4 * 211):
        total += 1
        if data[offset] < 24 and data[offset + 1] < 24 and data[offset + 2] < 24:
            dark += 1
    return total > 0 and dark / total > 0.93


_DEVICE_CONFIG: dict[str, tuple[float, Any]] = {}  # Adresse → (Zeitpunkt, Kanalliste | None)


def device_snapshot(host: str, channel: str, timeout: float = 3.0) -> bytes | None:
    """Standbild direkt vom Gerät – Rückfall für Encoder, deren NDI-Strom sich nicht dekodieren lässt.

    Unterstützt: LinkPi-Firmware (u. a. TBS-Encoder): ``/config/config.json`` nennt die Kanäle samt NDI-Namen,
    ``enc.snap`` über ``/RPC`` legt ``/snap/snap<id>.jpg`` ab. Am Gerät wird nichts umgestellt.
    Andere Geräte → ``None`` (zehn Minuten gemerkt, damit nicht jede Abfrage erneut anklopft).
    """
    import json as _json
    import urllib.request

    def call(path: str, data: bytes | None = None) -> tuple[str, bytes]:
        req = urllib.request.Request(f"http://{host}{path}", data=data, headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste http-Adresse im Studionetz
            return resp.headers.get("Content-Type", ""), resp.read(4_000_000)

    now = time.monotonic()
    cached = _DEVICE_CONFIG.get(host)
    try:
        if cached is None or now - cached[0] > 600:
            channels = None
            try:
                data = _json.loads(call("/config/config.json")[1])
                if isinstance(data, list) and data and isinstance(data[0], dict) and "ndi" in data[0]:
                    channels = [(c.get("id"), str((c.get("ndi") or {}).get("name", ""))) for c in data if isinstance(c, dict)]
            except (OSError, ValueError):
                channels = None
            cached = _DEVICE_CONFIG[host] = (now, channels)
        if not cached[1]:
            return None
        ident = next((cid for cid, name in cached[1] if name.casefold() == channel.casefold()), None)
        if ident is None:
            return None
        call("/RPC", b'{"jsonrpc":"2.0","method":"enc.snap","params":[],"id":1}')
        time.sleep(0.5)
        ctype, body = call(f"/snap/snap{int(ident)}.jpg")
        return body if ctype.startswith("image/") and body[:2] == b"\xff\xd8" else None
    except (OSError, ValueError, TypeError):
        return None


def scale_jpeg(data: bytes, width: int, quality: int) -> tuple[bytes, int, int]:
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    size = image.size
    if 0 < width < image.width:
        image.draft("RGB", (width, width))  # JPEG gleich verkleinert dekodieren
    image = image.convert("RGB")
    if 0 < width < image.width:
        image = image.resize((width, max(1, round(image.height * width / image.width))), Image.BILINEAR)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality)
    return out.getvalue(), size[0], size[1]


def find_library() -> Path | None:
    candidates = [os.environ.get("AVM_NDI_LIB") or "", str(data_dir() / "ndi" / "libndi.so.6")]
    candidates += [f"{d}/libndi.so.6" for d in ("/usr/local/lib", "/usr/lib", "/usr/lib/aarch64-linux-gnu")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def encode_jpeg(frame: RawFrame, width: int, quality: int) -> bytes:
    """RGBX → JPEG, auf höchstens ``width`` Pixel Breite verkleinert (nie vergrößert)."""
    from PIL import Image  # erst hier laden: ohne Vorschau braucht der Server Pillow nicht

    image = Image.frombuffer("RGBX", (frame.width, frame.height), frame.data, "raw", "RGBX", frame.stride, 1).convert("RGB")
    if 0 < width < frame.width:
        factor = frame.width // width
        if factor >= 2:
            image = image.reduce(factor)  # schnelle ganzzahlige Verkleinerung
        if image.width > width:
            image = image.resize((width, max(1, round(image.height * width / image.width))), Image.BILINEAR)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality)
    return out.getvalue()


@dataclass(slots=True)
class Thumb:
    state: str
    jpeg: bytes | None = None
    at: float = 0.0  # time.monotonic() der Aufnahme
    width: int = 0
    height: int = 0
    origin: str = "ndi"  # "ndi" = aus dem NDI-Feed, "device" = Standbild-Funktion des Geräts

    @property
    def age(self) -> float:
        return time.monotonic() - self.at


@dataclass(eq=False)
class LiveReceiver:
    """Ein offener Empfänger (eigener Thread) für die Live-Vorschau einer Quelle."""

    source: str
    address: str | None
    width: int
    fps: float
    started: float = field(default_factory=time.monotonic)
    frames: int = 0
    state: str = "connecting"
    subscribers: set[asyncio.Queue[bytes | None]] = field(default_factory=set)
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    last_jpeg: bytes | None = None
    last_frame: RawFrame | None = None
    last_at: float = 0.0
    empty_since: float | None = None


class PreviewManager:
    def __init__(self, registry: Any, options: dict[str, Any] | None = None) -> None:
        opts = options or {}
        self.registry = registry
        self.enabled = bool(opts.get("enabled", True))
        self.thumb_width = int(opts.get("thumb_width", 320))
        self.thumb_ttl = float(opts.get("thumb_ttl", 4.0))
        self.thumb_timeout = float(opts.get("thumb_timeout", 2.5))
        #: NDI|HX kostet ein Vielfaches (volle Auflösung, Software-Dekodierung): Standbilder seltener holen
        self.hx_ttl = float(opts.get("hx_ttl", 20.0))
        self.hx_timeout = float(opts.get("hx_timeout", 5.0))  # das erste dekodierbare Bild braucht einen Keyframe
        #: Live für HX: "stills" = Standbild alle hx_live_interval Sekunden, "stream" = offener Empfänger
        self.hx_live = str(opts.get("hx_live", "stills"))
        self.hx_live_interval = float(opts.get("hx_live_interval", 2.0))
        self.hx_live_fps = float(opts.get("hx_live_fps", 5.0))
        #: Quellen ohne dekodierbares Bild nicht alle paar Sekunden neu versuchen
        self.fail_ttl = float(opts.get("fail_ttl", 60.0))
        self._heavy: set[str] = set()  # Quellen, die in voller Auflösung ankommen (HX) oder vom Gerät geholt werden
        self.device_fallback = bool(opts.get("device_fallback", True))
        self._device_only: set[str] = set()
        self.max_parallel = max(1, int(opts.get("max_parallel", 2)))
        self.max_live = max(0, int(opts.get("max_live", 1)))
        self.live_width = int(opts.get("live_width", 640))
        self.live_fps = float(opts.get("live_fps", 12.5))
        self.live_linger = float(opts.get("live_linger", 3.0))
        self.live_max_seconds = float(opts.get("live_max_seconds", 600.0))
        self.quality = int(opts.get("jpeg_quality", 72))
        self._lib: NdiLib | None = None
        self._lib_error: str | None = None
        self._lib_tried = False
        self.hx_decoder: bool | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._slots = asyncio.Semaphore(self.max_parallel)
        self._thumbs: dict[str, Thumb] = {}
        self._inflight: dict[str, asyncio.Task[Thumb]] = {}
        self._live: dict[str, LiveReceiver] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self.opened_total = 0
        self.closed_total = 0
        self.open_now = 0
        self._count_lock = threading.Lock()

    # ------------------------------------------------------------ library
    def _load(self) -> NdiLib | None:
        if not self._lib_tried:
            self._lib_tried = True
            if not self.enabled:
                self._lib_error = "in der Konfiguration abgeschaltet (preview.enabled)"
                return None
            path = find_library()
            if path is None:
                self._lib_error = "libndi.so.6 nicht gefunden (deploy/install-ndi-sdk.sh ausführen)"
                return None
            try:
                self._lib = NdiLib(path)
                self.hx_decoder = hx_decoder_available()
                _LOGGER.info("NDI-Vorschau bereit: %s (%s), NDI|HX-Decoder: %s", self._lib.version, path, "ja" if self.hx_decoder else "nein")
            except OSError as err:
                self._lib_error = str(err)
                _LOGGER.warning("NDI SDK lässt sich nicht laden: %s", err)
        return self._lib

    @property
    def available(self) -> bool:
        return self._load() is not None

    def _pool(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_parallel, thread_name_prefix="avm-ndi")
        return self._executor

    def _opened(self) -> None:
        with self._count_lock:
            self.opened_total += 1
            self.open_now += 1

    def _closed(self) -> None:
        with self._count_lock:
            self.closed_total += 1
            self.open_now -= 1

    # ------------------------------------------------------------ sources
    def source_state(self, source_id: str) -> tuple[str, str | None]:
        """``(Zustand, Adresse)`` einer Quelle laut Quellenregister, ohne einen Empfänger zu öffnen."""
        if self._load() is None:
            return STATE_UNAVAILABLE, None
        record = self.registry.get(source_id)
        if record is None:
            return STATE_UNKNOWN, None
        if not record.live:
            return STATE_OFFLINE, None
        return STATE_OK, record.address

    # --------------------------------------------------------- thumbnails
    def _grab(self, name: str, address: str | None) -> RawFrame | None:
        """Empfänger öffnen, erstes Bild holen, Empfänger schließen (läuft im Thread)."""
        lib = self._lib
        assert lib is not None
        handle = lib.open(name, address)
        self._opened()
        try:
            deadline = time.monotonic() + (self.hx_timeout if self.hx_decoder else self.thumb_timeout)
            while time.monotonic() < deadline:
                got = lib.capture(handle, 250)
                if isinstance(got, RawFrame):
                    return got
                if got == FRAME_ERROR:
                    return None
            return None
        finally:
            lib.close(handle)
            self._closed()

    def _device_still(self, name: str, address: str | None, width: int) -> Thumb | None:
        """Der NDI-Strom liefert nichts Dekodierbares: Standbild des Geräts holen, wenn es das anbietet."""
        if not self.device_fallback or not address:
            return None
        host = address.rsplit(":", 1)[0]
        channel = name[name.rfind("(") + 1 : name.rfind(")")] if "(" in name and name.endswith(")") else name
        data = device_snapshot(host, channel)
        if data is None:
            return None
        try:
            jpeg, w, h = scale_jpeg(data, width, self.quality)
        except Exception:  # noqa: BLE001 - kein gültiges Bild
            return None
        self._heavy.add(name)  # seltener holen: jedes Bild ist ein Auftrag an das Gerät
        return Thumb(STATE_OK, jpeg, time.monotonic(), w, h, origin="device")

    def _grab_jpeg(self, name: str, address: str | None, width: int) -> Thumb:
        if name in self._device_only:  # der NDI-Strom dieser Quelle war nicht dekodierbar: gleich das Gerät fragen
            fallback = self._device_still(name, address, width)
            if fallback is not None:
                return fallback
            self._device_only.discard(name)
        frame = self._grab(name, address)
        if frame is None or (not self.hx_decoder and is_decoder_placeholder(frame)):
            fallback = self._device_still(name, address, width)
            if fallback is not None:
                self._device_only.add(name)
                return fallback
        if not self.hx_decoder and (frame is None or is_decoder_placeholder(frame)):
            # die Quelle ist angekündigt, liefert aber nichts Dekodierbares: ohne FFmpeg ist das fast immer NDI|HX
            return Thumb(STATE_UNSUPPORTED, at=time.monotonic())
        if frame is None:
            return Thumb(STATE_NO_SIGNAL, at=time.monotonic())
        if frame.width > 960:  # kein Proxy-Stream: NDI|HX in voller Auflösung
            self._heavy.add(name)
        jpeg = encode_jpeg(frame, width, self.quality)
        return Thumb(STATE_OK, jpeg, time.monotonic(), frame.width, frame.height)

    async def thumbnail(self, source_id: str, width: int | None = None) -> Thumb:
        """Aktuelles Standbild einer Quelle (höchstens ``thumb_ttl`` Sekunden alt) oder ihr Zustand."""
        width = max(64, min(int(width or self.thumb_width), 640))
        state, address = self.source_state(source_id)
        key = f"{source_id}\0{width}"
        if state != STATE_OK:
            self._thumbs.pop(key, None)  # kein altes Bild ausliefern, wenn die Quelle weg ist
            return Thumb(state)
        live = self._live.get(source_id)
        if live is not None and live.last_frame is not None and time.monotonic() - live.last_at < 2.0:
            # die Live-Vorschau dieser Quelle läuft ohnehin: kein zweiter Empfänger
            frame, at = live.last_frame, live.last_at
            cached = self._thumbs.get(key)
            if cached is None or cached.at < at - 1.0:
                jpeg = await asyncio.get_running_loop().run_in_executor(self._pool(), encode_jpeg, frame, width, self.quality)
                cached = self._thumbs[key] = Thumb(STATE_OK, jpeg, at, frame.width, frame.height)
            return cached
        cached = self._thumbs.get(key)
        if cached is not None:
            ttl = self.thumb_ttl if cached.state == STATE_OK else self.fail_ttl
            if cached.state == STATE_OK and source_id in self._heavy:
                ttl = self.hx_ttl
            if cached.age < ttl:
                return cached
        task = self._inflight.get(key)
        if task is None:
            task = self._inflight[key] = asyncio.ensure_future(self._capture(key, source_id, address, width))
            task.add_done_callback(lambda _t: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    async def _capture(self, key: str, source_id: str, address: str | None, width: int) -> Thumb:
        async with self._slots:  # Obergrenze gleichzeitiger Empfänger
            try:
                thumb = await asyncio.get_running_loop().run_in_executor(self._pool(), self._grab_jpeg, source_id, address, width)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Vorschau von %s fehlgeschlagen: %s", source_id, err)
                thumb = Thumb(STATE_NO_SIGNAL, at=time.monotonic())
        self._thumbs[key] = thumb
        if len(self._thumbs) > 64:  # alte Einträge (verschwundene Quellen, andere Breiten) wegräumen
            for old in sorted(self._thumbs, key=lambda k: self._thumbs[k].at)[:16]:
                self._thumbs.pop(old, None)
        return thumb

    # ---------------------------------------------------------------- live
    def _live_stills(self, rx: LiveReceiver) -> None:
        """Live-Vorschau einer HX-Quelle als Folge von Standbildern: öffnen, ein Bild, schließen, warten."""
        assert self._loop is not None
        _LOGGER.info("Live-Vorschau (Standbilder, NDI|HX): %s", rx.source)
        try:
            while not rx.stop.is_set() and time.monotonic() - rx.started < self.live_max_seconds:
                now = time.monotonic()
                if not rx.subscribers:
                    rx.empty_since = rx.empty_since or now
                    if now - rx.empty_since > self.live_linger:
                        break
                else:
                    rx.empty_since = None
                    thumb = self._grab_jpeg(rx.source, rx.address, rx.width)
                    if thumb.state != STATE_OK or thumb.jpeg is None:
                        rx.state = thumb.state
                        break
                    rx.last_at, rx.state = time.monotonic(), STATE_OK
                    rx.last_jpeg = thumb.jpeg
                    rx.frames += 1
                    self._loop.call_soon_threadsafe(self._publish, rx, rx.last_jpeg)
                rx.stop.wait(self.hx_live_interval)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Live-Vorschau %s abgebrochen", rx.source)
        finally:
            _LOGGER.info("Live-Vorschau geschlossen: %s (%d Bilder)", rx.source, rx.frames)
            self._loop.call_soon_threadsafe(self._live_ended, rx)

    def _live_thread(self, rx: LiveReceiver) -> None:
        lib = self._lib
        assert lib is not None and self._loop is not None
        if rx.source in self._heavy and self.hx_live != "stream":
            self._live_stills(rx)
            return
        try:
            handle = lib.open(rx.source, rx.address)
        except OSError as err:
            _LOGGER.warning("Live-Vorschau %s: %s", rx.source, err)
            rx.state = STATE_NO_SIGNAL
            self._loop.call_soon_threadsafe(self._live_ended, rx)
            return
        self._opened()
        _LOGGER.info("Live-Vorschau geöffnet: %s", rx.source)
        interval = 1.0 / max(1.0, rx.fps)
        opened = last_sent = time.monotonic()
        try:
            while not rx.stop.is_set():
                now = time.monotonic()
                if now - rx.started > self.live_max_seconds:
                    break
                if not rx.subscribers:
                    rx.empty_since = rx.empty_since or now
                    if now - rx.empty_since > self.live_linger:
                        break  # niemand schaut mehr zu
                else:
                    rx.empty_since = None
                got = lib.capture(handle, 250)
                now = time.monotonic()
                if isinstance(got, RawFrame):
                    if rx.last_frame is None and not self.hx_decoder and is_decoder_placeholder(got):
                        rx.state = STATE_UNSUPPORTED  # Hinweistafel der Bibliothek, kein Bild der Quelle
                        break
                    rx.last_frame, rx.last_at, rx.state = got, now, STATE_OK
                    if got.width > 960 and rx.source not in self._heavy:
                        self._heavy.add(rx.source)  # erst jetzt als HX erkannt
                        if self.hx_live != "stream":
                            lib.close(handle)
                            self._closed()
                            handle = None
                            self._live_stills(rx)
                            return
                        interval = max(interval, 1.0 / max(1.0, self.hx_live_fps))
                    if now - last_sent >= interval * 0.85 and rx.subscribers:
                        rx.last_jpeg = encode_jpeg(got, rx.width, self.quality)
                        rx.frames += 1
                        last_sent = now
                        self._loop.call_soon_threadsafe(self._publish, rx, rx.last_jpeg)
                elif got == FRAME_ERROR:
                    rx.state = STATE_NO_SIGNAL
                    break
                elif rx.last_jpeg is not None and now - last_sent >= 1.0 and rx.subscribers:
                    # ruhendes Bild (Testbild, Standbild): letztes Bild wiederholen, damit der Stream lebt
                    last_sent = now
                    self._loop.call_soon_threadsafe(self._publish, rx, rx.last_jpeg)
                elif rx.last_frame is None and now - opened > self.thumb_timeout + 1.5:
                    lib.close(handle)
                    self._closed()
                    handle = None
                    if self._device_still(rx.source, rx.address, rx.width) is not None:
                        self._live_stills(rx)  # das Gerät liefert Standbilder: damit weiter
                        return
                    rx.state = STATE_NO_SIGNAL
                    self._loop.call_soon_threadsafe(self._live_ended, rx)
                    return
        finally:
            if handle is not None:
                lib.close(handle)
                self._closed()
                _LOGGER.info("Live-Vorschau geschlossen: %s (%d Bilder)", rx.source, rx.frames)
                self._loop.call_soon_threadsafe(self._live_ended, rx)

    @staticmethod
    def _publish(rx: LiveReceiver, jpeg: bytes | None) -> None:
        for queue in list(rx.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()  # langsamer Zuschauer: altes Bild verwerfen statt stauen
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(jpeg)

    def _live_ended(self, rx: LiveReceiver) -> None:
        if self._live.get(rx.source) is rx:
            del self._live[rx.source]
        self._publish(rx, None)  # Zuschauern das Ende melden

    def subscribe(self, source_id: str, width: int | None = None, fps: float | None = None) -> tuple[LiveReceiver, asyncio.Queue[bytes | None]]:
        """Live-Vorschau abonnieren. Wirft ``LookupError(Zustand)``, wenn die Quelle kein Bild liefern kann."""
        state, address = self.source_state(source_id)
        if state != STATE_OK:
            raise LookupError(state)
        if self.max_live <= 0:
            raise LookupError(STATE_UNAVAILABLE)
        self._loop = asyncio.get_running_loop()
        rx = self._live.get(source_id)
        if rx is None or rx.stop.is_set():
            while len(self._live) >= self.max_live:  # nur die eine angeklickte Quelle: die älteste weicht
                oldest = min(self._live.values(), key=lambda r: r.started)
                oldest.stop.set()
                del self._live[oldest.source]
            rx = LiveReceiver(
                source_id,
                address,
                max(160, min(int(width or self.live_width), 1280)),
                max(1.0, min(float(fps or self.live_fps), 25.0)),
            )
            self._live[source_id] = rx
            rx.thread = threading.Thread(target=self._live_thread, args=(rx,), name="avm-ndi-live", daemon=True)
            rx.thread.start()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=2)
        rx.subscribers.add(queue)
        if rx.last_jpeg is not None:
            queue.put_nowait(rx.last_jpeg)
        return rx, queue

    @staticmethod
    def unsubscribe(rx: LiveReceiver, queue: asyncio.Queue[bytes | None]) -> None:
        rx.subscribers.discard(queue)

    # -------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        available = self.available
        return {
            "available": available,
            "reason": None if available else self._lib_error,
            "ndi_version": self._lib.version if self._lib else None,
            "hx_decoder": self.hx_decoder,
            "bandwidth": "lowest",
            "hx_sources": sorted(self._heavy),
            "receivers_open": self.open_now,
            "receivers_opened_total": self.opened_total,
            "receivers_closed_total": self.closed_total,
            "live": [
                {
                    "source": rx.source,
                    "clients": len(rx.subscribers),
                    "seconds": round(time.monotonic() - rx.started, 1),
                    "frames": rx.frames,
                    "state": rx.state,
                    "mode": "stills" if rx.source in self._heavy and self.hx_live != "stream" else "stream",
                }
                for rx in self._live.values()
            ],
            "limits": {
                "max_parallel_stills": self.max_parallel,
                "max_live": self.max_live,
                "still_cache_seconds": self.thumb_ttl,
                "live_fps": self.live_fps,
                "live_linger_seconds": self.live_linger,
                "live_max_seconds": self.live_max_seconds,
            },
        }

    async def close(self) -> None:
        for rx in list(self._live.values()):
            rx.stop.set()
        for rx in list(self._live.values()):
            if rx.thread is not None:
                await asyncio.to_thread(rx.thread.join, 3.0)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
