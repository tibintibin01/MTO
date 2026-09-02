import pytest

import migration_manager
from backend.services import migration_service


class _FakeSession:
    def __init__(self):
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def commit(self):
        self.commits += 1


def test_server_migration_entrypoint_runs_all_compatibility_checks(monkeypatch):
    session = _FakeSession()
    calls = []
    monkeypatch.setattr(migration_manager, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        migration_manager,
        "_run_migrations_service",
        lambda db_session: calls.append(("registry", db_session)) or 2,
    )
    monkeypatch.setattr(
        migration_manager,
        "ensure_refresh_token_session_columns",
        lambda db_session: calls.append(("refresh", db_session)),
    )
    monkeypatch.setattr(
        migration_manager,
        "ensure_payment_remarks_column",
        lambda db_session: calls.append(("remarks", db_session)),
    )
    monkeypatch.setattr(
        migration_manager,
        "ensure_portfolio_schema",
        lambda db_session: calls.append(("portfolio", db_session)),
    )

    assert migration_manager.run_migrations() == 2
    assert [name for name, _session in calls] == [
        "registry",
        "refresh",
        "remarks",
        "portfolio",
    ]
    assert all(call_session is session for _name, call_session in calls)
    assert session.commits == 1


class _FailingSession:
    def __init__(self):
        self.rollbacks = 0

    def execute(self, _statement):
        raise OSError("database unavailable")

    def commit(self):
        raise AssertionError("commit must not occur")

    def rollback(self):
        self.rollbacks += 1


def test_migration_registry_fails_closed_when_tracking_cannot_initialize():
    session = _FailingSession()

    with pytest.raises(RuntimeError, match="initialize migration tracking"):
        migration_service.run_migrations(session)

    assert session.rollbacks == 1
