# Frontend API (WebSocket + services)

Everything a dashboard card needs. State comes from the WebSocket API, actions are normal service calls.
All commands require an authenticated Home Assistant WebSocket connection (`hass.connection` in a card).

## `av_matrix/state`

One-shot snapshot.

```js
const state = await hass.connection.sendMessagePromise({ type: "av_matrix/state" });
```

## `av_matrix/subscribe`

Sends the full snapshot right after subscribing and again on every change (debounced 200 ms; identical snapshots
are not sent twice). Changes include: device polls, source appearing/disappearing/live changes, routes,
locks, labels, linked display results.

```js
const unsub = await hass.connection.subscribeMessage(
  (state) => render(state),
  { type: "av_matrix/subscribe" }
);
// later: unsub();
```

## Snapshot format

```jsonc
{
  "version": "0.9.0",
  "preview": {                                 // see "Preview pictures"
    "configured": true,                        // a preview server is set in the options
    "reachable": true,                         // true | false | null (not asked yet / not configured)
    "available": true,                         // the server can receive NDI (false: SDK missing, preview off)
    "reason": null,                            // the server's reason while available is false
    "hx_decoder": true,                        // the server can decode NDI|HX
    "server": { "name": "Strelle AV Matrix", "version": "1.0.0" },
    "protocols": ["ndi"],                      // protocols with pictures ([] if not configured)
    "still_url": "/api/av_matrix/preview.jpg",
    "stream_url": "/api/av_matrix/preview.mjpeg",
    "status_url": "/api/av_matrix/preview"
  },
  "protocols": {
    "ndi": {                                   // one key per protocol that has destinations or sources
      "title": "NDI®",
      "video": true,                           // the protocol carries pictures
      "preview": true,                         // pictures exist for its sources (preview server configured)
      "sources": [                             // sorted by name
        {
          "id": "STUDIO-PC (Slides)",          // identity; pass this as `source` when routing
          "name": "Slides",                    // label if set, else id
          "label": "Slides",                   // user label or null
          "original_name": "STUDIO-PC (Slides)", // name on the network (NDI name, Dante channel@device)
          "icon_key": "ndi_computer",          // device illustration, see "Device illustrations"
          // NDI only:
          "device_type": "computer",           // camera | computer | encoder | testpattern | unknown
          "web_url": null,                     // web UI of the sender if the preview server found one, else null
          "tags": ["presentation"],            // user tags (categories), may be []
          "live": true,                        // sending right now
          // grouped protocols (Dante®) only:
          "group": "STAGEBOX-A",               // device of the source (Dante: TX device)
          "channel": "Kick",                   // channel on that device
          "host": "192.0.2.40",                // informational, may be null
          "address": "192.0.2.40:5961",        // informational, may be null — never an identity
          "last_seen": "2026-10-04T12:00:05+00:00",   // last time it was live (null if never)
          "first_seen": "2026-10-04T09:12:00+00:00"
        }
      ],
      "destinations": [                        // sorted by name
        {
          "id": "magewell-a123456789_main",    // stable destination id
          "entity_id": "select.lobby_source",  // use this for service calls (null if the entity is disabled → use "id")
          "name": "Lobby",                     // label if set, else original_name
          "label": null,                       // user label of the destination or null
          "original_name": "Lobby",            // device name, plus " · Channel n" on multi-channel devices
          "tags": [],                          // user tags of the destination
          "channel": null,                     // channel name or null
          "device_name": "Lobby",
          "group": null,                       // Dante®: the device of the RX channel (sub-device), else null
          "device_id": "4f1c…",                // HA device registry id
          "entry_id": "01J…",
          "driver": "magewell",
          "manufacturer": "Magewell",          // from the device / mDNS, may be null
          "model": "Pro Convert NDI to AIO",   // may be null
          "icon_key": "magewell_ndi_aio",      // device illustration
          "host": "192.0.2.20",                // IP address / host name of the device (Dante®: of the Dante device), may be null
          "web_url": "http://192.0.2.20",      // web UI of the device as the driver knows it, null if it has none (Dante®)
          "protocol": "ndi",
          "current_source": "STUDIO-PC (Slides)",   // source id or null (= None/off)
          "current_source_live": true,
          "status": "connected",               // connected | connecting | no_source | source_lost | error | offline
          "resolution": "1920x1080p50",        // video format, Dante®: sample rate ("48 kHz"), or null
          "subscription": null,                // Dante®: {"state", "code", "status", "detail"} of the RX subscription
          "available": true,                   // false while the device is unreachable
          "locked": false,
          "can_undo": true,
          "display": {                         // null if no linked display is configured
            "entity_id": "media_player.lobby_tv",
            "state": "on",
            "source": "HDMI 2",
            "source_list": ["HDMI 1", "HDMI 2"],
            "configured_input": "HDMI 2",
            "auto_on": true,
            "off_on_none": false,
            "error": null                      // last linked-display error text, or null
          }
        }
      ]
    }
  }
}
```

Notes:
- The current source of a destination is always in `sources`, even if it is not live (`live: false`,
  `last_seen: null` if the registry never saw it).
- Sources stay in the list for 2 minutes after they stopped sending (`live: false`), then disappear.
- Dante®: sources are ordered by device and channel; `entity_id` is `null` for RX channels whose entities are
  disabled (devices with > 32 RX channels by default) - route them with `destination: [id]`.
- `status` meanings: `connected` = decoding; `connecting` = just routed / device still connecting;
  `no_source` = routed to None; `source_lost` = routed source is not sending (BirdDog shows its logo);
  `offline` = device unreachable; `error` = the device reports an error (Dante: subscription error, see
  `subscription.status` / `detail`).

- Do not assume two protocols: build tabs and lists from the keys of `protocols` and take the name from `title`.
  Show a picture area only where `video` is true; where `preview` is false say "no preview available" (never
  "no signal"), or show no picture area at all.

## Preview pictures

Optional. Home Assistant does not receive NDI; it relays the preview API of a Strelle AV Matrix server
(`server/docs/SCHNITTSTELLE.md`, "NDI-Vorschau") whose address is set in the options of the integration
(stored in `.storage/av_matrix`, key `preview_server`). All three views need a Home Assistant login. They are
relays and not `camera` / `image` entities because sources come and go (an entity per source would fill the
registry), the server's states must reach the card unchanged, and nothing may be cached.

| View | Purpose |
|---|---|
| `GET /api/av_matrix/preview.jpg?source=<source id>[&w=64…640]` | Current still (JPEG, default width 320). |
| `GET /api/av_matrix/preview.mjpeg?source=<source id>[&w=160…1280][&fps=1…25]` | Live preview, `multipart/x-mixed-replace`. Ends when the source is gone, after 10 minutes, or when another source takes the server's one live receiver. Close the connection to end it. |
| `GET /api/av_matrix/preview[?source=<source id>]` | The server's status JSON (`available`, `hx_decoder`, `live: [{source, frames, seconds, state, mode}]`, with `source`: `source: {id, state}`); opens no receiver. |

`source` is the exact NDI name (the `id` of the source), never a label.

```js
// still: with the login token, so the headers can be read
const res = await hass.fetchWithAuth(`/api/av_matrix/preview.jpg?source=${encodeURIComponent(id)}&w=320`);
const state = res.headers.get("X-Preview-State");          // "ok" or the reason
// live: an <img> cannot send a token - let Home Assistant sign the path
const { path } = await hass.callWS({ type: "auth/sign_path", path: `/api/av_matrix/preview.mjpeg?source=${encodeURIComponent(id)}`, expires: 30 });
img.src = hass.hassUrl(path);
```

Answers carry `Cache-Control: no-store` and the server's headers `X-Preview-State`, `X-Preview-Origin` (`ndi`, or
`device` = a still the device delivered itself: mark it), `X-Preview-Age`, `X-Preview-Size`. Without a picture
the body is JSON `{"ok": false, "error": <state>, "message": …}`:

| `X-Preview-State` | HTTP | Meaning |
|---|---|---|
| `offline`, `unknown_source` | 404 | The server knows the source but it is not sending / does not know it. |
| `no_signal` | 503 | The source is there but delivered no picture. |
| `unsupported_codec` | 415 | NDI\|HX source, the decoder is missing on the server. |
| `unavailable` | 501 | The server cannot receive NDI (SDK missing or preview off). |
| `not_configured` | 404 | No preview server is set. |
| `unreachable` | 502 | Home Assistant gets no answer from the server. |
| `bad_response` | 502 | Something answers, but not like a Strelle AV Matrix server. |
| `invalid` | 400 | `source` is missing. |

Be frugal - every still is a real NDI receiver on the server, and there is one live receiver: fetch only what is
on screen, every 4-5 s per source, at most two at a time, not while the page is hidden; never show a picture
older than ~15 s as current; while a live preview is open let the tiles rest. Home Assistant merges identical
requests and allows two requests to the server at a time.

## `av_matrix/label` (admin only)

Set or clear a label and tags of a source or a destination (persisted in `.storage/av_matrix`). Labels are display
names for the card ("Label | Original | both" switch); entity names in Home Assistant are not changed by
destination labels.

```js
await hass.connection.sendMessagePromise({
  type: "av_matrix/label",
  protocol: "ndi",
  source: "NDI_0A1B2C3D4E",       // source id
  label: "Präsentation",          // null or "" clears the label
  tags: ["presentation", "stage"] // null or [] clears tags
});
// → result: { "label": "Präsentation", "tags": ["presentation", "stage"] }  ({} when cleared)

await hass.connection.sendMessagePromise({
  type: "av_matrix/label",
  kind: "destination",            // default "source" (backwards compatible)
  destination: "magewell-a123456789_main",   // destination id
  label: "Foyer left"             // null or "" clears
});
```

Errors: `unknown_protocol`, `unknown_destination`, `invalid_format` (source missing), `unauthorized` (not admin).

Labels are also accepted by the services and appear as `select` options.

## `av_matrix/discovered` (admin only)

Devices Home Assistant discovered (DHCP / zeroconf) that wait for confirmation: the integration's config flows
started by a discovery source. The card shows them as *"n new receivers found"* and continues the flow with the
REST flow API (`GET/POST /api/config/config_entries/flow/<flow_id>`; texts from `frontend/get_translations`,
category `config`). Re-read it on `config_entries/flow/subscribe` events.

```js
const { flows } = await hass.connection.sendMessagePromise({ type: "av_matrix/discovered" });
// → { "flows": [ {
//      "flow_id": "01J…", "source": "dhcp",            // dhcp | zeroconf | ssdp | integration_discovery
//      "step_id": "confirm",
//      "name": "Magewell 192.0.2.127", "host": "192.0.2.127",
//      "driver": "magewell", "manufacturer": "Magewell", "model": null,
//      "icon_key": "magewell_pro_convert"               // device illustration
//    } ] }
```

Sorted by name. `host` may be `null` (Dante® network flow). Errors: `unauthorized` (not admin).

## Services (actions)

| Service | Data | Notes |
|---|---|---|
| `av_matrix.route` | `entity_id` and/or `device_id` and/or `destination` (destination ids, one or many), `source` | `source`: id, label, or `"None"` (off). Unknown names are passed through (the source may not be discovered yet). |
| `av_matrix.salvo` | `routes: [{destination: <select entity_id or destination id>, source}]` | All destinations validated first (unknown/locked → nothing switches). Different devices switch in parallel. |
| `av_matrix.lock` / `av_matrix.unlock` | `entity_id` / `device_id` / `destination` | Persistent. Locked destinations reject route/salvo/undo/select. |
| `av_matrix.undo` | `entity_id` / `device_id` / `destination` | Restores the previous source (history of 10 per destination, in memory). |
| `av_matrix.refresh_sources` | `entity_id` / `device_id` | Device rebuilds its source list; cached liveness is dropped. |
| `media_player.turn_on` / `turn_off` | `entity_id: display.entity_id` | For a power button of a linked display. |

```js
await hass.callService("av_matrix", "route", { entity_id: "select.lobby_source", source: "STUDIO-PC (Slides)" });
```

## Event

`av_matrix_routed` — fired after every successful route:

```json
{ "entity_id": "select.lobby_source", "destination": "magewell-a123456789_main", "destination_name": "Lobby",
  "protocol": "ndi", "source": "STUDIO-PC (Slides)", "previous_source": null,
  "origin": "service | select | salvo | undo" }
```

The event is fired with the context of the action that caused it, so `event.context.user_id` identifies the user
(null for automations without a user). The card resolves it to a name via `config/auth/list` for admins.

## Device illustrations

`icon_key` names an SVG in `/av_matrix_static/devices/<icon_key>.svg` (shipped with the integration). The key is
derived in `device_icons.py` from driver, manufacturer, model and device name (Dante: mDNS model or the default
name prefix such as `AVIOAES3-`, `DA-22UC-`, `WING`). NDI sources get the key of their `device_type`
(`source_types.py`, the rule table shared with the server: `ndi_camera`, `ndi_computer`, `ndi_encoder`,
`ndi_testpattern`, and the neutral `ndi_source` when no rule matches - it is not guessed); a configured preview
server overrides it with what it found out. Keys: `magewell_ndi_aio`, `magewell_pro_convert`, `birddog_play`,
`ndi_decoder`, `ndi_camera`, `ndi_computer`, `ndi_encoder`, `ndi_testpattern`, `ndi_source`,
`avio_aes3`, `avio_analog_in`, `avio_analog_out`, `avio_usb`, `dante_converter`, `wing`, `dante_device`, `display`.
The SVGs use CSS custom properties: `--avm-led` (status LED colour, set by the card), `--avm-dev-body`,
`--avm-dev-top`, `--avm-dev-side`, `--avm-dev-line`, `--avm-dev-metal`, `--avm-dev-screen`.

## Card loading

The integration serves `/av_matrix_static/av-matrix-card.js` and registers it with `frontend.add_extra_js_url`,
so the custom element `av-matrix-card` is available on every dashboard without a manual resource.
The Strelle marks of the brand line are in `/av_matrix_static/brand/` (see NOTICE).
A replacement card can be shipped the same way (same file name) or as a separate HACS frontend repository.
