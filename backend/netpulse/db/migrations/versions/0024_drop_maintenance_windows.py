"""Bez okien serwisowych (0.87.0): usunięcie tabeli `maintenance_windows` i kolumny `alerts.maintenance` (z 0013).

Wpisy dziennika zdarzeń o zmianach okien (`POST|PUT|DELETE /api/maintenance…`) też znikają. Alert otwarty w trakcie
okna (wyciszony) w następnym cyklu dostaje zwykłe powiadomienie, jeśli problem trwa.

`downgrade` zakłada z powrotem pustą tabelę i kolumnę (jak 0013) – usuniętych danych nie przywraca.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM audit_log WHERE action LIKE '% /api/maintenance%'")
    op.execute("DROP TABLE IF EXISTS maintenance_windows")
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS maintenance")


def downgrade() -> None:
    op.create_table(
        "maintenance_windows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("device_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("days", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("time_from", sa.String(length=5), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("alerts", sa.Column("maintenance", sa.Boolean(), nullable=False, server_default=sa.false()))
