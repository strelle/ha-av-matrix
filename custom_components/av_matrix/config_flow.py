"""Config flow: pick a device type, then the fields that driver declares.

New drivers need no change here - the form is built from ``Driver.CONFIG_FIELDS``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_DISPLAY_AUTO_ON,
    CONF_DISPLAY_ENTITY,
    CONF_DISPLAY_INPUT,
    CONF_DISPLAY_OFF_ON_NONE,
    CONF_DISPLAYS,
    CONF_DRIVER,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    REQUEST_TIMEOUT,
)
from .drivers import DRIVERS, CannotConnect, Driver, InvalidAuth
from .models import ConfigField, DeviceInfo, FieldType
from .protocols import PROTOCOLS

_LOGGER = logging.getLogger(__name__)


def _selector(field: ConfigField) -> Any:
    if field.type is FieldType.PASSWORD:
        return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
    if field.type in (FieldType.PORT, FieldType.INTEGER):
        return NumberSelector(
            NumberSelectorConfig(
                min=field.minimum or 0, max=field.maximum or 65535, step=1, mode=NumberSelectorMode.BOX
            )
        )
    return TextSelector()


def build_schema(fields: tuple[ConfigField, ...], values: Mapping[str, Any] | None = None) -> vol.Schema:
    """Form schema from driver-declared fields (``values`` pre-fill the form)."""
    values = values or {}
    schema: dict[Any, Any] = {}
    for field in fields:
        value = values.get(field.key, field.default)
        if field.type is FieldType.PASSWORD:
            value = None  # never pre-fill secrets
        marker = vol.Required if field.required else vol.Optional
        if value is None:
            key = marker(field.key)
        elif field.required:
            key = marker(field.key, default=value)
        else:
            key = marker(field.key, description={"suggested_value": value})
        schema[key] = _selector(field)
    return vol.Schema(schema)


def clean_input(fields: tuple[ConfigField, ...], user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce numbers (selectors return floats), strip strings, drop empty optionals."""
    data: dict[str, Any] = {}
    for field in fields:
        value = user_input.get(field.key)
        if isinstance(value, str):
            value = value.strip() if field.type is not FieldType.PASSWORD else value
        if value in (None, ""):
            if field.default is not None and field.type is not FieldType.PASSWORD:
                data[field.key] = field.default
            continue
        if field.type in (FieldType.PORT, FieldType.INTEGER):
            value = int(value)
        data[field.key] = value
    return data


def unique_id_for(driver_key: str, info: DeviceInfo, host: str) -> str:
    if info.serial:
        return f"{driver_key}-{str(info.serial).strip().lower()}"
    if info.mac:
        return f"{driver_key}-{format_mac(info.mac)}"
    return f"{driver_key}-{host.lower()}"


class AvMatrixConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a device (one config entry per device)."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._driver_key: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> AvMatrixOptionsFlow:
        return AvMatrixOptionsFlow()

    async def _async_validate(
        self, driver_cls: type[Driver], data: Mapping[str, Any]
    ) -> tuple[DeviceInfo | None, dict[str, str]]:
        driver = driver_cls(async_get_clientsession(self.hass), data, timeout=REQUEST_TIMEOUT)
        try:
            return await driver.async_get_info(), {}
        except InvalidAuth:
            return None, {"base": "invalid_auth"}
        except CannotConnect:
            return None, {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error while validating %s", driver_cls.KEY)
            return None, {"base": "unknown"}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose protocol + device type."""
        if user_input is not None:
            self._driver_key = user_input[CONF_DRIVER]
            return await self.async_step_device()
        options = [
            SelectOptionDict(value=key, label=f"{PROTOCOLS[cls.PROTOCOL].title} · {cls.TITLE}")
            for key, cls in sorted(DRIVERS.items(), key=lambda kv: (kv[1].PROTOCOL, kv[1].TITLE))
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DRIVER): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Device-specific fields, declared by the driver."""
        assert self._driver_key is not None
        driver_cls = DRIVERS[self._driver_key]
        errors: dict[str, str] = {}
        if user_input is not None:
            data = clean_input(driver_cls.CONFIG_FIELDS, user_input)
            info, errors = await self._async_validate(driver_cls, data)
            if info is not None:
                await self.async_set_unique_id(unique_id_for(driver_cls.KEY, info, data["host"]))
                self._abort_if_unique_id_configured(updates={k: v for k, v in data.items() if k in ("host", "port")})
                name = data.pop("name", None) or info.name or data["host"]
                return self.async_create_entry(title=name, data={CONF_DRIVER: driver_cls.KEY, **data})
        return self.async_show_form(
            step_id="device",
            data_schema=build_schema(driver_cls.CONFIG_FIELDS, user_input),
            errors=errors,
            description_placeholders={"device": driver_cls.TITLE},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        driver_cls = DRIVERS[entry.data[CONF_DRIVER]]
        fields = tuple(f for f in driver_cls.CONFIG_FIELDS if f.key == "username" or f.key in driver_cls.secret_keys())
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **clean_input(fields, user_input)}
            info, errors = await self._async_validate(driver_cls, data)
            if info is not None:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=build_schema(fields, entry.data),
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        driver_cls = DRIVERS[entry.data[CONF_DRIVER]]
        fields = tuple(f for f in driver_cls.CONFIG_FIELDS if f.key != "name")
        errors: dict[str, str] = {}
        if user_input is not None:
            data = clean_input(fields, user_input)
            for key in driver_cls.secret_keys():  # empty password field = keep the stored one
                if key not in data and key in entry.data:
                    data[key] = entry.data[key]
            info, errors = await self._async_validate(driver_cls, data)
            if info is not None:
                await self.async_set_unique_id(unique_id_for(driver_cls.KEY, info, data["host"]))
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data={CONF_DRIVER: driver_cls.KEY, **data})
        return self.async_show_form(
            step_id="reconfigure", data_schema=build_schema(fields, user_input or entry.data), errors=errors
        )


class AvMatrixOptionsFlow(OptionsFlow):
    """Polling interval + optional linked display per destination."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._pending: list[tuple[str, str]] = []
        self._current: tuple[str, str] | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._options = {
                **self.config_entry.options,
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                CONF_DISPLAYS: dict(self.config_entry.options.get(CONF_DISPLAYS, {})),
            }
            driver_cls = DRIVERS[self.config_entry.data[CONF_DRIVER]]
            driver = driver_cls(None, self.config_entry.data)  # type: ignore[arg-type] - no I/O here
            self._pending = [(d.id, d.name or self.config_entry.title) for d in driver.destinations()]
            return await self.async_step_display()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    )
                }
            ),
        )

    async def async_step_display(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Linked display of one destination (repeated for every destination)."""
        if user_input is not None and self._current is not None:
            dest_id, _ = self._current
            entity_id = user_input.get(CONF_DISPLAY_ENTITY)
            if not entity_id:
                self._options[CONF_DISPLAYS].pop(dest_id, None)
            else:
                old = self._options[CONF_DISPLAYS].get(dest_id, {})
                self._options[CONF_DISPLAYS][dest_id] = {
                    CONF_DISPLAY_ENTITY: entity_id,
                    CONF_DISPLAY_AUTO_ON: bool(user_input.get(CONF_DISPLAY_AUTO_ON, True)),
                    CONF_DISPLAY_OFF_ON_NONE: bool(user_input.get(CONF_DISPLAY_OFF_ON_NONE, False)),
                    CONF_DISPLAY_INPUT: old.get(CONF_DISPLAY_INPUT)
                    if old.get(CONF_DISPLAY_ENTITY) == entity_id
                    else None,
                }
                return await self.async_step_display_input()
            self._current = None
        if not self._pending and self._current is None:
            return self.async_create_entry(data=self._options)
        if self._current is None:
            self._current = self._pending.pop(0)
        dest_id, dest_name = self._current
        cfg = self._options[CONF_DISPLAYS].get(dest_id, {})
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_DISPLAY_ENTITY, description={"suggested_value": cfg.get(CONF_DISPLAY_ENTITY)}
            ): EntitySelector(EntitySelectorConfig(domain="media_player")),
            vol.Optional(CONF_DISPLAY_AUTO_ON, default=cfg.get(CONF_DISPLAY_AUTO_ON, True)): BooleanSelector(),
            vol.Optional(CONF_DISPLAY_OFF_ON_NONE, default=cfg.get(CONF_DISPLAY_OFF_ON_NONE, False)): BooleanSelector(),
        }
        return self.async_show_form(
            step_id="display", data_schema=vol.Schema(schema), description_placeholders={"destination": dest_name}
        )

    async def async_step_display_input(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Input of the linked display (suggestions from its ``source_list``)."""
        assert self._current is not None
        dest_id, dest_name = self._current
        cfg = self._options[CONF_DISPLAYS][dest_id]
        if user_input is not None:
            cfg[CONF_DISPLAY_INPUT] = (user_input.get(CONF_DISPLAY_INPUT) or "").strip() or None
            self._current = None
            return await self.async_step_display()
        state = self.hass.states.get(cfg[CONF_DISPLAY_ENTITY])
        inputs = [str(s) for s in (state.attributes.get("source_list") or [])] if state else []
        current = cfg.get(CONF_DISPLAY_INPUT)
        if current and current not in inputs:
            inputs.insert(0, current)
        return self.async_show_form(
            step_id="display_input",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DISPLAY_INPUT, description={"suggested_value": current}): SelectSelector(
                        SelectSelectorConfig(options=inputs, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
            description_placeholders={"destination": dest_name, "display": cfg[CONF_DISPLAY_ENTITY]},
        )
