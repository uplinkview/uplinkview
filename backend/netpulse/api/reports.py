"""Raport miesięczny (od 0.65.0): podgląd JSON, pobranie CSV i PDF. Logika i formaty: netpulse/report.py.

`month=RRRR-MM` (puste = poprzedni pełny miesiąc); każdy zalogowany (także podgląd) – raport tylko czyta dane.
`lang=pl|en` (od 0.76.0) – język pliku CSV/PDF; bez niego język żądania (`Accept-Language`).
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from .. import report as rp
from ..i18n import current_language
from .security import require_user

router = APIRouter(prefix="/api/reports", tags=["raporty"], dependencies=[Depends(require_user)])

MonthQuery = Query(None, pattern=r"^\d{4}-\d{2}$", description="miesiąc RRRR-MM; puste = poprzedni pełny miesiąc")
LangQuery = Query(None, pattern=r"^(pl|en)$", description="język pliku; puste = język żądania")


class DeviceRowOut(BaseModel):
    id: int
    name: str
    host: str
    kind: str
    percent: float | None
    down_s: int
    samples: int


class CheckRowOut(BaseModel):
    id: int
    name: str
    kind: str
    target: str
    percent: float | None
    samples: int
    failed: int
    avg_latency_ms: float | None
    max_latency_ms: float | None


class WanRowOut(BaseModel):
    name: str
    device: str
    rx_bytes: float
    tx_bytes: float
    percent: float | None
    down_s: float | None
    outages: int | None
    longest_outage_s: float | None


class AlertRowOut(BaseModel):
    id: int
    title: str
    severity: str
    device: str | None
    started_at: datetime
    resolved_at: datetime | None
    duration_s: float


class ReportOut(BaseModel):
    year: int
    month: int
    title: str
    start: datetime
    end: datetime
    generated_at: datetime
    timezone: str
    version: str
    raw_from: datetime | None
    devices_percent: float | None
    checks_percent: float | None
    devices: list[DeviceRowOut]
    checks: list[CheckRowOut]
    wan: list[WanRowOut]
    alerts: list[AlertRowOut]
    alerts_total: int
    alerts_by_severity: dict[str, int]


async def _build(month: str | None) -> rp.Report:
    try:
        year, mon = rp.parse_month(month)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await rp.build(year, mon)


def _download(data: bytes, name: str, media_type: str) -> Response:
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/monthly", response_model=ReportOut)
async def monthly(month: str | None = MonthQuery):
    return (await _build(month)).as_dict()


@router.get("/monthly.csv")
async def monthly_csv(month: str | None = MonthQuery, lang: str | None = LangQuery):
    r = await _build(month)
    lang = lang or current_language()
    return _download(rp.to_csv(r, lang), rp.filename(r, "csv", lang), "text/csv; charset=utf-8")


@router.get("/monthly.pdf")
async def monthly_pdf(month: str | None = MonthQuery, lang: str | None = LangQuery):
    r = await _build(month)
    lang = lang or current_language()
    data = await asyncio.to_thread(rp.to_pdf, r, True, lang)  # fpdf2 jest synchroniczny – nie blokujemy pętli API
    return _download(data, rp.filename(r, "pdf", lang), "application/pdf")
