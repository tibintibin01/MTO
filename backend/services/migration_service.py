from datetime import datetime
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

# --- MIGRATION REGISTRY ---
# Add your new SQL changes here!
# Each migration must have a unique ID (e.g., '2026_05_13_add_middle_name')
MIGRATIONS = [
    {
        "id": "init_migration_system",
        "sql": "CREATE TABLE IF NOT EXISTS system_migrations (id VARCHAR(255) PRIMARY KEY, applied_at DATETIME)",
    },
    {
        "id": "expand_backup_health_varchar",
        "sql": "ALTER TABLE backup_history MODIFY health VARCHAR(255)",
    },
    {
        "id": "sanitize_truncated_backup_status",
        "sql": "UPDATE backup_history SET health='SUCCESS' WHERE health='Suc' OR health='Issue: Suc'",
    },
    {
        "id": "add_archived_and_modern_columns_to_properties",
        "sql": "ALTER TABLE properties ADD COLUMN IF NOT EXISTS payor_name VARCHAR(255), ADD COLUMN IF NOT EXISTS lot_number VARCHAR(50), ADD COLUMN IF NOT EXISTS block_number VARCHAR(50), ADD COLUMN IF NOT EXISTS barangay VARCHAR(100), ADD COLUMN IF NOT EXISTS accountable_officer VARCHAR(255), ADD COLUMN IF NOT EXISTS prev_td_number VARCHAR(50), ADD COLUMN IF NOT EXISTS effectivity_date DATE, ADD COLUMN IF NOT EXISTS version INT DEFAULT 1, ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE, ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE",
    },
    {
        "id": "ensure_billing_infrastructure_and_discount_column_v2",
        "sql": "CREATE TABLE IF NOT EXISTS property_billings (id INT AUTO_INCREMENT PRIMARY KEY, property_id INT NOT NULL, tax_year VARCHAR(20) NOT NULL, assessed_value DECIMAL(14,2) DEFAULT 0, basic_amount DECIMAL(14,2) DEFAULT 0, sef_amount DECIMAL(14,2) DEFAULT 0, penalty DECIMAL(14,2) DEFAULT 0, total_due DECIMAL(14,2) DEFAULT 0, amount_paid DECIMAL(14,2) DEFAULT 0, has_payment BOOLEAN DEFAULT FALSE, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP); ALTER TABLE property_billings ADD COLUMN IF NOT EXISTS discount DECIMAL(14,2) DEFAULT 0; CREATE TABLE IF NOT EXISTS payment_billings (id INT AUTO_INCREMENT PRIMARY KEY, payment_id INT NOT NULL, billing_id INT, tax_year VARCHAR(20) NOT NULL, assessed_value DECIMAL(14,2) DEFAULT 0, basic_amount DECIMAL(14,2) DEFAULT 0, sef_amount DECIMAL(14,2) DEFAULT 0, penalty DECIMAL(14,2) DEFAULT 0, total_paid DECIMAL(14,2) DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);",
    },
    {
        "id": "ensure_audit_and_history_tables_v2",
        "sql": "CREATE TABLE IF NOT EXISTS audit_logs (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT, username VARCHAR(255) NOT NULL, action TEXT NOT NULL, table_name VARCHAR(100), record_id INT, old_values TEXT, new_values TEXT, ip_address VARCHAR(45), timestamp DATETIME NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS property_assessment_history (id INT AUTO_INCREMENT PRIMARY KEY, property_id INT NOT NULL, td_number VARCHAR(100), assessed_value DECIMAL(14,2), tax_year VARCHAR(100), kind_of_property VARCHAR(100), changed_by VARCHAR(255), change_reason VARCHAR(255) DEFAULT 'Import Update', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS receipt_history (id INT AUTO_INCREMENT PRIMARY KEY, property_id INT NOT NULL, payment_id INT, td_number VARCHAR(255), owner_name VARCHAR(255), or_number VARCHAR(255), tax_year VARCHAR(20), amount DECIMAL(12,2) DEFAULT 0, file_path TEXT NOT NULL, generated_by VARCHAR(255), generated_at DATETIME NOT NULL, status VARCHAR(50) DEFAULT 'PDF READY');",
    },
    {
        "id": "add_refresh_tokens_table",
        "sql": "CREATE TABLE IF NOT EXISTS refresh_tokens (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, token VARCHAR(512) UNIQUE NOT NULL, expires_at DATETIME NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_revoked BOOLEAN DEFAULT FALSE, INDEX(user_id), INDEX(token))",
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
        ),
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
        ),
    },
    {
        "id": "session_invalidation_on_password_change",
        "sql": (
            # Add password_changed_at to users table.
            # NULL means the password has never been explicitly reset — tokens
            # issued before this feature was deployed are not affected.
            "ALTER TABLE users "
            "  ADD COLUMN IF NOT EXISTS password_changed_at DATETIME NULL DEFAULT NULL;"
        ),
    },
    {
        "id": "week3_architecture_optimizations",
        "sql": (
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
        ),
    },
    {
        "id": "add_composite_unique_constraint_on_property_billings",
        "sql": (
            # Enforce database-level data integrity preventing duplicate billing records per property and tax year
            "ALTER TABLE property_billings ADD UNIQUE KEY IF NOT EXISTS uq_property_billings_property_tax_year (property_id, tax_year);"
        ),
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
        ),
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
        ),
    },
    {
        "id": "add_job_queue_composite_indexes",
        "sql": (
            "CREATE INDEX IF NOT EXISTS ix_jobs_status_type_created "
            "ON jobs (status, job_type, created_at);"
            "CREATE INDEX IF NOT EXISTS ix_jobs_status_started "
            "ON jobs (status, started_at);"
        ),
    },
    {
        "id": "add_payment_remarks_column",
        "sql": "ALTER TABLE payments ADD COLUMN IF NOT EXISTS remarks VARCHAR(500) NULL;",
    },
    {
        "id": "verified_duplicate_td_accounts_v1",
        "handler": "ensure_verified_duplicate_td_schema",
        "sql": "",
    },
    {
        "id": "phase3_financial_transaction_safety_v1",
        "handler": "ensure_financial_safety_schema",
        "sql": "",
    },
    {
        "id": "phase5_audit_integrity_observability_v1",
        "handler": "ensure_audit_integrity_schema",
        "sql": "",
    },
    {
        "id": "phase5_audit_timestamp_precision_recovery_v1",
        "handler": "ensure_audit_timestamp_precision_recovery",
        "sql": "",
    },
]


REFRESH_TOKEN_SESSION_COLUMNS = {
    "client_ip": "VARCHAR(45) NULL",
    "user_agent": "VARCHAR(500) NULL",
    "device_name": "VARCHAR(128) NULL",
    "last_used_at": "DATETIME NULL",
    "revoked_at": "DATETIME NULL",
}


def get_missing_refresh_token_session_columns(db_session: Session) -> set[str]:
    """Return login-session columns missing from an existing deployment."""
    inspector = inspect(db_session.connection())
    if not inspector.has_table("refresh_tokens"):
        raise RuntimeError("Required refresh_tokens table is missing")

    existing = {column["name"] for column in inspector.get_columns("refresh_tokens")}
    return set(REFRESH_TOKEN_SESSION_COLUMNS) - existing


def ensure_refresh_token_session_columns(db_session: Session) -> None:
    """Idempotently upgrade legacy refresh_tokens tables used during login."""
    missing = get_missing_refresh_token_session_columns(db_session)
    if not missing:
        return

    try:
        for column_name, column_sql in REFRESH_TOKEN_SESSION_COLUMNS.items():
            if column_name in missing:
                db_session.execute(
                    text(
                        f"ALTER TABLE refresh_tokens ADD COLUMN "
                        f"{column_name} {column_sql}"
                    )
                )

        db_session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_refresh_tokens_user_active_expiry "
                "ON refresh_tokens (user_id, is_revoked, expires_at)"
            )
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    remaining = get_missing_refresh_token_session_columns(db_session)
    if remaining:
        raise RuntimeError(
            "Refresh-token schema repair did not create: "
            + ", ".join(sorted(remaining))
        )

    print("Schema repair applied: refresh_tokens session metadata columns created.")


def ensure_payment_remarks_column(db_session: Session) -> None:
    """Repair deployments where the migration was recorded but the real column is missing."""
    try:
        inspector = inspect(db_session.connection())
        column_names = {column["name"] for column in inspector.get_columns("payments")}
        if "remarks" in column_names:
            return

        db_session.execute(
            text("ALTER TABLE payments ADD COLUMN remarks VARCHAR(500) NULL")
        )
        db_session.commit()
        print("Schema repair applied: payments.remarks column created.")
    except Exception as e:
        db_session.rollback()
        raise RuntimeError("Could not ensure payments.remarks column") from e


def ensure_verified_duplicate_td_schema(db_session: Session) -> None:
    """Prepare MariaDB for controlled, audited duplicate TD accounts."""
    connection = db_session.connection()
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Verified duplicate TD migration requires MariaDB/MySQL.")

    column_sql = {
        "previous_property_id": "INT NULL",
        "duplicate_td_verified": "BOOLEAN NOT NULL DEFAULT FALSE",
        "duplicate_td_reason": "VARCHAR(500) NULL",
        "duplicate_td_reference": "VARCHAR(255) NULL",
        "duplicate_td_approved_by": "VARCHAR(150) NULL",
        "duplicate_td_approved_at": "DATETIME NULL",
    }
    inspector = inspect(connection)
    existing_columns = {
        column["name"] for column in inspector.get_columns("properties")
    }
    for name, definition in column_sql.items():
        if name not in existing_columns:
            db_session.execute(
                text(f"ALTER TABLE properties ADD COLUMN {name} {definition}")
            )

    # Link legacy Previous-TD text only when exactly one active predecessor
    # exists. Ambiguous values remain unlinked so billing cannot choose a row.
    db_session.execute(
        text(
            "UPDATE properties child "
            "JOIN ("
            "  SELECT UPPER(TRIM(td_number)) AS td_key, MIN(id) AS parent_id "
            "  FROM properties WHERE deleted_at IS NULL "
            "  GROUP BY UPPER(TRIM(td_number)) HAVING COUNT(*) = 1"
            ") parent ON parent.td_key = UPPER(TRIM(child.prev_td_number)) "
            "SET child.previous_property_id = parent.parent_id "
            "WHERE child.previous_property_id IS NULL "
            "  AND parent.parent_id <> child.id "
            "  AND child.prev_td_number IS NOT NULL "
            "  AND TRIM(child.prev_td_number) <> ''"
        )
    )

    # SQLAlchemy-generated unique index names differ across installations.
    # Introspect and remove only single-column TD uniqueness; retain all other
    # database constraints and immediately install a normal lookup index.
    inspector = inspect(connection)
    unique_names = set()
    for constraint in inspector.get_unique_constraints("properties"):
        if constraint.get("name") and constraint.get("column_names") == ["td_number"]:
            unique_names.add(constraint["name"])
    for index in inspector.get_indexes("properties"):
        if (
            index.get("name")
            and index.get("unique")
            and index.get("column_names") == ["td_number"]
        ):
            unique_names.add(index["name"])

    quote = connection.dialect.identifier_preparer.quote
    for index_name in sorted(unique_names):
        db_session.execute(
            text(f"ALTER TABLE properties DROP INDEX {quote(index_name)}")
        )

    inspector = inspect(connection)
    indexes = inspector.get_indexes("properties")
    if not any(
        index.get("column_names") == ["td_number"] and not index.get("unique")
        for index in indexes
    ):
        db_session.execute(
            text(
                "CREATE INDEX ix_properties_td_number_lookup "
                "ON properties (td_number)"
            )
        )
    if not any(
        index.get("column_names") == ["previous_property_id"] for index in indexes
    ):
        db_session.execute(
            text(
                "CREATE INDEX ix_properties_previous_property_id "
                "ON properties (previous_property_id)"
            )
        )


def financial_invariant_violations(db_session: Session) -> dict[str, int]:
    """Return corruption counts that must be zero before constraints are added."""
    checks = {
        "duplicate_payment_identity": (
            "SELECT COUNT(*) FROM ("
            " SELECT property_id, UPPER(TRIM(or_number)) AS or_key,"
            "        UPPER(TRIM(tax_year)) AS year_key, DATE(date_paid) AS paid_key"
            " FROM payments"
            " WHERE or_number IS NOT NULL AND tax_year IS NOT NULL"
            "   AND date_paid IS NOT NULL"
            " GROUP BY property_id, UPPER(TRIM(or_number)),"
            "          UPPER(TRIM(tax_year)), DATE(date_paid)"
            " HAVING COUNT(*) > 1"
            ") duplicate_receipts"
        ),
        "duplicate_payment_allocations": (
            "SELECT COUNT(*) FROM ("
            " SELECT payment_id, billing_id"
            " FROM payment_billings"
            " GROUP BY payment_id, billing_id"
            " HAVING COUNT(*) > 1"
            ") duplicate_allocations"
        ),
        "cross_property_allocations": (
            "SELECT COUNT(*)"
            " FROM payment_billings link"
            " JOIN payments payment ON payment.id = link.payment_id"
            " JOIN property_billings billing ON billing.id = link.billing_id"
            " WHERE payment.property_id <> billing.property_id"
        ),
        "unbalanced_payment_allocations": (
            "SELECT COUNT(*) FROM ("
            " SELECT payment.id"
            " FROM payments payment"
            " LEFT JOIN payment_billings link ON link.payment_id = payment.id"
            " GROUP BY payment.id, payment.amount"
            " HAVING ABS(payment.amount - COALESCE(SUM(link.amount_paid), 0)) > 0.005"
            ") unbalanced_payments"
        ),
    }
    return {
        name: int(db_session.execute(text(statement)).scalar() or 0)
        for name, statement in checks.items()
    }


def _has_named_index(inspector, table_name, index_name):
    names = {
        item.get("name")
        for item in inspector.get_indexes(table_name)
        if item.get("name")
    }
    names.update(
        item.get("name")
        for item in inspector.get_unique_constraints(table_name)
        if item.get("name")
    )
    return index_name in names


def ensure_financial_safety_schema(db_session: Session) -> None:
    """Fail closed on corrupt financial links, then install Phase 3 guards."""
    connection = db_session.connection()
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Phase 3 financial safety migration requires MariaDB/MySQL.")

    inspector = inspect(connection)
    required_tables = {"payments", "property_billings", "payment_billings"}
    missing_tables = sorted(
        table_name
        for table_name in required_tables
        if not inspector.has_table(table_name)
    )
    if missing_tables:
        raise RuntimeError(
            "Phase 3 financial tables are missing: " + ", ".join(missing_tables)
        )

    violations = financial_invariant_violations(db_session)
    nonzero = {name: count for name, count in violations.items() if count}
    if nonzero:
        details = ", ".join(
            f"{name}={count}" for name, count in sorted(nonzero.items())
        )
        raise RuntimeError(
            "Phase 3 preflight found financial invariant violations; "
            f"repair and verify them before activation: {details}"
        )

    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS idempotency_keys ("
            " id INT AUTO_INCREMENT PRIMARY KEY,"
            " `key` VARCHAR(200) NOT NULL,"
            " user_id VARCHAR(64) NULL,"
            " request_hash VARCHAR(64) NULL,"
            " method VARCHAR(10) NOT NULL,"
            " path VARCHAR(255) NOT NULL,"
            " state VARCHAR(20) NOT NULL DEFAULT 'COMPLETED',"
            " status_code INT NOT NULL DEFAULT 200,"
            " response_body TEXT NULL,"
            " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            " updated_at DATETIME NULL,"
            " expires_at DATETIME NOT NULL,"
            " UNIQUE KEY uq_idempotency_keys_key (`key`)"
            ")"
        )
    )

    inspector = inspect(connection)
    idempotency_columns = {
        column["name"] for column in inspector.get_columns("idempotency_keys")
    }
    additions = {
        "user_id": "VARCHAR(64) NULL",
        "request_hash": "VARCHAR(64) NULL",
        "state": "VARCHAR(20) NOT NULL DEFAULT 'COMPLETED'",
        "updated_at": "DATETIME NULL",
    }
    for column_name, definition in additions.items():
        if column_name not in idempotency_columns:
            db_session.execute(
                text(
                    f"ALTER TABLE idempotency_keys ADD COLUMN "
                    f"{column_name} {definition}"
                )
            )

    db_session.execute(
        text(
            "UPDATE idempotency_keys SET state = 'COMPLETED' "
            "WHERE state IS NULL OR TRIM(state) = ''"
        )
    )

    inspector = inspect(connection)
    if not _has_named_index(
        inspector,
        "payment_billings",
        "uq_payment_billings_payment_billing",
    ):
        db_session.execute(
            text(
                "CREATE UNIQUE INDEX uq_payment_billings_payment_billing "
                "ON payment_billings (payment_id, billing_id)"
            )
        )
    if not _has_named_index(
        inspector,
        "payments",
        "uq_payments_property_or_tax_year_date",
    ):
        db_session.execute(
            text(
                "CREATE UNIQUE INDEX uq_payments_property_or_tax_year_date "
                "ON payments (property_id, or_number, tax_year, date_paid)"
            )
        )
    inspector = inspect(connection)
    if _has_named_index(
        inspector,
        "payments",
        "uq_payments_property_or_tax_year_text",
    ):
        # A short-lived Phase 3 build proposed a date-blind index. Install the
        # corrected guard first, then remove the overly restrictive index.
        db_session.execute(
            text("DROP INDEX uq_payments_property_or_tax_year_text ON payments")
        )
    if not _has_named_index(
        inspector,
        "idempotency_keys",
        "ix_idempotency_keys_user_id",
    ):
        db_session.execute(
            text(
                "CREATE INDEX ix_idempotency_keys_user_id "
                "ON idempotency_keys (user_id)"
            )
        )
    if not _has_named_index(
        inspector,
        "idempotency_keys",
        "ix_idempotency_keys_state",
    ):
        db_session.execute(
            text(
                "CREATE INDEX ix_idempotency_keys_state " "ON idempotency_keys (state)"
            )
        )


def ensure_audit_integrity_schema(db_session: Session) -> None:
    """Install Phase 5 columns and seal the preserved legacy audit history."""
    from backend.services.audit_integrity_service import (
        AUDIT_CHAIN_ORIGIN_LEGACY,
        AUDIT_CHAIN_STATE_ID,
        AUDIT_CHAIN_VERSION,
        AUDIT_GENESIS_HASH,
        calculate_audit_hash,
        canonical_audit_payload,
        deterministic_legacy_event_uuid,
        normalize_event_time,
    )

    connection = db_session.connection()
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Phase 5 audit integrity migration requires MariaDB/MySQL.")

    inspector = inspect(connection)
    if not inspector.has_table("audit_logs"):
        raise RuntimeError("Required audit_logs table is missing.")

    additions = {
        "event_uuid": "CHAR(36) NULL",
        "previous_hash": "CHAR(64) NULL",
        "current_hash": "CHAR(64) NULL",
        "chain_version": "SMALLINT NULL",
        "chain_origin": "VARCHAR(32) NULL",
        "compensates_audit_id": "INT NULL",
    }
    existing_columns = {
        column["name"] for column in inspector.get_columns("audit_logs")
    }
    for column_name, definition in additions.items():
        if column_name not in existing_columns:
            db_session.execute(
                text(f"ALTER TABLE audit_logs ADD COLUMN {column_name} {definition}")
            )

    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS audit_chain_state ("
            " id SMALLINT PRIMARY KEY,"
            " head_audit_id INT NULL,"
            " head_hash CHAR(64) NOT NULL,"
            " chain_version SMALLINT NOT NULL,"
            " legacy_event_count INT NOT NULL DEFAULT 0,"
            " legacy_head_audit_id INT NULL,"
            " legacy_head_hash CHAR(64) NULL,"
            " initialized_at DATETIME NOT NULL,"
            " updated_at DATETIME NOT NULL"
            ")"
        )
    )

    rows = (
        db_session.execute(
            text(
                "SELECT id, user_id, username, action, table_name, record_id,"
                " old_values, new_values, ip_address, timestamp, event_uuid,"
                " chain_version, chain_origin, compensates_audit_id"
                " FROM audit_logs ORDER BY id ASC"
            )
        )
        .mappings()
        .all()
    )

    previous_hash = AUDIT_GENESIS_HASH
    legacy_count = 0
    legacy_head_id = None
    legacy_head_hash = None
    updates = []
    for row in rows:
        event_uuid = row["event_uuid"] or deterministic_legacy_event_uuid(row["id"])
        chain_version = int(row["chain_version"] or AUDIT_CHAIN_VERSION)
        chain_origin = row["chain_origin"] or AUDIT_CHAIN_ORIGIN_LEGACY
        timestamp = normalize_event_time(row["timestamp"])
        payload = canonical_audit_payload(
            event_uuid=event_uuid,
            user_id=row["user_id"],
            username=row["username"] or "unknown",
            action=row["action"],
            table_name=row["table_name"],
            record_id=row["record_id"],
            old_values=row["old_values"],
            new_values=row["new_values"],
            ip_address=row["ip_address"],
            timestamp=timestamp,
            chain_version=chain_version,
            chain_origin=chain_origin,
            compensates_audit_id=row["compensates_audit_id"],
        )
        current_hash = calculate_audit_hash(previous_hash, payload)
        updates.append(
            {
                "audit_id": row["id"],
                "event_uuid": event_uuid,
                "previous_hash": previous_hash,
                "current_hash": current_hash,
                "chain_version": chain_version,
                "chain_origin": chain_origin,
            }
        )
        previous_hash = current_hash
        if chain_origin == AUDIT_CHAIN_ORIGIN_LEGACY:
            legacy_count += 1
            legacy_head_id = row["id"]
            legacy_head_hash = current_hash

    if updates:
        db_session.execute(
            text(
                "UPDATE audit_logs SET event_uuid=:event_uuid,"
                " previous_hash=:previous_hash, current_hash=:current_hash,"
                " chain_version=:chain_version, chain_origin=:chain_origin"
                " WHERE id=:audit_id"
            ),
            updates,
        )

    now = normalize_event_time()
    head_id = rows[-1]["id"] if rows else None
    db_session.execute(
        text(
            "INSERT INTO audit_chain_state"
            " (id, head_audit_id, head_hash, chain_version, legacy_event_count,"
            " legacy_head_audit_id, legacy_head_hash, initialized_at, updated_at)"
            " VALUES (:id, :head_id, :head_hash, :chain_version, :legacy_count,"
            " :legacy_head_id, :legacy_head_hash, :now, :now)"
            " ON DUPLICATE KEY UPDATE head_audit_id=VALUES(head_audit_id),"
            " head_hash=VALUES(head_hash), chain_version=VALUES(chain_version),"
            " legacy_event_count=VALUES(legacy_event_count),"
            " legacy_head_audit_id=VALUES(legacy_head_audit_id),"
            " legacy_head_hash=VALUES(legacy_head_hash), updated_at=VALUES(updated_at)"
        ),
        {
            "id": AUDIT_CHAIN_STATE_ID,
            "head_id": head_id,
            "head_hash": previous_hash,
            "chain_version": AUDIT_CHAIN_VERSION,
            "legacy_count": legacy_count,
            "legacy_head_id": legacy_head_id,
            "legacy_head_hash": legacy_head_hash,
            "now": now,
        },
    )

    inspector = inspect(connection)
    if not _has_named_index(inspector, "audit_logs", "uq_audit_logs_event_uuid"):
        db_session.execute(
            text(
                "CREATE UNIQUE INDEX uq_audit_logs_event_uuid "
                "ON audit_logs (event_uuid)"
            )
        )
    inspector = inspect(connection)
    if not _has_named_index(inspector, "audit_logs", "ix_audit_logs_current_hash"):
        db_session.execute(
            text(
                "CREATE INDEX ix_audit_logs_current_hash "
                "ON audit_logs (current_hash)"
            )
        )
    inspector = inspect(connection)
    if not _has_named_index(inspector, "audit_logs", "ix_audit_logs_compensates"):
        db_session.execute(
            text(
                "CREATE INDEX ix_audit_logs_compensates "
                "ON audit_logs (compensates_audit_id)"
            )
        )


def require_audit_integrity_schema(db_session: Session) -> None:
    """Fail server startup when the Phase 5 schema or chain is invalid."""
    from backend.services.audit_integrity_service import (
        AUDIT_TIMESTAMP_REQUIRED_PRECISION,
        audit_timestamp_storage_status,
        audit_chain_schema_status,
        verify_audit_chain,
    )

    status = audit_chain_schema_status(db_session)
    if not status["active"]:
        missing = ", ".join(status["missing_columns"]) or "chain state table"
        raise RuntimeError(f"Phase 5 audit integrity schema is incomplete: {missing}")
    timestamp_storage = audit_timestamp_storage_status(db_session)
    if (
        timestamp_storage["database_dialect"] in {"mysql", "mariadb"}
        and timestamp_storage["datetime_precision"]
        != AUDIT_TIMESTAMP_REQUIRED_PRECISION
    ):
        raise RuntimeError(
            "Phase 5 audit timestamp storage must use MariaDB DATETIME(6)."
        )
    verification = verify_audit_chain(db_session)
    if verification["status"] != "verified":
        raise RuntimeError(
            "Phase 5 audit chain verification failed; keep the API stopped and "
            "preserve the database for incident review."
        )


def run_migrations(db_session: Session) -> int:
    """Checks and applies all pending database migrations."""
    print("--- DATABASE MIGRATION ENGINE ---")

    # 1. Ensure the migration tracking table exists
    try:
        db_session.execute(text(MIGRATIONS[0]["sql"]))
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        raise RuntimeError("Could not initialize migration tracking") from e

    # 2. Get list of already applied migrations
    applied_ids = []
    try:
        results = db_session.execute(text("SELECT id FROM system_migrations")).all()
        applied_ids = [row[0] for row in results]
    except Exception as e:
        db_session.rollback()
        raise RuntimeError("Could not read migration history") from e

    # 3. Apply pending migrations
    new_count = 0
    for m in MIGRATIONS:
        m_id = m["id"]
        if m_id not in applied_ids:
            print(f"Applying Migration: [{m_id}]...")
            try:
                handler_name = m.get("handler")
                if handler_name == "ensure_verified_duplicate_td_schema":
                    ensure_verified_duplicate_td_schema(db_session)
                    statements = []
                elif handler_name == "ensure_financial_safety_schema":
                    ensure_financial_safety_schema(db_session)
                    statements = []
                elif handler_name == "ensure_audit_integrity_schema":
                    ensure_audit_integrity_schema(db_session)
                    statements = []
                elif handler_name == "ensure_audit_timestamp_precision_recovery":
                    from backend.services.audit_integrity_service import (
                        ensure_audit_timestamp_precision_recovery,
                    )

                    ensure_audit_timestamp_precision_recovery(db_session)
                    statements = []
                else:
                    statements = None

                # Support multi-statement migrations by splitting by semicolon
                # Support multi-statement migrations by splitting by semicolon (ignoring semicolons inside single quotes)
                if statements is None:
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
                    text(
                        "INSERT INTO system_migrations (id, applied_at) VALUES (:id, :now)"
                    ),
                    {"id": m_id, "now": datetime.now()},
                )
                db_session.commit()
                new_count += 1
                print(f"SUCCESS: [{m_id}] applied.")
            except Exception as e:
                db_session.rollback()
                raise RuntimeError(f"Migration [{m_id}] failed") from e

    if new_count > 0:
        print(f"Migration Complete: {new_count} new updates applied.")
    else:
        print("Database is up to date. No migrations needed.")
    print("---------------------------------")
    return new_count
