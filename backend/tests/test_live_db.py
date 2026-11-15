"""Tryb „Na żywo” na prawdziwej bazie: które porty trafiają do odpytywania.

Uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy).
"""

from __future__ import annotations

import asyncio
import os

import pytest

if os.environ.get("NETPULSE_TEST_DB") != "1":
    pytest.skip("brak testowej bazy (NETPULSE_TEST_DB=1)", allow_module_level=True)

from sqlalchemy import delete  # noqa: E402

from netpulse.api.live import LiveHub  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import Device, Interface  # noqa: E402


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


@pytest.fixture
def db():
    run(init_db)
    run(_clean)
    yield
    run(_clean)


def test_targets_are_visible_ports_of_watched_snmp_devices(db):
    async def seed():
        async with Session() as s, s.begin():
            gw = Device(name="UCG", host="10.0.0.1", community="public", kind="gateway", detected_driver="unifi")
            ap = Device(name="AP", host="10.0.0.3", community="public", kind="ap", detected_driver="nie-ma-takiego")
            sw = Device(name="USW", host="10.0.0.2", community="public", kind="switch")
            nas = Device(name="NAS", host="10.0.0.9", community="public", kind="server", driver="agent")
            s.add_all([gw, sw, nas, ap])
            await s.flush()
            s.add_all(
                [
                    Interface(device_id=gw.id, if_index=5, name="eth4", role="wan", speed_mbps=1000),
                    Interface(device_id=gw.id, if_index=1, name="eth0", role="lan"),
                    Interface(device_id=gw.id, if_index=9, name="lo", hidden=True),
                    Interface(device_id=sw.id, if_index=1, name="0/1"),
                    Interface(device_id=sw.id, if_index=2, name="0/2", hidden=True),
                    Interface(device_id=nas.id, if_index=1, name="eth0"),
                ]
            )
            return gw.id, sw.id, nas.id, ap.id

    gw_id, sw_id, nas_id, ap_id = run(seed)
    hub = LiveHub()
    assert run(lambda: hub._load_targets(frozenset())) == []
    targets = run(lambda: hub._load_targets(frozenset({gw_id, nas_id, ap_id})))
    # Tylko oglądane urządzenia, bez ukrytych portów i bez serwera z agentem (nie ma SNMP); urządzenie bez portów też (CPU, RAM)
    assert [(t.device.id, t.driver, [(p.if_index, p.speed_mbps) for p in t.ports]) for t in targets] == [
        (gw_id, "unifi", [(1, None), (5, 1000)]),
        (ap_id, "generic", []),  # nieznany driver – ogólny
    ]
