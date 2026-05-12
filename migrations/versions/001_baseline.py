"""Baseline municipal schema.

Revision ID: 001_baseline
Revises: 
Create Date: 2026-05-12 14:52:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001_baseline'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # --- USERS TABLE ---
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(50), nullable=False, unique=True),
        sa.Column('full_name', sa.String(100)),
        sa.Column('password', sa.String(255), nullable=False),
        sa.Column('role', sa.String(20), server_default='viewer'),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('is_deleted', sa.Boolean(), server_default='0'),
        sa.Column('failed_attempts', sa.Integer(), server_default='0'),
        sa.Column('lockout_until', sa.DateTime()),
        sa.Column('last_login', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now())
    )

    # --- PROPERTIES TABLE ---
    op.create_table(
        'properties',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('td_number', sa.String(50), nullable=False),
        sa.Column('owner_name', sa.String(255)),
        sa.Column('payor_name', sa.String(255)),
        sa.Column('lot_number', sa.String(50)),
        sa.Column('area', sa.String(50)),
        sa.Column('location', sa.Text()),
        sa.Column('kind_of_property', sa.String(50)),
        sa.Column('accountable_officer', sa.String(100)),
        sa.Column('assessed_value', sa.Numeric(15, 2), server_default='0.00'),
        sa.Column('penalty', sa.Numeric(15, 2), server_default='0.00'),
        sa.Column('discount', sa.Numeric(15, 2), server_default='0.00'),
        sa.Column('or_number', sa.String(50)),
        sa.Column('or_date', sa.Date()),
        sa.Column('tax_year', sa.String(20)),
        sa.Column('pin', sa.String(50)),
        sa.Column('block_number', sa.String(50)),
        sa.Column('prev_td_number', sa.String(50)),
        sa.Column('effectivity_date', sa.String(50)),
        sa.Column('barangay', sa.String(100)),
        sa.Column('is_deleted', sa.Boolean(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now())
    )

    # --- PAYMENTS TABLE ---
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('property_id', sa.Integer(), sa.ForeignKey('properties.id')),
        sa.Column('or_number', sa.String(50)),
        sa.Column('date_paid', sa.Date()),
        sa.Column('tax_year', sa.String(20)),
        sa.Column('amount', sa.Numeric(15, 2), server_default='0.00'),
        sa.Column('posted_by', sa.String(100)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now())
    )

    # --- RECEIPT HISTORY TABLE ---
    op.create_table(
        'receipt_history',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('property_id', sa.Integer(), sa.ForeignKey('properties.id')),
        sa.Column('payment_id', sa.Integer(), sa.ForeignKey('payments.id')),
        sa.Column('or_number', sa.String(50)),
        sa.Column('file_path', sa.Text()),
        sa.Column('generated_by', sa.String(100)),
        sa.Column('generated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('status', sa.String(50))
    )

    # --- AUDIT LOGS TABLE ---
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer()),
        sa.Column('username', sa.String(100)),
        sa.Column('action', sa.Text()),
        sa.Column('table_name', sa.String(50)),
        sa.Column('record_id', sa.Integer()),
        sa.Column('old_values', sa.JSON()),
        sa.Column('new_values', sa.JSON()),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.func.now())
    )

    # --- LOCKS TABLES ---
    for table_name in ['property_edit_locks', 'payment_post_locks', 'user_edit_locks']:
        op.create_table(
            table_name,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('property_id', sa.Integer()) if table_name == 'property_edit_locks' else sa.Column('user_id', sa.Integer()) if table_name == 'user_edit_locks' else sa.Column('receipt_number', sa.String(50)),
            sa.Column('locked_by', sa.String(100)),
            sa.Column('locked_at', sa.DateTime(), server_default=sa.func.now())
        )

def downgrade() -> None:
    op.drop_table('user_edit_locks')
    op.drop_table('payment_post_locks')
    op.drop_table('property_edit_locks')
    op.drop_table('audit_logs')
    op.drop_table('receipt_history')
    op.drop_table('payments')
    op.drop_table('properties')
    op.drop_table('users')
