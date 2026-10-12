"""NDI® preview pictures, relayed from a Strelle AV Matrix server (the stand-alone variant in ``server/``).

Home Assistant does not receive NDI itself. If the address of such a server is configured (optional, one address
for the whole integration), three authenticated views pass its preview API through - specified in
``server/docs/SCHNITTSTELLE.md``:

* ``/api/av_matrix/preview.jpg``   - current still of a source
* ``/api/av_matrix/preview.mjpeg`` - live preview (MJPEG) of the one source somebody is watching
* ``/api/av_matrix/preview``       - status (state of a source, running live receivers)

Why Home Assistant relays the pictures instead of the card loading them from the server: dashboards are also
opened through https (remote access, a reverse proxy). Browsers block pictures from a plain-http address there
(mixed content), and the server is often not reachable from the browser's network at all. The views need a
Home Assistant login like every other API call: the card fetches stills with its access token and opens the
stream through a signed path (``auth/sign_path``). Nothing is stored; a picture is never replaced by an old one.

The server also knows what kind of device an NDI source is (camera, encoder, computer, test pattern) and whether
it has a web interface; that is merged into the snapshot (``device_type``, ``icon_key``, ``web_url``).

Routing never depends on any of this: with the server unreachable the matrix works as before.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.hass_dict import HassKey

from .const import PREVIEW_STATUS_URL, PREVIEW_STILL_URL, PREVIEW_STREAM_URL
from .source_types import TYPES as SOURCE_TYPES

_LOGGER = logging.getLogger(__name__)

#: hass.data: address of a server seen on the network (mDNS), offered in the options while none is configured
DATA_PREVIEW_SUGGESTION: HassKey[str] = HassKey("av_matrix_preview_suggestion")
DEFAULT_PORT = 8088
REFRESH_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=6)
#: a still may have to wait for a key frame of an NDI|HX source and for a free receiver on the server
STILL_TIMEOUT = aiohttp.ClientTimeout(total=15)
#: live: no total limit (the server ends a stream after 10 minutes), but it repeats a resting picture every second
STREAM_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=6, sock_read=20)
#: stills fetched from the server at the same time, for all dashboards together (the server allows two)
PARALLEL_STILLS = 2
MAX_STILL_BYTES = 4 * 1024 * 1024

HEADER_STATE = "X-Preview-State"
PASS_HEADERS = (HEADER_STATE, "X-Preview-Origin", "X-Preview-Age", "X-Preview-Size")
NO_STORE = {"Cache-Control": "no-store"}

STATE_OK = "ok"
#: states of our own, next to the server's (offline, unknown_source, no_signal, unavailable, unsupported_codec)
STATE_NOT_CONFIGURED = "not_configured"
STATE_UNREACHABLE = "unreachable"
STATE_BAD_RESPONSE = "bad_response"
STATE_INVALID = "invalid"
#: what the server answers without a picture: HTTP status → state, if it sends neither header nor JSON
SERVER_STATES = {404: "unknown_source", 415: "unsupported_codec", 501: "unavailable", 503: "no_signal"}
_STATE_RE = re.compile(r"^[a-z_]{1,32}$")
_ICON_RE = re.compile(r"^[a-z0-9_]{1,48}$")


class InvalidPreviewUrl(ValueError):
    """The text is not an http(s) address."""


class PreviewServerError(Exception):
    """The address does not answer (``cannot_connect``) or is not a Strelle AV Matrix server (``not_matrix``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_url(text: Any) -> str | None:
    """``"192.0.2.8"`` → ``"http://192.0.2.8:8088"``; empty → None; anything that is not http(s) raises."""
    value = str(text or "").strip()
    if not value:
        return None
    explicit = "://" in value
    parts = urlsplit(value if explicit else f"http://{value}")
    try:
        port = parts.port
    except ValueError as err:
        raise InvalidPreviewUrl(value) from err
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.query or parts.fragment:
        raise InvalidPreviewUrl(value)
    if any(c.isspace() for c in value):
        raise InvalidPreviewUrl(value)
    netloc = parts.netloc
    if port is None and not explicit:  # just a host: the server's default port
        netloc = f"{netloc}:{DEFAULT_PORT}"
    return f"{parts.scheme}://{netloc}{parts.path.rstrip('/')}"


async def async_probe(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    """Ask ``/api/info`` (read-only). Returns name and version of the server, raises PreviewServerError."""
    try:
        async with session.get(f"{url}/api/info", timeout=REQUEST_TIMEOUT, allow_redirects=False) as resp:
            if resp.status != 200:
                raise PreviewServerError("not_matrix")
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise PreviewServerError("cannot_connect") from err
    except ValueError as err:
        raise PreviewServerError("not_matrix") from err
    if not isinstance(data, dict) or "version" not in data or "name" not in data:
        raise PreviewServerError("not_matrix")
    return {"name": str(data["name"]), "version": str(data["version"])}


@dataclass(slots=True)
class Relayed:
    """What a view answers: a picture, or the server's (or our own) reason why there is none."""

    status: int
    body: bytes
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)

    def response(self) -> web.Response:
        return web.Response(
            status=self.status, body=self.body, content_type=self.content_type, headers={**self.headers, **NO_STORE}
        )


def _failure(status: int, state: str, message: str) -> Relayed:
    body = json.dumps({"ok": False, "error": state, "message": message}).encode()
    return Relayed(status, body, "application/json", {HEADER_STATE: state})


NOT_CONFIGURED = _failure(404, STATE_NOT_CONFIGURED, "No preview server configured")
UNREACHABLE = _failure(502, STATE_UNREACHABLE, "Preview server not reachable")
BAD_RESPONSE = _failure(502, STATE_BAD_RESPONSE, "Unexpected answer from the preview server")


class PreviewServer:
    """The optional Strelle AV Matrix server behind the preview: address, health, what it knows about sources."""

    #: protocols the server delivers pictures for
    protocols: tuple[str, ...] = ("ndi",)

    def __init__(self, hass: HomeAssistant, on_change: Callable[[], None]) -> None:
        self.hass = hass
        self._on_change = on_change
        self.url: str | None = None
        self.reachable: bool | None = None  # None = not asked yet
        self.available: bool | None = None  # the server can receive NDI (SDK installed, preview enabled)
        self.reason: str | None = None
        self.hx_decoder: bool | None = None
        self.name: str | None = None
        self.version: str | None = None
        #: NDI source id → {"device_type", "icon_key", "web_url"} as the server reports them
        self.sources: dict[str, dict[str, Any]] = {}
        #: former name of a source → today's name (devices that carry their IP address as name)
        self.aliases: dict[str, str] = {}
        self._unsub: CALLBACK_TYPE | None = None
        self._refresh_lock = asyncio.Lock()
        self._stills = asyncio.Semaphore(PARALLEL_STILLS)
        self._inflight: dict[tuple[str, int], asyncio.Task[Relayed]] = {}

    @property
    def configured(self) -> bool:
        return self.url is not None

    def covers(self, protocol: str) -> bool:
        """Pictures exist for sources of ``protocol``."""
        return self.configured and protocol in self.protocols

    # ---------------------------------------------------------------- lifecycle
    @callback
    def async_start(self) -> None:
        """Ask the server now and every 30 s (only if an address is configured)."""
        if self.url is None or self._unsub is not None:
            return
        self._unsub = async_track_time_interval(
            self.hass, self._async_periodic, REFRESH_INTERVAL, cancel_on_shutdown=True
        )
        self.hass.async_create_background_task(self.async_refresh(), "av_matrix preview server")

    @callback
    def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def async_set_url(self, url: str | None) -> None:
        """Change (or remove) the address. Everything learned from the old server is dropped."""
        if url == self.url:
            return
        self.async_stop()
        self.url = url
        self.reachable = self.available = self.hx_decoder = None
        self.reason = self.name = self.version = None
        self.sources = {}
        self.aliases = {}
        self.async_start()
        self._on_change()

    async def _async_periodic(self, _now: datetime) -> None:
        await self.async_refresh()

    # ------------------------------------------------------------------- state
    def meta(self, source_id: str) -> dict[str, Any] | None:
        """What the server knows about a source (also under a former name)."""
        return self.sources.get(source_id) or self.sources.get(self.aliases.get(source_id, ""))

    def snapshot(self) -> dict[str, Any]:
        """The ``preview`` object of the frontend snapshot (docs/frontend-api.md)."""
        return {
            "configured": self.configured,
            "reachable": self.reachable if self.configured else None,
            "available": self.available if self.configured else None,
            "reason": self.reason if self.configured else None,
            "hx_decoder": self.hx_decoder if self.configured else None,
            "server": {"name": self.name, "version": self.version} if self.configured and self.version else None,
            "protocols": list(self.protocols) if self.configured else [],
            "still_url": PREVIEW_STILL_URL,
            "stream_url": PREVIEW_STREAM_URL,
            "status_url": PREVIEW_STATUS_URL,
        }

    def _fingerprint(self) -> tuple[Any, ...]:
        return (
            self.reachable,
            self.available,
            self.reason,
            self.hx_decoder,
            self.name,
            self.version,
            self.sources,
            self.aliases,
        )

    @callback
    def async_note(self, reachable: bool) -> None:
        """A relayed request told us whether the server answers - faster than the next poll."""
        if self.url is None or self.reachable is reachable:
            return
        self._log_reachable(reachable)
        self.reachable = reachable
        self._on_change()
        if reachable:  # back again: learn the rest (device types, NDI available) right away
            self.hass.async_create_background_task(self.async_refresh(), "av_matrix preview server")

    def _log_reachable(self, reachable: bool) -> None:
        if reachable and self.reachable is False:
            _LOGGER.info("Preview server %s is reachable again", self.url)
        elif not reachable and self.reachable is not False:
            _LOGGER.warning(
                "Preview server %s is not reachable - no preview pictures, routing is not affected", self.url
            )

    async def _async_json(self, url: str, path: str) -> Any:
        session = async_get_clientsession(self.hass)
        async with session.get(f"{url}{path}", timeout=REQUEST_TIMEOUT, allow_redirects=False) as resp:
            if resp.status != 200:
                raise ValueError(f"{path}: HTTP {resp.status}")
            return await resp.json(content_type=None)

    async def async_refresh(self) -> None:
        """Read device types, aliases and the preview status from the server."""
        async with self._refresh_lock:
            url = self.url
            if url is None:
                return
            before = self._fingerprint()
            try:
                state = await self._async_json(url, "/api/state")
                status = await self._async_json(url, "/api/preview")
                info = await self._async_json(url, "/api/info")
                try:
                    choices = await self._async_json(url, "/api/choices")
                except (aiohttp.ClientError, TimeoutError, ValueError):
                    choices = {}
                if not isinstance(state, dict) or not isinstance(status, dict) or not isinstance(info, dict):
                    raise ValueError("not a Strelle AV Matrix server")  # noqa: TRY004 - handled like any bad answer
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                if self.url != url:
                    return
                _LOGGER.debug("Preview server %s: %s", url, err or type(err).__name__)
                self._log_reachable(False)
                self.reachable = False  # device types stay as they were, so the icons do not jump
            else:
                if self.url != url:  # address changed while we were asking
                    return
                self._log_reachable(True)
                self.reachable = True
                self.available = bool(status.get("available"))
                self.reason = str(status["reason"]) if status.get("reason") else None
                self.hx_decoder = status.get("hx_decoder") if isinstance(status.get("hx_decoder"), bool) else None
                self.name = str(info["name"]) if info.get("name") else None
                self.version = str(info["version"]) if info.get("version") else None
                self.sources = _parse_sources(state)
                aliases = choices.get("aliases") if isinstance(choices, dict) else None
                self.aliases = (
                    {str(old): str(new) for old, new in aliases.items() if old and new}
                    if isinstance(aliases, dict)
                    else {}
                )
            if self._fingerprint() != before:
                self._on_change()

    # ------------------------------------------------------------------ relays
    async def async_still(self, source: str, width: int) -> Relayed:
        """Still of ``source``. Identical requests of several dashboards share one request to the server."""
        if self.url is None:
            return NOT_CONFIGURED
        key = (source, width)
        task = self._inflight.get(key)
        if task is None:
            task = self.hass.async_create_background_task(
                self._async_fetch_still(self.url, source, width), "av_matrix preview"
            )
            self._inflight[key] = task
            task.add_done_callback(lambda _task: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    async def _async_fetch_still(self, url: str, source: str, width: int) -> Relayed:
        session = async_get_clientsession(self.hass)
        try:
            async with (
                self._stills,
                session.get(
                    f"{url}/api/preview.jpg",
                    params={"source": source, "w": str(width)},
                    timeout=STILL_TIMEOUT,
                    allow_redirects=False,
                ) as resp,
            ):
                body = await _read(resp, MAX_STILL_BYTES)
                relayed = _relay(resp, body)
        except (aiohttp.ClientError, TimeoutError):
            self.async_note(False)
            return UNREACHABLE
        self.async_note(relayed is not BAD_RESPONSE)
        return relayed

    async def async_status(self, source: str | None) -> Relayed:
        """``/api/preview`` of the server (no receiver is opened for it)."""
        if self.url is None:
            return NOT_CONFIGURED
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{self.url}/api/preview",
                params={"source": source} if source else None,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            ) as resp:
                body = await _read(resp, MAX_STILL_BYTES)
                if resp.status != 200 or "json" not in resp.content_type or len(body) > MAX_STILL_BYTES:
                    return BAD_RESPONSE
        except (aiohttp.ClientError, TimeoutError):
            self.async_note(False)
            return UNREACHABLE
        self.async_note(True)
        return Relayed(200, body, "application/json")

    async def async_stream(
        self, request: web.Request, source: str, width: int, fps: float | None
    ) -> web.StreamResponse:
        """Pass the server's MJPEG stream through until the viewer leaves or the server ends it."""
        if self.url is None:
            return NOT_CONFIGURED.response()
        params = {"source": source, "w": str(width)}
        if fps is not None:
            params["fps"] = f"{fps:g}"
        session = async_get_clientsession(self.hass)
        try:
            upstream = await session.get(
                f"{self.url}/api/preview.mjpeg", params=params, timeout=STREAM_TIMEOUT, allow_redirects=False
            )
        except (aiohttp.ClientError, TimeoutError):
            self.async_note(False)
            return UNREACHABLE.response()
        try:
            self.async_note(True)
            if upstream.status != 200 or not upstream.content_type.startswith("multipart/"):
                body = await _read(upstream, 65536)
                relayed = BAD_RESPONSE if upstream.status == 200 or len(body) > 65536 else _relay(upstream, body)
                return relayed.response()
            response = web.StreamResponse(
                headers={
                    "Content-Type": upstream.headers.get("Content-Type", "multipart/x-mixed-replace"),
                    "X-Accel-Buffering": "no",
                    HEADER_STATE: STATE_OK,
                    **NO_STORE,
                }
            )
            await response.prepare(request)
            # the viewer left (connection reset) or the server ended the stream: both simply end the relay
            with contextlib.suppress(ConnectionResetError, aiohttp.ClientError, TimeoutError):
                async for chunk in upstream.content.iter_any():
                    await response.write(chunk)
            return response
        finally:
            upstream.close()  # drop the connection: the server closes its NDI receiver a few seconds later


async def _read(resp: aiohttp.ClientResponse, limit: int) -> bytes:
    """The whole body, but never more than ``limit`` + 1 bytes (a longer one is refused by the caller)."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in resp.content.iter_any():
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            break
    return b"".join(chunks)


def _parse_sources(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``device_type`` / ``icon_key`` / ``web_url`` of the NDI sources in a server snapshot (only checked values)."""
    out: dict[str, dict[str, Any]] = {}
    protocols = state.get("protocols")
    ndi = protocols.get("ndi") if isinstance(protocols, dict) else None
    for src in (ndi.get("sources") if isinstance(ndi, dict) else None) or []:
        if not isinstance(src, dict) or not isinstance(src.get("id"), str):
            continue
        kind = src.get("device_type")
        if kind not in SOURCE_TYPES:
            continue
        icon = src.get("icon_key")
        web_url = src.get("web_url")
        out[src["id"]] = {
            "device_type": kind,
            "icon_key": icon if isinstance(icon, str) and _ICON_RE.match(icon) else SOURCE_TYPES[kind][1],
            "web_url": web_url
            if isinstance(web_url, str) and re.match(r"^https?://", web_url, re.IGNORECASE)
            else None,
        }
    return out


def _relay(resp: aiohttp.ClientResponse, body: bytes) -> Relayed:
    """Turn the server's answer into ours: the picture, or its documented error with ``X-Preview-State``."""
    if len(body) > MAX_STILL_BYTES:
        return BAD_RESPONSE
    headers = {name: resp.headers[name] for name in PASS_HEADERS if name in resp.headers}
    if resp.status == 200:
        if not resp.content_type.startswith("image/"):
            return BAD_RESPONSE
        headers.setdefault(HEADER_STATE, STATE_OK)
        return Relayed(200, body, resp.content_type, headers)
    state = headers.get(HEADER_STATE)
    if not state and "json" in resp.content_type:
        with contextlib.suppress(ValueError):
            data = json.loads(body)
            state = data.get("error") if isinstance(data, dict) else None
    if not isinstance(state, str) or not _STATE_RE.match(state):
        state = SERVER_STATES.get(resp.status)
    if state is None or resp.status not in (400, 404, 415, 501, 503):
        return BAD_RESPONSE
    headers[HEADER_STATE] = state
    if "json" in resp.content_type:
        return Relayed(resp.status, body, "application/json", headers)
    return Relayed(resp.status, _failure(resp.status, state, "").body, "application/json", headers)


# ----------------------------------------------------------------------------- views
def _source(request: web.Request) -> str | None:
    source = request.query.get("source", "").strip()
    return source if source and len(source) <= 512 else None


def _number(request: web.Request, name: str, low: float, high: float, default: float | None) -> float | None:
    try:
        value = float(request.query[name])
    except (KeyError, ValueError):
        return default
    if math.isnan(value):
        return default
    return min(max(value, low), high)


INVALID = _failure(400, STATE_INVALID, "source is required")


class PreviewStatusView(HomeAssistantView):
    """``GET /api/av_matrix/preview[?source=…]`` - the server's preview status (opens no receiver)."""

    url = PREVIEW_STATUS_URL
    name = "api:av_matrix:preview"

    def __init__(self, server: PreviewServer) -> None:
        self._server = server

    async def get(self, request: web.Request) -> web.Response:
        return (await self._server.async_status(_source(request))).response()


class PreviewStillView(HomeAssistantView):
    """``GET /api/av_matrix/preview.jpg?source=<NDI name>[&w=64…640]`` - current still as JPEG."""

    url = PREVIEW_STILL_URL
    name = "api:av_matrix:preview:still"

    def __init__(self, server: PreviewServer) -> None:
        self._server = server

    async def get(self, request: web.Request) -> web.Response:
        source = _source(request)
        if source is None:
            return INVALID.response()
        width = int(_number(request, "w", 64, 640, 320) or 320)
        return (await self._server.async_still(source, width)).response()


class PreviewStreamView(HomeAssistantView):
    """``GET /api/av_matrix/preview.mjpeg?source=<NDI name>[&w=160…1280][&fps=1…25]`` - live preview (MJPEG)."""

    url = PREVIEW_STREAM_URL
    name = "api:av_matrix:preview:stream"

    def __init__(self, server: PreviewServer) -> None:
        self._server = server

    async def get(self, request: web.Request) -> web.StreamResponse:
        source = _source(request)
        if source is None:
            return INVALID.response()
        width = int(_number(request, "w", 160, 1280, 640) or 640)
        return await self._server.async_stream(request, source, width, _number(request, "fps", 1, 25, None))


@callback
def async_register_views(hass: HomeAssistant, server: PreviewServer) -> None:
    """Register the three relays (they answer 404 ``not_configured`` while no server is set)."""
    hass.http.register_view(PreviewStatusView(server))
    hass.http.register_view(PreviewStillView(server))
    hass.http.register_view(PreviewStreamView(server))
