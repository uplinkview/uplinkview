"""Potwierdzenie danych (od 0.64.0): rejestr źródeł i plakietka urządzenia."""

from __future__ import annotations

from fastapi.testclient import TestClient

from netpulse import verification
from netpulse.api import app
from netpulse.api.security import require_user
from netpulse.db.models import NON_SNMP_DRIVERS, Device, User
from netpulse.drivers import DRIVERS


def test_every_driver_has_a_described_source():
    # Nowy driver = decyzja, czy jego dane są potwierdzone na prawdziwym sprzęcie (wpis w verification.py)
    for driver in [*DRIVERS, *NON_SNMP_DRIVERS]:
        assert verification.for_driver(driver), f"brak wpisu w verification.SOURCES dla drivera {driver}"


def test_sources_are_consistent():
    ids = [s.id for s in verification.SOURCES]
    assert len(ids) == len(set(ids))
    known = {*DRIVERS, *NON_SNMP_DRIVERS}
    for s in verification.SOURCES:
        assert s.level in ("verified", "partial", "test") and s.label and s.note
        assert set(s.drivers) <= known, s.id


def test_device_levels():
    assert verification.device_level("unifi") == "verified"
    assert verification.device_level("generic") == "verified"
    assert verification.device_level("mikrotik") == "partial"  # system tak, czujniki/PoE/SFP nie
    assert verification.device_level("omada") == "partial"  # IF-MIB tak, MIB TP-Link tylko na zrzutach
    assert verification.device_level("nowy-driver") == "verified"
    assert Device(name="x", host="h", driver="omada").verification == "partial"


def test_api_lists_sources():
    app.dependency_overrides[require_user] = lambda: User(id=1, username="jan", password_hash="x", is_admin=False, role="viewer")
    try:
        res = TestClient(app).get("/api/system/verification")
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200
    by_id = {s["id"]: s for s in res.json()}
    assert by_id["dual_wan"]["level"] == "verified" and by_id["unifi_snmp"]["level"] == "verified"
    assert any(s["level"] == "test" for s in by_id.values())  # są źródła tylko na danych testowych
