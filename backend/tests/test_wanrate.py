"""Prędkość WAN co 5 s (od 0.85.0): rozkład bajtów na przedziały, zapis i jedna linia wykresu – bez bazy."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace

from netpulse import aggregates, wanrate
from netpulse.api.metrics import merge_fine
from netpulse.api.schemas import Point
from netpulse.snmp import SnmpError
from netpulse.wanrate import SlotTracker, WanPort, WanSampler

MBPS = 1_000_000 / 8  # bajtów na sekundę przy 1 Mb/s


def feed(tracker: SlotTracker, key, rates_mbps: list[float], start: float = 1000.0, step: float = 1.0, read: float = 0.25) -> list:
    """Licznik odświeżany co `step` s (0,1 s po pełnej sekundzie), odczyt co `read` s; `rates_mbps[i]` to prędkość
    w i-tym odcinku. Zwraca gotowe przedziały."""
    edges = [start + 0.1 + i * step for i in range(len(rates_mbps) + 1)]
    totals = [0]
    for rate in rates_mbps:
        totals.append(totals[-1] + int(rate * MBPS * step))
    out = []
    ts = start
    while ts <= edges[-1] + read:
        n = sum(1 for e in edges if e <= ts)
        tracker.add(key, ts, totals[min(n, len(totals)) - 1] if n else 0)
        out += tracker.ready(key)
        ts += read
    return out


def mbps(slots) -> list[float | None]:
    return [None if v is None else round(v / 1e6) for _, v in slots]


def test_download_shows_real_speed_and_duration():
    """Pobieranie 800 Mb/s przez 20 s między ruchem 1 Mb/s: cztery przedziały ok. 800 Mb/s, reszta ok. 1 Mb/s – nie średnia."""
    slots = feed(SlotTracker(), "wan", [1.0] * 10 + [800.0] * 20 + [1.0] * 10)
    assert [s for s, _ in slots][:8] == list(range(1000, 1040, 5))
    values = mbps(slots)[:8]
    assert values[0] <= 2 and values[1] <= 20
    assert all(760 <= v <= 840 for v in values[2:6])  # 20 s pobierania – prędkość i czas trwania
    assert values[6] <= 40 and values[7] <= 2


def test_bytes_are_conserved_with_slow_counter_refresh():
    """Licznik odświeżany co 3 s: bajty dzielą się na przedziały według czasu, suma się zgadza (bez „0, potem podwójnie”)."""
    slots = feed(SlotTracker(), "wan", [100.0] * 10, step=3.0)
    inner = [v for _, v in slots[1:-1]]
    assert len(inner) >= 3 and all(v is not None and 80 < v / 1e6 < 120 for v in inner)


def test_slot_not_aligned_with_counter_is_known_only_when_covered():
    tracker = SlotTracker()
    tracker.add("wan", 1002.0, 0)  # pierwsza zmiana w środku przedziału 1000–1005
    tracker.add("wan", 1007.0, int(5 * 10 * MBPS))
    tracker.add("wan", 1011.0, int(9 * 10 * MBPS))
    slots = tracker.ready("wan")
    assert [s for s, _ in slots] == [1000, 1005]
    assert slots[0][1] is None  # 1000–1002 bez danych – przedział niepełny
    assert round(slots[1][1] / 1e6) == 10


def test_gap_reset_and_impossible_speed_leave_slots_empty():
    tracker = SlotTracker()
    tracker.add("wan", 1000.0, 0)
    tracker.add("wan", 1100.0, int(100 * MBPS))  # przerwa ponad minutę – nie wiadomo, kiedy szły bajty
    tracker.add("wan", 1105.0, 10)  # reset licznika
    tracker.add("wan", 1110.0, 10 + int(5 * 5000 * MBPS), max_bps=1.1e9)  # 5 Gb/s na porcie 1 Gb/s
    assert all(v is None for _, v in tracker.ready("wan"))
    base = 10 + int(5 * 5000 * MBPS)
    for k in range(1, 61):  # potem zwykły ruch 50 Mb/s, odczyt co 0,25 s
        tracker.add("wan", 1110.0 + k * 0.25, base + int(k * 0.25 * 50 * MBPS))
    assert mbps(tracker.ready("wan"))[-1] == 50


def test_full_speed_with_counter_refreshed_every_second_keeps_all_bytes():
    """Licznik bramy odświeżany co ~1 s (z drganiem), odczyt co 0,5 s, 900 Mb/s na porcie 1 Gb/s: dwie zmiany licznika
    bywają widoczne 0,5 s od siebie (chwilowo „1,8 Gb/s”). Do 0.85.0 te odcinki były odrzucane i przedziały puste –
    test prędkości na VPS zgubił 1 GB z 1,6 GB (14.11.2026). Teraz każdy przedział jest i suma bajtów się zgadza."""
    import random

    rnd = random.Random(1)
    rate = 900e6 / 8
    t0 = 1000.0
    updates, u = [], t0 + 0.3
    while u < t0 + 60:
        updates.append(u)
        u += 1.0 + rnd.uniform(-0.25, 0.25)
    tracker = SlotTracker()
    slots = []
    for k in range(121):
        ts = t0 + k * 0.5
        seen = [x for x in updates if x <= ts]
        tracker.add("wan", ts, int(rate * (seen[-1] - t0)) if seen else 0, 64, 1.1e9)
        slots += tracker.ready("wan")
    assert len(slots) >= 10 and all(v is not None for _, v in slots)
    assert all(700e6 < v < 1.1e9 for _, v in slots[1:])
    total = sum(v for _, v in slots) * 5 / 8
    assert abs(total - rate * 5 * len(slots)) / (rate * 5 * len(slots)) < 0.05


def test_rows_wait_for_both_directions():
    sampler = WanSampler(client_factory=None, interval=1)
    sampler._pending = {(7, 1000): {"at": 1006.0, "in": 8e8}, (7, 995): {"at": 1001.0, "in": 1e6, "out": 2e5}}
    rows = sampler.take_rows(1007.0)
    assert rows == [{"time": datetime.fromtimestamp(995, UTC), "interface_id": 7, "in_bps": 1e6, "out_bps": 2e5}]
    # drugi kierunek się nie pojawił – po 20 s zapis z jednym
    rows = sampler.take_rows(1030.0)
    assert rows == [{"time": datetime.fromtimestamp(1000, UTC), "interface_id": 7, "in_bps": 8e8, "out_bps": None}]


def test_silent_router_does_not_slow_down_sampling_of_others():
    class Client:
        def __init__(self, alive: bool) -> None:
            self.alive, self.reads, self.octets = alive, 0, 0

        async def get(self, oids):
            self.reads += 1
            if not self.alive:
                raise SnmpError("timeout")
            self.octets += 1000
            return {oid: self.octets for oid in oids}

        async def close(self) -> None:
            pass

    clients = {1: Client(alive=True), 2: Client(alive=False)}
    sampler = WanSampler(client_factory=lambda target: clients[target.id], interval=1)
    port = (WanPort(50, 5, 1000, 6),)
    sampler._targets = {dev_id: (SimpleNamespace(id=dev_id, name=f"r{dev_id}"), port) for dev_id in clients}
    sampler._targets_at = time.monotonic()  # lista portów świeża – bez pytania bazy
    written = []

    async def write(rows):
        written.extend(rows)

    sampler.write = write  # type: ignore[method-assign]

    async def go() -> None:
        for _ in range(5):
            await sampler.sample()

    asyncio.run(go())
    assert clients[1].reads == 5
    assert clients[2].reads == 1  # jedna próba, potem przerwa
    assert wanrate.READ_TIMEOUT_S < 1 and wanrate.BACKOFF_S >= 10


def test_fine_buckets_only_for_wan_traffic():
    assert aggregates.bucket_seconds(15, fine=True) == 5
    assert aggregates.bucket_seconds(60, fine=True) == 15
    assert aggregates.bucket_seconds(60) == 30  # inne źródła – jak dotąd
    assert aggregates.bucket_seconds(1440, fine=True) == aggregates.bucket_seconds(1440) == 300
    assert aggregates.bucket_seconds(10080, fine=True) == 3600


def test_one_line_from_fine_rates_with_average_where_missing():
    t = [datetime.fromtimestamp(1000 + 15 * k, UTC) for k in range(4)]
    points = [Point(time=t[0], values={"in_bps": 2e6, "out_bps": 1e6, "in_errors": 0.0}), Point(time=t[2], values={"in_bps": 30e6, "out_bps": 2e6, "in_errors": 1.0})]
    merged = merge_fine(points, {t[1]: (800e6, 20e6), t[2]: (750e6, None)})
    assert [p.time for p in merged] == t[:3]
    assert [p.values["in_bps"] for p in merged] == [2e6, 800e6, 750e6]
    assert merged[2].values["out_bps"] == 2e6  # brak pomiaru wysyłania – średnia
    assert merged[1].values["in_errors"] is None
    assert merge_fine(points, {}) == points


def test_constant_full_speed_gives_flat_line():
    """Stałe 850 Mb/s, licznik co 1 s, odczyt co 0,25 s: przedziały blisko 850 (pobieranie 75 GB pokazywało do 984 przy 0,5 s)."""
    slots = feed(SlotTracker(), "wan", [850.0] * 120)
    values = [v for v in mbps(slots)[1:-1] if v is not None]
    assert len(values) >= 20 and all(800 <= v <= 900 for v in values)
