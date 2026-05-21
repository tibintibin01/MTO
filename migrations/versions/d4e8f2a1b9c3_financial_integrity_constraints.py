"""financial_integrity_constraints

Revision ID: d4e8f2a1b9c3
Revises: c7f4e8b2d6a9
Create Date: 2026-05-21

Changes:
  1. CHECK constraints on all monetary columns (amount >= 0, penalty >= 0,
     discount >= 0, amount_paid >= 0) across payments, properties,
     property_billings, and payment_billings tables.
     Prevents negative financial values at the DB layer regardless of
     application-level bugs or manual inserts.

  2. UNIQUE constraint on payments.or_number.
     A duplicate Official Receipt number is a serious accounting fraud signal.
     The application generates OR numbers via ORSequence with row-level locking,
     but this constraint closes the gap for manual inserts or migration bugs.
     NOTE: or_number is nullable — MariaDB allows multiple NULLs in a UNIQUE
     index, so pre-payment property records are unaffected.

  3. Widen idempotency_keys.key column from String(128) to String(200).
     The composite key format is: "{uuid}:{user_id}:{sha256_hex}"
     Max length: 36 + 1 + 20 + 1 + 64 = 122 chars. String(200) gives headroom.

  IMPORTANT — run this pre-flight check before upgrading:
    SELECT or_number, COUNT(*)
    FROM payments
    WHERE or_number IS NOT NULL
    GROUP BY or_number
    HAVING COUNT(*) > 1;
  If any rows are returned, resolve the duplicates before running this migration
  or the UNIQUE constraint creation will fail.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e8f2a1b9c3'
down_revision = 'c7f4e8b2d6a9'
branch_labels = None
depends_on = None


def upgrade():
    # ---------------------------------------------------------------------------
    # payments table
    # ---------------------------------------------------------------------------
    op.create_check_constraint(
        'chk_payments_amount_non_negative',
        'payments',
        'amount >= 0'
    )
    op.create_check_constraint(
        'chk_payments_penalty_non_negative',
        'payments',
        'penalty >= 0'
    )
    op.create_check_constraint(
        'chk_payments_discount_non_negative',
        'payments',
        'discount >= 0'
    )
    # UNIQUE on or_number — nullable column, multiple NULLs allowed in MariaDB
    op.create_unique_constraint(
        'uq_payments_or_number',
        'payments',
        ['or_number']
    )

    # ---------------------------------------------------------------------------
    # properties table
    # ---------------------------------------------------------------------------
    op.create_check_constraint(
        'chk_properties_assessed_value_non_negative',
        'properties',
        'assessed_value >= 0'
    )
    op.create_check_constraint(
        'chk_properties_penalty_non_negative',
        'properties',
        'penalty >= 0'
    )
    op.create_check_constraint(
        'chk_properties_discount_non_negative',
        'properties',
        'discount >= 0'
    )

    # ---------------------------------------------------------------------------
    # property_billings table
    # ---------------------------------------------------------------------------
    op.create_check_constraint(
        'chk_property_billings_assessed_value_non_negative',
        'property_billings',
        'assessed_value >= 0'
    )
    op.create_check_constraint(
        'chk_property_billings_penalty_non_negative',
        'property_billings',
        'penalty >= 0'
    )
    op.create_check_constraint(
        'chk_property_billings_discount_non_negative',
        'property_billings',
        'discount >= 0'
    )
    op.create_check_constraint(
        'chk_property_billings_amount_paid_non_negative',
        'property_billings',
        'amount_paid >= 0'
    )

    # ---------------------------------------------------------------------------
    # payment_billings table
    # ---------------------------------------------------------------------------
    op.create_check_constraint(
        'chk_payment_billings_amount_paid_non_negative',
        'payment_billings',
        'amount_paid >= 0'
    )

    # ---------------------------------------------------------------------------
    # idempotency_keys — widen key column
    # ---------------------------------------------------------------------------
    op.alter_column(
        'idempotency_keys',
        'key',
        existing_type=sa.String(128),
        type_=sa.String(200),
        existing_nullable=False,
    )


def downgrade():
    # Restore idempotency_keys column width
    op.alter_column(
        'idempotency_keys',
        'key',
        existing_type=sa.String(200),
        type_=sa.String(128),
        existing_nullable=False,
    )

    # Drop payment_billings constraints
    op.drop_constraint('chk_payment_billings_amount_paid_non_negative', 'payment_billings', type_='check')

    # Drop property_billings constraints
    op.drop_constraint('chk_property_billings_amount_paid_non_negative', 'property_billings', type_='check')
    op.drop_constraint('chk_property_billings_discount_non_negative', 'property_billings', type_='check')
    op.drop_constraint('chk_property_billings_penalty_non_negative', 'property_billings', type_='check')
    op.drop_constraint('chk_property_billings_assessed_value_non_negative', 'property_billings', type_='check')

    # Drop properties constraints
    op.drop_constraint('chk_properties_discount_non_negative', 'properties', type_='check')
    op.drop_constraint('chk_properties_penalty_non_negative', 'properties', type_='check')
    op.drop_constraint('chk_properties_assessed_value_non_negative', 'properties', type_='check')

    # Drop payments constraints
    op.drop_constraint('uq_payments_or_number', 'payments', type_='unique')
    op.drop_constraint('chk_payments_discount_non_negative', 'payments', type_='check')
    op.drop_constraint('chk_payments_penalty_non_negative', 'payments', type_='check')
    op.drop_constraint('chk_payments_amount_non_negative', 'payments', type_='check')
