"""Initial schema + TimescaleDB hypertables (PostgreSQL only).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

from app.database import models
from app.database.base import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DAY_MS = 86_400_000


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        has_ts = bind.exec_driver_sql(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'"
        ).first()
        if has_ts:
            op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            for t in models.TIMESERIES_TABLES:
                op.execute(
                    f"SELECT create_hypertable('{t}', 'ts', chunk_time_interval => {DAY_MS}, "
                    "if_not_exists => TRUE, migrate_data => TRUE)"
                )


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
