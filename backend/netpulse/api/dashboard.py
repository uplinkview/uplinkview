"""Dane do pulpitu: podsumowanie sieci i zagregowane serie (ruch WAN, klienci WiFi)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import distinct_on

from .. import aggregates
from ..config import settings
from ..db import Session, timescale_available
from ..db.models import Device, Interface, InterfaceMetric, WifiNetwork
from ..freshness import status_sql
from ..modules import hidden_drivers, read_modules
from .metrics import MinutesQuery, OffsetQuery, _bucket_seconds, fine_series, merge_fine, window
from .schemas import Point
from .security import require_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_user)])

# „Bieżąca” wartość to ostatnia próbka z tego okna – starsze oznaczają, że urządzenie przestało odpowiadać
CURRENT_WINDOW = timedelta(minutes=5)


class DevicesSummary(BaseModel):
    total: int
    up: int
    down: int
    unknown: int


class WanSummary(BaseModel):
    in_bps: float | None
    out_bps: float | None
    interfaces: int


class DashboardSummary(BaseModel):
    devices: DevicesSummary
    wan: WanSummary
    wifi_clients: int | None
    last_poll_at: datetime | None
    poll_interval_s: int


class SeriesOut(BaseModel):
    interval_s: int
    points: list[Point]


@router.get("/summary", response_model=DashboardSummary)
async def summary():
    since = datetime.now(UTC) - CURRENT_WINDOW
    async with Session() as session:
        visible = Device.driver.not_in(hidden_drivers(await read_modules(session)) or ("",))
        status = status_sql(Device).label("live_status")  # nieaktualny werdykt kolektora = nieznany, nie „działa”
        by_status = dict(
            (await session.execute(select(status, func.count()).where(Device.enabled, visible).group_by(text("live_status")))).all()
        )
        last_poll = await session.scalar(select(func.max(Device.last_polled_at)).where(Device.enabled))

        wan_ids = (
            await session.scalars(
                select(Interface.id)
                .join(Device, Device.id == Interface.device_id)
                .where(Interface.role == "wan", Device.enabled)
            )
        ).all()
        in_bps = out_bps = None
        if wan_ids:
            latest = (
                select(InterfaceMetric.interface_id, InterfaceMetric.in_bps, InterfaceMetric.out_bps)
                .ext(distinct_on(InterfaceMetric.interface_id))
                .where(InterfaceMetric.interface_id.in_(wan_ids), InterfaceMetric.time >= since)
                .order_by(InterfaceMetric.interface_id, InterfaceMetric.time.desc())
            )
            rows = (await session.execute(latest)).all()
            ins = [r.in_bps for r in rows if r.in_bps is not None]
            outs = [r.out_bps for r in rows if r.out_bps is not None]
            in_bps = sum(ins) if ins else None
            out_bps = sum(outs) if outs else None

        n_wifi, clients = (
            await session.execute(
                select(func.count(WifiNetwork.id), func.sum(WifiNetwork.clients))
                .join(Device, Device.id == WifiNetwork.device_id)
                .where(WifiNetwork.hidden.is_(False), Device.enabled)
            )
        ).one()

    total = sum(by_status.values())
    up, down = by_status.get("up", 0), by_status.get("down", 0)
    return DashboardSummary(
        devices=DevicesSummary(total=total, up=up, down=down, unknown=total - up - down),
        wan=WanSummary(in_bps=in_bps, out_bps=out_bps, interfaces=len(wan_ids)),
        wifi_clients=int(clients) if n_wifi and clients is not None else None,
        last_poll_at=last_poll,
        poll_interval_s=settings.poll_interval,
    )


# date_bin (PostgreSQL 14+) działa z TimescaleDB i bez niego; kubełki wyrównane do stałego początku
_TRAFFIC_SQL = text(
    """
    SELECT bucket, SUM(in_bps) AS in_bps, SUM(out_bps) AS out_bps FROM (
        SELECT date_bin(CAST(:stride AS interval), m.time, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket,
               m.interface_id, AVG(m.in_bps) AS in_bps, AVG(m.out_bps) AS out_bps
        FROM interface_metrics m
        JOIN interfaces i ON i.id = m.interface_id
        JOIN devices d ON d.id = i.device_id
        WHERE i.role = 'wan' AND d.enabled AND m.time >= :since AND m.time < :until
        GROUP BY bucket, m.interface_id
    ) per_interface
    GROUP BY bucket ORDER BY bucket
    """
)

_WIFI_SQL = text(
    """
    SELECT bucket, SUM(clients) AS clients FROM (
        SELECT date_bin(CAST(:stride AS interval), m.time, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket,
               m.wifi_id, AVG(m.clients) AS clients
        FROM wifi_metrics m
        JOIN wifi_networks w ON w.id = m.wifi_id
        JOIN devices d ON d.id = w.device_id
        WHERE NOT w.hidden AND d.enabled AND m.time >= :since AND m.time < :until
        GROUP BY bucket, m.wifi_id
    ) per_network
    GROUP BY bucket ORDER BY bucket
    """
)


# Te same zestawienia z agregatów godzinowych – dla zakresów dłuższych niż 7 dni (aggregates.py)
_TRAFFIC_1H_SQL = text(
    """
    SELECT bucket, SUM(in_bps) AS in_bps, SUM(out_bps) AS out_bps FROM (
        SELECT date_bin(CAST(:stride AS interval), m.bucket, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket,
               m.interface_id, AVG(m.in_bps) AS in_bps, AVG(m.out_bps) AS out_bps
        FROM interface_metrics_1h m
        JOIN interfaces i ON i.id = m.interface_id
        JOIN devices d ON d.id = i.device_id
        WHERE i.role = 'wan' AND d.enabled AND m.bucket >= :since AND m.bucket < :until
        GROUP BY 1, m.interface_id
    ) per_interface
    GROUP BY bucket ORDER BY bucket
    """
)

_WIFI_1H_SQL = text(
    """
    SELECT bucket, SUM(clients) AS clients FROM (
        SELECT date_bin(CAST(:stride AS interval), m.bucket, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket,
               m.wifi_id, AVG(m.clients) AS clients
        FROM wifi_metrics_1h m
        JOIN wifi_networks w ON w.id = m.wifi_id
        JOIN devices d ON d.id = w.device_id
        WHERE NOT w.hidden AND d.enabled AND m.bucket >= :since AND m.bucket < :until
        GROUP BY 1, m.wifi_id
    ) per_network
    GROUP BY bucket ORDER BY bucket
    """
)


async def _aggregate(sql, sql_1h, minutes: int, columns: list[str], offset: int = 0, stride: int | None = None) -> SeriesOut:
    stride = stride or _bucket_seconds(minutes)
    since, until = window(minutes, offset)
    timescale = await timescale_available()
    if aggregates.use_aggregate(minutes, timescale):
        sql = sql_1h
    async with Session() as session:
        rows = (await session.execute(sql, {"stride": timedelta(seconds=stride), "since": since, "until": until})).all()
    points = [
        Point(time=r[0], values={c: (float(v) if v is not None else None) for c, v in zip(columns, r[1:], strict=True)})
        for r in rows
    ]
    return SeriesOut(interval_s=stride, points=points)


@router.get("/traffic", response_model=SeriesOut)
async def traffic(minutes: int = MinutesQuery, offset: int = OffsetQuery):
    """Ruch WAN (suma po wszystkich routerach): pobieranie `in_bps` i wysyłanie `out_bps`.
    Od 0.85.0 jedna linia z prawdziwej prędkości: najwyższa wartość z pomiaru co 5 s w kubełku (`wanrate.py`), a gdzie
    pomiaru nie ma – średnia z 30 s. `interval_s` nie mniej niż 30 s (panel rysuje lukę dopiero po 2,5 odstępu)."""
    stride = _bucket_seconds(minutes, fine=True)
    out = await _aggregate(_TRAFFIC_SQL, _TRAFFIC_1H_SQL, minutes, ["in_bps", "out_bps"], offset, stride)
    return SeriesOut(interval_s=max(stride, 30), points=merge_fine(out.points, await fine_series(minutes, offset, stride)))


@router.get("/wifi", response_model=SeriesOut)
async def wifi(minutes: int = MinutesQuery, offset: int = OffsetQuery):
    """Liczba klientów WiFi (suma po wszystkich widocznych sieciach)."""
    return await _aggregate(_WIFI_SQL, _WIFI_1H_SQL, minutes, ["clients"], offset)
