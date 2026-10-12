# Schnittstelle des Servers

Sprachneutrale Beschreibung dessen, was ein Backend von **Strelle AV Matrix** liefern muss, damit das Panel
(`avmatrix/static/`), das Companion-Modul, die Companion-Seiten und andere Oberflächen (z. B. die
Home-Assistant-Karte für die Vorschau) unverändert funktionieren. Maschinenlesbar daneben:
[`api/openapi.json`](api/openapi.json) (HTTP) und [`api/mcp-tools.json`](api/mcp-tools.json) (MCP-Werkzeuge mit
Schemata). Beide werden aus dem Code erzeugt (`scripts/export-spec.py`); ein Test hält sie aktuell.

## Grundsätze

- Ein Port (Vorgabe **8088**), reines HTTP, an allen Schnittstellen. Betrieb nur im Studionetz / Tailnet.
- Antworten sind JSON in UTF-8. Fehler: `{"ok": false, "error": "<code>", "message": "<Klartext, deutsch>"}`.

| `error` | HTTP | Bedeutung |
|---|---|---|
| `invalid` | 400 | Parameter fehlen oder passen nicht |
| `protected` | 403 | Ziel steht auf der festen Sperrliste |
| `forbidden` | 403 | unbekannter Host-Name oder Aufruf von fremder Webseite |
| `unknown_destination`, `unknown_preset`, `unknown_device` | 404 | |
| `ambiguous`, `nothing_to_undo` | 409 | Name nicht eindeutig / nichts rückgängig zu machen |
| `locked` | 423 | Ziel ist (von einem Menschen) gesperrt |
| `route_failed` | 502 | das Gerät hat das Schalten abgelehnt |

- **Schutz ohne Anmeldung:** `Host` muss eine IP-Adresse oder einer der eigenen Namen sein (gegen DNS-Rebinding).
  Anfragen mit fremdem `Origin` oder `Sec-Fetch-Site: cross-site` auf `/api`, `/ws`, `/mcp` werden abgelehnt –
  Ausnahme: die Bilder (`/api/preview.jpg`, `/api/preview.mjpeg`, `/api/qr.svg`, `/api/testpattern.jpg`), damit
  andere Oberflächen im Studionetz sie einbetten können.
- Parameter schaltender Aufrufe stehen in der Query **oder** im JSON-Body; `GET` und `POST` sind gleichwertig.

## Bezeichner

| | Form | Beispiel |
|---|---|---|
| NDI-Quelle | der NDI-Name, exakt | `STUDIO-PC (Program)` |
| Dante-Quelle | `<TX-Kanal>@<Gerät>` | `Mic 3@STAGEBOX-01` |
| Ziel eines Einzelgeräts | `<Geräte-id>_<Ausgang>` | `magewell-a1b2c3_main` |
| Dante-Ziel | `dante_<Gerät>:<RX-Nummer>` | `dante_STAGEBOX-01:2` |
| Preset | Kurzform des Namens | `schnitt-auf-regie` |

Wo ein Ziel oder eine Quelle verlangt ist, gilt auch das Label oder der Name (Groß-/Kleinschreibung egal, muss
eindeutig sein); für Dante-Ziele auch `<Gerät>:<RX-Nummer>`. „Keine Quelle“: leerer Wert, `null`, `None`, `Aus`.

## Zustand lesen

- `GET /api/state` – der **Schnappschuss**. Format wie in [`../../docs/frontend-api.md`](../../docs/frontend-api.md)
  („Snapshot format“), mit diesen Abweichungen: `entity_id`, `device_id`, `display` sind `null`; jedes Ziel hat
  zusätzlich `protected` (Grund als Text oder `null`; geschützte Ziele melden auch `locked: true`); auf oberster
  Ebene kommen `presets` (Liste wie `GET /api/presets`), `can_undo` und `protected` (Regeln der Sperrliste) dazu.
- `GET /api/status` – `{"routes": {<Ziel-id>: <Quelle|null>}, "presets": {<id>: true|false}, "can_undo": bool}`
- `GET /api/choices` – `{"destinations": [{id, name, protocol, protected}], "sources": [{id, name, protocol}], "presets": [{id, name}]}`
- `GET /api/events` – Server-Sent Events. Ereignis `status` bei jeder Änderung (200 ms gebündelt, nur bei
  geändertem Inhalt): Daten wie `/api/status` plus `choices_rev` (ändert sich, wenn `/api/choices` sich ändert).
  Alle 25 s eine Kommentarzeile `: ping`.
- `GET /api/history` – die letzten 50 Umschaltungen, `GET /api/info` – Name, Version, Adressen, `mcp_urls`,
  `GET /api/devices` – Geräteübersicht ohne Zugangsdaten.

## Schalten

| Aufruf | Parameter | Antwort |
|---|---|---|
| `GET\|POST /api/route` | `dest` (oder `destination`), `source` | `{ok, destination, source, previous_source}` |
| `POST /api/salvo` | `routes: [{destination, source}]` | `{ok, switched: [...], skipped_offline: [...]}` |
| `GET\|POST /api/undo` | optional `dest` | `{ok, restored: [{destination, source}]}`; ohne `dest` die letzte Aktion komplett |
| `POST /api/lock`, `/api/unlock` | `dest` | `{ok, destination, locked}` |
| `POST /api/label` | `{protocol, source, label, tags}` oder `{destination, label, tags}` | |
| `POST /api/refresh` | – | Geräte bauen ihre Quellenlisten neu auf |

Regeln: Vor einer Salve oder einem Preset werden **alle** Ziele geprüft – ist eines unbekannt, gesperrt oder
geschützt, wird nichts geschaltet. Ziele verschiedener Geräte schalten parallel. Undo je Ziel merkt sich die
letzten 10 Quellen; „letzte Aktion“ nimmt eine Einzelschaltung, Salve oder ein Preset als Ganzes zurück.

## Presets

Ein Preset ist `{id, name, routes: [{destination, source}]}`. **Aktiv** heißt: bei jedem Ziel des Presets liegt
genau die genannte Quelle an.

- `GET /api/presets` → `{"presets": [{id, name, active, updated, routes: [{destination, destination_name,
  protocol, source, source_name, known, available, locked, matches}]}]}`
- `POST /api/presets` mit `{name, routes}` **oder** `{name, destinations: [...]}` (hält den Ist-Zustand fest)
- `PUT /api/presets/<id>` (wie POST; nur `name` = umbenennen), `DELETE /api/presets/<id>`
- `GET|POST /api/presets/<id>/recall` und `GET|POST /api/preset/recall?preset=<id|Name>` →
  `{ok, preset, name, switched, skipped_offline}`. Ziele, deren Gerät gerade offline ist, werden übersprungen
  und gemeldet; gesperrte/geschützte Ziele brechen den Abruf ab.

Geschützte Ziele lassen sich nicht in ein Preset aufnehmen (403).

## Geräte

`GET /api/devices`, `PATCH /api/devices/<id>` (`title`, `static_hosts`, `scan_interval`), `DELETE /api/devices/<id>`.
Hinzufügen läuft über den Dialog der Karte: `POST /api/ha/config/config_entries/flow` beginnt, `GET`/`POST`/
`DELETE …/flow/<id>` führen fort. Antworten wie bei Home-Assistant-Config-Flows: `type` = `menu` (`menu_options`),
`form` (`data_schema` als Liste aus `{name, required, default?, description: {suggested_value}?, selector}`,
`errors`, `description_placeholders`), `create_entry` (`title`) oder `abort` (`reason`). Schritte: `user` (Menü:
`scan`, `manual`) → `scan` (Subnetz) → `pick` → `confirm` bzw. `manual` → `device` / `network`.

## NDI-Vorschau

Nur für NDI-Quellen. Kein Schlüssel, keine Anmeldung; die beiden Bild-Adressen dürfen auch von Seiten anderer
Herkunft per `<img>` eingebettet werden.

### `GET /api/preview.jpg?source=<Quelle>[&w=<Breite>]`

Aktuelles Standbild als `image/jpeg`. `source`: id oder Label der NDI-Quelle (URL-kodiert). `w`: 64–640,
Vorgabe 320; das Bild wird nie vergrößert (der Proxy-Stream hat meist 640×360), Seitenverhältnis bleibt.
Antwort-Header: `X-Preview-State: ok`, `X-Preview-Age` (Sekunden seit der Aufnahme, höchstens der Puffer von 4 s),
`X-Preview-Size` (Größe des empfangenen Bildes), `Cache-Control: no-store`.

`X-Preview-Origin` sagt, woher das Bild stammt: `ndi` (aus dem NDI-Feed) oder `device` – Rückfall für Encoder,
deren NDI-Strom sich nicht dekodieren lässt: das Gerät liefert selbst ein Standbild (derzeit LinkPi-Firmware, u. a.
TBS: `enc.snap` über `/RPC`, Bild unter `/snap/snap<Kanal>.jpg`). Oberflächen sollen das kenntlich machen.
Solche Quellen und NDI|HX in voller Auflösung puffert der Server 20 s statt 4 s; ihre „Live“-Vorschau ist eine
Folge von Standbildern (`mode: "stills"` in `/api/preview`), kein offener Stream.

Kein Bild → JSON-Fehler, **nie ein altes oder Platzhalterbild**; der Zustand steht auch im Header `X-Preview-State`:

| `error` | HTTP | Bedeutung |
|---|---|---|
| `offline` | 404 | Quelle bekannt, sendet aber nicht (laut Quellenregister) |
| `unknown_source` | 404 | Quelle unbekannt |
| `no_signal` | 503 | Quelle ist da, liefert binnen 2,5 s kein Bild |
| `unavailable` | 501 | NDI SDK nicht installiert oder Vorschau abgeschaltet |
| `unsupported_codec` | 415 | NDI\|HX-Quelle (H.264/HEVC), der Decoder fehlt auf dem Server (`hx_decoder: false` in `/api/preview`) |

Empfohlener Takt für Kacheln: alle 4–5 s je sichtbarer Quelle, höchstens zwei Abrufe gleichzeitig, nur solange
die Ansicht sichtbar ist. Ein Bild, das älter als ~15 s ist, nicht mehr als aktuell zeigen.

### `GET /api/preview.mjpeg?source=<Quelle>[&w=<Breite>][&fps=<Rate>]`

Live-Vorschau als `multipart/x-mixed-replace; boundary=avmframe`, jedes Teil `Content-Type: image/jpeg` mit
`Content-Length`. `w`: 160–1280 (Vorgabe 640, nie vergrößert), `fps`: 1–25 (Vorgabe 12,5). Ein ruhendes Bild
wird jede Sekunde wiederholt. Der Stream **endet**, wenn die Quelle wegfällt, 8 s kein Bild kam, nach 10 min
oder wenn eine andere Quelle die Live-Vorschau übernimmt (höchstens `max_live` Quellen gleichzeitig, Vorgabe 1;
mehrere Zuschauer derselben Quelle teilen sich einen Empfänger). Fehler vor dem ersten Bild wie oben.
Zum Beenden die Verbindung schließen (`img.src = ""`); der Empfänger schließt 3 s später.

### `GET /api/preview[?source=<Quelle>]`

`{available, reason, ndi_version, bandwidth: "lowest", receivers_open, receivers_opened_total,
receivers_closed_total, live: [{source, clients, seconds, frames, state}], limits: {…}}`; mit `source` zusätzlich
`source: {id, state}` (`ok`, `offline`, `unknown_source`, `unavailable`) – ohne einen Empfänger zu öffnen.

Ziele haben keine eigene Vorschau: ein Ziel zeigt das Bild seiner `current_source`.

## Gerätetyp einer NDI-Quelle

Jede NDI-Quelle im Schnappschuss trägt zusätzlich:

| Feld | Bedeutung |
|---|---|
| `device_type` | `camera` \| `computer` \| `encoder` \| `testpattern` \| `unknown` – der geltende Typ |
| `device_type_auto` | was die Regeln ergeben haben |
| `device_type_manual` | `true`, wenn der Typ von Hand festgelegt wurde |
| `icon_key` | Illustration dazu: `ndi_camera`, `ndi_computer`, `ndi_encoder`, `ndi_testpattern`, `ndi_source` (unter `/static/devices/<icon_key>.svg`) |
| `web_url` | `http://<Adresse>/`, wenn das Gerät dort antwortet (einmal je Adresse nur lesend geprüft), sonst `null` |

Regeln (erste passende gewinnt; Tabelle in `avmatrix/source_types.py`): Ein NDI-Name ist `MASCHINE (Kanal)`.
Geprüft werden Maschine, Kanal und – falls vorhanden – Titel/Server der Weboberfläche. `testpattern`: Kanal endet
auf „AV Matrix Testbild“. `camera`: Kameranamen (ZowieCAM, PTZ, CAM, BirdDog P…, …). `encoder`: Encodernamen
(TBS, LinkPi, Kiloview, Pro Convert, …) oder die Maschine ist eine **IP-Adresse** und der Kanal heißt wie ein
Eingang (`AUX2`, `HDMI`, `SDI 1`, …). `computer`: nur wenn erkennbar Software sendet (Test Patterns, Scan
Converter, OBS, vMix, Loop, …) oder die Maschine wie ein Rechner heißt (`MAC…`, `DESKTOP-…`, …). Sonst
`unknown` mit dem neutralen Symbol – es wird nicht geraten.

Von Hand: `POST /api/label` mit `{"protocol": "ndi", "source": "<id>", "type": "<Typ>"}`; `"auto"` oder `null`
stellt die Automatik wieder her. Die Wahl wird gespeichert und hat Vorrang.

## Quellen, die ihren Namen wechseln, und verschwundene Quellen

- Trägt ein Gerät seine IP-Adresse als Namen (`192.0.2.7 (AUX1)`) und erscheint nach einem Adresswechsel unter
  neuem Namen, während der alte nicht mehr sendet, gilt es als dasselbe Gerät (gleicher Kanalname, genau ein
  sendender Kandidat): Presets und Labels ziehen um, der alte Eintrag entfällt, der alte Name bleibt als Alias
  gültig. `GET /api/choices` liefert `aliases: {<alter Name>: <heutiger Name>}`; alle Aufrufe, die eine Quelle
  nehmen, akzeptieren den alten Namen.
- Steht ein Ziel am Gerät noch auf dem alten Namen, trägt es im Schnappschuss
  `current_source_renamed_to: <heutiger Name>` (sonst `null`) – die Oberfläche soll zum Neuzuweisen auffordern.
- Eine Quelle, die nicht mehr sendet, bleibt `live: false` mit `last_seen` in der Liste, bis
  `source_hold_seconds` (Einstellung, Vorgabe 120 s) abgelaufen ist – länger nur, solange ein Ziel sie noch als
  aktuelle Quelle meldet. `POST /api/source/forget` mit `{protocol, source}` nimmt sie sofort heraus (400, wenn sie
  sendet oder noch zugewiesen ist).
- Neue Quellen kommen über mDNS und erscheinen ohne Neuladen (Schnappschuss über `/ws`, Ereignis-Stream).

## QR-Code zum Verbinden

`GET /api/info` enthält `connect`: die Adressen, die ein Telefon erreicht, die beste zuerst –
`[{kind, label, host, url}]` mit `kind` in dieser Reihenfolge: `lan_ip` (IP im Studionetz, Standard),
`tailscale_name`, `tailscale_ip`, `mdns_name` (zuletzt, weil Android `.local` oft nicht auflöst). Nie `localhost`
oder `127.0.0.1`; fehlende Arten entfallen. `url` ist `http://<host>:<port>/`.

`GET /api/qr.svg[?target=<kind>]` liefert den QR-Code der gewählten Adresse (Vorgabe: die erste aus `connect`)
als `image/svg+xml`: schwarz auf weiß, Fehlerkorrektur M, vier Module Ruhezone; der Header `X-QR-Url` nennt den
Inhalt. Unbekannte Art → 400. Das Panel zeigt den Code nur auf großen Bildschirmen (ab 861 px Breite, bei
Touch ab 1001 px) und bietet `lan_ip` und die Tailscale-Adresse zur Wahl.

## Testbild-Quelle

Eine eigene NDI-Quelle des Servers, Name `<RECHNERNAME in Großbuchstaben> (<name> Testbild)`, 1280×720, RGBA,
gemeldete Bildrate 25, tatsächlich ein Bild je Sekunde und nur, solange mindestens ein Empfänger verbunden ist.
Inhalt: Wortmarke, Name, Rechnername, Rahmen mit Eckmarken und Mittenkreuz, acht Farbbalken (75 %), elf
Graustufen, Uhrzeit und Datum mit blinkendem Punkt, der QR-Code der ersten Adresse aus `connect` und dieselbe
Adresse als Klartext. Sie erscheint in der Kreuzschiene wie jede andere NDI-Quelle (über mDNS).

- `GET /api/testpattern` → `{ok, enabled, available, running, source, connections, frames_sent, size, url, error}`
- `POST /api/testpattern` mit `{"enabled": true|false}` – der Zustand wird dauerhaft gespeichert
- `GET /api/testpattern.jpg` – das Bild als JPEG, auch ohne NDI SDK (`available: false`: dann wird nicht gesendet)

## Systemauslastung: `GET /api/system`

Lesend, ohne Schlüssel; enthält keine Kommandozeilen, Pfade aus Benutzerverzeichnissen oder Schlüssel.

```jsonc
{
  "time": 1790000000.0,
  "host": {
    "cpu_percent": 4.1, "cores_percent": [5.0, 3.9, 4.2, 3.1], "cores": 4, "load": [0.12, 0.2, 0.25],
    "memory": {"total_mb": 3795, "used_mb": 1174, "free_mb": 2621, "percent": 30.9, "swap_used_mb": 0},
    "temperature_c": 50.1,            // null, wenn nicht lesbar
    "undervoltage": false,            // true | false | null
    "throttled": null,                // Firmware-Status; null = ohne Root nicht lesbar
    "cpu_mhz": 1500, "cpu_max_mhz": 1500,
    "disk": {"total_gb": 30.8, "free_gb": 24.5, "percent": 20.4},
    "network": {"rx_kbit": 568, "tx_kbit": 240},
    "uptime_s": 39960
  },
  "processes": {                      // CPU in Prozent EINES Kerns
    "matrix": {"cpu_percent": 2.4, "rss_mb": 90, "threads": 18, "processes": 1, "uptime_s": 3600},
    "companion": {"cpu_percent": 13.0, "rss_mb": 1245, "threads": 119, "processes": 9}
  },
  "warnings": [{"code": "hot", "text": "Heiß: 72 °C"}],   // overheat | hot | undervoltage | throttled | disk_full | memory | load
  "activity": {
    "ndi_receivers": [{"source": "…", "kind": "live", "bandwidth": "lowest", "fps": 12.5, "seconds": 41.0, "viewers": 1, "frames": 500}],
    "ndi_receivers_open": 1, "ndi_stills_total": 25, "preview_available": true,
    "testpattern": {"enabled": true, "running": true, "connections": 1, "frames_sent": 120},
    "clients": {"panels": 2, "event_streams": 1, "mcp_calls": 4, "mcp_last_s": 30},
    "devices": [{"name": "…", "online": true, "detail": "…", "last_poll_s": 2.9, "error": null}],
    "routes": [{"time": "<ISO 8601>", "origin": "panel|companion|http|mcp|preset|salvo|undo", "destination": "…", "source": "…"}],
    "errors": [{"time": "<ISO 8601>", "level": "warning|error", "where": "…", "message": "…"}]
  },
  "history": [{"t": 1790000000, "cpu": 4.1, "mem": 30.9, "temp": 50.1, "matrix": 2.4, "companion": 13.0}],
  "monitor": {"interval_s": 2.0, "sample_cost_ms": 2.6, "samples": 120}
}
```

`?summary=1` liefert nur `{ok, cpu_percent, memory_percent, temperature_c, warnings}` für eine dauerhafte Anzeige.
Jeder Abruf zählt als Zuschauer: der Server misst dann alle 2 s (Vollform) bzw. 5 s (Kurzform), sonst einmal je
Minute. `history` reicht höchstens 180 Messungen zurück und liegt nur im Speicher. Dieselben Daten liefert das
MCP-Werkzeug `get_system_status`.

## Mobilansicht

Reine Sache des Panels, keine eigene Schnittstelle: Sie nutzt den Schnappschuss über `/ws` und schaltet mit
`POST /api/route`, `/api/undo`, `/api/lock`, `/api/unlock` und `/api/presets/<id>/recall` (`origin: "panel"`).

## WebSocket für das Panel: `GET /ws`

Textnachrichten als JSON. Der Client schickt `{"id": <Zahl>, "type": "<Befehl>", …}`; die Antwort ist
`{"id", "type": "result", "success": true, "result": …}` oder `{"id", "type": "result", "success": false,
"error": {"code", "message"}}`. Abonnements liefern danach `{"id", "type": "event", "event": …}`.
(Das ist der Ausschnitt des Home-Assistant-Protokolls, den die Karte benutzt.)

| `type` | Wirkung |
|---|---|
| `av_matrix/subscribe` | Schnappschuss sofort und bei jeder Änderung (200 ms gebündelt, nur wenn geändert) |
| `av_matrix/state` | Schnappschuss einmal |
| `call_service` | `service` = `route` \| `salvo` \| `lock` \| `unlock` \| `undo` \| `refresh_sources`, `service_data` wie in `frontend-api.md` (`destination`: id oder Liste, `source`, `routes`) |
| `subscribe_events` | Ereignisse `av_matrix_routed`: `{event_type, data: {destination, destination_name, protocol, source, previous_source, origin, time}, time_fired}` |
| `unsubscribe_events` | `subscription`: id des Abonnements |
| `av_matrix/label` | wie `frontend-api.md` |
| `av_matrix/discovered` | `{flows: [{flow_id, source, step_id, name, host, driver, manufacturer, model, icon_key}]}` – gefundene, noch nicht eingerichtete Decoder |
| `config_entries/flow/subscribe` | Ereignis (leere Liste), sobald sich die gefundenen Geräte ändern |
| `config_entries/ignore_flow` | `flow_id` – Gerät nicht mehr anbieten |
| `frontend/get_translations` | `{resources: {"component.av_matrix.config.…": Text}}` für den Dialog |
| `config/auth/list` | `[]` |
| `ping` | `{"id", "type": "pong"}` |

## Zugangsschlüssel

`GET /api/token` und `POST /api/token/rotate` antworten `{"token": "…"}` – nur mit Header `X-AVM-Panel: 1`
(das Panel setzt ihn; fremde Seiten scheitern am Herkunfts-Schutz). Der Schlüssel liegt in einer Datei mit
Rechten 600 außerhalb des Programms und wird nie protokolliert.

## MCP: `POST /mcp`

Streamable HTTP, JSON-RPC 2.0, zustandslos; Antwort `application/json` (kein Stream), Benachrichtigungen → 202,
`GET` → 405. Unterstützt: `initialize`, `ping`, `tools/list`, `tools/call`. Werkzeuge mit Schemata in
[`api/mcp-tools.json`](api/mcp-tools.json):

- lesend, ohne Schlüssel: `list_devices`, `list_sources`, `list_destinations`, `get_routing`, `list_presets`,
  `get_preview_url`, `get_system_status`
- schreibend, nur mit `Authorization: Bearer <Zugangsschlüssel>`: `set_route`, `recall_preset`, `save_preset`,
  `delete_preset`, `undo`

Ohne Schlüssel liefert ein schreibendes Werkzeug ein Ergebnis mit `isError: true` und erklärendem Text; ein
falscher Schlüssel im Header → HTTP 401. Ergebnisse stehen als JSON-Text in `content[0].text` und als
`structuredContent`. Fehler aus dem Kern tragen den Code in `_meta.code`. Die Sperrliste gilt auch mit Schlüssel.

## Statische Dateien

`GET /` liefert `static/index.html`, `GET /static/<pfad>` den Rest (Karte, Schriften, Geräte-Grafiken, Marke).
`GET /openapi.json` und `GET /llms.txt` beschreiben die laufende Instanz mit ihren echten Adressen.
