"""Ciągłe agregaty TimescaleDB (godzinowe): wykresy z całego roku i dostępność urządzeń przy małej bazie.

Surowe metryki trzymamy `retention_days` (domyślnie 30 dni), agregaty godzinowe `aggregate_retention_days`
(domyślnie 2 lata). Widoki zakłada `init_db` – to obiekty TimescaleDB, nie tabele z modeli, więc nie ma ich
w migracjach Alembic. Agregaty są „na żywo” (`materialized_only = false`): ostatnia, jeszcze niezmaterializowana
godzina jest liczona z surowych danych, więc zapytanie zawsze widzi komplet.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)

# Do 7 dni wykresy liczymy z surowych danych, dłuższe zakresy – z agregatów godzinowych
RAW_MAX_MINUTES = 7 * 24 * 60
# Rozmiary kubełków dla długich zakresów (wielokrotności godziny, żeby pasowały do agregatu)
LONG_BUCKETS_H = (1, 2, 3, 6, 12, 24, 48)
# Kubełki z surowych danych: wielokrotności 30 s (cyklu kolektora), dzielniki godziny
RAW_BUCKETS_S = (30, 60, 120, 300, 600, 900, 1800, 3600)
# Ruch WAN ma też prędkość co 5 s (wanrate.py, od 0.85.0): krótkie zakresy i przybliżenie dostają drobniejsze kubełki
FINE_BUCKETS_S = (5, 10, 15)
LOCK_KEY = 0x4E50_4341  # "NPCA" – jedno zakładanie agregatów naraz (kolektor i CLI)


@dataclass(frozen=True)
class Aggregate:
    view: str
    source: str  # hypertable z surowymi danymi
    key: str  # kolumna obiektu (interfejs, urządzenie, sieć WiFi)
    columns: tuple[str, ...]  # średnie godzinowe pod tą samą nazwą co w tabeli
    extra: tuple[tuple[str, str], ...] = ()  # (nazwa, wyrażenie SQL), np. liczba próbek
    fn: str = "avg"  # funkcja godzinowa kolumn (`max` – najwyższa prędkość WAN z 5 s)

    def create_sql(self) -> str:
        cols = [f"{self.fn}({c}) AS {c}" for c in self.columns] + [f"{expr} AS {name}" for name, expr in self.extra]
        return (
            f"CREATE MATERIALIZED VIEW IF NOT EXISTS {self.view} "
            "WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS "
            f"SELECT time_bucket(INTERVAL '1 hour', time) AS bucket, {self.key}, {', '.join(cols)} "
            f"FROM {self.source} GROUP BY bucket, {self.key} WITH NO DATA"
        )


AGGREGATES = (
    Aggregate(
        "interface_metrics_1h",
        "interface_metrics",
        "interface_id",
        ("in_bps", "out_bps", "in_errors", "out_errors", "in_discards", "out_discards"),
        # Dostępność portu: próbki ze stanem (`oper_up` znany) i te, w których port działał
        (("state_samples", "count(oper_up)"), ("up_samples", "count(*) FILTER (WHERE oper_up)")),
    ),
    Aggregate(
        "device_metrics_1h",
        "device_metrics",
        "device_id",
        ("cpu_percent", "mem_used_percent", "load1", "poll_ms"),
        (("samples", "count(*)"), ("up_samples", "count(*) FILTER (WHERE reachable)")),
    ),
    Aggregate("wifi_metrics_1h", "wifi_metrics", "wifi_id", ("clients", "rx_bps", "tx_bps")),
    # Najwyższa prędkość WAN z 5 s w każdej godzinie (od 0.85.0) – wykres ruchu powyżej 7 dni
    Aggregate("wan_rate_metrics_1h", "wan_rate_metrics", "interface_id", ("in_bps", "out_bps"), fn="max"),
)
BY_SOURCE = {a.source: a for a in AGGREGATES}


def bucket_seconds(minutes: int, fine: bool = False) -> int:
    """Kubełek wykresu: najwyżej ~300 punktów, z równej drabinki (od 0.71.0) – 24 h to kubełki 5-minutowe, 7 dni godzinowe,
    jak w statystykach UniFi, i zawsze o pełnych minutach. Wcześniej kubełek był „ile wyjdzie” (24 h = 288 s) i średnie
    obejmowały inne okna niż na bramie. Dla długich zakresów pełne godziny (agregat)."""
    raw = (minutes * 60) // 300
    if minutes <= RAW_MAX_MINUTES:
        ladder = (FINE_BUCKETS_S + RAW_BUCKETS_S) if fine else RAW_BUCKETS_S
        return next((s for s in ladder if s >= raw), ladder[-1])
    return next((h * 3600 for h in LONG_BUCKETS_H if h * 3600 >= raw), LONG_BUCKETS_H[-1] * 3600)


def use_aggregate(minutes: int, timescale: bool) -> bool:
    return timescale and minutes > RAW_MAX_MINUTES


async def _exists(conn, view: str) -> bool:
    res = await conn.execute(
        text("SELECT 1 FROM timescaledb_information.continuous_aggregates WHERE view_name = :v"), {"v": view}
    )
    return res.scalar() is not None


async def ensure(engine: AsyncEngine, raw_days: int, keep_days: int) -> list[str]:
    """Zakłada agregaty, zasady odświeżania i retencji (idempotentnie). Zwraca nazwy nowo utworzonych widoków.

    Nowy widok od razu dostaje dane z całej zachowanej historii – zanim dostanie zasadę odświeżania, bo zadanie
    TimescaleDB rusza zaraz po jej dodaniu i dwa odświeżenia naraz się blokują. Okno odświeżania jest krótsze niż
    retencja surowych danych – inaczej odświeżenie po usunięciu starych chunków skasowałoby też ich agregaty.
    Błąd agregatu nie zatrzymuje startu: wykresy z ostatnich 7 dni i reszta UplinkView działają bez niego."""
    refresh_days = max(1, min(7, raw_days - 1))
    created: list[str] = []
    async with engine.connect() as base:
        # CREATE MATERIALIZED VIEW … continuous i refresh_continuous_aggregate nie działają w transakcji
        conn = await base.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            for a in AGGREGATES:
                try:
                    if not await _exists(conn, a.view):
                        await conn.execute(text(a.create_sql()))
                        # Nazwa widoku to stała z AGGREGATES, nie dane od użytkownika
                        await conn.execute(
                            text(f"CALL refresh_continuous_aggregate('{a.view}', NULL::timestamptz, now() - INTERVAL '1 hour')")
                        )
                        created.append(a.view)
                        log.info("Agregat godzinowy %s utworzony i wypełniony historią", a.view)
                    await conn.execute(
                        text(
                            "SELECT add_continuous_aggregate_policy(:v, start_offset => make_interval(days => :s), "
                            "end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '30 minutes', if_not_exists => TRUE)"
                        ),
                        {"v": a.view, "s": refresh_days},
                    )
                    await conn.execute(
                        text("SELECT add_retention_policy(:v, make_interval(days => :d), if_not_exists => TRUE)"),
                        {"v": a.view, "d": keep_days},
                    )
                except DBAPIError as exc:
                    log.error("Agregat godzinowy %s: %s", a.view, exc.orig)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
    return created


async def _retrying(conn, sql: str, params: dict | None = None, attempts: int = 5) -> None:
    """Polecenie w punkcie zapisu, ponawiane, gdy zadanie TimescaleDB w tle (odświeżanie agregatu, retencja) w tej
    samej chwili zmienia katalog – wtedy PostgreSQL zgłasza „tuple concurrently deleted/updated”."""
    for attempt in range(attempts):
        try:
            async with conn.begin_nested():
                await conn.execute(text(sql), params or {})
            return
        except DBAPIError as exc:
            if "concurrently" not in str(exc.orig) or attempt == attempts - 1:
                raise
            await asyncio.sleep(0.2 * (attempt + 1))


async def delete_jobs(conn) -> None:
    """Usuwa zadania TimescaleDB w tle (odświeżanie agregatów, retencja; id ≥ 1000 to zadania użytkownika) – przed
    usunięciem tabel w testach, żeby żadne nie ruszyło w trakcie. `init_db` zakłada je ponownie."""
    if (await conn.execute(text("SELECT to_regclass('timescaledb_information.jobs')"))).scalar() is None:
        return  # baza bez TimescaleDB
    jobs = await conn.execute(text("SELECT job_id FROM timescaledb_information.jobs WHERE job_id >= 1000"))
    for (job_id,) in jobs.all():
        await _retrying(conn, "SELECT delete_job(:j)", {"j": job_id})


async def drop_all(conn) -> None:
    """Usuwa agregaty (np. przed usunięciem tabel w testach – widok zależy od hypertable).

    Najpierw zasady odświeżania i retencji – bez nich zadania w tle nie wystartują w trakcie usuwania widoku."""
    for a in AGGREGATES:
        if not await _exists(conn, a.view):
            continue
        await _retrying(conn, "SELECT remove_continuous_aggregate_policy(:v, if_exists => TRUE)", {"v": a.view})
        await _retrying(conn, "SELECT remove_retention_policy(:v, if_exists => TRUE)", {"v": a.view})
        # Nazwa widoku to stała z AGGREGATES, nie dane od użytkownika
        await _retrying(conn, f"DROP MATERIALIZED VIEW IF EXISTS {a.view} CASCADE")
