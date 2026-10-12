"""Gegenprobe mit den offiziellen AMWA-Schemata (IS-04 v1.3, IS-05 v1.1).

Simulation und Treiber stammen aus derselben Feder; diese Tests prüfen beide gegen etwas Unabhängiges:
* Was die Simulation ausliefert, ist gültiges IS-04 / IS-05 (sonst wäre sie als Prüfstein wertlos).
* Was der Treiber an ein Gerät schickt (jeder PATCH), ist gültig nach dem IS-05-Schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft4Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT4

from nmos_sim import blackmagic

from .conftest import BIDI, MINI, MakeNet, driver_for

SCHEMAS = Path(__file__).parent / "schemas"


def validator(spec: str, name: str) -> Draft4Validator:
    folder = SCHEMAS / spec

    def retrieve(uri: str) -> Resource:
        return Resource.from_contents(json.loads((folder / uri.rsplit("/", 1)[-1]).read_text()), default_specification=DRAFT4)

    schema = json.loads((folder / name).read_text())
    return Draft4Validator(schema, registry=Registry(retrieve=retrieve))


def check(spec: str, name: str, instance: Any) -> None:
    errors = sorted(validator(spec, name).iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, f"{name}: " + "; ".join(f"{'/'.join(map(str, e.path))}: {e.message[:160]}" for e in errors[:5])


async def get(session, url: str) -> Any:
    async with session.get(url) as resp:
        assert resp.status == 200, url
        return await resp.json()


@pytest.mark.parametrize("variant", ["studio", "four_nodes"])
async def test_simulated_devices_serve_valid_is04(make_net: MakeNet, session, variant: str) -> None:
    net = await make_net(blackmagic.studio() if variant == "studio" else blackmagic.converter_4x12g_as_four_nodes())
    for node in net.nodes:
        api = f"{node.url}/x-nmos/node/v1.3"
        check("is-04", "node.json", await get(session, f"{api}/self"))
        for what in ("devices", "sources", "flows", "senders", "receivers"):
            items = await get(session, f"{api}/{what}")
            check("is-04", f"{what}.json", items)
            for item in items:
                check("is-04", f"{what[:-1]}.json", await get(session, f"{api}/{what}/{item['id']}"))


async def test_simulated_devices_serve_valid_is05(make_net: MakeNet, session) -> None:
    net = await make_net([blackmagic.mini_bidirect_12g()])
    node = net.nodes[0]
    api = f"{node.connection_url}/x-nmos/connection/v1.1/single"
    for rid in node.receivers:
        for what in ("staged", "active"):
            check("is-05", "receiver-response-schema.json", await get(session, f"{api}/receivers/{rid}/{what}"))
        check("is-05", "constraints-schema.json", await get(session, f"{api}/receivers/{rid}/constraints"))
    for sid in node.senders:
        for what in ("staged", "active"):
            check("is-05", "sender-response-schema.json", await get(session, f"{api}/senders/{sid}/{what}"))


@pytest.mark.parametrize("quirk", [None, "params_only", "ignore"])
async def test_everything_the_driver_sends_is_valid_is05(make_net: MakeNet, session, quirk: str | None) -> None:
    """Verbinden (alle drei Arten), Trennen, Wiederherstellen, Sender einschalten – jeder PATCH gegen das Schema."""
    target = blackmagic.mini_ip_to_hdmi()
    if quirk:
        target.quirks.add(quirk)
    net = await make_net([target, blackmagic.mini_bidirect_12g()])
    driver = driver_for(session, net)
    await driver.async_poll()
    dest, source = f"{MINI}:HDMI Out", f"SDI In@{BIDI}"
    try:
        await driver.async_route(dest, source)
        snapshot = await driver.async_snapshot(dest)
        await driver.async_route(dest, None)
        await driver.async_restore(dest, snapshot)
    except Exception:  # noqa: BLE001 - "ignore" lässt das Schalten scheitern; geprüft werden die gesendeten Daten
        assert quirk == "ignore"
    mini, bidi = net.node(MINI), net.node(BIDI)
    assert len(mini.patches) >= 3 and len(bidi.patches) == (2 if quirk == "ignore" else 3)  # ignore: Sender an und wieder aus
    for _, body in mini.patches:
        check("is-05", "receiver-stage-schema.json", body)
    for _, body in bidi.patches:
        check("is-05", "sender-stage-schema.json", body)
    # und die Antworten der Simulation auf diese Aufrufe
    for rid in mini.receivers:
        check("is-05", "receiver-response-schema.json", mini.conn[rid]["active"])
