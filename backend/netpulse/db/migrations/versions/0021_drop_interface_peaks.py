"""Bez szczytu ruchu portu (0.84.0): usunięcie `interface_metrics.in_bps_max` i `out_bps_max` (dodanych w 0018).

Wykres ruchu pokazuje tylko średnie pobierania i wysyłania, pomiar szczytu (`peaks.py`) usunięty. Kolumny nie są
kolumnami segmentacji ani sortowania kompresji, więc TimescaleDB usuwa je także ze skompresowanych chunków.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE interface_metrics DROP COLUMN IF EXISTS in_bps_max")
    op.execute("ALTER TABLE interface_metrics DROP COLUMN IF EXISTS out_bps_max")


def downgrade() -> None:
    op.add_column("interface_metrics", sa.Column("in_bps_max", sa.Float(), nullable=True))
    op.add_column("interface_metrics", sa.Column("out_bps_max", sa.Float(), nullable=True))
