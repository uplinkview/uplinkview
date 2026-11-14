"""Moduły (Ustawienia → Moduły): integracje, które można wyłączyć, gdy się z nich nie korzysta.

Wyłączony moduł znika z panelu (menu, ustawienia, źródła wykresów, rodzaje reguł), jego pętla w kolektorze
niczego nie robi, a jego urządzenia i reguły alertów są pomijane. Dane i konfiguracja zostają w bazie.

Stan jest w `app_settings` (klucz `modules`). Gdy wpisu nie ma, wszystko jest włączone (zachowanie sprzed 0.18).
Przy starcie kolektor zapisuje stan początkowy (`ensure_modules`): włączone jest to, co jest już skonfigurowane,
więc nowa instalacja zaczyna z wyłączonymi integracjami, a aktualizowana nie traci niczego, czego używa.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import func, select

from .db import Session
from .db.models import Agent, AppSetting, Controller, OpnsenseApi, ProxmoxServer

log = logging.getLogger(__name__)

ModuleId = Literal["proxmox", "unifi", "opnsense", "agents", "backups"]
MODULES: tuple[ModuleId, ...] = ("proxmox", "unifi", "opnsense", "agents", "backups")
SETTINGS_KEY = "modules"
LABELS: dict[str, str] = {"proxmox": "Proxmox VE", "unifi": "UniFi", "opnsense": "OPNsense API", "agents": "Agenci serwerów", "backups": "Kopia zapasowa z panelu"}
# Urządzenia, które dostarcza moduł (devices.driver) – ukrywane, gdy moduł jest wyłączony
DRIVER_MODULE: dict[str, str] = {"agent": "agents", "proxmox": "proxmox", "unifi_api": "unifi"}


# Moduły dodane po pierwszym zapisie stanu: w zapisanym stanie ich nie ma, a nie powinny włączać się same
# (nowa integracja zaczyna wyłączona, jak w nowej instalacji). Bez zapisanego stanu – wszystko włączone (sprzed 0.18).
ADDED_LATER: frozenset[str] = frozenset({"opnsense"})


def _normalize(value: dict | None) -> dict[str, bool]:
    if not value:
        return dict.fromkeys(MODULES, True)
    return {m: bool(value.get(m, m not in ADDED_LATER)) for m in MODULES}


async def read_modules(session) -> dict[str, bool]:
    row = await session.get(AppSetting, SETTINGS_KEY)
    return _normalize(row.value if row else None)


async def get_modules() -> dict[str, bool]:
    async with Session() as session:
        return await read_modules(session)


async def is_enabled(module: str) -> bool:
    return (await get_modules())[module]


def hidden_drivers(mods: dict[str, bool]) -> tuple[str, ...]:
    """Sterowniki urządzeń wyłączonych modułów (do pominięcia w listach, pulpicie i alertach)."""
    return tuple(driver for driver, module in DRIVER_MODULE.items() if not mods.get(module, True))


async def detect(session) -> dict[str, bool]:
    """Stan początkowy: włączone to, co ma już konfigurację."""

    async def any_rows(model) -> bool:
        return bool(await session.scalar(select(func.count()).select_from(model)))

    return {
        "proxmox": await any_rows(ProxmoxServer),
        "unifi": await any_rows(Controller),
        "opnsense": await any_rows(OpnsenseApi),
        "agents": await any_rows(Agent),
        "backups": True,
    }


async def ensure_modules() -> dict[str, bool]:
    """Przy starcie kolektora: zapisuje stan początkowy, jeśli jeszcze go nie ma. Zwraca bieżący stan."""
    async with Session() as session, session.begin():
        row = await session.get(AppSetting, SETTINGS_KEY, with_for_update=True)
        if row is not None:
            return _normalize(row.value)
        state = await detect(session)
        session.add(AppSetting(key=SETTINGS_KEY, value=state, updated_at=datetime.now(UTC)))
        log.info("Moduły (stan początkowy): %s", ", ".join(f"{m}={'on' if v else 'off'}" for m, v in state.items()))
        return state


async def save_modules(values: dict[str, bool]) -> dict[str, bool]:
    async with Session() as session, session.begin():
        row = await session.get(AppSetting, SETTINGS_KEY, with_for_update=True)
        state = _normalize(row.value if row else None) | {m: bool(v) for m, v in values.items() if m in MODULES}
        if row is None:
            session.add(AppSetting(key=SETTINGS_KEY, value=state, updated_at=datetime.now(UTC)))
        else:
            row.value, row.updated_at = state, datetime.now(UTC)
    return state


def require_module(module: ModuleId):
    """Zależność FastAPI: 409, gdy moduł jest wyłączony (np. dodanie serwera Proxmox przy wyłączonym module)."""

    async def check() -> None:
        if not await is_enabled(module):
            raise HTTPException(409, f"Moduł „{LABELS[module]}” jest wyłączony. Włącz go w Ustawienia → Moduły.")

    return check
