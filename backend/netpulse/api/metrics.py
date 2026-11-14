"""Szeregi czasowe metryk do wykresów."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import column, func, select, table, text

from .. import aggregates
from ..db import Session, timescale_available
from ..db.models import (
    NON_SNMP_DRIVERS,
    Device,
    DeviceMetric,
    Interface,
    InterfaceMetric,
    Metric,
    PoePortMetric,
    ProxmoxNode,
    WifiMetric,
    WifiNetwork,
)
from .devices import poe_port_idx
from .schemas import Point
from .security import require_user

router = APIRouter(prefix="/api", tags=["metryki"], dependencies=[Depends(require_user)])

# Do roku wstecz: powyżej 7 dni dane idą z agregatów godzinowych (aggregates.py)
MinutesQuery = Query(60, ge=5, le=60 * 24 * 366, description="zakres wstecz w minutach")
# Porównanie w czasie: to samo okno przesunięte wstecz (np. 1440 = dzień wcześniej)
OffsetQuery = Query(0, ge=0, le=60 * 24 * 366, description="przesunięcie okna wstecz w minutach")


def window(minutes: int, offset: int = 0) -> tuple[datetime, datetime]:
    """Okno wykresu [od, do). Bez przesunięcia „do” jest z zapasem w przyszłości (próbki z bieżącej chwili)."""
    now = datetime.now(UTC)
    until = now - timedelta(minutes=offset) if offset else now + timedelta(days=1)
    return until - timedelta(minutes=minutes) if offset else now - timedelta(minutes=minutes), until


def _bucket_seconds(minutes: int) -> int:
    """Rozmiar kubełka tak, żeby wykres miał ~300 punktów, nie mniej niż 30 s (długie zakresy: pełne godziny)."""
    return aggregates.bucket_seconds(minutes)


async def _aggregate_series(agg: aggregates.Aggregate, obj_id: int, columns: list[str], minutes: int, offset: int = 0) -> list[Point]:
    """Szereg z agregatu godzinowego, przeliczony na większe kubełki (długie zakresy wykresów)."""
    since, until = window(minutes, offset)
    # Agregat godzinowy może nie mieć wszystkich kolumn tabeli – te serie są wtedy puste
    wanted, columns = columns, [c for c in columns if c in agg.columns]
    view = table(agg.view, column("bucket"), column(agg.key), *[column(c) for c in columns])
    bucket = func.date_bin(
        text(f"INTERVAL '{_bucket_seconds(minutes)} seconds'"), view.c.bucket, text("TIMESTAMPTZ '2000-01-01 00:00:00+00'")
    ).label("b")
    stmt = (
        select(bucket, *[func.avg(view.c[c]).label(c) for c in columns])
        .where(view.c[agg.key] == obj_id, view.c.bucket >= since, view.c.bucket < until)
        .group_by("b")
        .order_by("b")
    )
    async with Session() as session:
        rows = (await session.execute(stmt)).all()
    return [
        Point(
            time=r[0],
            values={**dict.fromkeys(wanted), **{c: (float(v) if v is not None else None) for c, v in zip(columns, r[1:], strict=True)}},
        )
        for r in rows
    ]


async def _series(
    model, id_col, obj_id: int | None, columns: list[str], minutes: int, extra_where: tuple = (), offset: int = 0
) -> list[Point]:
    """Szereg czasowy; `id_col=None` dla tabel bez klucza obiektu (np. stan serwera)."""
    since, until = window(minutes, offset)
    timescale = await timescale_available()
    agg = aggregates.BY_SOURCE.get(model.__tablename__)
    if agg is not None and obj_id is not None and aggregates.use_aggregate(minutes, timescale):
        return await _aggregate_series(agg, obj_id, columns, minutes, offset)
    async with Session() as session:
        cols = [getattr(model, c) for c in columns]
        where = [model.time >= since, model.time < until, *extra_where] + ([id_col == obj_id] if id_col is not None else [])
        if timescale:
            bucket = func.time_bucket(text(f"INTERVAL '{_bucket_seconds(minutes)} seconds'"), model.time)
            stmt = (
                select(bucket.label("bucket"), *[func.avg(c).label(c.key) for c in cols])
                .where(*where)
                .group_by("bucket")
                .order_by("bucket")
            )
        else:
            stmt = (
                select(model.time.label("bucket"), *cols)
                .where(*where)
                .order_by(model.time)
            )
        rows = (await session.execute(stmt)).all()
    return [
        Point(time=r[0], values={c: (float(v) if v is not None else None) for c, v in zip(columns, r[1:], strict=True)})
        for r in rows
    ]


async def _exists(model, obj_id: int, what: str) -> None:
    async with Session() as session:
        if await session.get(model, obj_id) is None:
            raise HTTPException(404, f"Nie ma takiego obiektu: {what}")


@router.get("/devices/{device_id}/metrics", response_model=list[Point])
async def device_metrics(device_id: int, minutes: int = MinutesQuery, offset: int = OffsetQuery):
    await _exists(Device, device_id, "urządzenie")
    return await _series(
        DeviceMetric,
        DeviceMetric.device_id,
        device_id,
        ["cpu_percent", "mem_used_percent", "load1", "poll_ms"],
        minutes,
        offset=offset,
    )


@router.get("/interfaces/{interface_id}/metrics", response_model=list[Point])
async def interface_metrics(interface_id: int, minutes: int = MinutesQuery, offset: int = OffsetQuery):
    await _exists(Interface, interface_id, "port")
    return await _series(
        InterfaceMetric,
        InterfaceMetric.interface_id,
        interface_id,
        ["in_bps", "out_bps", "in_errors", "out_errors", "in_discards", "out_discards"],
        minutes,
        offset=offset,
    )


@router.get("/interfaces/{interface_id}/poe-metrics", response_model=list[Point])
async def interface_poe_metrics(interface_id: int, minutes: int = MinutesQuery):
    """Moc PoE na porcie w czasie (dane z kontrolera UniFi); pusto dla portów bez PoE."""
    async with Session() as session:
        iface = await session.get(Interface, interface_id)
        if iface is None:
            raise HTTPException(404, "Nie ma takiego obiektu: port")
    port_idx = poe_port_idx(iface.name)
    if port_idx is None:
        return []
    return await _series(
        PoePortMetric,
        PoePortMetric.device_id,
        iface.device_id,
        ["power_w"],
        minutes,
        extra_where=(PoePortMetric.port_idx == port_idx,),
    )


# Źródło wykresu z agenta → {klucz serii: (nazwa w `metrics`, mnożnik)}. Dyski: bajty/s → bity/s, jak reszta przepustowości.
AGENT_SOURCES: dict[str, dict[str, tuple[str, float]]] = {
    "agent_net": {"rx_bps": ("net_rx_bps", 1.0), "tx_bps": ("net_tx_bps", 1.0)},
    "agent_disk": {"read_bps": ("disk_read_bps", 8.0), "write_bps": ("disk_write_bps", 8.0)},
    "agent_temp": {"temp_c": ("temp_c", 1.0)},
    "agent_container": {"container_cpu_percent": ("container_cpu_percent", 1.0), "container_mem_bytes": ("container_mem_bytes", 1.0)},
    # Maszyna Proxmox: kolektor zapisuje już bity/s (sieć) i bajty/s (dysk) – dysk przeliczamy na bity jak przy agencie
    "pve_guest": {
        "guest_cpu_percent": ("guest_cpu_percent", 1.0),
        "guest_mem_bytes": ("guest_mem_bytes", 1.0),
        "rx_bps": ("guest_net_rx_bps", 1.0),
        "tx_bps": ("guest_net_tx_bps", 1.0),
        "read_bps": ("guest_disk_read_bps", 8.0),
        "write_bps": ("guest_disk_write_bps", 8.0),
    },
    # Czujniki urządzeń SNMP (od 0.50.0, MikroTik): klucz = nazwa czujnika albo portu
    "snmp_sensor": {
        "temp_c": ("temp_c", 1.0),
        "fan_rpm": ("fan_rpm", 1.0),
        "voltage_v": ("voltage_v", 1.0),
        "current_a": ("current_a", 1.0),
        "power_w": ("power_w", 1.0),
        "channel_util_percent": ("channel_util_percent", 1.0),
    },
    "snmp_poe": {"poe_power_w": ("poe_power_w", 1.0), "poe_voltage_v": ("poe_voltage_v", 1.0)},
    # Łącza WAN bramy UniFi (od 0.55.0): brama pinguje internet każdym łączem, też zapasowym; klucz = interfejs łącza
    # … i bramy OPNsense (od 0.81.0: opóźnienie, rozrzut i utrata pakietów z dpinger)
    "wan_latency": {
        "latency_ms": ("wan_latency_ms", 1.0),
        "loss_percent": ("wan_loss_percent", 1.0),
        "jitter_ms": ("wan_jitter_ms", 1.0),
        "availability_percent": ("wan_availability_percent", 1.0),
    },
    "wan_ping": {"latency_ms": ("wan_ping_ms", 1.0)},
    # Testy prędkości bramy UniFi (od 0.70.0): wynik dokładnie z bramy, punkt w chwili testu; klucz = interfejs łącza
    "speedtest": {"down_bps": ("speedtest_down_bps", 1.0), "up_bps": ("speedtest_up_bps", 1.0), "ping_ms": ("speedtest_ping_ms", 1.0)},
    # Klienci VPN bramy UniFi (od 0.57.0): klucz = nazwa klienta; pobieranie = ruch do klienta
    "vpn": {"down_bps": ("vpn_down_bps", 1.0), "up_bps": ("vpn_up_bps", 1.0), "connected": ("vpn_connected", 1.0)},
    # Urządzenia w sieci LAN za OPNsense (od 0.83.0): próbka ruchu co 30 s; klucz = MAC urządzenia
    "lan_client": {"down_bps": ("client_down_bps", 1.0), "up_bps": ("client_up_bps", 1.0)},
    "snmp_sfp": {
        "sfp_rx_dbm": ("sfp_rx_dbm", 1.0),
        "sfp_tx_dbm": ("sfp_tx_dbm", 1.0),
        "sfp_temp_c": ("sfp_temp_c", 1.0),
        "sfp_voltage_v": ("sfp_voltage_v", 1.0),
    },
}
AgentSourceKind = Literal[
    "agent_cpu",
    "agent_net",
    "agent_disk",
    "agent_temp",
    "agent_container",
    "pve_guest",
    "snmp_sensor",
    "snmp_poe",
    "snmp_sfp",
    "wan_latency",
    "wan_ping",
    "speedtest",
    "vpn",
    "lan_client",
]
# Lista kluczy do edytora wykresu: źródło → nazwy metryk, z których bierzemy klucze
AGENT_KEY_NAMES: dict[str, tuple[str, ...]] = {
    "agent_net": ("net_rx_bps",),
    "agent_disk": ("disk_read_bps",),
    "agent_temp": ("temp_c",),
    "agent_container": ("container_up",),
    "pve_guest": ("guest_up",),
    "snmp_sensor": ("temp_c", "fan_rpm", "voltage_v", "current_a", "power_w", "channel_util_percent"),
    "snmp_poe": ("poe_power_w",),
    "snmp_sfp": ("sfp_rx_dbm",),
    "wan_latency": ("wan_latency_ms",),
    "wan_ping": ("wan_ping_ms",),
    "speedtest": ("speedtest_down_bps",),
    "vpn": ("vpn_connected",),
    "lan_client": ("client_down_bps",),
}


# Źródła z rzadkimi punktami (zdarzenia, nie pomiar co cykl): klucze szukane w ostatnich 30 dniach, nie w godzinie
RARE_SOURCES = ("speedtest",)


async def _same_server_devices(session, device_id: int) -> list[int]:
    """Maszyna Proxmox może przejść na inny węzeł (migracja) – wykres bierze dane ze wszystkich węzłów serwera."""
    server_id = await session.scalar(select(ProxmoxNode.server_id).where(ProxmoxNode.device_id == device_id))
    if server_id is None:
        return [device_id]
    return list((await session.scalars(select(ProxmoxNode.device_id).where(ProxmoxNode.server_id == server_id))).all())


def _bucket(minutes: int, timescale: bool):
    if timescale:
        return func.time_bucket(text(f"INTERVAL '{_bucket_seconds(minutes)} seconds'"), Metric.time)
    return Metric.time


@router.get("/devices/{device_id}/agent-metrics", response_model=list[Point])
async def agent_metrics(device_id: int, source: AgentSourceKind, key: str = "", minutes: int = MinutesQuery, offset: int = OffsetQuery):
    """Szereg z ogólnej tabeli `metrics` dla wykresu. `agent_cpu`: najbardziej i średnio obciążony rdzeń."""
    await _exists(Device, device_id, "urządzenie")
    since, until = window(minutes, offset)
    timescale = await timescale_available()
    bucket = _bucket(minutes, timescale).label("bucket")
    async with Session() as session:
        devices = await _same_server_devices(session, device_id) if source == "pve_guest" else [device_id]
        base = [Metric.device_id.in_(devices), Metric.time >= since, Metric.time < until]
        if source == "agent_cpu":
            rows = (
                await session.execute(
                    select(bucket, func.max(Metric.value), func.avg(Metric.value))
                    .where(*base, Metric.name == "cpu_core_percent")
                    .group_by("bucket")
                    .order_by("bucket")
                )
            ).all()
            return [Point(time=t, values={"core_max_percent": mx, "core_avg_percent": avg}) for t, mx, avg in rows]
        series = AGENT_SOURCES[source]
        by_name = {name: (series_key, factor) for series_key, (name, factor) in series.items()}
        rows = (
            await session.execute(
                select(bucket, Metric.name, func.avg(Metric.value))
                .where(*base, Metric.name.in_(list(by_name)), Metric.key == key)
                .group_by("bucket", Metric.name)
                .order_by("bucket")
            )
        ).all()
    points: dict[datetime, dict[str, float | None]] = {}
    for t, name, value in rows:
        series_key, factor = by_name[name]
        points.setdefault(t, dict.fromkeys(series))[series_key] = float(value) * factor if value is not None else None
    return [Point(time=t, values=v) for t, v in points.items()]


@router.get("/devices/{device_id}/agent-keys")
async def agent_keys(device_id: int) -> dict[str, list[str]]:
    """Interfejsy, dyski, czujniki i kontenery widziane w ostatniej godzinie – do wyboru w edytorze wykresu.
    Źródła `snmp_*` tylko dla urządzeń SNMP: temperatury serwera z agentem to `agent_temp`."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=1)
    rare = sorted({n for source in RARE_SOURCES for n in AGENT_KEY_NAMES[source]})
    async with Session() as session:
        device = await session.get(Device, device_id)
        if device is None:
            raise HTTPException(404, "Nie ma takiego obiektu: urządzenie")
        snmp = device.driver not in NON_SNMP_DRIVERS
        devices = await _same_server_devices(session, device_id)
        rows = (
            await session.execute(
                select(Metric.name, Metric.key)
                .where(
                    Metric.device_id.in_(devices),
                    Metric.time >= since,
                    Metric.name.in_(sorted({n for names in AGENT_KEY_NAMES.values() for n in names} - set(rare))),
                )
                .distinct()
                .order_by(Metric.key, Metric.name)
            )
        ).all()
        # Testy prędkości zdarzają się rzadko – łącze z testem z ostatnich 30 dni też jest do wyboru
        rows += (
            await session.execute(
                select(Metric.name, Metric.key)
                .where(Metric.device_id.in_(devices), Metric.time >= now - timedelta(days=30), Metric.name.in_(rare))
                .distinct()
                .order_by(Metric.key, Metric.name)
            )
        ).all()
    out: dict[str, list[str]] = {source: [] for source in AGENT_KEY_NAMES}
    for name, key in rows:
        for source, names in AGENT_KEY_NAMES.items():
            if source.startswith("snmp_") and not snmp:
                continue
            if name in names and key not in out[source]:
                out[source].append(key)
    return out


@router.get("/wifi/{wifi_id}/metrics", response_model=list[Point])
async def wifi_metrics(wifi_id: int, minutes: int = MinutesQuery, offset: int = OffsetQuery):
    await _exists(WifiNetwork, wifi_id, "sieć WiFi")
    return await _series(WifiMetric, WifiMetric.wifi_id, wifi_id, ["clients", "rx_bps", "tx_bps"], minutes, offset=offset)
