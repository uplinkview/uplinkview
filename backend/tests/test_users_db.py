"""Role kont i dziennik audytu na prawdziwej bazie (od 0.61.0).

Uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy).
"""

from __future__ import annotations

import asyncio
import os

import pytest

if os.environ.get("NETPULSE_TEST_DB") != "1":
    pytest.skip("brak testowej bazy (NETPULSE_TEST_DB=1)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from netpulse.api import app  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import Alert, AuditEntry, Device, User  # noqa: E402

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}
PASSWORD = "haslo-konta-123"


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
        await s.execute(delete(AuditEntry))
        await s.execute(delete(Alert))
        await s.execute(delete(Device))
        await s.execute(delete(User))


@pytest.fixture
def admin():
    login_limiter._failures.clear()
    run(_reset)
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        yield c
    run(_reset)


def login(username: str, password: str = PASSWORD) -> TestClient:
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200
    return c


def add_user(admin: TestClient, username: str, role: str) -> dict:
    res = admin.post("/api/users", json={"username": username, "password": PASSWORD, "role": role})
    assert res.status_code == 201, res.text
    return res.json()


def test_users_crud_and_last_admin_guard(admin):
    me = admin.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["is_admin"] is True

    jan = add_user(admin, "jan", "operator")
    assert jan["role"] == "operator" and jan["is_admin"] is False
    assert admin.post("/api/users", json={"username": "JAN", "password": PASSWORD}).status_code == 409
    assert admin.post("/api/users", json={"username": "ola", "password": "krotkie"}).status_code == 422
    assert admin.post("/api/users", json={"username": "ola", "password": PASSWORD, "role": "root"}).status_code == 422
    assert [u["username"] for u in admin.get("/api/users").json()] == ["admin", "jan"]

    # Ostatni administrator: bez degradacji i usunięcia; własnego konta nie usuwamy
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 409
    assert admin.delete(f"/api/users/{me['id']}").status_code == 409

    jan_client = login("jan")
    assert admin.patch(f"/api/users/{jan['id']}", json={"role": "viewer"}).json()["role"] == "viewer"
    assert jan_client.get("/api/auth/me").status_code == 401  # nowa rola = nowe logowanie

    assert admin.patch(f"/api/users/{jan['id']}", json={"password": "nowe-haslo-456"}).status_code == 200
    login("jan", "nowe-haslo-456")
    assert admin.delete(f"/api/users/{jan['id']}").status_code == 204
    assert admin.delete(f"/api/users/{jan['id']}").status_code == 404


def test_viewer_reads_but_cannot_change(admin):
    add_user(admin, "widz", "viewer")
    viewer = login("widz")
    assert viewer.get("/api/devices").status_code == 200
    assert viewer.get("/api/alert-rules").status_code == 200
    denied = viewer.post("/api/devices?probe=false", json={"name": "SW", "host": "10.7.0.9", "community": "public"})
    assert denied.status_code == 403 and "administratora" in denied.json()["detail"]
    assert viewer.post("/api/alerts/1/ack").status_code == 403  # potwierdzanie alertów: od operatora
    assert viewer.get("/api/users").status_code == 403  # konta i dziennik tylko dla administratora
    assert viewer.get("/api/audit").status_code == 403
    assert viewer.get("/api/backups").status_code == 403
    # Własne ustawienia wolno
    assert viewer.put("/api/preferences/refresh", json={"interval_s": 30, "range_min": 60}).status_code == 200
    res = viewer.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "inne-haslo-789"})
    assert res.status_code == 204


def test_operator_acks_alerts(admin):
    add_user(admin, "op", "operator")
    operator = login("op")

    async def alert():
        from datetime import UTC, datetime

        async with Session() as s, s.begin():
            a = Alert(subject="d1", state="firing", severity="warning", title="Test", started_at=datetime.now(UTC))
            s.add(a)
            await s.flush()
            return a.id

    alert_id = run(alert)
    assert operator.post(f"/api/alerts/{alert_id}/ack").status_code == 200
    assert operator.post("/api/alert-rules", json={"name": "x", "kind": "device_offline"}).status_code == 403


def test_audit_log_records_logins_and_changes(admin):
    bad = TestClient(app).post("/api/auth/login", json={"username": "admin", "password": "zle-haslo-000"})
    assert bad.status_code == 401
    add_user(admin, "widz", "viewer")
    viewer = login("widz")
    viewer.post("/api/devices?probe=false", json={"name": "SW", "host": "10.7.0.9", "community": "tajne-community"})
    created = admin.post("/api/devices?probe=false", json={"name": "SW", "host": "10.7.0.9", "community": "tajne-community"})
    assert created.status_code == 201, created.text

    page = admin.get("/api/audit").json()
    actions = [(e["username"], e["action"], e["status"]) for e in page["items"]]
    assert ("admin", "POST /api/devices", 201) in actions
    assert ("widz", "POST /api/devices", 403) in actions
    assert ("admin", "POST /api/users", 201) in actions
    assert ("widz", "login", None) in actions and ("admin", "setup", None) in actions
    assert ("admin", "login_failed", None) in actions
    assert "tajne-community" not in str(page)  # bez treści żądań
    assert page["total"] == len(page["items"])

    denied = admin.get("/api/audit", params={"kind": "denied"}).json()["items"]
    assert {e["action"] for e in denied} == {"login_failed", "POST /api/devices"}
    assert all(e["action"] in {"login", "login_failed", "setup"} for e in admin.get("/api/audit", params={"kind": "auth"}).json()["items"])
    assert {e["username"] for e in admin.get("/api/audit", params={"q": "widz"}).json()["items"]} == {"widz"}
    assert admin.get("/api/audit", params={"limit": 2}).json()["items"].__len__() == 2



def test_two_factor_login_flow(admin):
    from netpulse import totp

    add_user(admin, "jan", "viewer")
    jan = login("jan")
    assert jan.get("/api/auth/totp").json() == {"enabled": False, "pending": False, "recovery_left": 0}
    assert jan.post("/api/auth/totp/setup", json={"password": "zle-haslo-000"}).status_code == 403
    setup = jan.post("/api/auth/totp/setup", json={"password": PASSWORD}).json()
    secret = setup["secret"]
    assert setup["uri"].startswith("otpauth://totp/UplinkView%3Ajan?") and setup["qr_svg"].startswith("<svg")
    assert jan.get("/api/auth/totp").json()["pending"] is True
    # bez potwierdzenia kodem logowanie dalej działa samym hasłem
    login("jan")

    step = totp.current_step()
    assert jan.post("/api/auth/totp/enable", json={"code": "000000" if totp.code_at(secret, step) != "000000" else "111111"}).status_code == 422
    other = login("jan")  # druga sesja – po włączeniu 2FA ma się wylogować
    res = jan.post("/api/auth/totp/enable", json={"code": totp.code_at(secret, step)})
    assert res.status_code == 200, res.text
    codes = res.json()["recovery_codes"]
    assert len(codes) == 10
    assert jan.get("/api/auth/me").json()["totp_enabled"] is True
    assert other.get("/api/auth/me").status_code == 401

    # logowanie: hasło → prośba o kod (bez blokady), zły kod → 401, kod użyty przy włączaniu nie przechodzi drugi raz
    c = TestClient(app)
    need = c.post("/api/auth/login", json={"username": "jan", "password": PASSWORD})
    assert need.status_code == 401 and need.json()["detail"]["code"] == "totp_required"
    bad = c.post("/api/auth/login", json={"username": "jan", "password": PASSWORD, "code": "999999"})
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "totp_invalid"
    replay = c.post("/api/auth/login", json={"username": "jan", "password": PASSWORD, "code": totp.code_at(secret, step)})
    assert replay.status_code == 401
    ok = c.post("/api/auth/login", json={"username": "jan", "password": PASSWORD, "code": totp.code_at(secret, step + 1)})
    assert ok.status_code == 200, ok.text
    # zły kod nie pomaga przy złym haśle
    assert c.post("/api/auth/login", json={"username": "jan", "password": "zle-haslo-000", "code": "123456"}).json()["detail"] == "Nieprawidłowy login lub hasło"

    # kod zapasowy działa raz
    r1 = TestClient(app).post("/api/auth/login", json={"username": "jan", "password": PASSWORD, "code": codes[0]})
    assert r1.status_code == 200
    assert TestClient(app).post("/api/auth/login", json={"username": "jan", "password": PASSWORD, "code": codes[0]}).status_code == 401
    assert jan.get("/api/auth/totp").json()["recovery_left"] == 9

    # nowe kody zapasowe: stare przestają działać
    fresh = jan.post("/api/auth/totp/recovery", json={"password": PASSWORD, "code": codes[1]}).json()["recovery_codes"]
    assert TestClient(app).post("/api/auth/login", json={"username": "jan", "password": PASSWORD, "code": codes[2]}).status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"username": "jan", "password": PASSWORD, "code": fresh[0]}).status_code == 200

    # administrator widzi 2FA i może je wyłączyć (zgubiony telefon) – konto loguje się od nowa samym hasłem
    users = {u["username"]: u for u in admin.get("/api/users").json()}
    assert users["jan"]["totp_enabled"] is True
    assert admin.patch(f"/api/users/{users['jan']['id']}", json={"reset_totp": True}).json()["totp_enabled"] is False
    assert jan.get("/api/auth/me").status_code == 401
    login("jan")

    # wyłączenie przez właściciela: hasło + kod
    again = login("jan")
    s2 = again.post("/api/auth/totp/setup", json={"password": PASSWORD}).json()["secret"]
    again.post("/api/auth/totp/enable", json={"code": totp.code_at(s2, totp.current_step())})
    assert again.post("/api/auth/totp/disable", json={"password": PASSWORD, "code": "999999"}).status_code == 403
    off = again.post("/api/auth/totp/disable", json={"password": PASSWORD, "code": totp.code_at(s2, totp.current_step() + 1)})
    assert off.status_code == 200 and off.json()["enabled"] is False

    actions = [e["action"] for e in admin.get("/api/audit", params={"q": "jan"}).json()["items"]]
    assert {"totp_enable", "totp_disable", "totp_recovery"} <= set(actions)
    details = [e["detail"] for e in admin.get("/api/audit", params={"kind": "denied"}).json()["items"]]
    assert "zły kod 2FA" in details


def test_totp_secret_is_encrypted(admin):
    from sqlalchemy import text as sql

    from netpulse import crypto

    me = admin.get("/api/auth/me").json()
    crypto.set_key("klucz-testowy-totp")
    try:
        assert admin.post("/api/auth/totp/setup", json={"password": ADMIN["password"]}).status_code == 200
    finally:
        crypto.set_key(None)

    async def stored():
        async with Session() as s:
            return await s.scalar(sql("SELECT totp_secret FROM users WHERE id = :id"), {"id": me["id"]})

    assert run(stored).startswith("enc:v1:")
