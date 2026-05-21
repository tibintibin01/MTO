# -*- coding: utf-8 -*-
# MTO Treasury System - Migration Manager Shim
# Decoupled from legacy db_manager to use SQLAlchemy migration engine.

import sys
import os

from backend.database import SessionLocal
from backend.services.migration_service import run_migrations as _run_migrations_service


def run_migrations_shim():
    """Runs the SQLAlchemy-based migrations."""
    try:
        with SessionLocal() as session:
            _run_migrations_service(db_session=session)
    except Exception as e:
        print(f"FAILED to apply migrations in shim: {e}")
        raise


def run_migrations():
    """Public entry point called by clients/desktop/main.py."""
    run_migrations_shim()


if __name__ == "__main__":
    run_migrations_shim()
