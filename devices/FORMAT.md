# AV Device Profile (AVDP) und AV Rig – Entwurf 0.1

Vorbild ist die Lichttechnik: **GDTF** beschreibt einen Gerätetyp, **MVR** ein ganzes Projekt mit eingebetteten GDTF-Dateien.
Hier dasselbe für Bild- und Tontechnik.

| Datei | Inhalt | Vorbild |
|---|---|---|
| `profiles/<hersteller>__<modell>.json` | ein Gerätetyp oder ein Modul: Anschlüsse, innere Logik, Steuerung, Steckplätze, Quellen | GDTF |
| `projects/<projekt>.json` | Geräteinstanzen, gesteckte Module, Kabel, Signalflüsse im Netz, aktueller Patch; Profile eingebettet | MVR |

## Geräteprofil (`format: "avdp/0.1"`)

- `ports[]` – jede Buchse oder Buchsengruppe (`count`): `direction` in/out/bidi, `connector` (BNC, HDMI-A, XLR3F, TRS-6.3, RJ45, etherCON, SFP+ …), `signal` (SDI-12G, HDMI, analog-audio, Dante, ST2110 …), `formats`, `notes`.
  Eine einzelne Buchse einer Gruppe heißt im Projekt `<port>.<n>`, z. B. `sdi_in.11`.
- `logic[]` – innere Wege aus fünf Bausteinen: `passthrough` (fest, z. B. Loop-Out), `switch` (Eingangswahl), `matrix` (Kreuzschiene, z. B. ATEM-Aux),
  `mixer` (Mischer, z. B. ATEM-M/E, Pultsumme), `converter`/`encoder`/`decoder` (Formatwandlung), `recorder`, `splitter`.
- `slots[]` – Steckplätze mit `accepts` (erlaubte Modulprofile). Ein Modul ist ein eigenes Profil mit `slot` und `fits`; gesteckt bringt es seine Ports und Logik mit.
- `control[]` – wie die Kreuzschiene das Gerät live liest und schaltet (ATEM, NMOS, Dante, OSC, HyperDeck …).
- `sources[]` – Herstellerquelle je Angabe; `unverified[]` – nicht belegte Punkte.
- `status` – `draft` (z. B. von der LLM-Brücke aus dem Handbuch erzeugt) oder `verified` (von einem Menschen am Gerät geprüft).

## Projekt (`format: "avrig/0.1"`)

- `instances[]` – `id`, `profile`, `name`, `address`, `modules` {Steckplatz: Modulprofil}, Lage in der Ansicht.
- `cables[]` – physische Verbindung `from` → `to` (Instanz:Port), mit `medium` (SDI, HDMI, XLR, Cat6 …).
- `flows[]` – Signalfluss über ein Netz (NDI, Dante, ST 2110, RTMP), über welches Netzgerät er läuft.
- `routes[]` – aktueller innerer Patch eines Geräts (z. B. ATEM Aux 10 ← In 11), live aus der Kreuzschiene oder geplant.
- `embedded` – alle verwendeten Profile, damit ein Import ohne Bibliothek funktioniert.

## Rack (bautechnischer Verbund)

Ein Rack fasst Geräte zusammen, die fest gemeinsam verbaut sind, samt ihrer festen inneren Verkabelung (z. B. WING-Rack mit WING, ULXD4Q,
Router und PoE-Switch). Ein Rack ist wie ein Gerät wiederverwendbar: als eigene Datei exportieren, in jedes Projekt importieren.

- im Projekt: `racks[]` mit `id`, `name`, `members[]` (Instanz-IDs); Kabel innerhalb eines Racks tragen `"fixed": true`.
- Übergabepunkte (`ports[]` des Racks) sind die Buchsen, an denen andere Racks oder Geräte angeschlossen werden – z. B. der Uplink des
  PoE-Switch zur Videoregie. Beim Aufbau vor Ort muss man nur noch diese Verbindungen stecken und prüfen.

## Set (Zubehör-Bündel, `format: "avkit/0.1"`)

Optionales Zubehör, das als Einheit transportiert und gesteckt wird – z. B. Kamera + Fiber-Wandler + LC-Kabel. Innen fest verkabelt,
nach außen nur seine Übergabe-Ports (`ports[]`). `accepts[]` nennt die Buchsen, an die es passt (z. B. Patchfeld LC I/O 1/2).
Im Konfigurator wird ein Set per Drag and Drop auf eine passende Buchse gezogen; die ganze Kette ist danach verbunden.
Sets liegen in `kits/`.
