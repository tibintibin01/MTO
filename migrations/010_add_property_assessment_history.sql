-- Migration: Add Property Assessment History
-- Version: 010

CREATE TABLE IF NOT EXISTS property_assessment_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    td_number VARCHAR(100),
    assessed_value DECIMAL(14, 2),
    tax_year VARCHAR(100),
    kind_of_property VARCHAR(100),
    changed_by VARCHAR(255),
    change_reason VARCHAR(255) DEFAULT 'Import Update',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_assessment_history_property
        FOREIGN KEY (property_id) REFERENCES properties(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Index for fast lookup in Dossier
CREATE INDEX idx_assessment_history_property_id ON property_assessment_history(property_id);
