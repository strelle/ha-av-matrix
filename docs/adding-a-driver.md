# Adding a driver (or a protocol)

AV Matrix has two layers:

| Layer | Examples | Lives in | Responsibility |
|---|---|---|---|
| **Protocol** | `ndi`, later `dante` | `custom_components/av_matrix/protocols/` | What a *source* is (its identity), how sources are discovered, which sources are alive. One `SourceRegistry` per protocol. |
| **Driver** | `ndi` → `birddog`, `magewell`; later `ndi` → `kiloview`, `dante` → `dante_arc` | `custom_components/av_matrix/drivers/` | Talks to one device: info, sources it sees, current routing, routing, status. |

Sources of one protocol can only be routed to destinations of the same protocol.
A config entry is one **device**; a device has one or more **destinations** (decoder outputs, receiver channels),
each becomes a `select` entity and a row in the matrix.

## A new device family for an existing protocol

1. Create `drivers/<vendor>.py` with a subclass of `drivers.base.Driver`:

   ```python
   class KiloviewDecoder(Driver):
       KEY = "kiloview"                 # stored in the config entry, never change it later
       PROTOCOL = "ndi"
       TITLE = "Kiloview (N30, N40, N60 …)"
       MANUFACTURER = "Kiloview"
       DEFAULT_PORT = 80
       CONFIG_FIELDS = (HOST, ConfigField("username", default="admin"),
                        ConfigField("password", FieldType.PASSWORD, secret=True), NAME)
       TRUSTED_SOURCE_LIST = True       # False if the device lists stale sources
       SETTLE_TIME = 3.0                # seconds until "connected" after a route

       async def async_get_info(self) -> DeviceInfo: ...          # raise CannotConnect / InvalidAuth
       async def async_get_sources(self) -> list[SourceSighting]: ...
       async def async_get_current(self, destination: str) -> str | None: ...
       async def async_route(self, destination: str, source: str | None, address: str | None = None) -> None: ...
       async def async_get_status(self, destination: str) -> DestinationStatus: ...   # optional
       async def async_refresh_sources(self) -> None: ...                             # optional
       def destinations(self) -> list[DestinationInfo]: ...                          # optional, default: one
   ```

2. Register it in `drivers/__init__.py` (`DRIVERS`).
3. The config flow builds its form from `CONFIG_FIELDS`. Known keys (`host`, `port`, `username`, `password`,
   `name`, `channels`) are already translated; a new key needs labels in `strings.json` and
   `translations/*.json` (`config.step.device.data`).
4. Tests: `tests/test_<vendor>.py` against `tests/fake_http.py` with real (anonymised) answers of the device.
5. Document what you verified (model, firmware, date) in `docs/devices.md` and the README table.

Rules that keep the matrix honest:

- Use the `aiohttp` session you get (Home Assistant's shared session); always pass `timeout=self.timeout`.
- Raise `CannotConnect`, `InvalidAuth` or `RouteFailed` with short messages; **never put passwords into messages or logs**.
- Return source names **as the device knows them**; the registry maps device-specific placeholders.
- If the device's own list may contain stale sources, set `TRUSTED_SOURCE_LIST = False`.
- If a route is not reliably applied, read it back and retry once (see the BirdDog driver).

## A new protocol — sketch for Dante

Dante is not implemented. This is how it would fit:

**Identity.** Source = `"<device>:<tx channel>"` (e.g. `"STAGEBOX-01:Mic 3"`); destination = one RX channel of a
device (`"AMP-LOBBY:In 1"`). A Dante device usually has many RX channels → the driver returns one
`DestinationInfo` per RX channel from `destinations()` (or a configurable subset, 64 selects per device are a lot).

**Protocol module** `protocols/dante.py`:

```python
class DanteSourceRegistry(SourceRegistry):
    protocol = "dante"
    placeholder_re = None   # Dante names are stable, no placeholders
```

and in `protocols/__init__.py`:

```python
PROTOCOLS["dante"] = Protocol("dante", "Dante", DanteSourceRegistry)
```

**Discovery.** Dante devices announce `_netaudio-arc._udp.local.` (plus `_netaudio-cmc._udp`, `_netaudio-dbc._udp`,
`_netaudio-chan._udp` per channel). A `DanteMdnsBrowser` (like `discovery.NdiMdnsBrowser`) feeds device names;
TX channel names are read per device via ARC (UDP 4440) and registered with `set_discovered("<device>:<channel>", …)`.
The open-source project [netaudio](https://github.com/chris-ritsen/network-audio-controller) (Unlicense) implements
the ARC requests (list channels, add/remove subscription) in Python and is a good reference — either as a
requirement in `manifest.json` or as a small vendored client.

**Driver** `drivers/dante_arc.py`:

```python
class DanteDevice(Driver):
    KEY = "dante_arc"
    PROTOCOL = "dante"
    TITLE = "Dante device (ARC)"
    MANUFACTURER = "Audinate"
    CONFIG_FIELDS = (HOST, NAME)          # Dante control has no login (Dante Domain Manager aside)

    def destinations(self):               # one per RX channel
        return [DestinationInfo(str(n), name) for n, name in self._rx_channels]

    async def async_get_current(self, destination):   # subscription of the RX channel
        return f"{tx_device}:{tx_channel}" or None

    async def async_route(self, destination, source, address=None):
        # "None" = remove subscription, else add subscription rx → tx_device@tx_channel
        ...
```

Everything else — select entities, services, salvo/lock/undo, WebSocket API, the matrix card (one tab per
protocol) — works unchanged.
