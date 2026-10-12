# Betrieb

Kurz, was man im Alltag braucht. Alles Anlagenspezifische (Adressen, Sicherungen, Tastenbelegung) gehört in
`server/local/` – der Ordner ist nicht versioniert.

## Dienst

```bash
systemctl --user status av-matrix      # läuft er?
systemctl --user restart av-matrix     # neu starten (Zustand, Presets und Sperren bleiben erhalten)
tail -f ~/.local/share/av-matrix/server.log
```

Der Dienst ist ein systemd-Benutzerdienst (`~/.config/systemd/user/av-matrix.service`), `enabled`, startet nach
einem Neustart des Rechners von selbst (dafür muss einmal `loginctl enable-linger <benutzer>` gesetzt sein) und
nach einem Fehler erneut. Er läuft mit niedrigerer Priorität (`Nice=5`) und Obergrenzen für Speicher, damit
Companion auf demselben Rechner Vorrang hat.

## Aktualisieren

Auf dem Arbeitsrechner im Repo: `git pull`, dann `server/deploy/deploy.sh`. Das Skript spiegelt die gemeinsamen
Teile aus der Integration, lässt die Tests laufen, überträgt per rsync und startet den Dienst neu.
Einstellungen, Zugangsschlüssel und Zustand auf dem Zielrechner fasst es nicht an.

Neue Version des Companion-Moduls: `companion/module` bauen und das Paket in Companion unter *Modules → Import
module package* einspielen; in der Verbindung die neue Version wählen.

## Einstellungen (`~/.config/av-matrix/config.json`)

| Schlüssel | Bedeutung |
|---|---|
| `name` | Name im Panel und als Bonjour-Dienst |
| `port` | Vorgabe 8088 |
| `devices` | eingerichtete Geräte – pflegt das Panel, enthält Zugangsdaten der Decoder |
| `protected` | feste Sperrliste, siehe README |
| `scan_interval` | Abfrage der Geräte in Sekunden (Vorgabe 5; je Gerät überschreibbar) |
| `addresses` | `tailscale_name`, `mdns_name`, `lan_ip`, `tailscale_ip` – nur nötig, wenn die Erkennung nicht passt |
| `preview` | `enabled`, `max_live`, `max_parallel`, `thumb_ttl`, `live_fps`, `live_linger`, `live_max_seconds`, `hx_ttl`, `hx_live` (`stills`/`stream`), `fail_ttl` |
| `source_hold_seconds` | so lange bleiben verschwundene Quellen als „offline“ sichtbar (Vorgabe 120) |
| `memory_restart_mb` | über diesem Speicherverbrauch startet sich der Dienst neu (Vorgabe 240, 0 = aus) |
| `mdns` | `false` schaltet Suche und Ankündigung ab |
| `mdns_interface` | `"all"` = an allen Schnittstellen suchen (z. B. zweites Netz für ST 2110); Vorgabe: nur die Adresse des Studionetzes |
| `nmos_auto` | `false` = den Eintrag „ST 2110“ nicht von selbst anlegen |
| `ignored_hosts` | gefundene Decoder, die nicht mehr angeboten werden |

Nach Änderungen von Hand: `systemctl --user restart av-matrix`. Eine kaputte Datei überschreibt der Server
nicht – er startet dann nicht und sagt im Protokoll, warum.

## ST 2110 (NMOS)

Der Eintrag „ST 2110“ wird beim ersten Start von selbst angelegt und bleibt unsichtbar, bis sich ein Gerät meldet.
Am Liefertag: Gerät anstecken, im Panel **Geräte → ST 2110 prüfen** – der Dialog zeigt, welche Geräte antworten,
welche Ein- und Ausgänge sie melden, ob PTP eingerastet ist und was auffällt. Dabei wird nichts geschaltet;
„Rohdaten herunterladen“ liefert alles für die Fehlersuche. Im Terminal dasselbe mit
`.venv/bin/python -m avmatrix.nmos_check` (mit `--probe` ein Probe-Schaltvorgang samt Zurückschalten).

Für den Tag, an dem Switch und Wandler kommen, gibt es eine eigene Liste: [INBETRIEBNAHME-ST2110.md](INBETRIEBNAHME-ST2110.md).

**Was „ST 2110 prüfen“ außerdem sagt.** *Registry:* ob eine NMOS-Registry im Netz ist und antwortet. Ohne
Registry melden sich die Geräte direkt (Peer-to-Peer) – das ist der Normalfall und kein Fehler. *Taktgeber:*
welche Uhr den Takt gibt (PTP-Grandmaster, mit Gerätenamen, wenn es eines der gefundenen Geräte ist) und ob alle
Geräte auf dieselbe hören. Verschiedene Taktgeber oder „nicht eingerastet“ heißt: kein stabiles Bild.

**Schalten an anderer Stelle.** Die Kreuzschiene ist nicht der einzige Ort, an dem geschaltet werden kann: Ein
Blackmagic Ethernet Switch hat ein eigenes Bedienfeld, die Wandler haben ein Menü. Was dort geschaltet wird,
zeigt die Kreuzschiene nach wenigen Sekunden (Panel, Companion-Tasten, Schnittstellen); im Verlauf auf der Seite
*System* steht es mit der Herkunft „Extern“. „Rückgängig“ am Ziel stellt den Zustand vor dieser Umschaltung
wieder her. Wer das Schalten am Switch verhindern will: dort die Taste LOCK eine Sekunde halten.

**Switch auf der Geräteseite.** Ein Switch, der selbst NMOS spricht, steht im Block „ST 2110 (NMOS)“ als
„Netzwerk-Switch“ mit Adresse und online/offline; gibt er den Takt, trägt er die Marke „Taktgeber“. Sein
Statusbild und sein Monitorausgang erscheinen als Quelle und Ziel, wenn er sie meldet.

**Eigenes Netz / VLAN für ST 2110.** mDNS geht nicht über Netzgrenzen. Steht der Rechner nicht im selben Netz wie
die Geräte, findet er sie nicht von selbst. Dann eines von beidem:

1. Dem Rechner eine zweite Adresse im ST-2110-Netz geben (zweite Netzwerkkarte oder VLAN-Schnittstelle – braucht
   Root auf dem Rechner). Der Server sucht per mDNS nur an der Adresse des Studionetzes; deshalb zusätzlich in
   `config.json` unter dem Eintrag `nmos` die Geräte eintragen (Punkt 2) **oder** die Suche auf alle Schnittstellen
   stellen: `"mdns_interface": "all"`.
2. Ohne zweite Adresse, wenn das Netz geroutet wird (der Rechner erreicht die Geräte per IP): im Panel unter
   **Geräte → ST 2110 → Feste Adressen** die Adressen der Geräte eintragen (`192.0.2.31` oder `192.0.2.31:8090`;
   ohne Port werden 8090, 80, 3212 und 8080 probiert) oder unter **Registry** die Adresse einer NMOS-Registry
   (`http://192.0.2.5:8010`; eine Registry im selben Netz wird per mDNS von selbst gefunden). In der Datei: `devices` → Eintrag `nmos` → `options.static_hosts` /
   `options.registries`.

Schalten braucht nur HTTP zum Gerät (Steuerebene); die Medienströme laufen zwischen den Geräten und nie über
diesen Rechner. Weitere Optionen des Eintrags: `audio_breakaway` (Ton getrennt schaltbar, ab Werk aus),
`check_compat: false` (falls ein Gerät unbrauchbare Fähigkeiten meldet und zu Unrecht abgelehnt wird),
`enable_senders: false` (ausgeschaltete Sender beim Schalten nicht einschalten).

## Wenn etwas nicht geht

- **Panel nicht erreichbar:** Dienststatus, dann `curl http://127.0.0.1:8088/api/info` auf dem Rechner selbst.
- **Gerät „offline“:** Seite *Geräte* zeigt die letzte Fehlermeldung; „Anmeldung abgelehnt“ → Gerät entfernen
  und mit den richtigen Zugangsdaten neu hinzufügen.
- **ST-2110-Gerät fehlt oder schaltet nicht:** *Geräte → ST 2110 prüfen*; steht es in einem anderen Netz, siehe oben.
- **ST 2110: Bild ruckelt, friert ein oder fehlt trotz Verbindung:** *ST 2110 prüfen* → Zeile „Taktgeber“. Es darf
  nur einen geben; an allen anderen Geräten „PTP follower only“ einschalten.
- **Ein ST-2110-Ziel steht plötzlich auf einer anderen Quelle:** Seite *System* → Verlauf; „Extern“ heißt, es wurde
  am Switch oder an einem anderen Pult geschaltet.
- **Dante-Gerät fehlt:** es meldet sich nicht per mDNS → *Geräte → Feste Adressen*.
- **Companion-Tasten ohne Rückmeldung:** in Companion unter *Connections* muss „avmatrix“ grün sein.
- **Vorschau zeigt nichts:** `curl http://127.0.0.1:8088/api/preview` – `available: false` nennt den Grund.
- **Zugangsschlüssel verloren oder weitergegeben:** Panel → *LLM-Verbindung* → *Schlüssel erneuern*.

## Sichern

`~/.config/av-matrix/` (Einstellungen, Schlüssel) und `~/.local/share/av-matrix/state.json` (Presets, Labels,
Sperren). Vor Änderungen an Companion immer dessen Konfiguration exportieren (*Import / Export → Export*).
