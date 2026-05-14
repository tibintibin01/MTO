-- Phase 1: Performance & Aggregation
CREATE TABLE IF NOT EXISTS system_stats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stat_key VARCHAR(100) UNIQUE NOT NULL,
    stat_value DECIMAL(18, 2) DEFAULT 0.00,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    metadata_json TEXT,
    INDEX idx_stat_key (stat_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Phase 2: Security & Tamper-Evidence
ALTER TABLE audit_logs 
ADD COLUMN IF NOT EXISTS current_hash VARCHAR(255),
ADD COLUMN IF NOT EXISTS previous_hash VARCHAR(255);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token VARCHAR(512) UNIQUE NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_revoked BOOLEAN DEFAULT FALSE,
    INDEX idx_refresh_token (token),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS backup_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    checksum VARCHAR(64),
    status VARCHAR(50) DEFAULT 'PENDING',
    health VARCHAR(100) DEFAULT 'UNKNOWN',
    user_name VARCHAR(255),
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_backup_timestamp (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

