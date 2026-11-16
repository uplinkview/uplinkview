"""Kolektor kontrolerów UniFi i API klientów/PoE na prawdziwej bazie.

Uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

import pytest
from conftest import FIXTURES

if os.environ.get("NETPULSE_TEST_DB") != "1":
    pytest.skip("brak testowej bazy (NETPULSE_TEST_DB=1)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from netpulse.api import app  # noqa: E402
from netpulse.api.security import login_limiter  # noqa: E402
from netpulse.db import Session, engine, init_db  # noqa: E402
from netpulse.db.models import (  # noqa: E402
    AppSetting,
    Controller,
    Device,
    Interface,
    InterfaceMetric,
    Metric,
    NetworkClient,
    PoeBudgetMetric,
    PoePortMetric,
    UnifiApiDevice,
    User,
)
from netpulse.unifi import (  # noqa: E402
    UnifiError,
    parse_clients,
    parse_devices,
    parse_official_device,
    parse_official_devices,
    parse_vpn_servers,
    parse_vpn_sessions,
    parse_vpn_users,
)
from netpulse.unifi_collector import UnifiCollector  # noqa: E402

ADMIN = {"username": "admin", "password": "haslo-testowe-1"}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


VPN = fixture("unifi_vpn.json")


class FakeApi:
    def __init__(self, fail: bool = False, clients: dict | None = None, no_official: bool = False, vpn_sessions: bool = True) -> None:
        self.fail = fail
        self.vpn_sessions = vpn_sessions
        self._clients = clients or fixture("unifi_clients.json")
        self.no_official = no_official
        self.detail_calls: list[str] = []

    async def app_version(self):
        if self.fail:
            raise UnifiError("Kontroler odrzucił klucz API")
        return "10.6.109"

    async def devices(self):
        return parse_devices(fixture("unifi_devices.json"))

    async def clients(self):
        return parse_clients(self._clients)

    async def vpn(self):
        sessions = parse_vpn_sessions(VPN["remoteuservpn"]) if self.vpn_sessions else []
        return parse_vpn_servers(VPN["networkconf"]), parse_vpn_users(VPN["wireguard_users"]), sessions

    async def official_devices(self):
        if self.no_official:
            raise UnifiError("Kontroler nie ma oficjalnego API")
        return parse_official_devices(fixture("unifi_official.json")["devices"])

    async def official_details(self, device):
        data = fixture("unifi_official.json")
        self.detail_calls.append(device.mac)
        return parse_official_device(data["details"][device.id], data["statistics"][device.id])

    async def close(self):
        pass


def run(coro_fn):
    async def wrapper():
        try:
            return await coro_fn()
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


def seed() -> None:
    """Switch i AP pod adresami z fixtures (kolektor łączy urządzenia z kontrolerem po IP)."""
    devices = {d["type"]: d["ip"] for d in fixture("unifi_devices.json")["data"]}
    # Brama podaje w polu `ip` inny adres (WAN) niż ten, pod którym widzi ją sieć LAN (SNMP, LLDP u sąsiadów)
    (lan_ip,) = {ip for d in fixture("unifi_devices.json")["data"] for x in d.get("lldp_table", [])
                 if x["chassis_id"] == next(g["mac"] for g in fixture("unifi_devices.json")["data"] if g["type"] == "udm")
                 for ip in x.get("mgmt_ips") or [] if "." in ip}
    assert lan_ip != devices["udm"]
    devices["udm"] = lan_ip

    async def go():
        await init_db()
        async with Session() as s, s.begin():
            await s.execute(delete(Controller))
            await s.execute(delete(AppSetting).where(AppSetting.key.startswith("vpn:")))
            await s.execute(delete(Device))
            await s.execute(delete(User))
            switch = Device(name="USW", host=devices["usw"], community="public")
            s.add_all([switch, Device(name="U6+", host=devices["uap"], community="public"), Device(name="UCG", host=devices["udm"], community="public")])
            await s.flush()
            s.add(Interface(device_id=switch.id, if_index=1, name="0/1", label="Port 1", alias="AP U6+", speed_mbps=1000))
            s.add(Controller(name="UniFi", host="10.0.0.254", api_key="klucz-testowy-123"))

    run(go)


@pytest.fixture
def client():
    login_limiter._failures.clear()
    seed()
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json=ADMIN).status_code == 201
        yield c
    run(_clean)


async def _clean():
    async with Session() as s, s.begin():
        await s.execute(delete(Controller))
        await s.execute(delete(AppSetting).where(AppSetting.key.startswith("vpn:")))
        await s.execute(delete(Device))
        await s.execute(delete(User))


def poll(api: FakeApi) -> None:
    async def go():
        collector = UnifiCollector(api_factory=lambda _t: api)
        (target,) = await collector.load_targets()
        return await collector.poll_one(target)

    return run(go)


def test_poll_saves_poe_clients_and_status(client):
    assert poll(FakeApi()) is True

    async def check():
        async with Session() as s:
            ctrl = await s.scalar(select(Controller))
            assert ctrl.status == "up" and ctrl.app_version == "10.6.109" and ctrl.last_error is None
            assert await s.scalar(select(func.count()).select_from(PoePortMetric)) == 4
            budget = await s.scalar(select(PoeBudgetMetric))
            assert (budget.used_w, budget.max_w) == (3.89, 52.0)
            clients = (await s.scalars(select(NetworkClient))).all()
            assert len(clients) == 9
            tv = next(c for c in clients if c.is_wired and c.uplink_port == 7)
            assert tv.uplink_device_id is not None  # port 7 switcha przypisany do urządzenia UplinkView
            wifi = [c for c in clients if not c.is_wired]
            assert all(c.uplink_device_id is not None and c.signal_dbm for c in wifi)

    run(check)


def test_poll_replaces_client_snapshot(client):
    poll(FakeApi())
    fewer = fixture("unifi_clients.json")
    fewer["data"] = fewer["data"][:2]
    poll(FakeApi(clients=fewer))

    async def count():
        async with Session() as s:
            return await s.scalar(select(func.count()).select_from(NetworkClient))

    assert run(count) == 2


def test_poll_failure_marks_controller_down(client):
    assert poll(FakeApi(fail=True)) is False

    async def check():
        async with Session() as s:
            ctrl = await s.scalar(select(Controller))
            assert ctrl.status == "down" and "klucz" in ctrl.last_error

    run(check)


def test_clients_and_poe_endpoints(client):
    poll(FakeApi())
    wifi = client.get("/api/clients", params={"kind": "wifi"}).json()
    assert len(wifi) == 5 and all(not c["is_wired"] and c["essid"] for c in wifi)
    assert len(client.get("/api/clients", params={"kind": "wired"}).json()) == 4
    assert client.get("/api/clients", params={"kind": "inne"}).status_code == 422

    switch = next(d for d in client.get("/api/devices").json() if d["name"] == "USW")
    poe = client.get(f"/api/devices/{switch['id']}/poe").json()
    assert poe["budget"] == {"used_w": 3.89, "max_w": 52.0}
    assert [p["port_idx"] for p in poe["ports"]] == [1, 2, 3, 4]
    assert poe["ports"][0]["label"] == "AP U6+" and poe["ports"][0]["power_w"] == 3.89 and poe["ports"][0]["delivering"]
    assert client.get("/api/devices/99999/poe").status_code == 404


def test_vpn_status_and_metrics(client):
    """VPN (0.57.0): kto jest połączony, metryki na bramie, po rozłączeniu – ostatnio widziany i ostatni transfer."""
    poll(FakeApi())
    vpn = client.get("/api/vpn").json()
    gw = next(d["id"] for d in client.get("/api/devices").json() if d["name"] == "UCG")
    assert vpn["device_id"] == gw and vpn["stale"] is False
    assert vpn["servers"] == [{"id": "net-wg", "name": "WG-Home", "type": "WireGuard", "enabled": True, "port": 51820, "subnet": "192.168.3.1/24"}]
    iphone, laptop = vpn["users"]
    assert (iphone["name"], iphone["connected"], iphone["server"], iphone["remote_ip"]) == ("iPhone", True, "WG-Home", "203.0.113.7")
    assert iphone["down_bytes"] == 76148892 and iphone["down_bps"] == 147888 and iphone["since"]
    assert (laptop["name"], laptop["connected"], laptop["last_seen"]) == ("Laptop", False, None)

    async def rows():
        async with Session() as s:
            return {(m.name, m.key): m.value for m in (await s.scalars(select(Metric).where(Metric.device_id == gw))).all()}

    assert run(rows) == {("vpn_connected", "iPhone"): 1.0, ("vpn_connected", "Laptop"): 0.0, ("vpn_down_bps", "iPhone"): 147888, ("vpn_up_bps", "iPhone"): 96637}
    chart = client.get(f"/api/devices/{gw}/agent-metrics", params={"source": "vpn", "key": "iPhone"}).json()
    assert chart[-1]["values"]["down_bps"] == 147888
    assert set(client.get(f"/api/devices/{gw}/agent-keys").json()["vpn"]) == {"Laptop", "iPhone"}

    poll(FakeApi(vpn_sessions=False))
    iphone = next(u for u in client.get("/api/vpn").json()["users"] if u["name"] == "iPhone")
    assert iphone["connected"] is False and iphone["last_seen"] and iphone["down_bytes"] == 76148892 and iphone["down_bps"] is None


def test_vpn_rate_from_interface_samples(client):
    """Klient jedyny na swoim interfejsie (0.86.1): `vpn_down_bps`/`vpn_up_bps` z próbek SNMP `wgsrv1` z ich czasem."""
    sample_at = datetime.now(UTC).replace(microsecond=0)

    async def add_samples():
        async with Session() as s, s.begin():
            gw = await s.scalar(select(Device).where(Device.name == "UCG"))
            wg = Interface(device_id=gw.id, if_index=90497, name="wgsrv1", label="WG-Home", role="vpn", oper_status="up")
            s.add(wg)
            await s.flush()
            s.add(InterfaceMetric(time=sample_at, interface_id=wg.id, in_bps=48e6, out_bps=343e6))
            return gw.id

    gw = run(add_samples)
    poll(FakeApi())

    async def rows():
        async with Session() as s:
            return {(m.name, m.time): m.value for m in (await s.scalars(select(Metric).where(Metric.device_id == gw, Metric.key == "iPhone"))).all()}

    got = run(rows)
    assert got[("vpn_down_bps", sample_at)] == 343e6 and got[("vpn_up_bps", sample_at)] == 48e6
    assert {name for name, _ in got} == {"vpn_connected", "vpn_down_bps", "vpn_up_bps"} and len(got) == 3  # bez prędkości z kontrolera
    iphone = next(u for u in client.get("/api/vpn").json()["users"] if u["name"] == "iPhone")
    assert iphone["down_bps"] == 343e6 and iphone["up_bps"] == 48e6
    poll(FakeApi())  # ta sama próbka nie trafia drugi raz (byłby konflikt klucza)
    assert len(run(rows)) == 4


def test_controller_crud_hides_api_key(client):
    listed = client.get("/api/controllers").json()
    assert len(listed) == 1 and "api_key" not in listed[0]
    cid = listed[0]["id"]

    r = client.patch(f"/api/controllers/{cid}", json={"name": "Dom", "enabled": False})
    assert r.status_code == 200 and r.json()["name"] == "Dom" and not r.json()["enabled"]
    assert client.patch(f"/api/controllers/{cid}", json={"name": None}).status_code == 422
    assert client.post("/api/controllers", json={"name": "x", "host": "10.0.0.254", "api_key": "abcdefghij"}, params={"probe": "false"}).status_code == 409

    created = client.post("/api/controllers", json={"name": "Drugi", "host": "10.0.0.253", "api_key": "abcdefghij"}, params={"probe": "false"})
    assert created.status_code == 201 and "api_key" not in created.json()
    assert client.delete(f"/api/controllers/{created.json()['id']}").status_code == 204
    assert client.delete("/api/controllers/99999").status_code == 404


def test_controller_endpoints_require_login():
    with TestClient(app) as c:
        assert c.get("/api/controllers").status_code == 401
        assert c.get("/api/clients").status_code == 401
        assert c.get("/api/devices/1/poe").status_code == 401


def test_topology_joins_both_ends_of_each_cable(client):
    assert client.get("/api/topology").json() == {"nodes": [], "edges": []}  # bez odczytu kontrolera mapa jest pusta
    poll(FakeApi())
    topo = client.get("/api/topology").json()
    by_name = {n["name"]: n for n in topo["nodes"] if n["kind"] == "device"}
    assert set(by_name) == {"USW", "U6+", "UCG"}
    externals = [n for n in topo["nodes"] if n["kind"] == "external"]
    assert len(externals) == 1  # modem na porcie WAN bramy, którego kontroler nie zna

    def edge(x, y):
        a, b = by_name[x]["id"], by_name[y]["id"]
        (e,) = [e for e in topo["edges"] if {e["a"], e["b"]} == {a, b}]
        return {e["a"]: e["a_port"], e["b"]: e["b_port"]}[a], {e["a"]: e["a_port"], e["b"]: e["b_port"]}[b]

    assert edge("USW", "U6+") == (1, 1)  # AP na porcie 1 switcha, uplink AP to jego eth0
    assert edge("USW", "UCG") == (8, 1)  # brama na porcie 8 switcha
    assert len(topo["edges"]) == 3

    # Obciążenie kabla AP: port 1 switcha („0/1”, 1 Gb/s) i jego ostatni ruch – większy z kierunków
    async def traffic():
        async with Session() as s, s.begin():
            port = await s.scalar(select(Interface).where(Interface.name == "0/1"))
            s.add(InterfaceMetric(time=datetime.now(UTC), interface_id=port.id, in_bps=5e7, out_bps=2e8))
            return port.id

    port_id = run(traffic)
    (ap,) = [e for e in client.get("/api/topology").json()["edges"] if {e["a"], e["b"]} == {by_name["USW"]["id"], by_name["U6+"]["id"]}]
    assert (ap["interface_id"], ap["device_id"], ap["speed_mbps"]) == (port_id, by_name["USW"]["device_id"], 1000)
    assert ap["traffic_bps"] == 2e8 and ap["utilization"] == pytest.approx(0.2)
    (gw,) = [e for e in client.get("/api/topology").json()["edges"] if {e["a"], e["b"]} == {by_name["USW"]["id"], by_name["UCG"]["id"]}]
    assert gw["interface_id"] is None and gw["utilization"] is None  # portu 8 switcha nie ma w SNMP tego testu


# --- Urządzenia bez SNMP z oficjalnego API (od 0.52.0) ---


async def _drop_snmp_switch() -> None:
    async with Session() as s, s.begin():
        await s.execute(delete(Device).where(Device.name == "USW"))


def test_known_snmp_devices_are_not_duplicated(client):
    api = FakeApi()
    assert poll(api) is True
    assert api.detail_calls == []  # wszystkie trzy urządzenia UplinkView zna z SNMP

    async def check():
        async with Session() as s:
            assert await s.scalar(select(func.count()).select_from(Device).where(Device.driver == "unifi_api")) == 0

    run(check)


def test_device_without_snmp_is_created_from_official_api(client):
    run(_drop_snmp_switch)
    assert poll(FakeApi()) is True
    poll(FakeApi())  # drugi odczyt: ten sam wpis, bez duplikatu

    async def check():
        async with Session() as s:
            (dev,) = (await s.scalars(select(Device).where(Device.driver == "unifi_api"))).all()
            assert (dev.kind, dev.vendor, dev.model, dev.status) == ("switch", "Ubiquiti", "USW-Lite-8-PoE", "up")
            names = (await s.scalars(select(Interface.name).where(Interface.device_id == dev.id).order_by(Interface.if_index))).all()
            assert names == [f"0/{n}" for n in range(1, 9)]
            assert await s.scalar(select(func.count()).select_from(UnifiApiDevice)) == 1
            return dev.id

    dev_id = run(check)
    card = client.get(f"/api/devices/{dev_id}").json()
    assert card["driver"] == "unifi_api"
    assert client.post(f"/api/devices/{dev_id}/probe").status_code == 409  # bez SNMP – test nie ma sensu

    # Usunięte w panelu – kolektor nie zakłada go ponownie
    assert client.delete(f"/api/devices/{dev_id}").status_code == 204
    api = FakeApi()
    poll(api)

    async def gone():
        async with Session() as s:
            assert await s.scalar(select(func.count()).select_from(Device).where(Device.driver == "unifi_api")) == 0
            row = await s.scalar(select(UnifiApiDevice))
            assert row is not None and row.device_id is None

    run(gone)
    assert api.detail_calls == []


def test_controller_without_official_api_still_reads_poe_and_clients(client):
    run(_drop_snmp_switch)
    assert poll(FakeApi(no_official=True)) is True

    async def check():
        async with Session() as s:
            assert await s.scalar(select(func.count()).select_from(Device).where(Device.driver == "unifi_api")) == 0
            assert await s.scalar(select(func.count()).select_from(NetworkClient)) == 9

    run(check)


def test_controller_failure_marks_api_devices_down(client):
    run(_drop_snmp_switch)
    poll(FakeApi())
    assert poll(FakeApi(fail=True)) is False

    async def check():
        async with Session() as s:
            dev = await s.scalar(select(Device).where(Device.driver == "unifi_api"))
            assert dev.status == "down" and "Kontroler UniFi" in dev.last_error

    run(check)
