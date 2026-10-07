"""Discovery of NDI® decoders: driver probes, network scan, DHCP / zeroconf / scan config flows."""

from __future__ import annotations

import json
from ipaddress import IPv4Network, ip_address
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.av_matrix import scan
from custom_components.av_matrix.const import DOMAIN
from custom_components.av_matrix.drivers import DRIVERS, InvalidAuth
from custom_components.av_matrix.drivers.birddog import BirdDogDecoder
from custom_components.av_matrix.drivers.magewell import MagewellProConvert
from custom_components.av_matrix.models import DeviceInfo, ProbeResult

MAGEWELL_MAC = "d0:c8:57:80:00:01"  # Magewell block D0:C8:57:8x (anonymised)
FLOW = "custom_components.av_matrix.config_flow"


# ------------------------------------------------------------------ driver probes
async def test_magewell_probe_not_logged_in(session) -> None:
    """Verified live (FW 1.3.24): without a session the API answers status 37."""
    session.get_("http://192.0.2.10/mwapi?method=get-summary-info", payload={"status": 37})
    result = await MagewellProConvert.async_probe(session, "192.0.2.10")
    assert result == ProbeResult("magewell", "192.0.2.10", 80, needs_auth=True)


async def test_magewell_probe_open_device(session) -> None:
    session.get_(
        "http://192.0.2.10/mwapi?method=get-summary-info",
        payload={
            "status": 0,
            "device": {"name": "Stage", "model": "NDI to HDMI", "serial-no": "A1"},
            "ethernet": {"mac-addr": MAGEWELL_MAC},
        },
    )
    result = await MagewellProConvert.async_probe(session, "192.0.2.10")
    assert result is not None and not result.needs_auth
    assert (result.name, result.model, result.serial, result.mac) == ("Stage", "NDI to HDMI", "A1", MAGEWELL_MAC)


@pytest.mark.parametrize(
    ("status", "body"),
    [(200, "<html>router</html>"), (200, json.dumps({"ok": True})), (404, ""), (200, json.dumps([1]))],
)
async def test_magewell_probe_rejects_others(session, status, body) -> None:
    session.get_("http://192.0.2.11/mwapi?method=get-summary-info", status=status, body=body)
    assert await MagewellProConvert.async_probe(session, "192.0.2.11") is None


async def test_magewell_probe_connection_error(session) -> None:
    session.get_("http://192.0.2.11/mwapi?method=get-summary-info", exception=TimeoutError())
    assert await MagewellProConvert.async_probe(session, "192.0.2.11") is None


async def test_birddog_probe(session) -> None:
    session.get_(
        "http://192.0.2.30:8080/about",
        payload={"HostName": "PLAY-1.local", "FirmwareVersion": "1.0.14", "SerialNumber": "BD1", "Format": "NDI"},
    )
    result = await BirdDogDecoder.async_probe(session, "192.0.2.30")
    assert result == ProbeResult("birddog", "192.0.2.30", 8080, name="PLAY-1", serial="BD1")


@pytest.mark.parametrize(("status", "payload"), [(200, {"foo": 1}), (401, {}), (404, {})])
async def test_birddog_probe_rejects_others(session, status, payload) -> None:
    session.get_("http://192.0.2.31:8080/about", status=status, payload=payload)
    assert await BirdDogDecoder.async_probe(session, "192.0.2.31") is None


# ------------------------------------------------------------------ network scan
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("192.0.2.0/24", "192.0.2.0/24"),
        (" 192.0.2.77/24 ", "192.0.2.0/24"),
        ("192.0.2.77", "192.0.2.0/24"),
        ("192.0.0.0/22", "192.0.0.0/22"),
    ],
)
def test_parse_subnet(text, expected) -> None:
    assert str(scan.parse_subnet(text)) == expected


@pytest.mark.parametrize("text", ["", "10.0.0.0/8", "192.0.2.0/21", "2001:db8::/64", "no-net"])
def test_parse_subnet_rejects(text) -> None:
    with pytest.raises(scan.InvalidSubnet):
        scan.parse_subnet(text)


async def test_scan_checks_ports_then_probes(session) -> None:
    open_ports = {("192.0.2.10", 80), ("192.0.2.30", 8080), ("192.0.2.40", 80)}
    checked: list[tuple[str, int]] = []

    async def port_open(host, port, timeout):
        checked.append((host, port))
        return (host, port) in open_ports

    session.get_("http://192.0.2.10/mwapi?method=get-summary-info", payload={"status": 37})
    session.get_("http://192.0.2.30:8080/about", payload={"HostName": "PLAY-1", "SerialNumber": "BD1"})
    session.get_("http://192.0.2.40/mwapi?method=get-summary-info", body="<html>printer</html>")
    with patch.object(scan, "_port_open", port_open):
        drivers = [MagewellProConvert, BirdDogDecoder, DRIVERS["dante"]]
        found = await scan.async_scan(session, IPv4Network("192.0.2.0/26"), drivers, concurrency=8)
    assert [(r.driver, r.host) for r in found] == [("magewell", "192.0.2.10"), ("birddog", "192.0.2.30")]
    assert len(checked) == 62 * 2  # every host, both probe ports, Dante (network driver) not scanned
    # HTTP only where a port was open
    assert sorted(c[1] for c in session.calls) == [
        "http://192.0.2.10/mwapi?method=get-summary-info",
        "http://192.0.2.30:8080/about",
        "http://192.0.2.40/mwapi?method=get-summary-info",
    ]


# ------------------------------------------------------------------ config flows
class FakeMagewell(MagewellProConvert):
    hosts: ClassVar[set[str]] = set()

    @classmethod
    async def async_probe(cls, session, host, timeout=2.0):
        return ProbeResult(cls.KEY, host, 80, needs_auth=True) if host in cls.hosts else None

    async def async_get_info(self) -> DeviceInfo:
        if self.config.get("username") != "Admin" or self.config.get("password") != "Admin":
            raise InvalidAuth("wrong")
        return DeviceInfo(name="Strelle2", manufacturer="Magewell", serial="SN-MW1", mac=MAGEWELL_MAC)


class FakeBirdDog(BirdDogDecoder):
    @classmethod
    async def async_probe(cls, session, host, timeout=2.0):
        return ProbeResult(cls.KEY, host, 8080, name="PLAY-1", serial="BD1") if host == "192.0.2.30" else None

    async def async_get_info(self) -> DeviceInfo:
        return DeviceInfo(name="PLAY-1", manufacturer="BirdDog", serial="BD1")


@pytest.fixture(autouse=True)
def fake_drivers(hass: HomeAssistant):
    FakeMagewell.hosts = {"192.0.2.10"}
    hass.config.components.update({"frontend", "zeroconf", "network"})
    with (
        patch.dict(DRIVERS, {"magewell": FakeMagewell, "birddog": FakeBirdDog}),
        patch("custom_components.av_matrix.async_setup_entry", return_value=True),
    ):
        yield


def dhcp(ip: str = "192.0.2.10", mac: str = MAGEWELL_MAC.replace(":", ""), hostname: str = "strelle2"):
    return DhcpServiceInfo(ip=ip, macaddress=mac, hostname=hostname)


async def test_dhcp_magewell_one_click(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=dhcp()
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "confirm"
    schema = {str(k): k for k in result["data_schema"].schema}
    assert list(schema) == ["username", "password", "name"]
    assert schema["username"].default() == "Admin"
    assert schema["password"].description == {"suggested_value": "Admin"}  # factory login pre-filled
    flow = hass.config_entries.flow.async_get(result["flow_id"])
    assert flow["context"]["unique_id"] == f"magewell-{MAGEWELL_MAC}"
    assert flow["context"]["title_placeholders"] == {"name": "Magewell 192.0.2.10"}
    # same device announced again while the flow is open
    again = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=dhcp()
    )
    assert again["type"] is FlowResultType.ABORT and again["reason"] == "already_in_progress"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "Admin", "password": "Admin"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Strelle2"
    assert result["data"] == {
        "driver": "magewell",
        "host": "192.0.2.10",
        "port": 80,
        "username": "Admin",
        "password": "Admin",
    }
    assert result["result"].unique_id == "magewell-sn-mw1"  # same scheme as manually added devices


async def test_dhcp_wrong_login_then_right(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=dhcp()
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "Admin", "password": "nope"}
    )
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "invalid_auth"}
    # the form is not pre-filled with the factory password again after a failed attempt
    schema = {str(k): k for k in result["data_schema"].schema}
    assert schema["password"].description is None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "Admin", "password": "Admin"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_dhcp_not_a_decoder(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=dhcp(ip="192.0.2.99")
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "not_supported"


def _existing(hass: HomeAssistant, host: str = "192.0.2.10", serial: str = "mw1") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Regie",
        unique_id=f"magewell-sn-{serial}",
        data={"driver": "magewell", "host": host, "port": 80, "username": "Admin", "password": "x"},
    )
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        connections={(dr.CONNECTION_NETWORK_MAC, MAGEWELL_MAC)},
    )
    return entry


async def test_dhcp_already_configured_same_ip(hass: HomeAssistant) -> None:
    entry = _existing(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=dhcp()
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.10"


async def test_dhcp_new_ip_updates_entry(hass: HomeAssistant) -> None:
    """The entry's unique id is the serial (unknown before login) - the MAC in the device registry finds it."""
    entry = _existing(hass, host="192.0.2.10")
    FakeMagewell.hosts = {"192.0.2.12"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=dhcp(ip="192.0.2.12")
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.12"
    assert entry.data["password"] == "x"


async def test_birddog_discovery_knows_serial_and_updates_ip(hass: HomeAssistant) -> None:
    """BirdDog tells its serial without login → unique id up front, IP change via updates={host}."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="birddog-bd1", data={"driver": "birddog", "host": "192.0.2.5", "port": 8080}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=dhcp(ip="192.0.2.30", mac="d42000a00001", hostname="play-1"),
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.30"


async def test_birddog_discovery_confirm_without_password(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=dhcp(ip="192.0.2.30", mac="d42000a00001", hostname="play-1"),
    )
    assert result["step_id"] == "confirm"
    assert [str(k) for k in result["data_schema"].schema] == ["password", "channels", "name"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"driver": "birddog", "host": "192.0.2.30", "port": 8080, "channels": 1}
    assert result["result"].unique_id == "birddog-bd1"


async def test_zeroconf_non_dante_probes_host(hass: HomeAssistant) -> None:
    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.10"),
        ip_addresses=[ip_address("192.0.2.10")],
        hostname="Strelle2.local.",
        name="Strelle2._http._tcp.local.",
        port=80,
        type="_http._tcp.local.",
        properties={},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "confirm"


async def _start_scan(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.MENU and result["menu_options"] == ["scan", "manual"]
    with patch(f"{FLOW}.async_default_subnet", AsyncMock(return_value=IPv4Network("192.0.2.0/24"))):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "scan"})
    assert result["step_id"] == "scan"
    assert next(iter(result["data_schema"].schema)).default() == "192.0.2.0/24"
    return result


async def test_scan_pick_confirm(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="magewell-sn-other", data={"driver": "magewell", "host": "192.0.2.20"}).add_to_hass(
        hass
    )  # already set up → not offered
    result = await _start_scan(hass)
    found = [
        ProbeResult("magewell", "192.0.2.10", 80, needs_auth=True),
        ProbeResult("magewell", "192.0.2.20", 80, needs_auth=True),
        ProbeResult("birddog", "192.0.2.30", 8080, name="PLAY-1", serial="BD1"),
    ]
    with patch(f"{FLOW}.async_scan", AsyncMock(return_value=found)) as scan_mock:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"subnet": "192.0.2.0/24"})
    assert scan_mock.call_args.args[1] == IPv4Network("192.0.2.0/24")
    assert result["step_id"] == "pick" and result["description_placeholders"] == {"count": "2"}
    options = result["data_schema"].schema["host"].config["options"]
    assert [(o["value"], o["label"]) for o in options] == [
        ("192.0.2.10", "Magewell · 192.0.2.10"),
        ("192.0.2.30", "BirdDog · PLAY-1 · 192.0.2.30"),
    ]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.0.2.10"})
    assert result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "Admin", "password": "Admin", "name": "Regie 2"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "Regie 2"


async def test_scan_errors(hass: HomeAssistant) -> None:
    result = await _start_scan(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"subnet": "10.0.0.0/8"})
    assert result["errors"] == {"subnet": "invalid_subnet"}
    with patch(f"{FLOW}.async_scan", AsyncMock(return_value=[])):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"subnet": "192.0.2.0/24"})
    assert result["step_id"] == "scan" and result["errors"] == {"base": "no_devices_found"}


async def test_scan_finds_already_configured_birddog_by_serial(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id="birddog-bd1", data={"driver": "birddog", "host": "192.0.2.5"}
    ).add_to_hass(hass)
    result = await _start_scan(hass)
    found = [ProbeResult("birddog", "192.0.2.30", 8080, serial="BD1")]
    with patch(f"{FLOW}.async_scan", AsyncMock(return_value=found)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"subnet": "192.0.2.0/24"})
    assert result["errors"] == {"base": "no_devices_found"}


async def test_default_subnet_from_adapters(hass: HomeAssistant) -> None:
    adapters = [
        {"enabled": False, "ipv4": [{"address": "198.51.100.4", "network_prefix": 24}]},
        {"enabled": True, "ipv4": [{"address": "192.0.2.7", "network_prefix": 16}]},
    ]
    with patch.object(scan.network, "async_get_adapters", AsyncMock(return_value=adapters)):
        assert await scan.async_default_subnet(hass) == IPv4Network("192.0.2.0/24")


def test_manifest_matchers() -> None:
    from pathlib import Path

    manifest = json.loads(Path("custom_components/av_matrix/manifest.json").read_text())
    macs = [m["macaddress"] for m in manifest["dhcp"] if "macaddress" in m]
    assert "D0C8578*" in macs  # Magewell (verified on three devices)
    assert all(m == m.upper() for m in macs)
    assert {"registered_devices": True} in manifest["dhcp"]
    assert "_netaudio-arc._udp.local." in manifest["zeroconf"]
