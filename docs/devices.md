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
