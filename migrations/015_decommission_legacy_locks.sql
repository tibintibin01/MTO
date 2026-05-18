-- Decommission the legacy, unused manual edit locks tables
DROP TABLE IF EXISTS property_edit_locks;
DROP TABLE IF EXISTS payment_post_locks;
DROP TABLE IF EXISTS user_edit_locks;
