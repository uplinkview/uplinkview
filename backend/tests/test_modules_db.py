"""Moduły: stan początkowy, zmiana przez administratora i to, co wyłączony moduł faktycznie wyłącza.

Uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest

if os.environ.get("NETPULSE_TEST_DB") != "1":
    pytest.skip("brak testowej bazy (NETPULSE_TEST_DB=1)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from pve_fake import FakePve  # noqa: E402
from sqlalchemy import delete, insert, select  # noqa: E402

from netpulse.alerts import AlertEngine  # noqa: E402
from netpulse.api import app  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import (  # noqa: E402
    Alert,
    AlertRule,
    AppSetting,
    Controller,
    Device,
    Metric,
    ProxmoxServer,
    User,
)
from netpulse.modules import SETTINGS_KEY, ensure_modules, get_modules  # noqa: E402
from netpulse.proxmox import ProxmoxApi  # noqa: E402
from netpulse.proxmox_collector import ProxmoxCollector  # noqa: E402

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}


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
        # Bez wpisu modułów inne testy widzą wszystko włączone (zachowanie sprzed 0.18)
        await s.execute(delete(AppSetting).where(AppSetting.key == SETTINGS_KEY))
        await s.execute(delete(Alert))
        await s.execute(delete(AlertRule))
        await s.execute(delete(ProxmoxServer))
        await s.execute(delete(Controller))
        await s.execute(delete(Device))
        await s.execute(delete(User))


@pytest.fixture
def client():
    run(reset)
    login_limiter._failures.clear()
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        yield c
    run(reset)


def test_defaults_without_entry_are_all_on_and_fresh_install_starts_with_integrations_off(client):
    assert client.get("/api/modules").json() == {"proxmox": True, "unifi": True, "opnsense": True, "agents": True, "backups": True}
    assert run(ensure_modules) == {"proxmox": False, "unifi": False, "opnsense": False, "agents": False, "backups": True}
    assert client.get("/api/modules").json()["proxmox"] is False
    # Drugi start niczego nie zmienia
    client.put("/api/modules", json={"proxmox": True})
    assert run(ensure_modules)["proxmox"] is True


def test_existing_install_keeps_configured_integrations(client):
    async def configured():
        async with Session() as s, s.begin():
            s.add(Controller(name="UniFi", host="10.7.0.1", api_key="klucz-api-1234"))

    run(configured)
    assert run(ensure_modules) == {"proxmox": False, "unifi": True, "opnsense": False, "agents": False, "backups": True}


def test_only_admin_changes_modules(client):
    res = client.put("/api/modules", json={"unifi": False, "nieznany": True})
    assert res.status_code == 200 and res.json()["unifi"] is False and "nieznany" not in res.json()
    client.post("/api/auth/logout")
    assert client.get("/api/modules").status_code == 401


def test_disabled_module_blocks_setup_and_hides_devices(client):
    client.put("/api/modules", json={"proxmox": False, "agents": False, "unifi": False})
    assert client.post("/api/agents", json={"name": "NAS"}).status_code == 409
    msg = client.post("/api/proxmox/servers", params={"probe": "false"}, json={
        "name": "Lab", "host": "10.7.0.2", "token_id": "netpulse@pve!monitor", "token_secret": "secret-uuid-1234",
    })  # fmt: skip
    assert msg.status_code == 409 and "Ustawienia → Moduły" in msg.json()["detail"]
    assert client.post("/api/controllers", params={"probe": "false"}, json={"name": "U", "host": "10.7.0.3", "api_key": "klucz-api-1234"}).status_code == 409

    async def devices():
        async with Session() as s, s.begin():
            s.add_all(
                [
                    Device(name="SW", host="10.7.0.10", community="public", status="up"),
                    Device(name="pve1", host="10.7.0.11", driver="proxmox", kind="server", status="up", community=None),
                    Device(name="NAS", host="nas-mod", driver="agent", kind="server", status="up", community=None),
                ]
            )

    run(devices)
    assert [d["name"] for d in client.get("/api/devices").json()] == ["SW"]
    assert client.get("/api/dashboard/summary").json()["devices"]["total"] == 1
    client.put("/api/modules", json={"proxmox": True})
    assert sorted(d["name"] for d in client.get("/api/devices").json()) == ["SW", "pve1"]


def test_disabled_module_rules_resolve_and_collector_stays_idle(client):
    async def setup():
        async with Session() as s, s.begin():
            s.add(ProxmoxServer(name="Lab", host="10.7.0.2", token_id="netpulse@pve!monitor", token_secret="secret-uuid-1234"))
            dev = Device(name="pve1", host="10.7.0.11", driver="proxmox", kind="server", status="up", community=None)
            s.add(dev)
            await s.flush()
            s.add(AlertRule(name="Kopia", kind="backup_failed", duration_s=0, severity="critical"))
            await s.execute(insert(Metric), [{"time": datetime.now(UTC), "device_id": dev.id, "name": "backup_task_ok", "key": "vzdump", "value": 0.0}])

    run(setup)

    async def firing():
        await AlertEngine().evaluate()
        async with Session() as s:
            return [a.title for a in (await s.scalars(select(Alert).where(Alert.state == "firing"))).all()]

    assert firing_titles(firing) == ["pve1: kopia zapasowa vzdump zakończyła się błędem"]
    client.put("/api/modules", json={"proxmox": False})
    assert firing_titles(firing) == []  # alert zakończony, bo moduł wyłączony

    fake = FakePve()
    collector = ProxmoxCollector(api_factory=lambda t: ProxmoxApi(t.host, t.token_id, t.token_secret, transport=fake.transport()))

    async def poll():
        await collector.poll_all()

    run(poll)
    assert fake.calls == []  # wyłączony moduł nie łączy się z Proxmoxem
    assert run(get_modules)["proxmox"] is False


def firing_titles(fn) -> list[str]:
    return run(fn)
