"""Driver interface. One driver = one device family of one protocol.

A driver talks to exactly one physical device. It knows nothing about Home
Assistant; the integration wraps it in a ``DataUpdateCoordinator``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

import aiohttp

from ..models import (
    ConfigField,
    DestinationInfo,
    DestinationState,
    DestinationStatus,
    DeviceInfo,
    DevicePoll,
    FieldType,
    SourceSighting,
)

DEFAULT_TIMEOUT = 3.0


class DriverError(Exception):
    """Base error of all drivers. Messages are short and never contain secrets."""


class CannotConnect(DriverError):
    """The device is unreachable or answered garbage."""


class InvalidAuth(DriverError):
    """The device rejected the credentials."""


class RouteFailed(DriverError):
    """The device did not accept the requested route."""


def short(err: object, limit: int = 120) -> str:
    """Return a short, single-line error text."""
    text = " ".join(str(err).split()) or err.__class__.__name__
    return text if len(text) <= limit else text[: limit - 1] + "…"


HOST = ConfigField("host")
NAME = ConfigField("name", required=False)


class Driver(ABC):
    """Base class of all device drivers."""

    #: Registry key, e.g. ``"birddog"``. Stored in the config entry.
    KEY: ClassVar[str]
    #: Protocol key, e.g. ``"ndi"``. Sources route only to destinations of the same protocol.
    PROTOCOL: ClassVar[str]
    #: Shown in the config flow, e.g. ``"BirdDog (PLAY, Mini, Flex, Studio …)"``.
    TITLE: ClassVar[str]
    MANUFACTURER: ClassVar[str]
    DEFAULT_PORT: ClassVar[int | None] = None
    #: Fields the config flow asks for (in this order).
    CONFIG_FIELDS: ClassVar[tuple[ConfigField, ...]] = (HOST, NAME)
    #: True if the device's own source list only contains sources that are alive right now.
    TRUSTED_SOURCE_LIST: ClassVar[bool] = True
    #: Seconds a destination needs after a route before it reports "connected".
    SETTLE_TIME: ClassVar[float] = 3.0

    def __init__(
        self,
        session: aiohttp.ClientSession,
        config: Mapping[str, Any],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self.config = dict(config)
        self.host: str = str(config["host"]).strip()
        port = config.get("port") or self.DEFAULT_PORT
        self.port: int | None = int(port) if port else None
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    # ------------------------------------------------------------------ helpers
    @classmethod
    def secret_keys(cls) -> set[str]:
        """Config keys that must never be logged or exported."""
        return {f.key for f in cls.CONFIG_FIELDS if f.secret or f.type is FieldType.PASSWORD}

    @property
    def configuration_url(self) -> str | None:
        """Web UI of the device, if any."""
        return f"http://{self.host}"

    # --------------------------------------------------------------- interface
    def destinations(self) -> list[DestinationInfo]:
        """Destinations of this device. Static per config entry (default: exactly one)."""
        return [DestinationInfo("main")]

    @abstractmethod
    async def async_get_info(self) -> DeviceInfo:
        """Read static device information. Raises CannotConnect / InvalidAuth.

        Used by the config flow to validate a configuration.
        """

    @abstractmethod
    async def async_get_sources(self) -> list[SourceSighting]:
        """Return the sources the device can see (device's own naming)."""

    @abstractmethod
    async def async_get_current(self, destination: str) -> str | None:
        """Return the source currently routed to ``destination`` (None = nothing)."""

    @abstractmethod
    async def async_route(self, destination: str, source: str | None, address: str | None = None) -> None:
        """Route ``source`` (device's own naming, None = off) to ``destination``."""

    async def async_get_status(self, destination: str) -> DestinationStatus:
        """Return live status of ``destination``. Default: unknown."""
        return DestinationStatus()

    async def async_refresh_sources(self) -> None:
        """Ask the device to rebuild its source list (no-op if unsupported)."""

    async def async_poll(self) -> DevicePoll:
        """One poll cycle. Drivers may override this to save requests."""
        poll = DevicePoll(sources=await self.async_get_sources())
        for dest in self.destinations():
            poll.destinations[dest.id] = DestinationState(
                current=await self.async_get_current(dest.id),
                status=await self.async_get_status(dest.id),
            )
        return poll


def format_resolution(width: Any, height: Any, rate: Any = None, interlaced: Any = False) -> str | None:
    """Format ``1920x1080p50`` from loosely typed device values."""
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    text = f"{w}x{h}{'i' if interlaced in (True, 1, '1', 'true', 'True') else 'p'}"
    try:
        r = float(rate)
    except (TypeError, ValueError):
        return text
    if r > 1000:  # some firmwares report hundredths (5994 = 59.94)
        r /= 100
    if r <= 0:
        return text
    return text + (f"{r:.2f}".rstrip("0").rstrip("."))
