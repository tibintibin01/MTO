"""add_deleted_at_and_restrict_cascades

Revision ID: 87249241749c
Revises: 15a23adcbe4b
Create Date: 2026-05-19 07:16:55.501367

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '87249241749c'
down_revision = '15a23adcbe4b'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
    """), {"table_name": table_name}).scalar())


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND column_name = :column_name
    """), {"table_name": table_name, "column_name": column_name}).scalar())


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND index_name = :index_name
    """), {"table_name": table_name, "index_name": index_name}).scalar())


def _foreign_keys_for_column(table_name: str, column_name: str) -> list[str]:
    conn = op.get_bind()
    rows = conn.execute(text("""
        SELECT constraint_name
        FROM information_schema.key_column_usage
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND column_name = :column_name
          AND referenced_table_name IS NOT NULL
    """), {"table_name": table_name, "column_name": column_name}).fetchall()
    return [row[0] for row in rows]


def _drop_foreign_keys_for_column(table_name: str, column_name: str) -> None:
    if not _table_exists(table_name) or not _column_exists(table_name, column_name):
        return

    for constraint_name in _foreign_keys_for_column(table_name, column_name):
        op.drop_constraint(constraint_name, table_name, type_='foreignkey')


def _create_fk_if_missing(
    constraint_name: str,
    source_table: str,
    referent_table: str,
    local_cols: list[str],
    remote_cols: list[str],
    ondelete: str,
) -> None:
    if not _table_exists(source_table) or not _table_exists(referent_table):
        return
    if any(not _column_exists(source_table, col) for col in local_cols):
        return
    if any(not _column_exists(referent_table, col) for col in remote_cols):
        return

    op.create_foreign_key(
        constraint_name,
        source_table,
        referent_table,
        local_cols,
        remote_cols,
        ondelete=ondelete,
    )


def _ensure_billing_tables() -> None:
    if not _table_exists('property_billings'):
        op.create_table(
            'property_billings',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('property_id', sa.Integer(), nullable=False),
            sa.Column('tax_year', sa.SmallInteger(), nullable=False),
            sa.Column('assessed_value', sa.DECIMAL(14, 2), nullable=False, server_default='0.00'),
            sa.Column('penalty', sa.DECIMAL(14, 2), nullable=False, server_default='0.00'),
            sa.Column('discount', sa.DECIMAL(14, 2), nullable=False, server_default='0.00'),
            sa.Column('amount_paid', sa.DECIMAL(14, 2), nullable=False, server_default='0.00'),
            sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
        )

    if not _index_exists('property_billings', 'ix_property_billings_property_id_tax_year'):
        op.create_index(
            'ix_property_billings_property_id_tax_year',
            'property_billings',
            ['property_id', 'tax_year'],
            unique=True,
        )

    if not _table_exists('payment_billings'):
        op.create_table(
            'payment_billings',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('payment_id', sa.Integer(), nullable=False),
            sa.Column('billing_id', sa.Integer(), nullable=False),
            sa.Column('tax_year', sa.SmallInteger(), nullable=False),
            sa.Column('amount_paid', sa.DECIMAL(14, 2), nullable=False, server_default='0.00'),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
        )


def _ensure_assessment_history_table() -> None:
    if not _table_exists('property_assessment_history'):
        op.create_table(
            'property_assessment_history',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('property_id', sa.Integer(), nullable=False),
            sa.Column('td_number', sa.String(100)),
            sa.Column('assessed_value', sa.DECIMAL(14, 2)),
            sa.Column('tax_year', sa.String(100)),
            sa.Column('kind_of_property', sa.String(100)),
            sa.Column('changed_by', sa.String(255)),
            sa.Column('change_reason', sa.String(255), server_default='Import Update'),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
        )


def _replace_property_fk(table_name: str, column_name: str, constraint_name: str, ondelete: str) -> None:
    _drop_foreign_keys_for_column(table_name, column_name)
    _create_fk_if_missing(
        constraint_name,
        table_name,
        'properties',
        [column_name],
        ['id'],
        ondelete=ondelete,
    )


def upgrade() -> None:
    # 1. Add 'deleted_at' column to 'users' and 'properties'
    if not _column_exists('users', 'deleted_at'):
        op.add_column('users', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    if not _column_exists('properties', 'deleted_at'):
        op.add_column('properties', sa.Column('deleted_at', sa.DateTime(), nullable=True))

    # 2. Create indices for faster soft-delete filtering
    if not _index_exists('users', 'ix_users_deleted_at'):
        op.create_index(op.f('ix_users_deleted_at'), 'users', ['deleted_at'], unique=False)
    if not _index_exists('properties', 'ix_properties_deleted_at'):
        op.create_index(op.f('ix_properties_deleted_at'), 'properties', ['deleted_at'], unique=False)

    # 3. Migrate existing is_deleted = True records to current timestamp
    if _column_exists('users', 'is_deleted'):
        op.execute("UPDATE users SET deleted_at = NOW() WHERE is_deleted = 1")
    if _column_exists('properties', 'is_deleted'):
        op.execute("UPDATE properties SET deleted_at = NOW() WHERE is_deleted = 1")

    # 4. Ensure tables introduced in the ORM exist on fresh/cloud databases.
    _ensure_billing_tables()
    _ensure_assessment_history_table()

    # 5. Drop the obsolete 'is_deleted' columns
    if _column_exists('users', 'is_deleted'):
        op.drop_column('users', 'is_deleted')
    if _column_exists('properties', 'is_deleted'):
        op.drop_column('properties', 'is_deleted')

    # 6. Recreate foreign key constraints to enforce ON DELETE RESTRICT.
    # MySQL may auto-name FKs from earlier migrations, so drop by table/column.
    _replace_property_fk('payments', 'property_id', 'fk_payments_property', 'RESTRICT')
    _replace_property_fk('property_billings', 'property_id', 'fk_property_billings_property', 'RESTRICT')
    _replace_property_fk('property_assessment_history', 'property_id', 'fk_assessment_history_property', 'RESTRICT')
    _replace_property_fk('receipt_history', 'property_id', 'fk_receipt_history_property', 'RESTRICT')

    _drop_foreign_keys_for_column('payment_billings', 'payment_id')
    _create_fk_if_missing(
        'fk_payment_billings_payment',
        'payment_billings',
        'payments',
        ['payment_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    # 1. Revert constraints to CASCADE (original model state)
    _replace_property_fk('receipt_history', 'property_id', 'fk_receipt_history_property', 'CASCADE')
    _replace_property_fk('property_assessment_history', 'property_id', 'fk_assessment_history_property', 'CASCADE')
    _replace_property_fk('property_billings', 'property_id', 'fk_property_billings_property', 'CASCADE')
    _replace_property_fk('payments', 'property_id', 'fk_payments_property', 'CASCADE')

    # 2. Add back 'is_deleted' columns
    if not _column_exists('properties', 'is_deleted'):
        op.add_column('properties', sa.Column('is_deleted', sa.Boolean(), server_default='0', nullable=False))
    if not _column_exists('users', 'is_deleted'):
        op.add_column('users', sa.Column('is_deleted', sa.Boolean(), server_default='0', nullable=False))

    # 3. Restore soft deleted markers to is_deleted
    op.execute("UPDATE users SET is_deleted = 1 WHERE deleted_at IS NOT NULL")
    op.execute("UPDATE properties SET is_deleted = 1 WHERE deleted_at IS NOT NULL")

    # 4. Remove 'deleted_at' columns and indexes
    if _index_exists('properties', 'ix_properties_deleted_at'):
        op.drop_index(op.f('ix_properties_deleted_at'), table_name='properties')
    if _column_exists('properties', 'deleted_at'):
        op.drop_column('properties', 'deleted_at')

    if _index_exists('users', 'ix_users_deleted_at'):
        op.drop_index(op.f('ix_users_deleted_at'), table_name='users')
    if _column_exists('users', 'deleted_at'):
        op.drop_column('users', 'deleted_at')
