"""add_td_number_unique_and_payment_billing_fk

Revision ID: 1270f4fb9572
Revises: 87249241749c
Create Date: 2026-05-19

Changes:
  1. De-duplicate properties.td_number by appending suffix to duplicates
  2. Add UNIQUE constraint on properties.td_number
  3. Add FK constraint on payment_billings.billing_id -> property_billings.id (RESTRICT)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = '1270f4fb9572'
down_revision = '87249241749c'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # --- Step 1: Resolve duplicate td_numbers ---
    # Find all td_numbers that appear more than once
    duplicates = conn.execute(text("""
        SELECT td_number, COUNT(*) as cnt
        FROM properties
        WHERE deleted_at IS NULL
        GROUP BY td_number
        HAVING cnt > 1
    """)).fetchall()

    for row in duplicates:
        td = row[0]
        # Get all IDs for this td_number, keep the lowest (oldest) as-is
        ids = conn.execute(text(
            "SELECT id FROM properties WHERE td_number = :td ORDER BY id ASC"
        ), {"td": td}).fetchall()
        # Skip the first (canonical) record; suffix the rest
        for i, id_row in enumerate(ids[1:], start=2):
            new_td = f"{td}_DUP{i}"
            conn.execute(text(
                "UPDATE properties SET td_number = :new_td WHERE id = :id"
            ), {"new_td": new_td, "id": id_row[0]})

    # --- Step 2: Add UNIQUE constraint on properties.td_number ---
    op.create_unique_constraint(
        "uq_properties_td_number",
        "properties",
        ["td_number"]
    )

    # --- Step 3: Add FK on payment_billings.billing_id ---
    # Only add if there are no orphan billing_ids first
    orphan_count = conn.execute(text("""
        SELECT COUNT(*) FROM payment_billings pb
        WHERE NOT EXISTS (
            SELECT 1 FROM property_billings b WHERE b.id = pb.billing_id
        )
    """)).scalar()

    if orphan_count == 0:
        op.create_foreign_key(
            "fk_payment_billings_billing",
            "payment_billings",
            "property_billings",
            ["billing_id"],
            ["id"],
            ondelete="RESTRICT"
        )
    else:
        print(f"WARNING: Skipped FK on payment_billings.billing_id — {orphan_count} orphan rows found.")
        print("Resolve orphans manually then re-run: alembic upgrade head")


def downgrade():
    try:
        op.drop_constraint("fk_payment_billings_billing", "payment_billings", type_="foreignkey")
    except Exception:
        pass
    op.drop_constraint("uq_properties_td_number", "properties", type_="unique")
