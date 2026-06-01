"""Add composite unique constraint on payments (or_number, property_id, tax_year_int).

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-06-01

Context
-------
A simple UNIQUE(or_number) constraint was previously skipped because the live
data contains legitimate multi-year receipts where one OR number covers multiple
tax years for the same property (one row per year, same receipt).

Now that the tax_year_int virtual column exists (added in a1b2c3d4e5f6), we can
enforce the correct business rule at the DB layer:

    UNIQUE(or_number, property_id, tax_year_int)

This means:
  - The same OR number CAN appear on multiple rows for the same property
    as long as each row covers a different tax year. ✅ (multi-year receipts)
  - The same OR number CANNOT appear twice for the same property AND same year. ❌
  - The same OR number CAN appear on different properties (different cashiers
    may reuse OR numbers across different tax declarations). ✅

Pre-flight check (run before upgrading):
    SELECT or_number, property_id, tax_year_int, COUNT(*)
    FROM payments
    WHERE or_number IS NOT NULL AND tax_year_int IS NOT NULL
    GROUP BY or_number, property_id, tax_year_int
    HAVING COUNT(*) > 1;

If any rows are returned, those are genuine duplicate postings that must be
resolved before this migration can run.
"""

from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def _constraint_exists(table: str, name: str) -> bool:
    from sqlalchemy import text
    bind = op.get_bind()
    row = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :t AND CONSTRAINT_NAME = :n"
    ), {"t": table, "n": name}).scalar()
    return bool(row)


def upgrade():
    if not _constraint_exists('payments', 'uq_payments_or_property_year'):
        # MariaDB UNIQUE indexes allow multiple NULLs, so rows where
        # or_number or tax_year_int is NULL are unaffected by this constraint.
        op.execute("""
            ALTER TABLE payments
            ADD CONSTRAINT uq_payments_or_property_year
            UNIQUE (or_number, property_id, tax_year_int)
        """)


def downgrade():
    if _constraint_exists('payments', 'uq_payments_or_property_year'):
        op.drop_constraint('uq_payments_or_property_year', 'payments', type_='unique')
