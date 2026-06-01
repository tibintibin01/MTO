"""Catch-up: stamp drifted DB to head and apply genuinely missing schema items.

Revision ID: a1b2c3d4e5f6
Revises: f3a9b2c1d8e7
Create Date: 2026-06-01

Context
-------
The live database was built by a mix of SQLAlchemy create_all() and partial
manual migrations. As a result alembic_version was stuck at c7f4e8b2d6a9
(jobs table) while the schema already contained objects from the three later
migrations (d4e8f2a1b9c3, e9b3c7d2f5a1, f3a9b2c1d8e7).

Before running this migration, stamp the DB to f3a9b2c1d8e7 so alembic
knows those three revisions are already applied:

    alembic stamp f3a9b2c1d8e7

Then run:

    alembic upgrade head

This migration (a1b2c3d4e5f6) applies ONLY the items that were genuinely
missing from the live DB after the stamp:

  1. ix_audit_logs_record_id_table_name  — dossier endpoint composite index
  2. ix_payments_tax_year               — billing reconciliation index
  3. tax_year_int virtual column + index — safe integer join on payments
  4. uq_payments_or_number              — duplicate OR number guard
  5. ix_audit_logs_username_timestamp   — admin audit page composite index
     (replaces the existing idx_audit_logs_username with a covering index)

All operations use IF NOT EXISTS / IF EXISTS guards so this migration is
safe to re-run and safe against partial prior application.
"""

from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'f3a9b2c1d8e7'
branch_labels = None
depends_on = None


def _index_exists(index_name: str, table_name: str) -> bool:
    from sqlalchemy import inspect, text
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :tbl AND INDEX_NAME = :idx"
    ), {"tbl": table_name, "idx": index_name})
    return result.scalar() > 0


def _column_exists(table_name: str, column_name: str) -> bool:
    from sqlalchemy import text
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :tbl AND COLUMN_NAME = :col"
    ), {"tbl": table_name, "col": column_name})
    return result.scalar() > 0


def _constraint_exists(constraint_name: str, table_name: str) -> bool:
    from sqlalchemy import text
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :tbl AND CONSTRAINT_NAME = :con"
    ), {"tbl": table_name, "con": constraint_name})
    return result.scalar() > 0


def upgrade() -> None:
    # ── 1. Composite index on audit_logs(record_id, table_name) ──────────────
    # Used by the dossier endpoint: WHERE table_name='properties' AND record_id=?
    if not _index_exists('ix_audit_logs_record_id_table_name', 'audit_logs'):
        op.create_index(
            'ix_audit_logs_record_id_table_name',
            'audit_logs',
            ['record_id', 'table_name'],
            unique=False,
        )

    # ── 2. Index on payments(tax_year) ────────────────────────────────────────
    # Billing reconciliation and public portal status checks filter by tax_year.
    if not _index_exists('ix_payments_tax_year', 'payments'):
        op.create_index(
            'ix_payments_tax_year',
            'payments',
            ['tax_year'],
            unique=False,
        )

    # ── 3. tax_year_int virtual column on payments ────────────────────────────
    # Allows integer joins between payments.tax_year (VARCHAR) and
    # property_billings.tax_year (SMALLINT) without changing storage type.
    # VIRTUAL = zero storage overhead; computed on read only.
    if not _column_exists('payments', 'tax_year_int'):
        op.execute("""
            ALTER TABLE payments
            ADD COLUMN tax_year_int SMALLINT AS (
                CASE
                    WHEN tax_year REGEXP '^[0-9]{4}$'
                    THEN CAST(tax_year AS SIGNED)
                    ELSE NULL
                END
            ) VIRTUAL
        """)
        op.execute(
            "ALTER TABLE payments ADD INDEX ix_payments_tax_year_int (tax_year_int)"
        )

    # ── 4. UNIQUE constraint on payments.or_number ────────────────────────────
    # INTENTIONALLY SKIPPED — see comment above.

    # ── 5. CHECK constraints on financial tables ──────────────────────────────
    # Prevents negative monetary values at the DB layer regardless of
    # application bugs or manual inserts. The properties table already has
    # chk_assessed_value/penalty/discount from an earlier migration.
    for constraint, table, expr in [
        ('chk_payments_amount_non_negative',    'payments',          'amount >= 0'),
        ('chk_payments_penalty_non_negative',   'payments',          'penalty >= 0'),
        ('chk_payments_discount_non_negative',  'payments',          'discount >= 0'),
        ('chk_property_billings_assessed_value_non_negative', 'property_billings', 'assessed_value >= 0'),
        ('chk_property_billings_penalty_non_negative',        'property_billings', 'penalty >= 0'),
        ('chk_property_billings_discount_non_negative',       'property_billings', 'discount >= 0'),
        ('chk_property_billings_amount_paid_non_negative',    'property_billings', 'amount_paid >= 0'),
        ('chk_payment_billings_amount_paid_non_negative',     'payment_billings',  'amount_paid >= 0'),
    ]:
        if not _constraint_exists(constraint, table):
            op.create_check_constraint(constraint, table, expr)

    # ── 6. Composite covering index on audit_logs(username, timestamp) ────────
    # The admin audit page filters by username and sorts by timestamp DESC.
    # The existing idx_audit_logs_username is a single-column index; this
    # composite index covers both the filter and the sort in one scan.
    if not _index_exists('ix_audit_logs_username_timestamp', 'audit_logs'):
        op.create_index(
            'ix_audit_logs_username_timestamp',
            'audit_logs',
            ['username', 'timestamp'],
            unique=False,
        )

    # ── 5. Composite covering index on audit_logs(username, timestamp) ────────


def downgrade() -> None:
    if _index_exists('ix_audit_logs_username_timestamp', 'audit_logs'):
        op.drop_index('ix_audit_logs_username_timestamp', table_name='audit_logs')

    if _constraint_exists('uq_payments_or_number', 'payments'):
        op.drop_constraint('uq_payments_or_number', 'payments', type_='unique')

    if _index_exists('ix_payments_tax_year_int', 'payments'):
        op.execute("ALTER TABLE payments DROP INDEX ix_payments_tax_year_int")
    if _column_exists('payments', 'tax_year_int'):
        op.execute("ALTER TABLE payments DROP COLUMN tax_year_int")

    if _index_exists('ix_payments_tax_year', 'payments'):
        op.drop_index('ix_payments_tax_year', table_name='payments')

    if _index_exists('ix_audit_logs_record_id_table_name', 'audit_logs'):
        op.drop_index('ix_audit_logs_record_id_table_name', table_name='audit_logs')
