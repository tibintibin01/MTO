-- Add discount column to billing tables
ALTER TABLE property_billings 
ADD COLUMN discount DECIMAL(14,2) DEFAULT 0.00 AFTER penalty;

ALTER TABLE payment_billings 
ADD COLUMN discount DECIMAL(14,2) DEFAULT 0.00 AFTER penalty;
