"""OPNsense API na bazie: klucz przy urządzeniu (API), kolektor (metryki, stan, dane do strony urządzenia).

Uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy).
"""

from __future__ import annotations

import asyncio
import os

import pytest

if os.environ.get("NETPULSE_TEST_DB") != "1":
    pytest.skip("brak testowej bazy (NETPULSE_TEST_DB=1)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from test_opnsense import transport  # noqa: E402

from netpulse.api import app  # noqa: E402
from netpulse.api import opnsense as opnsense_api  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import Device, Metric, OpnsenseApi, User  # noqa: E402
from netpulse.opnsense import FIRMWARE  # noqa: E402
from netpulse.opnsense import OpnsenseApi as Client  # noqa: E402
from netpulse.opnsense_collector import OpnsenseCollector  # noqa: E402

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}
KEY = {"api_key": "klucz-api-123456", "api_secret": "sekret-api-456789"}


def run(coro_fn):
    async def wrapper():
        try:
            return await coro_fn()
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


async def reset():
    await init_db()
    async with Session() as s, s.begin():
        await s.execute(delete(OpnsenseApi))
        await s.execute(delete(Device))
        await s.execute(delete(User))


@pytest.fixture
def client(monkeypatch):
    run(reset)
    login_limiter._failures.clear()
    # klient API w trasach rozmawia z atrapą zamiast z prawdziwym OPNsense
    monkeypatch.setattr(opnsense_api, "Client", lambda host, key, secret, **kw: Client(host, key, secret, transport=transport()))
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        assert c.put("/api/modules", json={"opnsense": True}).status_code == 200
        yield c
    run(reset)


def add_device() -> int:
    async def go():
        async with Session() as s, s.begin():
            d = Device(name="OPNsense", host="192.168.1.135", driver="opnsense")
            s.add(d)
            await s.flush()
            return d.id

    return run(go)


def poll(status: dict | None = None) -> None:
    collector = OpnsenseCollector(client_factory=lambda t: Client(t.host, t.key, t.secret, transport=transport(status=status)))

    async def go():
        await collector.poll_all()

    run(go)


def test_module_off_by_default_on_existing_install(client):
    assert client.put("/api/modules", json={"opnsense": False}).status_code == 200
    dev = add_device()
    assert client.post("/api/opnsense/apis", json={"device_id": dev, **KEY}).status_code == 409
    assert client.get(f"/api/opnsense/devices/{dev}").json()["configured"] is False


def test_probe_create_hides_secret_and_rejects_duplicate(client):
    dev = add_device()
    probe = client.post("/api/opnsense/probe", json={"device_id": dev, **KEY})
    assert probe.status_code == 200, probe.text
    assert probe.json()["version"] == "26.7.9_1" and probe.json()["monitored"] == 1 and probe.json()["dhcp"] == "dnsmasq"

    res = client.post("/api/opnsense/apis", json={"device_id": dev, **KEY})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["key_hint"] == "…3456" and body["version"] == "26.7.9_1"
    assert KEY["api_secret"] not in res.text and KEY["api_key"] not in res.text
    assert client.post("/api/opnsense/apis", json={"device_id": dev, **KEY}).status_code == 409

    api_id = body["id"]
    assert client.patch(f"/api/opnsense/apis/{api_id}", json={"port": 8443}).json()["port"] == 8443
    assert client.delete(f"/api/opnsense/apis/{api_id}").status_code == 204
    assert client.get("/api/opnsense/apis").json() == []


def test_collector_writes_metrics_and_device_data(client):
    dev = add_device()
    assert client.post("/api/opnsense/apis?probe=false", json={"device_id": dev, **KEY}).status_code == 201
    poll()

    async def metrics():
        async with Session() as s:
            rows = (await s.execute(select(Metric.name, Metric.key, Metric.value).where(Metric.device_id == dev))).all()
        return {(n, k): v for n, k, v in rows}

    rows = run(metrics)
    assert rows[("wan_latency_ms", "em1")] == 12.3
    assert rows[("gateway_up", "WAN_DHCP")] == 1.0
    assert rows[("opnsense_service_up", "dpinger/WAN_DHCP")] == 1.0
    assert [v for (n, _k), v in rows.items() if n == "client_down_bps"] == [2_376_000]  # ruch urządzenia w LAN

    data = client.get(f"/api/opnsense/devices/{dev}").json()
    assert data["configured"] and data["status"] == "up" and not data["stale"]
    assert data["version"] == "26.7.9_1" and data["update_available"] is False and data["dhcp"] == "dnsmasq"
    assert {i["device"] for i in data["interfaces"]} == {"em0", "em1"}  # tylko przypisane interfejsy
    assert len(data["services"]) == 17 and len(data["hosts"]) == 4
    assert data["traffic"] == "ok" and next(h for h in data["hosts"] if h["ip"] == "192.168.10.126")["down_bps"] == 2_376_000
    assert client.get("/api/opnsense/apis").json()[0]["status"] == "up"


def test_collector_failure_keeps_last_data(client):
    dev = add_device()
    assert client.post("/api/opnsense/apis?probe=false", json={"device_id": dev, **KEY}).status_code == 201
    poll()
    poll(status={FIRMWARE: 401})
    data = client.get(f"/api/opnsense/devices/{dev}").json()
    assert data["status"] == "down" and "klucz API" in data["last_error"]
    assert data["version"] == "26.7.9_1" and data["gateways"]  # ostatni udany odczyt zostaje
