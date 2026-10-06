# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [SemVer](https://semver.org/).

## [0.4.0] - 2026-10-06

### Added
- **Device illustrations** in the card: own, stylised SVG drawings of the devices (Magewell Pro Convert NDI to AIO
  and other Pro Convert models, BirdDog PLAY, Audinate AVIO AES3 / analog / USB adapters, small Dante converters such
  as HDCVT DA-22UC, Behringer WING-style consoles, generic NDI cameras/computers/decoders, Dante devices, displays).
  The status LED in the drawing shows the destination status. New snapshot fields `icon_key`, `manufacturer`, `model`;
  the mapping lives in `device_icons.py` (rules on driver, manufacturer, model, Dante default name prefix) and is
  easy to extend (see CONTRIBUTING).
- **Names like on a broadcast router panel:** `Label | Original | Both` switch in the card header (key `N`, remembered
  per browser, YAML option `name_mode`, default `both`). Search finds labels and original names.
- **Labels for destinations** (decoder outputs, Dante RX channels): `av_matrix/label` with `kind: "destination"`
  (backwards compatible), snapshot fields `label`, `original_name`, `tags` for destinations and `original_name` for
  sources; label editor in the card for destinations. Entity names are not changed.
- Integration icon and logo (`brand/`), README header.

### Commits

- feat: device illustrations, Label/Original/Both names, destination labels, integration icon (effa53a)

## [0.3.1] - 2026-10-05

### Fixed
- Dante: switching back to a source of an offline/unknown device failed (the option vanished from the select as soon
  as it was no longer the current subscription). The source select now keeps recently seen/assigned sources per RX
  channel (current subscription, last 5 sources, undo history); the card shows them as offline.
- Dante: `av_matrix.route` / `salvo` accept any source in the form `channel@device`, also for devices that are offline
  or unknown (subscription "unresolved"); a malformed source is a translated validation error instead of a failed
  route. NDI behaviour is unchanged.

### Commits

- fix: Dante sources of offline devices stay selectable, route validates channel@device (0a12c21)

## [0.3.0] - 2026-10-05

### Added
- **Dante®** as a second protocol (*experimental*): one *Dante® network* config entry covers all Dante devices,
  found via mDNS (`_netaudio-arc._udp`, also offered by zeroconf discovery) or static addresses; TX channels are
  sources (`channel@device`), RX channels destinations, routing sets/clears subscriptions (ARC over UDP, paged
  `0x3410` writes for ARC 2.8.9+, classic `0x3010/0x3014` otherwise) with read-back. Pure Python, no new
  requirements. Protocol knowledge from the public-domain netaudio project (see NOTICE).
- Dante entities: source `select` + *Subscription* sensor (status code and explanation) + route lock per RX channel;
  TX/RX channel counts, sample rate and online state per device; devices online for the network. Devices and
  channels that appear later are added at runtime; devices with more than 32 RX channels start with disabled
  entities; options to hide devices or create entities only for selected RX channels; offline devices can be deleted.
- Card: protocol tab for Dante; sources and destinations grouped by device, collapsible (collapsed source devices
  become one summary column), device filters, dense tiles for big devices, subscription warnings; tested with a
  94 × 106 matrix in the demo (`docs/demo/?proto=dante`).
- Services accept destination ids (`destination`) besides entities; connection state `error`.

### Changed
- Snapshot sources/destinations are sorted naturally (`CH2` before `CH10`); new snapshot fields `group`, `channel`,
  `subscription`.

### Commits

- feat: Dante® network as second protocol (experimental) (8423846)

## [0.2.1] - 2026-10-04

### Fixed
- Magewell: the *Resolution* sensor no longer stays `unknown` after switching. Follow-up polls (1.5 / 3 / 5 / 8 / 12 s)
  run until the destination reports connected + resolution, independent of the polling interval; while the device
  still decodes the previous stream (summary `ndi.name` ≠ routed source) it reports *connecting* without the old
  resolution; `get-signal-info` is read whenever connected and only used if `signal-info-types` contains `video-info`.
- Magewell: summary `ndi` block parsed with the real FW 1.3.24 keys (`video-scan` → interlaced, `video-drop-frames`).
- Magewell: connection error texts can no longer contain the login query (user name / password hash).
- A poll that started before a route can no longer flip the select back to the previous source.
- Routes to the same destination are serialized (history/undo and BirdDog read-back stay consistent).
- BirdDog: HTTP 404 on an API endpoint is a driver error (was an unhandled `FileNotFoundError`).
- mDNS discovery is stopped again when the first device fails to set up.
- CI: `ruff check` added (imports cleaned up); the WebSocket test no longer hard-codes the version (failed after
  every release).

### Commits

- fix: resolution stuck at unknown after switching (Magewell), routing races, ruff in CI (ff1a677)

## [0.2.0] - 2026-10-04

### Added
- Card `custom:av-matrix-card` rebuilt as a broadcast-style router panel: X-Y panel mode and matrix mode
  (sticky headers, crosshair), direct or preset + TAKE (multi-destination salvo, Shift/long-press selection),
  lock/undo per destination, linked-display toggle, source search and tag filters, label/tag editor for admins,
  routing history with user names, keyboard control and ARIA roles, optimistic switching with rollback on errors,
  light/dark theme support, visual card editor, fallback to the select entities.
- Options `mode`, `take_mode`, `show_offline`, `compact`, `columns`, `destinations`.
- `docs/demo/` runs the card against a mocked Home Assistant; screenshots in `docs/screenshots/`.

### Changed
- The `av_matrix_routed` event now carries the context of the service call (so `context.user_id` tells who
  switched), and `origin` is `service` for `av_matrix.route` (was reported as `salvo`).

### Commits

- docs: card screenshots, options and shortcuts; changelog [Unreleased] support in release workflow (9d147bc)
- feat(card): broadcast-style router panel (1bc3b1f)
- feat: routed event carries the caller's context (who switched) (696397e)

## [0.1.0] - 2026-10-04

### Added
- Protocol-independent core: protocols (NDI® now, Dante planned) and drivers per device family.
- Drivers: Magewell Pro Convert (verified live, FW 1.3.24) and BirdDog decoders (untested in this project's CI hardware).
- Shared NDI® source registry: mDNS (`_ndi._tcp.local.`) + decoder source lists, dedupe by NDI name,
  TCP liveness check for untrusted lists, 2-minute hysteresis, mapping of BirdDog `NDI_<id>` placeholders.
- Entities per destination: source `select`, connection + resolution `sensor`, connected `binary_sensor`,
  route-lock `switch`; refresh-sources `button` per device.
- Services `av_matrix.route`, `salvo`, `lock`, `unlock`, `undo`, `refresh_sources`; event `av_matrix_routed`.
- Linked displays: power on a `media_player` and select its input when a destination is routed.
- WebSocket API `av_matrix/state`, `av_matrix/subscribe`, `av_matrix/label` (see docs/frontend-api.md).
- Basic Lovelace card `custom:av-matrix-card`, served and registered by the integration itself.
- Config flow (device type menu + driver-declared fields), re-auth, reconfigure, options flow, diagnostics.
