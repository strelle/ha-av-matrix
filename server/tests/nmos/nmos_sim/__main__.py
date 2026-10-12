"""``python -m nmos_sim`` – die fünf Blackmagic-Geräte lokal simulieren (Strg+C beendet und meldet ab).

Vorgabe: alles auf 127.0.0.1, mDNS nur auf der Loopback-Schnittstelle. Mit ``--lan <eigene IP>`` hören die
Nodes an dieser Adresse und werden im Netz angekündigt – nur für Vorführungen, nie neben einer laufenden
Kreuzschiene (die Phantomgeräte würden dort erscheinen).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal

from . import blackmagic
from .network import LOOPBACK, SimNetwork


async def run(args: argparse.Namespace) -> None:
    specs = blackmagic.studio()
    if args.four_nodes:
        specs = [s for s in specs if "4x12G" not in s.label] + blackmagic.converter_4x12g_as_four_nodes()
    host = args.lan or LOOPBACK
    net = SimNetwork(specs, host=host, base_port=args.port, mdns=None if args.no_mdns else host, registry=args.registry)
    await net.start()
    print(f"NMOS-Simulation läuft ({'NETZ ' + host if args.lan else 'nur lokal'}), mDNS: {'aus' if args.no_mdns else host}")
    for node in net.nodes:
        print(f"  {node.spec.label:45s} {node.url}/x-nmos/node/v1.3/self")
    if net.registry:
        print(f"  Registry {net.registry.url}/x-nmos/query/v1.3/nodes")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    if args.seconds:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), args.seconds)
    else:
        await stop.wait()
    await net.stop()
    print("Simulation beendet, mDNS-Einträge abgemeldet.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="nmos_sim", description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=18090, help="erster Port (Vorgabe 18090, je Gerät +1)")
    parser.add_argument("--lan", metavar="IP", help="an dieser eigenen Adresse hören und im Netz ankündigen (Vorsicht)")
    parser.add_argument("--no-mdns", action="store_true", help="nicht ankündigen")
    parser.add_argument("--registry", action="store_true", help="zusätzlich eine Registry (Query API) starten")
    parser.add_argument("--four-nodes", action="store_true", help="4x12G als vier einzelne Nodes")
    parser.add_argument("--seconds", type=float, default=0, help="nach so vielen Sekunden von selbst beenden")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
