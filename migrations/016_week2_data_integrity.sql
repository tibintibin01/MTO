-- Week 2 Data Integrity & Reliability Updates
-- 1. Create Official Receipt (OR) Sequence Table
CREATE TABLE IF NOT EXISTS or_sequences (
    id INT AUTO_INCREMENT PRIMARY KEY,
    prefix VARCHAR(50) UNIQUE NOT NULL,
    next_value INT NOT NULL DEFAULT 1,
    digits INT NOT NULL DEFAULT 6,
    INDEX(prefix)
);

-- 2. Standardize transactional decimal columns to (14,2)
ALTER TABLE payments 
    MODIFY COLUMN amount DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN penalty DECIMAL(14,2) DEFAULT 0.00,
    MODIFY COLUMN discount DECIMAL(14,2) DEFAULT 0.00;

ALTER TABLE property_billings 
    MODIFY COLUMN assessed_value DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN penalty DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN discount DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN amount_paid DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN tax_year SMALLINT NOT NULL;

ALTER TABLE payment_billings 
    MODIFY COLUMN amount_paid DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN tax_year SMALLINT NOT NULL;

ALTER TABLE receipt_history 
    MODIFY COLUMN amount DECIMAL(14,2) NOT NULL DEFAULT 0.00;
