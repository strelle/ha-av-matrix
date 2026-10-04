"""Magewell Pro Convert (NDI® decoder) - HTTP API ``/mwapi``.

Verified with Pro Convert "NDI to AIO", firmware 1.3.24. See docs/devices.md.

* Login ``GET /mwapi?method=login&id=<user>&pass=<md5hex(password)>`` sets a ``sid`` cookie.
* Every answer is ``{"status": n, ...}``: 0 ok, 36 wrong password, 37 not logged in.
* The source list (``get-ndi-sources``) is built live by the device, so it is trusted.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

from ..models import (
    ConfigField,
    DestinationState,
    DestinationStatus,
    DeviceInfo,
    DevicePoll,
    FieldType,
    SourceSighting,
)
from .base import HOST, NAME, CannotConnect, Driver, InvalidAuth, RouteFailed, format_resolution, short

_LOGGER = logging.getLogger(__name__)

STATUS_OK = 0
STATUS_BAD_PASSWORD = 36
STATUS_NOT_LOGGED_IN = 37


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


class MagewellProConvert(Driver):
    """Magewell Pro Convert NDI® decoders (NDI to HDMI / SDI / AIO)."""

    KEY = "magewell"
    PROTOCOL = "ndi"
    TITLE = "Magewell Pro Convert (NDI® → HDMI/SDI)"
    MANUFACTURER = "Magewell"
    DEFAULT_PORT = 80
    CONFIG_FIELDS = (
        HOST,
        ConfigField("port", FieldType.PORT, required=False, default=80, minimum=1, maximum=65535),
        ConfigField("username", default="Admin"),
        ConfigField("password", FieldType.PASSWORD, secret=True),
        NAME,
    )
    TRUSTED_SOURCE_LIST = True
    SETTLE_TIME = 3.0

    def __init__(self, session: aiohttp.ClientSession, config: dict[str, Any], timeout: float = 3.0) -> None:
        super().__init__(session, config, timeout)
        self._sid: str | None = None
        self._login_lock = asyncio.Lock()

    @property
    def _base(self) -> str:
        port = f":{self.port}" if self.port and self.port != 80 else ""
        return f"http://{self.host}{port}/mwapi"

    @property
    def configuration_url(self) -> str | None:
        return self._base.removesuffix("/mwapi")

    # ----------------------------------------------------------------- transport
    async def _get(self, method: str, **params: str) -> dict[str, Any]:
        query = "&".join(
            [f"method={quote(method)}"] + [f"{quote(k)}={quote(str(v), safe='')}" for k, v in params.items()]
        )
        headers = {"Cookie": f"sid={self._sid}"} if self._sid else {}
        try:
            async with self._session.get(f"{self._base}?{query}", headers=headers, timeout=self.timeout) as resp:
                for cookie in resp.headers.getall("Set-Cookie", []):
                    if cookie.startswith("sid="):
                        self._sid = cookie[4:].split(";", 1)[0] or self._sid
                if resp.status in (401, 403):
                    raise InvalidAuth(f"HTTP {resp.status}")
                if resp.status != 200:
                    raise CannotConnect(f"HTTP {resp.status}")
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            # never let the query (login: user name + password hash) end up in an error text / the log
            raise CannotConnect(short(str(err).replace(query, "…")) if str(err) else "timeout") from None
        try:
            data = json.loads(text)
        except ValueError as err:
            raise CannotConnect("not a Magewell /mwapi answer") from err
        if not isinstance(data, dict) or "status" not in data:
            raise CannotConnect("not a Magewell /mwapi answer")
        return data

    async def _login(self) -> None:
        user = str(self.config.get("username") or "Admin")
        digest = hashlib.md5(str(self.config.get("password") or "").encode()).hexdigest()
        self._sid = None
        data = await self._get("login", id=user, **{"pass": digest})
        status = data.get("status")
        if status == STATUS_BAD_PASSWORD:
            raise InvalidAuth("wrong user name or password")
        if status != STATUS_OK:
            raise CannotConnect(f"login failed (status {status})")

    async def _call(self, method: str, **params: str) -> dict[str, Any]:
        """Call a method, logging in (once) if the device says we are not logged in."""
        if self._sid is None:
            async with self._login_lock:
                if self._sid is None:
                    await self._login()
        data = await self._get(method, **params)
        if data.get("status") == STATUS_NOT_LOGGED_IN:
            async with self._login_lock:
                await self._login()
            data = await self._get(method, **params)
        status = data.get("status")
        if status == STATUS_BAD_PASSWORD:
            raise InvalidAuth("wrong user name or password")
        if status == STATUS_NOT_LOGGED_IN:
            raise InvalidAuth("device refuses the session")
        return data

    # ----------------------------------------------------------------- interface
    async def async_get_info(self) -> DeviceInfo:
        data = await self._call("get-summary-info")
        if data.get("status") != STATUS_OK:
            raise CannotConnect(f"get-summary-info status {data.get('status')}")
        dev = data.get("device") or {}
        eth = data.get("ethernet") or {}
        model = _first(dev, "model", "product-name")
        return DeviceInfo(
            name=_first(dev, "name"),
            manufacturer=self.MANUFACTURER,
            model=f"Pro Convert {model}" if model and "pro convert" not in str(model).lower() else model,
            firmware=_first(dev, "fw-version", "firmware-version", "firmware", "version"),
            serial=_first(dev, "serial-no", "serial-number", "sn"),
            mac=_first(eth, "mac-addr", "mac"),
        )

    async def async_get_sources(self) -> list[SourceSighting]:
        data = await self._call("get-ndi-sources")
        out: list[SourceSighting] = []
        for item in data.get("sources") or []:
            if isinstance(item, dict) and item.get("ndi-name"):
                out.append(SourceSighting(str(item["ndi-name"]), item.get("ip-addr") or None))
        return out

    async def async_get_current(self, destination: str) -> str | None:
        data = await self._call("get-channel")
        name = data.get("name")
        if not name:
            return None
        # ndi-name false = a channel preset stored on the device, shown as such
        return str(name) if data.get("ndi-name", True) else f"[preset] {name}"

    async def async_route(self, destination: str, source: str | None, address: str | None = None) -> None:
        if source and source.startswith("[preset] "):
            data = await self._call("set-channel", **{"ndi-name": "false", "name": source[9:]})
        else:
            data = await self._call("set-channel", **{"ndi-name": "true", "name": source or ""})
        if data.get("status") != STATUS_OK:
            raise RouteFailed(f"device answered status {data.get('status')}")

    @staticmethod
    def _status_from_summary(data: dict[str, Any], current: str | None = None) -> DestinationStatus:
        """Connection (+ resolution if the firmware has an ``ndi`` block) from ``get-summary-info``.

        FW 1.3.24 (verified live): ``ndi`` = ``{"name", "connected", "video-width", "video-height",
        "video-scan", "video-field-rate", "video-bit-rate", "video-drop-frames", …}``. The block may be
        missing (seen right after boot / switching); then ``device.output-state`` tells the connection.
        """
        ndi = data.get("ndi")
        ndi = ndi if isinstance(ndi, dict) else {}
        connected = ndi.get("connected")
        if connected is None:
            state = str((data.get("device") or {}).get("output-state") or "").strip().lower()
            connected = None if not state else state == "connected"
        else:
            connected = bool(connected)
        name = ndi.get("name")
        if connected and current and name and str(name).casefold() != current.casefold():
            # the device still decodes the previous source (switching takes ~2-5 s): its video
            # values belong to the old stream, so report "connecting" without a resolution
            return DestinationStatus(connected=False)
        res = None
        if connected is not False:
            scan = str(_first(ndi, "video-scan", "scan") or "").lower()
            res = format_resolution(
                _first(ndi, "video-width", "width"),
                _first(ndi, "video-height", "height"),
                _first(ndi, "video-field-rate", "video-frame-rate", "frame-rate"),
                scan.startswith("interl") or _first(ndi, "video-interlaced", "interlaced") in (True, 1, "1", "true"),
            )
        extra: dict[str, Any] = {}
        for key, src in (
            ("bitrate_kbps", "video-bit-rate"),
            ("dropped_frames", "video-drop-frames"),
            ("dropped_frames", "drop-frames"),
        ):
            if key not in extra and ndi.get(src) is not None:
                extra[key] = ndi[src]
        return DestinationStatus(connected=connected, resolution=res, extra=extra)

    @staticmethod
    def _video_from_signal_info(data: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        """``get-signal-info`` → ``{"signal-info-types": ["video-info"], "video-info": {"width", …}}``.

        Right after switching the device answers ``status 0`` with an empty ``signal-info-types``
        (no video yet) → no resolution (not an error, the next polls pick it up).
        """
        types = data.get("signal-info-types")
        if isinstance(types, list) and "video-info" not in types:
            return None, {}
        video = data.get("video-info") or data.get("video") or {}
        if not isinstance(video, dict):
            return None, {}
        scan = str(video.get("scan") or "").lower()
        res = format_resolution(
            video.get("width"), video.get("height"), video.get("field-rate"), scan.startswith("interl")
        )
        if res is None:
            return None, {}
        extra = {
            key.replace("-", "_"): video[key]
            for key in ("codec", "color-format", "sampling", "color-depth", "aspect-ratio", "quant-range")
            if video.get(key) not in (None, "")
        }
        return res, extra

    async def async_get_status(self, destination: str, current: str | None = None) -> DestinationStatus:
        """Live status. ``current`` (NDI name from ``get-channel``) detects a switch still in progress."""
        status = self._status_from_summary(await self._call("get-summary-info"), current)
        if status.connected is False:
            return status  # no stream (or still switching) → no resolution, polls continue
        try:
            sig = await self._call("get-signal-info")
        except CannotConnect:
            return status
        if sig.get("status") == STATUS_OK:
            res, extra = self._video_from_signal_info(sig)
            # get-signal-info describes the stream actually decoded → it wins over the summary
            status.resolution = res or status.resolution
            status.extra.update(extra)
        return status

    async def async_poll(self) -> DevicePoll:
        sources = await self.async_get_sources()
        current = await self.async_get_current("main")
        # a channel preset is not an NDI name → cannot be compared with the summary's ndi.name
        status = await self.async_get_status("main", None if current and current.startswith("[preset] ") else current)
        return DevicePoll(sources=sources, destinations={"main": DestinationState(current, status)})
