#!/usr/bin/env python3
"""
MTO Treasury System — DB User Provisioning Helper
==================================================
Reads MTO_DB_PASSWORD and MTO_DB_NAME from .env, then creates the least-
privilege 'mto_app' MariaDB/MySQL user and grants it the minimum permissions
required to run the application.

Usage (run from the project root):
    python scripts/create_db_user.py

You will be prompted for the MariaDB root password. The script never stores
or logs that password — it is passed directly to the subprocess via stdin.

Requirements:
    - mysql client binary on PATH (or set MTO_MYSQL_PATH in .env)
    - MariaDB/MySQL root access
    - .env file with MTO_DB_PASSWORD and MTO_DB_NAME set
"""

import os
import sys
import subprocess
import getpass
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root and load .env
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

if not ENV_FILE.exists():
    print(f"ERROR: .env file not found at {ENV_FILE}")
    print("Copy .env.template to .env and fill in the values first.")
    sys.exit(1)

# Parse .env manually — avoid importing the full app stack here
env_vars: dict[str, str] = {}
with open(ENV_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env_vars[key.strip()] = value.strip()

APP_PASSWORD = env_vars.get("MTO_DB_PASSWORD", "").strip()
DB_NAME      = env_vars.get("MTO_DB_NAME", "property_system").strip()
DB_HOST      = env_vars.get("MTO_DB_HOST", "127.0.0.1").strip()
DB_PORT      = env_vars.get("MTO_DB_PORT", "3306").strip()
MYSQL_BIN    = env_vars.get("MTO_MYSQL_PATH", "mysql").strip()

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
PLACEHOLDER = "CHANGE_ME"

if not APP_PASSWORD or APP_PASSWORD == PLACEHOLDER or "CHANGE_ME" in APP_PASSWORD:
    print("ERROR: MTO_DB_PASSWORD in .env is not set or still contains the placeholder.")
    print("Generate a strong password with:")
    print('  python -c "import secrets; print(secrets.token_hex(24))"')
    print("Then update MTO_DB_PASSWORD in .env and re-run this script.")
    sys.exit(1)

if len(APP_PASSWORD) < 16:
    print("ERROR: MTO_DB_PASSWORD is too short (minimum 16 characters).")
    sys.exit(1)

# Locate the mysql binary
import shutil
mysql_exe = MYSQL_BIN if shutil.which(MYSQL_BIN) or os.path.exists(MYSQL_BIN) else None
if not mysql_exe:
    # Try common Windows paths
    candidates = [
        r"C:\xampp\mysql\bin\mysql.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
        r"D:\xampp\mysql\bin\mysql.exe",
        "/usr/bin/mysql",
        "/usr/local/bin/mysql",
        "/opt/homebrew/bin/mysql",
    ]
    for c in candidates:
        if os.path.exists(c):
            mysql_exe = c
            break

if not mysql_exe:
    print("ERROR: Could not locate the mysql client binary.")
    print("Set MTO_MYSQL_PATH in .env to the full path of your mysql executable.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Build the SQL to execute
# ---------------------------------------------------------------------------
SQL = f"""
CREATE DATABASE IF NOT EXISTS `{DB_NAME}`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'mto_app'@'localhost'
    IDENTIFIED BY '{APP_PASSWORD}';

CREATE USER IF NOT EXISTS 'mto_app'@'%'
    IDENTIFIED BY '{APP_PASSWORD}';

ALTER USER 'mto_app'@'localhost' IDENTIFIED BY '{APP_PASSWORD}';
ALTER USER 'mto_app'@'%'         IDENTIFIED BY '{APP_PASSWORD}';

GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, ALTER, DROP, INDEX,
      REFERENCES, LOCK TABLES
    ON `{DB_NAME}`.*
    TO 'mto_app'@'localhost';

GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, ALTER, DROP, INDEX,
      REFERENCES, LOCK TABLES
    ON `{DB_NAME}`.*
    TO 'mto_app'@'%';

FLUSH PRIVILEGES;
"""

# ---------------------------------------------------------------------------
# Prompt for root password and execute
# ---------------------------------------------------------------------------
print("=" * 60)
print("  MTO Treasury — Database User Provisioning")
print("=" * 60)
print(f"  Database : {DB_NAME}")
print(f"  App user : mto_app")
print(f"  Host     : {DB_HOST}:{DB_PORT}")
print(f"  mysql    : {mysql_exe}")
print()
print("Enter the MariaDB/MySQL ROOT password to proceed.")
print("(Leave blank if root has no password — XAMPP default)")

root_password = getpass.getpass("Root password: ")

cmd = [
    mysql_exe,
    f"--host={DB_HOST}",
    f"--port={DB_PORT}",
    "--user=root",
    "--batch",
    "--execute",
    SQL,
]
if root_password:
    cmd.insert(4, f"--password={root_password}")

print()
print("Running provisioning SQL...")

try:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print("ERROR: mysql returned a non-zero exit code.")
        # Strip the password from any error output before printing
        stderr = result.stderr.replace(root_password, "***") if root_password else result.stderr
        print(stderr)
        sys.exit(1)
except subprocess.TimeoutExpired:
    print("ERROR: mysql command timed out after 30 seconds.")
    sys.exit(1)
except FileNotFoundError:
    print(f"ERROR: mysql binary not found at '{mysql_exe}'.")
    sys.exit(1)

print()
print("✅  Provisioning complete.")
print()
print("Verify with (connect as root):")
print(f"  SHOW GRANTS FOR 'mto_app'@'localhost';")
print(f"  SHOW GRANTS FOR 'mto_app'@'%';")
print()
print("Next steps:")
print("  1. Confirm MTO_DB_USER=mto_app in .env")
print("  2. Run: python backend/main.py  (or docker compose up)")
