#!/usr/bin/env python3
"""
MTO Treasury System - Database Root User Hardening
==================================================
Reads DB_ROOT_PASSWORD from .env and applies it to all 'root' MariaDB/MySQL accounts,
closing the blank-password root security vulnerability.

Usage:
    python scripts/secure_root_user.py
"""

import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

if not ENV_FILE.exists():
    print(f"ERROR: .env file not found at {ENV_FILE}")
    sys.exit(1)

# Parse .env manually
env_vars = {}
with open(ENV_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env_vars[key.strip()] = value.strip()

ROOT_PASSWORD = env_vars.get("DB_ROOT_PASSWORD", "").strip()
DB_HOST = env_vars.get("MTO_DB_HOST", "127.0.0.1").strip()
DB_PORT = env_vars.get("MTO_DB_PORT", "3306").strip()

if not ROOT_PASSWORD or ROOT_PASSWORD in ("CHANGE_ME", "your_secure_root_password_min_16_chars"):
    print("ERROR: DB_ROOT_PASSWORD in .env is not set or still contains a placeholder.")
    sys.exit(1)

print("=" * 65)
print("  MariaDB/MySQL Root User Hardening")
print("=" * 65)
print(f"  Target Host : {DB_HOST}:{DB_PORT}")
print()

# Step 1: Check if root is already secured
print("Step 1: Testing if root is already secured...")
already_secured = False
try:
    # Try connecting with the secure password
    engine_secure = create_engine(f"mysql+pymysql://root:{ROOT_PASSWORD}@{DB_HOST}:{DB_PORT}/mysql")
    with engine_secure.connect() as conn:
        conn.execute(text("SELECT 1"))
    already_secured = True
    print("  -> root is ALREADY secured with the password from .env! No action needed.")
except Exception:
    print("  -> Cannot connect as root with .env password. Checking blank password...")

# Step 2: If not secured, attempt to connect with blank password and secure it
if not already_secured:
    try:
        engine_blank = create_engine(f"mysql+pymysql://root:@{DB_HOST}:{DB_PORT}/mysql")
        with engine_blank.connect() as conn:
            print("Step 2: Connected successfully as root with a blank password. Securing accounts...")
            
            # Fetch all root hosts
            res = conn.execute(text("SELECT Host FROM mysql.user WHERE User='root'")).fetchall()
            hosts = [row[0] for row in res]
            print(f"  Found root hosts: {hosts}")
            
            for host in hosts:
                # Validate host before interpolating — ALTER USER syntax does not
                # support bind parameters for the host value, so we whitelist the
                # only values that should ever appear in mysql.user for root.
                ALLOWED_HOSTS = {"localhost", "127.0.0.1", "%", "::1"}
                if host not in ALLOWED_HOSTS:
                    print(f"  Skipping unexpected host '{host}' — manual review required.")
                    continue
                print(f"  Securing root@{host}...")
                conn.execute(text(f"ALTER USER 'root'@'{host}' IDENTIFIED BY :pwd"), {"pwd": ROOT_PASSWORD})
            
            print("  Applying privilege flush...")
            conn.execute(text("FLUSH PRIVILEGES"))
            conn.commit()
            print("[SUCCESS] Root accounts secured successfully!")
            
    except Exception as e:
        print(f"[ERROR] Failed to secure root account: {e}")
        sys.exit(1)

# Step 3: Self-validation
print("\nStep 3: Self-validating security constraints...")

# Check that blank password is now rejected
try:
    engine_blank = create_engine(f"mysql+pymysql://root:@{DB_HOST}:{DB_PORT}/mysql")
    with engine_blank.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("[ERROR] SECURITY VALIDATION FAILED: root is still accessible with a blank password!")
    sys.exit(1)
except Exception:
    print("  -> Verification 1 passed: Blank-password root access is REJECTED (expected).")

# Check that secure password is accepted
try:
    engine_secure = create_engine(f"mysql+pymysql://root:{ROOT_PASSWORD}@{DB_HOST}:{DB_PORT}/mysql")
    with engine_secure.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("  -> Verification 2 passed: Secure-password root access is ACCEPTED (expected).")
except Exception as e:
    print(f"[ERROR] VALIDATION ERROR: Failed to connect with secure password: {e}")
    sys.exit(1)

# Check that mto_app continues to work perfectly
APP_PASSWORD = env_vars.get("MTO_DB_PASSWORD", "").strip()
APP_USER = env_vars.get("MTO_DB_USER", "mto_app").strip()
APP_DB = env_vars.get("MTO_DB_NAME", "property_system").strip()

try:
    engine_app = create_engine(f"mysql+pymysql://{APP_USER}:{APP_PASSWORD}@{DB_HOST}:{DB_PORT}/{APP_DB}")
    with engine_app.connect() as conn:
        res = conn.execute(text("SELECT 1")).scalar()
    if res == 1:
        print(f"  -> Verification 3 passed: Least-privilege user '{APP_USER}' can connect successfully.")
except Exception as e:
    print(f"[ERROR] VALIDATION ERROR: App user '{APP_USER}' is unable to connect: {e}")
    sys.exit(1)

print("\nALL DATABASE HARDENING TESTS PASSED SUCCESSFULLY! The root password is now strictly secured.")
