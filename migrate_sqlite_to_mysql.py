"""
One-off recovery script: migrate the old SQLite `property_system.db` into a
fresh MySQL database that matches the schema the current MTO app expects.

Run this ONCE after XAMPP is back up:

    python migrate_sqlite_to_mysql.py

Optional:

    python migrate_sqlite_to_mysql.py --sqlite property_system.db --overwrite

What it does
------------
1. Reads MySQL credentials from db_config.json (runtime block).
2. Creates the `property_system` database if it does not exist.
3. Creates every table the current app expects (users, properties, payments,
   property_billings, payment_billings, property_edit_locks, audit_logs,
   receipt_history).
4. Copies users, properties, and payment history from the SQLite snapshot.
5. Leaves passwords as-is (plain text). On their first successful login the
   app's verify_password() automatically upgrades them to pbkdf2_sha256.

The script is idempotent: re-running it without --overwrite will skip rows
that already exist (matched on username for users, td_number for properties).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    sys.stderr.write(
        "mysql-connector-python is required. Install it with:\n"
        "    pip install mysql-connector-python\n"
    )
    sys.exit(1)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SQLITE = os.path.join(BASE_DIR, "property_system.db")
DB_CONFIG_PATH = os.path.join(BASE_DIR, "db_config.json")

# SQLite role -> MySQL role mapping. The MTO permission matrix only knows
# admin / cashier / encoder / viewer, so the legacy "user" role is mapped to
# cashier (which can post payments and view records). Adjust if you want
# something stricter.
ROLE_MAP = {
    "admin": "admin",
    "cashier": "cashier",
    "staff": "cashier",
    "encoder": "encoder",
    "viewer": "viewer",
    "user": "cashier",
    "": "viewer",
}


TABLE_DDL = [
    # users
    """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        full_name VARCHAR(255) NOT NULL DEFAULT '',
        username VARCHAR(150) NOT NULL UNIQUE,
        password VARCHAR(512) NOT NULL,
        role VARCHAR(50) NOT NULL DEFAULT 'viewer',
        is_deleted TINYINT(1) NOT NULL DEFAULT 0,
        last_login DATETIME NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # properties
    """
    CREATE TABLE IF NOT EXISTS properties (
        id INT AUTO_INCREMENT PRIMARY KEY,
        td_number VARCHAR(100) NOT NULL,
        owner_name VARCHAR(255) NOT NULL,
        lot_number VARCHAR(100) NULL,
        area VARCHAR(100) NULL,
        location VARCHAR(255) NULL,
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # payments
    """
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # property_billings
    """
    CREATE TABLE IF NOT EXISTS property_billings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        property_id INT NOT NULL,
        tax_year VARCHAR(20) NOT NULL,
        assessed_value DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
        basic_amount DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
        sef_amount DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
        penalty DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
        total_due DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
        has_payment TINYINT(1) NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_property_billings_property_year (property_id, tax_year),
        INDEX idx_property_billings_property_id (property_id),
        CONSTRAINT fk_property_billings_property
            FOREIGN KEY (property_id) REFERENCES properties(id)
            ON UPDATE CASCADE ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # payment_billings
    """
    CREATE TABLE IF NOT EXISTS payment_billings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        payment_id INT NOT NULL,
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # property_edit_locks
    """
    CREATE TABLE IF NOT EXISTS property_edit_locks (
        property_id INT NOT NULL PRIMARY KEY,
        locked_by VARCHAR(255) NOT NULL,
        locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_edit_locks_property
            FOREIGN KEY (property_id) REFERENCES properties(id)
            ON UPDATE CASCADE ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # audit_logs
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(255) NOT NULL,
        action TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_audit_logs_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # receipt_history
    """
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
        INDEX idx_receipt_history_property_id (property_id),
        INDEX idx_receipt_history_or_number (or_number),
        INDEX idx_receipt_history_generated_at (generated_at),
        CONSTRAINT fk_receipt_history_property
            FOREIGN KEY (property_id) REFERENCES properties(id)
            ON DELETE CASCADE ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def load_mysql_config() -> dict:
    if not os.path.exists(DB_CONFIG_PATH):
        raise SystemExit(
            f"db_config.json not found at {DB_CONFIG_PATH}. "
            "Copy db_config.example.json to db_config.json and fill it in first."
        )
    with open(DB_CONFIG_PATH, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    runtime = config.get("runtime", config)
    for key in ("host", "user", "database"):
        if not runtime.get(key):
            raise SystemExit(f"db_config.json runtime.{key} is empty.")
    return {
        "host": runtime["host"],
        "user": runtime["user"],
        "password": runtime.get("password", ""),
        "connect_timeout": int(runtime.get("connect_timeout") or 5),
        "database_name": runtime["database"],
    }


def clean_number(value) -> float:
    if value is None:
        return 0.0
    text = str(value).replace(",", "").replace("\u20b1", "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def clean_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def ensure_database(cfg: dict) -> None:
    print(f"Connecting to MySQL server at {cfg['host']} as {cfg['user']!r}...")
    conn = mysql.connector.connect(
        host=cfg["host"],
        user=cfg["user"],
        password=cfg["password"],
        connect_timeout=cfg["connect_timeout"],
    )
    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{cfg['database_name']}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
        print(f"Database `{cfg['database_name']}` is ready.")
    finally:
        conn.close()


# Columns that must exist on existing tables (for DBs created by earlier
# versions of the app). Each entry is: table -> list of (column, ALTER clause).
REQUIRED_COLUMNS = {
    "users": [
        ("full_name", "ADD COLUMN full_name VARCHAR(255) NOT NULL DEFAULT '' AFTER id"),
        ("password", "ADD COLUMN password VARCHAR(512) NOT NULL DEFAULT '' AFTER username"),
        ("role", "ADD COLUMN role VARCHAR(50) NOT NULL DEFAULT 'viewer' AFTER password"),
        ("is_deleted", "ADD COLUMN is_deleted TINYINT(1) NOT NULL DEFAULT 0 AFTER role"),
        ("last_login", "ADD COLUMN last_login DATETIME NULL AFTER is_deleted"),
        ("created_at", "ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP AFTER last_login"),
    ],
    "properties": [
        ("td_number", "ADD COLUMN td_number VARCHAR(100) NOT NULL DEFAULT ''"),
        ("owner_name", "ADD COLUMN owner_name VARCHAR(255) NOT NULL DEFAULT ''"),
        ("lot_number", "ADD COLUMN lot_number VARCHAR(100) NULL"),
        ("area", "ADD COLUMN area VARCHAR(100) NULL"),
        ("location", "ADD COLUMN location VARCHAR(255) NULL"),
        ("accountable_officer", "ADD COLUMN accountable_officer VARCHAR(255) NULL"),
        ("assessed_value", "ADD COLUMN assessed_value DECIMAL(14, 2) NOT NULL DEFAULT 0.00"),
        ("penalty", "ADD COLUMN penalty DECIMAL(14, 2) NOT NULL DEFAULT 0.00"),
        ("or_number", "ADD COLUMN or_number VARCHAR(100) NULL"),
        ("or_date", "ADD COLUMN or_date DATE NULL"),
        ("tax_year", "ADD COLUMN tax_year VARCHAR(100) NULL"),
        ("is_deleted", "ADD COLUMN is_deleted TINYINT(1) NOT NULL DEFAULT 0"),
        ("archived", "ADD COLUMN archived TINYINT(1) NOT NULL DEFAULT 0"),
        ("created_at", "ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ],
    "payments": [
        ("property_id", "ADD COLUMN property_id INT NULL AFTER id"),
        ("amount", "ADD COLUMN amount DECIMAL(12, 2) NOT NULL DEFAULT 0.00 AFTER property_id"),
        ("or_number", "ADD COLUMN or_number VARCHAR(255) NULL AFTER amount"),
        ("date_paid", "ADD COLUMN date_paid DATE NULL AFTER or_number"),
        ("tax_year", "ADD COLUMN tax_year VARCHAR(20) NULL AFTER date_paid"),
        ("posted_by", "ADD COLUMN posted_by VARCHAR(255) NULL AFTER tax_year"),
        ("created_at", "ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP AFTER posted_by"),
    ],
}


def _existing_columns(cur, table: str) -> set[str]:
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table,),
    )
    return {row[0] for row in cur.fetchall()}


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


def create_tables(conn) -> None:
    cur = conn.cursor()
    for ddl in TABLE_DDL:
        cur.execute(ddl)
    conn.commit()

    # Patch pre-existing tables so they match the schema the app expects.
    added_any = False
    for table, columns in REQUIRED_COLUMNS.items():
        if not _table_exists(cur, table):
            continue
        existing = _existing_columns(cur, table)
        for column_name, alter_clause in columns:
            if column_name in existing:
                continue
            try:
                cur.execute(f"ALTER TABLE {table} {alter_clause}")
                print(f"  + added column {table}.{column_name}")
                added_any = True
            except MySQLError as exc:
                print(f"  ! could not add {table}.{column_name}: {exc}")
    conn.commit()
    if not added_any:
        print("All required tables are in place.")
    else:
        print("All required tables are in place (schema patched).")


def migrate_users(sqlite_conn, mysql_conn, overwrite: bool) -> None:
    rows = sqlite_conn.execute(
        "SELECT username, password, COALESCE(role, '') FROM users"
    ).fetchall()
    if not rows:
        print("No users to migrate.")
        return

    cur = mysql_conn.cursor()
    inserted = skipped = updated = 0
    for username, password, role in rows:
        normalized_role = ROLE_MAP.get(str(role or "").strip().lower(), str(role or "viewer"))
        full_name = username.title()
        cur.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (username,))
        existing = cur.fetchone()
        if existing:
            if overwrite:
                cur.execute(
                    "UPDATE users SET password=%s, role=%s, is_deleted=0 WHERE id=%s",
                    (password, normalized_role, existing[0]),
                )
                updated += 1
            else:
                skipped += 1
            continue
        cur.execute(
            """
            INSERT INTO users (full_name, username, password, role, is_deleted)
            VALUES (%s, %s, %s, %s, 0)
            """,
            (full_name, username, password, normalized_role),
        )
        inserted += 1
    mysql_conn.commit()
    print(f"Users: inserted={inserted}, updated={updated}, skipped={skipped}")


def fetch_property_columns(sqlite_conn) -> list[str]:
    return [row[1] for row in sqlite_conn.execute("PRAGMA table_info(properties)")]


def fetch_payment_columns(sqlite_conn) -> list[str]:
    try:
        return [row[1] for row in sqlite_conn.execute("PRAGMA table_info(payment_history)")]
    except sqlite3.OperationalError:
        return []


def migrate_properties(sqlite_conn, mysql_conn, overwrite: bool) -> dict:
    sqlite_cols = fetch_property_columns(sqlite_conn)
    if not sqlite_cols:
        print("No properties table in SQLite source; skipping.")
        return {}

    rows = sqlite_conn.execute(f"SELECT {', '.join(sqlite_cols)} FROM properties").fetchall()
    if not rows:
        print("No properties to migrate.")
        return {}

    cur = mysql_conn.cursor()
    inserted = skipped = updated = 0
    td_to_id: dict[str, int] = {}

    for row in rows:
        record = dict(zip(sqlite_cols, row))
        td_number = (record.get("td_number") or "").strip()
        owner_name = (record.get("owner_name") or "").strip()
        if not td_number or not owner_name:
            continue

        values = (
            td_number,
            owner_name,
            (record.get("lot_number") or "").strip(),
            (record.get("area") or "").strip(),
            (record.get("location") or "").strip(),
            (record.get("accountable_officer") or "System").strip() or "System",
            clean_number(record.get("assessed_value")),
            clean_number(record.get("penalty")),
            (record.get("or_number") or "").strip(),
            clean_date(record.get("or_date")),
            (record.get("tax_year") or "").strip(),
            int(record.get("is_deleted") or 0),
        )

        cur.execute("SELECT id FROM properties WHERE td_number=%s LIMIT 1", (td_number,))
        existing = cur.fetchone()
        if existing:
            td_to_id[td_number] = existing[0]
            if overwrite:
                cur.execute(
                    """
                    UPDATE properties
                    SET owner_name=%s, lot_number=%s, area=%s, location=%s,
                        accountable_officer=%s, assessed_value=%s, penalty=%s,
                        or_number=%s, or_date=%s, tax_year=%s, is_deleted=%s
                    WHERE id=%s
                    """,
                    (*values[1:], existing[0]),
                )
                updated += 1
            else:
                skipped += 1
            continue

        cur.execute(
            """
            INSERT INTO properties (
                td_number, owner_name, lot_number, area, location,
                accountable_officer, assessed_value, penalty,
                or_number, or_date, tax_year, is_deleted
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )
        td_to_id[td_number] = cur.lastrowid
        inserted += 1

    mysql_conn.commit()
    print(f"Properties: inserted={inserted}, updated={updated}, skipped={skipped}")
    return td_to_id


def migrate_payments(sqlite_conn, mysql_conn, td_to_id: dict, overwrite: bool) -> None:
    payment_cols = fetch_payment_columns(sqlite_conn)
    if not payment_cols:
        print("No payment_history table in SQLite source; skipping.")
        return

    rows = sqlite_conn.execute(f"SELECT {', '.join(payment_cols)} FROM payment_history").fetchall()
    if not rows:
        print("No payment history rows to migrate.")
        return

    cur = mysql_conn.cursor()
    inserted = skipped = 0
    for row in rows:
        record = dict(zip(payment_cols, row))
        td_number = (record.get("td_number") or "").strip()
        property_id = td_to_id.get(td_number)
        if not property_id:
            skipped += 1
            continue

        amount = clean_number(record.get("amount_paid"))
        or_number = (record.get("or_number") or "").strip()
        date_paid = clean_date(record.get("date_paid"))
        tax_year = (record.get("tax_year") or "").strip()
        posted_by = (record.get("posted_by") or "System").strip() or "System"

        # Skip duplicates (same property + OR + tax_year) unless overwriting
        if not overwrite and or_number:
            cur.execute(
                "SELECT id FROM payments WHERE property_id=%s AND or_number=%s AND IFNULL(tax_year,'')=%s LIMIT 1",
                (property_id, or_number, tax_year),
            )
            if cur.fetchone():
                skipped += 1
                continue

        cur.execute(
            """
            INSERT INTO payments (property_id, amount, or_number, date_paid, tax_year, posted_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (property_id, amount, or_number, date_paid, tax_year, posted_by),
        )
        inserted += 1

    mysql_conn.commit()
    print(f"Payments: inserted={inserted}, skipped={skipped}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite",
        default=DEFAULT_SQLITE,
        help=f"Path to the SQLite source DB (default: {DEFAULT_SQLITE})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Update existing MySQL rows with SQLite values (default: skip duplicates).",
    )
    args = parser.parse_args()

    if not os.path.exists(args.sqlite):
        raise SystemExit(f"SQLite file not found: {args.sqlite}")

    cfg = load_mysql_config()

    try:
        ensure_database(cfg)
    except MySQLError as exc:
        raise SystemExit(f"Could not connect to MySQL server: {exc}") from exc

    mysql_conn = mysql.connector.connect(
        host=cfg["host"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database_name"],
        connect_timeout=cfg["connect_timeout"],
    )
    sqlite_conn = sqlite3.connect(args.sqlite)

    try:
        create_tables(mysql_conn)
        migrate_users(sqlite_conn, mysql_conn, args.overwrite)
        td_to_id = migrate_properties(sqlite_conn, mysql_conn, args.overwrite)
        migrate_payments(sqlite_conn, mysql_conn, td_to_id, args.overwrite)
    finally:
        sqlite_conn.close()
        mysql_conn.close()

    print("\nMigration complete. You can now launch the app and log in.")
    print("  Default users (from the SQLite snapshot):")
    print("    admin / 1111  (role: admin)")
    print("    kebin / 11111 (role: cashier)")
    print("  After your first successful login the app will re-hash each password automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
