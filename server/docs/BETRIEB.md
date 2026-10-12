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
| `ignored_hosts` | gefundene Decoder, die nicht mehr angeboten werden |

Nach Änderungen von Hand: `systemctl --user restart av-matrix`. Eine kaputte Datei überschreibt der Server
nicht – er startet dann nicht und sagt im Protokoll, warum.

## Wenn etwas nicht geht

- **Panel nicht erreichbar:** Dienststatus, dann `curl http://127.0.0.1:8088/api/info` auf dem Rechner selbst.
- **Gerät „offline“:** Seite *Geräte* zeigt die letzte Fehlermeldung; „Anmeldung abgelehnt“ → Gerät entfernen
  und mit den richtigen Zugangsdaten neu hinzufügen.
- **Dante-Gerät fehlt:** es meldet sich nicht per mDNS → *Geräte → Feste Adressen*.
- **Companion-Tasten ohne Rückmeldung:** in Companion unter *Connections* muss „avmatrix“ grün sein.
- **Vorschau zeigt nichts:** `curl http://127.0.0.1:8088/api/preview` – `available: false` nennt den Grund.
- **Zugangsschlüssel verloren oder weitergegeben:** Panel → *LLM-Verbindung* → *Schlüssel erneuern*.

## Sichern

`~/.config/av-matrix/` (Einstellungen, Schlüssel) und `~/.local/share/av-matrix/state.json` (Presets, Labels,
Sperren). Vor Änderungen an Companion immer dessen Konfiguration exportieren (*Import / Export → Export*).
