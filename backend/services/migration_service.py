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
                statements = [s.strip() for s in m["sql"].split(";") if s.strip()]
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
