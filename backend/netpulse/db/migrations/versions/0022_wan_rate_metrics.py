"""Prędkość portów WAN co 5 s: tabela `wan_rate_metrics` (od 0.85.0, `wanrate.py`).

Wykres ruchu WAN rysuje z niej jedną linię – najwyższą prędkość w kubełku – zamiast średniej z 30 s i osobnej serii
szczytu (usuniętej w 0021). Hypertable, retencję i kompresję zakłada init_db (HYPERTABLES, `compression.SEGMENT_BY`).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wan_rate_metrics",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interface_id", sa.Integer(), nullable=False),
        sa.Column("in_bps", sa.Float(), nullable=True),
        sa.Column("out_bps", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["interface_id"], ["interfaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("time", "interface_id"),
    )
    op.create_index("ix_wan_rate_metrics_interface_time", "wan_rate_metrics", ["interface_id", "time"], unique=False)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS wan_rate_metrics_1h CASCADE")
    op.drop_index("ix_wan_rate_metrics_interface_time", table_name="wan_rate_metrics")
    op.drop_table("wan_rate_metrics")
