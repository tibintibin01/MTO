-- Migration: Upgrade Audit Logs to support forensic tracing
-- Version: 003

ALTER TABLE audit_logs 
ADD COLUMN user_id INT NULL AFTER id,
MODIFY COLUMN username VARCHAR(255) NOT NULL,
ADD COLUMN table_name VARCHAR(100) NULL AFTER action,
ADD COLUMN record_id INT NULL AFTER table_name,
ADD COLUMN old_values LONGTEXT NULL AFTER record_id,
ADD COLUMN new_values LONGTEXT NULL AFTER old_values,
ADD COLUMN ip_address VARCHAR(45) NULL AFTER new_values,
ADD INDEX idx_audit_logs_user_id (user_id);
