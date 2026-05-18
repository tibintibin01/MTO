-- Add penalty and discount columns to payments table
ALTER TABLE payments 
ADD COLUMN penalty DECIMAL(12, 2) DEFAULT 0.00 AFTER amount,
ADD COLUMN discount DECIMAL(12, 2) DEFAULT 0.00 AFTER penalty;
