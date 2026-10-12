# ST 2110 (NMOS) – Treiber im Server

Dritter Protokolltyp der Kreuzschiene neben NDI® und Dante®: Geräte, die SMPTE ST 2110 sprechen und sich über
AMWA NMOS (IS-04 / IS-05) steuern lassen. Der Treiber liegt **vorerst nur hier im Server**:

| Datei | Inhalt |
|---|---|
| `drivers/nmos.py` | `NmosNetwork`: Geräte finden und abfragen, Schalten über IS-05, Offline-Verhalten |
| `protocols/nmos.py` | IS-04 lesen, Gruppen bilden (Bild + Ton + Zusatzdaten), Kompatibilität, Quellenregister |
| `protocols/nmos_mdns.py` | mDNS-Suche (`_nmos-node._tcp`, `_nmos-query._tcp`, `_nmos-register._tcp`) |
| `icons/st2110_*.svg` | sechs Geräte-Illustrationen (darunter `st2110_switch`) |
| `../avmatrix/nmos_check.py` | Prüfwerkzeug (`python -m avmatrix.nmos_check`, im Panel „ST 2110 prüfen“) |
| `../tests/nmos/` | Tests, Simulation der Geräte (`nmos_sim`: Nodes, Registry, zweiter Controller), AMWA-Schemata (Apache 2.0, siehe `schemas/LICENSE`) |

## Wie er eingehängt wird

Die anderen Treiber spiegelt `scripts/sync-shared.sh` aus der Home-Assistant-Variante
(`../../custom_components/av_matrix`). Danach kopiert dasselbe Skript die Dateien aus diesem Ordner in die
gespiegelten Pakete (`avmatrix/drivers`, `avmatrix/protocols`, `avmatrix/static/devices`) und ruft
`scripts/register-nmos.py` auf. Das trägt ein:

- `drivers/__init__.py`: `NmosNetwork` in `DRIVERS`
- `protocols/__init__.py`: `"st2110": Protocol("st2110", "ST 2110", NmosSourceRegistry, video=True)`
- `device_icons.py`: Regeln für die Grafiken und den Rückfall `st2110_device`

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
  je Gerät und Abfrage, einmal je Minute ein voller Abruf; eine Registry wird alle sechs Abfragen nach ihrer
  Geräteliste gefragt (ein GET).
- `pop_external_changes()` nennt die Ziele, die seit dem letzten Aufruf jemand anderes umgeschaltet hat
  (`(Ziel, Quelle vorher, Quelle jetzt)`). Eigene Schaltungen, Umbenennungen und Geräte, die offline gehen oder
  wiederkommen, zählen nie dazu.

## Mehrere Controller, Registry, Switch

**Zweiter Controller.** NMOS kennt keinen „Besitzer“ einer Verbindung: Jeder Controller darf jeden Empfänger
schalten. Der Treiber liest deshalb bei jeder Abfrage `/receivers` jedes Geräts (IS-04 spiegelt die Verbindung in
`subscription`) und zeigt, was dort steht – gleich, wer geschaltet hat. Drei Absicherungen für Geräte, die IS-04
nicht sauber nachziehen:

1. Ändert sich nur der Versionsstempel eines Empfängers, nicht aber `subscription`, wird sofort IS-05 `active`
   gelesen. Weicht es ab, gilt für dieses Gerät ab dann IS-05 bei jeder Abfrage (ein GET je Empfänger mehr).
2. Der volle Abruf einmal je Minute vergleicht IS-04 mit IS-05 und schaltet bei Abweichung ebenso um.
3. Im Peer-to-Peer-Betrieb löst ein geänderter mDNS-Zähler (`ver_rcv` …) sofort einen vollen Abruf aus.

Ein Gerät, das IS-04 gar nicht nachzieht und noch nie von der Kreuzschiene geschaltet wurde, zeigt die erste
fremde Umschaltung daher spätestens nach einer Minute, jede weitere mit der nächsten Abfrage.
IS-04-Websockets gibt es nur an einer Registry (Query API), nicht am Gerät selbst; da das Zielnetz ohne Registry
läuft, bleibt es bei der Abfrage im Fünf-Sekunden-Takt (`scan_interval`).

Der Kern (`avmatrix/hub.py`, `note_external`) trägt fremde Umschaltungen mit der Herkunft `extern` in den Verlauf
ein, hängt den Zustand davor an die Undo-Liste des Ziels und nimmt das Ziel aus älteren eigenen Aktionen heraus –
„letzte Aktion rückgängig“ springt so nie über eine fremde Schaltung hinweg. Presets bleiben unberührt.

**Registry.** Gefunden wird ein Gerät über mDNS (`_nmos-node._tcp`), über eine Registry (Query API, per mDNS
`_nmos-query._tcp` oder von Hand eingetragen) oder über eine feste Adresse – alle Wege gleichzeitig. Ein Gerät ist
durch seine Node-Kennung bestimmt, nicht durch seine Adresse: Wer über zwei Wege oder unter zwei Adressen
(Medien- und Steueranschluss) auftaucht, erscheint einmal; die Adresse, die antwortet, bleibt, die andere wird als
Ausweichadresse gemerkt und erst benutzt, wenn die erste ausfällt. Nennt die Registry mehrere Adressen, werden alle
probiert. Fällt die Registry aus, bleiben die gefundenen Geräte bedienbar. Eine Registry, die nur ihre
Registration API ankündigt (`_nmos-register._tcp`), wird vermerkt („ST 2110 prüfen“ sagt es), aber nicht abgefragt.

**Switch.** Ein Netzwerk-Switch, der selbst ein NMOS-Node ist, bekommt den Gerätetyp `switch` (Symbol
`st2110_switch`). Erkannt wird er am Namen („Ethernet Switch“ in Label, Beschreibung oder Hostname). Meldet er
Sender oder Empfänger, sind es gewöhnliche Quellen und Ziele; meldet er keine, steht er nur auf der Geräteseite.
Den Taktgeber benennt der Treiber, wenn die PTP-Kennung (`gmid` aus IS-04 `clocks`) zur MAC-Adresse eines
gefundenen Geräts passt (`…-ff-fe-…` in der Mitte); passt keine, wird nur die Kennung gezeigt.

## Blackmagic Ethernet Switch 360P: belegt und offen

Quellen: Handbuch „Blackmagic Ethernet Switch“ (Blackmagic Design, © 2026, englischer Teil S. 4–36), technische
Daten auf blackmagicdesign.com (Abruf 12.10.2026), Handbuch „Blackmagic 2110 IP Converters“.

Belegt:

- NMOS IS-04 v1.3.2 „Peer-to-peer via mDNS/DNS-SD“, IS-05 v1.1.2, BCP-002-01, BCP-004-01; PTP nach IEEE 1588-2008,
  ST 2059-1/-2 (technische Daten, „IP Video Compliance“).
- Eingebauter NMOS-Controller und eingebaute PTP-Uhr: „Your Ethernet switch includes a built in PTP clock and NMOS
  controller“ (S. 8). Geschaltet wird am Gerät mit OUT/IN/TAKE; Geräte am Switch erscheinen dort von selbst.
- Der Switch ist selbst Quelle und Ziel: Das Statusbild ist „available as a SMPTE-2110 video source on your
  network“ (S. 20, nur Bild, 1080p50/59,94/60; in der Quellenliste „Status“), der SDI-Monitorausgang ist ein
  2110-Ziel („Monitor SDI“, S. 21). Der Sendername „will appear as a source when routing streams via the setup
  utility or an NMOS controller“ (S. 24).
- NMOS-Betriebsart einstellbar: „auto, peer to peer or manual registry“ oder „disabled“ (S. 26). Dieselbe
  Einstellung haben die Wandler („check auto to automatically discover the NMOS registry“).
- PTP: Der Switch kann Taktgeber werden, solange „PTP follower only“ nicht gesetzt ist; Priorität, Domain
  („commonly 127“), Announce-Werte einstellbar; „Grandmaster ID“ und „PTP Lock“ werden angezeigt (S. 25).
  „Ethernet Switch acts as a boundary clock“ steht im Abschnitt über die PTP-Anschlüsse des Modells 820 (S. 6).
- Verwaltung: Programm „Blackmagic Ethernet Switch Setup“ über USB oder Ethernet (S. 22, 31); Adresse ab Werk per
  DHCP (S. 18); Name als `<Name>.local`. Frontplatte sperrbar (LOCK, S. 19).
- „Transmit 2110 Media“: Blackmagic-Controller starten den Sender beim Schalten selbst (S. 26). Die Kreuzschiene
  tut das auch (`enable_senders`), die Einstellung darf also auf „on NMOS transmit request“ bleiben.

Offen (steht in keiner der Quellen):

- Ob der Switch eine **Registry** betreibt. Genannt sind nur Controller und Peer-to-Peer; eine Registration- oder
  Query-API des Switch ist nirgends erwähnt. Die Kreuzschiene kommt mit beidem zurecht.
- Ob die Wandler per mDNS sichtbar bleiben, wenn sie sich an einer Registry angemeldet haben.
- IGMP: Das Switch-Handbuch nennt weder Snooping noch Querier noch eine Einstellung dazu („there are no complex
  multicast settings to configure“, S. 3). Das Wandler-Handbuch verlangt von Switches IGMPv3-Snooping und führt
  den 360P als geeignet. Wie er Multicast an einem Anschluss ins übrige Hausnetz behandelt, ist nicht beschrieben.
- Eine Steuerschnittstelle außer NMOS (REST, Videohub-Protokoll): nicht dokumentiert. Die Kreuzschiene braucht
  keine – sie schaltet die Empfänger direkt und liest den Zustand dort.
- Ob der 360P die im Handbuch genannten Anschlüsse „1G Management“, „1G Control“ und „PTP“ hat: Die technischen
  Daten des 360P führen nur 16 × 10G, 2 × 100G, SDI, HDMI und USB-C; die drei gehören demnach zum Modell 820.
- Wie sich der Switch in IS-04 genau meldet (Namen, Gruppen-Tags, ob der Monitorausgang als Empfänger erscheint,
  ob die Taktgeber-Kennung aus seiner MAC-Adresse gebildet ist). Simuliert ist die naheliegende Form
  (`tests/nmos/nmos_sim/blackmagic.py`, `ethernet_switch_360p`); „ST 2110 prüfen“ zeigt die echte.

## Belegt und angenommen

Die fünf Blackmagic-Geräte (2110 IP Mini IP to HDMI, Presentation Converter, Mini BiDirect 12G, Converter 4x12G PWR,
DeckLink IP/SDI HD) sind nach Handbuch und technischen Daten **simuliert**; Mitschnitte ihrer NMOS-Schnittstelle
gab es nicht. Belegt: IS-04 v1.3, IS-05 v1.1, getrennte Ströme für Bild, Ton und Zusatzdaten, IP10 bei 2160p60.
Annahme: wie die Geräte ihre Ströme benennen und gruppieren, wie der Empfänger die Verbindung beschrieben haben
will, ob der 4x12G als ein Node oder als vier erscheint (beides ist getestet). „ST 2110 prüfen“ zeigt am echten
Gerät, was davon stimmt.
