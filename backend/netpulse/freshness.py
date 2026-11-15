"""Świeżość danych: awaria urządzenia ≠ brak aktualnych danych.

Status urządzenia (`up` / `down`) zapisuje kolektor (SNMP, UniFi, OPNsense) albo raport agenta, a razem z nim
`last_polled_at` – czas ostatniego werdyktu. Gdy werdykt jest starszy niż kilka cykli odpytywania (kolektor stoi,
pętla integracji się zawiesiła, baza była niedostępna), zapisany status jest nieaktualny: API pokazuje `unknown`
i `stale = True`, a silnik alertów nie otwiera ani nie zamyka alertów takiego urządzenia (alerts.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, literal, or_

from .config import settings

# Ile pełnych cykli odpytywania może minąć bez nowego werdyktu (duża sieć: cykl bywa dłuższy niż interwał)
STALE_CYCLES = 4
# Dolna granica – krótki interwał w testach albo w .env nie może dawać „nieznany” po chwilowym opóźnieniu
MIN_STALE_S = 120


def stale_after_s(interval_s: int | None = None) -> int:
    """Po ilu sekundach bez werdyktu status jest nieaktualny; `interval_s` = własny interwał (sprawdzenia dostępności)."""
    return max(MIN_STALE_S, (interval_s or settings.poll_interval) * STALE_CYCLES)


def stale_cutoff(now: datetime | None = None, interval_s: int | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(seconds=stale_after_s(interval_s))


def is_stale(last_polled_at: datetime | None, now: datetime | None = None, interval_s: int | None = None) -> bool:
    """Brak werdyktu albo werdykt starszy niż `stale_after_s()`."""
    return last_polled_at is None or last_polled_at < stale_cutoff(now, interval_s)


def live_status(status: str, last_polled_at: datetime | None, now: datetime | None = None, interval_s: int | None = None) -> str:
    """Status do pokazania: zapisany, gdy jest świeży, inaczej `unknown`."""
    return "unknown" if is_stale(last_polled_at, now, interval_s) else status


def status_sql(device, now: datetime | None = None):
    """To samo co `live_status` jako wyrażenie SQL (zliczanie i filtrowanie w bazie)."""
    cutoff = stale_cutoff(now)
    return case(
        (or_(device.last_polled_at.is_(None), device.last_polled_at < cutoff), literal("unknown")),
        else_=device.status,
    )
