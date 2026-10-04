# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [SemVer](https://semver.org/).

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
