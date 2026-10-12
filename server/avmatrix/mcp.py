"""MCP-Schnittstelle (Model Context Protocol, Streamable HTTP) – schlank, ohne SDK.

``POST /mcp`` nimmt JSON-RPC 2.0 entgegen und antwortet mit ``application/json`` (kein SSE-Stream nötig,
der Server ist zustandslos). ``GET /mcp`` → 405 (kein Server-Stream), wie es die Spezifikation erlaubt.

Lesende Werkzeuge gehen ohne Schlüssel. Schreibende brauchen ``Authorization: Bearer <Zugangsschlüssel>``.
Die feste Sperrliste (guard.py) gilt hier wie überall – auch mit Schlüssel.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from collections.abc import Callable as _Callable
from typing import Any
from urllib.parse import quote

from . import __version__
from .hub import Hub, MatrixError
from .preview import MESSAGES as PREVIEW_MESSAGES
from .preview import PreviewManager

_LOGGER = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = "2025-06-18"

INSTRUCTIONS = (
    "Strelle AV Matrix: Kreuzschiene des Studios (NDI®-Video und Dante®-Audio). Quellen werden auf Ziele geschaltet. "
    "Erst lesen (list_destinations, list_sources, get_routing), dann schalten. Schreibende Werkzeuge "
    "(set_route, recall_preset, save_preset, delete_preset, undo) brauchen den Zugangsschlüssel als Bearer-Token. "
    "Ziele mit 'protected' sind fest gesperrt und lassen sich über keine Schnittstelle verändern; Ziele mit "
    "'locked' hat ein Mensch gesperrt – nicht umgehen, sondern nachfragen. Vor jedem Schalten kurz sagen, was "
    "sich ändert; nach einem Versehen undo benutzen."
)


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


_PROTOCOL = {"type": "string", "enum": ["ndi", "dante"], "description": "Nur dieses Protokoll (ndi = Video, dante = Audio)."}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_devices",
        "title": "Geräte auflisten",
        "description": "Eingerichtete Geräte (NDI-Decoder, Dante-Geräte) mit Adresse, Modell und Online-Status.",
        "inputSchema": _obj({}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_sources",
        "title": "Quellen auflisten",
        "description": "Alle bekannten Quellen (NDI-Sender, Dante-Sendekanäle 'Kanal@Gerät'). 'id' ist der Wert für set_route.",
        "inputSchema": _obj(
            {"protocol": _PROTOCOL, "live_only": {"type": "boolean", "description": "Nur Quellen, die gerade senden."}}
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_destinations",
        "title": "Ziele auflisten",
        "description": "Alle Ziele (Decoder-Ausgänge, Dante-Empfangskanäle) mit aktueller Quelle, Status, Sperre und Schutz.",
        "inputSchema": _obj({"protocol": _PROTOCOL}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_routing",
        "title": "Schaltzustand abfragen",
        "description": "Kompakter Ist-Zustand: welche Quelle liegt auf welchem Ziel, welche Presets sind aktiv.",
        "inputSchema": _obj({"protocol": _PROTOCOL}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_presets",
        "title": "Presets auflisten",
        "description": "Gespeicherte Presets (mehrere Verbindungen auf einmal) mit ihren Verbindungen und ob sie gerade aktiv sind.",
        "inputSchema": _obj({}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_preview_url",
        "title": "Vorschau-Adresse einer NDI-Quelle",
        "description": (
            "Adressen der Bildvorschau einer NDI-Quelle: 'jpeg' (aktuelles Standbild) und 'mjpeg' (fortlaufende "
            "Live-Vorschau), jeweils je Zugangsadresse des Servers. Liefert kein Bild, nur die Adressen und den "
            "Zustand (ok, offline, unavailable). Nur NDI – Dante ist Audio."
        ),
        "inputSchema": _obj({"source": {"type": "string", "description": "NDI-Quelle: 'id' oder Label aus list_sources."}}, ["source"]),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_system_status",
        "title": "Systemauslastung",
        "description": (
            "Auslastung des Rechners (CPU gesamt und je Kern, Load, RAM, Temperatur, Speicherplatz, Netz), Verbrauch "
            "des Matrix-Dienstes und von Companion, was der Server gerade tut (NDI-Empfänger, Testbild, verbundene "
            "Clients, Geräteverbindungen, letzte Schaltvorgänge und Fehler), Warnungen und ein kurzer Verlauf."
        ),
        "inputSchema": _obj({}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "set_route",
        "title": "Verbindung setzen",
        "description": "Eine Quelle auf ein Ziel schalten. Braucht den Zugangsschlüssel. Gesperrte und geschützte Ziele werden abgelehnt.",
        "inputSchema": _obj(
            {
                "destination": {"type": "string", "description": "Ziel: 'id' oder Name aus list_destinations."},
                "source": {
                    "type": ["string", "null"],
                    "description": "Quelle: 'id' oder Label aus list_sources. null oder 'Aus' trennt die Verbindung.",
                },
            },
            ["destination", "source"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "recall_preset",
        "title": "Preset abrufen",
        "description": "Alle Verbindungen eines Presets schalten. Braucht den Zugangsschlüssel. Ist ein Ziel gesperrt, wird nichts geschaltet.",
        "inputSchema": _obj({"preset": {"type": "string", "description": "'id' oder Name des Presets."}}, ["preset"]),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "save_preset",
        "title": "Preset anlegen oder ändern",
        "description": (
            "Preset speichern. Entweder 'routes' (Liste aus {destination, source}) angeben oder 'destinations' "
            "(dann wird der Ist-Zustand dieser Ziele festgehalten). Mit 'preset' wird ein bestehendes Preset "
            "überschrieben. Braucht den Zugangsschlüssel."
        ),
        "inputSchema": _obj(
            {
                "name": {"type": "string", "description": "Name des Presets."},
                "routes": {
                    "type": "array",
                    "items": _obj(
                        {"destination": {"type": "string"}, "source": {"type": ["string", "null"]}}, ["destination", "source"]
                    ),
                },
                "destinations": {"type": "array", "items": {"type": "string"}},
                "preset": {"type": "string", "description": "'id' oder Name eines bestehenden Presets (zum Ändern)."},
            },
            ["name"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "delete_preset",
        "title": "Preset löschen",
        "description": "Ein Preset löschen (schaltet nichts). Braucht den Zugangsschlüssel.",
        "inputSchema": _obj({"preset": {"type": "string", "description": "'id' oder Name des Presets."}}, ["preset"]),
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
    {
        "name": "undo",
        "title": "Rückgängig",
        "description": (
            "Ohne 'destination': die letzte Aktion (Einzelschaltung oder Preset) komplett zurücknehmen. "
            "Mit 'destination': die vorherige Quelle dieses Ziels wiederherstellen. Braucht den Zugangsschlüssel."
        ),
        "inputSchema": _obj({"destination": {"type": "string"}}),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
]
WRITE_TOOLS = {t["name"] for t in TOOLS if not t["annotations"].get("readOnlyHint")}


class McpServer:
    def __init__(
        self,
        hub: Hub,
        preview: PreviewManager | None = None,
        info: _Callable[[], dict[str, Any]] | None = None,
        system: _Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.hub = hub
        self.preview = preview
        self.info = info
        self.system = system

    # ------------------------------------------------------------------ tools
    def _destinations(self, protocol: str | None) -> list[dict[str, Any]]:
        out = []
        for key, proto in self.hub.snapshot()["protocols"].items():
            if protocol and key != protocol:
                continue
            for d in proto["destinations"]:
                out.append(
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "protocol": key,
                        "device": d["device_name"],
                        "host": d["host"],
                        "current_source": d["current_source"],
                        "status": d["status"],
                        "available": d["available"],
                        "locked": d["locked"],
                        "protected": d["protected"],
                    }
                )
        return out

    async def _tool_list_devices(self, args: dict[str, Any]) -> Any:
        return {"devices": self.hub.devices()}

    async def _tool_list_sources(self, args: dict[str, Any]) -> Any:
        out = []
        for key, proto in self.hub.snapshot()["protocols"].items():
            if args.get("protocol") and key != args["protocol"]:
                continue
            for s in proto["sources"]:
                if args.get("live_only") and not s["live"]:
                    continue
                item = {"id": s["id"], "name": s["name"], "protocol": key, "live": s["live"], "host": s["host"]}
                if s.get("group"):
                    item["device"] = s["group"]
                out.append(item)
        return {"sources": out}

    async def _tool_list_destinations(self, args: dict[str, Any]) -> Any:
        return {"destinations": self._destinations(args.get("protocol"))}

    async def _tool_get_routing(self, args: dict[str, Any]) -> Any:
        routing = [
            {
                "destination": d["id"],
                "destination_name": d["name"],
                "protocol": d["protocol"],
                "source": d["current_source"],
                "status": d["status"],
                **({"protected": d["protected"]} if d["protected"] else {}),
                **({"locked": True} if d["locked"] and not d["protected"] else {}),
            }
            for d in self._destinations(args.get("protocol"))
        ]
        presets = [{"id": p["id"], "name": p["name"], "active": p["active"]} for p in self.hub.presets_view()]
        return {"routing": routing, "presets": presets}

    async def _tool_list_presets(self, args: dict[str, Any]) -> Any:
        return {"presets": self.hub.presets_view()}

    async def _tool_get_system_status(self, args: dict[str, Any]) -> Any:
        if self.system is None:
            raise MatrixError("invalid", "Systemauslastung nicht verfügbar")
        data = dict(self.system())
        data["history"] = data.get("history", [])[-30:]
        return data

    async def _tool_get_preview_url(self, args: dict[str, Any]) -> Any:
        source = self.hub.resolve_source("ndi", args.get("source"))
        if source is None or self.preview is None:
            raise MatrixError("invalid", "NDI-Quelle angeben")
        state = self.preview.source_state(source)[0]
        query = "?source=" + quote(source, safe="")
        urls = [
            {"address": u["label"], "jpeg": f"{u['url']}api/preview.jpg{query}", "mjpeg": f"{u['url']}api/preview.mjpeg{query}"}
            for u in (self.info()["urls"] if self.info else [])
        ]
        return {
            "source": source,
            "state": state,
            "message": PREVIEW_MESSAGES.get(state),
            "urls": urls,
            "options": "jpeg: &w=<Breite 64-640>; mjpeg: &w=<Breite 160-1280>&fps=<1-25>",
        }

    async def _tool_set_route(self, args: dict[str, Any]) -> Any:
        dest = self.hub.resolve_destination(args.get("destination"))
        source = self.hub.resolve_source(dest.protocol, args.get("source"))
        event = await self.hub.route(dest.uid, source, origin="mcp")
        return {"ok": True, "destination": dest.uid, "source": source, "previous_source": event["previous_source"]}

    async def _tool_recall_preset(self, args: dict[str, Any]) -> Any:
        return {"ok": True, **await self.hub.recall_preset(str(args.get("preset") or ""), origin="mcp")}

    async def _tool_save_preset(self, args: dict[str, Any]) -> Any:
        preset_id = self.hub.get_preset(args["preset"])["id"] if args.get("preset") else None
        if args.get("routes"):
            return {"ok": True, "preset": self.hub.save_preset(args.get("name", ""), args["routes"], preset_id=preset_id)}
        if args.get("destinations"):
            return {
                "ok": True,
                "preset": self.hub.snapshot_preset(args.get("name", ""), args["destinations"], preset_id=preset_id),
            }
        raise MatrixError("invalid", "Entweder 'routes' oder 'destinations' angeben.")

    async def _tool_delete_preset(self, args: dict[str, Any]) -> Any:
        self.hub.delete_preset(str(args.get("preset") or ""))
        return {"ok": True}

    async def _tool_undo(self, args: dict[str, Any]) -> Any:
        if args.get("destination"):
            dest = self.hub.resolve_destination(args["destination"])
            event = await self.hub.undo(dest.uid)
            return {"ok": True, "restored": [{"destination": dest.uid, "source": event["source"]}]}
        return {"ok": True, **await self.hub.undo_last()}

    # --------------------------------------------------------------- JSON-RPC
    async def handle(self, message: Any, *, authorized: bool) -> dict[str, Any] | None:
        """Eine JSON-RPC-Nachricht verarbeiten. ``None`` = Benachrichtigung (keine Antwort)."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            if isinstance(message, dict) and "method" not in message and ("result" in message or "error" in message):
                return None  # Antwort des Clients auf eine Server-Anfrage: gibt es hier nicht
            return self._error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
        msg_id = message.get("id")
        method = message["method"]
        params = message.get("params") or {}
        if msg_id is None:
            return None  # notifications/initialized, notifications/cancelled …
        if method == "initialize":
            wanted = params.get("protocolVersion")
            return self._result(
                msg_id,
                {
                    "protocolVersion": wanted if wanted in PROTOCOL_VERSIONS else DEFAULT_PROTOCOL,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "av-matrix", "title": "Strelle AV Matrix (Kreuzschiene)", "version": __version__},
                    "instructions": INSTRUCTIONS,
                },
            )
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            return self._result(msg_id, {"tools": TOOLS})
        if method == "tools/call":
            return self._result(msg_id, await self._call(params, authorized))
        if method in ("resources/list", "prompts/list", "resources/templates/list"):
            return self._result(msg_id, {method.split("/")[0]: []} if "templates" not in method else {"resourceTemplates": []})
        return self._error(msg_id, -32601, f"Method not found: {method}")

    async def _call(self, params: dict[str, Any], authorized: bool) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        handler: Callable[[dict[str, Any]], Awaitable[Any]] | None = getattr(self, f"_tool_{name}", None)
        if handler is None or name not in {t["name"] for t in TOOLS} or not isinstance(args, dict):
            return self._tool_error(f"Unbekanntes Werkzeug oder ungültige Argumente: {name!r}")
        if name in WRITE_TOOLS and not authorized:
            return self._tool_error(
                "Zugangsschlüssel fehlt: schreibende Werkzeuge brauchen den Header "
                "'Authorization: Bearer <Zugangsschlüssel>'. Der Schlüssel steht im Panel unter „LLM-Verbindung“."
            )
        try:
            data = await handler(args)
        except MatrixError as err:
            return self._tool_error(err.message, err.code)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("MCP-Werkzeug %s fehlgeschlagen", name)
            return self._tool_error("Interner Fehler, siehe Protokoll des Servers.")
        return {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "structuredContent": data,
            "isError": False,
        }

    @staticmethod
    def _tool_error(text: str, code: str | None = None) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": text}], "isError": True, **({"_meta": {"code": code}} if code else {})}

    @staticmethod
    def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, text: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}
