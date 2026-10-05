"""Dante® network entry inside a (test) Home Assistant, with simulated devices behind a fake UDP transport."""

from __future__ import annotations

import struct
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.av_matrix.const import DOMAIN
from custom_components.av_matrix.diagnostics import async_get_config_entry_diagnostics
from custom_components.av_matrix.drivers.dante import VERIFY_DELAYS, DanteNetwork
from custom_components.av_matrix.hub import DATA_HUB
from custom_components.av_matrix.protocols import dante as arc

from .dante_sim import FakeDanteDevice, FakeRx, FakeTransport, studio_network

AVIO = "AVIOAES3-0d0e0f"
DA = "DA-22UC-0a0b0c"
TXT = {"arcp_vers": "2.8.9", "mf": "Audinate", "model": "DIOAES3", "router_vers": "4.3.0"}


@pytest.fixture(autouse=True)
def dante_env(hass: HomeAssistant):
    network = studio_network()
    FakeTransport.hosts = {"192.0.2.31": network[AVIO], "192.0.2.32": network[DA]}
    hass.config.components.update({"frontend", "zeroconf"})

    async def fake_browse(self) -> None:  # mDNS: announce the devices of the fake network
        for host, dev in FakeTransport.hosts.items():
            if dev.mdns:
                self.driver.add_host(host, arc.ARC_PORT, TXT, mdns=True)

    with (
        patch("custom_components.av_matrix.drivers.dante.ArcTransport", FakeTransport),
        patch("custom_components.av_matrix.drivers.dante.VERIFY_DELAYS", (0.0,)),
        patch("custom_components.av_matrix.discovery.DanteMdnsBrowser.async_start", fake_browse),
        patch("custom_components.av_matrix.discovery.DanteMdnsBrowser.async_stop", AsyncMock()),
        patch("custom_components.av_matrix.discovery.NdiMdnsBrowser.async_start", AsyncMock()),
        patch("custom_components.av_matrix.discovery.NdiMdnsBrowser.async_stop", AsyncMock()),
        patch("custom_components.av_matrix._async_register_card", AsyncMock()),
    ):
        yield network


async def add_network(hass: HomeAssistant, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Dante network", unique_id="dante-network", data={"driver": "dante"}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.data[DATA_HUB].async_evaluate()
    await hass.async_block_till_done()
    return entry


def requests(dev: FakeDanteDevice, opcode: int) -> list[bytes]:
    return [p for p in dev.requests if struct.unpack_from(">H", p, 6)[0] == opcode]


# ------------------------------------------------------------------ config flow
async def test_config_flow_network(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    labels = [o["label"] for o in result["data_schema"].schema["driver"].config["options"]]
    assert "Dante® network – all devices, found automatically" in labels
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"driver": "dante"})
    assert result["step_id"] == "network"
    with patch("custom_components.av_matrix.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"static_hosts": "192.0.2.40, 192.0.2.41"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dante network"
    assert result["data"] == {"driver": "dante"}
    assert result["options"] == {"static_hosts": ["192.0.2.40", "192.0.2.41"]}
    # only one network entry
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"driver": "dante"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


# --------------------------------------------------------------------- entities
async def test_devices_entities_and_snapshot(hass: HomeAssistant) -> None:
    entry = await add_network(hass)
    assert entry.state is ConfigEntryState.LOADED
    dev_reg = dr.async_get(hass)
    avio = dev_reg.async_get_device_by_identifier((DOMAIN, f"dante-network_{AVIO}"), entry.entry_id)
    assert avio is not None and avio.manufacturer == "Audinate" and avio.model == "DIOAES3"
    assert avio.via_device_id == dev_reg.async_get_device_by_identifier((DOMAIN, "dante-network"), entry.entry_id).id

    state = hass.states.get("select.avioaes3_0d0e0f_ch1_source")
    assert state.attributes["options"] == [
        "None",
        f"CH1@{AVIO}",
        f"CH2@{AVIO}",
        f"CH1@{DA}",
        f"CH2@{DA}",
        "61@Example-WING-Fullsize",
    ]
    assert state.state == "61@Example-WING-Fullsize"  # mixer is off: kept as current source
    assert state.attributes["protocol"] == "dante"
    sub = hass.states.get("sensor.avioaes3_0d0e0f_ch1_subscription")
    assert sub.state == "unresolved"
    assert sub.attributes["status"] == "UNRESOLVED" and sub.attributes["connection"] == "source_lost"
    assert hass.states.get("sensor.avioaes3_0d0e0f_tx_channels").state == "2"
    assert hass.states.get("sensor.avioaes3_0d0e0f_rx_channels").state == "2"
    assert float(hass.states.get("sensor.avioaes3_0d0e0f_sample_rate").state) == 48.0
    assert hass.states.get("binary_sensor.avioaes3_0d0e0f_online").state == "on"
    assert hass.states.get("sensor.dante_network_dante_devices_online").state == "2"
    assert hass.states.get("switch.avioaes3_0d0e0f_ch1_route_lock") is not None
    assert hass.states.get("sensor.avioaes3_0d0e0f_ch1_connection") is None  # Dante: subscription sensor instead

    snap = hass.data[DATA_HUB].snapshot()["protocols"]["dante"]
    assert snap["title"] == "Dante®"
    assert [d["id"] for d in snap["destinations"]] == [
        f"dante-network_{AVIO}:1",
        f"dante-network_{AVIO}:2",
        f"dante-network_{DA}:1",
        f"dante-network_{DA}:2",
    ]
    d = snap["destinations"][0]
    assert (d["name"], d["group"], d["channel"], d["resolution"]) == (f"{AVIO} · CH1", AVIO, "CH1", "48 kHz")
    assert d["subscription"]["state"] == "unresolved" and d["status"] == "source_lost"
    src = {s["id"]: s for s in snap["sources"]}
    assert src[f"CH1@{DA}"]["group"] == DA and src[f"CH1@{DA}"]["channel"] == "CH1" and src[f"CH1@{DA}"]["live"]
    assert not src["61@Example-WING-Fullsize"]["live"]

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert {d["name"] for d in diag["dante_devices"]} == {AVIO, DA}


async def test_route_uses_paged_subscription_and_reads_back(hass: HomeAssistant, dante_env) -> None:
    await add_network(hass)
    avio = dante_env[AVIO]
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.avioaes3_0d0e0f_ch1_source", "option": f"CH2@{DA}"},
        blocking=True,
    )
    pkt = requests(avio, arc.OP_SUBSCRIPTION_PAGE)[-1]
    assert pkt[:2] == bytes.fromhex("2809")  # ARC 2.8.9 from the mDNS TXT record
    assert pkt[16:24] == bytes.fromhex("0800020100010003")  # capacity 2, one record, RX 1, audio
    assert pkt.endswith(f"CH2\0{DA}\0".encode())
    assert not requests(avio, arc.OP_SUBSCRIPTION_ADD)  # never the legacy write on a modern device
    await hass.async_block_till_done()
    await hass.data[DATA_HUB].async_evaluate()
    await hass.async_block_till_done()
    assert hass.states.get("select.avioaes3_0d0e0f_ch1_source").state == f"CH2@{DA}"
    await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.avioaes3_0d0e0f_ch1_subscription").state == "subscribed"

    # off = clear the subscription (record without strings)
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.avioaes3_0d0e0f_ch1_source", "source": "None"}, blocking=True
    )
    pkt = requests(avio, arc.OP_SUBSCRIPTION_PAGE)[-1]
    assert pkt[20:28] == bytes([0, 1, 0, 3, 0, 0, 0, 0])
    assert avio.rx[0].tx_channel is None
    # undo brings the previous source back
    await hass.services.async_call(DOMAIN, "undo", {"entity_id": "select.avioaes3_0d0e0f_ch1_source"}, blocking=True)
    assert (avio.rx[0].tx_channel, avio.rx[0].tx_device) == ("CH2", DA)


async def test_route_by_destination_id_and_salvo(hass: HomeAssistant, dante_env) -> None:
    await add_network(hass)
    await hass.services.async_call(
        DOMAIN, "route", {"destination": [f"dante-network_{DA}:2"], "source": f"CH1@{AVIO}"}, blocking=True
    )
    assert (dante_env[DA].rx[1].tx_channel, dante_env[DA].rx[1].tx_device) == ("CH1", AVIO)
    await hass.services.async_call(
        DOMAIN,
        "salvo",
        {
            "routes": [
                {"destination": f"dante-network_{DA}:1", "source": f"CH2@{AVIO}"},
                {"destination": "select.avioaes3_0d0e0f_ch2_source", "source": f"CH1@{DA}"},
            ]
        },
        blocking=True,
    )
    assert dante_env[DA].rx[0].tx_channel == "CH2"
    assert dante_env[AVIO].rx[1].tx_device == DA


async def test_route_errors(hass: HomeAssistant, dante_env) -> None:
    await add_network(hass)
    dante_env[AVIO].refuse = True
    with pytest.raises(HomeAssistantError, match="refused"):
        await hass.services.async_call(
            DOMAIN, "route", {"entity_id": "select.avioaes3_0d0e0f_ch1_source", "source": f"CH1@{DA}"}, blocking=True
        )
    dante_env[AVIO].refuse = False
    dante_env[AVIO].ignore_writes = True
    with pytest.raises(HomeAssistantError, match="did not apply"):
        await hass.services.async_call(
            DOMAIN, "route", {"entity_id": "select.avioaes3_0d0e0f_ch1_source", "source": f"CH1@{DA}"}, blocking=True
        )
    with pytest.raises(HomeAssistantError, match="not a Dante source"):
        await hass.services.async_call(
            DOMAIN, "route", {"entity_id": "select.avioaes3_0d0e0f_ch1_source", "source": "CAM (1)"}, blocking=True
        )


async def test_static_host_learns_protocol(hass: HomeAssistant, dante_env) -> None:
    """Without mDNS data the classic write is tried first; if the device ignores it, the paged one."""
    for dev in dante_env.values():
        dev.mdns = False
    await add_network(hass, {"static_hosts": ["192.0.2.31", "192.0.2.32"]})
    hub = hass.data[DATA_HUB]
    assert len(hub.destinations) == 4
    avio = dante_env[AVIO]
    orig = avio._write

    def only_paged(opcode, pkt):
        if opcode == arc.OP_SUBSCRIPTION_PAGE:
            orig(opcode, pkt)

    avio._write = only_paged
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.avioaes3_0d0e0f_ch1_source", "source": f"CH1@{DA}"}, blocking=True
    )
    assert requests(avio, arc.OP_SUBSCRIPTION_ADD) and requests(avio, arc.OP_SUBSCRIPTION_PAGE)
    assert avio.rx[0].tx_device == DA
    # the DA device accepts the classic write → stays on it
    await hass.services.async_call(
        DOMAIN, "route", {"entity_id": "select.da_22uc_0a0b0c_ch1_source", "source": f"CH2@{AVIO}"}, blocking=True
    )
    assert requests(dante_env[DA], arc.OP_SUBSCRIPTION_ADD) and not requests(dante_env[DA], arc.OP_SUBSCRIPTION_PAGE)


async def test_new_device_appears_and_offline(hass: HomeAssistant, dante_env) -> None:
    entry = await add_network(hass)
    coordinator = entry.runtime_data.coordinator
    big = FakeDanteDevice(
        "STAGEBOX-64",
        [f"Mic {n}" for n in range(1, 65)],
        [FakeRx(f"{n:02d}") for n in range(1, 65)],
        labels={1: "Kick"},
        network=dante_env,
    )
    dante_env[big.name] = big
    FakeTransport.hosts["192.0.2.33"] = big
    coordinator.driver.add_host("192.0.2.33", arc.ARC_PORT, TXT, mdns=True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    await hass.data[DATA_HUB].async_evaluate()
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("select", DOMAIN, "dante-network_STAGEBOX-64:1_source")
    assert entity_id is not None
    # 64 RX channels: entities exist but are disabled by default …
    assert ent_reg.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # … the matrix still shows (and routes) them, with the TX label "Kick"
    snap = hass.data[DATA_HUB].snapshot()["protocols"]["dante"]
    stage = [d for d in snap["destinations"] if d["group"] == "STAGEBOX-64"]
    assert len(stage) == 64 and stage[0]["entity_id"] is None and stage[1]["channel"] == "02"
    assert "Kick@STAGEBOX-64" in {s["id"] for s in snap["sources"]}
    assert "Mic 2@STAGEBOX-64" in {s["id"] for s in snap["sources"]}
    await hass.services.async_call(
        DOMAIN, "route", {"destination": ["dante-network_STAGEBOX-64:17"], "source": "Kick@STAGEBOX-64"}, blocking=True
    )
    assert big.rx[16].status == 0x04  # subscribed to itself
    assert len(requests(big, arc.OP_RX_CHANNELS)) >= 4  # 64 channels = 4 pages
    assert len(requests(big, arc.OP_TX_CHANNELS)) >= 2  # 2 pages

    # device goes offline → destinations unavailable, its sources go stale
    big.online = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.stagebox_64_online").state == "off"
    snap = hass.data[DATA_HUB].snapshot()["protocols"]["dante"]
    assert all(d["status"] == "offline" for d in snap["destinations"] if d["group"] == "STAGEBOX-64")
    assert hass.states.get("binary_sensor.avioaes3_0d0e0f_online").state == "on"
    # a device that left can be removed from the UI, a live one cannot
    dev_reg = dr.async_get(hass)
    from custom_components.av_matrix import async_remove_config_entry_device

    gone = dev_reg.async_get_device_by_identifier((DOMAIN, "dante-network_STAGEBOX-64"), entry.entry_id)
    live = dev_reg.async_get_device_by_identifier((DOMAIN, f"dante-network_{AVIO}"), entry.entry_id)
    assert await async_remove_config_entry_device(hass, entry, gone)
    assert not await async_remove_config_entry_device(hass, entry, live)


async def test_options_hide_devices_and_select_channels(hass: HomeAssistant) -> None:
    entry = await add_network(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "network"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 10, "devices": [AVIO], "only_selected": True, "static_hosts": ""}
    )
    assert result["step_id"] == "rx_channels"
    values = [o["value"] for o in result["data_schema"].schema["rx_selected"].config["options"]]
    assert values == [f"{AVIO}:1", f"{AVIO}:2"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"rx_selected": [f"{AVIO}:2"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["hidden_devices"] == [DA]
    await hass.async_block_till_done()
    hub = hass.data[DATA_HUB]
    await hub.async_evaluate()
    assert [d.dest_id for d in hub.destinations.values()] == [f"{AVIO}:2"]
    snap = hub.snapshot()["protocols"]["dante"]
    assert all(s["group"] == AVIO for s in snap["sources"] if s["live"])


async def test_reconfigure_aborts(hass: HomeAssistant) -> None:
    entry = await add_network(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "network_reconfigure"


async def test_unload(hass: HomeAssistant) -> None:
    entry = await add_network(hass)
    closed = []
    entry.runtime_data.coordinator.driver.close = lambda: closed.append(True)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert closed and not hass.data[DATA_HUB].destinations


def test_verify_delays_are_short() -> None:
    assert sum(VERIFY_DELAYS) < 1 and DanteNetwork.NETWORK


async def test_zeroconf_offers_the_network_once(hass: HomeAssistant) -> None:
    from ipaddress import ip_address

    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.31"),
        ip_addresses=[ip_address("192.0.2.31")],
        hostname=f"{AVIO}.local.",
        name=f"{AVIO}._netaudio-arc._udp.local.",
        port=4440,
        type="_netaudio-arc._udp.local.",
        properties=TXT,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "network"
    hass.config_entries.flow.async_abort(result["flow_id"])
    await add_network(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
