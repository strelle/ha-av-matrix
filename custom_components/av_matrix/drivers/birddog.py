"""BirdDog NDI® decoders (PLAY, Mini, Flex, Studio NDI …) - REST API on port 8080.

Verified (earlier project) with BirdDog PLAY, firmware 1.0.14. See docs/devices.md.

* ``GET /about``, ``GET /List`` (name → "ip:port"), ``POST /refresh``,
  ``GET|POST /connectTo`` ``{"sourceName": …}``, ``GET /decodestatus``.
* The API normally needs no login; the password protects the web UI on port 80.
  If the API answers 401/403 we log in via ``POST /login`` (form ``auth_password``,
  cookie ``BirdDogSession``) and retry once.
* ``/List`` keeps stale entries → NOT trusted (the registry verifies them by TCP).
* Names with non-ASCII characters are listed as ``NDI_<id>`` and must be routed
  with exactly that name (the registry maps it to the real name by address).
* Some firmwares do not switch reliably → verify after routing, retry once.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from ..models import (
    ConfigField,
    DestinationInfo,
    DestinationStatus,
    DeviceInfo,
    FieldType,
    ProbeResult,
    SourceSighting,
)
from .base import (
    HOST,
    NAME,
    PROBE_TIMEOUT,
    CannotConnect,
    Driver,
    InvalidAuth,
    RouteFailed,
    format_resolution,
    short,
)

_LOGGER = logging.getLogger(__name__)

NONE_NAMES = {"", "none", "None"}


class EndpointNotFound(CannotConnect):
    """HTTP 404 - the firmware does not have this endpoint (a DriverError, so callers handle it)."""


def _ci(data: dict[str, Any], *keys: str) -> Any:
    """Case-insensitive lookup of the first present key."""
    lower = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return None


class BirdDogDecoder(Driver):
    """BirdDog NDI® decoders."""

    KEY = "birddog"
    PROTOCOL = "ndi"
    TITLE = "BirdDog (PLAY, Mini, Flex, Studio NDI …)"
    MANUFACTURER = "BirdDog"
    DEFAULT_PORT = 8080
    CONFIG_FIELDS = (
        HOST,
        ConfigField("port", FieldType.PORT, required=False, default=8080, minimum=1, maximum=65535),
        ConfigField("password", FieldType.PASSWORD, required=False, secret=True),
        ConfigField("channels", FieldType.INTEGER, required=False, default=1, minimum=1, maximum=4),
        NAME,
    )
    TRUSTED_SOURCE_LIST = False
    SETTLE_TIME = 2.0
    VERIFY_DELAY = 0.7
    PROBE_PORTS = (8080,)

    @classmethod
    async def async_probe(
        cls, session: aiohttp.ClientSession, host: str, timeout: float = PROBE_TIMEOUT
    ) -> ProbeResult | None:
        """``GET :8080/about`` (no login) → JSON with ``HostName`` / ``FirmwareVersion`` / ``SerialNumber``."""
        try:
            async with session.get(
                f"http://{host}:8080/about",
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status in (401, 403):
                    return None  # API locked: cannot tell a BirdDog from anything else without a password
                if resp.status != 200:
                    return None
                data = json.loads(await resp.text())
        except (aiohttp.ClientError, TimeoutError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict) or _ci(data, "HostName", "FirmwareVersion", "SerialNumber") is None:
            return None
        hostname = _ci(data, "HostName", "hostname")
        return ProbeResult(
            cls.KEY,
            host,
            8080,
            name=str(hostname).removesuffix(".local") if hostname else None,
            model=_ci(data, "Model", "ProductName", "DeviceModel"),
            serial=_ci(data, "SerialNumber", "Serial"),
            mac=_ci(data, "MacAddress", "MAC"),
        )

    def __init__(self, session: aiohttp.ClientSession, config: dict[str, Any], timeout: float = 3.0) -> None:
        super().__init__(session, config, timeout)
        self._cookie: str | None = None
        self._decodestatus_supported = True
        self.channels = max(1, min(4, int(config.get("channels") or 1)))

    @property
    def _base(self) -> str:
        return f"http://{self.host}:{self.port or 8080}"

    # ----------------------------------------------------------------- transport
    async def _login(self) -> None:
        password = self.config.get("password")
        if not password:
            raise InvalidAuth("device requires a password")
        for url in (f"http://{self.host}/login", f"{self._base}/login"):
            try:
                async with self._session.post(
                    url, data={"auth_password": password}, timeout=self.timeout, allow_redirects=False
                ) as resp:
                    for cookie in resp.headers.getall("Set-Cookie", []):
                        if cookie.startswith("BirdDogSession=") and "Max-Age=0" not in cookie:
                            self._cookie = cookie.split("=", 1)[1].split(";", 1)[0]
                    if resp.status in (401, 403):
                        continue
                    if self._cookie:
                        return
            except (aiohttp.ClientError, TimeoutError):
                continue
        raise InvalidAuth("login rejected")

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        *,
        _retry: bool = True,
    ) -> Any:
        headers = {"Accept": "application/json, text/plain, */*"}
        if self._cookie:
            headers["Cookie"] = f"BirdDogSession={self._cookie}"
        try:
            async with self._session.request(
                method, self._base + path, json=body, params=params, headers=headers, timeout=self.timeout
            ) as resp:
                if resp.status in (401, 403):
                    if _retry:
                        await self._login()
                        return await self._request(method, path, body, params, _retry=False)
                    raise InvalidAuth(f"HTTP {resp.status}")
                if resp.status == 404:
                    raise EndpointNotFound(f"{path}: HTTP 404")
                if resp.status >= 400:
                    raise CannotConnect(f"{path}: HTTP {resp.status}")
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(short(err) if str(err) else "timeout") from err
        try:
            return json.loads(text)
        except ValueError:
            return text.strip()

    def _ch(self, destination: str) -> dict[str, Any]:
        """Channel selector for multi-channel devices (untested, see docs/devices.md)."""
        return {"ChNum": int(destination)} if self.channels > 1 else {}

    # ----------------------------------------------------------------- interface
    def destinations(self) -> list[DestinationInfo]:
        if self.channels == 1:
            return [DestinationInfo("1")]
        return [DestinationInfo(str(n), f"Channel {n}") for n in range(1, self.channels + 1)]

    async def async_get_info(self) -> DeviceInfo:
        try:
            data = await self._request("GET", "/about")
        except EndpointNotFound as err:
            raise CannotConnect("no BirdDog API on this port") from err
        if not isinstance(data, dict):
            raise CannotConnect("no BirdDog API on this port")
        host = _ci(data, "HostName", "hostname")
        return DeviceInfo(
            name=str(host).removesuffix(".local") if host else None,
            manufacturer=self.MANUFACTURER,
            model=_ci(data, "Model", "ProductName", "DeviceModel") or "NDI decoder",
            firmware=_ci(data, "FirmwareVersion", "Firmware", "Version"),
            serial=_ci(data, "SerialNumber", "Serial"),
            mac=_ci(data, "MacAddress", "MAC"),
        )

    async def async_get_sources(self) -> list[SourceSighting]:
        data = await self._request("GET", "/List")
        if not isinstance(data, dict):
            return []
        return [
            SourceSighting(str(name), None if str(addr) in NONE_NAMES else str(addr))
            for name, addr in data.items()
            if str(name) not in NONE_NAMES
        ]

    async def async_refresh_sources(self) -> None:
        try:
            await self._request("POST", "/refresh")
        except CannotConnect:
            try:  # older firmware: GET /refresh
                await self._request("GET", "/refresh")
            except EndpointNotFound:
                pass

    async def async_get_current(self, destination: str) -> str | None:
        data = await self._request("GET", "/connectTo", params=self._ch(destination) or None)
        name = _ci(data, "sourceName") if isinstance(data, dict) else None
        return None if name is None or str(name) in NONE_NAMES else str(name)

    async def async_route(self, destination: str, source: str | None, address: str | None = None) -> None:
        body: dict[str, Any] = {"sourceName": source or "", **self._ch(destination)}
        for attempt in (1, 2):
            await self._request("POST", "/connectTo", body)
            await asyncio.sleep(self.VERIFY_DELAY)
            current = await self.async_get_current(destination)
            if current == (source or None):
                return
            _LOGGER.debug("BirdDog %s: route not applied (attempt %s), device shows %r", self.host, attempt, current)
        raise RouteFailed(f"device still shows {current!r}")

    async def async_get_status(self, destination: str) -> DestinationStatus:
        if not self._decodestatus_supported:
            return DestinationStatus()
        try:
            data = await self._request("GET", "/decodestatus", params=self._ch(destination) or None)
        except EndpointNotFound:
            self._decodestatus_supported = False
            return DestinationStatus()
        if not isinstance(data, dict):
            return DestinationStatus()
        state = _ci(data, "status", "State", "ConnectionStatus", "connected")
        connected: bool | None = None
        if isinstance(state, bool):
            connected = state
        elif state is not None:
            text = str(state).lower()
            if "disconnect" in text or "no source" in text or "not" in text or "idle" in text:
                connected = False
            elif "connect" in text or "decod" in text or "receiv" in text:
                connected = True
        resolution = _ci(data, "resolution", "VideoFormat", "Format", "vidFormat")
        if resolution is None:
            resolution = format_resolution(
                _ci(data, "width", "xres"), _ci(data, "height", "yres"), _ci(data, "fps", "framerate", "FrameRate")
            )
        else:
            fps = _ci(data, "fps", "framerate", "FrameRate")
            resolution = str(resolution) + (f"@{fps}" if fps and str(fps) not in str(resolution) else "")
        return DestinationStatus(connected=connected, resolution=resolution)
