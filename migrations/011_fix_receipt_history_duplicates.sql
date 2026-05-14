-- Fix duplicates in receipt_history and add unique constraint
-- This prevents the "Regenerate" button from creating duplicate entries in the ledger

-- 1. Cleanup: Remove older duplicate records for the same payment_id, keeping only the one with the highest ID
DELETE FROM receipt_history 
WHERE id NOT IN (
    SELECT max_id FROM (
        SELECT MAX(id) as max_id 
        FROM receipt_history 
        GROUP BY payment_id
    ) as tmp
) AND payment_id IS NOT NULL;

-- 2. Prevent future duplicates by adding a UNIQUE constraint on payment_id
-- This allows the INSERT ... ON DUPLICATE KEY UPDATE logic to work as intended
ALTER TABLE receipt_history ADD UNIQUE KEY uq_receipt_history_payment_id (payment_id);
