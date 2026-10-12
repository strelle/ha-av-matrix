# ST 2110 (NMOS) – Treiber im Server

Dritter Protokolltyp der Kreuzschiene neben NDI® und Dante®: Geräte, die SMPTE ST 2110 sprechen und sich über
AMWA NMOS (IS-04 / IS-05) steuern lassen. Der Treiber liegt **vorerst nur hier im Server**:

| Datei | Inhalt |
|---|---|
| `drivers/nmos.py` | `NmosNetwork`: Geräte finden und abfragen, Schalten über IS-05, Offline-Verhalten |
| `protocols/nmos.py` | IS-04 lesen, Gruppen bilden (Bild + Ton + Zusatzdaten), Kompatibilität, Quellenregister |
| `protocols/nmos_mdns.py` | mDNS-Suche (`_nmos-node._tcp`, `_nmos-query._tcp`) |
| `icons/st2110_*.svg` | fünf Geräte-Illustrationen |
| `../avmatrix/nmos_check.py` | Prüfwerkzeug (`python -m avmatrix.nmos_check`, im Panel „ST 2110 prüfen“) |
| `../tests/nmos/` | Tests, Simulation der Geräte (`nmos_sim`), AMWA-Schemata (Apache 2.0, siehe `schemas/LICENSE`) |

## Wie er eingehängt wird

Die anderen Treiber spiegelt `scripts/sync-shared.sh` aus der Home-Assistant-Variante
(`../../custom_components/av_matrix`). Danach kopiert dasselbe Skript die Dateien aus diesem Ordner in die
gespiegelten Pakete (`avmatrix/drivers`, `avmatrix/protocols`, `avmatrix/static/devices`) und ruft
`scripts/register-nmos.py` auf. Das trägt ein:

- `drivers/__init__.py`: `NmosNetwork` in `DRIVERS`
- `protocols/__init__.py`: `"st2110": Protocol("st2110", "ST 2110", NmosSourceRegistry, video=True)`
- `device_icons.py`: Regeln für die fünf Grafiken und den Rückfall `st2110_device`

Findet `register-nmos.py` eine dieser Stellen nicht mehr, bricht es mit Hinweis ab – dann hat sich die Integration
geändert und die Stelle ist hier nachzuziehen.

## Später: Zusammenführen mit der Home-Assistant-Variante

Sobald die Integration ST 2110 bekommt, wandert der Treiber dorthin und der Server spiegelt ihn wie alle anderen:

1. `drivers/nmos.py` → `custom_components/av_matrix/drivers/`, `protocols/nmos*.py` →
   `custom_components/av_matrix/protocols/`, `icons/*.svg` → `custom_components/av_matrix/frontend/devices/`.
2. Die drei Einträge aus `register-nmos.py` fest in die Integration schreiben
   (`drivers/__init__.py`, `protocols/__init__.py`, `device_icons.py`).
3. Tests `tests/nmos/test_nmos_{model,driver,mdns,schemas}.py`, `nmos_sim/` und `schemas/` nach `tests/` an der
   Wurzel; in `scripts/sync-shared.sh` in die Liste der gespiegelten Tests aufnehmen (Importe
   `custom_components.av_matrix` ↔ `avmatrix` ersetzt das Skript). `test_nmos_hub.py`, `test_nmos_server.py` und
   `test_nmos_check.py` bleiben im Server.
4. In `scripts/sync-shared.sh` den Block „ST 2110 (NMOS)“ und `scripts/register-nmos.py` entfernen, diesen Ordner
   löschen.
5. In der Integration bleibt zu tun, was der Server schon hat: mDNS-Browser für `_nmos-node._tcp`, Optionen des
   Netzwerk-Eintrags, Quellen-/Zielfelder (`format`, `layers`, `breakaway`, `partial`), Texte.

Der Server braucht dabei keine Änderung: Er spricht den Treiber nur über die gemeinsame Treiber-Schnittstelle an.

## Was der Treiber dem Kern zusichert

- `async_poll()` wirft nie wegen eines einzelnen Geräts; ein Gerät, das zweimal nicht antwortet, ist offline, seine
  Ziele bleiben stehen.
- `async_route()` wirft nur `RouteFailed` mit kurzem deutschem Text; schlägt eine Ebene fehl, werden die schon
  geschalteten zurückgestellt.
- Kein Medienempfang, kein Thread, kein eigener Socket außer HTTP über die übergebene Session. Ruhezustand: ein GET
  je Gerät und Abfrage, einmal je Minute ein voller Abruf.

## Belegt und angenommen

Die fünf Blackmagic-Geräte (2110 IP Mini IP to HDMI, Presentation Converter, Mini BiDirect 12G, Converter 4x12G PWR,
DeckLink IP/SDI HD) sind nach Handbuch und technischen Daten **simuliert**; Mitschnitte ihrer NMOS-Schnittstelle
gab es nicht. Belegt: IS-04 v1.3, IS-05 v1.1, getrennte Ströme für Bild, Ton und Zusatzdaten, IP10 bei 2160p60.
Annahme: wie die Geräte ihre Ströme benennen und gruppieren, wie der Empfänger die Verbindung beschrieben haben
will, ob der 4x12G als ein Node oder als vier erscheint (beides ist getestet). „ST 2110 prüfen“ zeigt am echten
Gerät, was davon stimmt.
