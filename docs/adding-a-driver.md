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

## A new protocol — how Dante® was added

Dante shows the pieces a protocol needs; use it as the template.

**Protocol module** `protocols/dante.py` — no Home Assistant imports:

- `DanteSourceRegistry(SourceRegistry)` with `protocol = "dante"`, `grouped = True` (sources belong to devices:
  the card groups them, lists are ordered by device) and `describe()` → `{"group": device, "channel": …}` for the
  WebSocket snapshot, `sort_key()` for natural ordering (`CH2` before `CH10`).
- Identity helpers (`"channel@device"`) and the wire format: request builders and response parsers for the ARC
  protocol, tested against real packets (`tests/test_dante_protocol.py`).
- Registered in `protocols/__init__.py`: `PROTOCOLS["dante"] = Protocol("dante", "Dante®", DanteSourceRegistry)`.

**Network driver** `drivers/dante.py` — Dante has no "one device = one entry" shape, so the driver covers the
whole network:

```python
class DanteNetwork(Driver):
    KEY = "dante"
    PROTOCOL = "dante"
    NETWORK = True            # one config entry for the network; destinations may change after every poll
    CONFIG_FIELDS = ()        # nothing to ask: devices come from mDNS (+ optional static hosts in the options)

    def destinations(self):                       # one per RX channel of every visible device
        return [DestinationInfo(f"{dev}:{n}", rx_name, device=dev), ...]

    def destination_available(self, destination): # per-device online state
        ...
    async def async_poll(self) -> DevicePoll: ... # all devices in parallel, TX channels as sources
    async def async_route(self, destination, source, address=None): ...  # subscribe / clear, then read back
```

What `NETWORK = True` changes in the integration (no driver code needed):

- The config flow shows the driver as a network entry (no form fields, single instance, zeroconf discovery offers it).
- After every poll, new destinations become hub destinations and their entities are added at runtime
  (`entity.async_setup_destination_entities`); `DestinationInfo.device` makes them belong to a sub-device
  (a Home Assistant device linked to the network device via `via_device_id`).
- `async_remove_config_entry_device` lets users delete sub-devices that went offline.
- Drivers can report an explicit state through `DestinationStatus.state` (e.g. `ConnectionState.ERROR` for a failed
  subscription) instead of letting the hub derive it.

**Discovery** `discovery.DanteMdnsBrowser` browses `_netaudio-arc._udp.local.` with Home Assistant's zeroconf
instance and hands host, port and TXT record to the driver.

**Tests:** `tests/dante_sim.py` simulates devices behind a fake UDP transport (answers built like the captured
packets), `tests/test_dante.py` runs the whole integration against it.

Everything else — select entities, services, salvo/lock/undo, WebSocket API, the matrix card (one tab per
protocol) — works unchanged.
