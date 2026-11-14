"""Łącza WAN routera (dual WAN / failover): stan, historia (które łącze niosło ruch), SLA i konfiguracja.

- GET /api/wan/status – łącza i ich bieżący stan (active | standby | down | unknown), ruch, od kiedy w tym stanie,
- GET /api/wan/history?minutes= – ruch aktywnego łącza w kubełkach, odcinki stanów i momenty przełączenia,
- GET /api/wan/sla?days= – dostępność w %, czas i liczba przerw dla każdego łącza,
- GET /api/wan/usage?reset_day=&device_id= – zużycie transferu dziś i w okresie rozliczeniowym (od 0.82.0),
- GET/PUT /api/wan/links – które porty są WAN 1, WAN 2 … (zapis: administrator),
- GET /api/wan/suggestions – łącza WAN, które zgłasza kontroler UniFi, a nie ma ich na liście.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import distinct_on

from .. import usage, wan_links
from ..config import settings
from ..db import Session, timescale_available
from ..db.models import Device, Interface, WanLink, WanLinkMetric
from ..modules import hidden_drivers, is_enabled, read_modules
from ..wan import Sample, compute_sla, segments, switches
from .metrics import MinutesQuery, _bucket_seconds
from .schemas import Point
from .security import require_admin, require_user

router = APIRouter(prefix="/api/wan", tags=["łącza WAN"], dependencies=[Depends(require_user)])

CURRENT_WINDOW = timedelta(minutes=5)
MAX_OUTAGES = 20


class WanLinkOut(BaseModel):
    id: int
    name: str
    position: int
    device_id: int
    device_name: str
    interface_id: int
    interface_name: str
    interface_label: str
    speed_mbps: int | None
    state: str  # active | standby | down | unknown
    state_since: datetime | None
    source: str | None  # controller | traffic | priority
    in_bps: float | None = None
    out_bps: float | None = None
    sampled_at: datetime | None = None


class WanStatusOut(BaseModel):
    links: list[WanLinkOut]
    active_ids: list[int]


async def _links(session) -> list[WanLinkOut]:
    rows = (
        await session.execute(
            select(WanLink, Device.name, Interface)
            .join(Device, Device.id == WanLink.device_id)
            .join(Interface, Interface.id == WanLink.interface_id)
            .order_by(WanLink.position, Device.name, WanLink.id)
        )
    ).all()
    return [
        WanLinkOut(
            id=link.id,
            name=link.name,
            position=link.position,
            device_id=link.device_id,
            device_name=device_name,
            interface_id=iface.id,
            interface_name=iface.name,
            interface_label=iface.label,
            speed_mbps=iface.speed_mbps,
            state=link.state,
            state_since=link.state_since,
            source=link.source,
        )
        for link, device_name, iface in rows
    ]


@router.get("/status", response_model=WanStatusOut)
async def status():
    since = datetime.now(UTC) - CURRENT_WINDOW
    async with Session() as session:
        links = await _links(session)
        if links:
            latest = (
                select(WanLinkMetric.wan_link_id, WanLinkMetric.time, WanLinkMetric.in_bps, WanLinkMetric.out_bps)
                .ext(distinct_on(WanLinkMetric.wan_link_id))
                .where(WanLinkMetric.wan_link_id.in_([x.id for x in links]), WanLinkMetric.time >= since)
                .order_by(WanLinkMetric.wan_link_id, WanLinkMetric.time.desc())
            )
            last = {r.wan_link_id: r for r in await session.execute(latest)}
            for x in links:
                if x.id in last:
                    x.in_bps, x.out_bps, x.sampled_at = last[x.id].in_bps, last[x.id].out_bps, last[x.id].time
                elif x.state != "unknown":
                    x.state = "unknown"  # brak świeżych próbek (np. kolektor nie działa)
    return WanStatusOut(links=links, active_ids=[x.id for x in links if x.state == "active"])


# --- historia ------------------------------------------------------------------------------------


class SegmentOut(BaseModel):
    link_id: int
    state: str
    start: datetime
    end: datetime


class SwitchOut(BaseModel):
    time: datetime
    from_ids: list[int]
    to_ids: list[int]


class WanHistoryOut(BaseModel):
    interval_s: int
    links: list[WanLinkOut]
    # Wartości `in_<id>` / `out_<id>`: ruch łącza tylko wtedy, gdy było aktywne (inaczej brak) – linia
    # łącza zapasowego zaczyna się w chwili przełączenia
    points: list[Point]
    segments: list[SegmentOut]
    switches: list[SwitchOut]


_HISTORY_SQL = text(
    """
    SELECT date_bin(CAST(:stride AS interval), time, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket, wan_link_id,
           AVG(in_bps) FILTER (WHERE active) AS in_bps, AVG(out_bps) FILTER (WHERE active) AS out_bps
    FROM wan_link_metrics
    WHERE wan_link_id = ANY(:ids) AND time >= :since
    GROUP BY bucket, wan_link_id
    ORDER BY bucket
    """
)


async def _samples(session, ids: list[int], since: datetime) -> dict[int, list[Sample]]:
    rows = await session.execute(
        select(WanLinkMetric.wan_link_id, WanLinkMetric.time, WanLinkMetric.up, WanLinkMetric.active)
        .where(WanLinkMetric.wan_link_id.in_(ids), WanLinkMetric.time >= since)
        .order_by(WanLinkMetric.time)
    )
    out: dict[int, list[Sample]] = defaultdict(list)
    for link_id, t, up, active in rows:
        out[link_id].append(Sample(t, up, active))
    return out


@router.get("/history", response_model=WanHistoryOut)
async def history(minutes: int = MinutesQuery):
    stride = _bucket_seconds(minutes)
    now = datetime.now(UTC)
    since = now - timedelta(minutes=minutes)
    max_gap = wan_links.stale_after()
    async with Session() as session:
        links = await _links(session)
        ids = [x.id for x in links]
        if not ids:
            return WanHistoryOut(interval_s=stride, links=[], points=[], segments=[], switches=[])
        rows = (await session.execute(_HISTORY_SQL, {"stride": timedelta(seconds=stride), "since": since, "ids": ids})).all()
        samples = await _samples(session, ids, since - max_gap)

    buckets: dict[datetime, dict[str, float | None]] = {}
    for bucket, link_id, in_bps, out_bps in rows:
        values = buckets.setdefault(bucket, {f"{d}_{i}": None for i in ids for d in ("in", "out")})
        values[f"in_{link_id}"] = float(in_bps) if in_bps is not None else None
        values[f"out_{link_id}"] = float(out_bps) if out_bps is not None else None
    segs = [
        SegmentOut(link_id=link_id, state=s.state, start=s.start, end=s.end)
        for link_id, items in samples.items()
        for s in segments(items, since, now, max_gap)
    ]
    # Jedna kolejność łączy dla wszystkich routerów, więc przełączenie może też przejść z routera na router
    events = switches({x.id: [s for s in samples.get(x.id, []) if s.time >= since] for x in links}, max_gap)
    return WanHistoryOut(
        interval_s=stride,
        links=links,
        points=[Point(time=t, values=v) for t, v in sorted(buckets.items())],
        segments=segs,
        switches=[SwitchOut(time=sw.time, from_ids=list(sw.from_ids), to_ids=list(sw.to_ids)) for sw in events],
    )


# --- SLA -----------------------------------------------------------------------------------------


class OutageOut(BaseModel):
    start: datetime
    end: datetime
    duration_s: float
    ongoing: bool


class LinkSlaOut(BaseModel):
    link: WanLinkOut
    availability: float | None  # % czasu z danymi, w którym łącze działało
    up_s: float
    down_s: float
    active_s: float  # ile czasu łącze niosło ruch
    unknown_s: float  # brak danych (router nie odpowiadał, kolektor nie działał)
    outages: int
    longest_outage_s: float
    recent_outages: list[OutageOut]  # najnowsze na początku


class WanSlaOut(BaseModel):
    days: int
    start: datetime
    end: datetime
    links: list[LinkSlaOut]


@router.get("/sla", response_model=WanSlaOut)
async def sla(days: int = Query(1, ge=1, le=90, description="okres wstecz w dniach (np. 1, 7, 30)")):
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    max_gap = wan_links.stale_after()
    async with Session() as session:
        links = await _links(session)
        samples = await _samples(session, [x.id for x in links], start - max_gap) if links else {}
    out = []
    for x in links:
        r = compute_sla(samples.get(x.id, []), start, end, max_gap)
        out.append(
            LinkSlaOut(
                link=x,
                availability=r.availability,
                up_s=round(r.up_s, 1),
                down_s=round(r.down_s, 1),
                active_s=round(r.active_s, 1),
                unknown_s=round(r.unknown_s, 1),
                outages=len(r.outages),
                longest_outage_s=round(r.longest_s, 1),
                recent_outages=[
                    OutageOut(start=o.start, end=o.end, duration_s=round(o.seconds, 1), ongoing=o.ongoing)
                    for o in reversed(r.outages[-MAX_OUTAGES:])
                ],
            )
        )
    return WanSlaOut(days=days, start=start, end=end, links=out)


# --- zużycie transferu ----------------------------------------------------------------------------


class UsageTotals(BaseModel):
    rx_bytes: float  # pobrane
    tx_bytes: float  # wysłane


class UsagePortOut(BaseModel):
    interface_id: int
    device_id: int
    device_name: str
    name: str  # nazwa łącza WAN (Ustawienia → Łącza WAN) albo etykieta portu
    today: UsageTotals
    period: UsageTotals


class UsageDayOut(BaseModel):
    day: date
    rx_bytes: float
    tx_bytes: float


class WanUsageOut(BaseModel):
    timezone: str
    reset_day: int
    today: date
    period_start: date
    next_period_start: date  # dzień, od którego licznik okresu zaczyna od zera
    total_today: UsageTotals
    total_period: UsageTotals
    ports: list[UsagePortOut]
    days: list[UsageDayOut]  # każdy dzień okresu do dziś


def _totals(t: usage.Totals) -> UsageTotals:
    return UsageTotals(rx_bytes=round(t.rx), tx_bytes=round(t.tx))


@router.get("/usage", response_model=WanUsageOut)
async def wan_usage(
    reset_day: int = Query(1, ge=1, le=usage.MAX_RESET_DAY, description="dzień miesiąca, od którego liczy się okres (1 = miesiąc kalendarzowy)"),
    device_id: int | None = Query(None, ge=1, description="router; puste = wszystkie"),
):
    """Zużycie transferu portów WAN: dziś i w bieżącym okresie (miesiąc albo okres od dnia `reset_day`)."""
    timescale = await timescale_available()
    async with Session() as session:
        hidden = hidden_drivers(await read_modules(session))
        q = (
            select(Interface, Device.name)
            .join(Device, Device.id == Interface.device_id)
            .where(Interface.role == "wan", Device.driver.not_in(hidden or ("",)))
        )
        if device_id is not None:
            q = q.where(Device.id == device_id)
        ports = (await session.execute(q)).all()
        links = {x.interface_id: x for x in (await session.scalars(select(WanLink))).all()}
        data = await usage.load(session, [p.id for p, _ in ports], reset_day, timescale)

    order = sorted(ports, key=lambda p: (links[p[0].id].position if p[0].id in links else 99, p[1], p[0].if_index))
    out_ports = []
    total_today, total_period = usage.Totals(), usage.Totals()
    for iface, device_name in order:
        today, period = data.port(iface.id, data.today), data.port(iface.id)
        total_today.add(today.rx, today.tx)
        total_period.add(period.rx, period.tx)
        link = links.get(iface.id)
        out_ports.append(
            UsagePortOut(
                interface_id=iface.id,
                device_id=iface.device_id,
                device_name=device_name,
                name=link.name if link else iface.label or iface.name,
                today=_totals(today),
                period=_totals(period),
            )
        )
    return WanUsageOut(
        timezone=settings.timezone,
        reset_day=reset_day,
        today=data.today,
        period_start=data.start,
        next_period_start=data.next_start,
        total_today=_totals(total_today),
        total_period=_totals(total_period),
        ports=out_ports,
        days=[UsageDayOut(day=d, rx_bytes=round(t.rx), tx_bytes=round(t.tx)) for d, t in data.days({p.id for p, _ in ports})],
    )


# --- konfiguracja ----------------------------------------------------------------------------------


class WanLinkIn(BaseModel):
    interface_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Podaj nazwę łącza")
        return v


class WanLinksIn(BaseModel):
    """Pełna lista łączy w kolejności (pierwsze = WAN 1, łącze główne; kolejność wspólna dla wszystkich routerów).
    Pominięte łącza są usuwane razem z historią."""

    links: list[WanLinkIn] = Field(max_length=wan_links.MAX_LINKS * 4)

    @model_validator(mode="after")
    def _unique(self) -> WanLinksIn:
        ids = [x.interface_id for x in self.links]
        if len(set(ids)) != len(ids):
            raise ValueError("Ten sam port nie może być dwoma łączami WAN")
        return self


@router.get("/links", response_model=list[WanLinkOut])
async def list_links():
    async with Session() as session:
        return await _links(session)


@router.put("/links", response_model=list[WanLinkOut], dependencies=[Depends(require_admin)])
async def save_links(body: WanLinksIn):
    async with Session() as session, session.begin():
        ifaces = {
            i.id: i
            for i in (await session.scalars(select(Interface).where(Interface.id.in_([x.interface_id for x in body.links] or [0])))).all()
        }
        missing = [x.interface_id for x in body.links if x.interface_id not in ifaces]
        if missing:
            raise HTTPException(422, f"Nie ma portu o id {missing[0]}")
        per_device: dict[int, int] = defaultdict(int)
        for x in body.links:
            per_device[ifaces[x.interface_id].device_id] += 1
        if any(n > wan_links.MAX_LINKS for n in per_device.values()):
            raise HTTPException(422, f"Router może mieć najwyżej {wan_links.MAX_LINKS} łącza WAN")

        existing = {link.interface_id: link for link in (await session.scalars(select(WanLink))).all()}
        keep = {x.interface_id for x in body.links}
        await session.execute(delete(WanLink).where(WanLink.interface_id.not_in(keep or {0})))
        for position, x in enumerate(body.links, start=1):
            link = existing.get(x.interface_id)
            if link is None:
                device_id = ifaces[x.interface_id].device_id
                session.add(WanLink(device_id=device_id, interface_id=x.interface_id, position=position, name=x.name, state="unknown"))
            else:
                link.name, link.position = x.name, position
        # Od teraz porty WAN wybiera użytkownik – kolektor nie dopisze już sam portów z rolą WAN
        await wan_links.set_manual(session)
    async with Session() as session:
        return await _links(session)


class WanSuggestionOut(BaseModel):
    device_id: int
    device_name: str
    interface_id: int
    interface_name: str
    interface_label: str
    slot: int | None  # numer łącza w UniFi (WAN 2 …)
    up: bool | None
    active: bool


@router.get("/suggestions", response_model=list[WanSuggestionOut])
async def suggestions():
    """Porty, które kontroler UniFi zna jako WAN bramy, a nie są ustawione jako łącza WAN w UplinkView."""
    if not await is_enabled("unifi"):
        return []
    async with Session() as session:
        found = await wan_links.detected(session)
        if not found:
            return []
        configured = set(await session.scalars(select(WanLink.interface_id)))
        rows = (
            await session.execute(
                select(Interface, Device.name).join(Device, Device.id == Interface.device_id).where(Interface.device_id.in_(list(found)))
            )
        ).all()
    by_name = {(iface.device_id, iface.name): (iface, device_name) for iface, device_name in rows}
    out = []
    for device_id, ports in found.items():
        for p in ports:
            match = by_name.get((device_id, p.get("ifname")))
            if match is None or match[0].id in configured:
                continue
            iface, device_name = match
            out.append(
                WanSuggestionOut(
                    device_id=device_id,
                    device_name=device_name,
                    interface_id=iface.id,
                    interface_name=iface.name,
                    interface_label=iface.label,
                    slot=p.get("slot"),
                    up=p.get("up"),
                    active=bool(p.get("active")),
                )
            )
    return sorted(out, key=lambda x: (x.device_name, x.slot or 99, x.interface_name))
