# Strelle AV Matrix – Server

Die Kreuzschiene für **NDI®-Video, Dante®-Audio und ST 2110 (NMOS)** als eigenständiger, sparsamer Dienst – ohne Home Assistant.
Gedacht für einen kleinen Rechner am Regie- oder Schnittplatz (z. B. der Raspberry Pi, auf dem Bitfocus Companion
läuft). Ein einzelner asyncio-Python-Prozess liefert:

- **Browser-Panel** im Strelle Pult-UI (PC, Tablet, Handy): Quellen × Ziele, Schalten, Undo, Sperre, Namensmodus,
  Geräte-IP und Web-Link, Geräteverwaltung mit Netzwerksuche, **Presets**, Live-Aktualisierung
- **NDI-Vorschau**: Standbild in jeder Quellen- und Ziel-Kachel, per Klick eine flüssige Live-Vorschau
- **Mobilansicht** fürs Telefon (eigene Oberfläche: Ziel wählen → Quelle wählen → geschaltet) und ein
  **QR-Code** auf großen Bildschirmen, der die Matrix am Telefon öffnet
- **Testbild-Quelle**: eigene NDI-Quelle mit Logo, Testbild, Uhr und QR-Code für einen Studiobildschirm
- **Systemauslastung**: Anzeige in der Kopfzeile, Seite „System“ (Rechner, Matrix-Dienst und Companion getrennt,
  was der Server gerade tut, Warnungen)
- **HTTP-Schnittstelle** für Companion, Skripte und andere Oberflächen
- **Companion-Modul** mit Rückmeldung (Taste rot = Verbindung bzw. Preset aktiv) und fertigen Seiten
- **MCP-Schnittstelle** für Sprachmodelle (lesen frei, schalten nur mit Zugangsschlüssel)
- **feste Sperrliste**: Ziele, die über keine Schnittstelle verändert werden

*English: standalone, low-footprint NDI®/Dante® crosspoint router with a browser panel, HTTP API, Bitfocus
Companion module and MCP endpoint. It reuses the device drivers and the card of the Home Assistant variant in
this repository. Documentation is in German.*

Der Server ist eine von mehreren Varianten von **Strelle AV Matrix**; die Home-Assistant-Variante liegt in
[`../custom_components`](../custom_components), Überblick in der [README an der Wurzel](../README.md).
Treiber (Magewell Pro Convert, BirdDog, Dante), Datenmodelle, Geräte-Grafiken, Schriften und die Karte kommen
unverändert von dort (`scripts/sync-shared.sh`) – eine Quelle, keine zweite Kopie im Repo.

## Schnell starten (zum Ausprobieren)

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
scripts/sync-shared.sh
.venv/bin/python -m avmatrix --port 8088        # → http://localhost:8088/
```

Geräte richtest du im Panel unter **Geräte → Gerät hinzufügen** ein (Netzwerksuche oder von Hand; das
Dante®-Netzwerk findet seine Geräte selbst). Decoder, die sich per mDNS melden, bietet das Panel von selbst an.

## Auf einen Rechner ausrollen

Voraussetzungen am Ziel: Linux mit Python ≥ 3.12 (`venv`), SSH-Zugang, `loginctl enable-linger <benutzer>`.
**Kein sudo nötig** – der Server läuft als systemd-Benutzerdienst `av-matrix.service` (enabled, Neustart bei Fehler).

```bash
mkdir -p local && cp deploy/deploy.env.example local/deploy.env      # Ziel eintragen
cp deploy/studio.example.json local/studio.json                      # Name, Sperrliste, Tailscale-Name
deploy/deploy.sh                                                     # Tests, rsync, venv, Dienst
deploy/install-ndi-sdk.sh --accept-license                           # nur für die NDI-Vorschau, siehe unten
```

`local/` ist nicht versioniert: dort liegen Ziel, Einstellungen und alles andere, was nur deine Anlage betrifft.

| Was | Wo (auf dem Zielrechner) |
|---|---|
| Programm | `~/av-matrix-server/` (venv in `.venv/`) |
| Einstellungen | `~/.config/av-matrix/config.json` (Rechte 600; Geräte samt Zugangsdaten, Sperrliste) |
| Zugangsschlüssel | `~/.config/av-matrix/token` (Rechte 600, wird beim ersten Start erzeugt) |
| Zustand | `~/.local/share/av-matrix/state.json` (Sperren, Labels, Presets) |
| Protokoll | `~/.local/share/av-matrix/server.log` (rotiert, 3 × 0,5 MB) |
| NDI-Bibliothek | `~/.local/share/av-matrix/ndi/` |

Dienstbefehle: `systemctl --user status|restart|stop av-matrix`. Mehr in [docs/BETRIEB.md](docs/BETRIEB.md).

## Im Netz finden

- `http://<rechnername>.local:8088/` und die IP-Adresse; mit Tailscale zusätzlich Tailnet-Name und -IP
- Bonjour / DNS-SD: Dienst `_http._tcp`, Name wie in `config.json` → `name`
- Der Server lauscht an allen Schnittstellen. Er gehört ins Studionetz bzw. Tailnet – **keine Portfreigabe, kein
  Tunnel nach außen**. Im Studionetz braucht das Panel bewusst keine Anmeldung.

## Sperrliste

`config.json` → `protected` ist eine Liste von Regeln. Ein Ziel ist geschützt, wenn das Protokoll passt **und**
(die Adresse **oder** der Gerätename passt) **und** der Kanal passt:

```json
{"protocol": "dante", "host": "192.0.2.31", "device": "AVIOAES3*", "channels": null, "reason": "…"}
```

Geschützte Ziele erscheinen im Panel als gesperrt und lassen sich weder schalten noch trennen, entsperren, per
Undo zurückstellen oder in Presets aufnehmen – über **keine** Schnittstelle (Panel, HTTP, Companion, MCP).
Durchgesetzt wird das zweimal: im Kern vor jedem Treiberaufruf und zusätzlich im Dante-Treiber, der an geschützte
Kanäle kein Abo-Paket schickt (`avmatrix/guard.py`, Tests in `tests/test_guard.py`). Änderbar nur in der Datei.

## NDI-Vorschau

Echter NDI-Empfang mit dem offiziellen SDK (`libndi`, über ctypes), immer in der **niedrigsten Bandbreite**
(Proxy-Stream, meist 640×360) und nur, solange jemand zuschaut:

- **Standbild** je Kachel: Empfänger öffnen, erstes Bild nehmen, sofort schließen; 4 s zwischengespeichert und
  von allen Panels geteilt. Höchstens 2 Empfänger gleichzeitig.
- **Live** (Klick auf das Symbol im Bild): ein offener Empfänger, höchstens eine Quelle gleichzeitig; er schließt
  3 s, nachdem der letzte Zuschauer weg ist, spätestens nach 10 min. Währenddessen ruhen die Kacheln.
- Kein Panel offen → kein Empfänger, kein Thread, keine Last. Ohne SDK meldet die Schnittstelle `unavailable`;
  Platzhalterbilder gibt es nicht. Fällt eine Quelle weg, zeigt die Kachel „Offline“ / „Kein Signal“.

**NDI|HX** (H.264/HEVC, z. B. viele PTZ-Kameras und HDMI-Encoder) dekodiert `libndi` unter Linux nur mit
FFmpeg (`libavcodec.so.61`, `libavutil.so.59`). Mit Root genügt `sudo apt install libavcodec61`. Ohne Root holt
`deploy/install-hx-decoder.sh` die Debian-Pakete samt fehlender Abhängigkeiten und entpackt sie ins
Benutzerverzeichnis (`~/.local/share/av-matrix/ndi/ffmpeg/`, rund 90 MB; FFmpeg steht unter LGPL/GPL, die
Lizenztexte liegen unter `…/ffmpeg/usr/share/doc/`); der Dienst findet sie beim Start von selbst. Fehlt der
Decoder, zeigt die Kachel „Vorschau nicht möglich (NDI|HX)“ statt eines Bildes – schalten lässt sich die Quelle
trotzdem. HX-Quellen mit eigenem kleinem Stream (viele Kameras) sind günstig; kommt nur das volle Bild, holt der
Server Standbilder seltener (20 s) und zeigt „Live“ als Folge von Standbildern statt als offenen Stream.

Liefert ein Encoder über NDI gar nichts Dekodierbares (bei uns: TBS/LinkPi mit NDI|HX), holt der Server das
Standbild über die **Standbild-Funktion des Geräts** selbst – ohne Dekodierung auf dem Server. Die Kachel trägt
dann den Vermerk „vom Gerät“; „Live“ ist dort eine Folge von Standbildern.

Das **NDI SDK** gehört der Vizrt NDI AB und steht unter dem *NDI SDK License Agreement*
(<https://ndi.video/for-developers/ndi-sdk/>). Es ist **nicht** Teil dieses Repos. `deploy/install-ndi-sdk.sh
--accept-license` lädt es vom Hersteller und legt `libndi.so.6` samt Lizenztexten ins Benutzerverzeichnis des
Zielrechners. Lies die Lizenz, bevor du zustimmst: sie regelt u. a., auf welchen Geräten und in welchen Produkten
das SDK eingesetzt werden darf. NDI® ist eine eingetragene Marke der Vizrt NDI AB.

Messwerte und was wir über den Empfang gelernt haben: [../docs/ndi-preview.md](../docs/ndi-preview.md).

## ST 2110 (NMOS)

Dritter Protokollbereich neben NDI® und Dante®: Geräte, die SMPTE ST 2110 sprechen und sich über NMOS
(IS-04 / IS-05) steuern lassen – z. B. die Blackmagic-2110-IP-Konverter. Sie melden sich per mDNS und erscheinen
von selbst als eigene Gruppe **ST 2110** in der Kreuzschiene, in der Mobilansicht, in Presets (auch gemischt mit
NDI und Dante), im Companion-Modul und in der Systemanzeige.

- Eine Quelle ist **Bild, Ton und Zusatzdaten gemeinsam**; ein Mehrkanalgerät zeigt je Ein-/Ausgang eine Kachel.
- Was nicht zusammenpasst (z. B. ein komprimiertes Signal auf einen Empfänger, der es nicht kann), wird mit
  lesbarem Grund abgelehnt, bevor etwas geschaltet wird.
- **Keine Vorschau:** Der Server spricht nur die Steuerebene; die Kacheln sagen „Keine Vorschau verfügbar“.
- **Geräte → ST 2110 prüfen** zeigt ohne Terminal, was die Geräte melden (Ein-/Ausgänge, PTP, Auffälligkeiten) –
  es wird dabei nichts geschaltet; die Rohdaten gibt es als Download.
- „Ton getrennt schalten“ (ab Werk aus), feste Adressen und eine Registry lassen sich im selben Block einstellen;
  für ein eigenes ST-2110-Netz siehe [docs/BETRIEB.md](docs/BETRIEB.md).

Der Treiber liegt vorerst in [`nmos/`](nmos/) (siehe dort, auch zum späteren Zusammenführen mit der
Home-Assistant-Variante). Getestet ist er gegen eine Simulation der Geräte und die offiziellen AMWA-Schemata,
**noch nicht gegen echte Geräte**.

## Symbole der Quellen

Jede NDI-Quelle zeigt eine Illustration nach ihrem Gerätetyp: Kamera, Rechner, Encoder/Wandler, Testbild – oder
das neutrale „NDI-Quelle“, wenn nichts sicher erkennbar ist. Die Zuordnung ist eine kleine, kommentierte Tabelle
(`avmatrix/source_types.py`: Muster für Gerätename, Kanalname oder die Selbstauskunft der Weboberfläche → Typ).
Unter **Geräte → NDI-Quellen** lässt sich der Typ je Quelle von Hand festlegen; das hat Vorrang und bleibt
gespeichert. Antwortet das Gerät hinter einer Quelle auf `http://<ip>/`, bietet die Kachel den Link zur
Weboberfläche an. Die drei zusätzlichen Illustrationen liegen in `avmatrix/static/devices-extra/`.

## Telefon: QR-Code und Mobilansicht

Auf großen Bildschirmen zeigt der Knopf **Telefon** in der Kopfzeile einen QR-Code mit der Adresse darunter.
Sein Inhalt ist eine Adresse, die ein Telefon wirklich erreicht: die IP im Studionetz (Standard), umschaltbar auf
die Tailscale-Adresse – nie `localhost` und nicht der `.local`-Name, den Android oft nicht auflöst. Der Code
entsteht im Server (`/api/qr.svg`), ohne externen Dienst. Am Telefon selbst erscheint er nicht.

Ein Telefon bekommt automatisch die **Mobilansicht**: erkannt über Bildschirmbreite und Zeigerart (bis 700 px,
oder Touch bis 900 px), umschaltbar über das Menü „⋯“ bzw. „Zur Mobilansicht“ am Seitenende. Tastflächen sind
mindestens 44 px hoch, nichts scrollt seitlich; Vorschaubilder holt sie nur für Kacheln, die gerade im Bild sind.
Presets anlegen, Geräte und die LLM-Verbindung bleiben der Desktop-Ansicht vorbehalten.

## Testbild-Quelle

Unter **Geräte → Testbild-Quelle** einschaltbar. Der Server sendet dann die NDI-Quelle
`<RECHNER> (<Name> Testbild)` – 1280×720 mit Wortmarke, Name, Rahmen und Mittenkreuz, Farbbalken, Graustufen,
Uhr und dem QR-Code samt Adresse. Sie lässt sich wie jede Quelle auf einen Decoder legen. Gesendet wird nur,
solange ein Empfänger verbunden ist, ein Bild je Sekunde; ausgeschaltet gibt es weder Sender noch Thread.
Der Schalter steht in `state.json` und übersteht Neustarts. Braucht das NDI SDK; `/api/testpattern.jpg` zeigt das
Bild auch ohne.

## Systemauslastung

Die Anzeige in der Kopfzeile (CPU, RAM, Temperatur) führt zur Seite **System**: CPU gesamt und je Kern, Load, RAM,
Temperatur, Takt, Unterspannung, Speicherplatz, Netzdurchsatz, Laufzeiten – und getrennt, was der Matrix-Dienst
und was Companion verbrauchen. Dazu, was der Server gerade tut: offene NDI-Empfänger, Testbild, verbundene
Clients, Geräteverbindungen, letzte Schaltvorgänge mit Herkunft, letzte Fehler, ein Verlauf über einige Minuten.
Warnungen (Überhitzung, Unterspannung, Drosselung, voller Speicher, Dauerlast) erscheinen als schraffierte Fläche
mit Symbol und Text – bewusst nicht in Rot oder Bernstein, den Farben für Program und Preset.

Gelesen wird direkt aus `/proc` und `/sys`, nur solange jemand zuschaut (2 s auf der Seite, 5 s für die Anzeige),
sonst einmal je Minute für den Verlauf. Ob die Firmware drosselt, lässt sich ohne Root nicht lesen; angezeigt
werden deshalb Takt, Temperatur und der Unterspannungs-Alarm.

## Schnittstellen

Vollständig und sprachneutral in [docs/SCHNITTSTELLE.md](docs/SCHNITTSTELLE.md), maschinenlesbar in
[docs/api/openapi.json](docs/api/openapi.json) und [docs/api/mcp-tools.json](docs/api/mcp-tools.json); der
laufende Server liefert `/openapi.json` und `/llms.txt`. Das Wichtigste:

```
GET  /api/state                                   alles: Quellen, Ziele, Presets, Sperrliste
GET  /api/status                                  kompakt: routes {Ziel: Quelle}, presets {id: aktiv}
GET|POST /api/route?dest=<Ziel>&source=<Quelle>   Verbindung setzen (source leer / "Aus" trennt)
GET|POST /api/preset/recall?preset=<Name|id>      Preset abrufen
GET|POST /api/undo[?dest=<Ziel>]                  letzte Aktion bzw. dieses Ziel zurück
GET  /api/preview.jpg?source=<NDI-Quelle>&w=320   Standbild
GET  /api/preview.mjpeg?source=<NDI-Quelle>       Live-Vorschau (MJPEG)
GET  /api/qr.svg[?target=tailscale_name]          QR-Code zum Verbinden
GET|POST /api/testpattern                         Testbild-Quelle: Zustand / {enabled: true|false}
GET  /api/system[?summary=1]                      Systemauslastung
POST /mcp                                         MCP (Streamable HTTP)
```

Ziele und Quellen dürfen als `id`, Label oder Name angegeben werden. Schalt-Adressen gehen als GET und POST,
damit sie in Companions generisches HTTP-Modul, ein Lesezeichen oder `curl` passen.

## Bitfocus Companion

`companion/module/` ist ein eigenes Companion-Modul (**Strelle: AV Matrix**): Es hält den Zustand über den
Ereignis-Stream des Servers aktuell, Tasten werten ihn über Rückmeldungen aus. Das ist der robusteste Weg –
der Server muss nichts von Tasten oder Seiten wissen, und Companion fragt nichts zyklisch ab.

- Aktionen: *Verbindung setzen*, *Preset abrufen*, *Letzte Aktion rückgängig*, *Ziel: vorherige Quelle*
- Rückmeldungen: *Verbindung aktiv*, *Preset aktiv*, *Ziel hat keine Quelle* (Vorgabe: Taste rot)
- Auswahllisten mit den echten Zielen, Quellen und Presets; Tasten-Vorlagen zum Ziehen; Variablen je Ziel

```bash
cd companion/module && npm install && npx companion-module-build     # → strelle-avmatrix-<version>.tgz
```

In Companion: **Modules → Import module package** (geht nur von dem Rechner aus, auf dem Companion läuft, oder
über einen SSH-Tunnel auf dessen Port 8000), dann **Connections → Strelle: AV Matrix → Add**
(Vorgabe 127.0.0.1:8088). `companion/make_pages.py` erzeugt zwei Seiten als Import-Dateien – eine mit
Beispieltasten aus den vorhandenen Zielen, Quellen und Presets, eine mit den Zugangsadressen des Panels:
**Import / Export → Import → Destination „Insert new page“** hängt sie hinten an. Vorher exportieren!

Neue Taste: eine vorhandene kopieren und in Aktion **und** Rückmeldung Ziel/Quelle wählen – oder eine
Vorlage aus dem Reiter *Presets* der Tastenansicht auf eine freie Taste ziehen.

## Sprachmodelle (MCP)

Die Seite **LLM-Verbindung** im Panel zeigt die Adresse, den Zugangsschlüssel (erst nach „Anzeigen“), die
fertige Zeile für Claude Code und einen Einrichtungs-Prompt:

```bash
claude mcp add --transport http av-matrix http://<rechner>.local:8088/mcp --header "Authorization: Bearer <Schlüssel>"
```

Lesen geht ohne Schlüssel; alles, was schaltet oder Presets ändert, nur mit. Die Sperrliste gilt auch mit
Schlüssel. Der Schlüssel schützt vor versehentlichem Schalten durch ein Modell – er ist kein Ersatz für ein
abgeschottetes Netz, denn das Panel selbst schaltet im Studionetz ohne Anmeldung.

## Entwickeln

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # spiegelt vorher die gemeinsamen Teile
.venv/bin/ruff check .
scripts/export-spec.py                 # nach Änderungen an der Schnittstelle
```

Tests laufen lokal; es gibt bewusst keinen GitHub-Workflow für den Server. Aufbau:

| Datei | Aufgabe |
|---|---|
| `avmatrix/hub.py` | Kern: Geräte, Quellenregister, Schalten, Undo, Sperren, Presets, Schnappschuss |
| `avmatrix/guard.py` | feste Sperrliste (Kern + Dante-Treiber) |
| `avmatrix/web.py` | HTTP, WebSocket für das Panel, Ereignis-Stream, Vorschau, MCP-Endpunkt |
| `avmatrix/mcp.py` | MCP-Werkzeuge (JSON-RPC, ohne SDK) |
| `avmatrix/preview.py` | NDI-Empfang und JPEG |
| `avmatrix/testpattern.py` | eigene NDI-Testbild-Quelle und QR-Code |
| `avmatrix/sysmon.py` | Systemauslastung aus `/proc` und `/sys` |
| `avmatrix/source_types.py` | Gerätetyp einer NDI-Quelle (Regeltabelle) |
| `avmatrix/nmos_check.py`, `nmos/` | ST 2110: Prüfwerkzeug und Treiber (NMOS) |
| `avmatrix/flows.py` | „Gerät hinzufügen“ (Schritte wie in Home Assistant) |
| `avmatrix/discovery.py` | mDNS: NDI-Quellen, Dante-Geräte, Decoder, eigene Ankündigung |
| `avmatrix/static/` | das Panel: statisches Frontend (`app.js`, `extras.js`, `mobile.js`; die Vorschau in den Kacheln macht die Karte selbst), spricht nur über die Schnittstelle mit dem Backend |

Das Panel ist ein eigenständiges statisches Frontend (kein serverseitiges Rendern). Ein anderes Backend, das
[docs/SCHNITTSTELLE.md](docs/SCHNITTSTELLE.md) erfüllt, kann es unverändert ausliefern.

## Lizenz und Marken

Code: MIT (siehe [../LICENSE](../LICENSE)). Wortmarke und Bildmarke „Strelle“ unter `avmatrix/static/brand/`
sind Marken der Strelle GmbH und **nicht** Teil der MIT-Lizenz – siehe [NOTICE.md](NOTICE.md).
