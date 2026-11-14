"""Zużycie transferu WAN (od 0.82.0): ile bajtów pobrano i wysłano dziś i w bieżącym okresie rozliczeniowym.

Bajty z próbek ruchu portów z rolą `wan` (`interface_metrics`): każda próbka to średnia szybkość z jednego cyklu
kolektora (po pominiętym odczycie kolektor dzieli przedział na części po jednym cyklu – `rates.sample_times`), więc
suma `in_bps × poll_interval / 8` to bajty, które przeszły przez port. Przerwa w odczytach dłuższa niż 2 min to jedna
próbka (ruch z niej zaniżony) – świadomie: długość przedziału z odstępu między próbkami zawyżałaby ruch po restarcie
kolektora, gdy pierwsza próbka po starcie opisuje tylko 30 s. Starsze niż surowe dane (`retention_days`)
– z agregatu godzinowego (średnia × 3600 s), tylko pełne godziny.

Dni i okres liczone w strefie czasowej instalacji (TZ). Okres zaczyna się w dniu `reset_day` (1–28) – jak u operatora
internetu mobilnego, który liczy pakiet np. od 15. dnia miesiąca; 1 = miesiąc kalendarzowy.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .config import settings

MAX_RESET_DAY = 28  # każdy miesiąc ma ten dzień


def period_start(today: date, reset_day: int = 1) -> date:
    """Pierwszy dzień bieżącego okresu rozliczeniowego (dzień `reset_day` tego albo poprzedniego miesiąca)."""
    if not 1 <= reset_day <= MAX_RESET_DAY:
        raise ValueError(f"reset_day must be 1–{MAX_RESET_DAY}")
    if today.day >= reset_day:
        return today.replace(day=reset_day)
    prev = today.replace(day=1) - timedelta(days=1)
    return prev.replace(day=reset_day)


def next_period_start(start: date) -> date:
    """Pierwszy dzień następnego okresu (ten sam dzień miesiąca, miesiąc później)."""
    return date(start.year + (start.month == 12), start.month % 12 + 1, start.day)


def local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0), tzinfo=tz).astimezone(UTC)


@dataclass
class Totals:
    rx: float = 0.0  # pobrane (do sieci), bajty
    tx: float = 0.0  # wysłane

    def add(self, rx: float, tx: float) -> None:
        self.rx += rx
        self.tx += tx


@dataclass
class Usage:
    today: date
    start: date
    next_start: date
    # (port, dzień lokalny) → bajty
    by_day: dict[tuple[int, date], Totals] = field(default_factory=lambda: defaultdict(Totals))

    def port(self, interface_id: int, since: date | None = None) -> Totals:
        out = Totals()
        for (iid, day), v in self.by_day.items():
            if iid == interface_id and day >= (since or self.start):
                out.add(v.rx, v.tx)
        return out

    def days(self, interface_ids: set[int]) -> list[tuple[date, Totals]]:
        """Każdy dzień okresu do dziś (także bez ruchu), suma wybranych portów."""
        per: dict[date, Totals] = defaultdict(Totals)
        for (iid, day), v in self.by_day.items():
            if iid in interface_ids:
                per[day].add(v.rx, v.tx)
        out, day = [], self.start
        while day <= self.today:
            out.append((day, per.get(day, Totals())))
            day += timedelta(days=1)
        return out


_RAW_SQL = text(
    """
    SELECT interface_id, CAST(time AT TIME ZONE :tz AS date) AS day,
           coalesce(sum(in_bps), 0) * :step / 8 AS rx, coalesce(sum(out_bps), 0) * :step / 8 AS tx
    FROM interface_metrics
    WHERE interface_id = ANY(:ids) AND time >= :s AND time < :e
    GROUP BY 1, 2
    """
)
_HOURLY_SQL = text(
    """
    SELECT interface_id, CAST(bucket AT TIME ZONE :tz AS date) AS day,
           coalesce(sum(in_bps), 0) * 3600 / 8 AS rx, coalesce(sum(out_bps), 0) * 3600 / 8 AS tx
    FROM interface_metrics_1h
    WHERE interface_id = ANY(:ids) AND bucket >= :s AND bucket < :e
    GROUP BY 1, 2
    """
)


async def load(session, interface_ids: list[int], reset_day: int, timescale: bool, now: datetime | None = None) -> Usage:
    tz = ZoneInfo(settings.timezone)
    now = now or datetime.now(UTC)
    today = now.astimezone(tz).date()
    start = period_start(today, reset_day)
    usage = Usage(today=today, start=start, next_start=next_period_start(start))
    if not interface_ids:
        return usage
    since = local_midnight(start, tz)
    # Surowe próbki są tylko z `retention_days` – wcześniejsze godziny z agregatu (pełne godziny UTC)
    raw_from = since
    if timescale:
        oldest_raw = (now - timedelta(days=settings.retention_days) + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        raw_from = max(since, oldest_raw)
    queries = [(_RAW_SQL, raw_from, now)]
    if raw_from > since:
        queries.insert(0, (_HOURLY_SQL, since, raw_from))
    for sql, s, e in queries:
        params = {"ids": interface_ids, "s": s, "e": e, "tz": settings.timezone}
        if sql is _RAW_SQL:
            params["step"] = settings.poll_interval
        for row in (await session.execute(sql, params)).all():
            usage.by_day[(row.interface_id, row.day)].add(float(row.rx), float(row.tx))
    return usage
