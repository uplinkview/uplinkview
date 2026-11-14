"""VPN użytkowników zdalnych z kontrolera UniFi (0.57.0): parsery, zdjęcie stanu, wykrywanie nowych połączeń."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import UTC, datetime, timedelta

import httpx
from conftest import FIXTURES

from netpulse.unifi import UnifiApi, parse_vpn_servers, parse_vpn_sessions, parse_vpn_users
from netpulse.vpn import detect, metrics, snapshot

DATA = json.loads((FIXTURES / "unifi_vpn.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def parsed():
    return parse_vpn_servers(DATA["networkconf"]), parse_vpn_users(DATA["wireguard_users"]), parse_vpn_sessions(DATA["remoteuservpn"])


def test_parsers_read_servers_users_and_sessions():
    servers, users, sessions = parsed()
    (srv,) = servers  # sieć LAN to nie serwer VPN
    assert (srv.name, srv.vpn_type, srv.port, srv.subnet, srv.enabled) == ("WG-Home", "wireguard-server", 51820, "192.168.3.1/24", True)
    assert [u.name for u in users] == ["iPhone", "Laptop"]
    (s,) = sessions
    assert (s.user, s.interface, s.tunnel_ip, s.server_id, s.connected_at) == ("iPhone", "wgsrv1", "192.168.3.2", "net-wg", 1793835408)
    # Kontroler podaje rx_rate/tx_rate w bitach/s (zmierzone 13.11.2026), tx = do klienta
    assert s.tx_bps == 147888 and s.rx_bps == 96637 and s.tx_bytes == 76148892  # b/s prosto z kontrolera
    assert parse_vpn_sessions({"data": [{"user": "x", "up": False}]}) == []
    assert parse_vpn_servers({}) == [] and parse_vpn_users({"data": "zły format"}) == []


def test_snapshot_keeps_offline_users_and_last_seen():
    snap = snapshot(*parsed(), None, NOW, 1)
    assert snap["servers"] == [{"id": "net-wg", "name": "WG-Home", "type": "WireGuard", "enabled": True, "port": 51820, "subnet": "192.168.3.1/24"}]
    phone, laptop = snap["users"]
    assert phone["connected"] and phone["down_bps"] == 147888 and phone["up_bytes"] == 11867028
    assert phone["since"] == datetime.fromtimestamp(1793835408, UTC).isoformat() and phone["last_seen"] == NOW.isoformat()
    assert not laptop["connected"] and laptop["last_seen"] is None and laptop["tunnel_ip"] == "192.168.3.3"
    # Rozłączenie: zostaje czas ostatniego połączenia i przesłane dane, bez bieżącego ruchu
    later = NOW + timedelta(minutes=5)
    servers, users, _ = parsed()
    snap2 = snapshot(servers, users, [], snap, later, 1)
    phone2 = snap2["users"][0]
    assert not phone2["connected"] and phone2["last_seen"] == NOW.isoformat() and phone2["down_bps"] is None
    assert phone2["down_bytes"] == 76148892 and phone2["remote_ip"] == "203.0.113.7"


def test_rate_from_byte_counters_between_samples():
    """Prędkość z przyrostu bajtów od poprzedniego odczytu, nie chwilowa wartość z ok. 1 s (tunel WG-VPS 14.11.2026:
    chwilowe odczyty co 30 s dawały −53 % / −27 % względem liczników jądra bramy)."""
    servers, users, (s,) = parsed()
    snap = snapshot(servers, users, [s], None, NOW, 1)
    assert snap["users"][0]["down_bps"] == 147888  # pierwszy odczyt sesji – wartość z kontrolera
    more = dataclasses.replace(s, tx_bytes=s.tx_bytes + 3_000_000, rx_bytes=s.rx_bytes + 600_000, tx_bps=5000, rx_bps=1)
    phone = snapshot(servers, users, [more], snap, NOW + timedelta(seconds=30), 1)["users"][0]
    assert phone["down_bps"] == 800_000 and phone["up_bps"] == 160_000  # 3 MB i 0,6 MB w 30 s
    # Nowa sesja (inny czas połączenia), wyzerowany licznik albo długa przerwa – znowu wartość z kontrolera
    new = dataclasses.replace(more, connected_at=s.connected_at + 100, tx_bytes=10)
    assert snapshot(servers, users, [new], snap, NOW + timedelta(seconds=30), 1)["users"][0]["down_bps"] == 5000
    reset = dataclasses.replace(more, tx_bytes=10)
    assert snapshot(servers, users, [reset], snap, NOW + timedelta(seconds=30), 1)["users"][0]["down_bps"] == 5000
    assert snapshot(servers, users, [more], snap, NOW + timedelta(minutes=5), 1)["users"][0]["down_bps"] == 5000


def test_metrics_connected_flag_for_everyone_traffic_only_when_connected():
    rows = {(m.name, m.key): m.value for m in metrics(1, snapshot(*parsed(), None, NOW, 1), NOW)}
    assert rows == {
        ("vpn_connected", "iPhone"): 1.0,
        ("vpn_down_bps", "iPhone"): 147888,  # rx_rate/tx_rate z kontrolera to już b/s (0.72.0)
        ("vpn_up_bps", "iPhone"): 96637,
        ("vpn_connected", "Laptop"): 0.0,
    }


def test_detect_new_connection_only_after_disconnected_sample():
    t = [NOW + timedelta(seconds=30 * i) for i in range(8)]
    samples = [
        (1, "iPhone", t[0], 1.0),  # pierwsza próbka – nie wiadomo, co było wcześniej
        (1, "iPhone", t[1], 0.0),
        (1, "iPhone", t[2], 1.0),  # połączenie
        (1, "iPhone", t[3], 1.0),
        (1, "Laptop", t[0], 0.0),
        (1, "Laptop", t[7], 1.0),  # po przerwie w odczytach (3,5 min) – bez zdarzenia
    ]
    assert [(c.user, c.time) for c in detect(samples)] == [("iPhone", t[2])]


def test_api_vpn_reads_three_endpoints_and_tolerates_missing_vpn():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/rest/networkconf"):
            return httpx.Response(200, json=DATA["networkconf"])
        if path.endswith("/stat/remoteuservpn"):
            return httpx.Response(200, json=DATA["remoteuservpn"])
        if path.endswith("/wireguard/users"):
            return httpx.Response(200, json=DATA["wireguard_users"])
        return httpx.Response(404)

    api = UnifiApi("10.0.0.1", "klucz", transport=httpx.MockTransport(handler))
    servers, users, sessions = asyncio.run(api.vpn())
    assert [s.name for s in servers] == ["WG-Home"] and len(users) == 2 and sessions[0].user == "iPhone"

    # Starszy kontroler bez adresów VPN (404) albo bez serwera VPN – puste listy, bez błędu
    old = UnifiApi("10.0.0.1", "klucz", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert asyncio.run(old.vpn()) == ([], [], [])
    lan_only = UnifiApi(
        "10.0.0.1", "klucz", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [DATA["networkconf"]["data"][0]]}))
    )
    assert asyncio.run(lan_only.vpn()) == ([], [], [])
