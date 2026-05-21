-- =============================================================================
-- Migration 018: Financial Integrity Constraints
-- WIN 2: Add CHECK constraints on monetary amounts and UNIQUE on or_number.
--
-- Rationale:
--   - Negative amounts are never valid for payments, assessed values, or
--     billing records. A CHECK constraint enforces this at the DB layer so
--     no application bug or manual insert can create invalid financial data.
--   - Duplicate OR (Official Receipt) numbers are a serious accounting fraud
--     signal. The application generates them via ORSequence with row-level
--     locking, but a manual insert or a buggy migration could create dupes
--     silently. UNIQUE closes that gap.
--
-- MariaDB 10.2+ enforces CHECK constraints. Earlier versions parse but ignore
-- them — upgrade to 10.2+ before relying on these for hard enforcement.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- payments table
-- ---------------------------------------------------------------------------

-- Prevent negative payment amounts
ALTER TABLE payments
    ADD CONSTRAINT chk_payments_amount_non_negative
        CHECK (amount >= 0);

ALTER TABLE payments
    ADD CONSTRAINT chk_payments_penalty_non_negative
        CHECK (penalty >= 0);

ALTER TABLE payments
    ADD CONSTRAINT chk_payments_discount_non_negative
        CHECK (discount >= 0);

-- Unique OR number — a receipt number must never be reused.
-- NOTE: or_number is nullable (pre-payment property records have no OR).
-- MariaDB allows multiple NULLs in a UNIQUE index, so this is safe.
ALTER TABLE payments
    ADD CONSTRAINT uq_payments_or_number
        UNIQUE (or_number);

-- ---------------------------------------------------------------------------
-- properties table
-- ---------------------------------------------------------------------------

ALTER TABLE properties
    ADD CONSTRAINT chk_properties_assessed_value_non_negative
        CHECK (assessed_value >= 0);

ALTER TABLE properties
    ADD CONSTRAINT chk_properties_penalty_non_negative
        CHECK (penalty >= 0);

ALTER TABLE properties
    ADD CONSTRAINT chk_properties_discount_non_negative
        CHECK (discount >= 0);

-- ---------------------------------------------------------------------------
-- property_billings table
-- ---------------------------------------------------------------------------

ALTER TABLE property_billings
    ADD CONSTRAINT chk_property_billings_assessed_value_non_negative
        CHECK (assessed_value >= 0);

ALTER TABLE property_billings
    ADD CONSTRAINT chk_property_billings_penalty_non_negative
        CHECK (penalty >= 0);

ALTER TABLE property_billings
    ADD CONSTRAINT chk_property_billings_discount_non_negative
        CHECK (discount >= 0);

ALTER TABLE property_billings
    ADD CONSTRAINT chk_property_billings_amount_paid_non_negative
        CHECK (amount_paid >= 0);

-- ---------------------------------------------------------------------------
-- payment_billings table
-- ---------------------------------------------------------------------------

ALTER TABLE payment_billings
    ADD CONSTRAINT chk_payment_billings_amount_paid_non_negative
        CHECK (amount_paid >= 0);
