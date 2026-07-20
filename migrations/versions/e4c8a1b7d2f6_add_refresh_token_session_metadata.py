"""Add refresh-token session metadata.

Revision ID: e4c8a1b7d2f6
Revises: d7a9c4e2b6f1
"""

from alembic import op
import sqlalchemy as sa


revision = "e4c8a1b7d2f6"
down_revision = "d7a9c4e2b6f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("refresh_tokens", sa.Column("client_ip", sa.String(45), nullable=True))
    op.add_column("refresh_tokens", sa.Column("user_agent", sa.String(500), nullable=True))
    op.add_column("refresh_tokens", sa.Column("device_name", sa.String(128), nullable=True))
    op.add_column("refresh_tokens", sa.Column("last_used_at", sa.DateTime(), nullable=True))
    op.add_column("refresh_tokens", sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_refresh_tokens_user_active_expiry",
        "refresh_tokens",
        ["user_id", "is_revoked", "expires_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_refresh_tokens_user_active_expiry", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "revoked_at")
    op.drop_column("refresh_tokens", "last_used_at")
    op.drop_column("refresh_tokens", "device_name")
    op.drop_column("refresh_tokens", "user_agent")
    op.drop_column("refresh_tokens", "client_ip")
