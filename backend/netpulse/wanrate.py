"""Prawdziwa prędkość łączy WAN co 5 sekund (od 0.85.0): wykres ruchu WAN rysuje ją jedną linią.

Kolektor czyta liczniki co 30 s, a wykres 24 h uśrednia je do 5 minut – pobieranie z prędkością 800 Mb/s przez 20 s
wyglądało jak ~55 Mb/s. Ten moduł czyta same liczniki portów WAN co `interval` (domyślnie 0,5 s; jedno małe zapytanie
SNMP na router) i zapisuje prędkość w każdym 5-sekundowym przedziale (`wan_rate_metrics`, przedziały równo z zegarem:
:00, :05, :10 …). Wykres bierze z tej tabeli najwyższą prędkość w kubełku (`api/metrics.fine_series`) – na krótkim
zakresie i po przybliżeniu kubełek ma 5–15 s, więc widać i prędkość, i czas trwania pobierania.

Bajty przypisujemy przedziałom według *zmian* licznika, nie odczytów: urządzenia odświeżają liczniki SNMP co sekundę
albo rzadziej (UCG Ultra: ok. 1 s, zmierzone 12.11.2026), a odczyt tej samej wartości dwa razy dałby „0, potem
podwójnie”. Przyrost między dwiema zmianami dzielimy na przedziały proporcjonalnie do czasu, więc suma bajtów się
zgadza przy każdym tempie odświeżania. Przedział zapisujemy, gdy jest w całości pokryty zmianami licznika; luka
(router nie odpowiadał, reset licznika, prędkość ponad możliwości łącza) zostawia go pustym – wykres ma tam zwykłą
średnią z 30 s. Licznik zużycia transferu dalej liczy bajty z `interface_metrics`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .config import settings
from .db import Session
from .db.models import NON_SNMP_DRIVERS, Device, Interface, WanRateMetric
from .rates import counter_delta, rate_factor
from .snmp import SnmpClient, SnmpError, as_int
from .snmp import oids as O

log = logging.getLogger("netpulse.wanrate")

SLOT_S = 5  # długość przedziału zapisu
# Zapas czasu przy sprawdzaniu „ponad możliwości łącza”: licznik odświeża się co ok. 1 s, a zmianę widzimy przy odczycie
# co 0,5 s – dwie zmiany mogą wyglądać na 0,5 s od siebie, choć bajty szły przez sekundę (prędkość ×2). Bez zapasu
# test prędkości 900 Mb/s na porcie 1 Gb/s gubił przedziały (VPS 14.11.2026: 600 MB zamiast 1645 MB w 5 minutach).
JITTER_S = 1.5
MAX_GAP_S = 60.0  # dłuższa przerwa między zmianami licznika = nie wiemy, kiedy szły bajty – przedziały zostają puste
KEEP_SLOTS_S = 300.0  # niedokończone przedziały starsze niż to zapominamy
WRITE_AFTER_S = 20.0  # przedział z jednym kierunkiem (drugi nieznany) zapisujemy po tym czasie
TARGETS_TTL = 60.0  # jak często odświeżać listę portów WAN z bazy
# Odczyt co pół sekundy nie może czekać jak zwykłe odpytywanie (2 s i ponowienie): zgubiony pakiet nadrobi następny odczyt
READ_TIMEOUT_S = 0.8
# Router, który nie odpowiada, pomijamy na pół minuty – inaczej jego limit czasu wstrzymywałby odczyt pozostałych
BACKOFF_S = 30.0


def make_client(target) -> SnmpClient:
    """Klient SNMP próbnika: krótki limit czasu, bez ponowień."""
    from .snmp.client import PySnmpClient

    return PySnmpClient(target.host, target.credentials, port=target.port, timeout=READ_TIMEOUT_S, retries=0)


@dataclass
class _Counter:
    last: tuple[float, int] | None = None  # (czas zauważenia ostatniej zmiany, wartość licznika)
    slots: dict[int, list[float]] = field(default_factory=dict)  # początek przedziału → [bajty, pokryte sekundy]


class SlotTracker:
    """Bajty licznika rozłożone na przedziały `slot_s`; `ready` oddaje przedziały w całości pokryte zmianami licznika."""

    def __init__(self, slot_s: int = SLOT_S, max_gap_s: float = MAX_GAP_S) -> None:
        self.slot_s = slot_s
        self.max_gap_s = max_gap_s
        self._counters: dict[Hashable, _Counter] = {}

    def add(self, key: Hashable, ts: float, octets: int | None, bits: int = 64, max_bps: float | None = None) -> None:
        if octets is None:
            return
        c = self._counters.setdefault(key, _Counter())
        if c.last is not None and octets == c.last[1]:
            return  # licznik jeszcze się nie odświeżył
        prev, c.last = c.last, (ts, octets)
        if prev is None or ts <= prev[0] or ts - prev[0] > self.max_gap_s:
            return
        delta = counter_delta(prev[1], octets, bits)
        if delta is None:
            return  # reset urządzenia – liczymy od następnej zmiany
        span = ts - prev[0]
        if max_bps and delta * 8 > max_bps * (span + JITTER_S):
            return  # ponad możliwości łącza nawet z zapasem – błąd licznika; przedziały zostają puste
        start = int(prev[0] // self.slot_s) * self.slot_s
        while start < ts:
            overlap = min(ts, start + self.slot_s) - max(prev[0], start)
            if overlap > 0:
                slot = c.slots.setdefault(start, [0.0, 0.0])
                slot[0] += delta * overlap / span
                slot[1] += overlap
            start += self.slot_s

    def ready(self, key: Hashable) -> list[tuple[int, float | None]]:
        """Przedziały zakończone przed ostatnią zmianą licznika: (początek, b/s) albo (początek, None) – niepełne dane."""
        c = self._counters.get(key)
        if c is None or c.last is None:
            return []
        known_until = c.last[0]
        out: list[tuple[int, float | None]] = []
        for start in sorted(s for s in c.slots if s + self.slot_s <= known_until):
            octets, covered = c.slots.pop(start)
            out.append((start, octets * 8 / self.slot_s if covered >= self.slot_s - 0.01 else None))
        for start in [s for s in c.slots if known_until - s > KEEP_SLOTS_S]:
            del c.slots[start]
        return out

    def forget(self, predicate) -> None:
        for key in [k for k in self._counters if predicate(k)]:
            del self._counters[key]


@dataclass(frozen=True)
class WanPort:
    interface_id: int
    if_index: int
    speed_mbps: int | None
    if_type: int | None


class WanSampler:
    """Pętla w kolektorze: co `interval` sekund liczniki portów WAN każdego routera SNMP, zapis co 5 s.
    `interval <= 0` wyłącza pomiar – wykres ruchu ma wtedy samą średnią z 30 s."""

    def __init__(self, client_factory=make_client, interval: float | None = None) -> None:
        self.client_factory = client_factory
        self.interval = settings.wan_sample_interval if interval is None else interval
        self.tracker = SlotTracker()
        self._skip_until: dict[int, float] = {}  # urządzenie → kiedy spróbować ponownie po braku odpowiedzi
        self._clients: dict[int, tuple[object, SnmpClient]] = {}
        self._targets: dict[int, tuple[object, tuple[WanPort, ...]]] = {}  # urządzenie → (cel SNMP, porty WAN)
        self._targets_at = 0.0
        # (port, początek przedziału) → {"in": b/s | None, "out": …, "at": kiedy pojawił się pierwszy kierunek}
        self._pending: dict[tuple[int, int], dict] = {}

    async def load_targets(self) -> dict[int, tuple[object, tuple[WanPort, ...]]]:
        from .collector import DeviceTarget, credentials_for

        async with Session() as session:
            rows = (
                await session.execute(
                    select(Device, Interface)
                    .join(Interface, Interface.device_id == Device.id)
                    .where(
                        Device.enabled,
                        Device.driver.not_in(NON_SNMP_DRIVERS),
                        Interface.role == "wan",
                        Interface.hidden.is_(False),
                        Interface.if_index > 0,
                    )
                    .order_by(Device.id, Interface.if_index)
                )
            ).all()
        out: dict[int, tuple[object, list[WanPort]]] = {}
        for d, i in rows:
            target = DeviceTarget(d.id, d.name, d.host, d.port, d.driver, credentials_for(d))
            out.setdefault(d.id, (target, []))[1].append(WanPort(i.id, i.if_index, i.speed_mbps, i.if_type))
        return {dev_id: (target, tuple(ports)) for dev_id, (target, ports) in out.items()}

    async def _client(self, target) -> SnmpClient:
        cached = self._clients.get(target.id)
        if cached and cached[0] == target:
            return cached[1]
        if cached:
            await self._drop(target.id)
        client = self.client_factory(target)
        self._clients[target.id] = (target, client)
        return client

    async def _drop(self, dev_id: int) -> None:
        cached = self._clients.pop(dev_id, None)
        if cached:
            with contextlib.suppress(Exception):
                await cached[1].close()

    async def sample_device(self, target, ports: tuple[WanPort, ...], ts: float) -> None:
        oids = [f"{O.IF_HC_IN_OCTETS}.{p.if_index}" for p in ports] + [f"{O.IF_HC_OUT_OCTETS}.{p.if_index}" for p in ports]
        try:
            client = await self._client(target)
            values = await client.get(oids)
        except (SnmpError, TimeoutError, OSError) as exc:
            log.debug("%s: brak odpowiedzi przy pomiarze prędkości WAN – %s", target.name, exc)
            await self._drop(target.id)
            self._skip_until[target.id] = time.monotonic() + BACKOFF_S
            return
        for p in ports:
            limit = p.speed_mbps * 1_000_000 * rate_factor(p.if_type) if p.speed_mbps else None
            for direction, oid in (("in", O.IF_HC_IN_OCTETS), ("out", O.IF_HC_OUT_OCTETS)):
                key = (p.interface_id, direction)
                self.tracker.add(key, ts, as_int(values.get(f"{oid}.{p.if_index}")), 64, limit)
                for start, bps in self.tracker.ready(key):
                    self._pending.setdefault((p.interface_id, start), {"at": ts})[direction] = bps

    def take_rows(self, now: float) -> list[dict]:
        """Przedziały gotowe do zapisu: oba kierunki znane albo jeden czeka dłużej niż `WRITE_AFTER_S`."""
        rows = []
        for (iface, start), v in list(self._pending.items()):
            if ("in" in v and "out" in v) or now - v["at"] > WRITE_AFTER_S:
                del self._pending[(iface, start)]
                if v.get("in") is None and v.get("out") is None:
                    continue
                rows.append({"time": datetime.fromtimestamp(start, UTC), "interface_id": iface, "in_bps": v.get("in"), "out_bps": v.get("out")})
        return rows

    async def write(self, rows: list[dict]) -> None:
        if not rows:
            return
        async with Session() as session, session.begin():
            await session.execute(insert(WanRateMetric).values(rows).on_conflict_do_nothing())

    async def sample(self) -> None:
        now = time.monotonic()
        if now - self._targets_at > TARGETS_TTL or not self._targets_at:
            self._targets = await self.load_targets()
            self._targets_at = now
            for dev_id in [d for d in self._clients if d not in self._targets]:
                await self._drop(dev_id)
            ifaces = {p.interface_id for _, ports in self._targets.values() for p in ports}
            self.tracker.forget(lambda k: k[0] not in ifaces)
        due = [(t, ports) for dev_id, (t, ports) in self._targets.items() if self._skip_until.get(dev_id, 0.0) <= now]
        await asyncio.gather(*(self.sample_device(t, ports, time.time()) for t, ports in due))
        await self.write(self.take_rows(time.time()))

    async def run_forever(self) -> None:
        if self.interval <= 0:
            log.info("Pomiar prędkości WAN co 5 s wyłączony (NETPULSE_WAN_SAMPLE_INTERVAL=0)")
            return
        log.info("Pomiar prędkości WAN: odczyt co %ss, zapis co %ss", self.interval, SLOT_S)
        while True:
            started = time.monotonic()
            try:
                await self.sample()
            except Exception:
                log.exception("Błąd pomiaru prędkości WAN")
            await asyncio.sleep(max(0.2, self.interval - (time.monotonic() - started)))
