"""financial_integrity_constraints

Revision ID: d4e8f2a1b9c3
Revises: c7f4e8b2d6a9
Create Date: 2026-05-21

Changes:
  1. CHECK constraints on all monetary columns (amount >= 0, penalty >= 0,
     discount >= 0, amount_paid >= 0) across payments, properties,
     property_billings, and payment_billings tables.
  2. UNIQUE constraint on payments.or_number.
  3. Widen idempotency_keys.key column from String(128) to String(200).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'd4e8f2a1b9c3'
down_revision = 'c7f4e8b2d6a9'
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


def _column_length(table_name: str, column_name: str) -> int | None:
    conn = op.get_bind()
    return conn.execute(text("""
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND column_name = :column_name
    """), {"table_name": table_name, "column_name": column_name}).scalar()


def _constraint_exists(constraint_name: str, table_name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.table_constraints
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND constraint_name = :constraint_name
    """), {"table_name": table_name, "constraint_name": constraint_name}).scalar())


def _index_exists(index_name: str, table_name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND index_name = :index_name
    """), {"table_name": table_name, "index_name": index_name}).scalar())


def _create_check_if_missing(
    constraint_name: str,
    table_name: str,
    column_name: str,
    expression: str,
) -> None:
    if not _table_exists(table_name) or _constraint_exists(constraint_name, table_name):
        return
    if not _column_exists(table_name, column_name):
        return

    op.create_check_constraint(constraint_name, table_name, expression)


def _create_unique_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _table_exists(table_name) or _constraint_exists(index_name, table_name):
        return
    if _index_exists(index_name, table_name):
        return
    if any(not _column_exists(table_name, column) for column in columns):
        return

    op.create_unique_constraint(index_name, table_name, columns)


def upgrade():
    for constraint, table, column, expr in [
        ('chk_payments_amount_non_negative', 'payments', 'amount', 'amount >= 0'),
        ('chk_payments_penalty_non_negative', 'payments', 'penalty', 'penalty >= 0'),
        ('chk_payments_discount_non_negative', 'payments', 'discount', 'discount >= 0'),
        ('chk_properties_assessed_value_non_negative', 'properties', 'assessed_value', 'assessed_value >= 0'),
        ('chk_properties_penalty_non_negative', 'properties', 'penalty', 'penalty >= 0'),
        ('chk_properties_discount_non_negative', 'properties', 'discount', 'discount >= 0'),
        ('chk_property_billings_assessed_value_non_negative', 'property_billings', 'assessed_value', 'assessed_value >= 0'),
        ('chk_property_billings_penalty_non_negative', 'property_billings', 'penalty', 'penalty >= 0'),
        ('chk_property_billings_discount_non_negative', 'property_billings', 'discount', 'discount >= 0'),
        ('chk_property_billings_amount_paid_non_negative', 'property_billings', 'amount_paid', 'amount_paid >= 0'),
        ('chk_payment_billings_amount_paid_non_negative', 'payment_billings', 'amount_paid', 'amount_paid >= 0'),
    ]:
        _create_check_if_missing(constraint, table, column, expr)

    # UNIQUE on or_number: nullable column, multiple NULLs are allowed in MySQL/MariaDB.
    _create_unique_index_if_missing('uq_payments_or_number', 'payments', ['or_number'])

    # Widen idempotency_keys.key only when the table/column exists and still needs it.
    current_length = _column_length('idempotency_keys', 'key')
    if current_length is not None and current_length < 200:
        op.alter_column(
            'idempotency_keys',
            'key',
            existing_type=sa.String(current_length),
            type_=sa.String(200),
            existing_nullable=False,
        )


def downgrade():
    # Restore idempotency_keys column width
    current_length = _column_length('idempotency_keys', 'key')
    if current_length is not None and current_length > 128:
        op.alter_column(
            'idempotency_keys',
            'key',
            existing_type=sa.String(current_length),
            type_=sa.String(128),
            existing_nullable=False,
        )

    for constraint, table, constraint_type in [
        ('chk_payment_billings_amount_paid_non_negative', 'payment_billings', 'check'),
        ('chk_property_billings_amount_paid_non_negative', 'property_billings', 'check'),
        ('chk_property_billings_discount_non_negative', 'property_billings', 'check'),
        ('chk_property_billings_penalty_non_negative', 'property_billings', 'check'),
        ('chk_property_billings_assessed_value_non_negative', 'property_billings', 'check'),
        ('chk_properties_discount_non_negative', 'properties', 'check'),
        ('chk_properties_penalty_non_negative', 'properties', 'check'),
        ('chk_properties_assessed_value_non_negative', 'properties', 'check'),
        ('uq_payments_or_number', 'payments', 'unique'),
        ('chk_payments_discount_non_negative', 'payments', 'check'),
        ('chk_payments_penalty_non_negative', 'payments', 'check'),
        ('chk_payments_amount_non_negative', 'payments', 'check'),
    ]:
        if _constraint_exists(constraint, table):
            op.drop_constraint(constraint, table, type_=constraint_type)
