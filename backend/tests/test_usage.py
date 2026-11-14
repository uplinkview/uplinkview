"""Zużycie transferu WAN – okres rozliczeniowy (czysta logika, bez bazy)."""

from __future__ import annotations

from datetime import date

import pytest

from netpulse.usage import Totals, Usage, next_period_start, period_start


def test_calendar_month():
    assert period_start(date(2026, 11, 14)) == date(2026, 11, 1)
    assert period_start(date(2026, 11, 1)) == date(2026, 11, 1)
    assert next_period_start(date(2026, 11, 1)) == date(2026, 12, 1)
    assert next_period_start(date(2026, 12, 1)) == date(2027, 1, 1)


def test_reset_day_like_mobile_plan():
    # Pakiet od 15.: 14 listopada to jeszcze okres od 15 października
    assert period_start(date(2026, 11, 14), 15) == date(2026, 10, 15)
    assert period_start(date(2026, 11, 15), 15) == date(2026, 11, 15)
    assert period_start(date(2027, 1, 3), 28) == date(2026, 12, 28)
    assert next_period_start(date(2026, 12, 28)) == date(2027, 1, 28)
    with pytest.raises(ValueError):
        period_start(date(2026, 11, 14), 29)


def test_days_and_port_totals():
    u = Usage(today=date(2026, 11, 3), start=date(2026, 11, 1), next_start=date(2026, 12, 1))
    u.by_day[(1, date(2026, 11, 1))] = Totals(100, 10)
    u.by_day[(1, date(2026, 11, 3))] = Totals(50, 5)
    u.by_day[(2, date(2026, 11, 3))] = Totals(7, 1)
    assert (u.port(1).rx, u.port(1).tx) == (150, 15)
    assert u.port(1, date(2026, 11, 3)).rx == 50
    # Dzień bez ruchu też jest na liście; port 2 pominięty
    assert [(d.day, t.rx) for d, t in u.days({1})] == [(1, 100), (2, 0), (3, 50)]
    assert u.days({1, 2})[-1][1].rx == 57
