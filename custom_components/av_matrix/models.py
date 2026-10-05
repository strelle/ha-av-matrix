"""Plain data models shared by drivers, protocols and the Home Assistant glue.

This module must not import Home Assistant so drivers and the source registry
stay testable (and reusable) without a running Home Assistant instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ConnectionState(StrEnum):
    """Connection state of a destination (decoder output / receiver channel)."""

    CONNECTED = "connected"
    CONNECTING = "connecting"
    NO_SOURCE = "no_source"
    SOURCE_LOST = "source_lost"
    OFFLINE = "offline"
    ERROR = "error"  # the device reports an error for this destination (e.g. a Dante subscription error)


class FieldType(StrEnum):
    """Type of a driver-declared config field."""

    STRING = "string"
    PASSWORD = "password"
    PORT = "port"
    INTEGER = "integer"


@dataclass(frozen=True, slots=True)
class ConfigField:
    """A config-flow field a driver needs (rendered generically by the config flow).

    Common keys (``host``, ``port``, ``username``, ``password``, ``name``,
    ``channels``) are already translated. A new key needs an entry in
    ``strings.json`` / ``translations/*.json`` - but no config flow code.
    """

    key: str
    type: FieldType = FieldType.STRING
    required: bool = True
    default: Any = None
    minimum: int | None = None
    maximum: int | None = None
    secret: bool = False  # redacted in diagnostics, asked again on re-auth


@dataclass(slots=True)
class DeviceInfo:
    """Static information about a device."""

    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    serial: str | None = None
    mac: str | None = None


@dataclass(frozen=True, slots=True)
class DestinationInfo:
    """A routable destination of a device (decoder output, receiver channel ...)."""

    id: str
    name: str | None = None  # None = the device's only destination
    device: str | None = None  # sub-device (network drivers like Dante: the Dante device), None = the entry's device


@dataclass(frozen=True, slots=True)
class SourceSighting:
    """A source as reported by a device or a discovery mechanism."""

    name: str
    address: str | None = None  # "ip:port", informational - never an identity


@dataclass(slots=True)
class DestinationStatus:
    """Live status of one destination as reported by the device."""

    connected: bool | None = None  # None = the device cannot tell
    resolution: str | None = None  # video format (e.g. 1920x1080p50) or audio format (e.g. 48 kHz)
    extra: dict[str, Any] = field(default_factory=dict)
    state: ConnectionState | None = None  # explicit state if the device reports one (overrides the derivation)


@dataclass(slots=True)
class DestinationState:
    """Polled state of one destination: current source (device's own name) + status."""

    current: str | None = None
    status: DestinationStatus = field(default_factory=DestinationStatus)


@dataclass(slots=True)
class DevicePoll:
    """Result of one poll cycle of a device."""

    sources: list[SourceSighting] = field(default_factory=list)
    destinations: dict[str, DestinationState] = field(default_factory=dict)
