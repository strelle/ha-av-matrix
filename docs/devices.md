# Device notes

Field notes about the supported devices, collected while building a conference control room (2026) and while
verifying this integration (October 2026). "Verified" means: seen on a real device with the firmware listed.
Everything marked *untested* comes from documentation, other projects or older firmware.

## General lessons

- **An address is not an identity.** NDI® senders reuse ports when they restart (e.g. quit one app, start another).
  A source is identified by its **NDI name** (`MACHINE (Stream name)`), never by `ip:port`.
- **Receiver source lists can lie.** Some decoders keep sources in their list long after they stopped sending.
  The integration only trusts such a list if the address answers on TCP *and* is not currently used by another,
  live-seen name.
- **Hysteresis.** Sources disappear from option lists only after 2 minutes of absence, so the UI does not jump.
- **Own polling per device** (default every 5 s, 3 s timeout). An offline device is retried with a growing pause
  (10, 20, 30 s) and never slows down the others.
- **mDNS is the best live view.** Every NDI sender announces `_ndi._tcp.local.`; the instance name *is* the NDI name.
  If your network uses an NDI Discovery Server and blocks mDNS, the integration only sees what the decoders list.
- **NDI port 5960:** every NDI sender answers on TCP 5960 (without login) with XML
  `<ndi><services><service name=… port=…/></services></ndi>`. *Not used yet* (planned as an optional extra source
  of truth).

## Discovery signals (verified October 2026, studio LAN)

What the devices actually send, checked with `dns-sd -B _services._dns-sd._udp`, `dns-sd -L`, python-zeroconf, an
SSDP `M-SEARCH ssdp:all`, TCP port checks and the UniFi client list. Read-only, nothing was changed on the devices.

| Signal | Magewell Pro Convert (FW 1.3.24, 2 online + 1 offline) | BirdDog | Dante® (AVIO AES3, HDCVT DA-22UC) |
|---|---|---|---|
| MAC vendor prefix | `D0:C8:57:8…` — **IEEE MA-M block `D0:C8:57:80/28`** of Nanjing Magewell (the rest of `D0:C8:57` belongs to other vendors!); also `70:B3:D5:75:D0/36`. All three studio devices are in the `/28`. | `D4:20:00:A0/28`, `70:B3:D5:3B:90/36`, `70:B3:D5:C7:E0/36` (IEEE registry, *no device here*) | – |
| DHCP host name | the device name set by the user (e.g. `Strelle2`) — useless for matching | *untested* | – |
| mDNS | `<device name>._http._tcp.local.` port 80, **empty TXT record** (no model, no MAC) — no `_ndi._tcp`, no vendor service type | *untested* | `_netaudio-arc/-cmc/-dbc._udp` (+ `_netaudio-chan`) |
| SSDP | no answer | *untested* | – |
| HTTP fingerprint | `GET /mwapi?method=get-summary-info` → `{"status":37}` (not logged in) + cookie `sid`; web UI title `Pro Convert`; server `nginx` | `GET :8080/about` → JSON `HostName`, `FirmwareVersion`, `SerialNumber` (no login) | – |
| Other | TCP **5959 open** (the Pro Convert runs an NDI Discovery Server / listens on the discovery port) | – | – |

Consequences for the integration (`manifest.json`):

- `dhcp`: `macaddress` `D0C8578*`, `70B3D575D*` (Magewell), `D42000A*`, `70B3D53B9*`, `70B3D5C7E*` (BirdDog) and
  `registered_devices: true` (IP changes of devices that are already set up, any vendor).
- `zeroconf`: only `_netaudio-arc._udp.local.` (Dante network). An `_http._tcp` matcher for Magewell is not possible
  without matching every web server on the network.
- Network scan (`Driver.async_probe`): Magewell by the status-37 answer, BirdDog by `/about`.
- Unique id stays the serial number. A Magewell does not tell it before login, so discovery first uses the MAC
  (`magewell-<mac>`) and finds already configured devices through the MAC connection in the device registry.

## Magewell Pro Convert (NDI® → HDMI / SDI / AIO)

| | |
|---|---|
| Verified | Pro Convert **NDI to AIO**, firmware **1.3.24** (October 2026): login, info, sources, current source, routing, status, signal info |
| API | `http://<host>/mwapi?method=…` (JSON) |
| Factory login | `Admin` / `Admin` — **change it** in the web UI |
| Trusted source list | yes (built live by the device) |

- **Login:** `GET /mwapi?method=login&id=<user>&pass=<md5hex(password)>` → `{"status":0}` plus cookie `sid`.
  Send the cookie with every call. (Home Assistant's shared HTTP session ignores cookies from IP addresses, so the
  driver handles `sid` itself.)
- **Status codes** in every answer `{"status": n}`: `0` ok, `36` wrong password (→ re-auth flow), `37` not logged in
  (→ log in again and repeat the call once).
- `get-summary-info` →
  `{"status":0,"device":{"name":"…","model":"NDI to AIO","product-id":1057,"auth-type":4,"serial-no":"…","hw-revision":"A","fw-version":"1.3.24","up-to-date":true,"output-state":"connected",…},"ethernet":{"state":"1000m","mac-addr":"…","ip-addr":"…",…},…}`
  - `device.name` → default display name, `device.serial-no` → unique id, `device.fw-version` → firmware.
  - **Connection state:** `device.output-state` (`"connected"` while a stream is decoded). Some firmware versions also
    have an `ndi` block with `connected`, `video-width/-height`, `video-field-rate`, `video-bit-rate`, `drop-frames`
    (*untested on 1.3.24*; parsed when present).
- `get-signal-info` →
  `{"status":0,"signal-info-types":["video-info"],"video-info":{"codec":"shq2","width":1920,"height":1080,"scan":"progressive","color-depth":8,"field-rate":30.0,"quant-range":"limited","sat-range":"limited","frame-struct":"2d","aspect-ratio":"16:9","color-format":"bt.709","sampling":"4:2:2"}}`
  → resolution sensor `1920x1080p30` (`scan: interlaced` → `1920x1080i<field-rate>`), attributes `codec`,
  `color_format`, `sampling`, …
- `get-channel` → `{"status":0,"name":"HOST (Test Patterns)","ndi-name":true}`. `ndi-name:false` means a channel
  preset stored on the device (shown as `[preset] <name>`).
- `get-ndi-sources` → `{"status":0,"sources":[{"ndi-name":"HOST.LOCALDOMAIN (Test Patterns)","ip-addr":"x.x.x.x:5961"}]}`
- **Observed:** the currently selected source does not have to be in `get-ndi-sources` (it may have stopped sending).
  The integration still shows it as current option, marked *not live*.
- **Routing:** `set-channel&ndi-name=true&name=<NDI name, URL-encoded>` → `{"status":0}`. After **~2 s**
  (up to 5 s) `output-state` is `connected` and `get-channel` returns the new source. The integration polls
  immediately and again after 3 s. Off: `set-channel&ndi-name=true&name=` (empty name).
- **Tally:** not reported by the Pro Convert.
- Stored channels: `list-channels`, `add-channel&name=…&url=ntkndi://ndi?name=<NDI>&url=<ip>%3A<port>` (*untested*,
  not used).

## BirdDog (PLAY, Mini, Flex, Studio NDI …)

| | |
|---|---|
| Verified | BirdDog **PLAY**, firmware **1.0.14** — in an earlier project (2026), *not yet with this integration* |
| API | `http://<host>:8080` (JSON), usually **without login** |
| Factory password | `birddog` (protects the web UI on port 80) |
| Trusted source list | **no** (contains stale entries) |

- `GET /about` → `FirmwareVersion`, `HostName` (e.g. `LOBBY-PLAY.local`), `IPAddress`, `SerialNumber`, `Status`.
- `GET /List` → `{"NAME (Stream)": "ip:port", …}`; empty list = `{"None":"None"}`.
  **Contains stale sources** (laptops that left, old ports after a restart).
- `POST /refresh` rebuilds the list (older firmware: `GET /refresh`). Stale entries sometimes survive until a reboot;
  the integration hides them because they do not answer on TCP.
- `GET /connectTo` → `{"sourceName": …}`; `POST /connectTo` with body `{"sourceName":"MACHINE (Name)"}`
  (`Content-Type: application/json`) switches immediately.
- **Some firmware does not switch reliably** → the driver reads back `/connectTo` and retries once.
- **Off** (empty `sourceName`) — *untested*.
- **Non-ASCII names** (umlauts, en dash …) are listed as `NDI_<hex id>` and must be routed with exactly that name.
  The integration maps the id to the real name through the address that name currently uses.
- **Logo instead of black:** if the selected source stops sending, BirdDog shows its logo. The integration reports
  `source_lost` in that case.
- `GET /decodestatus` → status / resolution / frame rate — *untested*, parsed defensively; if the endpoint does not
  exist the connection state is derived from the source registry.
- **Authentication:** if the API answers 401/403, the driver logs in via `POST /login` (form field `auth_password`,
  cookie `BirdDogSession`, port 80 first, then 8080) and retries once — *untested*, modelled after
  [mtcdtech/ha-birddog-ndi](https://github.com/mtcdtech/ha-birddog-ndi).
- **Multi-channel devices:** `ChNum` (1–4) in the `/connectTo` body and query — *untested*. Set "Number of decoder
  channels" in the config flow to get one destination per channel.

## Dante® (any device with the Dante control protocol)

| | |
|---|---|
| Verified (read-only) | October 2026, studio network: **Audinate AVIO AES3** adapter and an **HDCVT ULTIMOX2**-based Dante interface, both ARC `2.8.9`, router `4.3.0`, 2×2 channels, 48 kHz: discovery, names, channel counts, TX/RX names, sample rate, subscriptions and subscription status |
| Not verified on hardware | **switching** (setting / clearing subscriptions) - checked against netaudio's reference packets and the test simulator only |
| Control | ARC, UDP 4440 (port from mDNS), no login |
| Integration | one config entry for the whole network (*Dante® network*) |

- **Discovery:** each device announces `_netaudio-arc._udp` (control, port 4440), `_netaudio-cmc._udp` (port 8800,
  TXT `id=` = hardware id), `_netaudio-dbc._udp` (4455). The ARC TXT record has `arcp_vers` (e.g. `2.8.9`), `mf`,
  `model` (some OEM devices send a cryptic `_0000000020240403` - `router_info` is used instead, e.g. `ULTIMOX2`),
  `router_vers`. `_netaudio-chan._udp` (per channel) was not announced by these devices and is not needed.
- **Requests** (all with protocol id `0x27FF`): header `protocol, length, sequence, opcode` + body; answers carry the
  same sequence number (used to match answers) and a result code after the opcode (`0x0001` ok, `0x8112` ok + more
  pages). Strings are zero-terminated and referenced by absolute offsets into the packet.
  - `0x1002` device name, `0x1000` channel counts (TX at offset 12, RX at 14),
  - `0x2000` TX channels (32 per page: number, flags, format pointer → sample rate, name pointer),
    `0x2010` TX labels (only channels with a label),
  - `0x3000` RX channels (16 per page, 20-byte records: number, flags, format, TX channel, TX device, RX name,
    receiver status, subscription status).
- **Answers may come with a different protocol id** than requested (a `0x2809` request was answered with `0x2801`),
  so the integration matches by sequence number and opcode only.
- **Writes:** devices with ARC 2.8.9 or newer (`arcp_vers`) need the paged subscription command `0x3410` with
  protocol id `0x2809`/`0x280C`/`0x280F`; older ones the classic `0x3010` (add) / `0x3014` (remove). Static hosts
  without mDNS data: classic first, paged if the read-back shows no change.
- **Subscription status:** code `1` with receiver status `0x0101` = subscribed, with `0` = *unresolved* (the
  transmitting device is not on the network) - both studio devices showed this for their stored subscriptions to
  devices that were switched off. `9` dynamic (unicast), `10` static (multicast), `4` own device, `2`/`8` resolving /
  setting up, `5` source channel does not exist, `0x10`+ errors (format, latency, clock domain, flows …).
- A subscription stays stored on the receiver when the transmitter disappears and resolves again when it returns -
  the integration keeps such a source as the current option (marked not live).
- Renaming a device in Dante Controller changes its identity (also for Dante itself: subscriptions use names) -
  the integration creates a new device; the old one can be deleted in Home Assistant once it is offline.
