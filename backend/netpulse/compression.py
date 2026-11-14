"""Kompresja TimescaleDB na hypertables z metrykami (od 0.67.0): mniejsza baza i szybsze długie zakresy.

Chunki starsze niż `compress_after_days` (domyślnie 7 dni) TimescaleDB kompresuje w tle kolumnowo – metryki
zajmują zwykle kilka–kilkanaście razy mniej miejsca. Do 7 dni wykresy czytają surowe, nieskompresowane dane
(`aggregates.RAW_MAX_MINUTES`), więc bieżąca praca panelu się nie zmienia; starsze dane czytają agregaty
godzinowe, raport miesięczny i dostępność.

Zakłada to `init_db` (obiekty TimescaleDB, poza Alembikiem – jak agregaty). Błąd kompresji jednej tabeli nie
zatrzymuje startu: tabela zostaje nieskompresowana, reszta UplinkView działa.

Zasady dla migracji: do skompresowanej hypertable można dodać kolumnę (bez wartości domyślnej albo ze stałą),
ale nie zmienić typu kolumny ani nie dodać ograniczenia – taka migracja musi najpierw zdekompresować chunki.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

log = logging.getLogger(__name__)

# Tabela → kolumny `segmentby`: obiekt, po którym filtrują zapytania (wykres jednego portu, urządzenia, sprawdzenia).
# Wiersze jednego obiektu leżą razem, więc zapytanie o niego czyta tylko jego segmenty. Pusta krotka = bez podziału.
# Nowa hypertable = wpis tutaj (pilnuje test_compression.py).
SEGMENT_BY: dict[str, tuple[str, ...]] = {
    "interface_metrics": ("interface_id",),
    "device_metrics": ("device_id",),
    "wifi_metrics": ("wifi_id",),
    "poe_port_metrics": ("device_id", "port_idx"),
    "poe_budget_metrics": ("device_id",),
    "system_metrics": (),
    "disk_metrics": ("device_id", "mount"),
    "server_metrics": ("device_id",),
    "metrics": ("device_id", "name", "key"),
    "wan_link_metrics": ("wan_link_id",),
    "client_metrics": ("mac",),
    "check_metrics": ("check_id",),
    "wan_rate_metrics": ("interface_id",),
}


def compress_after_days(retention_days: int, wanted: int) -> int:
    """Po ilu dniach kompresować: nie później niż dzień przed retencją (inaczej chunk znikałby przed kompresją)
    i nie wcześniej niż po 1 dniu (bieżący chunk jest zapisywany)."""
    return max(1, min(wanted, retention_days - 1))


def settings_sql(table: str) -> str:
    """Włączenie kompresji tabeli. Nazwy tabel i kolumn to stałe z `SEGMENT_BY`, nie dane od użytkownika."""
    options = ["timescaledb.compress", "timescaledb.compress_orderby = 'time DESC'"]
    if SEGMENT_BY[table]:
        options.append(f"timescaledb.compress_segmentby = '{', '.join(SEGMENT_BY[table])}'")
    return f"ALTER TABLE {table} SET ({', '.join(options)})"


async def ensure(conn, tables: tuple[str, ...], retention_days: int, wanted_days: int) -> list[str]:
    """Włącza kompresję i zasadę kompresowania starszych chunków (idempotentnie). Zwraca tabele z kompresją.

    `wanted_days <= 0` wyłącza: nowych zasad nie zakładamy, istniejące usuwamy (skompresowane chunki zostają
    czytelne – dekompresja to osobna, świadoma operacja)."""
    done: list[str] = []
    for table in tables:
        if table not in SEGMENT_BY:
            log.error("Kompresja: brak wpisu SEGMENT_BY dla tabeli %s", table)
            continue
        try:
            # Punkt zapisu: błąd jednej tabeli nie przerywa transakcji `init_db`
            async with conn.begin_nested():
                if wanted_days <= 0:
                    await conn.execute(text("SELECT remove_compression_policy(:t, if_exists => TRUE)"), {"t": table})
                    continue
                enabled = (
                    await conn.execute(
                        text("SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name = :t"),
                        {"t": table},
                    )
                ).scalar()
                if not enabled:
                    await conn.execute(text(settings_sql(table)))
                await conn.execute(
                    text("SELECT add_compression_policy(:t, make_interval(days => :d), if_not_exists => TRUE)"),
                    {"t": table, "d": compress_after_days(retention_days, wanted_days)},
                )
                done.append(table)
        except DBAPIError as exc:
            log.error("Kompresja tabeli %s: %s", table, exc.orig)
    return done
