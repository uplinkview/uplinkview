"""Kolektor kontrolerów UniFi: PoE na portach switchy i klienci sieci (co cykl, razem z kolektorem SNMP).

Od 0.52.0 także urządzenia kontrolera, których UplinkView nie zna z SNMP (np. USW Flex, USW Ultra – nie mają SNMP):
zakłada je jako urządzenia `driver = "unifi_api"` i zapisuje jak wynik drivera SNMP (`unifi_devices.py`)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from . import vpn as vpn_state
from . import wan_links
from .collector import Collector, DeviceTarget, _write_with_retry
from .config import settings
from .db import Session
from .db.models import (
    ClientMetric,
    Controller,
    Device,
    DeviceMetric,
    Interface,
    KnownClient,
    Metric,
    NetworkClient,
    PoeBudgetMetric,
    PoePortMetric,
    TopologyLink,
    UnifiApiDevice,
)
from .modules import is_enabled
from .unifi import (
    GATEWAY_TYPES,
    OfficialDevice,
    Speedtest,
    UnifiApi,
    UnifiClient,
    UnifiDevice,
    UnifiError,
    WanPort,
)
from .unifi_devices import DRIVER as API_DRIVER
from .unifi_devices import build_poll_result, device_kind

log = logging.getLogger("netpulse.unifi")

# Klucz pingu bramy do serwera: interfejs łącza i serwer (`eth3 · google.com`)
WAN_PING_SEP = " · "


def wan_metrics(dev_id: int, wans: tuple[WanPort, ...], now: datetime) -> list[Metric]:
    """Pomiary łączy WAN z bramy (od 0.55.0) do ogólnej tabeli `metrics`, klucz = interfejs łącza (jak `ifName`):
    `wan_latency_ms` i `wan_availability_percent` łącza oraz `wan_ping_ms` do każdego serwera, który brama pinguje."""
    rows: list[Metric] = []
    for w in wans:
        if w.latency_ms is not None:
            rows.append(Metric(time=now, device_id=dev_id, name="wan_latency_ms", key=w.ifname, value=w.latency_ms))
        if w.availability is not None:
            rows.append(Metric(time=now, device_id=dev_id, name="wan_availability_percent", key=w.ifname, value=w.availability))
        seen: set[str] = set()
        for target, ms in w.monitors:
            key = f"{w.ifname}{WAN_PING_SEP}{target}"[:255]
            if key not in seen:
                seen.add(key)
                rows.append(Metric(time=now, device_id=dev_id, name="wan_ping_ms", key=key, value=ms))
    return rows


def speedtest_rows(dev_id: int, st: Speedtest) -> list[dict]:
    """Wynik testu prędkości bramy (od 0.70.0) do tabeli `metrics`, z czasem samego testu i kluczem = interfejs łącza.
    Prędkości w b/s (jak reszta przepustowości), żeby wykres rysował je w tej samej skali co ruch WAN."""
    when = datetime.fromtimestamp(st.ran_at, UTC)
    rows = [
        {"time": when, "device_id": dev_id, "name": "speedtest_down_bps", "key": st.ifname, "value": st.download_mbps * 1_000_000},
        {"time": when, "device_id": dev_id, "name": "speedtest_up_bps", "key": st.ifname, "value": st.upload_mbps * 1_000_000},
    ]
    if st.latency_ms is not None:
        rows.append({"time": when, "device_id": dev_id, "name": "speedtest_ping_ms", "key": st.ifname, "value": st.latency_ms})
    return rows


async def save_speedtest(session, dev_id: int, st: Speedtest, now: datetime, retention_days: int) -> None:
    """Zapisuje test raz: klucz główny (czas testu, urządzenie, nazwa, łącze) odrzuca powtórkę przy kolejnych odczytach.
    Test starszy niż retencja surowych danych pomijamy – wiersz trafiłby do usuniętego już okresu."""
    age = now.timestamp() - st.ran_at
    if age < -300 or age > (retention_days - 1) * 86400:
        return
    await session.execute(insert(Metric).values(speedtest_rows(dev_id, st)).on_conflict_do_nothing())


@dataclass(frozen=True)
class ControllerTarget:
    id: int
    name: str
    host: str
    port: int
    api_key: str
    site: str
    verify_tls: bool


def make_api(target: ControllerTarget) -> UnifiApi:
    return UnifiApi(
        target.host,
        target.api_key,
        port=target.port,
        site=target.site,
        verify_tls=target.verify_tls,
        timeout=max(5.0, settings.snmp_timeout * 3),
    )


def match_devices(devices: list[UnifiDevice], by_host: dict[str, int], by_iface_mac: dict[str, int]) -> dict[str, int]:
    """Łączy urządzenia kontrolera z urządzeniami UplinkView (SNMP): {MAC z kontrolera: id urządzenia}.

    Samo pole `ip` z kontrolera bywa mylące (brama podaje tam adres WAN), więc próbujemy po kolei:
    1) `ip` z kontrolera, 2) adresy, pod którymi widzą to urządzenie sąsiedzi w LLDP (adres w sieci LAN),
    3) adresy MAC interfejsów, które UplinkView zna z SNMP (ifPhysAddress)."""
    lan_ips: dict[str, list[str]] = {}
    for d in devices:
        for link in d.lldp:
            lan_ips.setdefault(link.remote_mac, []).extend(link.remote_ips)
    matched: dict[str, int] = {}
    for d in devices:
        for ip in [d.ip, *lan_ips.get(d.mac, [])]:
            if ip in by_host:
                matched[d.mac] = by_host[ip]
                break
        else:
            for mac in d.macs:
                if mac in by_iface_mac:
                    matched[d.mac] = by_iface_mac[mac]
                    break
    return matched


_HISTORY_FIELDS = ("is_wired", "signal_dbm", "tx_rate_kbps", "rx_rate_kbps", "uplink_device_id", "uplink_name", "uplink_port", "essid", "radio")
_KNOWN_FIELDS = ("name", "ip", "is_wired", "is_guest", "essid", "uplink_device_id", "uplink_name")


async def save_client_history(session, rows: list[dict], now: datetime) -> None:
    """Historia klientów: próbka stanu na cykl (`client_metrics`) i znani klienci (`known_clients`)."""
    await session.execute(
        insert(ClientMetric)
        .values([{"time": now, "mac": r["mac"], **{k: r[k] for k in _HISTORY_FIELDS}} for r in rows])
        .on_conflict_do_nothing()  # ten sam klient widziany przez dwa kontrolery w tej samej chwili
    )
    # Jeden wiersz na MAC (dwa kontrolery mogą widzieć tego samego klienta)
    known = {r["mac"]: {"mac": r["mac"], **{k: r[k] for k in _KNOWN_FIELDS}, "first_seen_at": now, "last_seen_at": now} for r in rows}
    stmt = insert(KnownClient).values(list(known.values()))
    # Nazwa i adres zostają z poprzedniego razu, gdy kontroler chwilowo ich nie podaje
    keep = {"name", "ip"}
    stmt = stmt.on_conflict_do_update(
        index_elements=["mac"],
        set_={
            **{k: func.coalesce(stmt.excluded[k], getattr(KnownClient, k)) if k in keep else stmt.excluded[k] for k in _KNOWN_FIELDS},
            "last_seen_at": stmt.excluded.last_seen_at,
        },
    )
    await session.execute(stmt)


def api_host(device: OfficialDevice, taken: set[str]) -> str:
    """Adres urządzenia z API (kolumna `host` jest unikalna): IP z kontrolera, a gdy zajęte albo go brak – MAC."""
    if device.ip and device.ip not in taken:
        return device.ip
    return f"unifi-{device.mac.replace(':', '')}"


class UnifiCollector:
    def __init__(self, api_factory=make_api) -> None:
        self.api_factory = api_factory
        # Zapis urządzeń z API tą samą drogą co SNMP (porty, przepływy z liczników, CPU/RAM); własny licznik przepływów
        self.saver = Collector()

    async def run_forever(self) -> None:
        log.info("Kolektor UniFi start: interwał %ss", settings.poll_interval)
        while True:
            started = time.monotonic()
            try:
                await self.poll_all()
            except Exception:
                log.exception("Błąd cyklu odpytywania kontrolerów UniFi")
            await asyncio.sleep(max(1.0, settings.poll_interval - (time.monotonic() - started)))

    async def load_targets(self) -> list[ControllerTarget]:
        async with Session() as session:
            rows = (await session.scalars(select(Controller).where(Controller.enabled))).all()
        return [ControllerTarget(c.id, c.name, c.host, c.port, c.api_key, c.site, c.verify_tls) for c in rows]

    async def poll_all(self) -> None:
        if not await is_enabled("unifi"):
            return  # moduł wyłączony (Ustawienia → Moduły)
        targets = await self.load_targets()
        if targets:
            await asyncio.gather(*(self.poll_one(t) for t in targets))

    async def poll_one(self, target: ControllerTarget) -> bool:
        now = datetime.now(UTC)
        api = self.api_factory(target)
        try:
            version = await api.app_version()
            devices, clients = await asyncio.gather(api.devices(), api.clients())
            official = await self.read_official(api, target, devices)
            vpn = await self.read_vpn(api, target)
        except UnifiError as exc:
            log.warning("%s (%s): %s", target.name, target.host, exc)
            await self.save_failure(target, now, str(exc))
            return False
        except Exception as exc:
            log.exception("%s (%s): błąd odczytu kontrolera", target.name, target.host)
            await self.save_failure(target, now, f"{type(exc).__name__}: {exc}")
            return False
        finally:
            await api.close()
        await self.save_result(target, now, version, devices, clients, vpn)
        if official is not None:
            await self.save_official(target, now, official, devices)
        return True

    async def read_vpn(self, api: UnifiApi, target: ControllerTarget):
        """Serwery, klienci i połączenia VPN (od 0.57.0). Błąd odczytu VPN nie psuje reszty odczytu kontrolera."""
        try:
            return await api.vpn()
        except UnifiError as exc:
            log.info("%s: bez danych VPN (%s)", target.name, exc)
            return None

    async def read_official(self, api: UnifiApi, target: ControllerTarget, devices: list[UnifiDevice]) -> list[OfficialDevice] | None:
        """Urządzenia do odczytu z oficjalnego API: już założone jako `unifi_api` i nowe, których nie znamy z SNMP.

        Starszy kontroler bez oficjalnego API (albo bez listy urządzeń) = None: reszta odczytu działa jak wcześniej."""
        try:
            listed = await api.official_devices()
        except UnifiError as exc:
            log.info("%s: oficjalne API bez listy urządzeń (%s) – pomijam urządzenia bez SNMP", target.name, exc)
            return None
        async with Session() as session:
            mapped = dict(
                (await session.execute(select(UnifiApiDevice.mac, UnifiApiDevice.device_id).where(UnifiApiDevice.controller_id == target.id))).all()
            )
            snmp_hosts = {
                host: dev_id
                for dev_id, host in (await session.execute(select(Device.id, Device.host).where(Device.driver != API_DRIVER))).all()
            }
            by_iface_mac = {
                mac.lower(): dev_id
                for dev_id, mac in (
                    await session.execute(
                        select(Interface.device_id, Interface.mac).join(Device).where(Interface.mac.is_not(None), Device.driver != API_DRIVER)
                    )
                ).all()
            }
        snmp = match_devices(devices, snmp_hosts, by_iface_mac)
        wanted = [
            d
            for d in listed
            if (d.mac in mapped and mapped[d.mac] is not None)  # już założone urządzenie z API
            or (d.mac not in mapped and d.mac not in snmp and d.ip not in snmp_hosts)  # nowe, nieznane z SNMP
        ]
        sem = asyncio.Semaphore(4)

        async def details(d: OfficialDevice) -> OfficialDevice:
            async with sem:
                try:
                    return await api.official_details(d)
                except UnifiError as exc:
                    log.debug("%s: brak szczegółów %s: %s", target.name, d.mac, exc)
                    return d

        return list(await asyncio.gather(*(details(d) for d in wanted)))

    async def save_official(self, target: ControllerTarget, now: datetime, official: list[OfficialDevice], devices: list[UnifiDevice]) -> None:
        """Zakłada nowe urządzenia z API i zapisuje odczyt każdego (jak wynik drivera SNMP)."""
        ids: dict[str, tuple[int, str, bool]] = {}
        legacy = {d.mac: d for d in devices}

        async def ensure(session) -> None:
            ids.clear()
            rows = {m.mac: m for m in (await session.scalars(select(UnifiApiDevice).where(UnifiApiDevice.controller_id == target.id))).all()}
            taken = set((await session.scalars(select(Device.host))).all())
            for d in official:
                row = rows.get(d.mac)
                if row is not None and row.device_id is None:
                    continue  # usunięte w panelu albo dodane przez SNMP – nie zakładamy ponownie
                if row is None:
                    host = api_host(d, taken)
                    taken.add(host)
                    device = Device(
                        name=(d.name or d.model or d.mac)[:128], host=host, port=0, driver=API_DRIVER, detected_driver=API_DRIVER,
                        kind=device_kind(d, legacy.get(d.mac)), vendor="Ubiquiti", model=(d.model or "")[:64] or None, community=None, status="unknown",
                    )  # fmt: skip
                    session.add(device)
                    await session.flush()
                    row = UnifiApiDevice(controller_id=target.id, mac=d.mac, device_id=device.id, official_id=d.id, updated_at=now)
                    session.add(row)
                    log.info("%s: nowe urządzenie z oficjalnego API %s (%s, urządzenie %d)", target.name, d.name or d.mac, d.model, device.id)
                else:
                    row.official_id, row.updated_at = d.id, now
                dev = await session.get(Device, row.device_id)
                if dev is not None:
                    ids[d.mac] = (dev.id, dev.name, dev.enabled)

        await _write_with_retry(ensure)
        for d in official:
            if d.mac not in ids:
                continue
            dev_id, name, enabled = ids[d.mac]
            if not enabled:
                continue
            if not d.online:
                await self._mark_down(dev_id, now, f"Kontroler UniFi: urządzenie {d.state or 'niedostępne'}")
                continue
            result = build_poll_result(d, legacy.get(d.mac))
            await self.saver.save_result(DeviceTarget(dev_id, name, "", 0, API_DRIVER, None), result, now, 0.0)  # type: ignore[arg-type]

    async def _mark_down(self, dev_id: int, now: datetime, error: str) -> None:
        async def write(session) -> None:
            await session.execute(update(Device).where(Device.id == dev_id).values(status="down", last_polled_at=now, last_error=error[:2000]))
            session.add(DeviceMetric(time=now, device_id=dev_id, reachable=False))

        await _write_with_retry(write)

    async def save_failure(self, target: ControllerTarget, now: datetime, error: str) -> None:
        async def write(session) -> None:
            await session.execute(
                update(Controller)
                .where(Controller.id == target.id)
                .values(status="down", last_polled_at=now, last_error=error[:2000])
            )
            # Urządzenia z oficjalnego API tego kontrolera są wtedy niedostępne (alert „urządzenie nie odpowiada”)
            ids = (
                await session.scalars(
                    select(UnifiApiDevice.device_id)
                    .join(Device, Device.id == UnifiApiDevice.device_id)
                    .where(UnifiApiDevice.controller_id == target.id, Device.enabled)
                )
            ).all()
            if ids:
                await session.execute(
                    update(Device).where(Device.id.in_(ids)).values(status="down", last_polled_at=now, last_error=f"Kontroler UniFi: {error}"[:2000])
                )
                session.add_all(DeviceMetric(time=now, device_id=i, reachable=False) for i in ids)

        await _write_with_retry(write)

    async def save_result(
        self,
        target: ControllerTarget,
        now: datetime,
        version: str | None,
        devices: list[UnifiDevice],
        clients: list[UnifiClient],
        vpn=None,
    ) -> None:
        async def write(session) -> None:
            await session.execute(
                update(Controller)
                .where(Controller.id == target.id)
                .values(
                    status="up", last_polled_at=now, last_ok_at=now, last_error=None, app_version=version
                )
            )
            # Urządzenia UplinkView (SNMP) łączymy z kontrolerem po adresie IP
            by_host = {host: dev_id for dev_id, host in (await session.execute(select(Device.id, Device.host))).all()}
            by_iface_mac = {
                mac.lower(): dev_id
                for dev_id, mac in (
                    await session.execute(select(Interface.device_id, Interface.mac).where(Interface.mac.is_not(None)))
                ).all()
            }
            by_mac = match_devices(devices, by_host, by_iface_mac)

            for d in devices:
                dev_id = by_mac.get(d.mac)
                if dev_id is None:
                    continue
                session.add_all(
                    PoePortMetric(
                        time=now,
                        device_id=dev_id,
                        port_idx=p.port_idx,
                        power_w=p.power_w,
                        voltage_v=p.voltage_v,
                        current_ma=p.current_ma,
                        poe_mode=p.poe_mode,
                        poe_class=p.poe_class,
                        delivering=p.delivering,
                    )
                    for p in d.poe_ports
                )
                if d.poe_ports and (d.poe_used_w is not None or d.poe_max_w is not None):
                    session.add(PoeBudgetMetric(time=now, device_id=dev_id, used_w=d.poe_used_w, max_w=d.poe_max_w))
                # Brama: który port WAN działa i którym idzie ruch – kolektor SNMP użyje tego w następnym cyklu
                if d.wans:
                    await wan_links.apply_controller(session, dev_id, d.wans, now)
                    session.add_all(wan_metrics(dev_id, d.wans, now))
                if d.speedtest is not None:
                    await save_speedtest(session, dev_id, d.speedtest, now, settings.retention_days)
                if d.type in GATEWAY_TYPES:
                    await wan_links.save_detected(session, dev_id, d.wans)

            # VPN: stan klientów (zdjęcie) i metryki na bramie – brama to urządzenie, które VPN obsługuje
            if vpn is not None:
                gateway = next((by_mac[d.mac] for d in devices if d.type in GATEWAY_TYPES and d.mac in by_mac), None)
                prev_vpn = await vpn_state.previous(session, target.id)
                snap = vpn_state.snapshot(*vpn, prev_vpn, now, gateway)
                if snap["servers"] or snap["users"]:
                    iface_rows = []
                    if gateway is not None:
                        # Klient jedyny na swoim interfejsie (np. tunel do VPS): prędkość z licznika SNMP interfejsu
                        ifaces = vpn_state.single_client_interfaces(snap)
                        samples = await vpn_state.interface_samples(session, gateway, ifaces, now)
                        iface_rows = vpn_state.use_interface_rates(gateway, snap, prev_vpn, samples, now)
                    await vpn_state.save(session, target.id, snap)
                    if gateway is not None:
                        session.add_all(vpn_state.metrics(gateway, snap, now) + iface_rows)

            # Topologia: zdjęcie stanu połączeń LLDP urządzeń, które znamy z SNMP
            links = [
                {
                    "controller_id": target.id,
                    "device_id": by_mac[d.mac],
                    "local_port_idx": link.local_port_idx,
                    "remote_mac": link.remote_mac,
                    "local_mac": d.mac,
                    "updated_at": now,
                }
                for d in devices
                if d.mac in by_mac
                for link in d.lldp
            ]
            await session.execute(delete(TopologyLink).where(TopologyLink.controller_id == target.id))
            if links:
                await session.execute(insert(TopologyLink).values(links).on_conflict_do_nothing())

            # Klienci: zdjęcie stanu – zniknięci z kontrolera znikają też u nas
            names = {d.mac: d.name for d in devices}
            await session.execute(
                delete(NetworkClient).where(
                    NetworkClient.controller_id == target.id, NetworkClient.mac.not_in([c.mac for c in clients] or [""])
                )
            )
            if clients:
                rows = [
                    {
                        "controller_id": target.id,
                        "mac": c.mac,
                        "name": (c.name or "")[:255] or None,
                        "ip": c.ip,
                        "is_wired": c.is_wired,
                        "is_guest": c.is_guest,
                        "essid": c.essid,
                        "radio": c.radio,
                        "signal_dbm": c.signal_dbm,
                        "tx_rate_kbps": c.tx_rate_kbps,
                        "rx_rate_kbps": c.rx_rate_kbps,
                        "uplink_device_id": by_mac.get(c.uplink_mac) if c.uplink_mac else None,
                        "uplink_name": (names.get(c.uplink_mac) or "")[:128] or None if c.uplink_mac else None,
                        "uplink_port": c.uplink_port,
                        "connected_s": c.connected_s,
                        "updated_at": now,
                    }
                    for c in clients
                ]
                stmt = insert(NetworkClient).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["controller_id", "mac"],
                    set_={k: stmt.excluded[k] for k in rows[0] if k not in ("controller_id", "mac")},
                )
                await session.execute(stmt)
                await save_client_history(session, rows, now)

        await _write_with_retry(write)
        log.debug("%s: %d urządzeń, %d klientów", target.name, len(devices), len(clients))
