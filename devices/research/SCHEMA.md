# Rechercheformat je Gerät (eine JSON-Datei pro Gerät)
{
  "id": "blackmagic/atem-2me-constellation-hd",          // hersteller/modell, klein, Bindestriche
  "manufacturer": "...", "model": "...", "category": "switcher|converter|router|recorder|streamer|monitor|mixer|wireless|decoder|control|computer|camera|display",
  "rack_units": 1, "power": "...",
  "ports": [  // JEDE physische Buchse einzeln oder als Gruppe mit count
    {"id": "sdi_in", "label": "SDI In", "count": 10, "direction": "in|out|bidi",
     "connector": "BNC|HDMI-A|USB-C|XLR3F|XLR3M|TRS-6.3|TRS-3.5|RCA|RJ45|SFP+|QSFP28|etherCON|DIN|IEC|DC|...",
     "signal": "SDI-12G|SDI-3G|HDMI|analog-audio|AES3|Dante|ST2110|Ethernet|USB|timecode|reference|power|...",
     "formats": "z. B. 1080p50, 2160p50; 48 kHz",
     "notes": "z. B. Loop-Out von SDI In 1, PoE, Ein-/Ausgang umschaltbar"}
  ],
  "logic": [  // innere Signalwege als Bausteine
    {"type": "passthrough|switch|matrix|mixer|converter|encoder|decoder|recorder|splitter", "from": ["port ids"], "to": ["port ids"], "notes": "..."}
  ],
  "control": [{"protocol": "z. B. ATEM 9910/UDP, Videohub 9990, HyperDeck 9993, REST, NMOS IS-04/05, OSC 2223, Dante", "notes": "..."}],
  "sources": [{"url": "...", "what": "techspecs|manual S. 12|..."}],
  "unverified": ["Angaben, die nicht belegt werden konnten"]
}
Regeln: nur Herstellerquellen (Produktseite, Tech Specs, Handbuch-PDF); jede Angabe belegbar; Unklares in "unverified", nichts erfinden.
