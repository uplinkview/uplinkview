"""Bez integracji Proxmox VE (0.86.0): usunięcie tabel `proxmox_*` (z 0005), węzłów jako urządzeń i reguł alertów.

Węzły Proxmoxa były urządzeniami `devices.driver = 'proxmox'` – ich metryki, próbki i reguły znikają kaskadą razem
z urządzeniem. Alerty z historii (reguły maszyny zatrzymanej, kopii vzdump i wieku kopii oraz alerty węzłów) też
wypadają, bo panel nie zna już ich rodzajów. Moduł `proxmox` znika ze stanu modułów (`app_settings`).
Zapisane pulpity z wykresami maszyn czyści przy odczycie `layout_schemas.DashboardLayout`.

`downgrade` zakłada z powrotem puste tabele (jak 0005) – usuniętych danych nie przywraca.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

REMOVED_RULES = "kind IN ('guest_stopped', 'backup_failed') OR (kind = 'metric' AND metric = 'backup_age_h')"


def upgrade() -> None:
    op.execute(
        "DELETE FROM alerts WHERE rule_id IN (SELECT id FROM alert_rules WHERE " + REMOVED_RULES + ")"
        " OR device_id IN (SELECT id FROM devices WHERE driver = 'proxmox')"
    )
    op.execute("DELETE FROM alert_rules WHERE " + REMOVED_RULES)
    for table in ("proxmox_storages", "proxmox_nodes", "proxmox_guests", "proxmox_servers"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DELETE FROM devices WHERE driver = 'proxmox'")
    op.execute("UPDATE app_settings SET value = value - 'proxmox' WHERE key = 'modules' AND jsonb_typeof(value) = 'object'")


def downgrade() -> None:
    op.create_table('proxmox_servers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('host', sa.String(length=255), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('token_id', sa.String(length=255), nullable=False),
    sa.Column('token_secret', sa.Text(), nullable=False),
    sa.Column('verify_tls', sa.Boolean(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('cluster_name', sa.String(length=128), nullable=True),
    sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_ok_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('host')
    )
    op.create_table('proxmox_guests',
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('vmid', sa.Integer(), nullable=False),
    sa.Column('node', sa.String(length=64), nullable=False),
    sa.Column('type', sa.String(length=8), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('template', sa.Boolean(), nullable=False),
    sa.Column('tags', sa.String(length=255), nullable=True),
    sa.Column('cpus', sa.Integer(), nullable=True),
    sa.Column('cpu_percent', sa.Float(), nullable=True),
    sa.Column('mem_used', sa.BigInteger(), nullable=True),
    sa.Column('mem_total', sa.BigInteger(), nullable=True),
    sa.Column('disk_used', sa.BigInteger(), nullable=True),
    sa.Column('disk_total', sa.BigInteger(), nullable=True),
    sa.Column('uptime_s', sa.BigInteger(), nullable=True),
    sa.Column('last_backup_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['proxmox_servers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'vmid')
    )
    op.create_table('proxmox_nodes',
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('node', sa.String(length=64), nullable=False),
    sa.Column('device_id', sa.Integer(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('online', sa.Boolean(), nullable=False),
    sa.Column('backup_status', sa.String(length=255), nullable=True),
    sa.Column('backup_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['server_id'], ['proxmox_servers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'node'),
    sa.UniqueConstraint('device_id')
    )
    op.create_table('proxmox_storages',
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('node', sa.String(length=64), nullable=False),
    sa.Column('storage', sa.String(length=128), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=True),
    sa.Column('shared', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('content', sa.String(length=255), nullable=True),
    sa.Column('used_bytes', sa.BigInteger(), nullable=True),
    sa.Column('total_bytes', sa.BigInteger(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['proxmox_servers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'node', 'storage')
    )

