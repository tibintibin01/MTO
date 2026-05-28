"""Add missing indexes and fix tax_year type mismatch on payments table.

Revision ID: f3a9b2c1d8e7
Revises: e9b3c7d2f5a1
Create Date: 2026-05-28

Changes:
  1. Add index on audit_logs(timestamp)          — audit log date-range queries
  2. Add composite index on audit_logs(record_id, table_name) — dossier endpoint
  3. Add index on payments(tax_year)             — billing reconciliation joins
  4. Fix type mismatch: payments.tax_year String(20) → VARCHAR(20)
     NOTE: PropertyBilling.tax_year is SmallInteger. We intentionally keep
     payments.tax_year as VARCHAR because it stores values like "2023", "2024"
     entered by cashiers and may contain non-numeric legacy data. The mismatch
     in the ORM model is documented — joins must CAST(payments.tax_year AS SIGNED).
     A future migration can normalise this once legacy data is cleaned.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a9b2c1d8e7'
down_revision = 'e9b3c7d2f5a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. audit_logs(timestamp) ─────────────────────────────────────────────
    # Audit log queries always filter by date range (date_from / date_to).
    # Without this index, every audit log query does a full table scan.
    op.create_index(
        'ix_audit_logs_timestamp',
        'audit_logs',
        ['timestamp'],
        unique=False,
    )

    # ── 2. audit_logs(record_id, table_name) composite ───────────────────────
    # The dossier endpoint queries: WHERE table_name = 'properties' AND record_id = ?
    # This composite index covers both filter columns.
    op.create_index(
        'ix_audit_logs_record_id_table_name',
        'audit_logs',
        ['record_id', 'table_name'],
        unique=False,
    )

    # ── 3. payments(tax_year) ────────────────────────────────────────────────
    # Billing reconciliation joins payments to property_billings on tax_year.
    # The delinquency dashboard and public portal status check both filter
    # payments by tax_year — this index makes those queries fast.
    op.create_index(
        'ix_payments_tax_year',
        'payments',
        ['tax_year'],
        unique=False,
    )

    # ── 4. Document the tax_year type mismatch ───────────────────────────────
    # payments.tax_year is VARCHAR(20) — stores cashier-entered strings like "2023"
    # property_billings.tax_year is SMALLINT — stores integer years
    #
    # We add a generated/virtual column on payments to allow integer comparisons
    # without changing the storage type (which would risk data loss on legacy rows).
    #
    # MariaDB 10.2+ supports generated columns. This is safe to add.
    # The column is VIRTUAL (not stored) so it has zero storage overhead.
    #
    # Usage: JOIN property_billings pb ON pb.tax_year = p.tax_year_int
    op.execute("""
        ALTER TABLE payments
        ADD COLUMN tax_year_int SMALLINT AS (
            CASE
                WHEN tax_year REGEXP '^[0-9]{4}$' THEN CAST(tax_year AS SIGNED)
                ELSE NULL
            END
        ) VIRTUAL
    """)

    # Index the virtual column so joins on it are fast
    op.execute("""
        ALTER TABLE payments
        ADD INDEX ix_payments_tax_year_int (tax_year_int)
    """)


def downgrade() -> None:
    # Remove virtual column and its index first
    op.execute("ALTER TABLE payments DROP INDEX ix_payments_tax_year_int")
    op.execute("ALTER TABLE payments DROP COLUMN tax_year_int")

    op.drop_index('ix_payments_tax_year', table_name='payments')
    op.drop_index('ix_audit_logs_record_id_table_name', table_name='audit_logs')
    op.drop_index('ix_audit_logs_timestamp', table_name='audit_logs')
