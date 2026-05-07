from datetime import datetime
from db_manager import (
    db_query, DB_CONFIG, _show_warning, hash_password, is_password_hashed,
    MAINTENANCE_DB_CONFIG, _run_with_db_config
)

def _table_exists(table_name):
    result = db_query("SHOW TABLES LIKE %s", (table_name,), fetch=True, commit=False)
    return bool(result)


def _column_exists(table_name, column_name):
    result = db_query(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (DB_CONFIG["database"], table_name, column_name),
        fetch=True,
        commit=False,
    )
    return bool(result and result[0][0])


def _foreign_key_exists(table_name, constraint_name):
    result = db_query(
        """
        SELECT COUNT(*)
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = %s AND TABLE_NAME = %s
          AND CONSTRAINT_NAME = %s AND CONSTRAINT_TYPE = 'FOREIGN KEY'
        """,
        (DB_CONFIG["database"], table_name, constraint_name),
        fetch=True,
        commit=False,
    )
    return bool(result and result[0][0])


def _index_exists(table_name, index_name):
    result = db_query(
        """
        SELECT COUNT(*)
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = %s
        """,
        (DB_CONFIG["database"], table_name, index_name),
        fetch=True,
        commit=False,
    )
    return bool(result and result[0][0])


def ensure_payments_schema():
    if not _table_exists("payments"):
        db_query(
            """
            CREATE TABLE payments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                property_id INT NOT NULL,
                amount DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
                or_number VARCHAR(255),
                date_paid DATE,
                tax_year VARCHAR(20),
                posted_by VARCHAR(255),
                payor_name VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_payments_property_id (property_id),
                CONSTRAINT fk_payments_property
                    FOREIGN KEY (property_id) REFERENCES properties(id)
                    ON UPDATE CASCADE ON DELETE CASCADE
            )
            """
        )
        return

    if not _column_exists("payments", "property_id"):
        db_query("ALTER TABLE payments ADD COLUMN property_id INT NULL AFTER id")

def ensure_properties_indexes():
    if not _table_exists("properties"):
        return
    if not _index_exists("properties", "idx_properties_is_deleted"):
        db_query("ALTER TABLE properties ADD INDEX idx_properties_is_deleted (is_deleted)")
    if not _index_exists("properties", "idx_properties_td_number"):
        db_query("ALTER TABLE properties ADD INDEX idx_properties_td_number (td_number)")

def ensure_properties_schema():
    if not _table_exists("properties"):
        return
    if not _column_exists("properties", "payor_name"):
        db_query("ALTER TABLE properties ADD COLUMN payor_name VARCHAR(255) NULL AFTER owner_name")
    if not _column_exists("properties", "kind_of_property"):
        db_query("ALTER TABLE properties ADD COLUMN kind_of_property VARCHAR(100) NULL AFTER location")

def ensure_property_billings_schema():
    if not _table_exists("property_billings"):
        db_query(
            """
            CREATE TABLE property_billings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                property_id INT NOT NULL,
                tax_year VARCHAR(20) NOT NULL,
                assessed_value DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
                penalty DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
                amount_paid DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                due_date DATE NULL,
                last_penalty_applied_at TIMESTAMP NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_property_billings_property_year (property_id, tax_year),
                INDEX idx_property_billings_tax_year (tax_year),
                CONSTRAINT fk_property_billings_property
                    FOREIGN KEY (property_id) REFERENCES properties(id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            )
            """
        )

def ensure_payment_billings_schema():
    if not _table_exists("payment_billings"):
        db_query(
            """
            CREATE TABLE payment_billings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                payment_id INT NOT NULL,
                billing_id INT NOT NULL,
                tax_year VARCHAR(20) NOT NULL,
                amount_paid DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_payment_billings_payment_billing (payment_id, billing_id),
                INDEX idx_payment_billings_payment_id (payment_id),
                INDEX idx_payment_billings_billing_id (billing_id),
                CONSTRAINT fk_payment_billings_payment
                    FOREIGN KEY (payment_id) REFERENCES payments(id)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                CONSTRAINT fk_payment_billings_billing
                    FOREIGN KEY (billing_id) REFERENCES property_billings(id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            )
            """
        )

def ensure_edit_locks_schema():
    if not _table_exists("property_edit_locks"):
        db_query("CREATE TABLE property_edit_locks (property_id INT PRIMARY KEY, locked_by VARCHAR(255) NOT NULL, locked_at DATETIME NOT NULL)")

def ensure_user_edit_locks_schema():
    if not _table_exists("user_edit_locks"):
        db_query("CREATE TABLE user_edit_locks (user_id INT PRIMARY KEY, locked_by VARCHAR(255) NOT NULL, locked_at DATETIME NOT NULL)")

def ensure_payment_post_locks_schema():
    if not _table_exists("payment_post_locks"):
        db_query("CREATE TABLE payment_post_locks (property_id INT PRIMARY KEY, locked_by VARCHAR(255) NOT NULL, locked_at DATETIME NOT NULL)")

def ensure_audit_logs_schema():
    if not _table_exists("audit_logs"):
        db_query(
            """
            CREATE TABLE audit_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                username VARCHAR(255) NOT NULL,
                action VARCHAR(255) NOT NULL,
                table_name VARCHAR(100) NULL,
                record_id INT NULL,
                old_values LONGTEXT NULL,
                new_values LONGTEXT NULL,
                ip_address VARCHAR(45) NULL,
                timestamp DATETIME NOT NULL,
                INDEX idx_audit_logs_timestamp (timestamp),
                INDEX idx_audit_logs_username (username(100)),
                INDEX idx_audit_logs_user_id (user_id)
            )
            """
        )
    else:
        if not _column_exists("audit_logs", "user_id"):
            db_query("ALTER TABLE audit_logs ADD COLUMN user_id INT NULL AFTER id")
        if not _column_exists("audit_logs", "table_name"):
            db_query("ALTER TABLE audit_logs ADD COLUMN table_name VARCHAR(100) NULL AFTER action")
        if not _column_exists("audit_logs", "record_id"):
            db_query("ALTER TABLE audit_logs ADD COLUMN record_id INT NULL AFTER table_name")
        if not _column_exists("audit_logs", "old_values"):
            db_query("ALTER TABLE audit_logs ADD COLUMN old_values LONGTEXT NULL AFTER record_id")
        if not _column_exists("audit_logs", "new_values"):
            db_query("ALTER TABLE audit_logs ADD COLUMN new_values LONGTEXT NULL AFTER old_values")
        if not _column_exists("audit_logs", "ip_address"):
            db_query("ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR(45) NULL AFTER new_values")

def ensure_users_password_hashes():
    if not _table_exists("users"): return
    rows = db_query("SELECT id, password FROM users", fetch=True, commit=False)
    for user_id, stored_password in rows:
        if stored_password and not is_password_hashed(stored_password):
            db_query("UPDATE users SET password=%s WHERE id=%s", (hash_password(stored_password), user_id))

def ensure_delinquency_communications_schema():
    if not _table_exists("delinquency_communications"):
        db_query(
            """
            CREATE TABLE delinquency_communications (
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
            )
            """
        )

def ensure_receipt_history_schema():
    if not _table_exists("receipt_history"):
        db_query(
            """
            CREATE TABLE receipt_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                property_id INT NOT NULL,
                payment_id INT NULL,
                td_number VARCHAR(255),
                owner_name VARCHAR(255),
                payor_name VARCHAR(255),
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
            )
            """
        )
    else:
        if not _column_exists("receipt_history", "status"):
            db_query("ALTER TABLE receipt_history ADD COLUMN status VARCHAR(50) DEFAULT 'PDF READY' AFTER generated_at")

def run_startup_maintenance():
    from migration_manager import run_migrations
    print("Executing Migration Manager...")
    run_migrations()

if __name__ == "__main__":
    run_startup_maintenance()
