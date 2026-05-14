-- Add discount column to properties table
ALTER TABLE properties 
ADD COLUMN discount DECIMAL(15,2) DEFAULT 0.00 AFTER penalty;

-- Update total due calculation logic in any relevant views or queries would happen in code
