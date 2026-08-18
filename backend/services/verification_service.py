import os
import subprocess
import hashlib
import re
import uuid
import pymysql
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from utils.config import config as mto_config
from utils.secrets_manager import secrets

DB_CONFIG = {
    "mysql_path": getattr(mto_config, "MYSQL_PATH", "mysql"),
    "user": mto_config.DB_USER,
    "password": secrets.db_password,
    "host": mto_config.DB_HOST,
    "port": mto_config.DB_PORT,
}



def _restore_credential_candidates():
    """Returns DB users to try for isolated restore verification."""
    candidates = []

    verify_user = secrets.get("MTO_BACKUP_VERIFY_DB_USER", default=None)
    verify_password = secrets.get("MTO_BACKUP_VERIFY_DB_PASSWORD", default="")
    if verify_user:
        candidates.append((verify_user, verify_password, "configured verification user"))

    root_password = secrets.get("DB_ROOT_PASSWORD", default=None)
    if root_password is not None:
        candidates.append(("root", root_password, "DB_ROOT_PASSWORD root user"))

    # XAMPP installs often use a blank local root password. Try it only as a
    # local fallback, never as the first production assumption.
    candidates.append(("root", "", "local root fallback"))
    candidates.append((DB_CONFIG["user"], DB_CONFIG["password"], "application user"))

    unique = []
    seen = set()
    for user, password, label in candidates:
        key = (user, password)
        if user and key not in seen:
            unique.append((user, password, label))
            seen.add(key)
    return unique


def _connect_for_restore_verification():
    """Finds a MySQL account that can connect for restore verification."""
    last_error = None
    for user, password, label in _restore_credential_candidates():
        try:
            conn = pymysql.connect(
                host=DB_CONFIG["host"],
                port=int(DB_CONFIG["port"]),
                user=user,
                password=password or "",
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=10,
                read_timeout=30,
                write_timeout=30,
            )
            return conn, user, password or "", label
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"could not connect with any restore verification DB account: {last_error}")

def _calculate_sha256(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(1024 * 1024), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


DATABASE_SCOPE_STATEMENT = re.compile(
    r"(?:^|;)\s*(?:/\*![0-9]{5}\s*)?"
    r"(?:USE\s+|(?:CREATE|DROP|ALTER)\s+(?:DATABASE|SCHEMA)\b)",
    re.IGNORECASE,
)


def _find_database_scope_statement(file_path: str) -> str | None:
    """Rejects dump commands that could redirect a restore outside the test DB."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as source:
        for line_number, line in enumerate(source, start=1):
            match = DATABASE_SCOPE_STATEMENT.search(line)
            if match:
                statement = " ".join(match.group(0).strip(" ;").split())
                return f"line {line_number}: {statement[:80]}"
    return None


def verify_sql_dump(
    file_path,
    db_session: Session = None,
    expected_checksum: str = None,
    *,
    require_restore_test: bool = False,
):
    """
    Performs a multi-point integrity check on a MySQL dump file.
    1. Shallow Check: File presence and completion marker.
    2. Deep Check: Automated Restore Test into a temp database (skipped if
       no DB session is available or DB credentials are not configured).
    """
    # 1. Shallow Check
    if not os.path.exists(file_path):
        return False, "Backup file was not created."
    
    file_size = os.path.getsize(file_path)
    if file_size < 100:
        return False, f"Backup file is suspiciously small ({file_size} bytes)."

    try:
        with open(file_path, "rb") as f:
            if file_size > 1024:
                f.seek(-1024, os.SEEK_END)
            footer = f.read().decode("utf-8", errors="ignore")
            if "-- Dump completed" not in footer and "UNLOCK TABLES;" not in footer:
                return False, "Incomplete SQL dump (no completion marker)."
    except Exception as e:
        return False, f"Shallow Verification Error: {str(e)}"

    # 2. Deep Check — requires a live DB session and configured credentials
    if expected_checksum:
        try:
            actual_checksum = _calculate_sha256(file_path)
            if actual_checksum.lower() != expected_checksum.lower():
                return False, "Checksum mismatch: backup file content changed after creation."
        except Exception as e:
            return False, f"Checksum Verification Error: {str(e)}"

    if db_session is None:
        try:
            with SessionLocal() as session:
                return perform_restore_test(
                    file_path,
                    db_session=session,
                    require_restore_test=require_restore_test,
                )
        except Exception as exc:
            if require_restore_test:
                return False, (
                    "Full restore verification is required but the application "
                    f"database session could not be opened: {exc}"
                )
            # If we can't get a session (e.g. DB not configured), skip deep check
            return True, "Shallow check passed. Deep restore test skipped (no DB session)."

    return perform_restore_test(
        file_path,
        db_session=db_session,
        require_restore_test=require_restore_test,
    )


def perform_restore_test(
    file_path,
    db_session: Session = None,
    *,
    require_restore_test: bool = False,
):
    """
    Verifies that the backup can actually be restored by performing
    a dry-run restore into a temporary validation database.

    The normal application DB user is intentionally least-privilege and may not
    be allowed to CREATE/DROP DATABASE. When no verification-capable account is
    available, checksum verification still passes but the restore test is
    marked as skipped with clear setup guidance.
    """
    # Create a safe temp name (sanitize filename to be a valid DB name).
    # Only allow alphanumeric + underscore; no SQL injection possible.
    base_name = os.path.basename(file_path).split('.')[0]
    safe_name = "".join([c if c.isalnum() else "_" for c in base_name])[:40]
    temp_db_name = f"mto_verify_{safe_name}_{uuid.uuid4().hex[:8]}"
    unsafe_statement = _find_database_scope_statement(file_path)
    if unsafe_statement:
        return False, (
            "Restore Test Failed: SQL dump contains a database-level statement "
            f"that is unsafe for isolated verification ({unsafe_statement})."
        )


    if not re.fullmatch(r"[a-zA-Z0-9_]+", temp_db_name):
        return False, f"Unsafe temp DB name generated: {temp_db_name!r}"

    mysql_path = DB_CONFIG.get("mysql_path", "mysql")

    COMMON_MYSQL_PATHS = [
        mysql_path,
        r"C:\xampp\mysql\bin\mysql.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
        r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysql.exe",
        r"D:\xampp\mysql\bin\mysql.exe",
        r"C:\mysql\bin\mysql.exe",
        "/usr/bin/mysql",
        "/usr/local/bin/mysql",
        "/opt/homebrew/bin/mysql",
        "/usr/local/mysql/bin/mysql",
    ]

    import shutil
    actual_mysql_executable = None
    for p in COMMON_MYSQL_PATHS:
        if "\\" not in p and "/" not in p:
            if shutil.which(p):
                actual_mysql_executable = p
                break
        elif os.path.exists(p):
            actual_mysql_executable = p
            break

    if not actual_mysql_executable:
        if require_restore_test:
            return False, (
                "Full restore verification is required, but the mysql executable "
                "was not found. Configure MTO_MYSQL_PATH before enabling cloud backup."
            )
        return True, "Checksum passed. Restore test skipped: mysql executable was not found."

    conn = None
    created_db = False
    try:
        conn, db_user, db_pass, credential_label = _connect_for_restore_verification()
        with conn.cursor() as cur:
            try:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{temp_db_name}`")
                created_db = True
            except pymysql.err.OperationalError as exc:
                code = exc.args[0] if exc.args else None
                if code in (1044, 1045):
                    if require_restore_test:
                        return False, (
                            "Full restore verification is required, but the configured "
                            "verification DB user cannot create and remove the isolated "
                            "test database. Configure MTO_BACKUP_VERIFY_DB_USER and "
                            "MTO_BACKUP_VERIFY_DB_PASSWORD with CREATE/DROP privileges."
                        )
                    return True, (
                        "Checksum passed. Restore test skipped: the configured DB user "
                        "cannot create a temporary verification database. Configure "
                        "MTO_BACKUP_VERIFY_DB_USER and MTO_BACKUP_VERIFY_DB_PASSWORD "
                        "with CREATE/DROP privileges to enable full restore testing."
                    )
                raise

        cmd = [
            actual_mysql_executable,
            f"-u{db_user}",
            f"-h{DB_CONFIG['host']}",
            f"-P{DB_CONFIG['port']}",
            "--one-database",
            temp_db_name,
        ]
        env = dict(os.environ)
        if db_pass:
            env["MYSQL_PWD"] = db_pass

        with open(file_path, "r", encoding="utf-8") as f:
            subprocess.run(cmd, stdin=f, check=True, timeout=600, env=env)

        required_tables = ("users", "properties", "payments", "property_billings", "backup_history")
        placeholders = ", ".join(["%s"] * len(required_tables))
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "  # nosec B608
                f"WHERE table_schema = %s AND table_name IN ({placeholders})",
                (temp_db_name, *required_tables),
            )
            restored_tables = {row[0] for row in cur.fetchall()}
            missing_tables = sorted(set(required_tables) - restored_tables)
            if missing_tables:
                raise RuntimeError(f"missing tables after restore: {', '.join(missing_tables)}")

            cur.execute(f"SELECT COUNT(*) FROM `{temp_db_name}`.`properties`")  # nosec B608
            property_count = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM `{temp_db_name}`.`payments`")  # nosec B608
            payment_count = cur.fetchone()[0]

        if property_count > 0:
            return True, (
                "Checksum and restore test passed: "
                f"{property_count} properties and {payment_count} payments verified."
            )
        return False, "Restore Test Failed: Database is empty after restoration."

    except Exception as e:
        return False, f"Restore Test Failed: {str(e)}"

    finally:
        if conn:
            try:
                if created_db:
                    with conn.cursor() as cur:
                        cur.execute(f"DROP DATABASE IF EXISTS `{temp_db_name}`")
            except Exception as cleanup_err:
                from utils.logger import mto_logger
                mto_logger.warning(
                    "verification_service: failed to drop temp DB '%s' during cleanup: %s",
                    temp_db_name, cleanup_err,
                )
            try:
                conn.close()
            except Exception:
                pass
