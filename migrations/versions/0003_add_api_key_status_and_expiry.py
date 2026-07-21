"""add api_keys.status and api_keys.expires_at

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-21

Additive columns for the new admin API (app/api/routers/admin.py):
`status` lets a key be disabled without deleting it (audit trail, can be
re-enabled); `expires_at` is nullable — NULL means permanent, matching
every existing row's intended behavior unchanged. `server_default='active'`
on `status` means existing rows come back as active with no backfill step.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    )
    op.add_column(
        "api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("api_keys", "expires_at")
    op.drop_column("api_keys", "status")
