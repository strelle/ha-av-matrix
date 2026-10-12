"""Ein zweiter NMOS-Controller – so, wie das Bedienfeld eines Blackmagic Ethernet Switch oder ein Videohub-Pult
schaltet: Er kennt die Kreuzschiene nicht, liest die Nodes selbst (IS-04) und verbindet Empfänger über IS-05.

Unabhängig vom Treiber geschrieben (nur aiohttp und die Spezifikation). In Tests und beim Vorführen:

    python -m nmos_sim.controller http://192.0.2.31:18090 "HDMI Out" http://192.0.2.34:18093 "SDI In 2"
    python -m nmos_sim.controller http://192.0.2.31:18090 "HDMI Out" none            # Verbindung trennen

Ein „Anschluss“ ist der Name eines Ein-/Ausgangs: alle Sender bzw. Empfänger, deren Name damit beginnt
(„SDI In 2 Video“, „SDI In 2 Audio“, „SDI In 2 ANC“), gehören dazu; verbunden wird Gleiches mit Gleichem.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import aiohttp

KINDS = ("video", "audio", "data")


class ForeignController:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def _get(self, url: str) -> Any:
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _port(self, node_url: str, what: str, name: str) -> tuple[str, dict[str, dict[str, Any]]]:
        """→ (Basis der Connection API, Art des Stroms → Sender/Empfänger) für einen Anschluss."""
        api = f"{node_url.rstrip('/')}/x-nmos/node/v1.3"
        device = (await self._get(f"{api}/devices"))[0]
        control = next(c["href"] for c in device["controls"] if c["type"].endswith("sr-ctrl/v1.1"))
        found: dict[str, dict[str, Any]] = {}
        flows = {f["id"]: f for f in await self._get(f"{api}/flows")} if what == "senders" else {}
        for item in await self._get(f"{api}/{what}"):
            if item["label"] != name and not item["label"].startswith(name + " "):
                continue
            urn = item["format"] if what == "receivers" else flows[item["flow_id"]]["format"]
            found[urn.rsplit(":", 1)[-1]] = item
        if not found:
            raise SystemExit(f"{node_url}: kein Anschluss {name!r}")
        return control.rstrip("/"), found

    async def take(self, dest_url: str, dest_port: str, source_url: str | None, source_port: str | None = None) -> list[str]:
        """Quelle auf Ziel schalten (``source_url=None``: trennen). → Namen der geschalteten Empfänger."""
        control, receivers = await self._port(dest_url, "receivers", dest_port)
        senders: dict[str, dict[str, Any]] = {}
        sender_control = ""
        if source_url is not None:
            sender_control, senders = await self._port(source_url, "senders", source_port or "")
        done = []
        for kind in KINDS:
            receiver, sender = receivers.get(kind), senders.get(kind)
            if receiver is None:
                continue
            body: dict[str, Any] = {"sender_id": None, "master_enable": False, "activation": {"mode": "activate_immediate"}}
            if sender is not None:
                base = f"{sender_control}/single/senders/{sender['id']}"
                # Blackmagic-Controller starten den Sender beim Schalten selbst (Handbuch, „Transmit 2110 Media“)
                await self._patch(f"{base}/staged", {"master_enable": True, "activation": {"mode": "activate_immediate"}})
                async with self.session.get(f"{base}/transportfile") as resp:
                    sdp = await resp.text()
                body.update({"sender_id": sender["id"], "master_enable": True, "transport_file": {"data": sdp, "type": "application/sdp"}})  # fmt: skip
            await self._patch(f"{control}/single/receivers/{receiver['id']}/staged", body)
            done.append(receiver["label"])
        return done

    async def _patch(self, url: str, body: dict[str, Any]) -> None:
        async with self.session.patch(url, json=body, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status not in (200, 202):
                raise SystemExit(f"{url}: {resp.status} {await resp.text()}")


async def _main(args: argparse.Namespace) -> None:
    async with aiohttp.ClientSession() as session:
        source = None if args.source.lower() in ("none", "aus", "-") else args.source
        done = await ForeignController(session).take(args.dest, args.dest_port, source, args.source_port)
        print(f"fremder Controller: {args.dest_port} ← {args.source_port if source else 'getrennt'}  ({', '.join(done)})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="nmos_sim.controller", description="Als zweiter NMOS-Controller schalten (Simulation).")
    parser.add_argument("dest", help="Adresse des Ziel-Nodes, z. B. http://127.0.0.1:18090")
    parser.add_argument("dest_port", help='Ausgang, z. B. "HDMI Out"')
    parser.add_argument("source", help="Adresse des Quell-Nodes oder 'none' zum Trennen")
    parser.add_argument("source_port", nargs="?", help='Eingang, z. B. "SDI In 2"')
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
