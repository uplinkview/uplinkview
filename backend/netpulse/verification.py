"""Potwierdzenie danych (od 0.64.0): które źródła danych sprawdzono na prawdziwym sprzęcie, a które tylko
na danych testowych (zrzuty syntetyczne, atrapy API).

Specyfikacja: „System musi pokazywać, które dane zostały rzeczywiście potwierdzone”. Panel pokazuje plakietkę przy
urządzeniu (najsłabszy poziom jego źródeł) i pełną listę w Ustawienia → System.

**Gdy źródło zostanie sprawdzone na prawdziwym urządzeniu (zanonimizowany zrzut w tests/fixtures), zmień tu jego
poziom i opis** – to jedyne miejsce z tą wiedzą.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Level = Literal["verified", "partial", "test"]
_ORDER = {"verified": 2, "partial": 1, "test": 0}


@dataclass(frozen=True)
class Source:
    id: str
    label: str
    level: Level
    note: str
    drivers: tuple[str, ...] = ()  # urządzenia z tymi driverami korzystają z tego źródła

    def as_dict(self) -> dict:
        d = asdict(self)
        d["drivers"] = list(self.drivers)
        return d


SOURCES: tuple[Source, ...] = (
    Source(
        "snmp_ifmib",
        "SNMP: porty, ruch, błędy (IF-MIB), CPU i RAM (UCD-SNMP-MIB)",
        "verified",
        "UniFi UCG Ultra, USW Lite 8 PoE, U6+ i MikroTik RouterOS 7.18 (CHR)",
        ("generic", "unifi", "mikrotik", "omada", "linux", "opnsense"),
    ),
    Source(
        "unifi_snmp",
        "UniFi przez SNMP: WAN/LAN bramy, sieci WiFi (VAP), zajętość kanału",
        "verified",
        "UCG Ultra, USW Lite 8 PoE, U6+",
        ("unifi",),
    ),
    Source(
        "unifi_api",
        "Kontroler UniFi: PoE, klienci WiFi, VPN, opóźnienie łączy WAN",
        "verified",
        "UCG Ultra, UniFi Network 10.x",
        ("unifi", "unifi_api"),
    ),
    Source(
        "unifi_api_devices",
        "Urządzenia UniFi bez SNMP (oficjalne API, np. USW Flex)",
        "verified",
        "zanonimizowane odpowiedzi kontrolera UniFi Network 10.6",
        ("unifi_api",),
    ),
    Source(
        "mikrotik_system",
        "MikroTik: system, porty i rozpoznanie WAN",
        "verified",
        "RouterOS 7.18.2 (CHR w VirtualBox)",
        ("mikrotik",),
    ),
    Source(
        "mikrotik_hw",
        "MikroTik: czujniki, PoE, SFP, kilka rdzeni",
        "test",
        "zrzut syntetyczny według oficjalnego MIKROTIK-MIB 7.25.1 – czeka na fizyczny routerboard",
        ("mikrotik",),
    ),
    Source(
        "omada_snmp",
        "TP-Link Omada / JetStream przez SNMP: CPU, RAM, PoE, SFP, WAN bramy",
        "test",
        "zrzuty syntetyczne według oficjalnych MIB TP-Link – czeka na prawdziwy sprzęt",
        ("omada",),
    ),
    Source(
        "linux_snmp",
        "Serwer Linux przez SNMP (snmpd): dyski, obciążenie",
        "test",
        "zrzut syntetyczny odwzorowujący snmpd – czeka na zrzut z prawdziwego serwera",
        ("linux",),
    ),
    Source(
        "opnsense_snmp",
        "OPNsense przez SNMP: rozpoznanie routera, WAN z trasy domyślnej, CPU, RAM, dysk",
        "verified",
        "OPNsense 26.7 (FreeBSD 15.1) w VirtualBox, wtyczka os-net-snmp",
        ("opnsense",),
    ),
    Source(
        "opnsense_api",
        "OPNsense API: bramy z pomiarem, wersja i aktualizacje, usługi, DHCP i ARP",
        "verified",
        "OPNsense 26.7.9 w VirtualBox (dnsmasq DHCP, brama monitorowana przez dpinger); VPN bez sesji",
        ("opnsense",),
    ),
    Source(
        "agent",
        "Agent UplinkView (Linux): CPU, RAM, dyski, Docker, usługi, SMART",
        "verified",
        "instalowany i sprawdzany na Ubuntu w teście CI każdej wersji",
        ("agent",),
    ),
    Source(
        "proxmox",
        "Proxmox VE: węzły, maszyny VM i LXC, magazyny, kopie vzdump",
        "partial",
        "PVE 9.1 / 9.2 z jednym węzłem; klaster kilku węzłów tylko na atrapie API",
        ("proxmox",),
    ),
    Source(
        "dual_wan",
        "Dual WAN: drugie łącze i przełączanie",
        "verified",
        "UCG Ultra (UniFi OS 6.0.17) z internetem mobilnym jako WAN 2: awaria WAN 1, praca na GSM i powrót "
        "(11.11.2026); zrzut kontrolera unifi_gateway_dual_wan.json",
    ),
    Source(
        "checks",
        "Sprawdzenia dostępności: ping, HTTP(S), TCP, DNS",
        "verified",
        "pomiar wykonuje sam UplinkView",
    ),
)

BY_ID = {s.id: s for s in SOURCES}


def for_driver(driver: str | None) -> list[Source]:
    return [s for s in SOURCES if driver and driver in s.drivers]


def device_level(driver: str | None) -> Level:
    """Najsłabszy poziom źródeł urządzenia (MikroTik: system potwierdzony, czujniki nie → `partial`)."""
    levels = [s.level for s in for_driver(driver)]
    if not levels:
        return "verified"  # brak opisanych źródeł (np. przyszły driver) – nie straszymy plakietką
    if all(lv == "verified" for lv in levels):
        return "verified"
    if all(lv == "test" for lv in levels):
        return "test"
    return "partial"
