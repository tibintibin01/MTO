-- Migration to add versioning for Optimistic Locking in Properties table
ALTER TABLE properties 
ADD COLUMN version INT NOT NULL DEFAULT 1;

-- Update existing records to have a starting version
UPDATE properties SET version = 1 WHERE version IS NULL;
