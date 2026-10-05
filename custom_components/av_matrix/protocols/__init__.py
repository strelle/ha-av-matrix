"""Protocols (NDI®, Dante® …). Each protocol has its own source registry.

Sources of one protocol can only be routed to destinations of the same protocol.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import SourceRecord, SourceRegistry, tcp_probe
from .dante import DanteSourceRegistry
from .ndi import NdiSourceRegistry


@dataclass(frozen=True, slots=True)
class Protocol:
    """Static description of a protocol."""

    key: str
    title: str
    registry: type[SourceRegistry]


PROTOCOLS: dict[str, Protocol] = {
    "ndi": Protocol("ndi", "NDI®", NdiSourceRegistry),
    "dante": Protocol("dante", "Dante®", DanteSourceRegistry),
}

__all__ = ["PROTOCOLS", "Protocol", "SourceRecord", "SourceRegistry", "tcp_probe"]
