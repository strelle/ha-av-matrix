"""Active network scan for devices of all drivers that implement ``Driver.async_probe``.

Two stages per address, both with short timeouts and a global limit on parallel connections:

1. TCP connect to the driver's ``PROBE_PORTS`` (cheap, unreachable addresses time out quickly),
2. ``Driver.async_probe`` (read-only HTTP fingerprint) only where a port is open.

New drivers take part automatically as soon as they set ``PROBE_PORTS`` and implement ``async_probe``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterable
from ipaddress import IPv4Address, IPv4Interface, IPv4Network, ip_network

import aiohttp
from homeassistant.components import network
from homeassistant.core import HomeAssistant

from .drivers.base import Driver
from .models import ProbeResult

_LOGGER = logging.getLogger(__name__)

#: Largest subnet a scan accepts (/22 = 1022 addresses)
MIN_PREFIX = 22
DEFAULT_PREFIX = 24
CONCURRENCY = 64
CONNECT_TIMEOUT = 0.7
PROBE_TIMEOUT = 2.0


class InvalidSubnet(ValueError):
    """Not an IPv4 subnet, or larger than /22."""


def parse_subnet(text: str) -> IPv4Network:
    """``"192.0.2.0/24"`` / ``"192.0.2.7/24"`` / ``"192.0.2.7"`` (→ /24) → network. Raises InvalidSubnet."""
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


async def async_default_subnet(hass: HomeAssistant) -> IPv4Network | None:
    """Home Assistant's own IPv4 network, narrowed to a /24 if it is larger."""
    try:
        adapters = await network.async_get_adapters(hass)
    except Exception:  # noqa: BLE001 - only a default for the form
        return None
    for adapter in adapters:
        if not adapter.get("enabled"):
            continue
        for ipv4 in adapter.get("ipv4") or []:
            address = ipv4.get("address")
            if not address or IPv4Address(address).is_loopback or IPv4Address(address).is_link_local:
                continue
            prefix = max(int(ipv4.get("network_prefix") or DEFAULT_PREFIX), DEFAULT_PREFIX)
            return IPv4Interface(f"{address}/{prefix}").network
    return None


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
    """First driver whose fingerprint matches ``host`` (``check_ports=False``: probe directly)."""
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
        except Exception:  # a broken probe must never stop the scan
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
    """Probe every host address of ``subnet``; results sorted by address."""
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
    _LOGGER.debug("Scan of %s: %d addresses, %d devices", subnet, len(hosts), len(found))
    return sorted(found, key=lambda r: IPv4Address(r.host))
