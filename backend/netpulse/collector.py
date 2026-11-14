"""Kolektor: cyklicznie odpytuje urządzenia i zapisuje metryki."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from . import ifindex, wan_links
from .config import settings
from .db import Session
from .db.models import (
    NON_SNMP_DRIVERS,
    Device,
    DeviceMetric,
    DiskMetric,
    Interface,
    InterfaceMetric,
    Metric,
    ServerMetric,
    WifiMetric,
    WifiNetwork,
)
from .drivers import PollResult, poll_device
from .modules import ensure_modules, is_enabled
from .peaks import PeakSampler
from .rates import CounterTracker, rate_factor, sample_times, wait_for_slot
from .snmp import SnmpClient, SnmpCredentials, SnmpError

log = logging.getLogger("netpulse.collector")
# Stan interfejsu, którego nie ma w ostatnim odczycie (ifOperStatus notPresent = 6 w IF-MIB)
NOT_PRESENT = "notPresent"


@dataclass(frozen=True)
class DeviceTarget:
    id: int
    name: str
    host: str
    port: int
    driver: str
    credentials: SnmpCredentials


def credentials_for(device: Device) -> SnmpCredentials:
    return SnmpCredentials(
        version=device.snmp_version,  # type: ignore[arg-type]
        community=device.community or "public",
        username=device.v3_username,
        auth_protocol=device.v3_auth_protocol,  # type: ignore[arg-type]
        auth_key=device.v3_auth_key,
        priv_protocol=device.v3_priv_protocol,  # type: ignore[arg-type]
        priv_key=device.v3_priv_key,
        context_name=device.v3_context or "",
    )


# Przyrosty (błędy, odrzucone pakiety) to liczby z całego przedziału – przy podziale próbki trafiają tylko do ostatniej
# części, żeby suma się zgadzała. Szybkości i stan dotyczą każdej części.
_COUNTS = frozenset({"in_errors", "out_errors", "in_discards", "out_discards"})


def spread(values: dict, slots: list[datetime]) -> list[tuple[datetime, dict]]:
    """Wiersze próbki: jeden na każdą część przedziału (`rates.sample_times`), przyrosty w ostatnim."""
    if len(slots) == 1:
        return [(slots[0], values)]
    head = {k: (None if k in _COUNTS or k.endswith("_max") else v) for k, v in values.items()}
    return [(at, head) for at in slots[:-1]] + [(slots[-1], values)]


def make_client(target: DeviceTarget) -> SnmpClient:
    from .snmp.client import PySnmpClient

    return PySnmpClient(
        target.host,
        target.credentials,
        port=target.port,
        timeout=settings.snmp_timeout,
        retries=settings.snmp_retries,
    )


class Collector:
    def __init__(self, client_factory=make_client, alert_engine=None, peaks: PeakSampler | None = None) -> None:
        self.alert_engine = alert_engine
        # Szczyt ruchu portów WAN mierzony między cyklami (od 0.70.0); None = bez pomiaru (testy, polecenia CLI)
        self.peaks = peaks
        self.tracker = CounterTracker()
        # Ostatni stan łącza każdego portu: odczyt z chwili, gdy łącze padło albo wróciło, nie liczy się (od 0.54.4)
        self._oper: dict[tuple, str] = {}
        self.client_factory = client_factory
        self._clients: dict[int, tuple[DeviceTarget, SnmpClient]] = {}
        self._last_uptime: dict[int, float] = {}
        # Nazwa portu pod każdym ifIndex: inna nazwa = przesunięte numery (np. po aktualizacji firmware),
        # liczniki pod tym numerem należą do innego portu – zaczynamy od nowa
        self._if_names: dict[tuple[int, int], str] = {}
        # Chwila poprzedniego odczytu liczników urządzenia – początek przedziału następnej próbki
        self._read_at: dict[int, float] = {}

    # --- pętla główna -----------------------------------------------------------

    async def run_forever(self) -> None:
        log.info("Kolektor start: interwał %ss, odczyty równo z zegarem", settings.poll_interval)
        first = True
        while True:
            # Pierwszy cykl od razu (stan urządzeń po starcie), kolejne o pełnych wielokrotnościach interwału (od 0.71.0)
            if not first:
                await asyncio.sleep(wait_for_slot(time.time(), settings.poll_interval))
            first = False
            try:
                await self.poll_all()
            except Exception:
                log.exception("Błąd cyklu odpytywania")
            if self.alert_engine is not None:
                try:
                    await self.alert_engine.evaluate()
                except Exception:
                    log.exception("Błąd oceny alertów")
            # Cykl dłuższy niż interwał: następny odczyt w kolejnym pełnym oknie, bez odczytu „na doczepkę” tuż po tym
            await asyncio.sleep(0.5)

    async def load_targets(self) -> list[DeviceTarget]:
        async with Session() as session:
            # Serwery z agentem same wysyłają dane (api/agents.py), węzły Proxmox czyta proxmox_collector – SNMP ich nie dotyczy
            devices = (await session.scalars(select(Device).where(Device.enabled, Device.driver.not_in(NON_SNMP_DRIVERS)))).all()
            return [
                DeviceTarget(d.id, d.name, d.host, d.port, d.driver, credentials_for(d))
                for d in devices
            ]

    async def mark_silent_agents(self, now: datetime | None = None) -> list[int]:
        """Agent, który przestał wysyłać raporty, oznacza serwer jako niedostępny (jak brak odpowiedzi SNMP)."""
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(seconds=max(90, settings.poll_interval * 3))
        ids: list[int] = []

        async def write(session) -> None:
            ids[:] = (
                await session.scalars(
                    update(Device)
                    .where(Device.driver == "agent", Device.enabled, Device.status == "up", Device.last_ok_at < cutoff)
                    .values(status="down", last_polled_at=now, last_error="Agent nie przysyła danych")
                    .returning(Device.id)
                )
            ).all()
            session.add_all(DeviceMetric(time=now, device_id=i, reachable=False) for i in ids)
            # Dalej milczy: werdykt „down” jest świeży, dopóki kolektor go potwierdza (bez tego po kilku cyklach
            # serwer pokazałby „nieznany” zamiast „nie odpowiada” – freshness.py)
            await session.execute(
                update(Device)
                .where(Device.driver == "agent", Device.enabled, Device.status == "down", Device.last_ok_at < cutoff)
                .values(last_polled_at=now)
            )

        await _write_with_retry(write)
        for i in ids:
            log.warning("Urządzenie %s: agent nie przysyła danych", i)
        return ids

    async def poll_all(self) -> None:
        try:
            if await is_enabled("agents"):
                await self.mark_silent_agents()
        except Exception:
            log.exception("Błąd sprawdzania agentów")
        targets = await self.load_targets()
        active = {t.id for t in targets}
        for dev_id in [d for d in self._clients if d not in active]:
            await self._drop_client(dev_id)
        if not targets:
            log.info("Brak urządzeń do odpytania – dodaj je: uplinkview device add")
            return
        sem = asyncio.Semaphore(settings.poll_concurrency)

        async def guarded(t: DeviceTarget) -> None:
            async with sem:
                await self.poll_one(t)

        await asyncio.gather(*(guarded(t) for t in targets))

    async def _client(self, target: DeviceTarget) -> SnmpClient:
        cached = self._clients.get(target.id)
        if cached and cached[0] == target:
            return cached[1]
        if cached:
            await self._drop_client(target.id)
        client = self.client_factory(target)
        self._clients[target.id] = (target, client)
        return client

    async def _drop_client(self, dev_id: int) -> None:
        cached = self._clients.pop(dev_id, None)
        if cached:
            await cached[1].close()

    # --- jedno urządzenie --------------------------------------------------------

    async def poll_one(self, target: DeviceTarget) -> PollResult | None:
        started = time.monotonic()
        now = datetime.now(UTC)
        limit = settings.effective_poll_timeout
        try:
            client = await self._client(target)
            # Limit czasu całego odczytu (od 0.77.0): wolne urządzenie z setkami interfejsów nie wstrzymuje już cyklu
            # wszystkich urządzeń (poll_all czeka na każde) – po limicie jest „nie odpowiada” z wyjaśnieniem
            result = await asyncio.wait_for(poll_device(client, target.driver), limit or None)
            # Chwila odczytu liczników: środek odpytywania. Liczy się od niej przepływ – początek odpytywania przesuwał
            # przedział o czas odpowiedzi urządzenia, który bywa różny w kolejnych cyklach (od 0.71.0)
            read_ts = now.timestamp() + (time.monotonic() - started) / 2
        except TimeoutError:
            error = f"Odczyt SNMP trwał dłużej niż {limit:g} s – urządzenie odpowiada za wolno albo ma bardzo dużo interfejsów"
            log.warning("%s (%s): %s", target.name, target.host, error)
            await self._drop_client(target.id)
            await self.save_failure(target, now, error)
            return None
        except (SnmpError, OSError) as exc:
            log.warning("%s (%s): brak odpowiedzi – %s", target.name, target.host, exc)
            await self._drop_client(target.id)
            await self.save_failure(target, now, str(exc))
            return None
        except Exception as exc:
            log.exception("%s (%s): błąd odczytu", target.name, target.host)
            await self.save_failure(target, now, f"{type(exc).__name__}: {exc}")
            return None
        poll_ms = (time.monotonic() - started) * 1000
        try:
            await self.save_result(target, result, now, poll_ms, read_ts)
        except Exception as exc:
            # Dane, których baza nie przyjęła, nie mogą przerwać cyklu pozostałych urządzeń (od 0.77.0)
            log.exception("%s (%s): błąd zapisu odczytu", target.name, target.host)
            await self.save_failure(target, now, f"Błąd zapisu odczytu: {type(exc).__name__}")
            return None
        log.debug(
            "%s: %d interfejsów, %d sieci WiFi, %.0f ms",
            target.name,
            len(result.interfaces),
            len(result.wifi),
            poll_ms,
        )
        return result

    async def save_failure(self, target: DeviceTarget, now: datetime, error: str) -> None:
        async def write(session) -> None:
            await session.execute(
                update(Device)
                .where(Device.id == target.id)
                .values(status="down", last_polled_at=now, last_error=error[:2000])
            )
            session.add(DeviceMetric(time=now, device_id=target.id, reachable=False))
            await wan_links.mark_unknown(session, target.id, now)

        await _write_with_retry(write)

    def compute_rates(self, dev_id: int, result: PollResult, ts: float) -> tuple[dict, dict]:
        """Liczy przepływy przed zapisem (żeby ponowienie zapisu nie psuło liczników)."""
        if_rates: dict[int, dict] = {}
        # Interfejs, którego nie ma w odczycie (VPN bez sesji, wyjęty moduł): po powrocie pierwsza próbka bez ruchu
        present = {i.if_index for i in result.interfaces}
        for key in [k for k in self._oper if k[0] == dev_id and k[1] == "if" and k[2] not in present]:
            self._oper[key] = NOT_PRESENT
        for i in result.interfaces:
            key = (dev_id, "if", i.if_index)
            prev_name = self._if_names.get((dev_id, i.if_index))
            self._if_names[(dev_id, i.if_index)] = i.name
            if prev_name is not None and prev_name != i.name:
                self.tracker.forget(lambda k, key=key: k[:3] == key)
                self._oper.pop(key, None)
            factor = rate_factor(i.if_type)
            values = {
                "in_bps": self.tracker.bps(key + ("in",), ts, i.in_octets, i.counter_bits, i.speed_mbps, factor),
                "out_bps": self.tracker.bps(key + ("out",), ts, i.out_octets, i.counter_bits, i.speed_mbps, factor),
            }
            # Łącze padło albo wróciło (router potrafi wtedy wyzerować liczniki) albo reset widać tylko w jednym kierunku –
            # drugi kierunek też jest niepewny: ta próbka bez ruchu (stan łącza zostaje), od następnej liczymy od nowa
            prev_oper = self._oper.get(key)
            self._oper[key] = i.oper_status
            changed = prev_oper is not None and prev_oper != i.oper_status
            # Od 0.71.0 także niemożliwa szybkość w jednym kierunku: router „dogania” zatrzymane liczniki i drugi kierunek
            # z tego samego odczytu też jest zawyżony (12.11.2026: pobieranie > 1 Gb/s odrzucone, wysyłanie 75,9 Mb/s
            # na łączu 50 Mb/s przeszło i zawyżyło średnią 5 minut z 1,6 do 9,2 Mb/s)
            suspect = any(self.tracker.was_reset(key + (d,)) or self.tracker.was_rejected(key + (d,)) for d in ("in", "out"))
            if changed or suspect:
                values["in_bps"] = values["out_bps"] = None
            for field in ("in_errors", "out_errors", "in_discards", "out_discards"):
                res = self.tracker.update(key + (field,), ts, getattr(i, field), 32)
                values[field] = res[0] if res else None
            if self.peaks is not None:
                # Zawsze odbieramy (zeruje okno); zapisujemy tylko przy wiarygodnej średniej. Szczyt nie może być
                # niższy od średniej z całego cyklu – okna szczytu i cyklu nie pokrywają się co do sekundy.
                for field, peak in zip(("in_bps", "out_bps"), self.peaks.take(dev_id, i.if_index), strict=True):
                    if peak is not None and values[field] is not None:
                        values[f"{field}_max"] = max(peak, values[field])
            if changed or any(v is not None for v in values.values()):
                values["oper_up"] = i.oper_status == "up"
                if_rates[i.if_index] = values
        wifi_rates: dict[str, dict] = {}
        for w in result.wifi:
            key = (dev_id, "wifi", w.key)
            wifi_rates[w.key] = {
                "clients": w.clients,
                "rx_bps": self.tracker.bps(key + ("rx",), ts, w.rx_octets, w.counter_bits),
                "tx_bps": self.tracker.bps(key + ("tx",), ts, w.tx_octets, w.counter_bits),
            }
        return if_rates, wifi_rates

    async def save_result(
        self, target: DeviceTarget, result: PollResult, now: datetime, poll_ms: float, read_ts: float | None = None
    ) -> None:
        ts = now.timestamp() if read_ts is None else read_ts
        sysinfo = result.system
        dev_id = target.id
        # Próbki ruchu zapisujemy w środku przedziału, który opisują (od 0.71.0) – patrz rates.sample_times
        slots = [datetime.fromtimestamp(s, UTC) for s in sample_times(self._read_at.get(dev_id), ts, float(settings.poll_interval))]
        self._read_at[dev_id] = ts

        # Restart urządzenia (uptime spadł) – liczniki zaczynają od zera
        if sysinfo.uptime_s is not None:
            prev = self._last_uptime.get(dev_id)
            if prev is not None and sysinfo.uptime_s < prev:
                log.info("%s: wykryto restart urządzenia", target.name)
                self.tracker.forget(lambda k: k[0] == dev_id)
            self._last_uptime[dev_id] = sysinfo.uptime_s

        if_rates, wifi_rates = self.compute_rates(dev_id, result, ts)

        async def write(session) -> None:
            await session.execute(
                update(Device)
                .where(Device.id == dev_id)
                .values(
                    status="up",
                    last_polled_at=now,
                    last_ok_at=now,
                    last_error=None,
                    detected_driver=result.driver,
                    kind=sysinfo.kind,
                    # Długość kolumn (od 0.77.0): sysName czy wersja z agenta potrafi być dłuższa – bez przycięcia
                    # baza odrzucała cały zapis urządzenia
                    vendor=_cut(sysinfo.vendor, 64),
                    model=_cut(sysinfo.model, 64),
                    firmware=_cut(sysinfo.firmware, 64),
                    sys_name=_cut(sysinfo.name, 255),
                    sys_descr=sysinfo.descr,
                    sys_object_id=_cut(sysinfo.object_id, 255),
                    uptime_s=sysinfo.uptime_s,
                )
            )

            if result.interfaces:
                # Przesunięte numery ifIndex: wiersz portu (historia, łącza WAN, widgety) idzie za nazwą
                moved = await ifindex.follow_names(session, dev_id, {i.if_index: i.name[:128] for i in result.interfaces})
                if moved:
                    log.info("%s: zmiana numeracji interfejsów – przeniesione %d, odstawione %d", target.name, len(moved.moves), len(moved.parked))
                # Port ustawiony jako łącze WAN (np. LAN 4 jako WAN 2) liczy się jak WAN: ruch WAN, „Na żywo”, alerty
                wan_ports = await wan_links.configured(session, dev_id)
                rows = [
                    {
                        "device_id": dev_id,
                        "if_index": i.if_index,
                        "name": i.name[:128],
                        "descr": (i.descr or "")[:255] or None,
                        "alias": (i.alias or "")[:255] or None,
                        "label": (i.label if i.role == "wan" or i.if_index not in wan_ports else wan_ports[i.if_index])[:128],
                        "if_type": i.if_type,
                        "mac": i.mac,
                        "role": "wan" if i.if_index in wan_ports else i.role,
                        "hidden": i.hidden,
                        "admin_up": i.admin_up,
                        "oper_status": i.oper_status,
                        "speed_mbps": i.speed_mbps,
                        "last_seen_at": now,
                    }
                    for i in sorted(result.interfaces, key=lambda x: x.if_index)
                ]
                stmt = insert(Interface).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["device_id", "if_index"],
                    set_={c: stmt.excluded[c] for c in rows[0] if c not in ("device_id", "if_index")},
                ).returning(Interface.id, Interface.if_index)
                ids = {row.if_index: row.id for row in await session.execute(stmt)}
                session.add_all(
                    InterfaceMetric(time=at, interface_id=ids[idx], **part)
                    for idx, values in if_rates.items()
                    for at, part in spread(values, slots)
                )
                await wan_links.record(session, dev_id, now, result, if_rates, ids)
                # Interfejs zniknął z odczytu (np. WireGuard bramy między połączeniami): stan „nieobecny” zamiast
                # ostatniego „działa”; bez próbek, więc nie ma alertu „port nie działa” ani fałszywego ruchu
                await session.execute(
                    update(Interface)
                    .where(Interface.device_id == dev_id, Interface.if_index.not_in(list(ids)), Interface.oper_status != NOT_PRESENT)
                    .values(oper_status=NOT_PRESENT)
                )

            if result.wifi:
                rows = [
                    {
                        "device_id": dev_id,
                        "key": w.key[:64],
                        "ssid": w.ssid[:64],
                        "radio": w.radio,
                        "channel": w.channel,
                        "bssid": w.bssid,
                        "hidden": w.hidden,
                        "clients": w.clients,
                        "last_seen_at": now,
                    }
                    for w in sorted(result.wifi, key=lambda x: x.key)
                ]
                stmt = insert(WifiNetwork).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["device_id", "key"],
                    set_={c: stmt.excluded[c] for c in rows[0] if c not in ("device_id", "key")},
                ).returning(WifiNetwork.id, WifiNetwork.key)
                wifi_ids = {row.key: row.id for row in await session.execute(stmt)}
                session.add_all(
                    WifiMetric(time=at, wifi_id=wifi_ids[key[:64]], **part)
                    for key, values in wifi_rates.items()
                    for at, part in spread(values, slots)
                )

            if result.disks:
                session.add_all(
                    DiskMetric(time=now, device_id=dev_id, mount=d.mount, total_bytes=d.total_bytes, used_bytes=d.used_bytes)
                    for d in result.disks
                )
            if result.server is not None:
                session.add(
                    ServerMetric(
                        time=now,
                        device_id=dev_id,
                        swap_used_percent=result.server.swap_used_percent,
                        processes=result.server.processes,
                    )
                )

            if result.metrics:
                session.add_all(
                    Metric(time=now, device_id=dev_id, name=m.name[:64], key=m.key[:255], value=m.value)
                    for m in {(m.name, m.key[:255]): m for m in result.metrics}.values()
                )

            h = result.health
            session.add(
                DeviceMetric(
                    time=now,
                    device_id=dev_id,
                    reachable=True,
                    poll_ms=round(poll_ms, 1),
                    uptime_s=sysinfo.uptime_s,
                    cpu_percent=h.cpu_percent,
                    mem_used_percent=h.mem_used_percent,
                    load1=h.load1,
                )
            )

        await _write_with_retry(write)


def _cut(value: str | None, size: int) -> str | None:
    return value[:size] if value else value


def _is_retryable(exc: DBAPIError) -> bool:
    code = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(
        getattr(getattr(exc, "orig", None), "__cause__", None), "sqlstate", None
    )
    return code in ("40P01", "40001") or "deadlock detected" in str(exc)


async def _write_with_retry(write, attempts: int = 5) -> None:
    """Zapis w transakcji z ponowieniem przy deadlocku (np. tworzenie nowego chunka Timescale)."""
    for attempt in range(1, attempts + 1):
        try:
            async with Session() as session, session.begin():
                await write(session)
            return
        except DBAPIError as exc:
            if attempt == attempts or not _is_retryable(exc):
                raise
            log.debug("Konflikt zapisu (próba %d) – ponawiam", attempt)
            await asyncio.sleep(0.05 * attempt + random.random() * 0.1)


async def run() -> None:
    from .alerts import AlertEngine
    from .checks_collector import ChecksCollector
    from .db import init_db
    from .notifications import Notifier
    from .opnsense_collector import OpnsenseCollector
    from .proxmox_collector import ProxmoxCollector
    from .sysinfo import SystemCollector
    from .unifi_collector import UnifiCollector

    await init_db()
    await ensure_modules()
    engine = AlertEngine(notifier=Notifier())
    await engine.ensure_default_rules()
    peaks = PeakSampler()
    await asyncio.gather(Collector(alert_engine=engine, peaks=peaks).run_forever(), peaks.run_forever(), UnifiCollector().run_forever(), SystemCollector().run_forever(), ProxmoxCollector().run_forever(),
                         OpnsenseCollector().run_forever(), ChecksCollector().run_forever())
