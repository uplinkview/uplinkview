"""Wykrywanie urządzeń i raport urządzenia (0.73.0): zakresy, rozpoznanie z `system`, skan jednym gniazdem, anonimizacja."""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import FIXTURES
from pyasn1.codec.ber import decoder, encoder
from pysnmp.proto import api

from netpulse import devreport, discovery
from netpulse.drivers.generic import read_system
from netpulse.snmp import SnmpCredentials
from netpulse.snmp.snmprec import SnmprecClient, parse_snmprec

# --- zakresy ------------------------------------------------------------------------------------


def test_hosts_of_cidr_range_and_single():
    assert len(discovery.hosts_of("192.168.1.0/24")) == 254
    assert discovery.hosts_of("192.168.1.7/24")[0] == "192.168.1.1"  # adres hosta w CIDR = cała podsieć
    assert discovery.hosts_of("10.0.0.5-10.0.0.7") == ["10.0.0.5", "10.0.0.6", "10.0.0.7"]
    assert discovery.hosts_of("10.0.0.250-252") == ["10.0.0.250", "10.0.0.251", "10.0.0.252"]
    assert discovery.hosts_of("10.0.0.9") == ["10.0.0.9"]
    assert len(discovery.hosts_of("10.0.0.0/22")) == 1022


@pytest.mark.parametrize("bad", ["10.0.0.0/21", "10.0.0.9-10.0.0.1", "abc", "10.0.0.0/33", "10.0.0.1-10.0.8.1"])
def test_hosts_of_rejects_bad_or_huge(bad):
    with pytest.raises(discovery.DiscoveryError):
        discovery.hosts_of(bad)


def test_suggest_network_prefers_devices_then_private_only():
    assert discovery.suggest_network(["192.168.1.1", "192.168.1.2", "10.0.5.1", "nas.local"]) == "192.168.1.0/24"
    assert discovery.suggest_network(["8.8.8.8", "127.0.0.1", None]) is None
    assert discovery.suggest_network(["172.18.0.4"]) == "172.18.0.0/24"


# --- rozpoznanie z samego `system` ----------------------------------------------------------------


async def _describe(fixture: str) -> discovery.Found:
    client = SnmprecClient.from_file(FIXTURES / fixture)
    return discovery.describe("192.0.2.10", await read_system(client))


@pytest.mark.parametrize(
    ("fixture", "driver", "kind", "model"),
    [
        ("ucg-ultra.snmprec", "unifi", "gateway", "UCG-Ultra"),
        ("u6-plus.snmprec", "unifi", "ap", "U6+"),
        ("mikrotik-chr.snmprec", "mikrotik", None, None),
        ("linux-server.snmprec", "linux", None, None),
        ("tplink-jetstream.snmprec", "omada", None, None),
        ("opnsense.snmprec", "opnsense", "gateway", "OPNsense"),
    ],
)
def test_describe_picks_same_driver_as_collector(fixture, driver, kind, model):
    f = asyncio.run(_describe(fixture))
    assert f.driver == driver and not f.generic
    if kind:
        assert f.kind == kind
    if model:
        assert f.model == model
    assert f.vendor and f.vendor != "Generic"


def test_unknown_device_is_generic():
    client = SnmprecClient({"1.3.6.1.2.1.1.1.0": b"Printer 3000", "1.3.6.1.2.1.1.2.0": "1.3.6.1.4.1.99999.1", "1.3.6.1.2.1.1.5.0": b"drukarka"})
    f = discovery.describe("192.0.2.20", asyncio.run(read_system(client)))
    assert f.generic and f.driver == "generic" and f.vendor is None  # numer 99999 nieznany – bez „Generic”
    assert discovery.vendor_of("1.3.6.1.4.1.6574.1") == "Synology"
    assert discovery.vendor_of(".1.3.6.1.4.1.11.2.3.9.1") == "HP"
    assert discovery.vendor_of("1.3.6.1.4.1.8072.3.2.10") is None
    assert discovery.default_name(f) == "drukarka"
    f.name = None
    assert discovery.default_name(f) == "Printer 192.0.2.20"


def test_scan_with_clients_skips_silent_hosts():
    data = {"192.0.2.1": FIXTURES / "ucg-ultra.snmprec", "192.0.2.3": FIXTURES / "u6-plus.snmprec"}

    class Silent:
        async def get(self, oids):
            raise TimeoutError

        async def close(self):
            return None

    def factory(host):
        return SnmprecClient.from_file(data[host]) if host in data else Silent()

    found = asyncio.run(discovery.scan(["192.0.2.3", "192.0.2.2", "192.0.2.1"], factory, concurrency=2))
    assert [f.host for f in found] == ["192.0.2.1", "192.0.2.3"]  # kolejność adresów, bez milczących
    assert [f.kind for f in found] == ["gateway", "ap"]


# --- skan SNMP v2c jednym gniazdem -----------------------------------------------------------------


class FakeAgent(asyncio.DatagramProtocol):
    """Prosty agent SNMP v2c na 127.0.0.1: odpowiada wartościami z .snmprec, na złą community milczy."""

    def __init__(self, values: dict, community: str = "public") -> None:
        self.values, self.community, self.requests = values, community, 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.requests += 1
        mod = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]
        msg, _ = decoder.decode(data, asn1Spec=mod.Message())
        if str(mod.apiMessage.get_community(msg)) != self.community:
            return
        req = mod.apiMessage.get_pdu(msg)
        rsp_msg = mod.apiMessage.get_response(msg)
        rsp = mod.apiMessage.get_pdu(rsp_msg)
        binds = []
        for name, _ in mod.apiPDU.get_varbinds(req):
            v = self.values.get(str(name))
            if isinstance(v, bytes):
                binds.append((name, mod.OctetString(v)))
            elif isinstance(v, int):
                binds.append((name, mod.TimeTicks(v)))
            elif isinstance(v, str):
                binds.append((name, mod.ObjectIdentifier(v)))
            else:
                binds.append((name, mod.Null("")))
        mod.apiPDU.set_varbinds(rsp, binds)
        self.transport.sendto(encoder.encode(rsp_msg), addr)


async def _scan_fake(community: str):
    values = parse_snmprec((FIXTURES / "usw-lite-8-poe.snmprec").read_text())
    loop = asyncio.get_running_loop()
    transport, agent = await loop.create_datagram_endpoint(lambda: FakeAgent(values), local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    try:
        return await discovery.scan_community(["127.0.0.1"], SnmpCredentials(community=community), port=port, wait_s=0.3), agent
    finally:
        transport.close()


def test_scan_community_reads_system_over_one_socket():
    systems, agent = asyncio.run(_scan_fake("public"))
    assert list(systems) == ["127.0.0.1"] and agent.requests == 1  # odpowiedział w pierwszej rundzie
    f = discovery.describe("127.0.0.1", systems["127.0.0.1"])
    assert f.driver == "unifi" and f.kind == "switch"


def test_scan_community_wrong_community_finds_nothing_and_retries():
    systems, agent = asyncio.run(_scan_fake("zla-community"))
    assert systems == {} and agent.requests == 2  # druga runda tylko do milczących


# --- raport urządzenia ----------------------------------------------------------------------------

SECRETS = {
    "sys_name": b"dom-kowalskich-router",
    "location": b"ul. Prywatna 5",
    "contact": b"jan@example.pl",
    "mac": bytes.fromhex("0ceaa1b2c3d4"),
    "alias": b"Pokoj Ani",
    "ssid": b"Wifi-Kowalscy",
    "neighbor": b"nas-jana",
    "serial": b"SN123456789",
}


def _sensitive_client() -> SnmprecClient:
    data = parse_snmprec((FIXTURES / "u6-plus.snmprec").read_text())
    data.update(
        {
            "1.3.6.1.2.1.1.5.0": SECRETS["sys_name"],
            "1.3.6.1.2.1.1.6.0": SECRETS["location"],
            "1.3.6.1.2.1.1.4.0": SECRETS["contact"],
            "1.3.6.1.2.1.2.2.1.6.2": SECRETS["mac"],
            "1.3.6.1.2.1.31.1.1.1.18.2": SECRETS["alias"],
            "1.3.6.1.4.1.41112.1.6.1.2.1.6.1": SECRETS["ssid"],
            "1.3.6.1.4.1.41112.1.6.1.2.1.6.9": b"element-abcdef",
            "1.3.6.1.2.1.47.1.1.1.1.11.1": SECRETS["serial"],
            "1.0.8802.1.1.2.1.4.1.1.9.0.3.1": SECRETS["neighbor"],
            # tekst z adresami i nazwą urządzenia, tablica z MAC w indeksie, adres IP jako wartość
            "1.3.6.1.4.1.41112.1.6.9.1.0": b"gw 192.168.1.1 mac 0c:ea:a1:b2:c3:d4 host dom-kowalskich-router",
            "1.3.6.1.4.1.41112.1.6.9.2.12.234.161.178.195.212": 7,
            "1.3.6.1.4.1.41112.1.6.9.3.0": "192.168.1.77",
            # tabela klientów WiFi – nie jest czytana wcale
            "1.3.6.1.4.1.41112.1.6.1.3.1.1.1": b"klient",
        }
    )
    return SnmprecClient(data)


def test_report_has_no_private_values():
    report = asyncio.run(devreport.build(_sensitive_client(), driver="unifi", interval_s=0))
    text = json.dumps(report, ensure_ascii=False)
    lowered = text.lower()
    for name, raw in SECRETS.items():
        assert raw.hex() not in lowered, name
        assert raw.decode(errors="ignore").lower() not in lowered, name
    for bad in ("192.168.1.1", "192.168.1.77", "0c:ea:a1", "12.234.161.178.195.212"):
        assert bad not in lowered, bad
    assert report["format"] == devreport.FORMAT and report["records"] > 100
    assert "public" not in text  # community nigdy
    walk = parse_snmprec(report["walk"])
    assert walk["1.3.6.1.2.1.1.5.0"] == b"device"
    assert walk["1.3.6.1.4.1.41112.1.6.1.2.1.6.1"] == b"ssid-1"
    assert walk["1.3.6.1.4.1.41112.1.6.1.2.1.6.9"].startswith(b"element-")  # driver ukrywa po przedrostku
    assert not any(k.startswith("1.3.6.1.4.1.41112.1.6.1.3.") for k in walk)
    assert walk["1.3.6.1.2.1.1.1.0"] == b"U6+ 6.7.54.15663"  # opis systemu (model) zostaje
    assert b"device" in walk["1.3.6.1.4.1.41112.1.6.9.1.0"]


def test_report_keeps_model_name_that_is_part_of_descr():
    data = parse_snmprec((FIXTURES / "ucg-ultra.snmprec").read_text())
    data["1.3.6.1.2.1.1.5.0"] = b"UCG-Ultra"
    report = asyncio.run(devreport.build(SnmprecClient(data), interval_s=0))
    assert parse_snmprec(report["walk"])["1.3.6.1.2.1.1.1.0"].startswith(b"Ubiquiti UniFi UCG-Ultra")


def test_report_second_read_lists_changed_counters():
    client = SnmprecClient.from_file(FIXTURES / "usw-lite-8-poe.snmprec")
    oid = "1.3.6.1.2.1.31.1.1.1.6.1"  # ifHCInOctets portu 1
    start = asyncio.run(client.get([oid]))[oid]

    async def build():
        task = asyncio.create_task(devreport.build(client, interval_s=0.05))
        await asyncio.sleep(0.01)
        client.set(oid, start + 1000)
        return await task

    report = asyncio.run(build())
    changes = parse_snmprec(report["walk2_changes"])
    assert changes == {oid: start + 1000} and report["changed"] == 1


def test_anonymizer_is_consistent():
    a = devreport.Anonymizer()
    assert a.ip("10.1.2.3") == a.ip("10.1.2.3") != a.ip("10.1.2.4")
    assert a.ip("0.0.0.0") == "0.0.0.0" and a.ip("255.255.255.0") == "255.255.255.0"
    m = a.mac(bytes.fromhex("aabbccddeeff"))
    assert m[0] == 0x02 and a.mac(bytes.fromhex("aabbccddeeff")) == m
    assert a.scrub("from 10.1.2.3 to AA-BB-CC-DD-EE-FF, mail x.y@firma.pl") == f"from {a.ip('10.1.2.3')} to {m.hex(':')}, mail user@example.com"
    assert devreport.vendor_branch("1.3.6.1.4.1.41112") == "1.3.6.1.4.1.41112"
    assert devreport.vendor_branch(".1.3.6.1.4.1.14988.1") == "1.3.6.1.4.1.14988"
    assert devreport.vendor_branch("1.3.6.1.4.1.8072.3.2.10") is None
