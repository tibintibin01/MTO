ALTER TABLE properties 
ADD COLUMN pin VARCHAR(100) DEFAULT NULL,
ADD COLUMN lot_number VARCHAR(100) DEFAULT NULL,
ADD COLUMN block_number VARCHAR(100) DEFAULT NULL,
ADD COLUMN prev_td_number VARCHAR(100) DEFAULT NULL,
ADD COLUMN effectivity_date DATE DEFAULT NULL,
ADD COLUMN barangay VARCHAR(100) DEFAULT NULL;

-- Indexing for the 25 Barangays to make reports fast
CREATE INDEX idx_barangay ON properties(barangay);
CREATE INDEX idx_pin ON properties(pin);
