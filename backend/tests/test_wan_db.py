"""Dual WAN na prawdziwej bazie: kolektor (UCG Ultra z .snmprec), dane z kontrolera UniFi i API stanu, historii, SLA.

Uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from conftest import FIXTURES

if os.environ.get("NETPULSE_TEST_DB") != "1":
    pytest.skip("brak testowej bazy (NETPULSE_TEST_DB=1)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from netpulse import wan_links  # noqa: E402
from netpulse.api import app  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.collector import Collector  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import AppSetting, Device, Interface, InterfaceMetric, User, WanLink, WanLinkMetric  # noqa: E402
from netpulse.snmp.snmprec import SnmprecClient  # noqa: E402
from netpulse.unifi import WanPort  # noqa: E402

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}
HOST = "10.0.0.1"
ETH4 = 8  # ifIndex portu WAN (eth4) w zrzucie UCG Ultra
OPER = "1.3.6.1.2.1.2.2.1.8"


def run(coro_fn):
    async def wrapper():
        try:
            return await coro_fn()
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


async def _clean():
    async with Session() as s, s.begin():
        await s.execute(delete(Device))
        await s.execute(delete(User))
        await s.execute(delete(AppSetting).where(AppSetting.key == wan_links.SETTINGS_KEY))
        await s.execute(delete(AppSetting).where(AppSetting.key.startswith(wan_links.DETECTED_PREFIX)))


@pytest.fixture
def ucg():
    login_limiter._failures.clear()
    snmp = SnmprecClient.from_file(FIXTURES / "ucg-ultra.snmprec")

    async def go():
        await init_db()
        await _clean()
        async with Session() as s, s.begin():
            s.add(Device(name="UCG", host=HOST, community="public"))

    run(go)
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        yield c, snmp
    run(_clean)


def poll(snmp: SnmprecClient, collector: Collector | None = None) -> Collector:
    collector = collector or Collector(client_factory=lambda _t: snmp)

    async def go():
        await collector.poll_all()

    run(go)
    return collector


def interface_id(name: str) -> int:
    async def go():
        async with Session() as s:
            return await s.scalar(select(Interface.id).where(Interface.name == name))

    return run(go)


def test_wan_is_detected_and_recorded(ucg):
    client, snmp = ucg
    poll(snmp)

    status = client.get("/api/wan/status").json()
    (link,) = status["links"]
    assert (link["name"], link["interface_name"], link["position"]) == ("WAN 1", "eth4", 1)
    assert link["state"] == "active" and link["source"] == "traffic" and link["sampled_at"]
    assert status["active_ids"] == [link["id"]]

    async def count():
        async with Session() as s:
            return await s.scalar(select(func.count()).select_from(WanLinkMetric))

    assert run(count) == 1


def test_failover_history_and_sla(ucg):
    client, snmp = ucg
    collector = poll(snmp)
    links = [{"interface_id": interface_id("eth4"), "name": "Światłowód"}, {"interface_id": interface_id("eth3"), "name": "LTE"}]
    saved = client.put("/api/wan/links", json={"links": links})
    assert saved.status_code == 200, saved.text
    assert [(x["name"], x["position"], x["interface_name"]) for x in saved.json()] == [("Światłowód", 1, "eth4"), ("LTE", 2, "eth3")]

    # Oba łącza działają, ruch znikomy – zostaje łącze, które było aktywne
    poll(snmp, collector)
    states = {x["name"]: x["state"] for x in client.get("/api/wan/status").json()["links"]}
    assert states == {"Światłowód": "active", "LTE": "standby"}
    # Port LAN 4 ustawiony jako WAN 2 liczy się jak WAN (ruch WAN, „Na żywo”, alerty)
    ports = {i["name"]: i for i in client.get(f"/api/devices/{saved.json()[0]['device_id']}/interfaces").json()}
    assert ports["eth3"]["role"] == "wan" and ports["eth3"]["label"] == "LTE"
    assert ports["eth4"]["label"] == "WAN"

    # Awaria WAN 1: link znika, ruch przejmuje WAN 2
    snmp.set(f"{OPER}.{ETH4}", 2)
    poll(snmp, collector)
    status = client.get("/api/wan/status").json()
    by_name = {x["name"]: x for x in status["links"]}
    assert by_name["Światłowód"]["state"] == "down" and by_name["LTE"]["state"] == "active"
    assert status["active_ids"] == [by_name["LTE"]["id"]]

    history = client.get("/api/wan/history", params={"minutes": 60}).json()
    wan1, wan2 = by_name["Światłowód"]["id"], by_name["LTE"]["id"]
    assert [(e["from_ids"], e["to_ids"]) for e in history["switches"]] == [([wan1], [wan2])]
    assert {(s["link_id"], s["state"]) for s in history["segments"]} >= {(wan1, "active"), (wan1, "down"), (wan2, "standby"), (wan2, "active")}
    assert history["points"] and f"in_{wan2}" in history["points"][0]["values"]

    sla = {x["link"]["name"]: x for x in client.get("/api/wan/sla", params={"days": 7}).json()["links"]}
    assert sla["Światłowód"]["outages"] == 1 and sla["Światłowód"]["recent_outages"][0]["ongoing"]
    assert sla["Światłowód"]["availability"] < 100
    assert sla["LTE"]["availability"] == 100 and sla["LTE"]["outages"] == 0
    assert client.get("/api/wan/sla", params={"days": 0}).status_code == 422

    # Usunięcie łącza z listy: port wraca do roli LAN, kolektor nie dokłada go sam z powrotem
    assert client.put("/api/wan/links", json={"links": links[:1]}).status_code == 200
    poll(snmp, collector)
    ports = {i["name"]: i for i in client.get(f"/api/devices/{saved.json()[0]['device_id']}/interfaces").json()}
    assert ports["eth3"]["role"] == "lan" and ports["eth3"]["label"] == "LAN 4"
    assert len(client.get("/api/wan/links").json()) == 1


def test_transfer_usage(ucg):
    """Licznik transferu: bajty = szybkość × cykl kolektora / 8, dziś i w okresie, każdy dzień okresu na liście."""
    client, snmp = ucg
    poll(snmp)
    eth4 = interface_id("eth4")
    now = datetime.now(UTC)

    eth0 = interface_id("eth0")

    async def samples():
        async with Session() as s, s.begin():
            await s.execute(delete(InterfaceMetric))
            # Dwie próbki po 30 s: 8 Mb/s w dół, 0,8 Mb/s w górę → 2 × 30 MB i 2 × 3 MB
            for back in (5, 35):
                s.add(InterfaceMetric(time=now - timedelta(seconds=back), interface_id=eth4, in_bps=8e6, out_bps=8e5))
            # WAN routera za bramą (np. OPNsense w VM): rola `wan`, ale nie na liście łączy – jego ruch już policzyło eth4
            (await s.get(Interface, eth0)).role = "wan"
            s.add(InterfaceMetric(time=now - timedelta(seconds=5), interface_id=eth0, in_bps=8e9, out_bps=8e9))

    run(samples)
    body = client.get("/api/wan/usage").json()
    assert body["total_today"] == {"rx_bytes": 60e6, "tx_bytes": 6e6}
    assert body["total_period"] == body["total_today"]
    (port,) = body["ports"]
    assert (port["name"], port["interface_id"], port["period"]["rx_bytes"]) == ("WAN 1", eth4, 60e6)
    assert body["period_start"].endswith("-01") and body["days"][0]["day"] == body["period_start"]
    assert body["days"][-1] == {"day": body["today"], "rx_bytes": 60e6, "tx_bytes": 6e6}
    # Okres od innego dnia i filtr routera
    assert client.get("/api/wan/usage", params={"reset_day": 15}).json()["period_start"][-2:] == "15"
    assert client.get("/api/wan/usage", params={"device_id": 999999}).json()["ports"] == []
    assert client.get("/api/wan/usage", params={"reset_day": 29}).status_code == 422


def test_controller_decides_active_link(ucg):
    client, snmp = ucg
    collector = poll(snmp)
    links = [{"interface_id": interface_id("eth4"), "name": "WAN 1"}, {"interface_id": interface_id("eth3"), "name": "WAN 2"}]
    assert client.put("/api/wan/links", json={"links": links}).status_code == 200

    async def controller_says(wans):
        async with Session() as s, s.begin():
            dev_id = await s.scalar(select(Device.id))
            return await wan_links.apply_controller(s, dev_id, wans, datetime.now(UTC))

    # UniFi: WAN 1 ma link, ale bez internetu; ruch idzie przez WAN 2
    assert run(lambda: controller_says([WanPort("eth4", False, False), WanPort("eth3", True, True)])) == 2
    poll(snmp, collector)
    by_name = {x["name"]: x for x in client.get("/api/wan/status").json()["links"]}
    assert (by_name["WAN 1"]["state"], by_name["WAN 2"]["state"]) == ("down", "active")
    assert by_name["WAN 2"]["source"] == "controller"


def test_controller_suggests_missing_wan_link(ucg):
    """Kontroler zna WAN 2 (np. internet mobilny na porcie 4), którego nie ma na liście – podpowiedź w ustawieniach."""
    client, snmp = ucg
    poll(snmp)
    assert client.get("/api/wan/suggestions").json() == []

    async def controller_says(wans):
        async with Session() as s, s.begin():
            dev_id = await s.scalar(select(Device.id))
            await wan_links.save_detected(s, dev_id, wans)

    wans = [WanPort("eth3", True, False, slot=2), WanPort("eth4", True, True, slot=1)]
    run(lambda: controller_says(wans))
    (hint,) = client.get("/api/wan/suggestions").json()
    assert (hint["interface_name"], hint["interface_label"], hint["slot"], hint["up"], hint["active"]) == ("eth3", "LAN 4", 2, True, False)

    # Po dodaniu łącza podpowiedź znika
    links = [{"interface_id": interface_id("eth4"), "name": "WAN 1"}, {"interface_id": hint["interface_id"], "name": "LTE"}]
    assert client.put("/api/wan/links", json={"links": links}).status_code == 200
    assert client.get("/api/wan/suggestions").json() == []
    # Kontroler przestał zgłaszać WAN 2 i łącza nie ma na liście – bez podpowiedzi
    assert client.put("/api/wan/links", json={"links": links[:1]}).status_code == 200
    run(lambda: controller_says(wans[1:]))
    assert client.get("/api/wan/suggestions").json() == []


def test_router_offline_makes_links_unknown(ucg):
    client, snmp = ucg
    collector = poll(snmp)

    async def fail():
        (target,) = await collector.load_targets()
        await collector.save_failure(target, datetime.now(UTC), "timeout")

    run(fail)
    assert [x["state"] for x in client.get("/api/wan/status").json()["links"]] == ["unknown"]


def test_priority_is_shared_between_routers(ucg):
    """WAN 1 na jednym routerze, WAN 2 na drugim: WAN 1 jest główne, WAN 2 przejmuje ruch, gdy WAN 1 padnie."""
    client, snmp = ucg
    second = SnmprecClient.from_file(FIXTURES / "ucg-ultra.snmprec")

    async def add_second():
        async with Session() as s, s.begin():
            s.add(Device(name="Zapasowy", host="10.0.0.2", community="public"))

    run(add_second)
    collector = Collector(client_factory=lambda t: snmp if t.host == HOST else second)
    poll(snmp, collector)

    async def eth4_ids():
        async with Session() as s:
            rows = await s.execute(select(Device.name, Interface.id).join(Interface).where(Interface.name == "eth4"))
            return dict(rows.all())

    ids = run(eth4_ids)
    # Kolejność jak w ustawieniach: WAN 1 to router „Zapasowy” (nazwa nie decyduje, decyduje pozycja)
    links = [{"interface_id": ids["Zapasowy"], "name": "WAN 1"}, {"interface_id": ids["UCG"], "name": "WAN 2"}]
    saved = client.put("/api/wan/links", json={"links": links})
    assert [(x["name"], x["position"]) for x in saved.json()] == [("WAN 1", 1), ("WAN 2", 2)]

    poll(snmp, collector)
    poll(snmp, collector)
    status = client.get("/api/wan/status").json()
    assert [(x["name"], x["state"]) for x in status["links"]] == [("WAN 1", "active"), ("WAN 2", "standby")]

    # Awaria WAN 1 – w następnym cyklu ruch przejmuje WAN 2 na drugim routerze
    second.set(f"{OPER}.{ETH4}", 2)
    poll(snmp, collector)
    poll(snmp, collector)
    status = client.get("/api/wan/status").json()
    assert [(x["name"], x["state"]) for x in status["links"]] == [("WAN 1", "down"), ("WAN 2", "active")]
    wan1, wan2 = (x["id"] for x in status["links"])
    history = client.get("/api/wan/history", params={"minutes": 60}).json()
    assert (history["switches"][-1]["from_ids"], history["switches"][-1]["to_ids"]) == ([wan1], [wan2])

    # WAN 1 wraca – ruch wraca na łącze główne
    second.set(f"{OPER}.{ETH4}", 1)
    poll(snmp, collector)
    poll(snmp, collector)
    assert [x["state"] for x in client.get("/api/wan/status").json()["links"]] == ["active", "standby"]


def test_links_validation_and_login(ucg):
    client, snmp = ucg
    poll(snmp)
    eth4 = interface_id("eth4")
    assert client.put("/api/wan/links", json={"links": [{"interface_id": eth4, "name": "A"}, {"interface_id": eth4, "name": "B"}]}).status_code == 422
    assert client.put("/api/wan/links", json={"links": [{"interface_id": 999999, "name": "A"}]}).status_code == 422
    assert client.put("/api/wan/links", json={"links": [{"interface_id": eth4, "name": "  "}]}).status_code == 422
    assert client.put("/api/wan/links", json={"links": []}).status_code == 200
    assert client.get("/api/wan/status").json() == {"links": [], "active_ids": []}

    async def links_left():
        async with Session() as s:
            return await s.scalar(select(func.count()).select_from(WanLink))

    assert run(links_left) == 0
    client.post("/api/auth/logout")
    assert client.get("/api/wan/status").status_code == 401
