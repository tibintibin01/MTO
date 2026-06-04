from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.database import SessionLocal

# --- MIGRATION REGISTRY ---
# Add your new SQL changes here! 
# Each migration must have a unique ID (e.g., '2026_05_13_add_middle_name')
MIGRATIONS = [
    {
        "id": "init_migration_system",
        "sql": "CREATE TABLE IF NOT EXISTS system_migrations (id VARCHAR(255) PRIMARY KEY, applied_at DATETIME)"
    },
    {
        "id": "expand_backup_health_varchar",
        "sql": "ALTER TABLE backup_history MODIFY health VARCHAR(255)"
    },
    {
        "id": "sanitize_truncated_backup_status",
        "sql": "UPDATE backup_history SET health='SUCCESS' WHERE health='Suc' OR health='Issue: Suc'"
    },
    {
        "id": "add_archived_and_modern_columns_to_properties",
        "sql": "ALTER TABLE properties ADD COLUMN IF NOT EXISTS payor_name VARCHAR(255), ADD COLUMN IF NOT EXISTS lot_number VARCHAR(50), ADD COLUMN IF NOT EXISTS block_number VARCHAR(50), ADD COLUMN IF NOT EXISTS barangay VARCHAR(100), ADD COLUMN IF NOT EXISTS accountable_officer VARCHAR(255), ADD COLUMN IF NOT EXISTS prev_td_number VARCHAR(50), ADD COLUMN IF NOT EXISTS effectivity_date DATE, ADD COLUMN IF NOT EXISTS version INT DEFAULT 1, ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE, ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE"
    },
    {
        "id": "ensure_billing_infrastructure_and_discount_column_v2",
        "sql": "CREATE TABLE IF NOT EXISTS property_billings (id INT AUTO_INCREMENT PRIMARY KEY, property_id INT NOT NULL, tax_year VARCHAR(20) NOT NULL, assessed_value DECIMAL(14,2) DEFAULT 0, basic_amount DECIMAL(14,2) DEFAULT 0, sef_amount DECIMAL(14,2) DEFAULT 0, penalty DECIMAL(14,2) DEFAULT 0, total_due DECIMAL(14,2) DEFAULT 0, amount_paid DECIMAL(14,2) DEFAULT 0, has_payment BOOLEAN DEFAULT FALSE, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP); ALTER TABLE property_billings ADD COLUMN IF NOT EXISTS discount DECIMAL(14,2) DEFAULT 0; CREATE TABLE IF NOT EXISTS payment_billings (id INT AUTO_INCREMENT PRIMARY KEY, payment_id INT NOT NULL, billing_id INT, tax_year VARCHAR(20) NOT NULL, assessed_value DECIMAL(14,2) DEFAULT 0, basic_amount DECIMAL(14,2) DEFAULT 0, sef_amount DECIMAL(14,2) DEFAULT 0, penalty DECIMAL(14,2) DEFAULT 0, total_paid DECIMAL(14,2) DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
    },
    {
        "id": "ensure_audit_and_history_tables_v2",
        "sql": "CREATE TABLE IF NOT EXISTS audit_logs (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT, username VARCHAR(255) NOT NULL, action TEXT NOT NULL, table_name VARCHAR(100), record_id INT, old_values TEXT, new_values TEXT, ip_address VARCHAR(45), timestamp DATETIME NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS property_assessment_history (id INT AUTO_INCREMENT PRIMARY KEY, property_id INT NOT NULL, td_number VARCHAR(100), assessed_value DECIMAL(14,2), tax_year VARCHAR(100), kind_of_property VARCHAR(100), changed_by VARCHAR(255), change_reason VARCHAR(255) DEFAULT 'Import Update', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS receipt_history (id INT AUTO_INCREMENT PRIMARY KEY, property_id INT NOT NULL, payment_id INT, td_number VARCHAR(255), owner_name VARCHAR(255), or_number VARCHAR(255), tax_year VARCHAR(20), amount DECIMAL(12,2) DEFAULT 0, file_path TEXT NOT NULL, generated_by VARCHAR(255), generated_at DATETIME NOT NULL, status VARCHAR(50) DEFAULT 'PDF READY');"
    },
    {
        "id": "add_refresh_tokens_table",
        "sql": "CREATE TABLE IF NOT EXISTS refresh_tokens (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, token VARCHAR(512) UNIQUE NOT NULL, expires_at DATETIME NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_revoked BOOLEAN DEFAULT FALSE, INDEX(user_id), INDEX(token))"
    },
    {
        "id": "week2_data_integrity_and_reliability",
        "sql": (
            # or_sequences table — idempotent
            "CREATE TABLE IF NOT EXISTS or_sequences ("
            "  id INT AUTO_INCREMENT PRIMARY KEY,"
            "  prefix VARCHAR(50) UNIQUE NOT NULL,"
            "  next_value INT NOT NULL DEFAULT 1,"
            "  digits INT NOT NULL DEFAULT 6,"
            "  INDEX(prefix)"
            ");"

            # payments — DECIMAL(14,2) precision upgrade
            # IF EXISTS guards make each statement safe to re-run if a prior
            # run failed partway through (MariaDB DDL is auto-committed, so a
            # partial migration cannot be rolled back — idempotency is the only
            # safe option).
            "ALTER TABLE payments"
            "  MODIFY COLUMN IF EXISTS amount   DECIMAL(14,2) NOT NULL DEFAULT 0.00,"
            "  MODIFY COLUMN IF EXISTS penalty  DECIMAL(14,2)          DEFAULT 0.00,"
            "  MODIFY COLUMN IF EXISTS discount DECIMAL(14,2)          DEFAULT 0.00;"

            # property_billings — DECIMAL(14,2) + tax_year → SMALLINT
            "ALTER TABLE property_billings"
            "  MODIFY COLUMN IF EXISTS assessed_value DECIMAL(14,2) NOT NULL DEFAULT 0.00,"
            "  MODIFY COLUMN IF EXISTS penalty        DECIMAL(14,2) NOT NULL DEFAULT 0.00,"
            "  MODIFY COLUMN IF EXISTS discount       DECIMAL(14,2) NOT NULL DEFAULT 0.00,"
            "  MODIFY COLUMN IF EXISTS amount_paid    DECIMAL(14,2) NOT NULL DEFAULT 0.00,"
            "  MODIFY COLUMN IF EXISTS tax_year       SMALLINT      NOT NULL;"

            # payment_billings — DECIMAL(14,2) + tax_year → SMALLINT
            "ALTER TABLE payment_billings"
            "  MODIFY COLUMN IF EXISTS amount_paid DECIMAL(14,2) NOT NULL DEFAULT 0.00,"
            "  MODIFY COLUMN IF EXISTS tax_year    SMALLINT      NOT NULL;"

            # receipt_history — DECIMAL(14,2) precision upgrade
            "ALTER TABLE receipt_history"
            "  MODIFY COLUMN IF EXISTS amount DECIMAL(14,2) NOT NULL DEFAULT 0.00;"
        )
    },
    {
        "id": "week4_data_retention_policy",
        "sql": (
            # retention_policies table
            "CREATE TABLE IF NOT EXISTS retention_policies ("
            "  id INT AUTO_INCREMENT PRIMARY KEY,"
            "  data_type VARCHAR(100) UNIQUE NOT NULL,"
            "  description VARCHAR(500) NOT NULL,"
            "  retention_years INT NOT NULL,"
            "  action VARCHAR(20) NOT NULL DEFAULT 'ARCHIVE',"
            "  legal_basis VARCHAR(255),"
            "  is_active BOOLEAN NOT NULL DEFAULT TRUE,"
            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "  INDEX(data_type)"
            ");"

            # retention_logs table — immutable audit trail
            "CREATE TABLE IF NOT EXISTS retention_logs ("
            "  id INT AUTO_INCREMENT PRIMARY KEY,"
            "  policy_id INT NOT NULL,"
            "  data_type VARCHAR(100) NOT NULL,"
            "  action VARCHAR(20) NOT NULL,"
            "  records_affected INT NOT NULL DEFAULT 0,"
            "  cutoff_date DATETIME NOT NULL,"
            "  executed_by VARCHAR(150) NOT NULL,"
            "  notes TEXT,"
            "  executed_at DATETIME NOT NULL,"
            "  INDEX(policy_id),"
            "  INDEX(data_type),"
            "  INDEX(executed_at),"
            "  FOREIGN KEY (policy_id) REFERENCES retention_policies(id) ON DELETE RESTRICT"
            ");"

            # Seed default policies (INSERT IGNORE = safe to re-run)
            "INSERT IGNORE INTO retention_policies "
            "  (data_type, description, retention_years, action, legal_basis) VALUES "
            "  ('payments', 'Official Receipt payment records. COA requires 10-year minimum retention.', 10, 'ARCHIVE', 'COA Circular 2009-006; RA 10173 Sec. 11'),"
            "  ('property_billings', 'Annual tax billing records per property. COA requires 10-year minimum retention.', 10, 'ARCHIVE', 'COA Circular 2009-006; RA 10173 Sec. 11'),"
            "  ('receipt_history', 'Generated PDF receipt audit trail. Retained alongside payment records.', 10, 'ARCHIVE', 'COA Circular 2009-006'),"
            "  ('audit_logs', 'System audit trail. Immutable by design; archived after 10 years for DB performance.', 10, 'ARCHIVE', 'COA Circular 2009-006; DICT MC 2022-002'),"
            "  ('deleted_users', 'Soft-deleted staff accounts. Purged after 5 years per NPC guidelines.', 5, 'PURGE', 'RA 10173 Sec. 11(e)'),"
            "  ('expired_tokens', 'Expired and revoked refresh tokens. Purged after 30 days for DB hygiene.', 0, 'PURGE', 'RA 10173 Sec. 11(e)');"
        )
    },
    {
        "id": "session_invalidation_on_password_change",
        "sql": (
            # Add password_changed_at to users table.
            # NULL means the password has never been explicitly reset — tokens
            # issued before this feature was deployed are not affected.
            "ALTER TABLE users "
            "  ADD COLUMN IF NOT EXISTS password_changed_at DATETIME NULL DEFAULT NULL;"
        )
    },
    {
        "id": "week3_architecture_optimizations",        "sql": (
            # tax_policies table
            "CREATE TABLE IF NOT EXISTS tax_policies ("
            "  id INT AUTO_INCREMENT PRIMARY KEY,"
            "  tax_year SMALLINT UNIQUE NOT NULL,"
            "  basic_rate DECIMAL(6, 4) NOT NULL DEFAULT 0.0100,"
            "  sef_rate DECIMAL(6, 4) NOT NULL DEFAULT 0.0100,"
            "  penalty_rate DECIMAL(6, 4) NOT NULL DEFAULT 0.0200,"
            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "  INDEX(tax_year)"
            ");"

            # seed default values
            "INSERT IGNORE INTO tax_policies (tax_year, basic_rate, sef_rate, penalty_rate) VALUES "
            "(2020, 0.0100, 0.0100, 0.0200), (2021, 0.0100, 0.0100, 0.0200), (2022, 0.0100, 0.0100, 0.0200), "
            "(2023, 0.0100, 0.0100, 0.0200), (2024, 0.0100, 0.0100, 0.0200), (2025, 0.0100, 0.0100, 0.0200), "
            "(2026, 0.0100, 0.0100, 0.0200), (2027, 0.0100, 0.0100, 0.0200), (2028, 0.0100, 0.0100, 0.0200), "
            "(2029, 0.0100, 0.0100, 0.0200), (2030, 0.0100, 0.0100, 0.0200);"

            # expand jobs.payload to MEDIUMTEXT for large import payloads
            "ALTER TABLE jobs MODIFY COLUMN IF EXISTS payload MEDIUMTEXT;"
        )
    },
    {
        "id": "add_composite_unique_constraint_on_property_billings",
        "sql": (
            # Enforce database-level data integrity preventing duplicate billing records per property and tax year
            "ALTER TABLE property_billings ADD UNIQUE KEY IF NOT EXISTS uq_property_billings_property_tax_year (property_id, tax_year);"
        )
    },
    {
        "id": "create_bank_deposits_table",
        "sql": (
            "CREATE TABLE IF NOT EXISTS bank_deposits ("
            "  id INT AUTO_INCREMENT PRIMARY KEY,"
            "  date_deposited DATETIME NOT NULL,"
            "  bank_name VARCHAR(255) NOT NULL,"
            "  reference_number VARCHAR(255) NOT NULL,"
            "  amount DECIMAL(14,2) NOT NULL DEFAULT 0.00,"
            "  deposited_by VARCHAR(150) NOT NULL,"
            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "  INDEX(date_deposited)"
            ");"
        )
    },
    {
        "id": "create_rate_limit_blocks_table",
        "sql": (
            "CREATE TABLE IF NOT EXISTS rate_limit_blocks ("
            "  id INT AUTO_INCREMENT PRIMARY KEY,"
            "  timestamp DATETIME NOT NULL,"
            "  ip_address VARCHAR(45) NOT NULL,"
            "  username VARCHAR(150),"
            "  endpoint VARCHAR(255) NOT NULL,"
            "  limit_rule VARCHAR(255) NOT NULL,"
            "  retry_after INT NOT NULL,"
            "  INDEX(timestamp),"
            "  INDEX(ip_address),"
            "  INDEX(username)"
            ");"
        )
    }

]


def run_migrations(db_session: Session = None):
    """Checks and applies all pending database migrations."""
    print("--- DATABASE MIGRATION ENGINE ---")
    
    # 1. Ensure the migration tracking table exists
    try:
        db_session.execute(text(MIGRATIONS[0]["sql"]))
        db_session.commit()
    except Exception as e:
        print(f"ERROR: Could not initialize migration system: {e}")
        db_session.rollback()
        return

    # 2. Get list of already applied migrations
    applied_ids = []
    try:
        results = db_session.execute(text("SELECT id FROM system_migrations")).all()
        applied_ids = [row[0] for row in results]
    except Exception as e:
        print(f"ERROR: Could not fetch migration history: {e}")

    # 3. Apply pending migrations
    new_count = 0
    for m in MIGRATIONS:
        m_id = m["id"]
        if m_id not in applied_ids:
            print(f"Applying Migration: [{m_id}]...")
            try:
                # Support multi-statement migrations by splitting by semicolon
                # Support multi-statement migrations by splitting by semicolon (ignoring semicolons inside single quotes)
                statements = []
                current = []
                in_quote = False
                for char in m["sql"]:
                    if char == "'":
                        in_quote = not in_quote
                        current.append(char)
                    elif char == ";" and not in_quote:
                        statements.append("".join(current).strip())
                        current = []
                    else:
                        current.append(char)
                if current:
                    stmt = "".join(current).strip()
                    if stmt:
                        statements.append(stmt)
                for statement in statements:
                    db_session.execute(text(statement))
                
                # Record that it was successful
                db_session.execute(
                    text("INSERT INTO system_migrations (id, applied_at) VALUES (:id, :now)"),
                    {"id": m_id, "now": datetime.now()}
                )
                db_session.commit()
                new_count += 1
                print(f"SUCCESS: [{m_id}] applied.")
            except Exception as e:
                db_session.rollback()
                print(f"FAILED: [{m_id}] error: {e}")
                # We stop here to prevent database inconsistency
                break
    
    if new_count > 0:
        print(f"Migration Complete: {new_count} new updates applied.")
    else:
        print("Database is up to date. No migrations needed.")
    print("---------------------------------")
