-- =============================================================================
-- Migration 019: Widen idempotency_keys.key column
--
-- The idempotency key is now a composite of:
--   {uuid}:{user_id}:{sha256_hex}
--   36     + 1 + 20  + 1 + 64    = 122 characters maximum
--
-- The previous String(128) was just barely sufficient but left no headroom.
-- Widening to 200 is safe — MariaDB VARCHAR only uses as much space as the
-- actual stored value, so there is no storage cost for the extra headroom.
-- =============================================================================

ALTER TABLE idempotency_keys
    MODIFY COLUMN `key` VARCHAR(200) NOT NULL;
