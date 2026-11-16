"""Dostępność (uptime) urządzeń i portów w procentach, np. „switch 99,98% w 30 dni”.

Źródło: próbki kolektora (`device_metrics.reachable`, `interface_metrics.oper_up`), przy TimescaleDB z agregatów
godzinowych (aggregates.py), więc okres może sięgać roku wstecz, choć surowe dane trzymamy 30 dni.
Dni liczone w strefie czasowej instalacji (zmienna TZ)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from ..config import settings
from ..db import Session, timescale_available
from ..db.models import Device, Interface
from .security import require_user

router = APIRouter(prefix="/api", tags=["dostępność"], dependencies=[Depends(require_user)])

DaysQuery = Query(30, ge=1, le=366, description="okres wstecz w dniach")

# (agregat godzinowy, tabela surowa, kolumna obiektu, suma próbek w agregacie, próbki „działa” w agregacie,
#  liczba próbek w surowej tabeli, próbki „działa” w surowej tabeli)
_SOURCES = {
    "device": ("device_metrics_1h", "device_metrics", "device_id", "samples", "up_samples", "count(*)", "count(*) FILTER (WHERE reachable)"),
    "interface": (
        "interface_metrics_1h",
        "interface_metrics",
        "interface_id",
        "state_samples",
        "up_samples",
        "count(oper_up)",
        "count(*) FILTER (WHERE oper_up)",
    ),
}


class DayOut(BaseModel):
    day: date
    percent: float | None
    samples: int


class AvailabilityOut(BaseModel):
    days: int
    percent: float | None  # None = brak próbek w okresie
    samples: int
    # Przybliżony czas niedostępności: próbki bez odpowiedzi × interwał odpytywania
    down_s: int
    daily: list[DayOut]


class DeviceAvailabilityOut(BaseModel):
    device_id: int
    percent: float | None
    samples: int


def _percent(total: int, up: int) -> float | None:
    return up * 100.0 / total if total else None


def _sql(kind: str, timescale: bool, *, per_day: bool) -> str:
    view, raw, key, agg_total, agg_up, raw_total, raw_up = _SOURCES[kind]
    if timescale:
        src, time_col, total, up = view, "bucket", f"sum({agg_total})", f"sum({agg_up})"
    else:
        src, time_col, total, up = raw, "time", raw_total, raw_up
    if per_day:
        return (
            f"SELECT (date_trunc('day', {time_col} AT TIME ZONE :tz))::date AS day, {total} AS total, {up} AS up "
            f"FROM {src} WHERE {key} = :id AND {time_col} >= :since GROUP BY 1 ORDER BY 1"
        )
    return f"SELECT {key}, {total} AS total, {up} AS up FROM {src} WHERE {time_col} >= :since GROUP BY {key}"


async def _timescale() -> bool:
    return await timescale_available()


async def availability(kind: str, obj_id: int, days: int) -> AvailabilityOut:
    """Dostępność jednego urządzenia albo portu: łącznie i dzień po dniu."""
    since = datetime.now(UTC) - timedelta(days=days)
    sql = _sql(kind, await _timescale(), per_day=True)
    async with Session() as session:
        rows = (await session.execute(text(sql), {"id": obj_id, "since": since, "tz": settings.timezone})).all()
    total = sum(int(r.total) for r in rows)
    up = sum(int(r.up) for r in rows)
    return AvailabilityOut(
        days=days,
        percent=_percent(total, up),
        samples=total,
        down_s=(total - up) * settings.poll_interval,
        daily=[DayOut(day=r.day, percent=_percent(int(r.total), int(r.up)), samples=int(r.total)) for r in rows],
    )


async def devices_availability(days: int) -> list[DeviceAvailabilityOut]:
    """Dostępność wszystkich urządzeń jednym zapytaniem (karty urządzeń na pulpicie)."""
    since = datetime.now(UTC) - timedelta(days=days)
    sql = _sql("device", await _timescale(), per_day=False)
    async with Session() as session:
        rows = (await session.execute(text(sql), {"since": since})).all()
    return [
        DeviceAvailabilityOut(device_id=r[0], percent=_percent(int(r.total), int(r.up)), samples=int(r.total))
        for r in rows
    ]


@router.get("/availability", response_model=list[DeviceAvailabilityOut])
async def all_devices(days: int = DaysQuery):
    return await devices_availability(days)


@router.get("/devices/{device_id}/availability", response_model=AvailabilityOut)
async def device_availability(device_id: int, days: int = DaysQuery):
    async with Session() as session:
        if await session.get(Device, device_id) is None:
            raise HTTPException(404, "Nie ma takiego urządzenia")
    return await availability("device", device_id, days)


@router.get("/interfaces/{interface_id}/availability", response_model=AvailabilityOut)
async def interface_availability(interface_id: int, days: int = DaysQuery):
    """Ile czasu port był podłączony (oper up) – próbki bez znanego stanu nie liczą się wcale."""
    async with Session() as session:
        if await session.get(Interface, interface_id) is None:
            raise HTTPException(404, "Nie ma takiego portu")
    return await availability("interface", interface_id, days)
