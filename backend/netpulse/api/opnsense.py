"""OPNsense API (od 0.81.0): klucz przy urządzeniu OPNsense i dane z ostatniego odczytu.

Zmiany kluczy może robić tylko administrator; odczyt – każdy zalogowany. Klucz i sekret nie wracają z API
(tylko końcówka klucza do rozpoznania). Odczyt danych: opnsense_collector.py. Opis: docs/46-opnsense-api.md.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import Session
from ..db.models import Device, OpnsenseApi
from ..freshness import is_stale
from ..modules import is_enabled, require_module
from ..opnsense import OpnsenseApi as Client
from ..opnsense import OpnsenseError, Snapshot, update_available
from .security import AdminUser, require_user

router = APIRouter(prefix="/api/opnsense", tags=["OPNsense"], dependencies=[Depends(require_user)])

KEY = r"^\S{8,255}$"


class ApiTarget(BaseModel):
    device_id: int
    port: int = Field(443, ge=1, le=65535)
    api_key: str = Field(pattern=KEY)
    api_secret: str = Field(pattern=KEY)
    verify_tls: bool = False


class ApiCreate(ApiTarget):
    enabled: bool = True


class ApiUpdate(BaseModel):
    """Pola pominięte zostają bez zmian; brak klucza albo sekretu znaczy „bez zmian”."""

    port: int | None = Field(None, ge=1, le=65535)
    api_key: str | None = Field(None, pattern=KEY)
    api_secret: str | None = Field(None, pattern=KEY)
    verify_tls: bool | None = None
    enabled: bool | None = None


class ApiOut(BaseModel):
    id: int
    device_id: int
    device_name: str
    host: str
    port: int
    key_hint: str
    verify_tls: bool
    enabled: bool
    status: str
    version: str | None
    latest_version: str | None
    update_available: bool
    last_polled_at: datetime | None
    last_ok_at: datetime | None
    last_error: str | None
    created_at: datetime


class Probe(BaseModel):
    version: str | None
    latest: str | None
    update_available: bool
    gateways: int
    monitored: int  # bramy z pomiarem (monitorowanie włączone)
    interfaces: int
    services: int
    hosts: int
    dhcp: str | None


class DeviceData(BaseModel):
    """Dane OPNsense do strony urządzenia; `configured = false` – urządzenie nie ma klucza API (albo moduł wyłączony)."""

    configured: bool
    status: str | None = None
    stale: bool = False  # ostatni udany odczyt jest stary – dane mogą być nieaktualne
    version: str | None = None
    latest_version: str | None = None
    update_available: bool = False
    last_ok_at: datetime | None = None
    last_error: str | None = None
    dhcp: str | None = None
    gateways: list[dict] = []
    interfaces: list[dict] = []
    services: list[dict] = []
    hosts: list[dict] = []


def _hint(key: str | None) -> str:
    return f"…{key[-4:]}" if key and len(key) > 8 else "…"


def _out(a: OpnsenseApi, device: Device) -> ApiOut:
    return ApiOut(
        id=a.id,
        device_id=a.device_id,
        device_name=device.name,
        host=device.host,
        port=a.port,
        key_hint=_hint(a.api_key),
        verify_tls=a.verify_tls,
        enabled=a.enabled,
        status=a.status,
        version=a.version,
        latest_version=a.latest_version,
        update_available=update_available(a.version, a.latest_version),
        last_polled_at=a.last_polled_at,
        last_ok_at=a.last_ok_at,
        last_error=a.last_error,
        created_at=a.created_at,
    )


async def _device(session, device_id: int) -> Device:
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "Nie ma takiego urządzenia")
    return device


async def _probe(host: str, t: ApiTarget) -> Probe:
    client = Client(host, t.api_key, t.api_secret, port=t.port, verify_tls=t.verify_tls)
    try:
        snap: Snapshot = await client.snapshot()
    except OpnsenseError as exc:
        raise HTTPException(422, f"OPNsense {host}: {exc}") from exc
    finally:
        await client.close()
    return Probe(
        version=snap.version,
        latest=snap.latest,
        update_available=snap.update_available,
        gateways=len(snap.gateways),
        monitored=sum(1 for g in snap.gateways if g.up is not None),
        interfaces=sum(1 for i in snap.interfaces if i.identifier and not i.device.startswith("lo")),
        services=len(snap.services),
        hosts=len(snap.hosts),
        dhcp=snap.dhcp,
    )


@router.get("/apis", response_model=list[ApiOut])
async def list_apis():
    async with Session() as session:
        rows = (await session.execute(select(OpnsenseApi, Device).join(Device, Device.id == OpnsenseApi.device_id).order_by(Device.name))).all()
    return [_out(a, d) for a, d in rows]


@router.post("/probe", response_model=Probe, dependencies=[Depends(require_module("opnsense"))])
async def probe_target(body: ApiTarget, _: AdminUser):
    """Test klucza bez zapisu – do formularza „Dodaj klucz API”."""
    async with Session() as session:
        device = await _device(session, body.device_id)
    return await _probe(device.host, body)


@router.post("/apis", response_model=ApiOut, status_code=201, dependencies=[Depends(require_module("opnsense"))])
async def create_api(body: ApiCreate, _: AdminUser, probe: bool = Query(True, description="najpierw sprawdź połączenie")):
    async with Session() as session:
        device = await _device(session, body.device_id)
        if await session.scalar(select(OpnsenseApi.id).where(OpnsenseApi.device_id == body.device_id)):
            raise HTTPException(409, f"Urządzenie {device.name} ma już klucz API OPNsense")
    info = await _probe(device.host, body) if probe else None
    api = OpnsenseApi(**body.model_dump(), status="unknown", version=info.version if info else None, latest_version=info.latest if info else None)
    async with Session() as session, session.begin():
        if await session.scalar(select(OpnsenseApi.id).where(OpnsenseApi.device_id == body.device_id)):
            raise HTTPException(409, f"Urządzenie {device.name} ma już klucz API OPNsense")
        session.add(api)
        await session.flush()
        await session.refresh(api)
    return _out(api, device)


@router.patch("/apis/{api_id}", response_model=ApiOut)
async def update_api(api_id: int, body: ApiUpdate, _: AdminUser):
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    async with Session() as session, session.begin():
        api = await session.get(OpnsenseApi, api_id)
        if api is None:
            raise HTTPException(404, "Nie ma takiego klucza API OPNsense")
        for field, value in changes.items():
            setattr(api, field, value)
        if {"port", "api_key", "api_secret", "verify_tls"} & changes.keys():
            api.status, api.last_error = "unknown", None  # nowe dane logowania – stary błąd już nie dotyczy
        device = await _device(session, api.device_id)
    return _out(api, device)


@router.delete("/apis/{api_id}", status_code=204)
async def delete_api(api_id: int, _: AdminUser):
    """Usuwa sam klucz; urządzenie i jego historia zostają."""
    async with Session() as session, session.begin():
        api = await session.get(OpnsenseApi, api_id)
        if api is None:
            raise HTTPException(404, "Nie ma takiego klucza API OPNsense")
        await session.delete(api)


@router.post("/apis/{api_id}/probe", response_model=Probe)
async def probe_saved(api_id: int, _: AdminUser):
    async with Session() as session:
        api = await session.get(OpnsenseApi, api_id)
        if api is None:
            raise HTTPException(404, "Nie ma takiego klucza API OPNsense")
        device = await _device(session, api.device_id)
        target = ApiTarget(device_id=api.device_id, port=api.port, api_key=api.api_key or "x" * 8, api_secret=api.api_secret or "x" * 8, verify_tls=api.verify_tls)
    return await _probe(device.host, target)


@router.get("/devices/{device_id}", response_model=DeviceData)
async def device_data(device_id: int):
    if not await is_enabled("opnsense"):
        return DeviceData(configured=False)
    async with Session() as session:
        api = await session.scalar(select(OpnsenseApi).where(OpnsenseApi.device_id == device_id))
    if api is None or not api.enabled:
        return DeviceData(configured=False)
    snap = api.snapshot or {}
    return DeviceData(
        configured=True,
        status=api.status,
        stale=is_stale(api.last_ok_at),
        version=api.version,
        latest_version=api.latest_version,
        update_available=update_available(api.version, api.latest_version),
        last_ok_at=api.last_ok_at,
        last_error=api.last_error,
        dhcp=snap.get("dhcp"),
        gateways=snap.get("gateways") or [],
        # przypisane interfejsy bez pętli zwrotnej (lo0 OPNsense pokazuje jako przypisany „Loopback”)
        interfaces=[i for i in snap.get("interfaces") or [] if i.get("identifier") and not str(i.get("device", "")).startswith("lo")],
        services=snap.get("services") or [],
        hosts=snap.get("hosts") or [],
    )
