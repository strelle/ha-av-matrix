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
  "version": "0.1.0",
  "protocols": {
    "ndi": {                                   // one key per protocol that has destinations or sources
      "title": "NDI®",
      "sources": [                             // sorted by name
        {
          "id": "STUDIO-PC (Slides)",          // identity; pass this as `source` when routing
          "name": "Slides",                    // label if set, else id
          "label": "Slides",                   // user label or null
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
          "name": "Lobby",                     // device name, plus " · Channel n" on multi-channel devices
          "channel": null,                     // channel name or null
          "device_name": "Lobby",
          "group": null,                       // Dante®: the device of the RX channel (sub-device), else null
          "device_id": "4f1c…",                // HA device registry id
          "entry_id": "01J…",
          "driver": "magewell",
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

## `av_matrix/label` (admin only)

Set or clear a label and tags of a source (persisted in `.storage/av_matrix`).

```js
await hass.connection.sendMessagePromise({
  type: "av_matrix/label",
  protocol: "ndi",
  source: "NDI_0A1B2C3D4E",       // source id
  label: "Präsentation",          // null or "" clears the label
  tags: ["presentation", "stage"] // null or [] clears tags
});
// → result: { "label": "Präsentation", "tags": ["presentation", "stage"] }  ({} when cleared)
```

Labels are also accepted by the services and appear as `select` options.

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

## Card loading

The integration serves `/av_matrix_static/av-matrix-card.js` and registers it with `frontend.add_extra_js_url`,
so the custom element `av-matrix-card` is available on every dashboard without a manual resource.
A replacement card can be shipped the same way (same file name) or as a separate HACS frontend repository.
