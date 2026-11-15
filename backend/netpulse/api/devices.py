"""Urządzenia: lista, dodawanie, edycja, usuwanie, test SNMP; porty i sieci WiFi."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import distinct_on

from ..collector import credentials_for
from ..db import Session
from ..db.models import (
    NON_SNMP_DRIVERS,
    Device,
    Interface,
    InterfaceMetric,
    Metric,
    UnifiApiDevice,
    WifiNetwork,
)
from ..drivers import PollResult
from ..modules import hidden_drivers, read_modules
from ..probe import probe as snmp_probe
from ..snmp import SnmpCredentials, SnmpError
from .maintenance import active_device_ids
from .schemas import (
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
    InterfaceDetailOut,
    InterfaceOut,
    PoeOut,
    ProbeInterface,
    ProbeOut,
    ProbeWifi,
    SensorOut,
    SensorsOut,
    SfpOut,
    SnmpTarget,
    WifiOut,
    credential_error,
)
from .security import require_user

router = APIRouter(prefix="/api", tags=["urządzenia"], dependencies=[Depends(require_user)])

# Porty switcha UniFi w SNMP: ifName 0/1…0/8 – ten sam numer co port PoE w kontrolerze
_UNIFI_PORT = re.compile(r"^0/(\d+)$")

# Pola SNMP, które przy SNMPv3 nie mają community i odwrotnie
_V3_FIELDS = ("v3_username", "v3_auth_protocol", "v3_auth_key", "v3_priv_protocol", "v3_priv_key", "v3_context")


def _creds(t: SnmpTarget) -> SnmpCredentials:
    return SnmpCredentials(
        version=t.snmp_version,
        community=t.community or "public",
        username=t.v3_username,
        auth_protocol=t.v3_auth_protocol,
        auth_key=t.v3_auth_key,
        priv_protocol=t.v3_priv_protocol,
        priv_key=t.v3_priv_key,
        context_name=t.v3_context or "",
    )


async def _probe_or_422(host: str, port: int, creds: SnmpCredentials, driver: str) -> PollResult:
    try:
        return await snmp_probe(host, port, creds, driver)
    except SnmpError as exc:
        raise HTTPException(422, f"Brak odpowiedzi SNMP z {host}: {exc}") from exc


def _probe_out(r: PollResult) -> ProbeOut:
    s = r.system
    return ProbeOut(
        driver=r.driver,
        name=s.name,
        vendor=s.vendor,
        model=s.model,
        firmware=s.firmware,
        kind=s.kind,
        uptime_s=s.uptime_s,
        interfaces=[
            ProbeInterface(
                if_index=i.if_index,
                name=i.name,
                label=i.label,
                alias=i.alias,
                role=i.role,
                hidden=i.hidden,
                oper_status=i.oper_status,
                speed_mbps=i.speed_mbps,
            )
            for i in r.interfaces
        ],
        wifi=[
            ProbeWifi(ssid=w.ssid, radio=w.radio, channel=w.channel, clients=w.clients, hidden=w.hidden)
            for w in r.wifi
        ],
    )


async def _get_device(session, device_id: int) -> Device:
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Nie ma takiego urządzenia")
    return device


async def _host_taken(session, host: str, except_id: int | None = None, *, convertible: bool = False) -> bool:
    """Adres zajęty przez inne urządzenie. `convertible`: urządzenie z API UniFi się nie liczy (dodanie przez SNMP je przejmie)."""
    stmt = select(Device.id).where(Device.host == host)
    if convertible:
        stmt = stmt.where(Device.driver != "unifi_api")
    if except_id is not None:
        stmt = stmt.where(Device.id != except_id)
    return await session.scalar(stmt) is not None


# --- urządzenia --------------------------------------------------------------


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices():
    """Urządzenia bez tych, które należą do wyłączonych modułów (serwery z agentem, urządzenia UniFi bez SNMP)."""
    async with Session() as session:
        hidden = hidden_drivers(await read_modules(session))
        devices = (await session.scalars(select(Device).where(Device.driver.not_in(hidden or ("",))).order_by(Device.id))).all()
        return await _mark_maintenance(session, devices)


async def _mark_maintenance(session, devices: list[Device]) -> list[Device]:
    """Znacznik „prace serwisowe” (zwykły atrybut obiektu, nie kolumna) – DeviceOut.maintenance."""
    everything, ids = await active_device_ids(session)
    for d in devices:
        d.maintenance = everything or d.id in ids
    return devices


@router.post("/probe", response_model=ProbeOut)
async def probe_target(body: SnmpTarget):
    """Test połączenia SNMP bez zapisu – do formularza „Dodaj urządzenie”."""
    if err := body.credential_error():
        raise HTTPException(422, err)
    return _probe_out(await _probe_or_422(body.host, body.port, _creds(body), body.driver))


@router.post("/devices", response_model=DeviceOut, status_code=201)
async def create_device(body: DeviceCreate, probe: bool = Query(True, description="najpierw sprawdź SNMP")):
    if err := body.credential_error():
        raise HTTPException(422, err)
    async with Session() as session:
        if await _host_taken(session, body.host, convertible=True):
            raise HTTPException(409, f"Urządzenie {body.host} już jest dodane")
    result = await _probe_or_422(body.host, body.port, _creds(body), body.driver) if probe else None

    values = body.model_dump()
    if body.snmp_version == "3":
        values["community"] = None
    else:
        values.update(dict.fromkeys(_V3_FIELDS))
    device = Device(**values)
    if result:
        # Od razu pokaż, co to za sprzęt – kolektor uzupełni resztę przy pierwszym odczycie
        s = result.system
        device.detected_driver = result.driver
        device.kind = s.kind
        device.vendor, device.model, device.firmware = s.vendor, s.model, s.firmware
        device.sys_name, device.sys_descr, device.sys_object_id = s.name, s.descr, s.object_id
        device.uptime_s = s.uptime_s
    async with Session() as session, session.begin():
        existing = await session.scalar(select(Device).where(Device.host == body.host))
        if existing is not None and existing.driver == "unifi_api":
            # Urządzenie z oficjalnego API kontrolera UniFi przechodzi na SNMP: to samo urządzenie (historia zostaje),
            # a kolektor UniFi nie założy go ponownie (powiązanie bez urządzenia = pominięte)
            await session.execute(update(UnifiApiDevice).where(UnifiApiDevice.device_id == existing.id).values(device_id=None))
            for field in ("name", "port", "enabled", "driver", "snmp_version", "community", *_V3_FIELDS):
                setattr(existing, field, getattr(device, field))
            for field in ("detected_driver", "kind", "vendor", "model", "firmware", "sys_name", "sys_descr", "sys_object_id", "uptime_s"):
                if getattr(device, field, None) is not None:
                    setattr(existing, field, getattr(device, field))
            existing.status, existing.last_error = "unknown", None
            await session.flush()
            await session.refresh(existing)
            return existing
        if await _host_taken(session, body.host):
            raise HTTPException(409, f"Urządzenie {body.host} już jest dodane")
        session.add(device)
        await session.flush()
        await session.refresh(device)  # id i created_at nadaje baza
    return device


@router.get("/devices/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int):
    async with Session() as session:
        (device,) = await _mark_maintenance(session, [await _get_device(session, device_id)])
        return device


@router.patch("/devices/{device_id}", response_model=DeviceOut)
async def update_device(device_id: int, body: DeviceUpdate):
    """Zmiana wybranych pól. Sekrety (community, klucze v3) pominięte w żądaniu zostają bez zmian."""
    changes = body.model_dump(exclude_unset=True)
    for field in ("name", "enabled", "host", "port", "driver", "snmp_version"):
        if field in changes and changes[field] is None:
            raise HTTPException(422, f"Pole {field} nie może być puste")
    async with Session() as session, session.begin():
        device = await _get_device(session, device_id)
        if device.driver in NON_SNMP_DRIVERS and set(changes) - {"name", "enabled"}:
            raise HTTPException(409, "To urządzenie nie używa SNMP (agent albo kontroler UniFi) – zmienić można tylko nazwę i włączenie")
        if "host" in changes and await _host_taken(session, changes["host"], except_id=device_id):
            raise HTTPException(409, f"Urządzenie {changes['host']} już jest dodane")
        for field, value in changes.items():
            setattr(device, field, value)
        if err := credential_error(
            device.snmp_version,
            device.community,
            device.v3_username,
            device.v3_auth_protocol,
            device.v3_auth_key,
            device.v3_priv_protocol,
            device.v3_priv_key,
        ):
            raise HTTPException(422, err)
    return device


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(device_id: int):
    """Usuwa urządzenie razem z portami i historią metryk."""
    async with Session() as session, session.begin():
        await session.delete(await _get_device(session, device_id))


@router.post("/devices/{device_id}/probe", response_model=ProbeOut)
async def probe_device(device_id: int):
    """Test SNMP zapisanego urządzenia (z zapisanymi danymi logowania)."""
    async with Session() as session:
        device = await _get_device(session, device_id)
    if device.driver in NON_SNMP_DRIVERS:
        raise HTTPException(409, "To urządzenie nie używa SNMP – stan widać w Ustawienia → Agenci albo Kontrolery UniFi")
    return _probe_out(await _probe_or_422(device.host, device.port, credentials_for(device), device.driver))


# --- porty i WiFi ------------------------------------------------------------


@router.get("/devices/{device_id}/interfaces", response_model=list[InterfaceOut])
async def device_interfaces(device_id: int, include_hidden: bool = False):
    async with Session() as session:
        await _get_device(session, device_id)
        stmt = select(Interface).where(Interface.device_id == device_id).order_by(Interface.if_index)
        if not include_hidden:
            stmt = stmt.where(Interface.hidden.is_(False))
        interfaces = (await session.scalars(stmt)).all()
        if not interfaces:
            return []
        # Ostatnia próbka dla każdego interfejsu (z ostatnich 5 minut)
        since = datetime.now(UTC) - timedelta(minutes=5)
        latest = (
            select(InterfaceMetric.interface_id, InterfaceMetric.in_bps, InterfaceMetric.out_bps)
            .ext(distinct_on(InterfaceMetric.interface_id))
            .where(
                InterfaceMetric.interface_id.in_([i.id for i in interfaces]),
                InterfaceMetric.time >= since,
            )
            .order_by(InterfaceMetric.interface_id, InterfaceMetric.time.desc())
        )
        last = {r.interface_id: r for r in await session.execute(latest)}
    out = []
    for i in interfaces:
        item = InterfaceOut.model_validate(i)
        if i.id in last:
            item.in_bps, item.out_bps = last[i.id].in_bps, last[i.id].out_bps
        out.append(item)
    return out


def poe_port_idx(interface_name: str) -> int | None:
    """Numer portu PoE z kontrolera dla interfejsu z SNMP (np. „0/5” → 5); None, gdy nazwa tego nie mówi."""
    m = _UNIFI_PORT.match(interface_name)
    return int(m.group(1)) if m else None


@router.get("/interfaces/{interface_id}", response_model=InterfaceDetailOut)
async def get_interface(interface_id: int):
    """Jeden port z urządzeniem i bieżącym ruchem (strona szczegółów portu)."""
    async with Session() as session:
        iface = await session.get(Interface, interface_id)
        if iface is None:
            raise HTTPException(404, "Nie ma takiego portu")
        device = await _get_device(session, iface.device_id)
        since = datetime.now(UTC) - timedelta(minutes=5)
        last = (
            await session.execute(
                select(InterfaceMetric.in_bps, InterfaceMetric.out_bps)
                .where(InterfaceMetric.interface_id == interface_id, InterfaceMetric.time >= since)
                .order_by(InterfaceMetric.time.desc())
                .limit(1)
            )
        ).first()
    out = InterfaceDetailOut.model_validate(
        {
            **InterfaceOut.model_validate(iface).model_dump(),
            "device_id": device.id,
            "device_name": device.name,
            "device_kind": device.kind,
            "last_seen_at": iface.last_seen_at,
            "poe_port_idx": poe_port_idx(iface.name),
        }
    )
    if last:
        out.in_bps, out.out_bps = last.in_bps, last.out_bps
    return out


@router.get("/devices/{device_id}/wifi", response_model=list[WifiOut])
async def device_wifi(device_id: int, include_hidden: bool = False):
    async with Session() as session:
        await _get_device(session, device_id)
        stmt = select(WifiNetwork).where(WifiNetwork.device_id == device_id).order_by(WifiNetwork.key)
        if not include_hidden:
            stmt = stmt.where(WifiNetwork.hidden.is_(False))
        return (await session.scalars(stmt)).all()


SENSOR_METRICS = ("temp_c", "fan_rpm", "voltage_v", "current_a", "power_w", "sensor_state", "channel_util_percent")
POE_METRICS = {"poe_state": "state", "poe_power_w": "power_w", "poe_voltage_v": "voltage_v"}
SFP_METRICS = {
    "sfp_rx_dbm": "rx_dbm",
    "sfp_tx_dbm": "tx_dbm",
    "sfp_temp_c": "temp_c",
    "sfp_voltage_v": "voltage_v",
    "sfp_rx_loss": "rx_loss",
    "sfp_tx_fault": "tx_fault",
}


def _natural(text: str) -> list:
    """„ether2” przed „ether10”."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def _flag(value: float | None) -> bool | None:
    return None if value is None else value >= 1


@router.get("/devices/{device_id}/sensors", response_model=SensorsOut)
async def device_sensors(device_id: int):
    """Czujniki, PoE i SFP urządzenia SNMP (od 0.50.0: MikroTik, od 0.51.0: switche TP-Link, od 0.52.0: zajętość kanału AP UniFi) – ostatnia wartość każdego z ostatnich 10 minut."""
    since = datetime.now(UTC) - timedelta(minutes=10)
    names = (*SENSOR_METRICS, *POE_METRICS, *SFP_METRICS)
    async with Session() as session:
        device = await _get_device(session, device_id)
        if device.driver == "agent":  # temperatury serwera z agentem pokazuje karta serwera
            return SensorsOut(sensors=[], poe=[], sfp=[])
        rows = (
            await session.execute(
                select(Metric.name, Metric.key, Metric.value)
                .ext(distinct_on(Metric.name, Metric.key))
                .where(Metric.device_id == device_id, Metric.name.in_(names), Metric.time >= since)
                .order_by(Metric.name, Metric.key, Metric.time.desc())
            )
        ).all()
    sensors: list[SensorOut] = []
    poe: dict[str, dict] = {}
    sfp: dict[str, dict] = {}
    for name, key, value in rows:
        if name in POE_METRICS:
            poe.setdefault(key, {})[POE_METRICS[name]] = value
        elif name in SFP_METRICS:
            sfp.setdefault(key, {})[SFP_METRICS[name]] = value
        elif value is not None:
            sensors.append(SensorOut(key=key, metric=name, value=value))
    poe_out = [
        PoeOut(port=port, state=None if (st := p.get("state")) is None else int(st), power_w=p.get("power_w"), voltage_v=p.get("voltage_v"))
        for port, p in poe.items()
    ]
    sfp_out = [
        SfpOut(
            port=port,
            rx_dbm=v.get("rx_dbm"),
            tx_dbm=v.get("tx_dbm"),
            temp_c=v.get("temp_c"),
            voltage_v=v.get("voltage_v"),
            rx_loss=_flag(v.get("rx_loss")),
            tx_fault=_flag(v.get("tx_fault")),
        )
        for port, v in sfp.items()
    ]
    return SensorsOut(
        sensors=sorted(sensors, key=lambda s: (SENSOR_METRICS.index(s.metric), _natural(s.key))),
        poe=sorted(poe_out, key=lambda p: _natural(p.port)),
        sfp=sorted(sfp_out, key=lambda p: _natural(p.port)),
    )
