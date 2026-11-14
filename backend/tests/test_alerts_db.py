"""Silnik alertów i API na prawdziwej bazie.

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
from sqlalchemy import delete, select, update  # noqa: E402

from netpulse.alerts import AlertEngine  # noqa: E402
from netpulse.api import app  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import (  # noqa: E402
    Alert,
    AlertRule,
    AppSetting,
    Device,
    DeviceMetric,
    Interface,
    InterfaceMetric,
    Metric,
    User,
    WanLink,
    WanLinkMetric,
)

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}
NOW = datetime.now(UTC).replace(microsecond=0)


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
        await s.execute(delete(Alert))
        await s.execute(delete(AlertRule))
        await s.execute(delete(AppSetting).where(AppSetting.key == "alert_defaults"))
        await s.execute(delete(Device))
        await s.execute(delete(User))


async def _clear_metrics():
    async with Session() as s, s.begin():
        await s.execute(delete(DeviceMetric))


@pytest.fixture
def client():
    login_limiter._failures.clear()
    run(_reset)
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        yield c
    run(_reset)


def evaluate(now=NOW, fresh=True):
    async def go():
        if fresh:
            await polled(now)
        await AlertEngine(now_fn=lambda: now).evaluate()

    run(go)


def alerts(client, state="all"):
    return client.get("/api/alerts", params={"state": state}).json()


async def polled(now):
    """Świeży werdykt kolektora dla wszystkich urządzeń – bez niego alerty urządzeń stoją (freshness.py)."""
    async with Session() as s, s.begin():
        await s.execute(update(Device).values(last_polled_at=now))


def add_device(**kw) -> int:
    async def go():
        async with Session() as s, s.begin():
            d = Device(name=kw.pop("name", "SW"), host=kw.pop("host", "10.9.0.1"), community=kw.pop("community", "public"), **kw)
            s.add(d)
            await s.flush()
            return d.id

    return run(go)


def add_rule(**kw) -> int:
    async def go():
        async with Session() as s, s.begin():
            r = AlertRule(**kw)
            s.add(r)
            await s.flush()
            return r.id

    return run(go)


def cpu_samples(dev_id: int, values: list[float], step=30):
    async def go():
        async with Session() as s, s.begin():
            n = len(values)
            s.add_all(
                DeviceMetric(time=NOW - timedelta(seconds=step * (n - 1 - i)), device_id=dev_id, reachable=True, cpu_percent=v)
                for i, v in enumerate(values)
            )

    run(go)


def test_offline_rule_fires_after_duration_and_resolves(client):
    dev = add_device(status="down", last_ok_at=NOW - timedelta(seconds=300), last_error="timeout")
    add_rule(name="offline", kind="device_offline", duration_s=120, severity="critical")
    evaluate()
    (a,) = alerts(client)
    assert a["state"] == "firing" and a["severity"] == "critical" and a["device_id"] == dev
    assert "nie odpowiada" in a["title"] and a["message"] == "timeout"

    evaluate()  # druga ocena nie dubluje alertu
    assert len(alerts(client)) == 1

    async def back_online():
        async with Session() as s, s.begin():
            (await s.get(Device, dev)).status = "up"

    run(back_online)
    evaluate(NOW + timedelta(seconds=30))
    (a,) = alerts(client)
    assert a["state"] == "resolved" and a["resolved_at"]


def test_stale_device_neither_fires_nor_resolves(client):
    """Kolektor stoi: zapisany werdykt jest nieaktualny – brak danych to nie awaria ani powrót do normy."""
    stale_at = NOW - timedelta(minutes=10)
    add_device(status="down", last_ok_at=NOW - timedelta(minutes=15), last_polled_at=stale_at)
    add_rule(name="offline", kind="device_offline", duration_s=0)
    evaluate(fresh=False)
    assert alerts(client) == []

    evaluate()  # świeży werdykt „down” – alert się otwiera
    (a,) = alerts(client)
    assert a["state"] == "firing"

    later = NOW + timedelta(minutes=10)  # od NOW żadnego odczytu: alert trwa bez zmian
    events = evaluate_stale(later)
    assert events == [] and [x["state"] for x in alerts(client)] == ["firing"]

    async def back_online():
        async with Session() as s, s.begin():
            (await s.get(Device, a["device_id"])).status = "up"

    run(back_online)
    evaluate(later)  # świeży odczyt „up” – teraz koniec alertu
    assert [x["state"] for x in alerts(client)] == ["resolved"]


def evaluate_stale(now):
    async def go():
        return await AlertEngine(now_fn=lambda: now).evaluate()

    return run(go)


def test_offline_rule_waits_for_duration(client):
    add_device(status="down", last_ok_at=NOW - timedelta(seconds=30))
    add_rule(name="offline", kind="device_offline", duration_s=120)
    evaluate()
    assert alerts(client) == []


def test_metric_rule_needs_sustained_breach(client):
    dev = add_device(status="up")
    add_rule(name="CPU", kind="metric", metric="cpu_percent", op=">", threshold=90, duration_s=300, severity="warning")
    cpu_samples(dev, [95] * 6 + [50] + [95] * 4)  # 5 min danych, ale z dołkiem
    evaluate()
    assert alerts(client) == []

    run(_clear_metrics)
    cpu_samples(dev, [95] * 15)
    evaluate()
    (a,) = alerts(client)
    assert "CPU 95,0%" in a["title"] and a["peak"] == 95 and "Warunek" in a["message"]


def test_port_down_only_after_transition(client):
    dev = add_device(status="up")
    ids = {}

    async def seed():
        async with Session() as s, s.begin():
            used = Interface(device_id=dev, if_index=1, name="0/1", label="Port 1", alias="NAS", oper_status="down")
            empty = Interface(device_id=dev, if_index=2, name="0/2", label="Port 2", oper_status="down")
            s.add_all([used, empty])
            await s.flush()
            ids["used"] = used.id
            s.add_all(
                [
                    InterfaceMetric(time=NOW - timedelta(seconds=30), interface_id=used.id, oper_up=True),
                    InterfaceMetric(time=NOW, interface_id=used.id, oper_up=False),
                    InterfaceMetric(time=NOW - timedelta(seconds=30), interface_id=empty.id, oper_up=False),
                    InterfaceMetric(time=NOW, interface_id=empty.id, oper_up=False),
                ]
            )

    run(seed)
    add_rule(name="port", kind="port_down")
    evaluate()
    (a,) = alerts(client)  # tylko port, który działał; pusty port nie alarmuje
    assert "NAS" in a["title"] and a["state"] == "firing"

    evaluate(NOW + timedelta(seconds=10))  # port nadal wyłączony: alert trwa, bez duplikatu
    assert [x["state"] for x in alerts(client)] == ["firing"]

    async def port_back():
        async with Session() as s, s.begin():
            m = await s.scalar(
                select(InterfaceMetric).where(InterfaceMetric.interface_id == ids["used"], InterfaceMetric.time == NOW)
            )
            m.oper_up = True

    run(port_back)
    evaluate(NOW + timedelta(seconds=30))
    assert [x["state"] for x in alerts(client)] == ["resolved"]


def test_port_down_survives_switch_restart(client):
    """Switch chwilę nie odpowiada (restart): alert portu trwa i zamyka się dopiero, gdy port wstanie."""
    dev = add_device(status="up")
    ids = {}

    async def seed():
        async with Session() as s, s.begin():
            port = Interface(device_id=dev, if_index=6, name="0/6", label="Port 6", oper_status="down")
            s.add(port)
            await s.flush()
            ids["port"] = port.id
            s.add_all(
                [
                    InterfaceMetric(time=NOW - timedelta(seconds=30), interface_id=port.id, oper_up=True),
                    InterfaceMetric(time=NOW, interface_id=port.id, oper_up=False),
                ]
            )

    async def set_status(status):
        async with Session() as s, s.begin():
            (await s.get(Device, dev)).status = status

    def reading(at, oper_up):
        async def go():
            async with Session() as s, s.begin():
                s.add(InterfaceMetric(time=at, interface_id=ids["port"], oper_up=oper_up))

        run(go)

    run(seed)
    add_rule(name="port", kind="port_down")
    evaluate()
    assert [x["state"] for x in alerts(client)] == ["firing"]

    run(lambda: set_status("down"))  # restart switcha: brak odczytów portów
    t = NOW + timedelta(minutes=10)
    evaluate(t)
    assert [x["state"] for x in alerts(client)] == ["firing"]

    run(lambda: set_status("up"))  # switch wrócił, port dalej wyłączony
    t += timedelta(minutes=2)
    reading(t - timedelta(seconds=30), False)
    reading(t, False)
    evaluate(t)
    assert [x["state"] for x in alerts(client)] == ["firing"]

    t += timedelta(seconds=30)
    reading(t, True)
    evaluate(t)
    assert [x["state"] for x in alerts(client)] == ["resolved"]


def test_port_down_during_switch_restart(client):
    """Port działał przed przerwą w odczytach (restart switcha), a po niej jest down: alert, ale dopiero po dwóch
    odczytach – port, który po starcie switcha chwilę negocjuje link, i port pusty od dawna nie alarmują."""
    dev = add_device(status="up")
    before = NOW - timedelta(minutes=10)  # ostatni odczyt przed restartem
    # port: (stan przed przerwą, odczyty po przerwie od najstarszego)
    plan = {
        "Proxmox": (True, [False, False]),
        "NAS": (True, [False, True]),
        "pusty": (False, [False, False]),
        "TV": (True, [False]),
    }

    async def seed():
        async with Session() as s, s.begin():
            for n, (label, (was_up, after)) in enumerate(plan.items(), start=1):
                port = Interface(device_id=dev, if_index=n, name=f"0/{n}", label=label, oper_status="down")
                s.add(port)
                await s.flush()
                s.add(InterfaceMetric(time=before - timedelta(seconds=30), interface_id=port.id, oper_up=was_up))
                s.add(InterfaceMetric(time=before, interface_id=port.id, oper_up=was_up))
                for k, oper_up in enumerate(reversed(after)):
                    s.add(InterfaceMetric(time=NOW - timedelta(seconds=30 * k), interface_id=port.id, oper_up=oper_up))

    run(seed)
    add_rule(name="port", kind="port_down")
    evaluate()
    assert [(a["title"], a["state"]) for a in alerts(client)] == [("Port Proxmox (SW) jest wyłączony", "firing")]


def test_default_community_alert_until_changed(client):
    """Fabryczne community SNMP (0.31.2): alert na urządzenie v1/v2c z „public”/„private”, znika po zmianie."""
    weak = add_device(name="UCG", host="10.9.0.1", status="up")  # community domyślnie „public”
    add_device(name="AP", host="10.9.0.2", status="up", community="Private")
    add_device(name="Switch", host="10.9.0.3", status="up", community="domowe-123")
    add_device(name="Router v3", host="10.9.0.4", status="up", snmp_version="3", community="public")
    add_device(name="Wyłączony", host="10.9.0.5", status="up", enabled=False)
    add_rule(name="Community", kind="default_community", duration_s=0, severity="warning")
    evaluate()
    firing = sorted(a["title"] for a in alerts(client, "firing"))
    assert firing == ["AP: fabryczne community SNMP", "UCG: fabryczne community SNMP"]
    assert "Ustawienia → Urządzenia" in alerts(client, "firing")[0]["message"]

    assert client.patch(f"/api/devices/{weak}", json={"community": "nowe-tajne-1"}).status_code == 200
    evaluate(NOW + timedelta(seconds=30))
    assert [a["title"] for a in alerts(client, "firing")] == ["AP: fabryczne community SNMP"]


def test_deleted_rule_ends_its_alerts_but_keeps_history(client):
    add_device(status="down", last_ok_at=NOW - timedelta(seconds=600))
    rule = add_rule(name="offline", kind="device_offline", duration_s=0)
    evaluate()
    assert client.delete(f"/api/alert-rules/{rule}").status_code == 204
    evaluate(NOW + timedelta(seconds=30))
    (a,) = alerts(client)
    assert a["state"] == "resolved" and a["rule_id"] is None


def evaluate_events(now):
    async def go():
        await polled(now)  # kolektor odpytał urządzenia tuż przed oceną (kolejność jak w pętli kolektora)
        return await AlertEngine(now_fn=lambda: now).evaluate()

    return run(go)


def test_device_restart_is_a_short_alert_without_end_notice(client):
    dev = add_device(name="USW", status="up")
    add_rule(name="Restart", kind="device_restart", duration_s=0, severity="info")

    async def samples():
        async with Session() as s, s.begin():
            # Czas pracy rośnie, 2 min temu spada do 60 s – restart
            for m, uptime in ((6, 9000), (4, 9120), (2, 60), (0, 180)):
                s.add(DeviceMetric(time=NOW - timedelta(minutes=m), device_id=dev, reachable=True, uptime_s=uptime))

    run(samples)
    events = evaluate_events(NOW)
    assert [(e.kind, e.title) for e in events] == [("firing", "USW: restart urządzenia")]
    (a,) = alerts(client)
    assert a["state"] == "firing" and a["severity"] == "info" and a["message"] == "Czas pracy po restarcie: 1 min"
    # Kolejny cykl: ten sam restart, bez nowego alertu
    assert evaluate_events(NOW + timedelta(seconds=30)) == []
    # Po 10 minutach alert się kończy – bez powiadomienia o końcu
    assert evaluate_events(NOW + timedelta(minutes=11)) == []
    (a,) = alerts(client)
    assert a["state"] == "resolved"


def test_wan_switch_alert(client):
    gw = add_device(name="UCG", status="up")
    add_rule(name="WAN", kind="wan_switch", duration_s=0, severity="warning")

    async def seed():
        async with Session() as s, s.begin():
            ports = [Interface(device_id=gw, if_index=i, name=f"eth{i}") for i in (4, 3)]
            s.add_all(ports)
            await s.flush()
            links = [WanLink(device_id=gw, interface_id=p.id, position=n, name=n == 1 and "Światłowód" or "LTE") for n, p in enumerate(ports, 1)]
            s.add_all(links)
            await s.flush()
            # WAN 1 niesie ruch, 2 min temu pada – ruch przejmuje LTE
            for m in (5, 4, 3, 2, 1, 0):
                t = NOW - timedelta(minutes=m)
                s.add(WanLinkMetric(time=t, wan_link_id=links[0].id, up=m > 2, active=m > 2))
                s.add(WanLinkMetric(time=t, wan_link_id=links[1].id, up=True, active=m <= 2))

    run(seed)
    events = evaluate_events(NOW)
    assert [(e.kind, e.title, e.device_name) for e in events] == [("firing", "Przełączenie WAN: Światłowód → LTE", "UCG")]
    assert evaluate_events(NOW + timedelta(seconds=30)) == []
    assert evaluate_events(NOW + timedelta(minutes=13)) == []
    assert [a["state"] for a in alerts(client)] == ["resolved"]
    # Reguła przełączenia dotyczy wszystkich łączy – bez urządzenia
    bad = {"name": "x", "kind": "wan_switch", "device_id": gw}
    assert client.post("/api/alert-rules", json=bad).status_code == 422


def test_vpn_connect_alert(client):
    """Nowe połączenie VPN (0.57.0): `vpn_connected` 1 po 0 – alert trwa 10 min, kolejne cykle go nie powtarzają."""
    gw = add_device(name="UCG", status="up")
    add_rule(name="VPN", kind="vpn_connect", duration_s=0, severity="info")

    async def seed():
        async with Session() as s, s.begin():
            for m, value in ((3, 0.0), (2, 0.0), (1, 1.0), (0, 1.0)):
                s.add(Metric(time=NOW - timedelta(minutes=m), device_id=gw, name="vpn_connected", key="iPhone", value=value))

    run(seed)
    events = evaluate_events(NOW)
    assert [(e.kind, e.title, e.device_name) for e in events] == [("firing", "VPN: połączenie – iPhone", "UCG")]
    assert evaluate_events(NOW + timedelta(seconds=30)) == []
    assert evaluate_events(NOW + timedelta(minutes=12)) == []
    assert [a["state"] for a in alerts(client)] == ["resolved"]


def test_default_rules_created_once(client):
    async def go():
        await AlertEngine().ensure_default_rules()
        await AlertEngine().ensure_default_rules()

    run(go)
    kinds = [r["kind"] for r in client.get("/api/alert-rules").json()]
    assert kinds == [
        "device_offline", "port_down", "container_stopped", "service_failed", "smart_failed", "metric",
        "guest_stopped", "backup_failed", "metric", "check_down", "metric", "default_community",
        "wan_switch", "device_restart", "vpn_connect", "gateway_down", "opnsense_service_failed", "metric",
    ]  # fmt: skip


def test_default_rules_for_existing_install_and_deleted_rules_stay_deleted(client):
    """Instalacja z 0.11 (ma reguły, brak znacznika) dostaje tylko nowsze zestawy (agent, Proxmox), raz."""
    add_rule(name="moja", kind="device_offline", duration_s=60)

    async def go():
        await AlertEngine().ensure_default_rules()

    run(go)
    rules = client.get("/api/alert-rules").json()
    assert [r["name"] for r in rules][:2] == ["moja", "Kontener zatrzymany"] and len(rules) == 17
    temp = next(r for r in rules if r["metric"] == "temp_c")
    assert temp["threshold"] == 85 and temp["op"] == ">"
    assert client.delete(f"/api/alert-rules/{rules[1]['id']}").status_code == 204
    run(go)
    assert len(client.get("/api/alert-rules").json()) == 13


def test_rules_api_validation(client):
    ok = {"name": "CPU", "kind": "metric", "metric": "cpu_percent", "op": ">", "threshold": 90, "duration_s": 600}
    created = client.post("/api/alert-rules", json=ok)
    assert created.status_code == 201 and created.json()["severity"] == "warning"
    assert client.post("/api/alert-rules", json={**ok, "metric": "nie_ma"}).status_code == 422
    assert client.post("/api/alert-rules", json={**ok, "threshold": None}).status_code == 422
    assert client.post("/api/alert-rules", json={**ok, "metric": "wan_in_bps", "device_id": 1}).status_code == 422
    assert client.post("/api/alert-rules", json={**ok, "device_id": 99999}).status_code == 422
    assert client.post("/api/alert-rules", json={**ok, "severity": "straszne"}).status_code == 422
    # Pola metryki są ignorowane dla reguł innego rodzaju
    off = client.post(
        "/api/alert-rules", json={"name": "off", "kind": "device_offline", "metric": "cpu_percent", "op": ">", "threshold": 1}
    )
    assert off.json()["metric"] is None and off.json()["threshold"] is None

    rid = created.json()["id"]
    upd = client.put(f"/api/alert-rules/{rid}", json={**ok, "threshold": 80, "enabled": False})
    assert upd.status_code == 200 and upd.json()["threshold"] == 80 and not upd.json()["enabled"]
    assert client.put("/api/alert-rules/99999", json=ok).status_code == 404
    assert any(m["metric"] == "wan_in_bps" and not m["per_device"] for m in client.get("/api/alert-rules/metrics").json())


def test_ack_and_summary(client):
    add_device(status="down", last_ok_at=NOW - timedelta(seconds=600))
    add_rule(name="offline", kind="device_offline", severity="critical")
    evaluate()
    assert client.get("/api/alerts/summary").json() == {
        "firing": 1,
        "unacked": 1,
        "unacked_critical": 1,
        "critical": 1,
        "warning": 0,
        "info": 0,
    }
    aid = alerts(client)[0]["id"]
    acked = client.post(f"/api/alerts/{aid}/ack")
    assert acked.status_code == 200 and acked.json()["acked_by"] == "admin"
    summary = client.get("/api/alerts/summary").json()
    assert summary["unacked"] == 0 and summary["unacked_critical"] == 0 and summary["firing"] == 1
    assert client.post("/api/alerts/99999/ack").status_code == 404
    assert client.get("/api/alerts", params={"state": "resolved"}).json() == []
    assert client.get("/api/alerts", params={"severity": "info"}).json() == []


def test_alert_endpoints_require_login():
    with TestClient(app) as c:
        for path in ("/api/alerts", "/api/alerts/summary", "/api/alert-rules"):
            assert c.get(path).status_code == 401
