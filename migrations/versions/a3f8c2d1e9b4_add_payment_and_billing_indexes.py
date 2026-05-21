"""add_payment_and_billing_indexes

Revision ID: a3f8c2d1e9b4
Revises: 1270f4fb9572
Create Date: 2026-05-19

Changes:
  1. ix_payments_property_id      — payments.property_id (FK lookups, ledger queries)
  2. ix_payments_date_paid        — payments.date_paid (trend/KPI queries, date range filters)
  3. ix_payments_or_number        — payments.or_number (receipt search)
  4. ix_property_billings_property_id_tax_year — composite (property_id, tax_year)
                                    (billing reconciliation, sync_property_billing lookups)
  5. ix_receipt_history_payment_id — receipt_history.payment_id (receipt JOIN in ledger queries)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'a3f8c2d1e9b4'
down_revision = '1270f4fb9572'
branch_labels = None
depends_on = None


def _index_exists(conn, index_name, table_name):
    """Returns True if the named index already exists on the given table."""
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() "
        "AND table_name = :table AND index_name = :index"
    ), {"table": table_name, "index": index_name}).scalar()
    return result > 0


def upgrade():
    conn = op.get_bind()

    # 1. payments.property_id
    if not _index_exists(conn, "ix_payments_property_id", "payments"):
        op.create_index("ix_payments_property_id", "payments", ["property_id"])

    # 2. payments.date_paid
    if not _index_exists(conn, "ix_payments_date_paid", "payments"):
        op.create_index("ix_payments_date_paid", "payments", ["date_paid"])

    # 3. payments.or_number
    if not _index_exists(conn, "ix_payments_or_number", "payments"):
        op.create_index("ix_payments_or_number", "payments", ["or_number"])

    # 4. property_billings composite (property_id, tax_year)
    if not _index_exists(conn, "ix_property_billings_property_id_tax_year", "property_billings"):
        op.create_index(
            "ix_property_billings_property_id_tax_year",
            "property_billings",
            ["property_id", "tax_year"],
        )

    # 5. receipt_history.payment_id
    if not _index_exists(conn, "ix_receipt_history_payment_id", "receipt_history"):
        op.create_index("ix_receipt_history_payment_id", "receipt_history", ["payment_id"])


def downgrade():
    op.drop_index("ix_receipt_history_payment_id", table_name="receipt_history")
    op.drop_index("ix_property_billings_property_id_tax_year", table_name="property_billings")
    op.drop_index("ix_payments_or_number", table_name="payments")
    op.drop_index("ix_payments_date_paid", table_name="payments")
    op.drop_index("ix_payments_property_id", table_name="payments")
