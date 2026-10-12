"""``nmos-check`` – was meldet sich im Netz per NMOS, und lässt es sich schalten?

Am Liefertag: Geräte einstecken, dann

    nmos-check                 alle NMOS-Geräte auflisten (nur lesend)
    nmos-check --probe         zusätzlich einen Probe-Schaltvorgang mit Zurückschalten anbieten
    nmos-check --host 192.0.2.50:8090      ein Gerät direkt ansprechen, falls es sich nicht selbst meldet

Ohne ``--probe`` wird an keinem Gerät etwas verändert. Die Probe merkt sich den genauen Zustand des Ziels,
schaltet, liest zurück und stellt den Zustand wieder her (auch einen dafür eingeschalteten Sender).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import aiohttp
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncZeroconf

from .drivers.base import DriverError
from .drivers.nmos import CONF_AUDIO_BREAKAWAY, CONF_CHECK_COMPAT, CONF_STATIC_HOSTS, NmosNetwork, NmosNode
from .protocols import nmos
from .protocols.nmos_mdns import NmosBrowser

EXIT_OK, EXIT_ERROR, EXIT_PROBE_FAILED = 0, 1, 2


def say(text: str = "") -> None:
    print(text, flush=True)


async def discover(args: argparse.Namespace, session: aiohttp.ClientSession) -> tuple[NmosNetwork, dict[str, Any]]:
    """mDNS-Suche (und ``--host``), danach zwei Abfragen: finden und lesen."""
    driver = NmosNetwork(
        session,
        {"host": "nmos"},
        options={
            CONF_STATIC_HOSTS: args.host,
            CONF_AUDIO_BREAKAWAY: args.audio,
            CONF_CHECK_COMPAT: not args.force,
            "registries": args.registry,
        },
    )
    stats: dict[str, Any] = {"mdns": not args.no_mdns, "mdns_error": None, "announced": 0, "registries": 0}
    aiozc = browser = None
    if not args.no_mdns:
        try:
            kwargs: dict[str, Any] = {"ip_version": IPVersion.V4Only}
            if args.interface:
                kwargs["interfaces"] = [args.interface]
            aiozc = AsyncZeroconf(**kwargs)
            browser = NmosBrowser(aiozc.zeroconf, lambda: driver)
            await browser.async_start()
        except Exception as err:  # noqa: BLE001 - ohne mDNS geht --host trotzdem
            stats["mdns_error"] = str(err)
    try:
        waited = 0.0
        while waited < args.timeout:
            await asyncio.sleep(min(1.0, args.timeout - waited))
            waited += 1.0
            if browser is not None and browser.nodes and waited >= 2.0 and len(browser.nodes) == stats["announced"]:
                break  # seit einer Sekunde nichts Neues
            stats["announced"] = len(browser.nodes) if browser else 0
        if browser is not None:
            stats["announced"], stats["registries"] = len(browser.nodes), len(browser.registries)
        await driver.async_poll()  # finden …
        await driver.async_poll()  # … und alles lesen (Registry-Einträge kommen im ersten Durchgang dazu)
    finally:
        if browser is not None:
            await browser.async_stop()
        if aiozc is not None:
            await aiozc.async_close()
    return driver, stats


def describe_node(driver: NmosNetwork, node: NmosNode) -> None:
    how = ", ".join(w for w, on in (("mDNS", node.via_mdns), ("Registry", node.via_registry), ("von Hand", node.static)) if on)
    say(f"\n■ {node.name}")
    say(f"  Adresse      {node.host}:{node.port}  (gefunden über {how or '?'})")
    if not node.online:
        say(f"  OFFLINE      {node.last_error or 'antwortet nicht'}")
        return
    say(
        f"  Gerät        {node.manufacturer or 'Hersteller unbekannt'} · {node.model or 'Modell unbekannt'} · {node.device_type_title}"
    )
    say(f"  Schnittstelle IS-04 {node.api_version}, IS-05 {_connection_versions(node)}")
    say(f"  Weboberfläche {node.web_url or 'keine (auf Port 80 antwortet keine Webseite)'}")
    ptp = node.ptp
    if ptp is None:
        say("  PTP          Gerät meldet keine PTP-Uhr")
    else:
        lock = {True: "eingerastet", False: "NICHT eingerastet", None: "unbekannt"}[ptp["locked"]]
        say(f"  PTP          {lock}, Taktgeber {ptp['grandmaster'] or '?'}")
    assert node.data is not None
    say(f"  Sender ({len(node.data.senders)})")
    for sender in sorted(node.data.senders.values(), key=lambda s: nmos.natural_key(s.label)):
        hint = (sender.tags.get(nmos.GROUPHINT_TAG) or ["–"])[0]
        state = {True: "sendet", False: "AUS", None: "?"}[sender.active]
        say(f"    {sender.label:28s} {sender.flow.text if sender.flow else 'kein Signal/Flow':38s} {state:7s} Gruppe: {hint}")
    say(f"  Empfänger ({len(node.data.receivers)})")
    for receiver in sorted(node.data.receivers.values(), key=lambda r: nmos.natural_key(r.label)):
        hint = (receiver.tags.get(nmos.GROUPHINT_TAG) or ["–"])[0]
        media = ", ".join(nmos.media_title(m) for m in receiver.caps.get("media_types") or []) or "keine Angabe"
        conn = node.conn.get(receiver.id)
        current = driver._source_of(node, receiver.id) if conn else None
        say(f"    {receiver.label:28s} nimmt: {media:38s} ← {current or 'nichts'}  Gruppe: {hint}")
    if node.is04_unreliable:
        say("  Hinweis      IS-04 zeigt den Schaltzustand nicht zuverlässig; der Treiber liest ihn über IS-05 (etwas mehr Last).")
    if any(not g.hinted for g in [*node.sources.values(), *node.dests.values()]):
        say("  Hinweis      Gerät nennt keine Gruppen (BCP-002-01); Bild/Ton/ANC wurden über die Namen zusammengefasst.")


def _connection_versions(node: NmosNode) -> str:
    versions = {d.connection_version for d in node.data.devices.values()} if node.data else set()
    return ", ".join(sorted(v for v in versions if v)) or "FEHLT (nicht schaltbar)"


def describe_matrix(driver: NmosNetwork) -> None:
    say("\nSo erscheinen die Geräte in der Kreuzschiene (Gruppe „ST 2110“, keine Vorschau verfügbar):")
    say("  Quellen")
    for node in driver.visible_devices():
        for name in node.sources if node.online else []:
            sid = nmos.source_id(name, node.name)
            info = driver.source_info(sid)
            say(f"    {sid:62s} {'+'.join(info.get('essences') or []):17s} {info.get('format') or ''}")
    say("  Ziele")
    for dest in driver.destinations():
        node, group, audio = driver._dest(dest.id)
        current = driver._current(node, group, audio)
        say(f"    {dest.id:62s} {'+'.join(group.kinds()) if not audio else 'audio':17s} ← {current or 'nichts'}")


def pick_probe(driver: NmosNetwork, args: argparse.Namespace) -> tuple[str, str] | None:
    """Ziel und Quelle für die Probe: wie angegeben, sonst das erste Paar, das zusammenpasst."""
    dests = [d.id for d in driver.destinations() if driver.destination_available(d.id) and not d.id.endswith(nmos.AUDIO_SUFFIX)]
    sources = [nmos.source_id(g, n.name) for n in driver.visible_devices() if n.online for g in n.sources]
    if args.dest:
        dests = [d for d in dests if d.casefold() == args.dest.casefold()] or [args.dest]
    if args.source:
        sources = [s for s in sources if s.casefold() == args.source.casefold()] or [args.source]
    problems: list[str] = []
    for dest in dests:
        node = driver._node_of(dest)
        # ein anderes Gerät als Quelle bevorzugen (das ist der echte Fall)
        for source in sorted(sources, key=lambda s: bool(node and s.endswith("@" + node.name))):
            try:
                driver.plan(dest, source)
            except DriverError as err:
                problems.append(f"    {source} → {dest}: {err}")
                continue
            return dest, source
    if problems:
        say("  Keine passende Kombination gefunden:")
        for line in problems[:8]:
            say(line)
    return None


async def probe(driver: NmosNetwork, args: argparse.Namespace) -> int:
    say("\nProbe-Schaltvorgang")
    pair = pick_probe(driver, args)
    if pair is None:
        say("  Dafür braucht es mindestens einen Sender und einen dazu passenden Empfänger. Nichts geschaltet.")
        return EXIT_PROBE_FAILED
    dest, source = pair
    before = await driver.async_get_current(dest)
    say(f"  Ziel    {dest}   (jetzt: {before or 'nichts'})")
    say(f"  Quelle  {source}")
    for step in driver.plan(dest, source):
        what = nmos.KIND_TITLE.get(step.layer[0], step.layer[0])
        say(
            f"    {what:12s} {step.sender.label if step.sender else '– wird getrennt: ' + (step.note or '')} → {step.receiver.label}"
        )
    say(f"  Danach wird der jetzige Zustand wiederhergestellt (nach {args.hold:g} s).")
    if not args.yes:
        if not sys.stdin.isatty():
            say("  Abgebrochen: Bestätigung nötig (im Terminal starten oder --yes angeben).")
            return EXIT_PROBE_FAILED
        if input("  Jetzt schalten? [j/N] ").strip().lower() not in ("j", "ja", "y", "yes"):
            say("  Abgebrochen, nichts geschaltet.")
            return EXIT_OK
    snapshot = await driver.async_snapshot(dest)
    switched_before = len(driver.switched_on)
    result = EXIT_OK
    try:
        await driver.async_route(dest, source)
        await driver.async_poll()
        now = await driver.async_get_current(dest)
        status = await driver.async_get_status(dest)
        node = driver._node_of(dest)
        say(
            f"  ✔ geschaltet und zurückgelesen: {now}  ({status.resolution}, Zustand {status.state.value if status.state else '?'})"
        )
        say(f"    Das Gerät nimmt Verbindungen an als: {_mode_text(node.patch_mode if node else None)}")
        for device in dict.fromkeys(d for d, _ in driver.switched_on[switched_before:]):
            say(f"    Die Sender an {device} waren ausgeschaltet und wurden für die Probe eingeschaltet (danach wieder aus).")
        if now != source:
            say("  ✘ Das Ziel meldet eine andere Quelle als geschaltet.")
            result = EXIT_PROBE_FAILED
        say(f"    Bitte jetzt am Ausgang nachsehen, ob Bild und Ton ankommen ({args.hold:g} s) …")
        await asyncio.sleep(args.hold)
    except DriverError as err:
        say(f"  ✘ Schalten fehlgeschlagen: {err}")
        result = EXIT_PROBE_FAILED
    finally:
        try:
            await driver.async_restore(dest, snapshot)
            for device, sender_id in driver.switched_on[switched_before:]:
                await driver.async_set_sender(device, sender_id, False)
            del driver.switched_on[switched_before:]
            await driver.async_poll()
            after = await driver.async_get_current(dest)
            ok = after == before
            say(f"  {'✔' if ok else '✘'} zurückgestellt: {after or 'nichts'}")
            if not ok:
                result = EXIT_PROBE_FAILED
        except DriverError as err:
            say(f"  ✘ Zurückstellen fehlgeschlagen: {err}  → Ziel bitte von Hand prüfen!")
            result = EXIT_PROBE_FAILED
    return result


def _mode_text(mode: str | None) -> str:
    return {
        "sdp": "Sender-Kennung + SDP-Datei (der Normalfall)",
        "params": "Sender-Kennung + einzelne Transportparameter (SDP wurde abgelehnt)",
        "id": "nur Sender-Kennung (SDP und Parameter wurden abgelehnt)",
    }.get(mode or "", "unbekannt")


async def run(args: argparse.Namespace) -> int:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        say(
            f"Suche NMOS-Geräte ({'mDNS _nmos-node._tcp' if not args.no_mdns else 'ohne mDNS'}{', ' + ', '.join(args.host) if args.host else ''}), bis zu {args.timeout:g} s …"
        )
        driver, stats = await discover(args, session)
        nodes = driver.visible_devices()
        if args.json:
            print(json.dumps({"discovery": stats, **driver.diagnostics()}, indent=2, ensure_ascii=False, default=str))
            return EXIT_OK
        if stats["mdns_error"]:
            say(f"mDNS nicht verfügbar: {stats['mdns_error']}")
        if not nodes:
            say("\nKeine NMOS-Geräte gefunden.")
            if stats["announced"] or driver._pending:
                say(f"  {stats['announced']} Gerät(e) haben sich angekündigt, aber keines antwortet auf der NMOS-Schnittstelle:")
                for host, port in driver._pending:
                    say(f"    {host}:{port or '?'}")
            say("  Das ist richtig, solange noch kein ST-2110-Gerät am Netz hängt. Sonst prüfen:")
            say("   · Gerät eingeschaltet, Netzwerkkabel an einem 10-Gbit-Port, Link-Anzeige an?")
            say("   · Hängt dieser Rechner im selben Netz/VLAN wie das Gerät? (mDNS geht nicht über Netzgrenzen)")
            say("   · Hat das Gerät eine Adresse? (Blackmagic Converters Setup zeigt sie) – dann direkt:")
            say("       nmos-check --host <Adresse>          probiert die üblichen Ports (8090, 80, 3212, 8080)")
            return EXIT_OK
        online = [n for n in nodes if n.online]
        say(
            f"\n{len(nodes)} NMOS-Gerät(e) gefunden, {len(online)} antworten."
            + (f"  Registry im Netz: {', '.join(driver.registries)}" if driver.registries else "")
        )
        for node in nodes:
            describe_node(driver, node)
        describe_matrix(driver)
        grandmasters = {n.ptp["grandmaster"] for n in online if n.ptp and n.ptp["grandmaster"]}
        unlocked = [n.name for n in online if n.ptp and n.ptp["locked"] is False]
        if len(grandmasters) > 1:
            say(
                f"\n⚠ Die Geräte hören auf verschiedene PTP-Taktgeber ({', '.join(sorted(grandmasters))}) – so gibt es kein stabiles Bild."
            )
        if unlocked:
            say(f"\n⚠ PTP nicht eingerastet: {', '.join(unlocked)}")
        if args.probe:
            return await probe(driver, args)
        say("\nNichts verändert. Probe-Schaltvorgang: nmos-check --probe")
        return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nmos-check", description="NMOS-Geräte (SMPTE ST 2110) im Netz auflisten und probeweise schalten."
    )
    parser.add_argument("--timeout", type=float, default=6.0, help="Sekunden für die Suche (Vorgabe 6)")
    parser.add_argument("--interface", metavar="IP", help="nur über diese eigene Adresse suchen (Vorgabe: alle Schnittstellen)")
    parser.add_argument(
        "--host", action="append", default=[], metavar="ADRESSE[:PORT]", help="Gerät direkt ansprechen (mehrfach möglich)"
    )
    parser.add_argument(
        "--registry",
        action="append",
        default=[],
        metavar="URL",
        help="NMOS-Registry direkt angeben, z. B. http://192.0.2.5:8010",
    )
    parser.add_argument("--no-mdns", action="store_true", help="nicht per mDNS suchen (nur --host / --registry)")
    parser.add_argument("--probe", action="store_true", help="Probe-Schaltvorgang mit Zurückschalten")
    parser.add_argument("--dest", help="Ziel für die Probe (sonst das erste passende)")
    parser.add_argument("--source", help="Quelle für die Probe (sonst die erste passende)")
    parser.add_argument("--hold", type=float, default=5.0, help="Sekunden, die die Probe-Verbindung steht (Vorgabe 5)")
    parser.add_argument("--yes", action="store_true", help="Probe ohne Rückfrage schalten")
    parser.add_argument(
        "--force", action="store_true", help="Kompatibilitätsprüfung auslassen (falls ein Gerät unsinnige Fähigkeiten meldet)"
    )
    parser.add_argument("--audio", action="store_true", help="Ton-Ziele zusätzlich einzeln zeigen (Audio getrennt schalten)")
    parser.add_argument("--json", action="store_true", help="alles als JSON ausgeben (für die Fehlersuche)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
