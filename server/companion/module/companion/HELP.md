# Strelle AV Matrix

Verbindet Companion mit dem **Strelle AV Matrix Server** (NDI®-/Dante®-Kreuzschiene) auf demselben Rechner.

## Einrichtung
Adresse `127.0.0.1`, Port `8088` – das ist die Vorgabe und passt, wenn der Server auf dem Companion-Pi läuft.

## Aktionen
- **Verbindung setzen** – Quelle auf Ziel schalten (Quelle „Aus“ trennt).
- **Preset abrufen** – alle Verbindungen eines Presets auf einmal.
- **Letzte Aktion rückgängig** – nimmt die letzte Schaltung oder das letzte Preset zurück.
- **Ziel: vorherige Quelle** – stellt bei einem Ziel die vorherige Quelle wieder her.

## Rückmeldungen
- **Verbindung aktiv** – wahr, solange genau diese Quelle auf diesem Ziel liegt (Taste rot).
- **Preset aktiv** – wahr, solange der Ist-Zustand dem Preset entspricht (Taste rot).
- **Ziel hat keine Quelle** – wahr, wenn am Ziel nichts anliegt.

## Fertige Tasten
Unter **Presets** (Tasten-Vorlagen) liegen für jeden NDI-Decoder Tasten „Quelle auf Ziel“ und für jedes Preset
des Servers eine Taste – einfach auf eine Taste ziehen.

## Hinweis
Fest geschützte Ziele (Sperrliste des Servers) lehnt der Server ab; sie erscheinen in den Auswahllisten mit
dem Zusatz „gesperrt“.
