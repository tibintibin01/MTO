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
        "ensure_financial_safety_schema",
        lambda db_session: calls.append(("financial", db_session)),
    )
    monkeypatch.setattr(
        migration_manager,
        "ensure_phase6_financial_reconciliation_schema",
        lambda db_session: calls.append(("phase6", db_session)),
    )
    monkeypatch.setattr(
        migration_manager,
        "require_audit_integrity_schema",
        lambda db_session: calls.append(("audit", db_session)),
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
        "financial",
        "phase6",
        "audit",
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


def test_phase6_migration_is_registered_and_dispatched():
    migration = next(
        item
        for item in migration_service.MIGRATIONS
        if item["id"] == "phase6_financial_reconciliation_integrity_v1"
    )

    assert migration["handler"] == "ensure_phase6_financial_reconciliation_schema"


def test_receipt_payment_foreign_key_matcher_requires_exact_identity():
    class Inspector:
        def get_foreign_keys(self, _table_name):
            return [
                {
                    "constrained_columns": ["payment_id"],
                    "referred_table": "payments",
                    "referred_columns": ["id"],
                    "options": {"ondelete": "SET NULL"},
                },
                {
                    "constrained_columns": ["property_id"],
                    "referred_table": "properties",
                    "referred_columns": ["id"],
                    "options": {"ondelete": "RESTRICT"},
                },
            ]

    matches = migration_service._receipt_payment_foreign_keys(Inspector())

    assert len(matches) == 1
    assert matches[0]["options"]["ondelete"] == "SET NULL"


class _Phase6Dialect:
    name = "mysql"


class _Phase6Connection:
    dialect = _Phase6Dialect()


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _Phase6Session:
    def __init__(self, orphan_count=0):
        self.orphan_count = orphan_count
        self.statements = []

    def connection(self):
        return _Phase6Connection()

    def execute(self, statement):
        rendered = str(statement)
        self.statements.append(rendered)
        if rendered.startswith("SELECT COUNT(*) FROM receipt_history"):
            return _ScalarResult(self.orphan_count)
        return _ScalarResult(None)


class _Phase6Inspector:
    def __init__(self, foreign_keys=()):
        self.foreign_keys = list(foreign_keys)

    def has_table(self, _table_name):
        return True

    def get_foreign_keys(self, _table_name):
        return self.foreign_keys


def test_phase6_migration_refuses_orphan_receipt_links(monkeypatch):
    session = _Phase6Session(orphan_count=2)
    monkeypatch.setattr(
        migration_service,
        "inspect",
        lambda _connection: _Phase6Inspector(),
    )

    with pytest.raises(RuntimeError, match="orphan receipt links=2"):
        migration_service.ensure_phase6_financial_reconciliation_schema(session)

    assert not any(
        statement.startswith("ALTER TABLE receipt_history")
        for statement in session.statements
    )


def test_phase6_migration_accepts_existing_set_null_guard(monkeypatch):
    session = _Phase6Session()
    foreign_key = {
        "constrained_columns": ["payment_id"],
        "referred_table": "payments",
        "referred_columns": ["id"],
        "options": {"ondelete": "SET NULL"},
    }
    monkeypatch.setattr(
        migration_service,
        "inspect",
        lambda _connection: _Phase6Inspector([foreign_key]),
    )

    migration_service.ensure_phase6_financial_reconciliation_schema(session)

    assert session.statements == []


def test_phase6_migration_adds_and_verifies_set_null_guard(monkeypatch):
    session = _Phase6Session()
    foreign_key = {
        "constrained_columns": ["payment_id"],
        "referred_table": "payments",
        "referred_columns": ["id"],
        "options": {"ondelete": "SET NULL"},
    }
    inspectors = iter([_Phase6Inspector(), _Phase6Inspector([foreign_key])])
    monkeypatch.setattr(
        migration_service,
        "inspect",
        lambda _connection: next(inspectors),
    )

    migration_service.ensure_phase6_financial_reconciliation_schema(session)

    assert any("ON DELETE SET NULL" in statement for statement in session.statements)
