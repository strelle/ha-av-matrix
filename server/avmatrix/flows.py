"""„Gerät hinzufügen“ – dieselben Schritte wie der Config-Flow der HA-Integration, ohne Home Assistant.

Die Karte (``static/av-matrix-card.js``) steuert den Dialog über die REST-Schnittstelle, die Home Assistant
für Config-Flows hat (``config/config_entries/flow``). Dieser Baustein bildet sie nach:
Menü (suchen / manuell) → Subnetz durchsuchen → Gerät wählen → bestätigen → Eintrag angelegt.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from ipaddress import IPv4Interface
from pathlib import Path
from typing import Any

from .device_icons import icon_key
from .drivers import DRIVERS, CannotConnect, Driver, InvalidAuth
from .drivers.dante import CONF_STATIC_HOSTS
from .hub import Hub, MatrixError
from .models import ConfigField, DeviceInfo, FieldType, ProbeResult
from .protocols import PROTOCOLS
from .scan import InvalidSubnet, async_probe_host, async_scan, parse_subnet

_LOGGER = logging.getLogger(__name__)
HANDLER = "av_matrix"


def _field(config: ConfigField, values: dict[str, Any], factory: dict[str, Any]) -> dict[str, Any]:
    value = values.get(config.key, factory.get(config.key, config.default))
    if config.type is FieldType.PASSWORD:
        value = factory.get(config.key)  # gespeicherte Geheimnisse nie vorausfüllen
    out: dict[str, Any] = {"name": config.key, "required": config.required}
    if config.type is FieldType.PASSWORD:
        out["selector"] = {"text": {"type": "password"}}
    elif config.type in (FieldType.PORT, FieldType.INTEGER):
        out["selector"] = {"number": {"min": config.minimum or 0, "max": config.maximum or 65535, "step": 1, "mode": "box"}}
    else:
        out["selector"] = {"text": {}}
    if value is not None:
        if config.required and config.type is not FieldType.PASSWORD:
            out["default"] = value
        else:
            out["description"] = {"suggested_value": value}
    return out


def clean_input(fields: tuple[ConfigField, ...], user_input: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for config in fields:
        value = user_input.get(config.key)
        if isinstance(value, str):
            value = value.strip() if config.type is not FieldType.PASSWORD else value
        if value in (None, ""):
            if config.default is not None and config.type is not FieldType.PASSWORD:
                data[config.key] = config.default
            continue
        if config.type in (FieldType.PORT, FieldType.INTEGER):
            value = int(value)
        data[config.key] = value
    return data


def parse_hosts(text: Any) -> list[str]:
    if not text:
        return []
    if isinstance(text, list):
        return [str(t).strip() for t in text if str(t).strip()]
    return [h for h in (p.strip() for p in str(text).replace("\n", ",").replace(" ", ",").split(",")) if h]


@lru_cache(maxsize=4)
def translations(language: str) -> dict[str, str]:
    """Texte des Dialogs als ``component.av_matrix.config.…`` (aus den Übersetzungen der HA-Integration)."""
    lang = "de" if language.startswith("de") else "en"
    raw = json.loads((Path(__file__).parent / "translations" / f"{lang}.json").read_text(encoding="utf-8"))
    out: dict[str, str] = {}

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(f"{prefix}.{key}", value)
        elif isinstance(node, str):
            text = node.replace("das Netz von Home Assistant", "das Netz dieses Servers")
            text = text.replace("mDNS Home Assistant nicht erreicht", "mDNS diesen Server nicht erreicht")
            text = text.replace("Home Assistant's own network", "this server's network")
            text = text.replace("does not reach Home Assistant", "does not reach this server")
            out[prefix] = text

    walk(f"component.{HANDLER}.config", raw.get("config", {}))
    return out


@dataclass(slots=True)
class Flow:
    id: str
    source: str = "user"  # user | zeroconf
    step: str = "user"
    driver_key: str | None = None
    probe: ProbeResult | None = None
    scan_results: list[ProbeResult] = field(default_factory=list)
    placeholders: dict[str, str] = field(default_factory=dict)


class FlowManager:
    def __init__(self, hub: Hub, default_subnet: Callable[[], str]) -> None:
        self.hub = hub
        self.flows: dict[str, Flow] = {}
        self._default_subnet = default_subnet
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------ helpers
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _ignored(self) -> list[str]:
        return list(self.hub.config.data.get("ignored_hosts") or [])

    def _base(self, flow: Flow) -> dict[str, Any]:
        return {"flow_id": flow.id, "handler": HANDLER, "step_id": flow.step}

    def _form(
        self, flow: Flow, schema: list[dict[str, Any]], errors: dict[str, str] | None = None, ph: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return {
            **self._base(flow),
            "type": "form",
            "data_schema": schema,
            "errors": errors or {},
            "description_placeholders": ph or {},
        }

    def _abort(self, flow: Flow, reason: str) -> dict[str, Any]:
        self.flows.pop(flow.id, None)
        self._changed()
        return {"type": "abort", "flow_id": flow.id, "handler": HANDLER, "reason": reason}

    def _created(self, flow: Flow, title: str) -> dict[str, Any]:
        self.flows.pop(flow.id, None)
        self._changed()
        return {"type": "create_entry", "flow_id": flow.id, "handler": HANDLER, "title": title}

    async def _validate(self, driver_cls: type[Driver], data: dict[str, Any]) -> tuple[DeviceInfo | None, dict[str, str]]:
        try:
            return await self.hub.validate_device(driver_cls.KEY, data), {}
        except InvalidAuth:
            return None, {"base": "invalid_auth"}
        except CannotConnect:
            return None, {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unerwarteter Fehler beim Prüfen von %s", driver_cls.KEY)
            return None, {"base": "unknown"}

    # ------------------------------------------------------------- public
    def discovered(self) -> list[dict[str, Any]]:
        out = []
        for flow in self.flows.values():
            if flow.source == "user" or flow.probe is None:
                continue
            cls = DRIVERS[flow.probe.driver]
            name = flow.placeholders.get("name") or flow.probe.host
            out.append(
                {
                    "flow_id": flow.id,
                    "source": flow.source,
                    "step_id": flow.step,
                    "name": name,
                    "host": flow.probe.host,
                    "driver": cls.KEY,
                    "manufacturer": cls.MANUFACTURER,
                    "model": flow.probe.model,
                    "icon_key": icon_key(
                        protocol=cls.PROTOCOL, driver=cls.KEY, manufacturer=cls.MANUFACTURER, model=flow.probe.model, name=name
                    ),
                }
            )
        return sorted(out, key=lambda f: (f["name"] or "").casefold())

    async def probe_host(self, host: str, mdns_name: str | None = None) -> bool:
        """Von mDNS gemeldete Adresse prüfen; unterstützter, noch nicht eingerichteter Decoder → anbieten."""
        if host.lower() in self.hub.configured_hosts() or host in self._ignored():
            return False
        if any(f.probe and f.probe.host == host for f in self.flows.values()):
            return False
        drivers = [d for d in DRIVERS.values() if not d.NETWORK]
        probe = await async_probe_host(self.hub.session, host, drivers, check_ports=False)  # type: ignore[arg-type]
        if probe is None:
            return False
        probe.name = probe.name or mdns_name
        flow = Flow(secrets.token_urlsafe(12), source="zeroconf")
        self._offer(flow, probe)
        self.flows[flow.id] = flow
        _LOGGER.info("Neuer Decoder gefunden: %s (%s)", flow.placeholders["name"], host)
        self._changed()
        return True

    def ignore(self, flow_id: str) -> None:
        flow = self.flows.pop(flow_id, None)
        if flow is None:
            raise MatrixError("invalid", "Dieser Vorgang existiert nicht mehr.")
        if flow.probe is not None:
            ignored = self._ignored()
            if flow.probe.host not in ignored:
                self.hub.config.data["ignored_hosts"] = [*ignored, flow.probe.host]
                self.hub.config.save()
        self._changed()

    def delete(self, flow_id: str) -> None:
        if self.flows.pop(flow_id, None) is not None:
            self._changed()

    def start(self) -> dict[str, Any]:
        flow = Flow(secrets.token_urlsafe(12))
        self.flows[flow.id] = flow
        return self._menu(flow)

    def _menu(self, flow: Flow) -> dict[str, Any]:
        flow.step = "user"
        return {**self._base(flow), "type": "menu", "menu_options": ["scan", "manual"]}

    async def get(self, flow_id: str) -> dict[str, Any]:
        flow = self.flows.get(flow_id)
        if flow is None:
            raise MatrixError("invalid", "Dieser Vorgang existiert nicht mehr.")
        return await self._step(flow, None)

    async def submit(self, flow_id: str, user_input: dict[str, Any]) -> dict[str, Any]:
        flow = self.flows.get(flow_id)
        if flow is None:
            raise MatrixError("invalid", "Dieser Vorgang existiert nicht mehr.")
        if flow.step == "user":
            nxt = user_input.get("next_step_id")
            if nxt not in ("scan", "manual"):
                return self._menu(flow)
            flow.step = nxt
            return await self._step(flow, None)
        return await self._step(flow, user_input)

    # --------------------------------------------------------------- steps
    async def _step(self, flow: Flow, user_input: dict[str, Any] | None) -> dict[str, Any]:
        return await getattr(self, f"_step_{flow.step}")(flow, user_input)

    async def _step_user(self, flow: Flow, user_input: dict[str, Any] | None) -> dict[str, Any]:
        return self._menu(flow)

    async def _step_manual(self, flow: Flow, user_input: dict[str, Any] | None) -> dict[str, Any]:
        if user_input is not None and user_input.get("driver") in DRIVERS:
            flow.driver_key = user_input["driver"]
            flow.step = "network" if DRIVERS[flow.driver_key].NETWORK else "device"
            return await self._step(flow, None)
        options = [
            {
                "value": key,
                "label": f"{PROTOCOLS[cls.PROTOCOL].title} {cls.TITLE}"
                if cls.NETWORK
                else f"{PROTOCOLS[cls.PROTOCOL].title} · {cls.TITLE}",
            }
            for key, cls in sorted(DRIVERS.items(), key=lambda kv: (kv[1].PROTOCOL, not kv[1].NETWORK, kv[1].TITLE))
        ]
        return self._form(
            flow, [{"name": "driver", "required": True, "selector": {"select": {"options": options, "mode": "list"}}}]
        )

    async def _step_scan(self, flow: Flow, user_input: dict[str, Any] | None) -> dict[str, Any]:
        errors: dict[str, str] = {}
        default = self._default_subnet()
        if user_input is not None:
            default = user_input.get("subnet", "")
            try:
                subnet = parse_subnet(default)
            except InvalidSubnet:
                errors["subnet"] = "invalid_subnet"
            else:
                found = await async_scan(self.hub.session, subnet, DRIVERS.values())  # type: ignore[arg-type]
                configured = self.hub.configured_hosts()
                flow.scan_results = [r for r in found if r.host.lower() not in configured]
                if flow.scan_results:
                    flow.step = "pick"
                    return await self._step(flow, None)
                errors["base"] = "no_devices_found"
        return self._form(flow, [{"name": "subnet", "required": True, "default": default, "selector": {"text": {}}}], errors)

    async def _step_pick(self, flow: Flow, user_input: dict[str, Any] | None) -> dict[str, Any]:
        if user_input is not None:
            probe = next((r for r in flow.scan_results if r.host == user_input.get("host")), None)
            if probe is not None:
                self._offer(flow, probe)
                return await self._step(flow, None)
        options = [
            {
                "value": r.host,
                "label": " · ".join(p for p in (DRIVERS[r.driver].MANUFACTURER, r.name or r.model or "", r.host) if p),
            }
            for r in flow.scan_results
        ]
        return self._form(
            flow,
            [
                {
                    "name": "host",
                    "required": True,
                    "default": options[0]["value"],
                    "selector": {"select": {"options": options, "mode": "list"}},
                }
            ],
            ph={"count": str(len(options))},
        )

    def _offer(self, flow: Flow, probe: ProbeResult) -> None:
        cls = DRIVERS[probe.driver]
        flow.driver_key = cls.KEY
        flow.probe = probe
        flow.step = "confirm"
        flow.placeholders = {"name": probe.name or f"{cls.MANUFACTURER} {probe.host}", "host": probe.host}

    async def _step_confirm(self, flow: Flow, user_input: dict[str, Any] | None) -> dict[str, Any]:
        assert flow.probe is not None and flow.driver_key is not None
        probe, cls = flow.probe, DRIVERS[flow.driver_key]
        fields = tuple(f for f in cls.CONFIG_FIELDS if f.key not in ("host", "port"))
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {"host": probe.host, **clean_input(fields, user_input)}
            if probe.port and probe.port != cls.DEFAULT_PORT:
                data["port"] = probe.port
            elif any(f.key == "port" for f in cls.CONFIG_FIELDS):
                data["port"] = cls.DEFAULT_PORT
            info, errors = await self._validate(cls, data)
            if info is not None:
                return self._create(flow, cls, data, info, probe.host)
        schema = [_field(f, user_input or {}, cls.DISCOVERY_DEFAULTS if user_input is None else {}) for f in fields]
        return self._form(
            flow, schema, errors, {"device": cls.TITLE, "host": probe.host, "name": probe.name or cls.MANUFACTURER}
        )

    async def _step_device(self, flow: Flow, user_input: dict[str, Any] | None) -> dict[str, Any]:
        assert flow.driver_key is not None
        cls = DRIVERS[flow.driver_key]
        errors: dict[str, str] = {}
        if user_input is not None:
            data = clean_input(cls.CONFIG_FIELDS, user_input)
            if not data.get("host"):
                errors["base"] = "cannot_connect"
            else:
                info, errors = await self._validate(cls, data)
                if info is not None:
                    return self._create(flow, cls, data, info, data["host"])
        schema = [_field(f, user_input or {}, {}) for f in cls.CONFIG_FIELDS]
        return self._form(flow, schema, errors, {"device": cls.TITLE})

    def _create(self, flow: Flow, cls: type[Driver], data: dict[str, Any], info: DeviceInfo, host: str) -> dict[str, Any]:
        name = data.pop("name", None) or info.name or host
        try:
            self.hub.add_entry(cls.KEY, data, title=name, info=info)
        except MatrixError:
            return self._abort(flow, "already_configured")
        return self._created(flow, name)

    async def _step_network(self, flow: Flow, user_input: dict[str, Any] | None) -> dict[str, Any]:
        assert flow.driver_key is not None
        cls = DRIVERS[flow.driver_key]
        if cls.KEY in self.hub.entries:
            return self._abort(flow, "already_configured")
        if user_input is not None:
            hosts = parse_hosts(user_input.get(CONF_STATIC_HOSTS))
            title = f"{PROTOCOLS[cls.PROTOCOL].title.rstrip('®')}-Netzwerk"
            self.hub.add_entry(cls.KEY, {"host": "dante"}, title=title, options={CONF_STATIC_HOSTS: hosts} if hosts else {})
            return self._created(flow, title)
        return self._form(flow, [{"name": CONF_STATIC_HOSTS, "required": False, "selector": {"text": {}}}])


def default_subnet(lan_ip: str | None) -> str:
    return str(IPv4Interface(f"{lan_ip}/24").network) if lan_ip else ""
