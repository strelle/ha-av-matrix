"""Aktive Netzwerksuche nach Geräten aller Treiber mit ``Driver.async_probe`` (aus ha-av-matrix, ohne HA).

Zwei Stufen je Adresse, kurze Timeouts, begrenzte Parallelität:
1. TCP-Verbindung zu den ``PROBE_PORTS`` der Treiber,
2. ``Driver.async_probe`` (nur lesender HTTP-Fingerabdruck) dort, wo ein Port offen ist.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterable
from ipaddress import IPv4Address, IPv4Network, ip_network

import aiohttp

from .drivers.base import Driver
from .models import ProbeResult

_LOGGER = logging.getLogger(__name__)

MIN_PREFIX = 22
DEFAULT_PREFIX = 24
CONCURRENCY = 48
CONNECT_TIMEOUT = 0.7
PROBE_TIMEOUT = 2.0


class InvalidSubnet(ValueError):
    """Kein IPv4-Subnetz oder größer als /22."""


def parse_subnet(text: str) -> IPv4Network:
    text = (text or "").strip()
    if not text:
        raise InvalidSubnet("empty")
    if "/" not in text:
        text += f"/{DEFAULT_PREFIX}"
    try:
        net = ip_network(text, strict=False)
    except ValueError as err:
        raise InvalidSubnet(str(err)) from err
    if not isinstance(net, IPv4Network) or net.prefixlen < MIN_PREFIX:
        raise InvalidSubnet("IPv4 /22 … /32 only")
    return net


async def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError, TimeoutError):
        await asyncio.wait_for(writer.wait_closed(), timeout)
    return True


async def async_probe_host(
    session: aiohttp.ClientSession,
    host: str,
    drivers: Iterable[type[Driver]],
    *,
    connect_timeout: float = CONNECT_TIMEOUT,
    probe_timeout: float = PROBE_TIMEOUT,
    check_ports: bool = True,
) -> ProbeResult | None:
    drivers = [d for d in drivers if d.PROBE_PORTS]
    open_ports: dict[int, bool] = {}
    if check_ports:
        ports = sorted({p for d in drivers for p in d.PROBE_PORTS})
        states = await asyncio.gather(*(_port_open(host, p, connect_timeout) for p in ports))
        open_ports = dict(zip(ports, states, strict=True))
    for driver in drivers:
        if check_ports and not any(open_ports[p] for p in driver.PROBE_PORTS):
            continue
        try:
            result = await driver.async_probe(session, host, probe_timeout)
        except Exception:  # noqa: BLE001 - eine kaputte Probe darf die Suche nie stoppen
            _LOGGER.debug("Probe of %s by %s failed", host, driver.KEY, exc_info=True)
            continue
        if result is not None:
            return result
    return None


async def async_scan(
    session: aiohttp.ClientSession,
    subnet: IPv4Network,
    drivers: Iterable[type[Driver]],
    *,
    concurrency: int = CONCURRENCY,
    connect_timeout: float = CONNECT_TIMEOUT,
    probe_timeout: float = PROBE_TIMEOUT,
) -> list[ProbeResult]:
    drivers = [d for d in drivers if d.PROBE_PORTS and not d.NETWORK]
    if not drivers:
        return []
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(host: str) -> ProbeResult | None:
        async with semaphore:
            return await async_probe_host(
                session, host, drivers, connect_timeout=connect_timeout, probe_timeout=probe_timeout
            )

    hosts = [str(h) for h in (subnet.hosts() if subnet.num_addresses > 1 else [subnet.network_address])]
    results = await asyncio.gather(*(one(h) for h in hosts))
    found = [r for r in results if r is not None]
    return sorted(found, key=lambda r: IPv4Address(r.host))
