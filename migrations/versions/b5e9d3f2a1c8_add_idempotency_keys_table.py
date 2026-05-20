"""add_idempotency_keys_table

Revision ID: b5e9d3f2a1c8
Revises: a3f8c2d1e9b4
Create Date: 2026-05-20

Changes:
  1. Creates idempotency_keys table to prevent duplicate payment submissions
     from double-clicks or network retries.
  2. Adds index on (key) for fast lookup and (expires_at) for efficient cleanup.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5e9d3f2a1c8'
down_revision = 'a3f8c2d1e9b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('key', sa.String(128), nullable=False, unique=True),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('path', sa.String(255), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False, default=200),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_idempotency_keys_key', 'idempotency_keys', ['key'], unique=True)
    op.create_index('ix_idempotency_keys_expires_at', 'idempotency_keys', ['expires_at'])


def downgrade():
    op.drop_index('ix_idempotency_keys_expires_at', table_name='idempotency_keys')
    op.drop_index('ix_idempotency_keys_key', table_name='idempotency_keys')
    op.drop_table('idempotency_keys')
