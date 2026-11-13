"""Testy driverów na zanonimizowanych zrzutach z prawdziwych urządzeń UniFi."""

from __future__ import annotations

import asyncio

import pytest
from conftest import FIXTURES

from netpulse.drivers import (
    GenericDriver,
    LinuxDriver,
    MikrotikDriver,
    OmadaDriver,
    OpnsenseDriver,
    UnifiDriver,
    detect_driver,
    poll_device,
)
from netpulse.drivers.base import SystemInfo
from netpulse.drivers.linux import is_real_mount, parse_kernel
from netpulse.drivers.opnsense import parse_series
from netpulse.snmp.snmprec import SnmprecClient, parse_snmprec


def poll(name: str, driver: str = "auto"):
    client = SnmprecClient.from_file(FIXTURES / f"{name}.snmprec")
    return asyncio.run(poll_device(client, driver))


def by_name(result):
    return {i.name: i for i in result.interfaces}


def test_ucg_ultra_gateway():
    r = poll("ucg-ultra")
    assert r.driver == UnifiDriver.name
    assert r.system.kind == "gateway"
    assert r.system.model == "UCG-Ultra"
    assert r.system.firmware == "5.1.33"
    ifs = by_name(r)
    assert (ifs["eth4"].role, ifs["eth4"].label) == ("wan", "WAN")
    assert [ifs[f"eth{n}"].label for n in range(4)] == ["LAN 1", "LAN 2", "LAN 3", "LAN 4"]
    visible = {i.name for i in r.visible_interfaces()}
    assert visible == {"eth0", "eth1", "eth2", "eth3", "eth4"}
    assert ifs["eth4"].counter_bits == 64
    assert ifs["eth4"].in_octets and ifs["eth4"].in_octets > 0
    assert ifs["eth4"].speed_mbps == 1000
    assert r.health.mem_total_kb and r.health.mem_used_percent is not None
    assert r.health.load1 is not None


def test_ucg_ultra_unifi_os_6():
    """UniFi OS 6.0.17 (prawdziwy zrzut 11.11.2026): inne numery ifIndex, te same role po nazwach, WireGuard stale."""
    r = poll("ucg-ultra-6")
    assert (r.system.model, r.system.firmware, r.system.kind) == ("UCG-Ultra", "6.0.17", "gateway")
    ifs = by_name(r)
    assert (ifs["eth4"].if_index, ifs["eth4"].role, ifs["eth4"].label) == (7, "wan", "WAN")
    assert [ifs[f"eth{n}"].label for n in range(4)] == ["LAN 1", "LAN 2", "LAN 3", "LAN 4"]
    assert ifs["eth3"].if_index == 12
    assert not {"bond0", "ifb0", "ifb1"} & set(ifs)
    assert {i.name for i in r.visible_interfaces()} == {"eth0", "eth1", "eth2", "eth3", "eth4", "wgsrv1", "wgsrv2"}
    assert (ifs["wgsrv1"].role, ifs["wgsrv1"].label) == ("vpn", "WG-Server-1")
    assert r.health.mem_total_kb and r.health.load1 is not None


def test_unifi_gateway_vpn_interface_has_vpn_role():
    """WireGuard bramy (`wgsrv1`, alias = nazwa sieci VPN w UniFi) jest widoczny z rolą „vpn” (od 0.57.0)."""
    from netpulse.drivers.base import InterfaceSample

    r = poll("ucg-ultra")
    iface = InterfaceSample(if_index=90497, name="wgsrv1", descr="wgsrv1", alias="WG-Home", if_type=1)
    UnifiDriver().enrich_interface(iface, r)
    assert (iface.role, iface.label, iface.hidden) == ("vpn", "WG-Home", False)
    wg = InterfaceSample(if_index=5, name="wg0", descr="wg0", alias=None, if_type=1)
    UnifiDriver().enrich_interface(wg, r)
    assert wg.hidden  # stary wg0 bez sieci VPN – dalej wirtualny


def test_usw_lite_switch():
    r = poll("usw-lite-8-poe")
    assert r.system.kind == "switch"
    ports = r.visible_interfaces()
    assert [p.label for p in ports] == [f"Port {n}" for n in range(1, 9)]
    ifs = by_name(r)
    assert ifs["0/1"].alias == "AP U6+"
    assert ifs["0/8"].alias == "UCG Ultra"
    assert ifs["0/2"].alias is None  # domyślny alias "Port 2" jest pomijany
    assert ifs["0/7"].speed_mbps == 100  # telewizor
    assert ifs["0/2"].oper_status == "down"


def test_u6_plus_access_point():
    r = poll("u6-plus")
    assert r.system.kind == "ap"
    assert r.system.model == "U6+"
    assert r.system.firmware == "6.7.54.15663"
    visible = r.visible_interfaces()
    assert [(i.name, i.role) for i in visible] == [("eth0", "uplink")]
    ssids = [w for w in r.wifi if not w.hidden]
    assert {(w.ssid, w.radio) for w in ssids} == {
        ("NetPulse-Test-2G", "2.4GHz"),
        ("NetPulse-Test", "2.4GHz"),
        ("NetPulse-Test", "5GHz"),
    }
    assert sum(w.clients or 0 for w in ssids) == 5
    assert all(w.hidden for w in r.wifi if w.ssid.startswith(("element-", "vwire-")))
    # Zajętość kanału z UI-MIB unifiRadioTable (CuTotal), klucz = pasmo
    util = {m.key: m.value for m in r.metrics if m.name == "channel_util_percent"}
    assert util == {"2.4GHz": 30.0, "5GHz": 1.0}


def test_unifi_switch_has_no_radio_metrics():
    r = poll("usw-lite-8-poe")
    assert not [m for m in r.metrics if m.name == "channel_util_percent"]


def test_generic_driver_forced():
    r = poll("usw-lite-8-poe", driver="generic")
    assert r.driver == "generic"
    assert len(r.interfaces) == 8
    assert r.interfaces[0].label == "AP U6+"  # generic: alias jako etykieta


def test_linux_server_snmpd():
    r = poll("linux-server")
    assert r.driver == LinuxDriver.name
    s = r.system
    assert (s.kind, s.vendor, s.model, s.firmware) == ("server", "Linux", "Linux 6.8.0-45-generic", "6.8.0-45-generic")
    assert s.name == "homelab-srv" and s.uptime_s == 1234567.89
    h = r.health
    assert h.cpu_percent == 13.0 and h.mem_total_kb == 16384000
    assert h.mem_used_percent == 35.0  # bez pamięci podręcznej i buforów
    assert (h.load1, h.load5, h.load15) == (0.52, 0.40, 0.31)
    assert r.server is not None and r.server.swap_used_percent == 25.0 and r.server.processes == 213


def test_linux_server_disks_skip_pseudo_filesystems():
    disks = {d.mount: d for d in poll("linux-server").disks}
    assert set(disks) == {"/", "/boot", "/mnt/data"}  # bez /run, /dev/shm, /boot/efi, warstw Dockera i snap-ów
    assert disks["/"].total_bytes == 15_000_000 * 4096 and disks["/"].used_percent == 35.0
    assert disks["/boot"].used_percent == 25.0
    assert disks["/mnt/data"].used_percent == 89.8


def test_linux_server_hides_container_interfaces():
    r = poll("linux-server")
    assert {i.name for i in r.visible_interfaces()} == {"eno1", "wlp2s0"}
    ifs = by_name(r)
    assert ifs["eno1"].role == "lan" and ifs["eno1"].speed_mbps == 1000 and ifs["eno1"].oper_status == "up"
    assert ifs["wlp2s0"].oper_status == "down"
    for hidden in ("lo", "docker0", "br-0123456789ab", "veth1a2b3c4"):
        assert ifs[hidden].hidden
    assert ifs["docker0"].role == "virtual"


def test_linux_driver_detection_and_helpers():
    linux = SystemInfo(descr="Linux srv 6.1.0 #1 SMP x86_64", object_id="1.3.6.1.4.1.8072.3.2.10")
    assert detect_driver(linux) is LinuxDriver
    assert detect_driver(SystemInfo(descr="Cisco IOS Software")) is GenericDriver
    # Urządzenia UniFi też mają net-snmp na Linuksie, ale własny driver wygrywa
    unifi = SystemInfo(descr="Ubiquiti UniFi UCG-Ultra 5.1.33 Linux 5.4.213", object_id="1.3.6.1.4.1.8072.3.2.10")
    assert detect_driver(unifi) is UnifiDriver
    assert parse_kernel("Linux srv 6.8.0-45-generic #45 SMP") == "6.8.0-45-generic"
    assert parse_kernel("Windows") is None and parse_kernel(None) is None
    assert is_real_mount("/mnt/nas") and not is_real_mount("/run/lock") and not is_real_mount("/var/lib/docker/overlay2/x")


def test_forced_linux_driver_on_any_snmpd():
    r = poll("ucg-ultra", driver="linux")  # wymuszenie w formularzu urządzenia
    assert r.driver == "linux" and r.system.kind == "server"


def poll_with(name: str, **overrides):
    """Zrzut z podmienionymi wartościami (np. nazwa płyty, komentarz portu) – inne modele bez nowych plików."""
    client = SnmprecClient.from_file(FIXTURES / f"{name}.snmprec")
    for oid, value in overrides.items():
        client.set(oid, value)
    return asyncio.run(poll_device(client))


MT_BOARD = "1.3.6.1.4.1.14988.1.1.7.8.0"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"


def test_mikrotik_router():
    r = poll("mikrotik-hex")
    assert r.driver == MikrotikDriver.name
    s = r.system
    assert (s.kind, s.vendor, s.model, s.firmware, s.name) == ("gateway", "MikroTik", "RB750Gr3", "7.15.3", "hex")
    assert r.health.cpu_percent == 25.0  # średnia z czterech rdzeni
    assert r.health.mem_total_kb == 262144 and r.health.mem_used_percent == 38.1


def test_mikrotik_interfaces_wan_lan_and_virtual():
    r = poll("mikrotik-hex")
    ifs = by_name(r)
    assert [i.name for i in r.interfaces if i.role == "wan"] == ["ether1"]  # PPPoE nie liczy się drugi raz
    assert (ifs["ether1"].role, ifs["ether1"].label) == ("wan", "WAN")
    assert (ifs["ether2"].role, ifs["ether2"].label, ifs["ether2"].alias) == ("lan", "NAS", "NAS")  # komentarz jako nazwa
    assert (ifs["ether3"].role, ifs["ether3"].label) == ("lan", "ether3")
    assert {"bridge", "pppoe-out1"} <= {i.name for i in r.interfaces if i.hidden}
    assert {i.name for i in r.visible_interfaces()} == {f"ether{n}" for n in range(1, 6)}


def test_mikrotik_wan_marked_by_comment_and_board_decides_kind():
    r = poll_with("mikrotik-hex", **{f"{IF_ALIAS}.3": b"Internet LTE"})
    ifs = by_name(r)
    assert ifs["ether3"].role == "wan" and ifs["ether3"].label == "Internet LTE"
    assert r.system.kind == "gateway"

    switch = poll_with("mikrotik-hex", **{MT_BOARD: b"CRS326-24G-2S+RM"})
    assert switch.system.kind == "switch" and by_name(switch)["ether2"].role == "port"
    assert not [i for i in switch.interfaces if i.role == "wan"]  # switch nie ma WAN

    assert poll_with("mikrotik-hex", **{MT_BOARD: b"cAP ac"}).system.kind == "ap"


def test_mikrotik_chr_real_dump():
    """Prawdziwy zrzut RouterOS 7.18.2 (CHR w VirtualBox): porty przemianowane na WAN i LAN, bez komentarzy."""
    r = poll("mikrotik-chr")
    assert r.driver == MikrotikDriver.name
    s = r.system
    assert (s.kind, s.vendor, s.model, s.firmware) == ("gateway", "MikroTik", "x86 innotek GmbH VirtualBox", "7.18.2")
    assert r.health.cpu_percent == 0.0  # hrProcessorLoad jednego rdzenia
    assert r.health.mem_total_kb == 524288 and r.health.mem_used_percent == 39.7  # „main memory” z hrStorage
    ifs = by_name(r)
    assert (ifs["WAN"].role, ifs["WAN"].label, ifs["WAN"].speed_mbps) == ("wan", "WAN", 100)
    assert (ifs["LAN"].role, ifs["LAN"].label) == ("lan", "LAN")  # przemianowany port Ethernet
    assert ifs["lo"].hidden
    assert {i.name for i in r.visible_interfaces()} == {"WAN", "LAN"}


MT = "1.3.6.1.4.1.14988.1.1"


def metrics_of(result) -> dict[tuple[str, str], float]:
    return {(m.name, m.key): m.value for m in result.metrics}


def test_mikrotik_sensors_from_gauge_table():
    """Tabela czujników RouterOS 7 (mtxrGaugeTable, oficjalny MIKROTIK-MIB 7.25.1): napięcie w dV, temperatura w °C."""
    m = metrics_of(poll("mikrotik-hex"))
    assert m == {("voltage_v", "voltage"): 24.1, ("temp_c", "cpu-temperature"): 46.0}


def test_mikrotik_poe_and_sfp():
    """hEX S: PoE na ether5 (mtxrPOETable) i moduł SFP (mtxrOpticalTable); pusta klatka sfp2 jest pomijana."""
    r = poll_with(
        "mikrotik-hex",
        **{
            f"{MT}.15.1.1.2.5": b"ether5",
            f"{MT}.15.1.1.3.5": 3,  # poweredOn
            f"{MT}.15.1.1.4.5": 238,  # 23,8 V
            f"{MT}.15.1.1.5.5": 152,  # mA
            f"{MT}.15.1.1.6.5": 36,  # 3,6 W
            f"{MT}.19.1.1.2.6": b"sfp1",
            f"{MT}.19.1.1.3.6": 0,
            f"{MT}.19.1.1.4.6": 0,
            f"{MT}.19.1.1.6.6": 41,  # °C
            f"{MT}.19.1.1.7.6": 3292,  # mV
            f"{MT}.19.1.1.9.6": -5871,  # 1/1000 dBm
            f"{MT}.19.1.1.10.6": -7340,
            f"{MT}.19.1.1.13.6": 1,
            f"{MT}.19.1.1.2.7": b"sfp2",
            f"{MT}.19.1.1.13.7": 0,
        },
    )
    m = metrics_of(r)
    assert (m[("poe_state", "ether5")], m[("poe_voltage_v", "ether5")], m[("poe_power_w", "ether5")]) == (3, 23.8, 3.6)
    assert m[("sfp_rx_dbm", "sfp1")] == -7.34 and m[("sfp_tx_dbm", "sfp1")] == -5.871
    assert (m[("sfp_temp_c", "sfp1")], m[("sfp_voltage_v", "sfp1")], m[("sfp_rx_loss", "sfp1")]) == (41, 3.292, 0)
    assert not [k for k in m if k[1] == "sfp2"]


def test_mikrotik_old_health_scalars_without_gauge_table():
    """Starsze płyty bez tabeli czujników: pojedyncze wartości w dziesiątych częściach; zera (brak czujnika) pomijane."""
    r = poll_with("mikrotik-chr", **{f"{MT}.3.10.0": 412, f"{MT}.3.8.0": 240, f"{MT}.3.17.0": 4200, f"{MT}.3.15.0": 1})
    assert metrics_of(r) == {
        ("temp_c", "temperature"): 41.2,
        ("voltage_v", "voltage"): 24.0,
        ("fan_rpm", "fan1-speed"): 4200,
        ("sensor_state", "psu1-state"): 1,
    }


def test_mikrotik_chr_has_no_sensors():
    assert poll("mikrotik-chr").metrics == []  # maszyna wirtualna: same zera w mtxrHealth


@pytest.mark.parametrize(
    ("name", "wan"),
    [("WAN", True), ("wan1", True), ("ether1-wan", True), ("Internet-LTE", True), ("LAN", False), ("swan", False), ("wanda", False)],
)
def test_mikrotik_wan_by_interface_name(name, wan):
    r = poll_with("mikrotik-chr", **{"1.3.6.1.2.1.31.1.1.1.1.2": name.encode(), "1.3.6.1.2.1.2.2.1.2.2": name.encode()})
    assert (by_name(r)[name].role == "wan") is wan


def test_tplink_jetstream_switch():
    r = poll("tplink-jetstream")
    assert r.driver == OmadaDriver.name
    assert (r.system.kind, r.system.vendor, r.system.model) == ("switch", "TP-Link", "SG2008P")
    ports = [i for i in r.visible_interfaces() if i.role == "port"]
    assert [p.label for p in ports] == [f"Port {n}" for n in range(1, 10)]
    ifs = by_name(r)
    assert ifs["gi1/0/1"].alias == "AP salon" and ifs["gi1/0/5"].speed_mbps == 100
    assert ifs["gi1/0/2"].oper_status == "down"
    assert ifs["vlan1"].hidden and ifs["lag1"].label == "LAG 1" and not ifs["lag1"].hidden


def test_tplink_switch_health_poe_and_sfp_from_official_mib():
    r = poll("tplink-jetstream")
    assert r.system.firmware == "1.0.4 Build 20240531 Rel.61923"
    assert (r.health.cpu_percent, r.health.mem_used_percent) == (12.0, 43.0)
    m = {(s.name, s.key): s.value for s in r.metrics}
    # PoE: indeks = numer portu → nazwa interfejsu (panel łączy PoE z portem po nazwie); 0,1 W i 0,1 V
    assert m[("poe_power_w", "gi1/0/1")] == 6.5 and m[("poe_voltage_v", "gi1/0/1")] == 53.2
    # Stan TP-Link (0 wył., 2 zasila, 3 przeciążenie) w skali panelu wspólnej z MikroTikiem (1 wył., 3 zasila, 4 przeciążenie)
    assert (m[("poe_state", "gi1/0/1")], m[("poe_state", "gi1/0/2")], m[("poe_state", "gi1/0/4")]) == (3.0, 1.0, 4.0)
    # DDM: wartości tekstowe, port „1/0/9” → gi1/0/9
    assert m[("sfp_rx_dbm", "gi1/0/9")] == -7.83 and m[("sfp_tx_dbm", "gi1/0/9")] == -2.51
    assert (m[("sfp_temp_c", "gi1/0/9")], m[("sfp_voltage_v", "gi1/0/9")]) == (35.2, 3.29)
    assert (m[("sfp_rx_loss", "gi1/0/9")], m[("sfp_tx_fault", "gi1/0/9")]) == (0.0, 0.0)


@pytest.mark.parametrize(
    ("raw", "power", "expected"),
    [(b"-7.83", True, -7.83), (b"35.2 C", False, 35.2), (b"--", True, None), (b"0.5012 mW", True, -3.0), (b"", False, None)],
)
def test_tplink_ddm_number(raw, power, expected):
    from netpulse.drivers.omada import ddm_number

    assert ddm_number(raw, power) == expected


def test_tplink_ddm_flag():
    from netpulse.drivers.omada import ddm_flag

    assert [ddm_flag(x) for x in (b"No", b"Normal", b"Yes", b"Loss", b"1", b"0", b"?", None)] == [0.0, 0.0, 1.0, 1.0, 1.0, 0.0, None, None]


def test_tplink_omada_gateway_wan_vlans():
    r = poll("tplink-er7206")
    assert r.driver == OmadaDriver.name
    assert (r.system.kind, r.system.model) == ("gateway", "ER7206")
    ifs = by_name(r)
    assert (ifs["eth0.10"].role, ifs["eth0.10"].label) == ("wan", "WAN 1")
    assert (ifs["eth0.20"].role, ifs["eth0.20"].label) == ("wan", "WAN 2")
    assert (ifs["br-lan"].role, ifs["br-lan"].label) == ("lan", "LAN")
    assert {i.name for i in r.visible_interfaces()} == {"eth0.10", "eth0.20", "br-lan"}
    assert r.metrics == []  # bramy nie mają tabel PoE/DDM switchy


@pytest.mark.parametrize(
    ("descr", "kind"),
    [
        (b"ER605 Omada Gigabit VPN Router", "gateway"),
        (b"ER707-M2", "gateway"),
        (b"Omada Multi-Gigabit VPN Router ER8411", "gateway"),
        (b"ER7212PC Omada 3-in-1 Gigabit VPN Router", "gateway"),
        (b"DR3650v", "gateway"),
        (b"SG3428X-M2 JetStream 24-Port", "switch"),
        (b"EAP650 Wi-Fi 6 Access Point", "ap"),
    ],
)
def test_tplink_device_kind_by_model(descr, kind):
    r = poll_with("tplink-jetstream", **{"1.3.6.1.2.1.1.1.0": descr})
    assert r.system.kind == kind


def test_tplink_access_point_and_detection():
    ap = poll_with("tplink-jetstream", **{"1.3.6.1.2.1.1.1.0": b"EAP245 AC1750 Ceiling Mount Dual-Band Wi-Fi Access Point"})
    assert ap.system.kind == "ap" and ap.system.model == "EAP245"

    omada = SystemInfo(descr="Omada Controller managed device")
    assert detect_driver(omada) is OmadaDriver
    assert detect_driver(SystemInfo(object_id="1.3.6.1.4.1.11863.5.45")) is OmadaDriver
    assert detect_driver(SystemInfo(object_id="1.3.6.1.4.1.14988.1", descr="RouterOS hEX")) is MikrotikDriver
    assert detect_driver(SystemInfo(descr="RouterOS CHR")) is MikrotikDriver
    assert detect_driver(SystemInfo(descr="Cisco IOS Software")) is GenericDriver
    assert detect_driver(SystemInfo(descr="Linux srv 6.1.0", object_id="1.3.6.1.4.1.8072.3.2.10")) is LinuxDriver


def test_forced_driver_on_generic_data_does_not_crash():
    for driver in ("mikrotik", "omada"):
        r = poll("ucg-ultra", driver=driver)  # wymuszony sterownik na obcym urządzeniu: bez wyjątku, tylko ubogie dane
        assert r.driver == driver and r.interfaces


def test_opnsense_router():
    """OPNsense 26.7 w VirtualBox (prawdziwy zrzut 13.11.2026): zwykły FreeBSD z net-snmp, bez własnego MIB-u."""
    r = poll("opnsense")
    assert r.driver == OpnsenseDriver.name
    s = r.system
    assert (s.kind, s.vendor, s.model, s.firmware) == ("gateway", "OPNsense", "OPNsense", "26.7")
    ifs = by_name(r)
    # WAN = interfejs trasy domyślnej (em1), nie pierwszy port; reszta kart to LAN
    assert (ifs["em1"].role, ifs["em1"].label) == ("wan", "WAN")
    assert [(ifs[n].role, ifs[n].label) for n in ("em0", "em2", "em3")] == [("lan", "em0"), ("lan", "em2"), ("lan", "em3")]
    assert {i.name for i in r.visible_interfaces()} == {"em0", "em1", "em2", "em3"}
    for hidden in ("lo0", "enc0", "pfsync0", "pflog0"):
        assert ifs[hidden].hidden and ifs[hidden].role == "system"
    assert ifs["em1"].counter_bits == 64 and ifs["em1"].speed_mbps == 1000 and ifs["em1"].oper_status == "up"
    assert r.health.cpu_percent == 2.0 and r.health.mem_total_kb == 2045492 and r.health.load1 == 0.56
    assert [d.mount for d in r.disks] == ["/"]  # zbiory ZFS (/tmp, /var/log, /home…) dzielą jedną pulę
    assert r.server is not None and r.server.processes == 80


def test_opnsense_detection():
    descr = "FreeBSD fw.lan 15.1-RELEASE-p6 FreeBSD 15.1-RELEASE-p6 stable/26.7-n284285-1633399de9dd SMP amd64"
    agent = "1.3.6.1.4.1.8072.3.2.8"
    assert detect_driver(SystemInfo(descr=descr, object_id=agent)) is OpnsenseDriver  # po gałęzi jądra, nie nazwie hosta
    assert parse_series(descr) == "26.7"
    # Czysty FreeBSD (releng/…, stable/15) to nie OPNsense
    plain = "FreeBSD nas 15.1-RELEASE FreeBSD 15.1-RELEASE releng/15.1-n280000-0123456789ab GENERIC amd64"
    assert detect_driver(SystemInfo(descr=plain, object_id=agent)) is GenericDriver
    assert parse_series("FreeBSD b 15.1-STABLE FreeBSD 15.1-STABLE stable/15-n281000-abcdef012345 GENERIC amd64") is None
    assert parse_series(None) is None


def test_opnsense_without_default_route_has_no_wan():
    data = parse_snmprec((FIXTURES / "opnsense.snmprec").read_text())
    del data["1.3.6.1.2.1.4.21.1.2.0.0.0.0"]
    client = SnmprecClient(data)
    r = asyncio.run(poll_device(client))
    assert not [i for i in r.interfaces if i.role == "wan"]
    assert by_name(r)["em1"].role == "lan"
