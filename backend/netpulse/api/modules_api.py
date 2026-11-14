"""Moduły: odczyt (każdy zalogowany – panel buduje z tego menu) i zmiana (tylko administrator)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..modules import get_modules, save_modules
from .security import AdminUser, require_user

router = APIRouter(prefix="/api/modules", tags=["moduły"], dependencies=[Depends(require_user)])


class ModulesOut(BaseModel):
    proxmox: bool
    unifi: bool
    opnsense: bool
    agents: bool
    backups: bool


class ModulesUpdate(BaseModel):
    """Pominięte moduły zostają bez zmian."""

    proxmox: bool | None = None
    unifi: bool | None = None
    opnsense: bool | None = None
    agents: bool | None = None
    backups: bool | None = None


@router.get("", response_model=ModulesOut)
async def read():
    return await get_modules()


@router.put("", response_model=ModulesOut)
async def update(body: ModulesUpdate, _: AdminUser):
    return await save_modules(body.model_dump(exclude_none=True))
