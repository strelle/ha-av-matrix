"""Per-device polling coordinator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, MAX_BACKOFF
from .drivers import Driver, DriverError, InvalidAuth
from .drivers.base import short
from .models import DestinationState, DestinationStatus, DeviceInfo, DevicePoll

if TYPE_CHECKING:
    from .hub import AvMatrixHub, Destination

_LOGGER = logging.getLogger(__name__)

#: Gaps between the follow-up polls after a route (→ 1.5, 3, 5, 8, 12 s). They stop as soon as
#: the routed destination reports "connected" with a resolution (or "no source").
FOLLOWUP_DELAYS: tuple[float, ...] = (1.5, 1.5, 2.0, 3.0, 4.0)


@dataclass(slots=True)
class AvMatrixRuntime:
    """Runtime data of one config entry."""

    coordinator: AvMatrixCoordinator
    destinations: list[Destination] = field(default_factory=list)
    #: network entries (Dante): sub-devices that already have a device + entities
    devices: set[str] = field(default_factory=set)
    #: network entries: discovery browser (stopped on unload)
    browser: Any = None
    #: network entries: device registry id of the network device (parent of the sub-devices)
    hub_device_id: str | None = None


type AvMatrixConfigEntry = ConfigEntry[AvMatrixRuntime]


class AvMatrixCoordinator(DataUpdateCoordinator[DevicePoll]):
    """Polls one device; backs off (up to 30 s) while it is offline."""

    config_entry: AvMatrixConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AvMatrixConfigEntry, driver: Driver, hub: AvMatrixHub) -> None:
        self.base_interval = timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {driver.host}",
            update_interval=self.base_interval,
            always_update=True,
        )
        self.driver = driver
        self.hub = hub
        self.info = DeviceInfo()
        self._failures = 0
        self._followup: CALLBACK_TYPE | None = None
        self._settling: set[str] = set()
        # routes made while a poll was running: that poll may predate them and must not undo them
        self._route_seq = 0
        self._optimistic: dict[str, tuple[int, str | None]] = {}

    @property
    def device_name(self) -> str:
        return self.config_entry.title or self.info.name or self.driver.host

    async def _async_setup(self) -> None:
        try:
            self.info = await self.driver.async_get_info()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(short(err)) from err
        except DriverError as err:
            raise UpdateFailed(short(err)) from err

    async def _async_update_data(self) -> DevicePoll:
        registry = self.hub.registry(self.driver.PROTOCOL)
        seq = self._route_seq
        try:
            poll = await self.driver.async_poll()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(short(err)) from err
        except DriverError as err:
            self._failures += 1
            self.update_interval = min(MAX_BACKOFF, self.base_interval * (2**self._failures))
            registry.remove_device(self.config_entry.entry_id)
            self.hub.schedule_evaluate()
            raise UpdateFailed(short(err)) from err
        if self._failures:
            _LOGGER.info("%s is back online", self.device_name)
        self._failures = 0
        self.update_interval = self.base_interval
        for dest_id, (route_seq, device_source) in list(self._optimistic.items()):
            if route_seq <= seq:  # this poll started after the route → it is the truth
                del self._optimistic[dest_id]
                continue
            state = poll.destinations.setdefault(dest_id, DestinationState())
            if state.current != device_source:
                state.current = device_source
                state.status = DestinationStatus(connected=False)
        registry.set_device_sightings(self.config_entry.entry_id, poll.sources, self.driver.TRUSTED_SOURCE_LIST)
        self.hub.schedule_evaluate()
        return poll

    @callback
    def set_current(self, dest_id: str, device_source: str | None) -> None:
        """Optimistic update right after a successful route."""
        self._route_seq += 1
        self._optimistic[dest_id] = (self._route_seq, device_source)
        self._settling.add(dest_id)
        if self.data is None:
            return
        state = self.data.destinations.setdefault(dest_id, DestinationState())
        state.current = device_source
        # "connecting" until the device reports otherwise; no resolution of the previous stream
        state.status = DestinationStatus(connected=False)
        self.async_update_listeners()

    def _settled(self) -> bool:
        """True when every routed destination reports its final state (connected + resolution, or off)."""
        if not self.last_update_success or self.data is None:
            return False
        for dest_id in self._settling:
            state = self.data.destinations.get(dest_id)
            if state is None:
                return False
            if state.current is not None and not (state.status.connected and state.status.resolution):
                return False
        return True

    @callback
    def async_refresh_after_route(self) -> None:
        """Poll right away, then follow up until the device has settled (Magewell: 2-5 s, max ~12 s)."""
        self.config_entry.async_create_background_task(self.hass, self.async_refresh(), f"{self.name} refresh")
        self._cancel_followup()
        self._schedule_followup(0)

    def _cancel_followup(self) -> None:
        if self._followup:
            self._followup()
            self._followup = None

    def _schedule_followup(self, step: int) -> None:
        if step >= len(FOLLOWUP_DELAYS):
            self._settling.clear()
            return

        @callback
        def _later(_now: object) -> None:
            self._followup = None
            self.config_entry.async_create_background_task(
                self.hass, self._async_followup(step), f"{self.name} settle refresh"
            )

        self._followup = async_call_later(self.hass, FOLLOWUP_DELAYS[step], _later)

    async def _async_followup(self, step: int) -> None:
        await self.async_refresh()
        if self._followup is not None:
            return  # a newer route restarted the follow-ups
        if self._settled():
            self._settling.clear()
        else:
            self._schedule_followup(step + 1)

    async def async_shutdown(self) -> None:
        self._cancel_followup()
        await super().async_shutdown()
