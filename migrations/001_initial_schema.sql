-- Baseline Migration: Initial Schema
-- Version: 001

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL DEFAULT '',
    username VARCHAR(150) NOT NULL UNIQUE,
    password VARCHAR(512) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    is_deleted TINYINT(1) NOT NULL DEFAULT 0,
    last_login DATETIME NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS properties (
    id INT AUTO_INCREMENT PRIMARY KEY,
    td_number VARCHAR(100) NOT NULL,
    owner_name VARCHAR(255) NOT NULL,
    payor_name VARCHAR(255) NULL,
    lot_number VARCHAR(100) NULL,
    area VARCHAR(100) NULL,
    location VARCHAR(255) NULL,
    kind_of_property VARCHAR(100) NULL,
    accountable_officer VARCHAR(255) NULL,
    assessed_value DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    penalty DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    or_number VARCHAR(100) NULL,
    or_date DATE NULL,
    tax_year VARCHAR(100) NULL,
    is_deleted TINYINT(1) NOT NULL DEFAULT 0,
    archived TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_properties_is_deleted (is_deleted),
    INDEX idx_properties_td_number (td_number),
    INDEX idx_properties_is_deleted_td_number (is_deleted, td_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    amount DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    or_number VARCHAR(255) NULL,
    date_paid DATE NULL,
    tax_year VARCHAR(20) NULL,
    posted_by VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_payments_property_id (property_id),
    CONSTRAINT fk_payments_property
        FOREIGN KEY (property_id) REFERENCES properties(id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS property_billings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    tax_year VARCHAR(20) NOT NULL,
    assessed_value DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    basic_amount DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    sef_amount DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    penalty DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    total_due DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    amount_paid DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    has_payment TINYINT(1) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_property_billings_property_year (property_id, tax_year),
    INDEX idx_property_billings_property_id (property_id),
    CONSTRAINT fk_property_billings_property
        FOREIGN KEY (property_id) REFERENCES properties(id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payment_billings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    payment_id INT NOT NULL,
    billing_id INT NULL,
    tax_year VARCHAR(20) NOT NULL,
    assessed_value DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    basic_amount DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    sef_amount DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    penalty DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    total_paid DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_payment_billings_payment_id (payment_id),
    CONSTRAINT fk_payment_billings_payment
        FOREIGN KEY (payment_id) REFERENCES payments(id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS property_edit_locks (
    property_id INT NOT NULL PRIMARY KEY,
    locked_by VARCHAR(255) NOT NULL,
    locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_edit_locks_property
        FOREIGN KEY (property_id) REFERENCES properties(id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_edit_locks (
    user_id INT PRIMARY KEY,
    locked_by VARCHAR(255) NOT NULL,
    locked_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    username VARCHAR(255) NOT NULL,
    action TEXT NOT NULL,
    table_name VARCHAR(100) NULL,
    record_id INT NULL,
    old_values LONGTEXT NULL,
    new_values LONGTEXT NULL,
    ip_address VARCHAR(45) NULL,
    timestamp DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_audit_logs_timestamp (timestamp),
    INDEX idx_audit_logs_username (username(100)),
    INDEX idx_audit_logs_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS receipt_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    payment_id INT NULL,
    td_number VARCHAR(255),
    owner_name VARCHAR(255),
    or_number VARCHAR(255),
    tax_year VARCHAR(20),
    amount DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    file_path TEXT NOT NULL,
    generated_by VARCHAR(255),
    generated_at DATETIME NOT NULL,
    status VARCHAR(50) DEFAULT 'PDF READY',
    INDEX idx_receipt_history_property_id (property_id),
    INDEX idx_receipt_history_or_number (or_number),
    INDEX idx_receipt_history_generated_at (generated_at),
    CONSTRAINT fk_receipt_history_property
        FOREIGN KEY (property_id) REFERENCES properties(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS delinquency_communications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    communication_type VARCHAR(100) NOT NULL,
    sent_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Sent',
    notes TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_delinq_comm_property
        FOREIGN KEY (property_id) REFERENCES properties(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
