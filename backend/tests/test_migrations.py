"""Migracje schematu (Alembic): nowa baza, baza sprzed migracji (0.9.0 i starsze), zgodność z modelami.

Testy na bazie uruchamiane, gdy ustawiono NETPULSE_TEST_DB=1 i NETPULSE_DATABASE_URL (CI ma usługę bazy).
"""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select, text

from netpulse import aggregates
from netpulse.db import SchemaMismatchError, Session, engine, init_db
from netpulse.db.migrate import alembic_config, current_revision, head_revision, include_object
from netpulse.db.models import Base, Device

needs_db = pytest.mark.skipif(os.environ.get("NETPULSE_TEST_DB") != "1", reason="brak testowej bazy (NETPULSE_TEST_DB=1)")


def run(coro_fn):
    async def wrapper():
        try:
            return await coro_fn()
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


async def drop_everything() -> None:
    async with engine.begin() as conn:
        await aggregates.delete_jobs(conn)  # zadania w tle nie mogą ruszyć w trakcie usuwania („tuple concurrently deleted”)
        await aggregates.drop_all(conn)  # agregaty zależą od hypertables
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


# Tabele i kolumny dodane migracjami po 0001 – baza z 0.9.0 ich nie miała
AFTER_BASELINE = {"agents", "metrics", "proxmox_servers", "proxmox_nodes", "proxmox_guests", "proxmox_storages", "wan_links", "wan_link_metrics", "known_clients", "client_metrics", "checks", "check_metrics", "unifi_api_devices", "maintenance_windows", "audit_log", "opnsense_apis", "wan_rate_metrics"}
COLUMNS_AFTER_BASELINE = {
    "alert_rules": ["match"],
    "dashboards": ["public_token_hash", "public_token", "public_expires_at", "public_pin_hash", "public_options"],
    "notification_channels": ["secret", "config", "quiet_from", "quiet_to", "quiet_critical", "quiet_backlog"],
    "alerts": ["muted", "maintenance"],
    "users": ["role", "totp_secret", "totp_enabled", "totp_last_step", "totp_recovery"],
}


async def legacy_schema() -> None:
    """Baza jak z wersji ≤ 0.9.0: tabele z create_all (bez nowszych), bez tabeli alembic_version."""
    await drop_everything()
    tables = [t for t in Base.metadata.sorted_tables if t.name not in AFTER_BASELINE]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        for table, columns in COLUMNS_AFTER_BASELINE.items():
            for column in columns:
                await conn.execute(text(f'ALTER TABLE {table} DROP COLUMN "{column}"'))


def schema_diff(sync_conn) -> list:
    ctx = MigrationContext.configure(sync_conn, opts={"include_object": include_object, "compare_type": True})
    return compare_metadata(ctx, Base.metadata)


async def state() -> tuple[str | None, list]:
    async with engine.connect() as conn:
        return await conn.run_sync(current_revision), await conn.run_sync(schema_diff)


@pytest.fixture
def clean_db():
    yield
    # Pozostałe testy dostają zwykłą, aktualną bazę
    async def restore():
        await drop_everything()
        await init_db()

    run(restore)


def test_single_head():
    """Dwie migracje z tym samym poprzednikiem (np. z dwóch gałęzi) muszą zostać scalone."""
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert heads == [head_revision()], heads


@needs_db
def test_fresh_db_matches_models(clean_db):
    """Migracje dają dokładnie schemat z modeli.

    Gdy ten test nie przechodzi po zmianie w models.py: brakuje migracji (docs/13-migracje-bazy.md)."""

    async def scenario():
        await drop_everything()
        await init_db()
        return await state()

    rev, diff = run(scenario)
    assert rev == head_revision()
    assert diff == [], diff


@needs_db
def test_legacy_db_is_adopted_without_data_loss(clean_db):
    async def scenario():
        await legacy_schema()
        async with Session() as s, s.begin():
            s.add(Device(name="Router", host="10.9.9.1"))
        async with engine.begin() as conn:
            # Starsza instalacja, która nie miała jeszcze nowszej tabeli
            await conn.execute(text("DROP TABLE notification_channels"))
        await init_db()
        rev, diff = await state()
        async with Session() as s:
            devices = await s.scalar(select(func.count()).select_from(Device))
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        return rev, diff, devices, tables

    rev, diff, devices, tables = run(scenario)
    assert rev == head_revision()
    assert diff == [], diff
    assert devices == 1
    assert "notification_channels" in tables


@needs_db
def test_legacy_db_with_missing_column_is_rejected(clean_db):
    """Brak kolumny w starej tabeli → czytelny błąd, a baza zostaje nietknięta (bez wpisu wersji)."""

    async def scenario():
        await legacy_schema()
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE devices DROP COLUMN port"))
        with pytest.raises(SchemaMismatchError, match="devices: port"):
            await init_db()
        async with engine.connect() as conn:
            return await conn.run_sync(lambda c: inspect(c).has_table("alembic_version"))

    assert run(scenario) is False


@needs_db
def test_parallel_init_is_serialized(clean_db):
    """Kolektor i CLI startujące naraz na pustej bazie nie wchodzą sobie w drogę."""

    async def scenario():
        await drop_everything()
        await asyncio.gather(init_db(), init_db(), init_db())
        return await state()

    rev, diff = run(scenario)
    assert rev == head_revision()
    assert diff == [], diff


@needs_db
def test_init_is_idempotent(clean_db):
    async def scenario():
        await drop_everything()
        await init_db()
        await init_db()
        async with engine.connect() as conn:
            rows = await conn.execute(text("SELECT count(*) FROM alembic_version"))
            return rows.scalar()

    assert run(scenario) == 1
