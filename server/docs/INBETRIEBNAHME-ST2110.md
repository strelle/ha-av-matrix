# ST 2110 in Betrieb nehmen: Blackmagic Ethernet Switch 360P und 2110-Wandler

Eine Liste zum Abhaken für den Tag, an dem die Geräte kommen. Was hier als „belegt“ steht, stammt aus den
Handbüchern und technischen Daten von Blackmagic Design; die Fundstellen stehen in
[`../nmos/README.md`](../nmos/README.md). Adressen und Namen der eigenen Anlage gehören nicht hierher, sondern
nach `server/local/`.

## Vorher (ohne Geräte)

- [ ] Auf einem Rechner (Mac oder Windows) von blackmagicdesign.com/support installieren: **Blackmagic Ethernet
      Switch Setup** und **Blackmagic Converters Setup**; für DeckLink-Karten **Desktop Video**.
- [ ] USB-C-Kabel bereitlegen (Switch und Wandler lassen sich darüber einstellen, auch ohne Netzwerk).
- [ ] Netzwerkkabel: CAT 6 oder besser für alle 10G-Strecken (lange Strecken: CAT 6A).
- [ ] Kreuzschiene läuft: Panel öffnen, Seite **Geräte** – der Block „ST 2110 (NMOS)“ ist da und noch leer.

## 1. Verkabeln

| Gerät | Anschluss am Gerät | wohin |
|---|---|---|
| Ethernet Switch 360P | Strom | Steckdose (zweite Einspeisung 12 V über XLR ist möglich, nicht nötig) |
| Ethernet Switch 360P | einer der 16 Anschlüsse „10G“ | normales Studionetz (siehe „Verbindung zum Studionetz“) |
| Ethernet Switch 360P | SDI oder HDMI „Monitor“ | ein Bildschirm – zeigt je Anschluss, wie viel Daten laufen |
| 2110 IP Converter 4x12G PWR | die **vier** Buchsen „10G 2110 IP“ | vier 10G-Anschlüsse am Switch (je Buchse ein Kanal) |
| 2110 IP Converter 4x12G PWR | Buchse „1G Ethernet“ | normales Studionetz (Einstellen mit Converters Setup) |
| Mini-Wandler (IP to HDMI, BiDirect 12G) | 10G-Buchse | 10G-Anschluss am Switch |
| Presentation Converter | 10G-Buchse | 10G-Anschluss am Switch |
| Rechner mit DeckLink IP | 10G-Buchse der Karte | 10G-Anschluss am Switch |

- Die beiden 100G-Anschlüsse (QSFP) bleiben frei; sie sind für weitere Switches oder 100G-Geräte.
- Die technischen Daten des 360P nennen keine Stromversorgung über das Netzwerkkabel. Die kleinen Wandler brauchen
  deshalb ihr eigenes Netzteil.

**Verbindung zum Studionetz.** Der Rechner mit der Kreuzschiene muss die Geräte erreichen – er steuert sie über
das Netzwerk, Bild und Ton laufen nie über ihn. Am einfachsten: ein Kabel von einem 10G-Anschluss des Switch zum
normalen Studio-Switch (die Anschlüsse können auch 1 Gbit). Dann bekommen Switch und Wandler ihre Adresse vom
Router (alle stehen ab Werk auf DHCP), und die Kreuzschiene findet sie von selbst.

> **Am ersten Tag beobachten:** Am Monitorausgang des Switch zeigt jeder Anschluss seine Datenrate. Sobald Bilder
> laufen, darf der Anschluss zum Studionetz **nicht** dauerhaft mit Hunderten Megabit senden. Tut er es, landen
> die Videoströme im Studionetz und bremsen es aus – dann das Kabel ziehen und melden (das Handbuch sagt nicht,
> wie der Switch das behandelt). Die Kreuzschiene erreicht die Geräte dann über „Feste Adressen“, siehe unten.

## 2. Switch einstellen

Switch einschalten, Sprache wählen. Dann per USB mit **Ethernet Switch Setup** verbinden:

- [ ] Reiter **Setup** → Name vergeben (so heißt er später in der Kreuzschiene). Software aktualisieren, falls
      das Programm es anbietet.
- [ ] Reiter **Setup** → Network: „DHCP“ lassen. Die angezeigte Adresse notieren.
- [ ] Reiter **2110** → **PTP Clock Settings**: „PTP follower only“ **aus** – der Switch gibt den Takt.
      Domain auf 127 lassen. Die „Grandmaster ID“ notieren.
- [ ] Reiter **2110** → **NMOS**: „IP Configuration“ auf **Auto** (oder „Peer to Peer“). Nicht „Disabled“.
- [ ] „Transmit 2110 Media“: Werkseinstellung lassen.
- [ ] Reiter **2110** → Sender Label: ein Name für das Statusbild des Switch (erscheint als Quelle).

Multicast und IGMP: Dazu gibt es am Switch nichts einzustellen.

## 3. Wandler und Karten einstellen (jedes Gerät einmal)

Mit **Converters Setup** (USB oder Netzwerk). Für DeckLink-Karten gilt dasselbe sinngemäß in **Desktop Video
Setup**; deren Handbuch ist hier nicht ausgewertet.

- [ ] Name vergeben, Ein- und Ausgänge benennen (z. B. „CAM 1“, „MON 2“). Diese Namen erscheinen in der
      Kreuzschiene **und** am Bedienfeld des Switch; dessen Kurzwahltasten (CAM, MON …) filtern danach.
- [ ] **PTP follower only: ein.** Domain 127 – dieselbe wie am Switch.
- [ ] NMOS (bei manchen Modellen „NMOS Registry“): „Auto“ lassen. Nicht ausschalten.
- [ ] Netzwerk: DHCP lassen.

## 4. Reihenfolge beim Einschalten

1. Switch – eine Minute warten, bis er läuft.
2. Wandler und Karten.
3. Im Panel der Kreuzschiene: **Geräte → ST 2110 prüfen**.

## 5. „ST 2110 prüfen“ – so soll es aussehen

- [ ] Alle Geräte stehen in der Liste und „antworten“ – auch der Switch (als „Netzwerk-Switch“).
- [ ] Zeile **Registry**: „Keine Registry im Netz – die Geräte melden sich direkt“ ist in Ordnung. Steht dort
      „Registry gefunden“, ist das auch in Ordnung.
- [ ] Zeile **Taktgeber**: genau **eine** Kennung, am besten mit dem Namen des Switch dahinter, und „Alle Geräte
      … hören auf ihn“. Die Kennung stimmt mit der notierten „Grandmaster ID“ überein.
- [ ] Kein Gerät „PTP nicht eingerastet“.
- [ ] Unten **Rohdaten herunterladen** und die Datei aufheben – sie zeigt, wie sich die echten Geräte melden.

Wenn etwas nicht stimmt:

| Anzeige | Ursache | Abhilfe |
|---|---|---|
| „verschiedene Taktgeber“ | ein Wandler hält sich selbst für den Taktgeber | an diesem Gerät „PTP follower only“ einschalten |
| „PTP nicht eingerastet“ | andere Domain, oder das Gerät sieht den Switch nicht | Domain 127 prüfen, Kabel am 10G-Anschluss prüfen |
| ein Gerät fehlt | NMOS am Gerät aus, oder es hat keine Adresse | im Setup-Programm NMOS auf „Auto“; Adresse ablesen und unter **Geräte → ST 2110 → Feste Adressen** eintragen |
| gar kein Gerät | der Rechner der Kreuzschiene erreicht das Netz der Geräte nicht | Verbindung zum Studionetz prüfen (Schritt 1) |
| der Switch fehlt, die Wandler sind da | er meldet sich nicht als NMOS-Gerät | kein Fehler der Kreuzschiene; seine Adresse unter „Feste Adressen“ versuchen |

## 6. Probe schalten

- [ ] In der Kreuzschiene eine ST-2110-Quelle auf ein Ziel schalten – Bild und Ton kommen am Ausgang an.
- [ ] Am **Switch** umschalten: OUT drücken, Ziel wählen, IN drücken, Quelle wählen, TAKE. Die Kreuzschiene zeigt
      die neue Quelle nach wenigen Sekunden; auf der Seite **System** steht die Umschaltung mit „Extern“.
- [ ] In der Kreuzschiene am selben Ziel **Rückgängig** – es steht wieder die Quelle von vorher.
- [ ] Soll am Switch niemand schalten: dort **LOCK** eine Sekunde halten (zum Lösen zwei Sekunden).

## Was erst die echten Geräte zeigen

- wie die Geräte ihre Ein- und Ausgänge benennen und zusammenfassen (Bild, Ton, Zusatzdaten);
- ob der 4x12G als ein Gerät mit vier Kanälen erscheint oder als vier Geräte;
- ob der Switch sein Statusbild und den Monitorausgang als Quelle und Ziel meldet;
- ob am Switch geschaltete Verbindungen sofort erscheinen oder (einmalig) erst nach bis zu einer Minute;
- ob der Anschluss zum Studionetz frei von Videoströmen bleibt (Schritt 1).

Alles davon steht in den Rohdaten aus Schritt 5.
