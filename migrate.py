# -*- coding: utf-8 -*-
# MTO Treasury System - Automated Migration Manager
# Decoupled from legacy db_manager to use SQLAlchemy migration engine.

import sys
import os

# Add root folder to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from backend.database import SessionLocal
from backend.services.migration_service import run_migrations

def main():
    print("--- MTO Automated Migration Manager (SQLAlchemy) ---")
    try:
        with SessionLocal() as session:
            run_migrations(db_session=session)
        print("\n[FINISH] Migration cycle complete.")
    except Exception as e:
        print(f"❌ CRITICAL MIGRATION ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
