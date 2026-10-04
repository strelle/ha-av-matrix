"""Per-device polling coordinator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, MAX_BACKOFF
from .drivers import Driver, DriverError, InvalidAuth
from .drivers.base import short
from .models import DestinationState, DeviceInfo, DevicePoll

if TYPE_CHECKING:
    from .hub import AvMatrixHub, Destination

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AvMatrixRuntime:
    """Runtime data of one config entry."""

    coordinator: AvMatrixCoordinator
    destinations: list[Destination] = field(default_factory=list)


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
        registry.set_device_sightings(self.config_entry.entry_id, poll.sources, self.driver.TRUSTED_SOURCE_LIST)
        self.hub.schedule_evaluate()
        return poll

    @callback
    def set_current(self, dest_id: str, device_source: str | None) -> None:
        """Optimistic update right after a successful route."""
        if self.data is None:
            return
        state = self.data.destinations.setdefault(dest_id, DestinationState())
        state.current = device_source
        state.status.connected = False  # "connecting" until the device reports otherwise
        state.status.resolution = None
        self.async_update_listeners()

    @callback
    def async_refresh_after_route(self) -> None:
        """Poll right away and again when the device should have settled (Magewell: 2-5 s)."""
        self.hass.async_create_task(self.async_refresh(), f"{self.name} refresh", eager_start=False)
        if self._followup:
            self._followup()

        @callback
        def _later(_now: object) -> None:
            self._followup = None
            self.hass.async_create_task(self.async_refresh(), f"{self.name} settle refresh", eager_start=False)

        self._followup = async_call_later(self.hass, self.driver.SETTLE_TIME, _later)

    async def async_shutdown(self) -> None:
        if self._followup:
            self._followup()
            self._followup = None
        await super().async_shutdown()
