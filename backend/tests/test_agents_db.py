"""Agenci serwerów: token z panelu, raport agenta, zapis metryk, stan w API, odwołanie tokenu, cisza agenta.

Uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

if os.environ.get("NETPULSE_TEST_DB") != "1":
    pytest.skip("brak testowej bazy (NETPULSE_TEST_DB=1)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, func, select, update  # noqa: E402

from netpulse.api import app  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.collector import Collector  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import Agent, Device, DeviceMetric, DiskMetric, Metric, User  # noqa: E402

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}

REPORT = {
    "agent_version": "0.11.0",
    "hostname": "nas-test",
    "os": "Ubuntu 24.04.1 LTS",
    "kernel": "6.8.0-45-generic",
    "uptime_s": 3600.0,
    "cpu_percent": 12.5,
    "cpu_cores": [10.0, 15.0],
    "load": [0.5, 0.4, 0.3],
    "mem_used_percent": 40.0,
    "mem_total_bytes": 8 * 1024**3,
    "swap_used_percent": 5.0,
    "processes": 150,
    "disks": [{"mount": "/", "fs": "ext4", "total_bytes": 100 * 1024**3, "used_bytes": 30 * 1024**3}],
    "net": [{"iface": "eth0", "rx_bps": 1000.0, "tx_bps": 2000.0}],
    "temps": [{"sensor": "coretemp/Package id 0", "celsius": 48.0}],
    "services": {"running": 30, "failed": 1, "items": [
        {"name": "backup.service", "active": "failed", "sub": "failed"},
        {"name": "ssh.service", "active": "active", "sub": "running", "watched": False, "mem_bytes": 4194304, "uptime_s": 60},
    ]},
    "containers": [{"name": "nextcloud", "image": "nextcloud:29", "state": "running", "cpu_percent": 2.0, "mem_bytes": 500_000_000}],
    "smart": [{"device": "sda", "model": "WDC", "passed": True, "temp_c": 35}],
}


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
        await s.execute(delete(Device))
        await s.execute(delete(User))


async def allow_next_report():
    """Raporty częściej niż co 5 s są odrzucane – w testach cofamy znacznik ostatniego raportu."""
    async with Session() as s, s.begin():
        await s.execute(update(Agent).values(last_seen_at=datetime.now(UTC) - timedelta(minutes=1)))


@pytest.fixture
def client():
    run(reset)
    login_limiter._failures.clear()
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        yield c
    run(reset)


def create(c: TestClient, name: str = "NAS") -> dict:
    res = c.post("/api/agents", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()


def push(c: TestClient, token: str, body: dict | None = None):
    # Agent nie ma ciasteczka sesji – tylko token
    return c.post("/api/agent/v1/report", json=body or REPORT, headers={"Authorization": f"Bearer {token}"})


def test_agent_report_flow(client):
    created = create(client)
    token, agent = created["token"], created["agent"]
    assert token.startswith("npa_") and agent["token_hint"] == token[-4:]
    assert agent["status"] == "unknown" and agent["last_seen_at"] is None

    device = client.get(f"/api/devices/{agent['device_id']}").json()
    assert device["driver"] == "agent" and device["kind"] == "server"

    anon = TestClient(app)
    res = anon.post("/api/agent/v1/report", json=REPORT, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    assert res.json()["accepted"] is True and res.json()["interval_s"] > 0
    # Drugi raport zaraz po pierwszym – odrzucony
    assert anon.post("/api/agent/v1/report", json=REPORT, headers={"Authorization": f"Bearer {token}"}).status_code == 429
    assert anon.post("/api/agent/v1/report", json=REPORT, headers={"Authorization": "Bearer npa_zly"}).status_code == 401

    device = client.get(f"/api/devices/{agent['device_id']}").json()
    assert device["status"] == "up"
    assert device["host"] == "nas-test"
    assert device["model"] == "Ubuntu 24.04.1 LTS"

    server = client.get(f"/api/devices/{agent['device_id']}/server").json()
    assert server["cpu_percent"] == 12.5 and server["swap_used_percent"] == 5.0 and server["processes"] == 150
    assert server["disks"][0]["used_percent"] == 30.0
    assert server["agent"]["containers"][0]["name"] == "nextcloud"
    assert server["agent"]["services"]["failed"] == 1
    assert server["agent"]["cpu_cores"] == 2
    assert server["agent"]["temps"][0]["celsius"] == 48.0
    assert server["agent"]["net"] == [{"iface": "eth0", "rx_bps": 1000.0, "tx_bps": 2000.0}]
    assert server["agent"]["agent_version"] == "0.11.0" and server["agent"]["outdated"] is True

    listed = client.get("/api/agents").json()
    assert listed[0]["hostname"] == "nas-test" and listed[0]["agent_version"] == "0.11.0"
    assert listed[0]["outdated"] is True
    assert listed[0]["last_ip"]

    async def counts():
        async with Session() as s:
            dev_id = agent["device_id"]
            return (
                await s.scalar(select(func.count()).select_from(DeviceMetric).where(DeviceMetric.device_id == dev_id)),
                await s.scalar(select(func.count()).select_from(DiskMetric).where(DiskMetric.device_id == dev_id)),
                {r.name for r in (await s.scalars(select(Metric).where(Metric.device_id == dev_id))).all()},
            )

    dm, disks, names = run(counts)
    assert dm == 1 and disks == 1
    assert {"cpu_core_percent", "load15", "net_rx_bps", "temp_c", "service_up", "container_up", "smart_ok"} <= names

    async def service_keys():
        async with Session() as s:
            return set((await s.scalars(select(Metric.key).where(Metric.device_id == agent["device_id"], Metric.name == "service_up"))).all())

    assert run(service_keys) == {"backup.service"}  # działająca, nieobserwowana usługa – tylko w tabeli, bez historii

    # Wykresy z danych agenta (tabela metrics)
    dev = agent["device_id"]
    keys = client.get(f"/api/devices/{dev}/agent-keys").json()
    assert keys == {
        "agent_net": ["eth0"],
        "agent_disk": [],
        "agent_temp": ["coretemp/Package id 0"],
        "agent_container": ["nextcloud"],
        "pve_guest": [],
        # Czujniki SNMP tylko dla urządzeń SNMP – temperatura serwera z agentem nie trafia do „Czujnika urządzenia”
        "snmp_sensor": [],
        "snmp_poe": [],
        "snmp_sfp": [],
        "wan_latency": [],
        "speedtest": [],
        "wan_ping": [],
        "vpn": [],
        "lan_client": [],
    }
    net = client.get(f"/api/devices/{dev}/agent-metrics", params={"source": "agent_net", "key": "eth0"}).json()
    assert net[-1]["values"] == {"rx_bps": 1000.0, "tx_bps": 2000.0}
    cpu = client.get(f"/api/devices/{dev}/agent-metrics", params={"source": "agent_cpu"}).json()
    assert cpu[-1]["values"] == {"core_max_percent": 15.0, "core_avg_percent": 12.5}
    cont = client.get(f"/api/devices/{dev}/agent-metrics", params={"source": "agent_container", "key": "nextcloud"}).json()
    assert cont[-1]["values"]["container_mem_bytes"] == 500_000_000
    assert client.get(f"/api/devices/{dev}/agent-metrics", params={"source": "nie_ma"}).status_code == 422

    # Panel: SNMP nie dotyczy serwera z agentem; nazwę zmienić można
    assert client.post(f"/api/devices/{agent['device_id']}/probe").status_code == 409
    assert client.patch(f"/api/devices/{agent['device_id']}", json={"host": "10.0.0.9"}).status_code == 409
    assert client.patch(f"/api/devices/{agent['device_id']}", json={"name": "NAS w piwnicy"}).status_code == 200


def test_rotate_token_and_disable(client):
    created = create(client)
    old, agent_id, dev_id = created["token"], created["agent"]["id"], created["agent"]["device_id"]
    rotated = client.post(f"/api/agents/{agent_id}/token").json()
    assert rotated["token"] != old
    assert push(client, old).status_code == 401
    assert push(client, rotated["token"]).status_code == 200

    run(allow_next_report)
    assert client.patch(f"/api/devices/{dev_id}", json={"enabled": False}).status_code == 200
    res = push(client, rotated["token"])
    assert res.status_code == 200 and res.json()["accepted"] is False

    async def dm_count():
        async with Session() as s:
            return await s.scalar(select(func.count()).select_from(DeviceMetric).where(DeviceMetric.device_id == dev_id))

    assert run(dm_count) == 1  # raport z wyłączonego serwera nie zapisuje danych

    # Usunięcie urządzenia usuwa też agenta – token przestaje działać
    run(allow_next_report)
    assert client.delete(f"/api/devices/{dev_id}").status_code == 204
    assert push(client, rotated["token"]).status_code == 401
    assert client.get("/api/agents").json() == []


def test_silent_agent_marks_server_down_and_is_not_polled(client):
    created = create(client)
    dev_id = created["agent"]["device_id"]
    assert push(client, created["token"]).status_code == 200

    async def scenario():
        collector = Collector()
        targets = await collector.load_targets()
        assert dev_id not in {t.id for t in targets}
        # Świeży raport – nic się nie dzieje
        assert await collector.mark_silent_agents() == []
        # Za 10 minut bez raportu – serwer niedostępny (raz)
        later = datetime.now(UTC) + timedelta(minutes=10)
        assert await collector.mark_silent_agents(later) == [dev_id]
        assert await collector.mark_silent_agents(later) == []
        async with Session() as s:
            device = await s.get(Device, dev_id)
            return device.status, device.last_error

    status, error = run(scenario)
    assert status == "down" and "Agent" in error

    run(allow_next_report)
    assert push(client, created["token"]).status_code == 200
    assert client.get(f"/api/devices/{dev_id}").json()["status"] == "up"


def test_agents_admin_only(client):
    client.post("/api/auth/logout")
    assert client.get("/api/agents").status_code == 401
    assert client.post("/api/agents", json={"name": "x"}).status_code == 401
