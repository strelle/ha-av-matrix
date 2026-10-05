# Contributing

Thanks for helping! Bug reports with diagnostics, device test reports and new drivers are all welcome.

## Development setup

```bash
git clone https://github.com/strelle/ha-av-matrix.git
cd ha-av-matrix
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/pytest -q
.venv/bin/ruff check custom_components tests && .venv/bin/ruff format --check custom_components tests
node --check custom_components/av_matrix/frontend/av-matrix-card.js
```

To try it in a real Home Assistant, copy (or symlink) `custom_components/av_matrix` into the `custom_components`
folder of a test instance and restart it.

## Architecture in one minute

```
custom_components/av_matrix/
├── models.py          plain dataclasses (no Home Assistant imports)
├── drivers/           one class per device family  ← add new devices here
│   ├── base.py        Driver interface + errors
│   ├── birddog.py
│   ├── dante.py       network driver: all Dante® devices of the network (NETWORK = True)
│   └── magewell.py
├── protocols/         one source registry per protocol (NDI®, Dante® incl. the ARC wire format)
├── discovery.py       mDNS browsers (NDI® sources, Dante® devices)
├── hub.py             integration-wide state: routing, salvo, lock, undo, labels, snapshot
├── coordinator.py     polling per device (backoff while offline)
├── select.py …        entities
├── services.py        av_matrix.route / salvo / lock / unlock / undo / refresh_sources
├── websocket.py       av_matrix/state, av_matrix/subscribe, av_matrix/label
└── frontend/          the Lovelace card (plain JS, no build step)
```

`drivers/` and `protocols/` do not import Home Assistant, so they are easy to test and reuse.

## Adding a new decoder / receiver

The short version (details and how the Dante® network driver works in [docs/adding-a-driver.md](docs/adding-a-driver.md)):

1. Subclass `Driver` in `drivers/<vendor>.py` and implement

   | Method | Returns |
   |---|---|
   | `async_get_info()` | `DeviceInfo` (name, model, firmware, serial) — raises `CannotConnect` / `InvalidAuth`; used to validate the config flow |
   | `async_get_sources()` | `list[SourceSighting]` the device can see (device's own naming) |
   | `async_get_current(destination)` | current source name or `None` |
   | `async_route(destination, source, address)` | routes; `source=None` = off; raise `RouteFailed` if the device refuses |
   | `async_get_status(destination)` | `DestinationStatus(connected, resolution, extra)` — optional |
   | `async_refresh_sources()` | optional |
   | `destinations()` | optional, one `DestinationInfo` per output/channel (default: one) |

   and set `KEY`, `PROTOCOL`, `TITLE`, `MANUFACTURER`, `DEFAULT_PORT`, `CONFIG_FIELDS`, `TRUSTED_SOURCE_LIST`,
   `SETTLE_TIME`.
2. Add it to `DRIVERS` in `drivers/__init__.py`. The config flow picks it up automatically.
3. Add translations for any new config field key.
4. Add tests with real (anonymised!) device answers using `tests/fake_http.py`.
5. Add the device to `docs/devices.md` and to the table in the README, with the firmware you tested.

Please never commit real IP addresses, serial numbers, MAC addresses or passwords. Use `192.0.2.x` (TEST-NET-1)
in examples.

## Releases

Every push to `main` that changes code creates a release automatically (`.github/workflows/release.yml`):
patch by default, `feat:` or `[minor]` in a commit message → minor, `feat!:` / `BREAKING CHANGE` / `[major]` →
major. Add `[skip release]` to a commit message to skip it.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) are appreciated (`fix(magewell): …`, `feat(card): …`),
they drive the version bump.
