"""Protocol-independent source registry.

One registry per protocol. It merges sightings from
* discovery (e.g. mDNS) - authoritative: whatever discovery sees is alive,
* devices whose source list is trusted (built live by the device),
* devices whose source list is NOT trusted (may contain stale entries) - those
  are only alive if their address answers (``probe``) and the address is not
  currently used by another, live-seen source ("an address is not an identity").

Identity of a source is its protocol name (NDI: the NDI name), never an address.
Sources disappear only after ``hold_time`` seconds without being alive
(hysteresis, so option lists in the UI do not jump around).

No Home Assistant imports here.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field

from ..models import SourceSighting

ProbeFunc = Callable[[str], Awaitable[bool]]

HOLD_TIME = 120.0
PROBE_TTL = 8.0


@dataclass(slots=True)
class SourceRecord:
    """A source known to the registry."""

    id: str
    address: str | None = None
    live: bool = False
    first_seen: float = 0.0  # wall clock (time.time)
    last_seen: float = 0.0  # wall clock of the last time it was alive
    seen_by: set[str] = field(default_factory=set)

    @property
    def host(self) -> str | None:
        if not self.address:
            return None
        return self.address.rsplit(":", 1)[0] if ":" in self.address else self.address


class SourceRegistry:
    """Source registry of one protocol."""

    protocol: str = "generic"
    #: Device-specific placeholder names that must be mapped to a real name by address.
    placeholder_re: re.Pattern[str] | None = None

    def __init__(
        self,
        probe: ProbeFunc | None = None,
        *,
        hold_time: float = HOLD_TIME,
        probe_ttl: float = PROBE_TTL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._probe = probe
        self.hold_time = hold_time
        self.probe_ttl = probe_ttl
        self._clock = clock
        self._discovered: dict[str, str | None] = {}
        self._device: dict[str, tuple[bool, list[SourceSighting]]] = {}
        self._probe_cache: dict[str, tuple[bool, float]] = {}
        self._records: dict[str, SourceRecord] = {}
        self._aliases: dict[tuple[str, str], str] = {}  # (device_key, placeholder) -> real name
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ inputs
    def set_discovered(self, name: str, address: str | None) -> None:
        self._discovered[name] = address

    def mark_discovered(self, name: str) -> None:
        """Seen by discovery, address not (yet) resolved."""
        self._discovered.setdefault(name, None)

    def remove_discovered(self, name: str) -> None:
        self._discovered.pop(name, None)

    def set_device_sightings(self, device_key: str, sightings: Iterable[SourceSighting], trusted: bool) -> None:
        self._device[device_key] = (trusted, list(sightings))

    def remove_device(self, device_key: str) -> None:
        self._device.pop(device_key, None)
        self._aliases = {k: v for k, v in self._aliases.items() if k[0] != device_key}

    def forget(self) -> None:
        """Forget cached knowledge (probe results, held sources). Used by "refresh sources"."""
        self._probe_cache.clear()
        self._records = {k: r for k, r in self._records.items() if r.live}

    # --------------------------------------------------------------- queries
    def is_placeholder(self, name: str) -> bool:
        return bool(self.placeholder_re and self.placeholder_re.match(name))

    @property
    def sources(self) -> list[SourceRecord]:
        return sorted(self._records.values(), key=lambda r: r.id.casefold())

    def get(self, source_id: str) -> SourceRecord | None:
        return self._records.get(source_id)

    def is_live(self, source_id: str | None) -> bool:
        rec = self._records.get(source_id) if source_id else None
        return bool(rec and rec.live)

    def real_name(self, device_key: str, name: str | None) -> str | None:
        """Name under which the registry knows a source a device reports (placeholders resolved)."""
        if name is None:
            return None
        return self._aliases.get((device_key, name), name)

    def device_name(self, device_key: str, source_id: str) -> str:
        """Reverse: the name under which THIS device knows ``source_id``."""
        for (key, placeholder), real in self._aliases.items():
            if key == device_key and real == source_id:
                return placeholder
        return source_id

    def address_for(self, device_key: str, source_id: str) -> str | None:
        rec = self._records.get(source_id)
        return rec.address if rec else None

    # ------------------------------------------------------------ evaluation
    async def _probe_cached(self, address: str, now: float) -> bool:
        cached = self._probe_cache.get(address)
        if cached and now - cached[1] < self.probe_ttl:
            return cached[0]
        ok = bool(self._probe and await self._probe(address))
        self._probe_cache[address] = (ok, now)
        return ok

    async def async_evaluate(self) -> bool:
        """Recompute liveness. Returns True if the visible source list changed."""
        async with self._lock:
            return await self._evaluate()

    async def _evaluate(self) -> bool:
        now = self._clock()
        # 1. authoritative: discovery + trusted device lists
        live: dict[str, tuple[str | None, set[str]]] = {}
        for name, addr in self._discovered.items():
            live[name] = (addr, {"discovery"})
        for key, (trusted, sightings) in self._device.items():
            if not trusted:
                continue
            for s in sightings:
                if self.is_placeholder(s.name):
                    continue
                addr, seen = live.get(s.name, (None, set()))
                live[s.name] = (addr or s.address, seen | {key})
        occupied = {addr: name for name, (addr, _) in live.items() if addr}

        # 2. placeholders → real names via the address that is in use right now
        aliases: dict[tuple[str, str], str] = {}
        untrusted: dict[str, tuple[str | None, set[str]]] = {}
        for key, (trusted, sightings) in self._device.items():
            for s in sightings:
                if self.is_placeholder(s.name):
                    if s.address and s.address in occupied:
                        aliases[(key, s.name)] = occupied[s.address]
                        continue
                    if (key, s.name) in self._aliases:
                        aliases[(key, s.name)] = self._aliases[(key, s.name)]
                        continue
                    # unmapped placeholder: keep it as a (cryptic) source of its own,
                    # users can give it a label
                if (not trusted or self.is_placeholder(s.name)) and s.name not in live:
                    addr, seen = untrusted.get(s.name, (None, set()))
                    untrusted[s.name] = (addr or s.address, seen | {key})
        self._aliases = aliases

        # 3. untrusted-only sources: alive if the address answers and nobody else uses it
        candidates = {n: a for n, (a, _) in untrusted.items() if a and a not in occupied}
        results = await asyncio.gather(*(self._probe_cached(a, now) for a in candidates.values()))
        for (name, addr), ok in zip(candidates.items(), results, strict=True):
            if ok:
                live[name] = (addr, untrusted[name][1])

        # 4. merge into records with hysteresis
        before = {(r.id, r.live) for r in self._records.values()}
        for rec in self._records.values():
            rec.live = False
        for name, (addr, seen) in live.items():
            rec = self._records.get(name)
            if rec is None:
                rec = self._records[name] = SourceRecord(name, first_seen=now)
            rec.live = True
            rec.address = addr or rec.address
            rec.last_seen = now
            rec.seen_by = seen
        for name in [n for n, r in self._records.items() if not r.live and now - r.last_seen > self.hold_time]:
            del self._records[name]
        return before != {(r.id, r.live) for r in self._records.values()}


async def tcp_probe(address: str, timeout: float = 1.0) -> bool:
    """True if ``host:port`` accepts a TCP connection."""
    try:
        host, port = address.rsplit(":", 1)
        _, writer = await asyncio.wait_for(asyncio.open_connection(host.strip("[]"), int(port)), timeout)
    except (OSError, ValueError, TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True
