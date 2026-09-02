# -*- coding: utf-8 -*-
"""Server-only database migration entrypoint.

Run this command from the API server checkout before starting the API:
    python -m migration_manager

Desktop clients must never import or execute this module.
"""

from backend.database import SessionLocal
from backend.services.migration_service import (
    ensure_payment_remarks_column,
    ensure_refresh_token_session_columns,
    run_migrations as _run_migrations_service,
)
from backend.services.portfolio_service import ensure_portfolio_schema


def run_migrations() -> int:
    """Apply server migrations and fail closed if any schema repair fails."""
    with SessionLocal() as session:
        applied = _run_migrations_service(db_session=session)
        ensure_refresh_token_session_columns(session)
        ensure_payment_remarks_column(session)
        ensure_portfolio_schema(session)
        session.commit()
    print("Server schema compatibility checks passed.")
    return applied


if __name__ == "__main__":
    run_migrations()
