"""Klient REST API OPNsense (od 0.81.0) – tylko odczyt (GET), klucz i sekret jako HTTP Basic.

Uzupełnia odczyt SNMP (driver `opnsense`) o to, czego SNMP nie podaje: stan bram z pomiarem `dpinger`
(opóźnienie, rozrzut, utrata pakietów), dokładną wersję i dostępną aktualizację, przypisanie interfejsów (WAN/LAN),
usługi, dzierżawy DHCP (dnsmasq albo Kea) i tablicę ARP. Parsery są czystymi funkcjami (testy na zanonimizowanych
odpowiedziach z OPNsense 26.7: `tests/fixtures/opnsense_api/*.json`). Opis: docs/46-opnsense-api.md.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

# Punkty API (OPNsense 24.7+; sprawdzone na 26.7.9)
FIRMWARE = "core/firmware/status"
GATEWAYS = "routes/gateway/status"
INTERFACES = "interfaces/overview/interfaces_info"
SERVICES = "core/service/search"
ARP = "diagnostics/interface/get_arp"
# DHCP: od 25.1 domyślnie dnsmasq, do wyboru Kea; ISC DHCP (wtyczka) ma własny punkt
LEASES = ("dnsmasq/leases/search", "kea/leases4/search", "dhcpv4/leases/search_lease")
# Ruch na adres (od 0.82.0): OPNsense próbkuje ruch interfejsu przez kilka sekund; lista identyfikatorów po przecinku
TRAFFIC_TOP = "diagnostics/traffic/top/{}"
TRAFFIC_TIMEOUT_S = 30.0  # odpowiedź trwa 3–11 s (bez ruchu – ok. 11 s i status „timeout”)

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


class OpnsenseError(Exception):
    """Błąd połączenia albo odpowiedzi API – tekst trafia do panelu (Ustawienia → OPNsense)."""


@dataclass
class Gateway:
    name: str
    address: str | None
    monitor: str | None  # adres pingowany przez dpinger; None = monitorowanie wyłączone
    status: str  # none | down | loss | delay | delay+loss (dpinger); "none" = w porządku
    up: bool | None  # None – bez monitorowania OPNsense nie wie, czy brama działa
    delay_ms: float | None
    jitter_ms: float | None
    loss_percent: float | None
    interface: str | None = None  # urządzenie (np. em1) z przypisania interfejsów – uzupełnia `link_gateways`
    default: bool = False  # interfejs bramy ma trasę domyślną (tędy idzie ruch do internetu)


@dataclass
class Iface:
    device: str  # em0, igb1, pppoe0 …
    identifier: str | None  # wan, lan, opt1 … (None = nieprzypisany)
    description: str | None  # nazwa z panelu OPNsense (WAN, LAN, Goście …)
    status: str | None  # up | down | no carrier
    link_type: str | None  # dhcp | static | pppoe …
    addr4: str | None
    gateways: list[str] = field(default_factory=list)
    default_route: bool = False


@dataclass
class Service:
    name: str
    description: str
    running: bool


@dataclass
class Host:
    """Urządzenie w sieci z DHCP albo ARP (MAC zawsze małymi literami)."""

    mac: str
    ip: str | None
    hostname: str | None
    interface: str | None  # opis interfejsu (LAN) albo urządzenie (em0)
    manufacturer: str | None
    source: str  # dhcp | arp
    expires: int | None = None  # koniec dzierżawy (unix), tylko DHCP
    # Ruch z próbki OPNsense (od 0.82.0), b/s; None = nie mierzono (adres spoza sieci LAN albo brak odczytu)
    down_bps: float | None = None
    up_bps: float | None = None


@dataclass
class Snapshot:
    version: str | None = None
    latest: str | None = None
    gateways: list[Gateway] = field(default_factory=list)
    interfaces: list[Iface] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    hosts: list[Host] = field(default_factory=list)
    dhcp: str | None = None  # z którego serwera DHCP są dzierżawy (dnsmasq | kea | isc); None = brak
    # Odczyt ruchu urządzeń (od 0.82.0): "ok", tekst błędu albo None (nie mierzono – brak sieci LAN albo uprawnień)
    traffic: str | None = None

    @property
    def update_available(self) -> bool:
        return update_available(self.version, self.latest)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["update_available"] = self.update_available
        return d


# --- parsery (czyste) ----------------------------------------------------------------------


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s != "~" else None


def parse_number(value: Any) -> float | None:
    """„12.4 ms” → 12.4, „0.0 %” → 0.0, „~” (brak pomiaru) → None."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    m = _NUMBER.search(str(value or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def parse_gateways(body: Any) -> list[Gateway]:
    items = body.get("items") if isinstance(body, dict) else body
    out: list[Gateway] = []
    for it in items or []:
        if not isinstance(it, dict) or not _text(it.get("name")):
            continue
        monitor = _text(it.get("monitor"))
        status = (_text(it.get("status")) or "none").lower()
        translated = (_text(it.get("status_translated")) or "").lower()
        if monitor is None:
            up = None
        else:
            up = not (status == "down" or translated == "offline")
        out.append(
            Gateway(
                name=str(it["name"]).strip()[:64],
                address=_text(it.get("address")),
                monitor=monitor,
                status=status,
                up=up,
                delay_ms=parse_number(it.get("delay")) if monitor else None,
                jitter_ms=parse_number(it.get("stddev")) if monitor else None,
                loss_percent=parse_number(it.get("loss")) if monitor else None,
            )
        )
    return out


def parse_interfaces(body: Any) -> list[Iface]:
    rows = body.get("rows") if isinstance(body, dict) else body
    out: list[Iface] = []
    for r in rows or []:
        if not isinstance(r, dict) or not _text(r.get("device")):
            continue
        identifier = _text(r.get("identifier"))
        routes = r.get("routes") or []
        out.append(
            Iface(
                device=str(r["device"]).strip(),
                identifier=identifier,
                description=_text(r.get("description")) if identifier else None,  # „Unassigned Interface” nic nie mówi
                status=_text(r.get("status")),
                link_type=_text(r.get("link_type")),
                addr4=_text(r.get("addr4")),
                gateways=[str(g) for g in (r.get("gateways") or []) if _text(g)],
                default_route="default" in routes if isinstance(routes, list) else False,
            )
        )
    return out


def link_gateways(gateways: list[Gateway], interfaces: list[Iface]) -> None:
    """Przypisuje bramie interfejs (urządzenie) po adresie bramy; trasa domyślna = brama w użyciu."""
    by_gw = {gw: i for i in interfaces for gw in i.gateways}
    for g in gateways:
        iface = by_gw.get(g.address) if g.address else None
        if iface is not None:
            g.interface = iface.device
            g.default = iface.default_route


def parse_services(body: Any) -> list[Service]:
    rows = body.get("rows") if isinstance(body, dict) else body
    out: list[Service] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        # `id` jest jednoznaczne (dpinger/WAN_DHCP, dpinger/:watcher:), `name` nie – dpinger jest raz na bramę
        name = _text(r.get("id")) or _text(r.get("name"))
        if not name:
            continue
        out.append(Service(name=name[:64], description=(_text(r.get("description")) or name)[:128], running=bool(int(r.get("running") or 0))))
    return out


def _mac(value: Any) -> str | None:
    s = (_text(value) or "").lower().replace("-", ":")
    return s if re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", s) else None


def parse_leases(body: Any) -> list[Host]:
    """Dzierżawy z dnsmasq, Kea albo ISC – pola różnią się nazwami, bierzemy pierwsze obecne."""
    rows = body.get("rows") if isinstance(body, dict) else body
    out: list[Host] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        mac = _mac(r.get("hwaddr") or r.get("hw_address") or r.get("mac"))
        if not mac:
            continue
        expire = r.get("expire") if r.get("expire") is not None else r.get("ends")
        out.append(
            Host(
                mac=mac,
                ip=_text(r.get("address") or r.get("ip_address") or r.get("ip")),
                hostname=_text(r.get("hostname") or r.get("client-hostname")),
                interface=_text(r.get("if_descr") or r.get("if")),
                manufacturer=_text(r.get("mac_info") or r.get("man")),
                source="dhcp",
                expires=int(expire) if isinstance(expire, int | float) else None,
            )
        )
    return out


def parse_arp(body: Any) -> list[Host]:
    out: list[Host] = []
    for r in body if isinstance(body, list) else []:
        if not isinstance(r, dict) or r.get("permanent"):  # własne adresy OPNsense
            continue
        mac = _mac(r.get("mac"))
        if not mac:
            continue
        out.append(
            Host(
                mac=mac,
                ip=_text(r.get("ip")),
                hostname=_text(r.get("hostname")),
                interface=_text(r.get("intf_description") or r.get("intf")),
                manufacturer=_text(r.get("manufacturer")),
                source="arp",
            )
        )
    return out


def merge_hosts(leases: list[Host], arp: list[Host]) -> list[Host]:
    """Jeden wiersz na MAC: dzierżawa DHCP (ma nazwę) uzupełniona o ARP; same wpisy ARP – urządzenia z adresem stałym."""
    by_mac = {h.mac: h for h in leases}
    for a in arp:
        h = by_mac.get(a.mac)
        if h is None:
            by_mac[a.mac] = a
        else:
            h.ip = h.ip or a.ip
            h.manufacturer = h.manufacturer or a.manufacturer
    return sorted(by_mac.values(), key=lambda h: tuple(int(p) for p in (h.ip or "999.0.0.0").split(".") if p.isdigit()))


def lan_interfaces(interfaces: list[Iface]) -> list[Iface]:
    """Sieci lokalne do pomiaru ruchu urządzeń: przypisane, z adresem IPv4, bez bramy i trasy domyślnej (to WAN), bez pętli."""
    return [
        i
        for i in interfaces
        if i.identifier and i.addr4 and not i.gateways and not i.default_route and not i.device.startswith("lo")
    ]


def parse_top(body: Any) -> dict[str, list[tuple[str, float, float]]]:
    """Próbka ruchu na adres: {identyfikator: [(adres, pobieranie b/s, wysyłanie b/s)]}.

    Sprawdzone na 26.7.9 (ruch w jedną stronę z licznikiem interfejsu obok): `*_in` = ruch DO adresu (pobieranie),
    `*_out` = ruch OD adresu. `cumulative_bytes_*` to bajty z jednej sekundy próbki – zgodne z licznikiem interfejsu
    w 98–100 %; `rate_bits_*` jest stale o połowę niższe (średnia z 2 s z jedną sekundą danych), więc go nie używamy.
    Status „timeout” = w czasie próbki nie było ruchu."""
    out: dict[str, list[tuple[str, float, float]]] = {}
    if not isinstance(body, dict):
        return out
    for ident, part in body.items():
        if not isinstance(part, dict):
            continue
        rows = []
        for r in part.get("records") or []:
            if not isinstance(r, dict) or not _text(r.get("address")):
                continue
            down, up = r.get("cumulative_bytes_in"), r.get("cumulative_bytes_out")
            if isinstance(down, int | float) and isinstance(up, int | float):
                rows.append((str(r["address"]).strip(), float(down) * 8, float(up) * 8))
        out[str(ident)] = rows
    return out


def apply_traffic(hosts: list[Host], lans: list[Iface], top: dict[str, list[tuple[str, float, float]]]) -> None:
    """Wpisuje ruch urządzeniom z sieci LAN, które OPNsense zmierzył; urządzenie z tej sieci bez wpisu = 0 b/s.
    Adresy spoza sieci LAN (serwery w internecie, po drugiej stronie) są pomijane."""
    nets = []
    for i in lans:
        if i.identifier in top:
            try:
                nets.append(ipaddress.ip_interface(i.addr4 or "").network)
            except ValueError:
                continue
    rates: dict[str, tuple[float, float]] = {}
    for ident in top:
        for addr, down, up in top[ident]:
            prev = rates.get(addr, (0.0, 0.0))
            rates[addr] = (prev[0] + down, prev[1] + up)
    for h in hosts:
        try:
            ip = ipaddress.ip_address(h.ip or "")
        except ValueError:
            continue
        if any(ip in n for n in nets):
            h.down_bps, h.up_bps = rates.get(str(ip), (0.0, 0.0))


def parse_firmware(body: Any) -> tuple[str | None, str | None]:
    product = body.get("product") if isinstance(body, dict) else None
    if not isinstance(product, dict):
        return None, None
    return _text(product.get("product_version")), _text(product.get("product_latest"))


def update_available(version: str | None, latest: str | None) -> bool:
    """„26.7.9_1” (poprawka pakietu) i najnowsza „26.7.9” to ta sama wersja; inna najnowsza = aktualizacja."""
    if not version or not latest:
        return False
    return version.split("_")[0] != latest.split("_")[0]


# --- klient ------------------------------------------------------------------------------------


class OpnsenseApi:
    def __init__(
        self,
        host: str,
        key: str,
        secret: str,
        *,
        port: int = 443,
        verify_tls: bool = False,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        netloc = f"[{host}]" if ":" in host else host
        self.base = f"https://{netloc}:{port}/api/" if port != 443 else f"https://{netloc}/api/"
        self._client = httpx.AsyncClient(
            auth=(key, secret), headers={"Accept": "application/json"}, verify=verify_tls, timeout=timeout, transport=transport
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, *, optional: bool = False) -> Any:
        """GET na punkt API. `optional`: brak punktu (404) albo uprawnień (403) – None zamiast błędu."""
        try:
            res = await self._client.get(self.base + path)
        except httpx.HTTPError as exc:
            raise OpnsenseError(f"Brak połączenia z OPNsense: {type(exc).__name__}: {exc}") from exc
        if res.status_code == 401:
            raise OpnsenseError("OPNsense odrzucił klucz API (sprawdź klucz i sekret)")
        if optional and res.status_code in (403, 404):
            return None
        if res.status_code == 403:
            raise OpnsenseError(f"Użytkownik klucza API nie ma uprawnień do {path}")
        if res.status_code != 200:
            raise OpnsenseError(f"OPNsense odpowiedział kodem {res.status_code} dla {path}")
        try:
            return res.json()
        except ValueError as exc:
            raise OpnsenseError("OPNsense zwrócił odpowiedź, która nie jest JSON-em") from exc

    async def snapshot(self) -> Snapshot:
        """Wszystko w jednym odczycie. Wersja i bramy są wymagane; reszta jest pomijana, gdy brak uprawnień."""
        firmware, gateways = await asyncio.gather(self.get(FIRMWARE), self.get(GATEWAYS))
        interfaces, services, arp = await asyncio.gather(
            self.get(INTERFACES, optional=True), self.get(SERVICES, optional=True), self.get(ARP, optional=True)
        )
        snap = Snapshot()
        snap.version, snap.latest = parse_firmware(firmware)
        snap.gateways = parse_gateways(gateways)
        snap.interfaces = parse_interfaces(interfaces)
        snap.services = parse_services(services)
        link_gateways(snap.gateways, snap.interfaces)
        leases: list[Host] = []
        for path, name in zip(LEASES, ("dnsmasq", "kea", "isc"), strict=True):
            rows = parse_leases(await self.get(path, optional=True))
            if rows:
                leases, snap.dhcp = rows, name
                break
        snap.hosts = merge_hosts(leases, parse_arp(arp))
        return snap

    async def read_traffic(self, snap: Snapshot) -> None:
        """Ruch urządzeń w sieciach LAN (osobno od `snapshot`, bo trwa kilka sekund). Błąd nie przerywa odczytu –
        trafia do `snap.traffic`; brak sieci LAN albo uprawnień = None (nie mierzono)."""
        lans = lan_interfaces(snap.interfaces)
        if not lans:
            return
        path = TRAFFIC_TOP.format(",".join(i.identifier or "" for i in lans))
        try:
            res = await self._client.get(self.base + path, timeout=TRAFFIC_TIMEOUT_S)
        except httpx.HTTPError as exc:
            snap.traffic = f"Brak połączenia z OPNsense: {type(exc).__name__}: {exc}"
            return
        if res.status_code in (403, 404):
            return
        if res.status_code != 200:
            snap.traffic = f"OPNsense odpowiedział kodem {res.status_code} dla {path}"
            return
        try:
            body = res.json()
        except ValueError:
            snap.traffic = "OPNsense zwrócił odpowiedź, która nie jest JSON-em"
            return
        apply_traffic(snap.hosts, lans, parse_top(body))
        snap.traffic = "ok"
