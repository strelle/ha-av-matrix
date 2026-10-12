"""HTTP-Server: Browser-Panel, HTTP-Schnittstelle, WebSocket für die Karte, Ereignis-Stream, MCP."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from . import __version__
from .docs import llms_txt, openapi
from .flows import FlowManager, translations
from .hub import Hub, MatrixError
from .mcp import McpServer
from .netinfo import connect_urls
from .preview import MESSAGES as PREVIEW_MESSAGES
from .preview import STATE_NO_SIGNAL, STATE_OK, STATE_UNAVAILABLE, STATE_UNSUPPORTED, PreviewManager
from .store import TokenFile
from .sysmon import SystemMonitor
from .testpattern import TestPattern, qr_svg

_LOGGER = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
PUSH_DEBOUNCE = 0.2
SSE_KEEPALIVE = 25.0

HUB = web.AppKey("hub", Hub)
TOKEN = web.AppKey("token", TokenFile)
FLOWS = web.AppKey("flows", FlowManager)
MCP = web.AppKey("mcp", McpServer)
INFO = web.AppKey("info", Callable[[], dict[str, Any]])
HOSTS = web.AppKey("hosts", Callable[[], set[str]])
SOCKETS = web.AppKey("sockets", set)
PREVIEW = web.AppKey("preview", PreviewManager)
PATTERN = web.AppKey("pattern", TestPattern)
SYSMON = web.AppKey("sysmon", SystemMonitor)
COUNTERS = web.AppKey("counters", dict)
#: Nur-Lese-Bilder dürfen auch fremde Seiten im Studionetz einbetten (HA-Karte, Companion)
EMBEDDABLE = ("/api/preview.jpg", "/api/preview.mjpeg", "/api/qr.svg", "/api/testpattern.jpg")


def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda d: json.dumps(d, ensure_ascii=False))


def _fail(err: MatrixError) -> web.Response:
    return _json({"ok": False, "error": err.code, "message": err.message}, err.status)


def _host_of(value: str) -> str:
    host = value.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if ":" in host else host


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


@web.middleware
async def security(request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]):
    """Nur unter den eigenen Namen/Adressen ansprechbar; keine Schaltbefehle von fremden Webseiten.

    * ``Host`` muss eine IP-Adresse oder einer der eigenen Namen sein (gegen DNS-Rebinding).
    * Kommt die Anfrage aus einem Browser von einer fremden Seite (``Origin`` / ``Sec-Fetch-Site``),
      wird sie abgelehnt – auch GET, weil die einfachen Schalt-Adressen für Companion per GET gehen.
    """
    host = _host_of(request.headers.get("Host", ""))
    if host and not _is_ip(host) and host not in request.app[HOSTS]():
        return _json({"ok": False, "error": "forbidden", "message": "Unbekannter Host-Name"}, 403)
    origin = request.headers.get("Origin")
    if request.method == "GET" and request.path in EMBEDDABLE:
        pass
    elif origin and origin != "null":
        if _host_of(urlsplit(origin).netloc) != host:
            return _json({"ok": False, "error": "forbidden", "message": "Fremde Herkunft (Origin)"}, 403)
    elif request.headers.get("Sec-Fetch-Site") == "cross-site" and request.path.startswith(("/api", "/mcp", "/ws")):
        return _json({"ok": False, "error": "forbidden", "message": "Aufruf von fremder Webseite"}, 403)
    try:
        response = await handler(request)
    except MatrixError as err:
        return _fail(err)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


async def _params(request: web.Request) -> dict[str, Any]:
    """Parameter aus Query und (JSON- oder Formular-)Body, Body gewinnt."""
    data: dict[str, Any] = dict(request.query)
    if request.can_read_body:
        ctype = request.content_type
        if ctype == "application/json":
            try:
                body = await request.json()
            except ValueError as err:
                raise MatrixError("invalid", "Ungültiges JSON im Body") from err
            if isinstance(body, dict):
                data.update(body)
        elif ctype in ("application/x-www-form-urlencoded", "multipart/form-data"):
            data.update(await request.post())
    return data


def _panel_only(request: web.Request) -> None:
    """Schlüssel anzeigen/erneuern: nur aus dem Panel (eigener Header erzwingt bei Fremdseiten einen Preflight)."""
    if request.headers.get("X-AVM-Panel") != "1":
        raise MatrixError("invalid", "Nur aus dem Panel aufrufbar (Header X-AVM-Panel: 1).")


# ------------------------------------------------------------------ pages
async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


async def static_file(request: web.Request) -> web.StreamResponse:
    rel = request.match_info["path"]
    path = (STATIC / rel).resolve()
    if STATIC.resolve() not in path.parents or not path.is_file():
        raise web.HTTPNotFound()
    cache = "public, max-age=604800" if path.suffix in (".woff2", ".svg") else "no-cache"
    return web.FileResponse(path, headers={"Cache-Control": cache})


async def get_openapi(request: web.Request) -> web.Response:
    return _json(openapi(request.app[INFO]()))


async def get_llms(request: web.Request) -> web.Response:
    return web.Response(text=llms_txt(request.app[INFO]()), content_type="text/plain", charset="utf-8")


# -------------------------------------------------------------------- API
async def api_info(request: web.Request) -> web.Response:
    hub = request.app[HUB]
    info = request.app[INFO]()
    return _json(
        {
            **info,
            "version": __version__,
            "uptime": round(time.time() - hub.started),
            "mcp_urls": [{**u, "url": u["url"] + "mcp"} for u in info["urls"]],
            "connect": connect_urls(info),
        }
    )


async def api_state(request: web.Request) -> web.Response:
    return _json(request.app[HUB].snapshot())


async def api_status(request: web.Request) -> web.Response:
    return _json(request.app[HUB].status())


async def api_choices(request: web.Request) -> web.Response:
    return _json(request.app[HUB].choices())


async def api_history(request: web.Request) -> web.Response:
    return _json({"events": list(request.app[HUB].events)})


async def api_route(request: web.Request) -> web.Response:
    hub = request.app[HUB]
    p = await _params(request)
    dest = hub.resolve_destination(p.get("dest") or p.get("destination"))
    raw = p.get("source")
    source = hub.resolve_source(dest.protocol, raw if isinstance(raw, str) else None)
    event = await hub.route(dest.uid, source, origin=str(p.get("origin") or "http"))
    return _json({"ok": True, "destination": dest.uid, "source": source, "previous_source": event["previous_source"]})


async def api_salvo(request: web.Request) -> web.Response:
    hub = request.app[HUB]
    p = await _params(request)
    routes = p.get("routes")
    if not isinstance(routes, list) or not routes:
        raise MatrixError("invalid", "routes: [{destination, source}] fehlt")
    plan = []
    for item in routes:
        dest = hub.resolve_destination(item.get("dest") or item.get("destination"))
        plan.append((dest.uid, hub.resolve_source(dest.protocol, item.get("source"))))
    return _json({"ok": True, **await hub.salvo(plan, origin="http")})


async def api_undo(request: web.Request) -> web.Response:
    hub = request.app[HUB]
    p = await _params(request)
    target = p.get("dest") or p.get("destination")
    if target:
        dest = hub.resolve_destination(target)
        event = await hub.undo(dest.uid)
        return _json({"ok": True, "restored": [{"destination": dest.uid, "source": event["source"]}]})
    return _json({"ok": True, **await hub.undo_last()})


def _lock(locked: bool) -> Callable[[web.Request], Awaitable[web.Response]]:
    async def handler(request: web.Request) -> web.Response:
        hub = request.app[HUB]
        p = await _params(request)
        dest = hub.resolve_destination(p.get("dest") or p.get("destination"))
        hub.set_lock(dest.uid, locked)
        return _json({"ok": True, "destination": dest.uid, "locked": locked})

    return handler


async def api_label(request: web.Request) -> web.Response:
    hub = request.app[HUB]
    p = await _params(request)
    tags = p.get("tags") if isinstance(p.get("tags"), list) else None
    if p.get("destination") or p.get("dest"):
        dest = hub.resolve_destination(p.get("dest") or p.get("destination"))
        return _json({"ok": True, **hub.set_destination_label(dest.uid, p.get("label"), tags)})
    if not p.get("source") or not p.get("protocol"):
        raise MatrixError("invalid", "protocol + source oder destination angeben")
    if "type" in p:  # Gerätetyp der Quelle von Hand (camera | computer | encoder | testpattern | unknown | auto)
        entry = hub.set_source_type(str(p["protocol"]), str(p["source"]), p.get("type"))
        if "label" not in p and "tags" not in p:
            return _json({"ok": True, **entry})
    return _json({"ok": True, **hub.set_label(str(p["protocol"]), str(p["source"]), p.get("label"), tags)})


async def api_source_forget(request: web.Request) -> web.Response:
    p = await _params(request)
    request.app[HUB].forget_source(str(p.get("protocol") or "ndi"), str(p.get("source") or ""))
    return _json({"ok": True})


async def api_refresh(request: web.Request) -> web.Response:
    request.app[HUB].refresh_sources()
    return _json({"ok": True})


# presets
async def api_presets(request: web.Request) -> web.Response:
    return _json({"presets": request.app[HUB].presets_view()})


async def api_preset_save(request: web.Request) -> web.Response:
    hub = request.app[HUB]
    p = await _params(request)
    preset_id = request.match_info.get("id")
    if preset_id is not None:
        preset_id = hub.get_preset(preset_id)["id"]
    name = str(p.get("name") or (hub.presets[preset_id]["name"] if preset_id else ""))
    if p.get("routes"):
        return _json({"ok": True, "preset": hub.save_preset(name, p["routes"], preset_id=preset_id)})
    if p.get("destinations"):
        return _json({"ok": True, "preset": hub.snapshot_preset(name, p["destinations"], preset_id=preset_id)})
    if preset_id:  # nur umbenennen
        return _json({"ok": True, "preset": hub.save_preset(name, hub.presets[preset_id]["routes"], preset_id=preset_id)})
    raise MatrixError("invalid", "routes oder destinations angeben")


async def api_preset_delete(request: web.Request) -> web.Response:
    request.app[HUB].delete_preset(request.match_info["id"])
    return _json({"ok": True})


async def api_preset_recall(request: web.Request) -> web.Response:
    hub = request.app[HUB]
    p = await _params(request)
    target = request.match_info.get("id") or p.get("preset") or p.get("name") or p.get("id")
    return _json({"ok": True, **await hub.recall_preset(str(target or ""), origin=str(p.get("origin") or "http"))})


# devices
async def api_devices(request: web.Request) -> web.Response:
    return _json({"devices": request.app[HUB].devices()})


async def api_device_delete(request: web.Request) -> web.Response:
    await request.app[HUB].remove_entry(request.match_info["id"])
    return _json({"ok": True})


async def api_device_update(request: web.Request) -> web.Response:
    hub = request.app[HUB]
    p = await _params(request)
    kwargs: dict[str, Any] = {}
    if "title" in p:
        kwargs["title"] = p["title"]
    from .flows import parse_hosts

    options: dict[str, Any] = {}
    if "static_hosts" in p:
        options["static_hosts"] = parse_hosts(p["static_hosts"])
    if "scan_interval" in p:
        options["scan_interval"] = max(2.0, min(60.0, float(p["scan_interval"])))
    if "registries" in p:  # ST 2110: IS-04-Registry von Hand, z. B. http://192.0.2.5:8010
        options["registries"] = parse_hosts(p["registries"]) if not isinstance(p["registries"], list) else [str(x) for x in p["registries"]]
    for flag in ("audio_breakaway", "check_compat", "enable_senders"):
        if flag in p:
            options[flag] = p[flag] if isinstance(p[flag], bool) else str(p[flag]).lower() in ("1", "true", "on", "ein", "yes")
    if options:
        kwargs["options"] = options
    entry = await hub.update_entry(request.match_info["id"], **kwargs)
    return _json({"ok": True, "id": entry.id})


async def api_device_forget(request: web.Request) -> web.Response:
    """Ein nicht antwortendes Gerät eines Netzwerk-Eintrags (Dante, ST 2110) aus der Liste nehmen."""
    p = await _params(request)
    request.app[HUB].forget_network_device(request.match_info["id"], str(p.get("device") or ""))
    return _json({"ok": True})


# ----------------------------------------------------- ST 2110 prüfen (NMOS)
def _nmos_findings(stats: dict[str, Any], diag: dict[str, Any]) -> list[dict[str, str]]:
    """Was am Ergebnis auffällt – in Klartext, mit Einstufung (ok | hinweis | problem)."""
    devices = diag.get("devices", [])
    out: list[dict[str, str]] = []
    if stats.get("mdns_error"):
        out.append({"level": "problem", "text": f"mDNS-Suche nicht möglich: {stats['mdns_error']}"})
    if not devices:
        if stats.get("announced") or diag.get("pending"):
            out.append({"level": "problem", "text": f"{stats.get('announced', 0)} Gerät(e) haben sich angekündigt, aber keines antwortet auf der "
                        f"NMOS-Schnittstelle: {', '.join(diag.get('pending', [])) or '–'}"})  # fmt: skip
        else:
            out.append({"level": "hinweis", "text": "Keine NMOS-Geräte gefunden. Das ist richtig, solange noch kein ST-2110-Gerät am Netz hängt. "
                        "Sonst: Gerät eingeschaltet und im selben Netz/VLAN wie dieser Rechner? Andernfalls die Adresse von Hand eintragen."})  # fmt: skip
        return out
    online = [d for d in devices if d["online"]]
    for d in devices:
        if not d["online"]:
            out.append({"level": "problem", "text": f"{d['name']} ({d['host']}) antwortet nicht: {d.get('last_error') or 'keine Antwort'}"})
    unlocked = [d["name"] for d in online if d.get("ptp") and d["ptp"].get("locked") is False]
    if unlocked:
        out.append({"level": "problem", "text": f"PTP nicht eingerastet: {', '.join(unlocked)} – ohne gemeinsamen Takt gibt es kein stabiles Bild."})
    masters = sorted({d["ptp"]["grandmaster"] for d in online if d.get("ptp") and d["ptp"].get("grandmaster")})
    if len(masters) > 1:
        out.append({"level": "problem", "text": f"Die Geräte hören auf verschiedene PTP-Taktgeber ({', '.join(masters)})."})
    no_ptp = [d["name"] for d in online if not d.get("ptp")]
    if no_ptp:
        out.append({"level": "hinweis", "text": f"Kein PTP-Zustand gemeldet: {', '.join(no_ptp)}"})
    for d in online:
        loose = [n for n, g in {**d.get("sources", {}), **d.get("destinations", {})}.items() if not g.get("hinted", True)]
        if loose and (len(d.get("sources", {})) > 1 or len(d.get("destinations", {})) > 1):
            out.append({"level": "hinweis", "text": f"{d['name']}: Bild/Ton/Zusatzdaten wurden über die Namen zusammengefasst (keine Gruppen-Angabe des Geräts) – "
                        "bitte prüfen, ob die Ein-/Ausgänge stimmen."})  # fmt: skip
        if not d.get("sources") and not d.get("destinations"):
            out.append({"level": "problem", "text": f"{d['name']} meldet weder Sender noch Empfänger."})
        off = [s["label"] for s in d.get("senders", []) if s.get("active") is False]
        if off:
            out.append({"level": "hinweis", "text": f"{d['name']}: {len(off)} Sender sind ausgeschaltet – sie werden beim Schalten eingeschaltet."})
        if not d.get("is04_subscription_reliable", True):
            out.append({"level": "hinweis", "text": f"{d['name']} zeigt den Schaltzustand in IS-04 nicht zuverlässig; er wird direkt über IS-05 gelesen."})
    if not any(f["level"] == "problem" for f in out):
        out.insert(0, {"level": "ok", "text": f"{len(online)} Gerät(e) antworten, nichts Auffälliges."})
    return out


async def api_nmos_check(request: web.Request) -> web.Response:
    """„ST 2110 prüfen“: sucht NMOS-Geräte und liest, was sie melden. Schaltet nichts (wie ``nmos-check``)."""
    import argparse

    from . import nmos_check

    hub = request.app[HUB]
    entry = hub.entries.get("nmos")
    options = entry.options if entry else {}
    args = argparse.Namespace(
        host=list(options.get("static_hosts", [])), registry=list(options.get("registries", [])), no_mdns=False,
        interface=request.app[INFO]().get("lan_ip"), timeout=5.0, audio=False, force=False,
    )  # fmt: skip
    driver, stats = await nmos_check.discover(args, hub.session)
    diag = json.loads(json.dumps(driver.diagnostics(), default=str))
    driver.close()
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    if request.query.get("raw") in ("1", "true"):  # Rohdaten für die Fehlersuche, als Datei
        body = json.dumps({"time": stamp, "discovery": stats, **diag}, ensure_ascii=False, indent=2)
        return web.Response(text=body, content_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="nmos-check-{stamp[:19].replace(":", "")}.json"', "Cache-Control": "no-store"})  # fmt: skip
    devices = [
        {
            "name": d["name"], "host": d["host"], "port": d["port"], "online": d["online"], "manufacturer": d["manufacturer"],
            "model": d["model"], "device_type": d["device_type"], "icon_key": d["icon_key"], "api": d["api"], "found_via":
            "mdns" if d["mdns"] else "registry" if d["registry"] else "static", "ptp": d["ptp"], "last_error": d["last_error"],
            "sources": [{"name": n, "essences": list(g.get("layers", {})), "grouped_by_device": bool(g.get("hinted"))} for n, g in d["sources"].items()],
            "destinations": [{"name": n, "essences": list(g.get("layers", {})), "grouped_by_device": bool(g.get("hinted"))} for n, g in d["destinations"].items()],
            "senders": len(d["senders"]), "receivers": len(d["receivers"]),
        }
        for d in diag["devices"]
    ]  # fmt: skip
    return _json(
        {
            "ok": True,
            "time": stamp,
            "configured": entry is not None,
            "discovery": stats,
            "registries": diag.get("registries", {}),
            "pending": diag.get("pending", []),
            "devices": devices,
            "findings": _nmos_findings(stats, diag),
            "note": "Es wurde nichts geschaltet oder verändert.",
        }
    )


# token
async def api_token(request: web.Request) -> web.Response:
    _panel_only(request)
    return _json({"token": request.app[TOKEN].token}, 200)


async def api_token_rotate(request: web.Request) -> web.Response:
    _panel_only(request)
    token = request.app[TOKEN].rotate()
    _LOGGER.info("Zugangsschlüssel wurde erneuert")
    return _json({"token": token})


# ---------------------------------------------------------- NDI-Vorschau
PREVIEW_STATUS = {STATE_UNAVAILABLE: 501, STATE_NO_SIGNAL: 503, STATE_UNSUPPORTED: 415}


def _preview_source(request: web.Request) -> str:
    text = request.query.get("source", "").strip()
    if not text:
        raise MatrixError("invalid", "source fehlt")
    hub = request.app[HUB]
    for key, registry in hub.registries.items():  # Quelle eines Protokolls ohne Vorschau (ST 2110, Dante)?
        if key != "ndi" and registry.get(text) is not None:
            raise NoPreview(key)
    source = request.app[HUB].resolve_source("ndi", text)
    if source is None:
        raise MatrixError("invalid", "source fehlt")
    return source


class NoPreview(Exception):
    """Die Quelle gehört zu einem Protokoll, für das es keine Vorschau gibt – kein Fehler, eine Eigenschaft."""


def _no_preview(protocol: str) -> web.Response:
    response = _json({"ok": False, "error": "no_preview", "protocol": protocol,
                      "message": "Für dieses Protokoll gibt es keine Vorschau (das Signal wird nicht empfangen)."}, 404)  # fmt: skip
    response.headers["X-Preview-State"] = "no_preview"
    response.headers["Cache-Control"] = "no-store"
    return response


def _preview_error(state: str) -> web.Response:
    response = _json({"ok": False, "error": state, "message": PREVIEW_MESSAGES.get(state, state)}, PREVIEW_STATUS.get(state, 404))
    response.headers["X-Preview-State"] = state
    response.headers["Cache-Control"] = "no-store"
    return response


def _int(request: web.Request, name: str) -> int | None:
    try:
        return int(request.query[name]) if request.query.get(name) else None
    except ValueError:
        raise MatrixError("invalid", f"{name} muss eine Zahl sein") from None


async def api_preview_status(request: web.Request) -> web.Response:
    preview = request.app[PREVIEW]
    data = preview.status()
    if request.query.get("source"):
        try:
            source = _preview_source(request)
            data["source"] = {"id": source, "state": preview.source_state(source)[0]}
        except NoPreview as err:
            data["source"] = {"id": request.query["source"], "state": "no_preview", "protocol": str(err)}
    return _json(data)


async def api_preview_jpeg(request: web.Request) -> web.Response:
    """Standbild einer NDI-Quelle als JPEG (aus dem Proxy-Stream, wenige Sekunden zwischengespeichert)."""
    try:
        source = _preview_source(request)
    except NoPreview as err:
        return _no_preview(str(err))
    thumb = await request.app[PREVIEW].thumbnail(source, _int(request, "w"))
    if thumb.state != STATE_OK or thumb.jpeg is None:
        return _preview_error(thumb.state)
    return web.Response(
        body=thumb.jpeg,
        content_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Preview-State": STATE_OK,
            "X-Preview-Age": f"{thumb.age:.1f}",
            "X-Preview-Size": f"{thumb.width}x{thumb.height}",
            "X-Preview-Origin": thumb.origin,
            "Access-Control-Expose-Headers": "X-Preview-State, X-Preview-Age, X-Preview-Size, X-Preview-Origin",
        },
    )


async def api_preview_mjpeg(request: web.Request) -> web.StreamResponse:
    """Fortlaufende Live-Vorschau (MJPEG, ``multipart/x-mixed-replace``). Endet, wenn die Quelle wegfällt."""
    preview = request.app[PREVIEW]
    try:
        source = _preview_source(request)
    except NoPreview as err:
        return _no_preview(str(err))
    fps = request.query.get("fps")
    try:
        rx, queue = preview.subscribe(source, _int(request, "w"), float(fps) if fps else None)
    except LookupError as err:
        return _preview_error(str(err))
    except ValueError:
        raise MatrixError("invalid", "fps muss eine Zahl sein") from None
    response = web.StreamResponse(
        headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=avmframe",
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "X-Preview-State": STATE_OK,
        }
    )
    try:
        await response.prepare(request)
        while True:
            try:
                jpeg = await asyncio.wait_for(queue.get(), 8.0)
            except TimeoutError:
                break  # kein Bild mehr: Stream beenden statt ein altes Bild stehen zu lassen
            if jpeg is None:
                break
            await response.write(
                b"--avmframe\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
            )
    except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        preview.unsubscribe(rx, queue)
    return response


# ------------------------------------------------------ Systemauslastung
def system_status(app: web.Application, *, detail: bool = True) -> dict[str, Any]:
    """Alles für die Seite „System“ – auch für das MCP-Werkzeug ``get_system_status``."""
    hub, monitor, preview, pattern = app[HUB], app[SYSMON], app[PREVIEW], app[PATTERN]
    monitor.watch(detail)
    if not monitor.current:
        monitor.sample()
    if not detail:
        return {"ok": True, **monitor.summary()}
    now = time.time()
    counters = app[COUNTERS]
    pstat = preview.status() if preview._lib_tried else {"available": None, "live": [], "receivers_open": 0, "receivers_opened_total": 0, "limits": {}}
    devices = []
    extra_warnings: list[dict[str, str]] = []
    for dev in hub.devices():
        poller = hub.pollers.get(dev["id"])
        age = round(now - poller.last_poll, 1) if poller and poller.last_poll else None
        if dev.get("network"):
            subs = dev.get("devices", [])
            if dev["driver"] == "nmos" and not subs:
                continue  # ST 2110 ohne Geräte: unauffällig bleiben
            devices.append({"name": dev.get("model") or dev["name"], "protocol": dev["protocol"], "online": True,
                            "detail": f"{sum(1 for s in subs if s['online'])} von {len(subs)} Geräten erreichbar",
                            "last_poll_s": age, "error": next((s["last_error"] for s in subs if s.get("last_error")), None)})  # fmt: skip
            if dev["driver"] == "nmos":  # je NMOS-Node eine Zeile: erreichbar? PTP eingerastet?
                for sub in subs:
                    ptp = sub.get("ptp")
                    text = "PTP eingerastet" if ptp and ptp.get("locked") else "PTP NICHT eingerastet" if ptp else "kein PTP-Zustand"
                    devices.append({"name": sub["name"], "protocol": dev["protocol"], "online": sub["online"], "ptp": ptp,
                                    "detail": f"{sub.get('device_type_title') or 'ST-2110-Gerät'} · {text}", "last_poll_s": age, "error": sub.get("last_error")})  # fmt: skip
                unlocked = [s["name"] for s in subs if s["online"] and s.get("ptp") and s["ptp"].get("locked") is False]
                masters = sorted({s["ptp"]["grandmaster"] for s in subs if s["online"] and s.get("ptp") and s["ptp"].get("grandmaster")})
                if unlocked:
                    extra_warnings.append({"code": "ptp_unlocked", "text": f"PTP nicht eingerastet: {', '.join(unlocked)}"})
                if len(masters) > 1:
                    extra_warnings.append({"code": "ptp_split", "text": "ST-2110-Geräte hören auf verschiedene PTP-Taktgeber"})
        else:
            devices.append({"name": dev["name"], "online": dev["online"], "detail": dev.get("model"), "last_poll_s": age, "error": dev.get("last_error")})
    return {
        "ok": True,
        **monitor.current,
        "warnings": [*monitor.warnings(), *extra_warnings],
        "activity": {
            "ndi_receivers": [
                {"source": rx["source"], "kind": "live", "bandwidth": "lowest", "fps": preview.live_fps, "seconds": rx["seconds"], "viewers": rx["clients"], "frames": rx["frames"]}
                for rx in pstat["live"]
            ],
            "ndi_receivers_open": pstat["receivers_open"],
            "ndi_stills_total": pstat["receivers_opened_total"],
            "preview_available": pstat["available"],
            "testpattern": {k: pattern.status()[k] for k in ("enabled", "running", "connections", "frames_sent")},
            "clients": {
                "panels": len(app[SOCKETS]),
                "event_streams": counters["sse"],
                "mcp_calls": counters["mcp"],
                "mcp_last_s": round(now - counters["mcp_at"]) if counters["mcp_at"] else None,
            },
            "devices": devices,
            "routes": [{"time": e["time"], "origin": e["origin"], "destination": e["destination_name"], "source": e["source"]} for e in list(hub.events)[:12]],
            "errors": [{**e, "time": datetime.fromtimestamp(e["time"], UTC).isoformat()} for e in monitor.errors.items],
        },
        "history": list(monitor.history),
        "monitor": {"interval_s": monitor.interval(), "sample_cost_ms": monitor.sample_cost_ms, "samples": monitor.samples},
    }


async def api_system(request: web.Request) -> web.Response:
    return _json(system_status(request.app, detail=request.query.get("summary") not in ("1", "true")))


# ------------------------------------------------- QR-Code und Testbild
async def api_qr(request: web.Request) -> web.Response:
    """QR-Code zum Verbinden als SVG. ``target``: Art der Adresse (Vorgabe: die erste aus ``connect``)."""
    urls = connect_urls(request.app[INFO]())
    target = request.query.get("target")
    hit = next((u for u in urls if u["kind"] == target), None) if target else (urls[0] if urls else None)
    if hit is None:
        raise MatrixError("invalid", "Keine Adresse dieser Art vorhanden")
    return web.Response(text=qr_svg(hit["url"]), content_type="image/svg+xml", headers={"Cache-Control": "no-store", "X-QR-Url": hit["url"]})


async def api_pattern(request: web.Request) -> web.Response:
    pattern = request.app[PATTERN]
    if request.method != "GET":
        p = await _params(request)
        if "enabled" not in p:
            raise MatrixError("invalid", "enabled fehlt (true/false)")
        value = p["enabled"]
        pattern.set_enabled(value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "ein", "yes"))
    return _json({"ok": True, **pattern.status()})


async def api_pattern_jpeg(request: web.Request) -> web.Response:
    data = await asyncio.to_thread(request.app[PATTERN].jpeg)
    return web.Response(body=data, content_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---------------------------------------------- HA-kompatible Flow-Schnittstelle (Karte: "Gerät hinzufügen")
async def flow_start(request: web.Request) -> web.Response:
    return _json(request.app[FLOWS].start())


async def flow_get(request: web.Request) -> web.Response:
    return _json(await request.app[FLOWS].get(request.match_info["id"]))


async def flow_post(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except ValueError:
        body = {}
    return _json(await request.app[FLOWS].submit(request.match_info["id"], body if isinstance(body, dict) else {}))


async def flow_delete(request: web.Request) -> web.Response:
    request.app[FLOWS].delete(request.match_info["id"])
    return _json({"message": "Flow aborted"})


# -------------------------------------------------------------- SSE stream
def _choices_rev(hub: Hub) -> str:
    if "choices_rev" not in hub._memo:
        hub._memo["choices_rev"] = hashlib.sha1(json.dumps(hub.choices(), sort_keys=True).encode()).hexdigest()[:12]
    return hub._memo["choices_rev"]


async def api_events(request: web.Request) -> web.StreamResponse:
    """Server-Sent Events: ``status`` bei jeder Änderung (kompakter Zustand + Kennung der Auswahllisten)."""
    hub = request.app[HUB]
    response = web.StreamResponse(
        headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
    await response.prepare(request)
    changed = asyncio.Event()
    changed.set()
    remove = hub.add_listener(changed.set)
    request.app[COUNTERS]["sse"] += 1
    last: str | None = None
    try:
        while True:
            try:
                await asyncio.wait_for(changed.wait(), SSE_KEEPALIVE)
            except TimeoutError:
                await response.write(b": ping\n\n")
                continue
            await asyncio.sleep(PUSH_DEBOUNCE)
            changed.clear()
            payload = json.dumps({**hub.status(), "choices_rev": _choices_rev(hub)}, ensure_ascii=False, sort_keys=True)
            if payload != last:
                last = payload
                await response.write(f"event: status\ndata: {payload}\n\n".encode())
    except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        remove()
        request.app[COUNTERS]["sse"] -= 1
    return response


# -------------------------------------------------------------- WebSocket
async def _service(hub: Hub, service: str, data: dict[str, Any]) -> None:
    """Dienste der HA-Integration (``av_matrix.route`` …), wie sie die Karte aufruft."""

    def targets() -> list[str]:
        raw = data.get("destination") or []
        return [hub.resolve_destination(t).uid for t in ([raw] if isinstance(raw, str) else raw)]

    if service == "route":
        for uid in targets():
            dest = hub.destinations[uid]
            await hub.route(uid, hub.resolve_source(dest.protocol, data.get("source")), origin="panel")
    elif service == "salvo":
        plan = []
        for item in data.get("routes") or []:
            dest = hub.resolve_destination(item.get("destination"))
            plan.append((dest.uid, hub.resolve_source(dest.protocol, item.get("source"))))
        await hub.salvo(plan, origin="salvo")
    elif service in ("lock", "unlock"):
        for uid in targets():
            hub.set_lock(uid, service == "lock")
    elif service == "undo":
        for uid in targets():
            await hub.undo(uid)
    elif service == "refresh_sources":
        hub.refresh_sources()
    else:
        raise MatrixError("invalid", f"Unbekannter Dienst {service!r}")


async def websocket(request: web.Request) -> web.StreamResponse:
    """Spricht das Protokoll, das die Karte von Home Assistant erwartet (Befehle mit ``id`` und ``type``)."""
    hub, flows = request.app[HUB], request.app[FLOWS]
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=1 << 20)
    await ws.prepare(request)
    request.app[SOCKETS].add(ws)
    subs: dict[int, Callable[[], None]] = {}
    tasks: set[asyncio.Task[Any]] = set()

    async def send(payload: dict[str, Any]) -> None:
        if not ws.closed:
            try:
                await ws.send_str(json.dumps(payload, ensure_ascii=False))
            except (ConnectionResetError, RuntimeError):
                pass

    def spawn(coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def subscribe_state(msg_id: int) -> None:
        state: dict[str, Any] = {"pending": False, "last": None, "text": None}

        async def push() -> None:
            await asyncio.sleep(PUSH_DEBOUNCE)
            state["pending"] = False
            snap = hub.snapshot()
            if snap is not state["last"]:
                text = hub._memo.get("snapshot_json")
                if text is None:  # einmal je Stand serialisieren, für alle Panels
                    text = hub._memo["snapshot_json"] = json.dumps(snap, ensure_ascii=False)
                if text != state["text"]:
                    state["text"] = text
                    if not ws.closed:
                        try:
                            await ws.send_str(f'{{"id": {msg_id}, "type": "event", "event": {text}}}')
                        except (ConnectionResetError, RuntimeError):
                            pass
                state["last"] = snap

        def changed() -> None:
            if not state["pending"]:
                state["pending"] = True
                spawn(push())

        subs[msg_id] = hub.add_listener(changed)
        changed()

    async def handle(msg: dict[str, Any]) -> None:
        msg_id, kind = msg.get("id"), msg.get("type")
        try:
            result: Any = None
            if kind == "av_matrix/subscribe":
                await send({"id": msg_id, "type": "result", "success": True, "result": None})
                subscribe_state(msg_id)
                return
            if kind == "av_matrix/state":
                result = hub.snapshot()
            elif kind == "subscribe_events":
                subs[msg_id] = hub.add_event_listener(
                    lambda ev: spawn(
                        send(
                            {
                                "id": msg_id,
                                "type": "event",
                                "event": {"event_type": "av_matrix_routed", "data": ev, "time_fired": ev["time"], "context": {}},
                            }
                        )
                    )
                )
            elif kind == "config_entries/flow/subscribe":
                subs[msg_id] = flows.add_listener(lambda: spawn(send({"id": msg_id, "type": "event", "event": []})))
            elif kind == "unsubscribe_events":
                remove = subs.pop(msg.get("subscription"), None)
                if remove:
                    remove()
            elif kind == "call_service":
                await _service(hub, str(msg.get("service")), msg.get("service_data") or {})
            elif kind == "av_matrix/label":
                tags = msg.get("tags")
                if msg.get("kind") == "destination":
                    result = hub.set_destination_label(str(msg.get("destination")), msg.get("label"), tags)
                else:
                    result = hub.set_label(str(msg.get("protocol")), str(msg.get("source") or ""), msg.get("label"), tags)
            elif kind == "av_matrix/discovered":
                result = {"flows": flows.discovered()}
            elif kind == "config_entries/ignore_flow":
                flows.ignore(str(msg.get("flow_id")))
            elif kind == "frontend/get_translations":
                result = {"resources": translations(str(msg.get("language") or "de"))}
            elif kind == "config/auth/list":
                result = []
            elif kind == "ping":
                await send({"id": msg_id, "type": "pong"})
                return
            else:
                await send(
                    {"id": msg_id, "type": "result", "success": False, "error": {"code": "unknown_command", "message": str(kind)}}
                )
                return
            await send({"id": msg_id, "type": "result", "success": True, "result": result})
        except MatrixError as err:
            await send({"id": msg_id, "type": "result", "success": False, "error": {"code": err.code, "message": err.message}})
        except Exception:  # noqa: BLE001
            _LOGGER.exception("WebSocket-Befehl %s fehlgeschlagen", kind)
            await send(
                {"id": msg_id, "type": "result", "success": False, "error": {"code": "unknown_error", "message": "Interner Fehler"}}
            )

    try:
        async for raw in ws:
            if raw.type is not WSMsgType.TEXT:
                continue
            try:
                msg = json.loads(raw.data)
            except ValueError:
                continue
            if isinstance(msg, dict) and isinstance(msg.get("id"), int):
                spawn(handle(msg))
    finally:
        request.app[SOCKETS].discard(ws)
        for remove in subs.values():
            remove()
        for task in list(tasks):
            task.cancel()
    return ws


# -------------------------------------------------------------------- MCP
async def mcp_post(request: web.Request) -> web.Response:
    token: TokenFile = request.app[TOKEN]
    auth = request.headers.get("Authorization", "")
    authorized = False
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() != "bearer" or not token.check(value.strip()):
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Zugangsschlüssel ungültig"}},
                status=401,
                headers={"WWW-Authenticate": 'Bearer realm="av-matrix", error="invalid_token"'},
            )
        authorized = True
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status=400)
    server: McpServer = request.app[MCP]
    request.app[COUNTERS]["mcp"] += 1
    request.app[COUNTERS]["mcp_at"] = time.time()
    if isinstance(body, list):
        answers = [a for a in [await server.handle(m, authorized=authorized) for m in body] if a is not None]
        return _json(answers) if answers else web.Response(status=202)
    answer = await server.handle(body, authorized=authorized)
    if answer is None:
        return web.Response(status=202)
    return _json(answer)


async def mcp_other(request: web.Request) -> web.Response:
    return web.Response(status=405, headers={"Allow": "POST"}, text="Nur POST (Streamable HTTP ohne Server-Stream).")


# -------------------------------------------------------------------- app
def create_app(
    hub: Hub,
    token: TokenFile,
    flows: FlowManager,
    info: Callable[[], dict[str, Any]],
    hosts: Callable[[], set[str]],
    preview: PreviewManager | None = None,
    pattern: TestPattern | None = None,
    monitor: SystemMonitor | None = None,
) -> web.Application:
    app = web.Application(middlewares=[security], client_max_size=1 << 20)
    app[HUB], app[TOKEN], app[FLOWS], app[INFO], app[HOSTS] = hub, token, flows, info, hosts
    app[PREVIEW] = preview or PreviewManager(hub.registries["ndi"], {"enabled": False})
    pv = app[PREVIEW]

    def preview_info() -> dict[str, Any]:
        tried = pv._lib_tried
        return {
            "configured": pv.enabled,
            "available": None if not tried else pv.available,  # None = noch nicht benutzt (die Bibliothek lädt beim ersten Bild)
            "reason": pv._lib_error if tried and not pv.available else None,
            "still_url": "/api/preview.jpg",
            "stream_url": "/api/preview.mjpeg",
            "status_url": "/api/preview",
        }

    hub.preview_info = preview_info
    app[PATTERN] = pattern or TestPattern(hub.state, info, app[PREVIEW])
    app[SYSMON] = monitor or SystemMonitor()
    app[COUNTERS] = {"sse": 0, "mcp": 0, "mcp_at": 0.0}
    app[MCP] = McpServer(hub, app[PREVIEW], info, lambda: system_status(app))
    app[SOCKETS] = set()
    r = app.router
    r.add_get("/", index)
    r.add_get("/static/{path:.+}", static_file)
    r.add_get("/openapi.json", get_openapi)
    r.add_get("/llms.txt", get_llms)
    r.add_get("/ws", websocket)
    r.add_get("/api/info", api_info)
    r.add_get("/api/state", api_state)
    r.add_get("/api/status", api_status)
    r.add_get("/api/choices", api_choices)
    r.add_get("/api/history", api_history)
    r.add_get("/api/events", api_events)
    r.add_get("/api/preview", api_preview_status)
    r.add_get("/api/preview.jpg", api_preview_jpeg)
    r.add_get("/api/preview.mjpeg", api_preview_mjpeg)
    r.add_get("/api/system", api_system)
    r.add_get("/api/qr.svg", api_qr)
    r.add_get("/api/testpattern", api_pattern)
    r.add_post("/api/testpattern", api_pattern)
    r.add_get("/api/testpattern.jpg", api_pattern_jpeg)
    for method in ("GET", "POST"):  # GET-Varianten für Companions generisches HTTP-Modul und Lesezeichen
        r.add_route(method, "/api/route", api_route)
        r.add_route(method, "/api/undo", api_undo)
        r.add_route(method, "/api/lock", _lock(True))
        r.add_route(method, "/api/unlock", _lock(False))
        r.add_route(method, "/api/preset/recall", api_preset_recall)
        r.add_route(method, "/api/presets/{id}/recall", api_preset_recall)
    r.add_post("/api/salvo", api_salvo)
    r.add_post("/api/label", api_label)
    r.add_post("/api/refresh", api_refresh)
    r.add_post("/api/source/forget", api_source_forget)
    r.add_get("/api/presets", api_presets)
    r.add_post("/api/presets", api_preset_save)
    r.add_put("/api/presets/{id}", api_preset_save)
    r.add_delete("/api/presets/{id}", api_preset_delete)
    r.add_get("/api/devices", api_devices)
    r.add_patch("/api/devices/{id}", api_device_update)
    r.add_delete("/api/devices/{id}", api_device_delete)
    r.add_post("/api/devices/{id}/forget", api_device_forget)
    r.add_get("/api/nmos/check", api_nmos_check)
    r.add_get("/api/token", api_token)
    r.add_post("/api/token/rotate", api_token_rotate)
    r.add_post("/api/ha/config/config_entries/flow", flow_start)
    r.add_get("/api/ha/config/config_entries/flow/{id}", flow_get)
    r.add_post("/api/ha/config/config_entries/flow/{id}", flow_post)
    r.add_delete("/api/ha/config/config_entries/flow/{id}", flow_delete)
    r.add_post("/mcp", mcp_post)
    r.add_route("*", "/mcp", mcp_other)

    async def close_sockets(app: web.Application) -> None:
        for ws in list(app[SOCKETS]):
            await ws.close(code=1001, message=b"server shutdown")
        await asyncio.to_thread(app[PATTERN].close)
        await app[PREVIEW].close()

    app.on_shutdown.append(close_sockets)
    return app
