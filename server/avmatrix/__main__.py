"""Start: ``python -m avmatrix [--port 8088] [--host 0.0.0.0]``."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from typing import Any

import aiohttp
from aiohttp import web

from . import __version__
from .flows import FlowManager, default_subnet
from .hub import Hub
from .netinfo import addresses, allowed_hosts
from .preview import PreviewManager
from .store import JsonFile, TokenFile, config_dir, data_dir
from .sysmon import SystemMonitor
from .testpattern import TestPattern
from .web import create_app

_LOGGER = logging.getLogger("avmatrix")
DEFAULT_PORT = 8088
DEFAULT_NAME = "Strelle AV Matrix"


def _tailscale_name() -> str | None:
    try:
        raw = subprocess.run(["tailscale", "status", "--json", "--peers=false"], capture_output=True, text=True, timeout=4).stdout
        name = json.loads(raw).get("Self", {}).get("DNSName", "")
        return name.rstrip(".") or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


async def run(args: argparse.Namespace) -> int:
    config = JsonFile(config_dir() / "config.json")
    state = JsonFile(data_dir() / "state.json")
    token = TokenFile(config_dir() / "token")
    token.load_or_create()
    session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
    hub = Hub(config, state, session=session)
    hub.load()
    cfg = config.data
    port = int(args.port or cfg.get("port") or DEFAULT_PORT)
    name = str(cfg.get("name") or DEFAULT_NAME)
    overrides = dict(cfg.get("addresses") or {})
    if not overrides.get("tailscale_name"):
        overrides["tailscale_name"] = await asyncio.to_thread(_tailscale_name)
    cache: dict[str, Any] = {"at": 0.0, "info": None}

    def info() -> dict[str, Any]:
        if cache["info"] is None or time.monotonic() - cache["at"] > 60:
            cache["info"] = {**addresses(port, overrides), "name": name}
            cache["at"] = time.monotonic()
        return cache["info"]

    for _ in range(30):  # beim Hochfahren des Rechners kurz auf das Netz warten (mDNS braucht die Adresse)
        if info().get("lan_ip") or args.no_mdns:
            break
        await asyncio.sleep(2)
        cache["info"] = None

    flows = FlowManager(hub, lambda: default_subnet(info().get("lan_ip")))
    discovery = None
    if not args.no_mdns and cfg.get("mdns", True):
        try:
            from .discovery import Discovery

            def dante() -> Any:
                poller = hub.pollers.get("dante")
                return poller.driver if poller else None

            def nmos() -> Any:
                poller = hub.pollers.get("nmos")
                return poller.driver if poller else None

            def nmos_changed() -> None:  # eingestecktes Gerät soll nach Sekunden erscheinen, nicht erst beim nächsten Takt
                poller = hub.pollers.get("nmos")
                if poller is not None:
                    poller.wake()

            async def http_host(host: str, mdns_name: str) -> None:
                await flows.probe_host(host, mdns_name)

            discovery = Discovery(
                # Vorgabe: nur an der Adresse des Studionetzes suchen; "all" nimmt alle Schnittstellen (zweites Netz)
                interface=None if cfg.get("mdns_interface") == "all" else (cfg.get("mdns_interface") or info().get("lan_ip")),
                ndi_registry=hub.registries["ndi"],
                on_change=hub.schedule_evaluate,
                dante=dante,
                on_http_host=http_host,
                nmos=nmos,
            )
            discovery.on_nmos_change = nmos_changed

            def feed(poller: Any) -> None:
                if poller.entry.id == "dante":
                    discovery.feed_dante(poller.driver)
                elif poller.entry.id == "nmos" and discovery.nmos_browser is not None:
                    discovery.nmos_browser.feed(poller.driver)

            hub.on_poller = feed
            await discovery.start()
        except Exception as err:  # noqa: BLE001 - ohne mDNS läuft alles andere weiter
            _LOGGER.warning("mDNS nicht verfügbar: %s", err)
            discovery = None
    await hub.start()

    preview = PreviewManager(hub.registries["ndi"], cfg.get("preview"))
    pattern = TestPattern(state, info, preview)
    monitor = SystemMonitor()
    monitor.memory_limit_mb = int(cfg.get("memory_restart_mb", 240))
    stop = asyncio.Event()
    state_flags = {"restart": False}

    def memory_limit(rss: int) -> None:
        if not state_flags["restart"] and not preview._live:  # nicht mitten in einer Live-Vorschau
            state_flags["restart"] = True
            _LOGGER.warning("Speicher %d MB über der Grenze von %d MB: Dienst startet sich neu", rss, monitor.memory_limit_mb)
            stop.set()

    monitor.on_memory_limit = memory_limit
    monitor.start()
    app = create_app(hub, token, flows, info, lambda: allowed_hosts(info(), cfg.get("allowed_hosts")), preview, pattern, monitor)
    runner = web.AppRunner(app, access_log=None, handle_signals=False, shutdown_timeout=2.0)
    await runner.setup()
    site = web.TCPSite(runner, args.host, port, reuse_address=True)
    await site.start()
    _LOGGER.info("Strelle AV Matrix Server %s läuft auf %s:%s (%s)", __version__, args.host, port, name)
    for url in info()["urls"]:
        _LOGGER.info("  %s: %s", url["label"], url["url"])
    if discovery is not None and info().get("lan_ip") and not args.no_announce:
        try:
            await discovery.announce(
                name, port, info()["hostname"], info()["lan_ip"], {"path": "/", "product": "av-matrix-server", "version": __version__}
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("mDNS-Ankündigung fehlgeschlagen: %s", err)

    if pattern.enabled:
        await asyncio.to_thread(pattern.apply)  # eingeschaltete Testbild-Quelle nach dem Neustart wieder senden

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    _LOGGER.info("Beende …")
    await hub.stop()  # zuerst sichern, was gesichert werden muss (Zustand, Einstellungen)
    for step in (discovery.stop() if discovery is not None else None, runner.cleanup(), session.close()):
        if step is None:
            continue
        try:  # offene Streams (Ereignisse, Live-Vorschau) dürfen das Beenden nicht aufhalten
            await asyncio.wait_for(step, 5)
        except (TimeoutError, Exception) as err:  # noqa: BLE001
            _LOGGER.warning("Beenden: %s", err or type(err).__name__)
    return 1 if state_flags["restart"] else 0  # 1 → systemd startet den Dienst neu (Restart=on-failure)


def _use_private_ffmpeg() -> None:
    """NDI|HX: libndi lädt FFmpeg zur Laufzeit. Liegt eine Kopie im Benutzerverzeichnis
    (deploy/install-hx-decoder.sh), muss der Suchpfad schon beim Start des Prozesses stimmen → einmal neu starten."""
    base = data_dir() / "ndi" / "ffmpeg" / "usr" / "lib"
    dirs = [str(d) for d in sorted(base.glob("*-linux-gnu*")) if d.is_dir()]
    if not dirs or os.environ.get("AVM_FFMPEG") == "1":
        return
    extra = [f"{d}{sub}" for d in dirs for sub in ("", "/pulseaudio", "/blas", "/lapack")]
    os.environ["LD_LIBRARY_PATH"] = ":".join([*extra, os.environ.get("LD_LIBRARY_PATH", "")]).rstrip(":")
    os.environ["AVM_FFMPEG"] = "1"
    os.execv(sys.executable, [sys.executable, "-m", "avmatrix", *sys.argv[1:]])


def main() -> None:
    _use_private_ffmpeg()
    parser = argparse.ArgumentParser(prog="avmatrix", description="Strelle AV Matrix Server (NDI®/Dante®-Kreuzschiene)")
    parser.add_argument("--host", default="0.0.0.0", help="Schnittstelle (Vorgabe: alle)")
    parser.add_argument("--port", type=int, default=None, help=f"Port (Vorgabe: Konfiguration oder {DEFAULT_PORT})")
    parser.add_argument("--no-mdns", action="store_true", help="kein mDNS (Suche und Ankündigung)")
    parser.add_argument("--no-announce", action="store_true", help="mDNS nur zum Suchen, den Server nicht ankündigen")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:  # zusätzlich in eine kleine, rotierende Datei (das Journal ist für den Dienstbenutzer nicht immer lesbar)
        from logging.handlers import RotatingFileHandler

        data_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
        handler = RotatingFileHandler(data_dir() / "server.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
    except OSError:
        pass
    logging.getLogger("zeroconf").setLevel(logging.WARNING)
    code = asyncio.run(run(args))
    logging.shutdown()
    os._exit(code)  # Threads der NDI-Bibliothek können das normale Beenden aufhalten


if __name__ == "__main__":
    main()
