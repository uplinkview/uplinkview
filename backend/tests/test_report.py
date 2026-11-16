"""Raport miesięczny (od 0.65.0): zakres miesiąca, formatowanie, CSV i PDF na przykładowych danych (bez bazy)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from netpulse import report as rp

WARSAW = ZoneInfo("Europe/Warsaw")


def sample(**over) -> rp.Report:
    start, end = rp.month_range(2026, 10, WARSAW, now=datetime(2026, 11, 6, tzinfo=UTC))
    r = rp.Report(
        year=2026,
        month=10,
        start=start,
        end=end,
        generated_at=datetime(2026, 11, 6, 8, 0, tzinfo=UTC),
        timezone="Europe/Warsaw",
        version="0.65.0",
        raw_from=datetime(2026, 10, 7, tzinfo=UTC),
        devices=[
            rp.DeviceRow(1, "UCG Ultra", "192.168.1.1", "gateway", 99.995, 120, 89000),
            rp.DeviceRow(2, "Przełącznik – biuro", "192.168.1.2", "switch", 100.0, 0, 89000),
            rp.DeviceRow(3, "Nowy AP", "192.168.1.9", "ap", None, 0, 0),
        ],
        checks=[rp.CheckRow(1, "Internet – Google DNS", "ping", "8.8.8.8", 99.5, 2000, 10, 15.24, 80.0)],
        wan=[rp.WanRow("WAN 1", "UCG Ultra", 512.3e9, 40.1e9, 99.9, 2580.0, 2, 1800.0)],
        alerts=[
            rp.AlertRow(1, "Port 7 przeszedł w stan down", "warning", "USW Lite 8 PoE", datetime(2026, 10, 3, 10, tzinfo=UTC),
                        datetime(2026, 10, 3, 10, 30, tzinfo=UTC), 1800.0),  # fmt: skip
            rp.AlertRow(2, "Urządzenie nie odpowiada", "critical", "UCG Ultra", datetime(2026, 10, 20, 2, tzinfo=UTC), None, 3600.0),
        ],
        alerts_total=2,
        alerts_by_severity={"warning": 1, "critical": 1},
    )
    for k, v in over.items():
        setattr(r, k, v)
    return r


def test_month_range_uses_local_midnight_and_stops_now():
    start, end = rp.month_range(2026, 10, WARSAW, now=datetime(2027, 1, 1, tzinfo=UTC))
    assert start == datetime(2026, 9, 30, 22, tzinfo=UTC)  # 1.10 00:00 CEST
    assert end == datetime(2026, 10, 31, 23, tzinfo=UTC)  # 1.11 00:00 CET (po zmianie czasu)
    _, end = rp.month_range(2026, 12, WARSAW, now=datetime(2027, 6, 1, tzinfo=UTC))
    assert end == datetime(2026, 12, 31, 23, tzinfo=UTC)  # grudzień → 1 stycznia następnego roku
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    assert rp.month_range(2026, 11, WARSAW, now=now)[1] == now  # bieżący miesiąc – do teraz


def test_parse_month():
    now = datetime(2026, 11, 6, tzinfo=UTC)
    assert rp.parse_month(None, now, WARSAW) == (2026, 10)
    assert rp.parse_month("2026-11", now, WARSAW) == (2026, 11)
    assert rp.parse_month(None, datetime(2026, 1, 3, tzinfo=UTC), WARSAW) == (2025, 12)
    for bad in ("2026-13", "listopad", "2026-12", "1999-01"):
        with pytest.raises(ValueError):
            rp.parse_month(bad, now, WARSAW)


def test_formatting():
    assert rp.fmt_percent(99.995) == "100,00%" or rp.fmt_percent(99.995) == "99,995%"
    assert rp.fmt_percent(99.9999) == "100,000%"  # przerwa była – nie piszemy równo 100,00%
    assert rp.fmt_percent(100.0) == "100,00%"
    assert rp.fmt_percent(None) == "–"
    assert rp.fmt_duration(45) == "45 s"
    assert rp.fmt_duration(3900) == "1 h 5 min"
    assert rp.fmt_duration(3 * 86400 + 7200) == "3 d 2 h"
    assert rp.fmt_bytes(512.3e9) == "512,3 GB"
    assert rp.fmt_bytes(1234) == "1,2 kB"
    assert rp.fmt_num(1234567.891, 1) == "1 234 567,9"


def test_weighted_averages():
    r = sample()
    assert r.devices_percent == pytest.approx((99.995 + 100.0) / 2)  # AP bez próbek się nie liczy
    assert r.as_dict()["title"] == "październik 2026"


def test_csv_sections_and_polish_excel_format():
    data = rp.to_csv(sample())
    assert data.startswith("﻿".encode())
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))
    assert rows[0] == ["Raport UplinkView", "październik 2026"]
    assert rows[1] == ["Okres", "01.10.2026 00:00", "01.11.2026 00:00"]
    flat = [r for r in rows if r]
    assert ["UCG Ultra", "192.168.1.1", "router", "99,995", "2,0", "89000"] in flat
    assert any(r[:2] == ["Nowy AP", "192.168.1.9"] and r[3] == "–" for r in flat)
    assert ["WAN 1", "UCG Ultra", "512,300", "40,100", "99,900", "2", "43,0", "30,0"] in flat
    alert = next(r for r in flat if r[4:5] == ["Urządzenie nie odpowiada"])
    assert alert[1] == "trwa" and alert[3] == "krytyczny" and len(alert) == 6
    assert ["Sprawdzenia i SLA WAN od", "07.10.2026 02:00"] in flat


@pytest.mark.parametrize("with_font", [True, False])
def test_pdf_renders_with_and_without_unicode_font(with_font):
    font = rp.find_font() if with_font else None
    if with_font and font is None:
        pytest.skip("brak czcionki TTF z polskimi znakami (DejaVu / Arial)")
    many = [
        rp.AlertRow(i, f"Alert {i}", "warning", "UCG Ultra", datetime(2026, 10, 5, tzinfo=UTC), None, float(i))
        for i in range(120)
    ]
    data = rp.to_pdf(sample(alerts=many, alerts_total=130), font=font)
    assert data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
    assert len(data) > 2000


def test_pdf_empty_month():
    data = rp.to_pdf(sample(devices=[], checks=[], wan=[], alerts=[], alerts_total=0, alerts_by_severity={}, raw_from=None), font=None)
    assert data.startswith(b"%PDF-")


def test_filename():
    assert rp.filename(sample(), "pdf") == "uplinkview-raport-2026-10.pdf"


def test_csv_and_pdf_in_english():
    """0.76.0: raport w języku panelu – teksty z katalogu, liczby z kropką, daty RRRR-MM-DD, CSV z przecinkiem."""
    data = rp.to_csv(sample(), "en")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows[0] == ["UplinkView report", "October 2026"]
    assert rows[1] == ["Period", "2026-10-01 00:00", "2026-11-01 00:00"]
    flat = [r for r in rows if r]
    assert ["UCG Ultra", "192.168.1.1", "router", "99.995", "2.0", "89000"] in flat
    assert ["WAN 1", "UCG Ultra", "512.300", "40.100", "99.900", "2", "43.0", "30.0"] in flat
    alert = next(r for r in flat if r[4:5] == ["Device not responding"])
    assert alert[1] == "ongoing" and alert[3] == "critical" and len(alert) == 6
    text = data.decode("utf-8-sig").replace("Przełącznik – biuro", "").replace("Port 7 przeszedł w stan down", "")  # nazwy z danych
    assert not any(c in text for c in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"), text
    assert rp.filename(sample(), "pdf", "en") == "uplinkview-report-2026-10.pdf"
    assert rp.to_pdf(sample(), font=None, lang="en").startswith(b"%PDF-")
