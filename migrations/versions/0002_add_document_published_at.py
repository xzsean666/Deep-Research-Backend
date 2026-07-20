"""add documents.published_at

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-17

Nullable, no default — safe additive column on the live table. Populated
going forward by Crawl4AI-side JSON-LD/OpenGraph date extraction
(app/services/crawl/crawl4ai_provider.py); existing rows stay NULL until
their next TTL refresh.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "published_at")
