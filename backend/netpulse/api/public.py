"""Pulpit publiczny (`/p/<token>`): osobne API tylko do odczytu, bez logowania i bez ciasteczek sesji.

Zasady bezpieczeństwa:
- token w adresie jest nieodgadywalny (32 bajty), w bazie jest tylko jego skrót do wyszukania; wyłączenie
  udostępniania albo nowy link od razu unieważnia stary; link może wygasnąć;
- opcjonalny PIN: po podaniu poprawnego klient dostaje klucz dostępu (skrót tokenu i skrótu PIN-u), zmiana PIN-u
  albo linku unieważnia klucz; nieudane próby są limitowane jak logowanie;
- dane wychodzą wyłącznie przez `/data?path=…` i tylko te, których potrzebują widgety zapisane w tym pulpicie
  (biała lista budowana z układu, nie z żądania) – reszta API pozostaje zamknięta;
- adresy IP i błędy urządzeń są domyślnie ukryte, odpowiedzi nie trafiają do pamięci podręcznej ani wyszukiwarek.
"""

from __future__ import annotations

import hmac
import re
from datetime import UTC, datetime
from typing import Any, get_args
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..auth import hash_token, verify_password_async
from ..db import Session
from ..db.models import Dashboard
from ..modules import get_modules
from . import (
    availability,
    checks,
    controllers,
    dashboard,
    devices,
    events,
    metrics,
    panels,
    servers,
    system,
    vpn,
    wan,
)
from .dashboards import _parse, public_options
from .layout_schemas import AgentSource, DashboardLayout, PublicOptions, RangeMinutes, Source
from .schemas import DeviceOut
from .security import LoginLimiter, client_ip

router = APIRouter(prefix="/api/public/dashboards", tags=["pulpit publiczny"])

ACCESS_HEADER = "X-Dashboard-Access"
NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
RANGES = set(get_args(RangeMinutes))
SLA_DAYS = {1, 7, 30}
AVAILABILITY_DAYS = {1, 7, 30, 365}
PathQuery = Query(max_length=512, description="ścieżka API, której potrzebuje widget, np. /api/dashboard/summary")
pin_limiter = LoginLimiter(max_failures=10, window_s=900)
# Pola urządzenia, które nie wychodzą poza panel (konfiguracja SNMP)
_DEVICE_PRIVATE = ("v3_username", "v3_auth_protocol", "v3_priv_protocol", "v3_context", "sys_name", "default_community")


class PublicDashboardOut(BaseModel):
    name: str
    locked: bool  # wymagany PIN, a klient nie podał poprawnego klucza
    layout: DashboardLayout | None  # None, gdy zablokowany
    options: PublicOptions


class UnlockIn(BaseModel):
    pin: str = Field(min_length=1, max_length=32)


class UnlockOut(BaseModel):
    access: str


def _gone() -> HTTPException:
    # Ten sam komunikat dla nieznanego, wyłączonego i wygasłego linku – nic nie zdradza
    return HTTPException(404, "Ten link jest nieaktywny albo wygasł", headers=NO_STORE)


async def _dashboard(token: str) -> Dashboard:
    if not 20 <= len(token) <= 128:
        raise _gone()
    async with Session() as session:
        row = await session.scalar(select(Dashboard).where(Dashboard.public_token_hash == hash_token(token)))
    if row is None or (row.public_expires_at is not None and row.public_expires_at <= datetime.now(UTC)):
        raise _gone()
    return row


def access_key(row: Dashboard) -> str:
    return hash_token(f"{row.public_token_hash}:{row.public_pin_hash}")


def _unlocked(row: Dashboard, request: Request) -> bool:
    if row.public_pin_hash is None:
        return True
    return hmac.compare_digest(request.headers.get(ACCESS_HEADER, ""), access_key(row))


@router.get("/{token}", response_model=PublicDashboardOut)
async def get_public(token: str, request: Request, response: Response):
    row = await _dashboard(token)
    response.headers.update(NO_STORE)
    locked = not _unlocked(row, request)
    return PublicDashboardOut(name=row.name, locked=locked, layout=None if locked else _parse(row.layout), options=public_options(row))


@router.post("/{token}/unlock", response_model=UnlockOut)
async def unlock(token: str, body: UnlockIn, request: Request, response: Response):
    key = f"pin:{client_ip(request)}"
    if (wait := pin_limiter.retry_after(key)) is not None:
        raise HTTPException(429, f"Za dużo prób. Spróbuj ponownie za {wait} s.", headers={"Retry-After": str(wait)})
    row = await _dashboard(token)
    response.headers.update(NO_STORE)
    if row.public_pin_hash is None:
        return UnlockOut(access=access_key(row))
    if not await verify_password_async(row.public_pin_hash, body.pin):
        pin_limiter.failure(key)
        raise HTTPException(403, "Nieprawidłowy PIN")
    pin_limiter.success(key)
    return UnlockOut(access=access_key(row))


# --- dane widgetów (biała lista z układu pulpitu) ------------------------------------


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError as exc:
        raise HTTPException(422, "Nieprawidłowy parametr") from exc


def _chart_path(source: Source) -> tuple[str, dict[str, str]]:
    """Ścieżka i stałe parametry, pod którymi panel pobiera dane wykresu (jak sourcePath w chartSource.ts)."""
    match source.kind:
        case "wan":
            return "/api/dashboard/traffic", {}
        case "wifi_total":
            return "/api/dashboard/wifi", {}
        case "interface":
            return f"/api/interfaces/{source.id}/metrics", {}
        case "device":
            return f"/api/devices/{source.id}/metrics", {}
        case "wifi_network":
            return f"/api/wifi/{source.id}/metrics", {}
        case "server":
            return "/api/system/metrics", {}
        case "check":
            return f"/api/checks/{source.id}/metrics", {}
    assert isinstance(source, AgentSource)
    return f"/api/devices/{source.id}/agent-metrics", {"source": source.kind, "key": source.key}


async def _chart(source: Source, minutes: int, offset: int = 0) -> Any:
    match source.kind:
        case "wan":
            return await dashboard.traffic(minutes, offset)
        case "wifi_total":
            return await dashboard.wifi(minutes, offset)
        case "interface":
            return await metrics.interface_metrics(source.id, minutes, offset)
        case "device":
            return await metrics.device_metrics(source.id, minutes, offset)
        case "wifi_network":
            return await metrics.wifi_metrics(source.id, minutes, offset)
        case "server":
            return await system.metrics(minutes, offset)
        case "check":
            return await checks.check_series(source.id, minutes, offset)
    assert isinstance(source, AgentSource)
    return await metrics.agent_metrics(source.id, source.kind, source.key, minutes, offset)


def _public_device(d, opts: PublicOptions) -> dict:
    out = DeviceOut.model_validate(d).model_dump(mode="json")
    out.update(dict.fromkeys(_DEVICE_PRIVATE))
    if opts.hide_hosts:
        out.update(host="", port=0, last_error=None)
    return out


HEATMAP_WEEK = 7 * 24 * 60


async def resolve(layout: DashboardLayout, opts: PublicOptions, raw: str) -> Any:
    """Dane dla jednego żądania widgetu – tylko jeśli taki widget jest w pulpicie. Inaczej 403."""
    parts = urlsplit(raw)
    path, query = parts.path, {k: v[-1] for k, v in parse_qs(parts.query).items()}
    widgets = layout.widgets
    types = {w.type for w in widgets}
    mods = await get_modules()

    def minutes() -> int:
        m = _int(query.get("minutes"), opts.range_min)
        if m not in RANGES:
            raise HTTPException(403, "Niedozwolony zakres czasu")
        return m

    async def visible_devices() -> list:
        return list(await devices.list_devices())  # bez urządzeń wyłączonych modułów

    if path == "/api/modules":
        return mods
    if path == "/api/dashboard/summary" and types & {"summary", "status"}:
        return await dashboard.summary()
    if path == "/api/devices" and types & {"devices", "poe"}:
        return [_public_device(d, opts) for d in await visible_devices()]
    if path == "/api/availability" and "devices" in types:
        days = _int(query.get("days"), 30)
        if days not in AVAILABILITY_DAYS:
            raise HTTPException(403, "Niedozwolony okres")
        return await availability.devices_availability(days)
    if (m := re.fullmatch(r"/api/devices/(\d+)/server", path)) and "devices" in types:
        device_id = int(m.group(1))
        if not any(d.id == device_id and d.kind == "server" for d in await visible_devices()):
            raise HTTPException(403, "Tych danych nie ma na tym pulpicie")
        status = await servers.device_server(device_id)
        if status is not None:
            status = status.model_copy(update={"agent": None, "proxmox": None})  # bez adresów i nazw hostów
        return status
    if (m := re.fullmatch(r"/api/devices/(\d+)/poe", path)) and mods.get("unifi", True):
        device_id = int(m.group(1))
        if any(w.type == "poe" and w.config.device_id in (None, device_id) for w in widgets):
            return await controllers.device_poe(device_id)
    if path == "/api/system" and "server" in types:
        return await system.current()
    if path == "/api/events" and "events" in types:
        # Kafelek „Zdarzenia”: tylko okres ustawiony w którymś kafelku pulpitu
        wanted = _int(query.get("minutes"), 0)
        if wanted not in {w.config.days * 24 * 60 for w in widgets if w.type == "events"} or query.get("offset"):
            raise HTTPException(403, "Niedozwolony zakres czasu")
        return await events.events(wanted, 0)
    if path == "/api/vpn" and "vpn" in types:
        return await vpn.status(public=True)  # bez adresów: skąd łączy się klient i adresu w tunelu
    if path == "/api/wan/status" and "wan_status" in types:
        return await wan.status()
    # Historia łączy: widget „Aktywne łącze WAN” albo wykres z kolorem łącza zapasowego (od 0.55.0)
    if path == "/api/wan/history" and ("wan_chart" in types or any(w.type == "chart" and w.config.wan_backup for w in widgets)):
        return await wan.history(minutes())
    if path == "/api/wan/sla" and "wan_sla" in types:
        days = _int(query.get("days"), 7)
        if days not in SLA_DAYS:
            raise HTTPException(403, "Niedozwolony okres")
        return await wan.sla(days)
    if path == "/api/wan/usage" and "wan_usage" in types:
        # Licznik transferu (od 0.82.0): tylko router i dzień startu okresu ustawione w którymś widgecie
        wanted = (_int(query.get("device_id"), 0) or None, _int(query.get("reset_day"), 1))
        if wanted not in {(w.config.device_id, w.config.reset_day) for w in widgets if w.type == "wan_usage"}:
            raise HTTPException(403, "Tych danych nie ma na tym pulpicie")
        return await wan.wan_usage(reset_day=wanted[1], device_id=wanted[0])
    if m := re.fullmatch(r"/api/collections/(\w+)", path):
        device_id = _int(query.get("device_id"), 0) or None
        # Tabela urządzeń (CPU, RAM) i paski dostępności sprawdzeń (od 0.42.0)
        if device_id is None and m.group(1) == "devices" and any(w.type == "devices" and w.config.display == "table" for w in widgets):
            return await panels.collection("devices", None)
        if device_id is None and m.group(1) == "checks" and "checks" in types:
            return await panels.collection("checks", None)
        for w in widgets:
            if w.type in ("bargauge", "table") and w.config.collection.kind == m.group(1) and w.config.collection.device_id == device_id:
                return await panels.collection(m.group(1), device_id)
            if w.type == "pie" and w.config.collection() == (m.group(1), device_id):
                return await panels.collection(m.group(1), device_id)
        raise HTTPException(403, "Tych danych nie ma na tym pulpicie")
    if path == "/api/states":
        wanted = (
            {("device", i) for i in panels._ids(query.get("devices"))}
            | {("interface", i) for i in panels._ids(query.get("interfaces"))}
            | {("check", i) for i in panels._ids(query.get("checks"))}
        )
        for w in widgets:
            if w.type == "state_timeline" and {(i.kind, i.id) for i in w.config.items} == wanted:
                return await panels.states(query.get("devices"), query.get("interfaces"), minutes(), query.get("checks"))
        raise HTTPException(403, "Tych danych nie ma na tym pulpicie")
    offset = _int(query.get("offset"), 0)
    # Mini-wykresy w kafelkach podsumowania: ruch WAN i klienci WiFi w zakresie pulpitu – tylko dla pokazanych kafelków
    tiles = {tile for w in widgets if w.type == "summary" for tile in w.config.tiles}
    if offset == 0:
        if path == "/api/dashboard/traffic" and tiles & {"wan_down", "wan_up"}:
            return await dashboard.traffic(minutes(), 0)
        if path == "/api/dashboard/wifi" and "wifi_clients" in tiles:
            return await dashboard.wifi(minutes(), 0)
    # Paski dostępności sprawdzeń: dni z widgetu, bez przesunięcia
    if (m := re.fullmatch(r"/api/checks/(\d+)/metrics", path)) and offset == 0:
        if any(w.type == "checks" and query.get("minutes") == str(w.config.days * 1440) for w in widgets):
            return await checks.check_series(int(m.group(1)), minutes(), 0)
    # Źródła wykresów: zapytania wykresów i panele „liczba”
    chart_queries = [(q.source, q.offset_min) for w in widgets if w.type == "chart" for q in w.config.queries]
    chart_queries += [(w.config.source, 0) for w in widgets if w.type == "stat"]
    # Zmiana w „liczbie”: poprzedni okres tej samej długości, czyli przesunięcie o zakres panelu
    chart_queries += [(w.config.source, w.config.range_min or opts.range_min) for w in widgets if w.type == "stat" and w.config.show_change]
    # Mapa cieplna: tydzień po tygodniu (zakres 7 dni, przesunięcie o kolejne tygodnie)
    heatmaps = [w.config for w in widgets if w.type == "heatmap"]
    if heatmaps and minutes() == HEATMAP_WEEK:
        chart_queries += [(c.source, k * HEATMAP_WEEK) for c in heatmaps for k in range(c.weeks)]
    for source, query_offset in chart_queries:
        chart_path, fixed = _chart_path(source)
        # Przesunięcie w czasie tylko takie, jakie ma zapytanie wykresu na tym pulpicie
        if path != chart_path or any(query.get(k) != v for k, v in fixed.items()) or offset != query_offset:
            continue
        if source.kind == "pve_guest" and not mods.get("proxmox", True):
            break
        if source.kind.startswith("agent_") and not mods.get("agents", True):
            break
        if source.kind == "vpn" and not mods.get("unifi", True):
            break
        if source.kind == "lan_client" and not mods.get("opnsense", False):
            break
        return await _chart(source, minutes(), offset)
    raise HTTPException(403, "Tych danych nie ma na tym pulpicie")


@router.get("/{token}/data")
async def public_data(token: str, request: Request, response: Response, path: str = PathQuery):
    row = await _dashboard(token)
    if not _unlocked(row, request):
        raise HTTPException(401, "Ten pulpit wymaga PIN-u", headers=NO_STORE)
    layout = _parse(row.layout)
    if layout is None:
        raise HTTPException(403, "Tych danych nie ma na tym pulpicie")
    response.headers.update(NO_STORE)
    return jsonable_encoder(await resolve(layout, public_options(row), path))
