"""Wykrywanie urządzeń w podsieci (od 0.73.0, część A z `docs/24-wykrywanie-propozycja.md`).

Każdy adres podsieci dostaje jedno zapytanie SNMP GET o gałąź `system` (krótki limit czasu, bez powtórzeń,
ograniczona równoległość). Kto odpowie, dostaje driver wybrany tak jak przy odczycie (`detect_driver`) i model / rodzaj
z danych `system` (`enrich_system` drivera, bez odczytu portów). Nic nie jest dodawane samo – wyniki trafiają do listy,
z której użytkownik wybiera urządzenia (w domu SNMP mają też drukarki, NAS-y i telewizory).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass

from .drivers import PollResult, SystemInfo, detect_driver
from .drivers.generic import read_system
from .snmp import SnmpClient, SnmpCredentials, SnmpError

log = logging.getLogger(__name__)

MAX_HOSTS = 1024  # /22 – większa podsieć to raczej pomyłka (i kilka minut skanu)
CONCURRENCY = 64
TIMEOUT_S = 1.0


class DiscoveryError(ValueError):
    """Zły zakres do skanu (komunikat dla użytkownika)."""


@dataclass
class Found:
    host: str
    name: str | None
    descr: str | None
    object_id: str | None
    vendor: str | None
    model: str | None
    firmware: str | None
    kind: str
    driver: str
    # Pełne wsparcie = driver producenta; ogólny driver też działa (porty, ruch), ale bez szczegółów
    generic: bool
    device_id: int | None = None  # już w UplinkView

    def as_dict(self) -> dict:
        return asdict(self)


def hosts_of(network: str) -> list[str]:
    """Adresy do skanu: podsieć CIDR (`192.168.1.0/24`), zakres (`192.168.1.10-192.168.1.40`) albo jeden adres."""
    text = network.strip()
    try:
        if "-" in text:
            first_s, last_s = (p.strip() for p in text.split("-", 1))
            first = ipaddress.IPv4Address(first_s)
            last = ipaddress.IPv4Address(last_s) if "." in last_s else ipaddress.IPv4Address(f"{first_s.rsplit('.', 1)[0]}.{last_s}")
            if last < first:
                raise DiscoveryError("Koniec zakresu jest przed jego początkiem")
            count = int(last) - int(first) + 1
            if count > MAX_HOSTS:
                raise DiscoveryError(f"Za duży zakres: {count} adresów (najwięcej {MAX_HOSTS})")
            return [str(ipaddress.IPv4Address(int(first) + i)) for i in range(count)]
        net = ipaddress.IPv4Network(text, strict=False)
    except DiscoveryError:
        raise
    except ValueError as exc:
        raise DiscoveryError(f"Nieprawidłowa podsieć: {text} (np. 192.168.1.0/24)") from exc
    if net.num_addresses > MAX_HOSTS + 2:
        raise DiscoveryError(f"Za duża podsieć: /{net.prefixlen} (najwięcej /22, {MAX_HOSTS} adresów)")
    hosts = [str(h) for h in net.hosts()] if net.num_addresses > 1 else [str(net.network_address)]
    return hosts


def suggest_network(addresses: Iterable[str | None]) -> str | None:
    """Podsieć /24 do skanu: najczęstsza wśród adresów urządzeń, a bez nich – adres przeglądarki (prywatny IPv4)."""
    counts: dict[str, int] = {}
    for a in addresses:
        try:
            ip = ipaddress.IPv4Address((a or "").strip())
        except ValueError:
            continue
        if not ip.is_private or ip.is_loopback or ip.is_link_local:
            continue
        net = str(ipaddress.IPv4Network(f"{ip}/24", strict=False))
        counts[net] = counts.get(net, 0) + 1
    return max(counts, key=lambda n: counts[n]) if counts else None


# Numery producentów (IANA Private Enterprise Numbers) – nazwa dla urządzeń na driverze ogólnym
ENTERPRISES = {
    "2": "IBM", "9": "Cisco", "11": "HP", "171": "D-Link", "236": "Samsung", "311": "Microsoft", "367": "Ricoh",
    "674": "Dell", "1248": "Epson", "1602": "Canon", "1916": "Extreme Networks", "2011": "Huawei", "2435": "Brother",
    "2636": "Juniper", "3375": "F5", "4413": "Broadcom", "4526": "Netgear", "6876": "VMware",
    "8072": None, "10002": "Ubiquiti (AirOS)", "11863": "TP-Link", "12356": "Fortinet", "12325": "FreeBSD (pfSense/OPNsense)",
    "14823": "Aruba", "14988": "MikroTik", "18334": "Konica Minolta", "24681": "QNAP", "25053": "Ruckus", "25506": "H3C",
    "30065": "Arista", "41112": "Ubiquiti", "44641": "Ubiquiti",
}


def vendor_of(object_id: str | None) -> str | None:
    """Producent z `sysObjectID` (1.3.6.1.4.1.<numer>…); net-snmp (8072) nic nie mówi o producencie."""
    parts = (object_id or "").lstrip(".").split(".")
    if len(parts) > 6 and parts[:6] == ["1", "3", "6", "1", "4", "1"]:
        return ENTERPRISES.get(parts[6])
    return None


def describe(host: str, system: SystemInfo) -> Found:
    """Driver, producent, model i rodzaj z samej gałęzi `system` – tak, jak wybierze je kolektor."""
    driver_cls = detect_driver(system)
    driver = driver_cls()
    # Driver ogólny nie zna producenta („Generic”) – nazwa z numeru producenta w sysObjectID, jeśli go znamy
    system.vendor = system.vendor or (vendor_of(system.object_id) if driver.name == "generic" else driver.vendor)
    result = PollResult(driver=driver.name, system=system)
    try:
        driver.enrich_system(result)
    except Exception:  # noqa: BLE001 – rozpoznanie bez portów nie może zepsuć skanu
        log.debug("%s: enrich_system bez portów", host, exc_info=True)
    return Found(
        host=host,
        name=system.name,
        descr=system.descr,
        object_id=system.object_id,
        vendor=system.vendor,
        model=system.model,
        firmware=system.firmware,
        kind=system.kind,
        driver=driver.name,
        generic=driver.name == "generic",
    )


ClientFactory = Callable[[str], SnmpClient]


async def discover(hosts: list[str], creds: SnmpCredentials, port: int = 161) -> list[Found]:
    """Skan z wybraną metodą: v1/v2c – jedno gniazdo dla całej podsieci, v3 – klienci pysnmp po kilka naraz
    (każdy z własnym silnikiem USM, więc więcej naraz tylko spowalnia)."""
    if creds.version in ("1", "2c"):
        systems = await scan_community(hosts, creds, port)
        found = [describe(h, s) for h, s in systems.items() if s.descr or s.name or s.object_id]
        found.sort(key=lambda f: ipaddress.IPv4Address(f.host))
        return found
    return await scan(hosts, default_client_factory(creds, port, timeout=2.0), concurrency=8)


def default_client_factory(creds: SnmpCredentials, port: int = 161, timeout: float = TIMEOUT_S) -> ClientFactory:
    from .snmp.client import PySnmpClient

    return lambda host: PySnmpClient(host, creds, port=port, timeout=timeout, retries=0)


async def _one(host: str, factory: ClientFactory) -> Found | None:
    client = factory(host)
    try:
        system = await read_system(client)
    except (SnmpError, OSError, TimeoutError):
        return None
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
    if system.descr is None and system.name is None and system.object_id is None:
        return None
    return describe(host, system)


_SYSTEM_OIDS = ("1.3.6.1.2.1.1.1.0", "1.3.6.1.2.1.1.2.0", "1.3.6.1.2.1.1.3.0", "1.3.6.1.2.1.1.5.0")


def _system_from(values: dict) -> SystemInfo:
    from .snmp import as_int, as_str

    uptime = as_int(values.get("1.3.6.1.2.1.1.3.0"))
    oid = as_str(values.get("1.3.6.1.2.1.1.2.0"))
    return SystemInfo(
        name=as_str(values.get("1.3.6.1.2.1.1.5.0")),
        descr=as_str(values.get("1.3.6.1.2.1.1.1.0")),
        object_id=oid.lstrip(".") if oid else None,
        uptime_s=uptime / 100.0 if uptime is not None else None,
    )


class _Collector(asyncio.DatagramProtocol):
    def __init__(self, decode) -> None:
        self.decode = decode
        self.answers: dict[str, dict] = {}

    def datagram_received(self, data: bytes, addr) -> None:  # noqa: D401
        try:
            values = self.decode(data)
        except Exception:  # noqa: BLE001 – obca albo uszkodzona odpowiedź
            return
        if values is not None:
            self.answers.setdefault(addr[0], values)


async def scan_community(hosts: list[str], creds: SnmpCredentials, port: int = 161, wait_s: float = 2.0, rounds: int = 2) -> dict[str, SystemInfo]:
    """SNMP v1/v2c: jedno gniazdo UDP, zapytanie GET o `system` do każdego adresu, odpowiedzi zbierane przez `wait_s`
    (dwie rundy – druga tylko do milczących). Cała /24 trwa kilka sekund i nie tworzy setek klientów SNMP."""
    from pyasn1.codec.ber import decoder, encoder
    from pysnmp.proto import api

    from .snmp.client import _convert

    mod = api.PROTOCOL_MODULES[api.SNMP_VERSION_1 if creds.version == "1" else api.SNMP_VERSION_2C]

    def request(req_id: int) -> bytes:
        pdu = mod.GetRequestPDU()
        mod.apiPDU.set_defaults(pdu)
        mod.apiPDU.set_request_id(pdu, req_id)
        mod.apiPDU.set_varbinds(pdu, [(oid, mod.Null("")) for oid in _SYSTEM_OIDS])
        msg = mod.Message()
        mod.apiMessage.set_defaults(msg)
        mod.apiMessage.set_community(msg, creds.community)
        mod.apiMessage.set_pdu(msg, pdu)
        return encoder.encode(msg)

    def decode(data: bytes) -> dict | None:
        msg, _ = decoder.decode(data, asn1Spec=mod.Message())
        if str(mod.apiMessage.get_community(msg)) != creds.community:
            return None
        pdu = mod.apiMessage.get_pdu(msg)
        if int(mod.apiPDU.get_error_status(pdu)):
            return {}
        out = {}
        for name, value in mod.apiPDU.get_varbinds(pdu):
            v = _convert(value)
            if v is not None:
                out[str(name)] = v
        return out

    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(lambda: _Collector(decode), local_addr=("0.0.0.0", 0))
    try:
        for _ in range(rounds):
            pending = [h for h in hosts if h not in proto.answers]
            if not pending:
                break
            for i, host in enumerate(pending):
                try:
                    transport.sendto(request(10_000 + i), (host, port))
                except OSError:
                    continue
                if i % 32 == 31:
                    await asyncio.sleep(0.005)  # bez zalewania sieci (i bufora gniazda)
            await asyncio.sleep(wait_s)
    finally:
        transport.close()
    return {h: _system_from(v) for h, v in proto.answers.items() if v}


async def scan(hosts: list[str], factory: ClientFactory, concurrency: int = CONCURRENCY, deadline_s: float = 120.0) -> list[Found]:
    """Odpytuje adresy klientami SNMP (najwyżej `concurrency` naraz; SNMPv3, testy), zwraca odpowiadające SNMP w kolejności adresów."""
    sem = asyncio.Semaphore(concurrency)
    end = time.monotonic() + deadline_s

    async def guarded(host: str) -> Found | None:
        async with sem:
            left = end - time.monotonic()
            if left <= 0:
                return None
            try:
                return await asyncio.wait_for(_one(host, factory), timeout=min(left, 10.0))
            except TimeoutError:
                return None

    results = await asyncio.gather(*(guarded(h) for h in hosts))
    found = [r for r in results if r is not None]
    found.sort(key=lambda f: ipaddress.IPv4Address(f.host))
    return found


def default_name(f: Found) -> str:
    """Nazwa nowego urządzenia: `sysName`, a bez niej model i adres."""
    return (f.name or "").strip()[:128] or f"{f.model or f.vendor or 'Urządzenie'} {f.host}"[:128]
