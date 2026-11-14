"""Endpointy pulpitu na prawdziwej bazie: podsumowanie oraz serie ruchu WAN i klientów WiFi.

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
from sqlalchemy import delete  # noqa: E402

from netpulse.api import app  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.config import settings  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import (  # noqa: E402
    Device,
    Interface,
    InterfaceMetric,
    User,
    WifiMetric,
    WifiNetwork,
)

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}


def run(coro_fn):
    async def wrapper():
        try:
            return await coro_fn()
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


def reset_db() -> None:
    async def go():
        await init_db()
        async with Session() as s, s.begin():
            await s.execute(delete(User))
            await s.execute(delete(Device))

    run(go)


@pytest.fixture
def client():
    reset_db()
    login_limiter._failures.clear()
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        yield c
    reset_db()


def _device(name: str, host: str, **kw) -> Device:
    return Device(name=name, host=host, community="public", **kw)


def seed() -> dict[str, int]:
    """Dwa routery (jeden aktywny, jeden nieaktywny), wyłączony switch, access point z dwiema sieciami WiFi."""
    now = datetime.now(UTC)

    async def go():
        async with Session() as s, s.begin():
            gw1 = _device("UCG", "10.1.0.1", status="up", kind="gateway", last_polled_at=now)
            gw2 = _device("Router 2", "10.1.0.2", status="down", kind="gateway", last_polled_at=now - timedelta(minutes=9))
            off = _device("Wyłączony", "10.1.0.3", status="up", kind="switch", enabled=False)
            ap = _device("AP", "10.1.0.4", status="up", kind="ap", last_polled_at=now - timedelta(seconds=20))
            s.add_all([gw1, gw2, off, ap])
            await s.flush()

            wan1 = Interface(device_id=gw1.id, if_index=1, name="eth4", role="wan")
            lan1 = Interface(device_id=gw1.id, if_index=2, name="eth0", role="lan")
            wan2 = Interface(device_id=gw2.id, if_index=1, name="wan", role="wan")
            wan_off = Interface(device_id=off.id, if_index=1, name="wan", role="wan")
            s.add_all([wan1, lan1, wan2, wan_off])
            ssid_a = WifiNetwork(device_id=ap.id, key="ra0", ssid="Dom", clients=5)
            ssid_b = WifiNetwork(device_id=ap.id, key="rai0", ssid="Dom 5G", clients=3)
            hidden = WifiNetwork(device_id=ap.id, key="vwire-0", ssid="vwire", clients=99, hidden=True)
            s.add_all([ssid_a, ssid_b, hidden])
            await s.flush()

            # wan1: starsza próbka (poza oknem „bieżącej”) i świeża; wan2 – tylko świeża; wan_off – ignorowany
            s.add_all(
                [
                    InterfaceMetric(time=now - timedelta(minutes=10), interface_id=wan1.id, in_bps=9e9, out_bps=9e9),
                    InterfaceMetric(time=now - timedelta(seconds=40), interface_id=wan1.id, in_bps=8e6, out_bps=1e6),
                    InterfaceMetric(time=now - timedelta(seconds=10), interface_id=wan1.id, in_bps=10e6, out_bps=2e6),
                    InterfaceMetric(time=now - timedelta(seconds=10), interface_id=wan2.id, in_bps=5e6, out_bps=None),
                    InterfaceMetric(time=now - timedelta(seconds=10), interface_id=lan1.id, in_bps=7e9, out_bps=7e9),
                    InterfaceMetric(time=now - timedelta(seconds=10), interface_id=wan_off.id, in_bps=4e9, out_bps=4e9),
                ]
            )
            s.add_all(
                [
                    WifiMetric(time=now - timedelta(seconds=40), wifi_id=ssid_a.id, clients=4),
                    WifiMetric(time=now - timedelta(seconds=40), wifi_id=ssid_b.id, clients=2),
                    WifiMetric(time=now - timedelta(seconds=10), wifi_id=ssid_a.id, clients=5),
                    WifiMetric(time=now - timedelta(seconds=10), wifi_id=ssid_b.id, clients=3),
                    WifiMetric(time=now - timedelta(seconds=10), wifi_id=hidden.id, clients=99),
                ]
            )
            return {"wan1": wan1.id}

    return run(go)


def test_requires_login():
    with TestClient(app) as c:
        for path in ("summary", "traffic", "wifi"):
            assert c.get(f"/api/dashboard/{path}").status_code == 401


def test_empty_database(client):
    r = client.get("/api/dashboard/summary").json()
    assert r["devices"] == {"total": 0, "up": 0, "down": 0, "unknown": 0}
    assert r["wan"] == {"in_bps": None, "out_bps": None, "interfaces": 0}
    assert r["wifi_clients"] is None and r["last_poll_at"] is None
    assert r["poll_interval_s"] == settings.poll_interval
    assert client.get("/api/dashboard/traffic").json()["points"] == []
    assert client.get("/api/dashboard/wifi").json()["points"] == []


def test_summary(client):
    seed()
    r = client.get("/api/dashboard/summary").json()
    # wyłączony switch nie liczy się do urządzeń ani do ruchu
    # Router 2: werdykt „down” sprzed 9 min – kolektor go nie potwierdza, więc „nieznany”, nie awaria (freshness.py)
    assert r["devices"] == {"total": 3, "up": 2, "down": 0, "unknown": 1}
    # WAN: tylko ostatnie próbki z 5 minut, suma po routerach (wan1 + wan2); LAN i wyłączone pominięte
    assert r["wan"]["interfaces"] == 2
    assert r["wan"]["in_bps"] == pytest.approx(15e6)
    assert r["wan"]["out_bps"] == pytest.approx(2e6)  # wan2 nie ma out_bps
    # klienci: 5 + 3, ukryta sieć pominięta
    assert r["wifi_clients"] == 8
    assert r["last_poll_at"] is not None
    # Lista urządzeń: status do pokazania + zapisany werdykt i znacznik nieaktualnych danych
    devices = {d["name"]: d for d in client.get("/api/devices").json()}
    assert (devices["Router 2"]["status"], devices["Router 2"]["stale"], devices["Router 2"]["last_status"]) == ("unknown", True, "down")
    assert (devices["UCG"]["status"], devices["UCG"]["stale"], devices["UCG"]["last_status"]) == ("up", False, "up")


def test_traffic_series_sums_wan_per_bucket(client):
    seed()
    r = client.get("/api/dashboard/traffic?minutes=5").json()
    assert r["interval_s"] == 30
    points = r["points"]
    assert 1 <= len(points) <= 3
    times = [p["time"] for p in points]
    assert times == sorted(times)
    # starsza próbka (10 min temu) poza zakresem; LAN i wyłączony switch nie wchodzą do sumy
    total_in = max(p["values"]["in_bps"] for p in points)
    assert total_in <= 15e6 + 1  # nigdy 9e9, 7e9 ani 4e9
    assert total_in >= 5e6
    assert all(set(p["values"]) == {"in_bps", "out_bps"} for p in points)


def test_wifi_series_excludes_hidden_networks(client):
    seed()
    points = client.get("/api/dashboard/wifi?minutes=5").json()["points"]
    assert points
    assert max(p["values"]["clients"] for p in points) <= 8  # 99 z ukrytej sieci nie wchodzi
    assert max(p["values"]["clients"] for p in points) >= 5


def test_longer_range_uses_larger_buckets(client):
    seed()
    r = client.get("/api/dashboard/traffic?minutes=1440").json()
    assert r["interval_s"] == 300  # 24 h w kubełkach 5-minutowych, jak w UniFi (od 0.71.0)
    assert r["points"]


def test_minutes_validated(client):
    assert client.get("/api/dashboard/traffic?minutes=1").status_code == 422
    assert client.get("/api/dashboard/traffic?minutes=999999").status_code == 422
