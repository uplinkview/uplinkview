"""Prędkość WAN co 5 s na prawdziwej bazie (od 0.85.0): zapis próbnika i jedna linia wykresów ruchu WAN i portu.

Uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy z TimescaleDB).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

if os.environ.get("NETPULSE_TEST_DB") != "1":
    pytest.skip("brak testowej bazy (NETPULSE_TEST_DB=1)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from netpulse.api import app  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import Device, Interface, InterfaceMetric, User, WanRateMetric  # noqa: E402
from netpulse.snmp import oids as O  # noqa: E402
from netpulse.wanrate import WanSampler  # noqa: E402

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}
MBPS = 1_000_000


def run(coro_fn):
    async def wrapper():
        try:
            return await coro_fn()
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


async def _reset():
    await init_db()
    async with Session() as s, s.begin():
        await s.execute(delete(Device))
        await s.execute(delete(User))


@pytest.fixture
def gateway():
    """Brama z portem WAN (eth4) i portem LAN; zwraca (id urządzenia, id portu WAN, id portu LAN)."""
    login_limiter._failures.clear()

    async def go():
        await _reset()
        async with Session() as s, s.begin():
            dev = Device(name="UCG Ultra", host="10.0.0.1", community="public", kind="gateway", status="up")
            s.add(dev)
            await s.flush()
            wan = Interface(device_id=dev.id, if_index=5, name="eth4", label="WAN", role="wan", oper_status="up", speed_mbps=1000, if_type=6)
            lan = Interface(device_id=dev.id, if_index=1, name="eth0", label="LAN 1", role="lan", oper_status="up", speed_mbps=1000, if_type=6)
            s.add_all([wan, lan])
            await s.flush()
            return dev.id, wan.id, lan.id

    ids = run(go)
    yield ids
    run(_reset)


def test_chart_line_is_the_real_speed_not_the_average(gateway):
    """Pobieranie 800 Mb/s przez 20 s: średnia z 30 s to ~270 Mb/s, wykres pokazuje 800 Mb/s – na 1 h i na 24 h."""
    _, wan_id, _ = gateway
    base = datetime.fromtimestamp((int(datetime.now(UTC).timestamp()) // 300 - 2) * 300, UTC)  # pełne 5 minut temu

    async def seed():
        async with Session() as s, s.begin():
            # Średnie z 30 s (kolektor): przed pobieraniem 2 Mb/s, w cyklu z pobieraniem 270 Mb/s
            s.add(InterfaceMetric(time=base + timedelta(seconds=15), interface_id=wan_id, in_bps=2 * MBPS, out_bps=1 * MBPS, oper_up=True))
            s.add(InterfaceMetric(time=base + timedelta(seconds=45), interface_id=wan_id, in_bps=270 * MBPS, out_bps=5 * MBPS, oper_up=True))
            # Pomiar co 5 s tylko w drugim cyklu: cztery przedziały po 800 Mb/s
            for k in range(6):
                down = 800 * MBPS if 1 <= k <= 4 else 4 * MBPS
                s.add(WanRateMetric(time=base + timedelta(seconds=30 + 5 * k), interface_id=wan_id, in_bps=down, out_bps=6 * MBPS))

    run(seed)
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        hour = c.get("/api/dashboard/traffic", params={"minutes": 60}).json()
        assert hour["interval_s"] == 30  # kubełek 15 s, ale luki dopiero po 75 s
        by_time = {p["time"][:19]: p["values"] for p in hour["points"]}
        first = (base + timedelta(seconds=15)).strftime("%Y-%m-%dT%H:%M:%S")  # kubełek 15 s z próbką średniej
        assert by_time[first]["in_bps"] == 2 * MBPS  # bez pomiaru co 5 s – średnia
        assert max(v["in_bps"] or 0 for v in by_time.values()) == 800 * MBPS
        assert sum(1 for v in by_time.values() if v["in_bps"] == 800 * MBPS) >= 1
        port = c.get(f"/api/interfaces/{wan_id}/metrics", params={"minutes": 60}).json()
        assert max(p["values"]["in_bps"] or 0 for p in port) == 800 * MBPS
        assert {"in_bps", "out_bps", "in_errors"} <= set(port[0]["values"])
        day = c.get("/api/dashboard/traffic", params={"minutes": 1440}).json()["points"]
        assert max(p["values"]["in_bps"] or 0 for p in day) == 800 * MBPS  # kubełek 5 min: najwyższa, nie średnia
        # Zakres 30 dni: agregat godzinowych maksimów – bez błędu
        for path in ("/api/dashboard/traffic", f"/api/interfaces/{wan_id}/metrics"):
            assert c.get(path, params={"minutes": 43200}).status_code == 200


class _Counters:
    """Atrapa klienta SNMP: liczniki portu WAN rosną z zadaną prędkością."""

    def __init__(self) -> None:
        self.octets = 0
        self.asked: list[list[str]] = []

    async def get(self, oids: list[str]) -> dict:
        self.asked.append(oids)
        return {oid: self.octets for oid in oids}

    async def close(self) -> None:
        pass


def test_sampler_reads_only_wan_ports_and_writes_five_second_rows(gateway):
    dev_id, wan_id, _ = gateway
    client = _Counters()
    sampler = WanSampler(client_factory=lambda target: client, interval=1)
    start = (int(datetime.now(UTC).timestamp()) // 5 - 10) * 5

    async def go():
        targets = await sampler.load_targets()
        assert list(targets) == [dev_id]
        target, ports = targets[dev_id]
        assert [p.if_index for p in ports] == [5]  # tylko port z rolą WAN, bez LAN
        for second in range(21):
            client.octets = int(second * 200 * MBPS / 8)
            await sampler.sample_device(target, ports, float(start + second))
        assert client.asked[0] == [f"{O.IF_HC_IN_OCTETS}.5", f"{O.IF_HC_OUT_OCTETS}.5"]
        await sampler.write(sampler.take_rows(float(start + 21)))
        async with Session() as s:
            rows = (await s.execute(select(WanRateMetric).order_by(WanRateMetric.time))).scalars().all()
        assert [r.interface_id for r in rows] == [wan_id] * 4
        assert [int(r.time.timestamp()) for r in rows] == [start, start + 5, start + 10, start + 15]
        assert all(round(r.in_bps / MBPS) == 200 and round(r.out_bps / MBPS) == 200 for r in rows)
        await sampler.write(sampler.take_rows(float(start + 21)))  # nic nowego – bez powtórek

    run(go)
