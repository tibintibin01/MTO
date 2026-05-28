"""add_retention_and_cleanup_tables

Revision ID: e9b3c7d2f5a1
Revises: d4e8f2a1b9c3
Create Date: 2026-05-21

Changes:
  1. Creates tax_policies table — configurable RPT rates per tax year.
  2. Creates or_sequences table — atomic OR number generation.
  3. Creates retention_policies table — RA 10173 / DICT MC 2022-002 compliance.
  4. Creates retention_logs table — immutable audit trail for retention actions.
  5. Adds missing columns to existing tables:
     - users: deleted_at, password_changed_at, full_name (if missing)
     - properties: deleted_at, archived, version, barangay, block_number,
                   prev_td_number, effectivity_date, pin
     - payments: penalty, discount
  6. Creates system_stats table for dashboard KPI caching.
  7. Creates backup_history table for backup audit trail.
  8. Creates refresh_tokens table for secure session management.
  9. Creates idempotency_keys table for duplicate payment prevention.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e9b3c7d2f5a1'
down_revision = 'd4e8f2a1b9c3'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    from sqlalchemy import inspect
    bind = op.get_bind()
    return inspect(bind).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    from sqlalchemy import inspect
    bind = op.get_bind()
    cols = [c['name'] for c in inspect(bind).get_columns(table_name)]
    return column_name in cols


def upgrade():
    # ── tax_policies ──────────────────────────────────────────────────────────
    if not _table_exists('tax_policies'):
        op.create_table(
            'tax_policies',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('tax_year', sa.SmallInteger(), nullable=False, unique=True),
            sa.Column('basic_rate', sa.DECIMAL(6, 4), nullable=False, server_default='0.0100'),
            sa.Column('sef_rate', sa.DECIMAL(6, 4), nullable=False, server_default='0.0100'),
            sa.Column('penalty_rate', sa.DECIMAL(6, 4), nullable=False, server_default='0.0200'),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
        )
        op.create_index('ix_tax_policies_tax_year', 'tax_policies', ['tax_year'])
        # Seed default policies 2020–2030
        op.execute("""
            INSERT IGNORE INTO tax_policies (tax_year, basic_rate, sef_rate, penalty_rate)
            VALUES (2020,0.0100,0.0100,0.0200),(2021,0.0100,0.0100,0.0200),
                   (2022,0.0100,0.0100,0.0200),(2023,0.0100,0.0100,0.0200),
                   (2024,0.0100,0.0100,0.0200),(2025,0.0100,0.0100,0.0200),
                   (2026,0.0100,0.0100,0.0200),(2027,0.0100,0.0100,0.0200),
                   (2028,0.0100,0.0100,0.0200),(2029,0.0100,0.0100,0.0200),
                   (2030,0.0100,0.0100,0.0200)
        """)

    # ── or_sequences ──────────────────────────────────────────────────────────
    if not _table_exists('or_sequences'):
        op.create_table(
            'or_sequences',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('prefix', sa.String(50), nullable=False, unique=True),
            sa.Column('next_value', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('digits', sa.Integer(), nullable=False, server_default='6'),
        )
        op.create_index('ix_or_sequences_prefix', 'or_sequences', ['prefix'])

    # ── system_stats ──────────────────────────────────────────────────────────
    if not _table_exists('system_stats'):
        op.create_table(
            'system_stats',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('stat_key', sa.String(100), nullable=False, unique=True),
            sa.Column('stat_value', sa.DECIMAL(18, 2), server_default='0.00'),
            sa.Column('last_updated', sa.DateTime(), server_default=sa.func.current_timestamp()),
            sa.Column('metadata_json', sa.Text(), nullable=True),
        )
        op.create_index('ix_system_stats_stat_key', 'system_stats', ['stat_key'])

    # ── backup_history ────────────────────────────────────────────────────────
    if not _table_exists('backup_history'):
        op.create_table(
            'backup_history',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('file_path', sa.Text(), nullable=False),
            sa.Column('checksum', sa.String(64), nullable=True),
            sa.Column('status', sa.String(50), server_default='PENDING'),
            sa.Column('health', sa.String(100), server_default='UNKNOWN'),
            sa.Column('user_name', sa.String(255), nullable=True),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
        )

    # ── refresh_tokens ────────────────────────────────────────────────────────
    if not _table_exists('refresh_tokens'):
        op.create_table(
            'refresh_tokens',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('token', sa.String(512), nullable=False, unique=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
            sa.Column('is_revoked', sa.Boolean(), server_default='0'),
        )
        op.create_index('ix_refresh_tokens_token', 'refresh_tokens', ['token'])

    # ── idempotency_keys ──────────────────────────────────────────────────────
    if not _table_exists('idempotency_keys'):
        op.create_table(
            'idempotency_keys',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('key', sa.String(200), nullable=False, unique=True),
            sa.Column('method', sa.String(10), nullable=False),
            sa.Column('path', sa.String(255), nullable=False),
            sa.Column('status_code', sa.Integer(), nullable=False, server_default='200'),
            sa.Column('response_body', sa.Text(), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_idempotency_keys_key', 'idempotency_keys', ['key'])

    # ── retention_policies ────────────────────────────────────────────────────
    if not _table_exists('retention_policies'):
        op.create_table(
            'retention_policies',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('data_type', sa.String(100), nullable=False, unique=True),
            sa.Column('description', sa.String(500), nullable=False),
            sa.Column('retention_years', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(20), nullable=False, server_default='ARCHIVE'),
            sa.Column('legal_basis', sa.String(255), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
        )
        op.create_index('ix_retention_policies_data_type', 'retention_policies', ['data_type'])

    # ── retention_logs ────────────────────────────────────────────────────────
    if not _table_exists('retention_logs'):
        op.create_table(
            'retention_logs',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('policy_id', sa.Integer(), sa.ForeignKey('retention_policies.id', ondelete='RESTRICT'), nullable=False),
            sa.Column('data_type', sa.String(100), nullable=False),
            sa.Column('action', sa.String(20), nullable=False),
            sa.Column('records_affected', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('cutoff_date', sa.DateTime(), nullable=False),
            sa.Column('executed_by', sa.String(150), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('executed_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_retention_logs_policy_id', 'retention_logs', ['policy_id'])

    # ── Add missing columns to existing tables ────────────────────────────────
    # users
    for col_name, col_def in [
        ('deleted_at', sa.Column('deleted_at', sa.DateTime(), nullable=True)),
        ('password_changed_at', sa.Column('password_changed_at', sa.DateTime(), nullable=True)),
        ('full_name', sa.Column('full_name', sa.String(255), nullable=False, server_default='')),
    ]:
        if not _column_exists('users', col_name):
            op.add_column('users', col_def)

    # properties
    for col_name, col_def in [
        ('deleted_at', sa.Column('deleted_at', sa.DateTime(), nullable=True)),
        ('archived', sa.Column('archived', sa.Boolean(), nullable=False, server_default='0')),
        ('version', sa.Column('version', sa.Integer(), server_default='1')),
        ('barangay', sa.Column('barangay', sa.String(255), nullable=True)),
        ('block_number', sa.Column('block_number', sa.String(100), nullable=True)),
        ('prev_td_number', sa.Column('prev_td_number', sa.String(100), nullable=True)),
        ('effectivity_date', sa.Column('effectivity_date', sa.String(100), nullable=True)),
        ('pin', sa.Column('pin', sa.String(100), nullable=True)),
    ]:
        if not _column_exists('properties', col_name):
            op.add_column('properties', col_def)

    # payments
    for col_name, col_def in [
        ('penalty', sa.Column('penalty', sa.DECIMAL(14, 2), server_default='0.00')),
        ('discount', sa.Column('discount', sa.DECIMAL(14, 2), server_default='0.00')),
    ]:
        if not _column_exists('payments', col_name):
            op.add_column('payments', col_def)


def downgrade():
    # Drop new tables in reverse dependency order
    if _table_exists('retention_logs'):
        op.drop_table('retention_logs')
    if _table_exists('retention_policies'):
        op.drop_table('retention_policies')
    if _table_exists('idempotency_keys'):
        op.drop_table('idempotency_keys')
    if _table_exists('refresh_tokens'):
        op.drop_table('refresh_tokens')
    if _table_exists('backup_history'):
        op.drop_table('backup_history')
    if _table_exists('system_stats'):
        op.drop_table('system_stats')
    if _table_exists('or_sequences'):
        op.drop_table('or_sequences')
    if _table_exists('tax_policies'):
        op.drop_table('tax_policies')
