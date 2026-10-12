"""Maschinenlesbare Beschreibung der HTTP-Schnittstelle: OpenAPI 3.1 (``/openapi.json``) und ``/llms.txt``."""

from __future__ import annotations

from typing import Any

from . import __version__

_DEST = {"name": "dest", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Ziel: id, Label oder Name"}
_OK = {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object"}}}}}
_ERR = {
    "403": {"description": "Ziel ist fest gesperrt (Sperrliste) oder Aufruf von fremder Webseite"},
    "404": {"description": "Ziel / Preset unbekannt"},
    "423": {"description": "Ziel ist gesperrt"},
    "502": {"description": "Gerät hat das Schalten abgelehnt"},
}


def _op(summary: str, params: list[dict[str, Any]] | None = None, *, write: bool = False, body: bool = False) -> dict[str, Any]:
    op: dict[str, Any] = {"summary": summary, "responses": {**_OK, **(_ERR if write else {})}}
    if params:
        op["parameters"] = params
    if body:
        op["requestBody"] = {"required": False, "content": {"application/json": {"schema": {"type": "object"}}}}
    return op


def _q(name: str, description: str, required: bool = False) -> dict[str, Any]:
    return {"name": name, "in": "query", "required": required, "schema": {"type": "string"}, "description": description}


def openapi(info: dict[str, Any]) -> dict[str, Any]:
    source = _q("source", "Quelle: id oder Label. Leer, 'None' oder 'Aus' trennt die Verbindung.", True)
    route = _op("Verbindung setzen (Quelle auf Ziel)", [_DEST, source], write=True, body=True)
    undo = _op("Rückgängig: ohne dest die letzte Aktion, mit dest die vorherige Quelle dieses Ziels", [{**_DEST, "required": False}], write=True)
    recall = _op("Preset abrufen", [_q("preset", "id oder Name des Presets", True)], write=True)
    pid = {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Strelle AV Matrix Server",
            "version": __version__,
            "description": (
                "Kreuzschiene für NDI® (Video), Dante® (Audio) und ST 2110 (über NMOS). Lesen und Schalten im Studionetz ohne Anmeldung; "
                "Schalt-Adressen gehen als GET und POST (Parameter in der Query oder als JSON-Body). "
                "Fest geschützte Ziele (Feld 'protected') lassen sich über keine Schnittstelle verändern. "
                "MCP (Streamable HTTP) unter /mcp, schreibende MCP-Werkzeuge mit Bearer-Token."
            ),
        },
        "servers": [{"url": u["url"].rstrip("/"), "description": u["label"]} for u in info.get("urls", [])],
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer", "description": "Zugangsschlüssel; nur für schreibende MCP-Werkzeuge nötig"}}},
        "paths": {
            "/api/state": {"get": _op("Kompletter Zustand: Protokolle, Quellen, Ziele, Presets, Sperrliste")},
            "/api/status": {"get": _op("Kompakter Zustand: routes {Ziel-id: Quelle}, presets {id: aktiv}")},
            "/api/choices": {"get": _op("Auswahllisten: Ziele, Quellen, Presets (für Companion)")},
            "/api/events": {"get": {"summary": "Server-Sent Events 'status' bei jeder Änderung", "responses": {"200": {"description": "text/event-stream"}}}},
            "/api/history": {"get": _op("Die letzten 50 Umschaltungen")},
            "/api/preview": {"get": _op("Zustand der NDI-Vorschau: verfügbar, offene Empfänger, Grenzen", [_q("source", "optional: Zustand dieser Quelle")])},
            "/api/preview.jpg": {
                "get": {
                    "summary": "Standbild einer NDI-Quelle (JPEG aus dem Proxy-Stream, wenige Sekunden zwischengespeichert)",
                    "parameters": [_q("source", "NDI-Quelle: id oder Label", True), _q("w", "Breite in Pixel, 64–640 (Vorgabe 320)")],
                    "responses": {
                        "200": {"description": "image/jpeg; Header X-Preview-Age (Sekunden), X-Preview-Size", "content": {"image/jpeg": {}}},
                        "404": {"description": "Quelle offline oder unbekannt (JSON, error: offline | unknown_source)"},
                        "415": {"description": "NDI|HX-Quelle, Decoder fehlt (error: unsupported_codec)"},
                        "501": {"description": "NDI SDK nicht installiert (error: unavailable)"},
                        "503": {"description": "Quelle liefert kein Bild (error: no_signal)"},
                    },
                }
            },
            "/api/preview.mjpeg": {
                "get": {
                    "summary": "Live-Vorschau einer NDI-Quelle als MJPEG-Stream (multipart/x-mixed-replace); höchstens eine Quelle gleichzeitig",
                    "parameters": [
                        _q("source", "NDI-Quelle: id oder Label", True),
                        _q("w", "Breite in Pixel, 160–1280 (Vorgabe 640)"),
                        _q("fps", "Bilder je Sekunde, 1–25 (Vorgabe 12.5)"),
                    ],
                    "responses": {"200": {"description": "multipart/x-mixed-replace; boundary=avmframe"}, "404": {"description": "offline"}, "501": {"description": "nicht verfügbar"}},
                }
            },
            "/api/info": {"get": _op("Version und Zugangsadressen")},
            "/api/route": {"get": route, "post": route},
            "/api/salvo": {"post": _op("Mehrere Verbindungen auf einmal: {routes: [{destination, source}]}", write=True, body=True)},
            "/api/undo": {"get": undo, "post": undo},
            "/api/lock": {"post": _op("Ziel sperren", [_DEST], write=True)},
            "/api/unlock": {"post": _op("Ziel entsperren (nicht möglich bei fest geschützten Zielen)", [_DEST], write=True)},
            "/api/label": {"post": _op("Label/Tags setzen: {protocol, source, label, tags} oder {destination, label, tags}; Gerätetyp einer NDI-Quelle: {protocol, source, type}", body=True)},
            "/api/refresh": {"post": _op("Quellenlisten der Geräte neu aufbauen")},
            "/api/source/forget": {"post": _op("Eine Quelle, die nicht mehr sendet, aus den Listen nehmen: {protocol, source}", body=True)},
            "/api/presets": {
                "get": _op("Presets mit Verbindungen und 'active'"),
                "post": _op("Preset anlegen: {name, routes: [{destination, source}]} oder {name, destinations: [...]} (Ist-Zustand)", write=True, body=True),
            },
            "/api/presets/{id}": {
                "put": {**_op("Preset ändern (name, routes oder destinations)", [pid], write=True, body=True)},
                "delete": _op("Preset löschen", [pid]),
            },
            "/api/presets/{id}/recall": {"get": _op("Preset abrufen", [pid], write=True), "post": _op("Preset abrufen", [pid], write=True)},
            "/api/preset/recall": {"get": recall, "post": recall},
            "/api/system": {
                "get": _op(
                    "Systemauslastung: host (CPU, Kerne, Load, RAM, Temperatur, Unterspannung, Speicherplatz, Netz, Laufzeit), "
                    "processes (matrix, companion), activity (NDI-Empfänger, Testbild, Clients, Geräte, Schaltvorgänge, Fehler), "
                    "warnings, history. Mit summary=1 nur die Kurzform für die Anzeige",
                    [_q("summary", "1 = nur cpu_percent, memory_percent, temperature_c, warnings")],
                )
            },
            "/api/qr.svg": {
                "get": {
                    "summary": "QR-Code zum Verbinden (SVG). Inhalt: eine vom Telefon erreichbare Adresse des Panels",
                    "parameters": [_q("target", "Art der Adresse: lan_ip (Vorgabe) | tailscale_name | tailscale_ip | mdns_name")],
                    "responses": {"200": {"description": "image/svg+xml; Header X-QR-Url nennt die Adresse", "content": {"image/svg+xml": {}}}},
                }
            },
            "/api/testpattern": {
                "get": _op("Zustand der eigenen NDI-Testbild-Quelle: enabled, available, running, source, connections, url"),
                "post": _op("Testbild-Quelle ein-/ausschalten: {enabled: true|false} (bleibt über Neustarts erhalten)", body=True),
            },
            "/api/testpattern.jpg": {"get": {"summary": "Das Testbild als JPEG (1280×720), auch ohne NDI SDK", "responses": {"200": {"description": "image/jpeg", "content": {"image/jpeg": {}}}}}},
            "/api/token": {"get": _op("Zugangsschlüssel anzeigen – nur aus dem Panel (Header X-AVM-Panel: 1)")},
            "/api/token/rotate": {"post": _op("Zugangsschlüssel erneuern – nur aus dem Panel (Header X-AVM-Panel: 1)")},
            "/api/ha/config/config_entries/flow": {"post": _op("„Gerät hinzufügen“ beginnen (Dialog der Karte; Ablauf wie Home-Assistant-Config-Flows)", body=True)},
            "/api/ha/config/config_entries/flow/{id}": {
                "get": _op("Aktuellen Schritt eines Vorgangs lesen", [pid]),
                "post": _op("Eingaben eines Schritts senden", [pid], body=True),
                "delete": _op("Vorgang abbrechen", [pid]),
            },
            "/ws": {"get": {"summary": "WebSocket für das Panel (Befehle mit id/type, siehe docs/SCHNITTSTELLE.md)", "responses": {"101": {"description": "Switching Protocols"}}}},
            "/mcp": {
                "post": {
                    "summary": "MCP (Streamable HTTP, JSON-RPC 2.0, zustandslos). Werkzeuge: docs/api/mcp-tools.json",
                    "security": [{}, {"bearer": []}],
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {"200": {"description": "JSON-RPC-Antwort"}, "202": {"description": "Benachrichtigung angenommen"}, "401": {"description": "Zugangsschlüssel ungültig"}},
                }
            },
            "/api/devices/{id}/forget": {"post": _op("Nicht antwortendes Gerät eines Netzwerk-Eintrags (dante, nmos) aus der Liste nehmen: {device}", [pid], body=True)},
            "/api/nmos/check": {
                "get": _op(
                    "ST 2110 prüfen: NMOS-Geräte suchen (mDNS, eingetragene Adressen/Registry) und lesen, was sie melden – schaltet nichts. "
                    "Antwort: discovery, devices (Name, Typ, Adresse, PTP, Ein-/Ausgänge), findings [{level: ok|hinweis|problem, text}]",
                    [_q("raw", "1 = vollständige Rohdaten als JSON-Datei zum Herunterladen")],
                )
            },
            "/api/devices": {"get": _op("Eingerichtete Geräte (ohne Zugangsdaten)")},
            "/api/devices/{id}": {"patch": _op("Gerät umbenennen / Optionen (title, scan_interval; Netzwerk-Einträge: static_hosts, registries, audio_breakaway, check_compat, enable_senders)", [pid], body=True), "delete": _op("Gerät entfernen", [pid])},
        },
    }


def llms_txt(info: dict[str, Any]) -> str:
    urls = "\n".join(f"- {u['label']}: {u['url']}" for u in info.get("urls", []))
    mcp = "\n".join(f"- {u['label']}: {u['url']}mcp" for u in info.get("urls", []))
    return f"""# Strelle AV Matrix Server

> Kreuzschiene des Studios für NDI® (Video), Dante® (Audio) und ST 2110 (NMOS): Quellen auf Ziele schalten, Presets abrufen,
> Zustand lesen. Läuft nur im Studionetz und im Tailnet. Version {__version__}.

## Adressen
{urls}

## MCP (für LLMs der bevorzugte Weg)
Streamable HTTP, zustandslos:
{mcp}

Lesende Werkzeuge ohne Schlüssel: list_devices, list_sources, list_destinations, get_routing, list_presets,
get_preview_url (Adresse der Bildvorschau einer NDI-Quelle), get_system_status (Auslastung).
Schreibende nur mit `Authorization: Bearer <Zugangsschlüssel>`: set_route, recall_preset, save_preset,
delete_preset, undo. Der Schlüssel steht im Panel unter „LLM-Verbindung“.

## HTTP (für Companion, Skripte, curl)
Ohne Anmeldung, Antworten als JSON. Schalt-Adressen gehen als GET und POST.

- `GET /api/state` – alles: Protokolle, Quellen, Ziele (mit `current_source`, `status`, `locked`, `protected`), Presets
- `GET /api/status` – kompakt: `routes` (Ziel-id → Quelle) und `presets` (id → aktiv)
- `GET|POST /api/route?dest=<Ziel>&source=<Quelle>` – Verbindung setzen; `source` leer / `Aus` trennt
- `GET|POST /api/preset/recall?preset=<id oder Name>` – Preset abrufen
- `GET|POST /api/undo` – letzte Aktion zurücknehmen; `?dest=<Ziel>` nur dieses Ziel
- `POST /api/lock?dest=` / `POST /api/unlock?dest=` – Ziel sperren / entsperren
- `GET /api/presets`, `POST /api/presets`, `PUT|DELETE /api/presets/<id>` – Presets verwalten
- `GET /api/events` – Server-Sent Events bei jeder Änderung
- `GET /api/preview.jpg?source=<NDI-Quelle>&w=320` – Standbild der Quelle als JPEG (Fehler als JSON:
  `offline` 404, `no_signal` 503, `unavailable` 501)
- `GET /api/preview.mjpeg?source=<NDI-Quelle>&w=640&fps=12` – Live-Vorschau als MJPEG-Stream (eine Quelle gleichzeitig)
- `GET /api/preview` – Zustand der Vorschau (offene Empfänger, Grenzen)
- `GET /api/system` – Systemauslastung und was der Server gerade tut (`?summary=1` = Kurzform)
- `GET /api/qr.svg` – QR-Code mit einer vom Telefon erreichbaren Adresse des Panels
- `GET|POST /api/testpattern` – eigene NDI-Testbild-Quelle ein/aus; `GET /api/testpattern.jpg` – das Bild
- `GET /openapi.json` – vollständige Beschreibung (OpenAPI 3.1)

Ziele und Quellen dürfen als `id`, Label oder Name angegeben werden (Groß-/Kleinschreibung egal).
Dante-Quellen heißen `Kanal@Gerät`, Dante-Ziele `Gerät:RX-Nummer`. ST-2110-Quellen heißen `Eingang@Gerät`,
ST-2110-Ziele `Gerät:Ausgang`; eine Quelle ist dort Bild, Ton und Zusatzdaten gemeinsam. Für ST 2110 gibt es
keine Bildvorschau. `GET /api/nmos/check` zeigt, was die ST-2110-Geräte melden, ohne zu schalten.

## Regeln
- Ziele mit `protected` sind fest gesperrt (serverseitige Sperrliste) und werden über keine Schnittstelle
  verändert – Antwort 403. Nicht versuchen, das zu umgehen.
- Ziele mit `locked` hat ein Mensch gesperrt: nicht entsperren, sondern nachfragen.
- Erst lesen, dann schalten; nach einem Versehen `undo`.
- Fehler: JSON `{{"ok": false, "error": "<code>", "message": "<Klartext>"}}` mit passendem HTTP-Status.
"""
