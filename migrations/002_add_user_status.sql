-- Migration: Add is_active to users
-- Version: 002

ALTER TABLE users ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1 AFTER role;
ALTER TABLE users ADD COLUMN payor_name VARCHAR(255) NULL AFTER full_name; -- In case we need it for users too, but maybe not.
