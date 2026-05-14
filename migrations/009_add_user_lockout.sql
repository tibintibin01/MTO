-- Migration: Add Account Lockout Security
-- Version: 009

ALTER TABLE users ADD COLUMN failed_attempts INT NOT NULL DEFAULT 0 AFTER is_active;
ALTER TABLE users ADD COLUMN lockout_until DATETIME NULL AFTER failed_attempts;
