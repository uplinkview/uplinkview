"""Dane dla paneli pulpitu (od 0.27.0): kolekcje bieżących wartości (paski, tabela) i stany w czasie (oś stanów).

- `GET /api/collections/{kind}`: wiersz na obiekt (urządzenie, port, dysk, sieć WiFi, kontener, usługa systemd, klient) z bieżącymi
  wartościami. Bez adresów, MAC-ów i sekretów – te same dane może dostać pulpit publiczny.
- `GET /api/states`: odcinki „działa / nie działa / brak danych” dla urządzeń (`reachable`) i portów (`oper_up`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import distinct_on

from ..collector import NOT_PRESENT
from ..config import settings
from ..db import Session
from ..db.models import (
    Agent,
    Check,
    CheckMetric,
    Device,
    DeviceMetric,
    Interface,
    InterfaceMetric,
    NetworkClient,
    WifiMetric,
    WifiNetwork,
)
from ..modules import hidden_drivers, read_modules
from .metrics import MinutesQuery, _bucket_seconds
from .security import require_user
from .servers import device_server

router = APIRouter(prefix="/api", tags=["panele"], dependencies=[Depends(require_user)])

CollectionKind = Literal["devices", "ports", "disks", "wifi", "containers", "services", "clients", "checks"]
MAX_ROWS = 200
MAX_STATE_ITEMS = 20
CURRENT = timedelta(minutes=5)
RADIO = {"na": "5 GHz", "ng": "2,4 GHz", "6e": "6 GHz"}


class Row(BaseModel):
    key: str
    label: str
    device_id: int | None = None
    values: dict[str, float | None]


class CollectionOut(BaseModel):
    kind: str
    rows: list[Row]


def _num(v) -> float | None:
    return float(v) if v is not None else None


async def _visible_devices(session) -> dict[int, Device]:
    hidden = hidden_drivers(await read_modules(session))
    rows = (await session.scalars(select(Device).where(Device.enabled, Device.driver.not_in(hidden or ("",))).order_by(Device.name))).all()
    return {d.id: d for d in rows}


async def _device(session, device_id: int | None) -> Device:
    if device_id is None:
        raise HTTPException(422, "Wybierz urządzenie")
    device = (await _visible_devices(session)).get(device_id)
    if device is None:
        raise HTTPException(404, "Nie ma takiego urządzenia")
    return device


@router.get("/collections/{kind}", response_model=CollectionOut)
async def collection(kind: CollectionKind, device_id: int | None = Query(None, ge=1)):
    since = datetime.now(UTC) - CURRENT
    async with Session() as session:
        mods = await read_modules(session)
        if kind == "devices":
            devices = await _visible_devices(session)
            latest = {
                m.device_id: m
                for m in (
                    await session.scalars(
                        select(DeviceMetric)
                        .ext(distinct_on(DeviceMetric.device_id))
                        .where(DeviceMetric.device_id.in_(list(devices) or [0]), DeviceMetric.time >= since)
                        .order_by(DeviceMetric.device_id, DeviceMetric.time.desc())
                    )
                ).all()
            }
            rows = []
            for d in devices.values():
                m = latest.get(d.id)
                rows.append(
                    Row(
                        key=str(d.id),
                        label=d.name,
                        device_id=d.id,
                        values={
                            "up": 1.0 if d.live_status == "up" else 0.0 if d.live_status == "down" else None,
                            "cpu_percent": _num(m.cpu_percent) if m else None,
                            "mem_used_percent": _num(m.mem_used_percent) if m else None,
                            "poll_ms": _num(m.poll_ms) if m else None,
                            "uptime_s": _num(d.uptime_s),
                        },
                    )
                )
        elif kind == "ports":
            device = await _device(session, device_id)
            # Bez interfejsów, których nie ma w ostatnim odczycie (zakończony tunel VPN, Teleport) – wracają same z sesją
            ports = (
                await session.scalars(
                    select(Interface)
                    .where(Interface.device_id == device.id, Interface.hidden.is_(False), Interface.oper_status != NOT_PRESENT)
                    .order_by(Interface.if_index)
                )
            ).all()
            latest = {
                r.interface_id: r
                for r in await session.execute(
                    select(InterfaceMetric.interface_id, InterfaceMetric.in_bps, InterfaceMetric.out_bps)
                    .ext(distinct_on(InterfaceMetric.interface_id))
                    .where(InterfaceMetric.interface_id.in_([p.id for p in ports] or [0]), InterfaceMetric.time >= since)
                    .order_by(InterfaceMetric.interface_id, InterfaceMetric.time.desc())
                )
            }
            rows = [
                Row(
                    key=str(p.id),
                    label=f"{p.label or p.name}" + (f" ({p.alias})" if p.alias and p.alias != p.label else ""),
                    device_id=device.id,
                    values={
                        "up": 1.0 if p.oper_status == "up" else 0.0,
                        "in_bps": _num(latest[p.id].in_bps) if p.id in latest else None,
                        "out_bps": _num(latest[p.id].out_bps) if p.id in latest else None,
                        "speed_mbps": _num(p.speed_mbps) if p.oper_status == "up" else None,
                    },
                )
                for p in ports
            ]
        elif kind == "disks":
            device = await _device(session, device_id)
            rows = []
        elif kind == "wifi":
            stmt = select(WifiNetwork).where(WifiNetwork.hidden.is_(False))
            if device_id is not None:
                stmt = stmt.where(WifiNetwork.device_id == (await _device(session, device_id)).id)
            else:
                stmt = stmt.where(WifiNetwork.device_id.in_(list(await _visible_devices(session)) or [0]))
            networks = (await session.scalars(stmt.order_by(WifiNetwork.ssid, WifiNetwork.radio))).all()
            latest = {
                m.wifi_id: m
                for m in (
                    await session.scalars(
                        select(WifiMetric)
                        .ext(distinct_on(WifiMetric.wifi_id))
                        .where(WifiMetric.wifi_id.in_([w.id for w in networks] or [0]), WifiMetric.time >= since)
                        .order_by(WifiMetric.wifi_id, WifiMetric.time.desc())
                    )
                ).all()
            }
            rows = [
                Row(
                    key=str(w.id),
                    label=f"{w.ssid} ({RADIO.get(w.radio or '', w.radio)})" if w.radio else w.ssid,
                    device_id=w.device_id,
                    values={
                        "clients": _num(w.clients),
                        "rx_bps": _num(latest[w.id].rx_bps) if w.id in latest else None,
                        "tx_bps": _num(latest[w.id].tx_bps) if w.id in latest else None,
                    },
                )
                for w in networks
            ]
        elif kind == "checks":
            from .checks import list_checks

            # Bez adresów celu – te same dane może dostać pulpit publiczny
            rows = [
                Row(
                    key=str(c.id),
                    label=c.name,
                    values={
                        "up": 1.0 if c.status == "up" else 0.0 if c.status == "down" else None,
                        "latency_ms": c.last_latency_ms,
                        "loss_percent": c.loss_percent,
                        "availability_percent": c.availability_24h,
                        "cert_days": c.cert_days,
                    },
                )
                for c in await list_checks()
                if c.enabled
            ]
        elif kind == "services":
            if not mods.get("agents", True):
                raise HTTPException(404, "Moduł agentów jest wyłączony")
            device = await _device(session, device_id)
            agent = await session.scalar(select(Agent).where(Agent.device_id == device.id))
            items = (((agent.inventory or {}).get("services") or {}).get("items") or []) if agent else []
            rows = [
                Row(
                    key=s["name"],
                    label=s["name"].removesuffix(".service"),
                    device_id=device.id,
                    values={
                        # aktywna (także jednorazowa „exited”) / z błędem, brak usługi albo zatrzymana / w trakcie zmiany
                        "up": 1.0 if s.get("active") == "active" else 0.0 if s.get("active") in ("failed", "missing", "inactive") else None,
                        "mem_bytes": _num(s.get("mem_bytes")),
                        "uptime_s": _num(s.get("uptime_s")),
                    },
                )
                for s in sorted(items, key=lambda s: s.get("name", ""))
            ]
        elif kind == "containers":
            if not mods.get("agents", True):
                raise HTTPException(404, "Moduł agentów jest wyłączony")
            device = await _device(session, device_id)
            agent = await session.scalar(select(Agent).where(Agent.device_id == device.id))
            items = ((agent.inventory or {}).get("containers") or []) if agent else []
            rows = [
                Row(
                    key=c["name"],
                    label=c["name"],
                    device_id=device.id,
                    values={"up": 1.0 if c.get("state") == "running" else 0.0, "cpu_percent": _num(c.get("cpu_percent")), "mem_bytes": _num(c.get("mem_bytes"))},
                )
                for c in sorted(items, key=lambda c: c.get("name", ""))
            ]
        else:  # clients
            if not mods.get("unifi", True):
                raise HTTPException(404, "Moduł UniFi jest wyłączony")
            clients = (await session.scalars(select(NetworkClient).where(NetworkClient.is_wired.is_(False)).order_by(NetworkClient.name))).all()
            # Kluczem jest kolejność, nie MAC – te same dane może pokazać pulpit publiczny
            rows = [
                Row(
                    key=str(i),
                    label=c.name or c.essid or "?",
                    values={
                        "signal_dbm": _num(c.signal_dbm),
                        "rx_rate_kbps": _num(c.rx_rate_kbps),
                        "tx_rate_kbps": _num(c.tx_rate_kbps),
                        "connected_s": _num(c.connected_s),
                    },
                )
                for i, c in enumerate(clients)
            ]
    if kind == "disks":
        status = await device_server(device.id)
        rows = [
            Row(
                key=d.mount,
                label=d.mount,
                device_id=device.id,
                values={"used_percent": d.used_percent, "used_bytes": float(d.used_bytes), "free_bytes": float(d.total_bytes - d.used_bytes), "total_bytes": float(d.total_bytes)},
            )
            for d in sorted(status.disks if status else [], key=lambda d: d.mount)
        ]
    return CollectionOut(kind=kind, rows=rows[:MAX_ROWS])


# --- stany w czasie -------------------------------------------------------------------------


class Segment(BaseModel):
    start: datetime
    end: datetime
    state: Literal["up", "down", "unknown"]


class StateItem(BaseModel):
    kind: Literal["device", "interface", "check"]
    id: int
    label: str
    segments: list[Segment]


class StatesOut(BaseModel):
    start: datetime
    end: datetime
    bucket_s: int
    items: list[StateItem]


def _ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        ids = [int(x) for x in raw.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(422, "Lista identyfikatorów: liczby po przecinku") from exc
    return list(dict.fromkeys(ids))


def segments(
    buckets: list[tuple[datetime, bool | None]], start: datetime, end: datetime, bucket_s: int, tolerance_s: int = 0
) -> list[Segment]:
    """Kubełki (początek, wszystkie próbki OK?) → odcinki stanów. Kubełek bez próbek = brak danych, ale przerwa
    nie dłuższa niż `tolerance_s` (spóźniony odczyt) przejmuje stan sprzed niej."""
    step = timedelta(seconds=bucket_s)
    tolerance = timedelta(seconds=tolerance_s)
    out: list[Segment] = []

    def add(a: datetime, b: datetime, state: str) -> None:
        a, b = max(a, start), min(b, end)
        if b <= a:
            return
        if out and out[-1].state == state and out[-1].end >= a:
            out[-1].end = b
        else:
            out.append(Segment(start=a, end=b, state=state))

    def gap(a: datetime, b: datetime) -> None:
        known = out and out[-1].state != "unknown" and out[-1].end >= a
        add(a, b, out[-1].state if known and b - a <= tolerance else "unknown")

    cursor = start
    for t, ok in sorted(buckets, key=lambda x: x[0]):
        if t > cursor:
            gap(cursor, t)
        add(t, t + step, "unknown" if ok is None else "up" if ok else "down")
        cursor = max(cursor, t + step)
    if cursor < end:
        gap(cursor, end)
    return out


@router.get("/states", response_model=StatesOut)
async def states(devices: str | None = None, interfaces: str | None = None, minutes: int = MinutesQuery, checks: str | None = None):
    """Stany urządzeń, portów i sprawdzeń dostępności w czasie. Bez listy – wszystkie urządzenia (bez portów)."""
    device_ids, interface_ids, check_ids = _ids(devices), _ids(interfaces), _ids(checks)
    if len(device_ids) + len(interface_ids) + len(check_ids) > MAX_STATE_ITEMS:
        raise HTTPException(422, f"Najwyżej {MAX_STATE_ITEMS} pozycji")
    end = datetime.now(UTC)
    start = end - timedelta(minutes=minutes)
    bucket_s = _bucket_seconds(minutes)
    tolerance_s = 3 * max(bucket_s, settings.poll_interval)
    stride = text(f"INTERVAL '{bucket_s} seconds'")
    origin = text("TIMESTAMPTZ '2000-01-01 00:00:00+00'")
    items: list[StateItem] = []
    async with Session() as session:
        visible = await _visible_devices(session)
        if not device_ids and not interface_ids and not check_ids:
            device_ids = list(visible)[:MAX_STATE_ITEMS]
        if device_ids:
            bucket = func.date_bin(stride, DeviceMetric.time, origin).label("b")
            rows = (
                await session.execute(
                    select(DeviceMetric.device_id, bucket, func.bool_and(DeviceMetric.reachable))
                    .where(DeviceMetric.device_id.in_(device_ids), DeviceMetric.time >= start)
                    .group_by(DeviceMetric.device_id, "b")
                )
            ).all()
            per: dict[int, list] = {}
            for dev, b, ok in rows:
                per.setdefault(dev, []).append((b, ok))
            for dev in device_ids:
                if dev in visible:
                    items.append(StateItem(kind="device", id=dev, label=visible[dev].name, segments=segments(per.get(dev, []), start, end, bucket_s, tolerance_s)))
        if interface_ids:
            ports = {
                p.id: p
                for p in (await session.scalars(select(Interface).where(Interface.id.in_(interface_ids), Interface.device_id.in_(list(visible) or [0])))).all()
            }
            bucket = func.date_bin(stride, InterfaceMetric.time, origin).label("b")
            rows = (
                await session.execute(
                    select(InterfaceMetric.interface_id, bucket, func.bool_and(InterfaceMetric.oper_up))
                    .where(InterfaceMetric.interface_id.in_(list(ports) or [0]), InterfaceMetric.time >= start)
                    .group_by(InterfaceMetric.interface_id, "b")
                )
            ).all()
            per = {}
            for iface, b, ok in rows:
                per.setdefault(iface, []).append((b, ok))
            for iface in interface_ids:
                if (p := ports.get(iface)) is not None:
                    label = f"{visible[p.device_id].name}: {p.label or p.name}"
                    items.append(StateItem(kind="interface", id=iface, label=label, segments=segments(per.get(iface, []), start, end, bucket_s, tolerance_s)))
        if check_ids:
            found = {c.id: c for c in (await session.scalars(select(Check).where(Check.id.in_(check_ids)))).all()}
            bucket = func.date_bin(stride, CheckMetric.time, origin).label("b")
            rows = (
                await session.execute(
                    select(CheckMetric.check_id, bucket, func.bool_and(CheckMetric.up))
                    .where(CheckMetric.check_id.in_(list(found) or [0]), CheckMetric.time >= start)
                    .group_by(CheckMetric.check_id, "b")
                )
            ).all()
            per = {}
            for check_id, b, ok in rows:
                per.setdefault(check_id, []).append((b, ok))
            for check_id in check_ids:
                if (c := found.get(check_id)) is not None:
                    # sprawdzenia mają własny odstęp – przerwa krótsza niż trzy odstępy to nie „brak danych”
                    tol = 3 * max(bucket_s, c.interval_s)
                    items.append(StateItem(kind="check", id=check_id, label=c.name, segments=segments(per.get(check_id, []), start, end, bucket_s, tol)))
    return StatesOut(start=start, end=end, bucket_s=bucket_s, items=items)
