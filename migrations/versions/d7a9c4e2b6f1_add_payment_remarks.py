"""Add optional remarks to payment records.

Revision ID: d7a9c4e2b6f1
Revises: c8d9e0f1a2b3
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa


revision = "d7a9c4e2b6f1"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in [col["name"] for col in inspector.get_columns(table_name)]


def upgrade():
    if not _column_exists("payments", "remarks"):
        op.add_column("payments", sa.Column("remarks", sa.String(length=500), nullable=True))


def downgrade():
    if _column_exists("payments", "remarks"):
        op.drop_column("payments", "remarks")
