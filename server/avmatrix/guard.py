"""Feste, serverseitige Sperrliste: Ziele, die über KEINE Schnittstelle verändert werden dürfen.

Zwei unabhängige Ebenen:

1. ``Guard.rule_for`` – der Hub prüft jedes Ziel, bevor er überhaupt einen Treiber anspricht
   (Schalten, Salve, Undo, Preset, Sperre lösen).
2. ``GuardedDanteNetwork._write`` – der Dante-Treiber weigert sich zusätzlich selbst, ein
   Abo-Paket an eine geschützte Adresse / einen geschützten Kanal zu schicken. Selbst ein Fehler
   im Hub kann die Sperre damit nicht umgehen.

Die Regeln stehen in der Konfiguration (``protected``) der jeweiligen Anlage – nie im Code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from .drivers.base import RouteFailed
from .drivers.dante import DanteDevice, DanteNetwork

#: Ohne Konfiguration ist nichts gesperrt. Die Regeln einer Anlage stehen in ihrer ``config.json``
#: (Schlüssel ``protected``), Beispiel in ``deploy/studio.example.json``.
DEFAULT_RULES: list[dict[str, Any]] = []


@dataclass(frozen=True, slots=True)
class ProtectionRule:
    """Ein Ziel ist geschützt, wenn Protokoll passt UND (Adresse ODER Gerätename passt) UND der Kanal passt."""

    protocol: str | None = None
    host: str | None = None
    device: str | None = None  # Muster mit * und ?, Groß-/Kleinschreibung egal
    channels: frozenset[int] | None = None  # None = alle Kanäle
    reason: str = "geschützt"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProtectionRule:
        channels = data.get("channels")
        if not data.get("host") and not data.get("device"):
            raise ValueError("Sperrregel braucht 'host' oder 'device'")
        return cls(
            protocol=(data.get("protocol") or None),
            host=(str(data["host"]).strip() if data.get("host") else None),
            device=(str(data["device"]).strip() if data.get("device") else None),
            channels=frozenset(int(c) for c in channels) if channels else None,
            reason=str(data.get("reason") or "geschützt"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "host": self.host,
            "device": self.device,
            "channels": sorted(self.channels) if self.channels else None,
            "reason": self.reason,
        }

    def matches(self, protocol: str | None, host: str | None, device: str | None, channel: int | None) -> bool:
        if self.protocol and protocol and self.protocol != protocol:
            return False
        by_host = bool(self.host and host and self.host.casefold() == host.strip().casefold())
        by_name = bool(self.device and device and fnmatchcase(device.casefold(), self.device.casefold()))
        if not (by_host or by_name):
            return False
        if self.channels is None:
            return True
        return channel is None or channel in self.channels  # Kanal unbekannt → im Zweifel geschützt


@dataclass(slots=True)
class Guard:
    rules: list[ProtectionRule] = field(default_factory=list)

    @classmethod
    def from_config(cls, raw: Any) -> Guard:
        """Liste von Regeln aus der Konfiguration; ``None`` (Schlüssel fehlt) → keine Regel."""
        data = DEFAULT_RULES if raw is None else raw
        return cls([ProtectionRule.from_dict(r) for r in data])

    def rule_for(
        self, protocol: str | None, host: str | None, device: str | None, channel: int | None
    ) -> ProtectionRule | None:
        for rule in self.rules:
            if rule.matches(protocol, host, device, channel):
                return rule
        return None


class GuardedDanteNetwork(DanteNetwork):
    """Dante-Treiber, der Schreibzugriffe auf geschützte Geräte/Kanäle selbst verweigert."""

    guard: Guard | None = None

    async def _write(  # type: ignore[override]
        self, dev: DanteDevice, rx: int, tx_channel: str | None, tx_device: str | None, protocol_id: int
    ) -> None:
        rule = self.guard.rule_for("dante", dev.host, dev.name, rx) if self.guard else None
        if rule is not None:
            raise RouteFailed(f"gesperrt: {rule.reason}")
        await super()._write(dev, rx, tx_channel, tx_device, protocol_id)
