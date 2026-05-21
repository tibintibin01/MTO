-- Week 3 Architecture & Optimization Updates
-- 1. Create Tax Policies Table
CREATE TABLE IF NOT EXISTS tax_policies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tax_year SMALLINT UNIQUE NOT NULL,
    basic_rate DECIMAL(6, 4) NOT NULL DEFAULT 0.0100,
    sef_rate DECIMAL(6, 4) NOT NULL DEFAULT 0.0100,
    penalty_rate DECIMAL(6, 4) NOT NULL DEFAULT 0.0200,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX(tax_year)
);

-- Seed default policies for 2020 through 2030 to prevent empty state latency
INSERT IGNORE INTO tax_policies (tax_year, basic_rate, sef_rate, penalty_rate) VALUES
(2020, 0.0100, 0.0100, 0.0200),
(2021, 0.0100, 0.0100, 0.0200),
(2022, 0.0100, 0.0100, 0.0200),
(2023, 0.0100, 0.0100, 0.0200),
(2024, 0.0100, 0.0100, 0.0200),
(2025, 0.0100, 0.0100, 0.0200),
(2026, 0.0100, 0.0100, 0.0200),
(2027, 0.0100, 0.0100, 0.0200),
(2028, 0.0100, 0.0100, 0.0200),
(2029, 0.0100, 0.0100, 0.0200),
(2030, 0.0100, 0.0100, 0.0200);

-- 2. Modify Job payload column to MEDIUMTEXT
ALTER TABLE jobs MODIFY COLUMN payload MEDIUMTEXT;
