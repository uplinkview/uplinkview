"""OPNsense API: parsery i klient na zanonimizowanych odpowiedziach OPNsense 26.7.9 (VirtualBox, 14.11.2026)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from netpulse.opnsense import (
    ARP,
    FIRMWARE,
    GATEWAYS,
    INTERFACES,
    LEASES,
    SERVICES,
    OpnsenseApi,
    OpnsenseError,
    parse_arp,
    parse_firmware,
    parse_gateways,
    parse_interfaces,
    parse_leases,
    parse_number,
    parse_services,
    update_available,
)
from netpulse.opnsense_collector import metric_rows, wan_states

FIX = Path(__file__).parent / "fixtures" / "opnsense_api"
FILES = {
    FIRMWARE: "core_firmware_status.json",
    GATEWAYS: "routes_gateway_status.json",
    INTERFACES: "interfaces_overview_interfaces_info.json",
    SERVICES: "core_service_search.json",
    ARP: "diagnostics_interface_get_arp.json",
    LEASES[0]: "dnsmasq_leases_search.json",
    LEASES[1]: "kea_leases4_search.json",
}


def load(path: str):
    return json.loads((FIX / FILES[path]).read_text(encoding="utf-8"))


def transport(status: dict[str, int] | None = None, override: dict[str, object] | None = None, seen: list | None = None):
    status, override = status or {}, override or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/")
        if seen is not None:
            seen.append((path, request.headers.get("authorization")))
        if path in status:
            return httpx.Response(status[path], json={"message": "x"})
        if path in override:
            return httpx.Response(200, json=override[path])
        if path in FILES:
            return httpx.Response(200, json=load(path))
        return httpx.Response(404, json={"errorMessage": "Endpoint not found"})

    return httpx.MockTransport(handler)


def snapshot(**kw):
    async def go():
        api = OpnsenseApi("192.168.1.135", "klucz-api-123", "sekret-api-456", transport=transport(**kw))
        try:
            return await api.snapshot()
        finally:
            await api.close()

    return asyncio.run(go())


def test_parse_number():
    assert parse_number("12.3 ms") == 12.3
    assert parse_number("0.0 %") == 0.0
    assert parse_number("~") is None
    assert parse_number(None) is None
    assert parse_number(5) == 5.0


def test_firmware_version_and_update():
    version, latest = parse_firmware(load(FIRMWARE))
    assert (version, latest) == ("26.7.9_1", "26.7.9")
    assert not update_available(version, latest)  # _1 = poprawka pakietu tej samej wersji
    assert update_available("26.7.9_1", "26.7.10")
    assert not update_available(None, "26.7.10")


def test_gateways_monitored_and_not():
    gws = {g.name: g for g in parse_gateways(load(GATEWAYS))}
    v4, v6 = gws["WAN_DHCP"], gws["WAN_DHCP6"]
    assert v4.up is True and v4.monitor == "8.8.8.8" and v4.address == "192.168.1.1"
    assert (v4.delay_ms, v4.jitter_ms, v4.loss_percent) == (12.3, 0.8, 0.0)
    assert v6.up is None and v6.delay_ms is None  # bez monitorowania – brak pomiaru, nie „działa”


def test_gateway_down():
    body = {"items": [{"name": "WAN_GSM", "address": "10.0.0.1", "status": "down", "loss": "100.0 %", "delay": "0.0 ms",
                       "stddev": "0.0 ms", "monitor": "1.1.1.1", "status_translated": "Offline"}]}
    (g,) = parse_gateways(body)
    assert g.up is False and g.loss_percent == 100.0


def test_interfaces_and_default_route():
    ifaces = {i.device: i for i in parse_interfaces(load(INTERFACES))}
    assert ifaces["em0"].identifier == "lan" and ifaces["em0"].description == "LAN"
    assert ifaces["em0"].addr4 == "192.168.10.1/24" and not ifaces["em0"].default_route
    wan = ifaces["em1"]
    assert (wan.identifier, wan.description, wan.link_type) == ("wan", "WAN", "dhcp")
    assert wan.gateways == ["192.168.1.1"] and wan.default_route


def test_services_keyed_by_id():
    services = {s.name: s for s in parse_services(load(SERVICES))}
    assert "dpinger/WAN_DHCP" in services and "dpinger/:watcher:" in services  # dwa dpinger – nie nadpisują się
    assert services["unbound"].running and services["unbound"].description == "Unbound"
    assert len(services) == 17


def test_leases_and_arp():
    (lease,) = parse_leases(load(LEASES[0]))
    assert lease.ip == "192.168.10.126" and lease.hostname == "host-1" and lease.interface == "LAN"
    assert lease.source == "dhcp" and isinstance(lease.expires, int)
    assert parse_leases(load(LEASES[1])) == []
    arp = parse_arp(load(ARP))
    assert len(arp) == 4  # bez dwóch własnych adresów OPNsense (permanent)
    assert all(h.source == "arp" for h in arp)


def test_snapshot_from_real_responses():
    snap = snapshot()
    assert snap.version == "26.7.9_1" and not snap.update_available
    assert snap.dhcp == "dnsmasq"
    (v4,) = [g for g in snap.gateways if g.name == "WAN_DHCP"]
    assert v4.interface == "em1" and v4.default  # brama przypisana do interfejsu z trasą domyślną
    hosts = {h.ip: h for h in snap.hosts}
    assert hosts["192.168.10.126"].source == "dhcp"  # dzierżawa i ARP tego samego MAC – jeden wiersz
    assert hosts["192.168.10.126"].hostname == "host-1"
    assert [h.ip for h in snap.hosts] == sorted(hosts, key=lambda ip: tuple(int(p) for p in ip.split(".")))
    assert len(snap.hosts) == 4
    d = snap.as_dict()
    assert d["update_available"] is False and d["gateways"][0]["name"]
    json.dumps(d)  # do kolumny JSONB


def test_metric_rows_and_wan_states():
    snap = snapshot()
    now = datetime(2026, 11, 14, tzinfo=UTC)
    rows = {(r["name"], r["key"]): r["value"] for r in metric_rows(7, snap, now)}
    assert rows[("gateway_up", "WAN_DHCP")] == 1.0
    assert ("gateway_up", "WAN_DHCP6") not in rows  # bez monitorowania
    assert rows[("wan_latency_ms", "em1")] == 12.3
    assert rows[("wan_jitter_ms", "em1")] == 0.8
    assert rows[("wan_loss_percent", "em1")] == 0.0
    assert rows[("opnsense_service_up", "unbound")] == 1.0
    (w,) = wan_states(snap)
    assert (w.ifname, w.up, w.active) == ("em1", True, True)


def test_optional_endpoints_without_privileges():
    snap = snapshot(status={INTERFACES: 403, SERVICES: 403, ARP: 403, LEASES[0]: 404, LEASES[1]: 404, LEASES[2]: 404})
    assert snap.version == "26.7.9_1" and snap.gateways
    assert snap.interfaces == [] and snap.services == [] and snap.hosts == [] and snap.dhcp is None
    assert all(g.interface is None for g in snap.gateways)


def test_kea_used_when_dnsmasq_empty():
    kea = {"rows": [{"hwaddr": "02:00:00:00:00:aa", "address": "192.168.10.50", "hostname": "nas", "if_descr": "LAN"}]}
    snap = snapshot(override={LEASES[0]: {"rows": []}, LEASES[1]: kea})
    assert snap.dhcp == "kea"
    assert any(h.hostname == "nas" and h.source == "dhcp" for h in snap.hosts)


@pytest.mark.parametrize(
    ("status", "message"),
    [({FIRMWARE: 401}, "odrzucił klucz"), ({GATEWAYS: 403}, "nie ma uprawnień"), ({FIRMWARE: 500}, "kodem 500")],
)
def test_errors_are_readable(status, message):
    with pytest.raises(OpnsenseError, match=message):
        snapshot(status=status)


def test_basic_auth_and_base_url():
    seen: list = []

    async def go():
        api = OpnsenseApi("192.168.1.135", "klucz-api-123", "sekret-api-456", port=8443, transport=transport(seen=seen))
        assert api.base == "https://192.168.1.135:8443/api/"
        try:
            await api.get(FIRMWARE)
        finally:
            await api.close()

    asyncio.run(go())
    assert seen and seen[0][0] == FIRMWARE and seen[0][1].startswith("Basic ")
