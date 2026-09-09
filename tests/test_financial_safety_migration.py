import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.services.migration_service import (
    ensure_financial_safety_schema,
    financial_invariant_violations,
)


@pytest.fixture()
def migration_db():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE payments ("
                "id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL,"
                "or_number TEXT, tax_year TEXT, amount NUMERIC NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE property_billings ("
                "id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE payment_billings ("
                "id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL,"
                "billing_id INTEGER NOT NULL, amount_paid NUMERIC NOT NULL)"
            )
        )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_financial_invariant_preflight_passes_balanced_data(migration_db):
    migration_db.execute(
        text(
            "INSERT INTO payments VALUES "
            "(1, 10, 'OR-1', '2026', 100),"
            "(2, 20, 'OR-1', '2026', 75)"
        )
    )
    migration_db.execute(
        text("INSERT INTO property_billings VALUES (100, 10), (200, 20)")
    )
    migration_db.execute(
        text("INSERT INTO payment_billings VALUES " "(1, 1, 100, 100), (2, 2, 200, 75)")
    )

    assert financial_invariant_violations(migration_db) == {
        "duplicate_payment_identity": 0,
        "duplicate_payment_allocations": 0,
        "cross_property_allocations": 0,
        "unbalanced_payment_allocations": 0,
    }


def test_financial_invariant_preflight_reports_each_corruption_type(migration_db):
    migration_db.execute(
        text(
            "INSERT INTO payments VALUES "
            "(1, 10, 'OR-DUP', '2026', 100),"
            "(2, 10, 'or-dup', '2026', 100),"
            "(3, 30, 'OR-CROSS', '2026', 50)"
        )
    )
    migration_db.execute(
        text("INSERT INTO property_billings VALUES (100, 10), (300, 99)")
    )
    migration_db.execute(
        text(
            "INSERT INTO payment_billings VALUES "
            "(1, 1, 100, 60),"
            "(2, 1, 100, 40),"
            "(3, 3, 300, 50)"
        )
    )

    violations = financial_invariant_violations(migration_db)

    assert violations["duplicate_payment_identity"] == 1
    assert violations["duplicate_payment_allocations"] == 1
    assert violations["cross_property_allocations"] == 1
    assert violations["unbalanced_payment_allocations"] == 1


def test_duplicate_identity_check_matches_nullable_unique_index(migration_db):
    migration_db.execute(
        text(
            "INSERT INTO payments VALUES "
            "(1, 10, '', '2026', 0),"
            "(2, 10, '', '2026', 0),"
            "(3, 20, NULL, '2026', 0),"
            "(4, 20, NULL, '2026', 0),"
            "(5, 30, 'OR-X', NULL, 0),"
            "(6, 30, 'OR-X', NULL, 0)"
        )
    )

    violations = financial_invariant_violations(migration_db)

    # Blank non-null values collide in the unique index. NULL components do
    # not, so the preflight must neither miss the former nor block the latter.
    assert violations["duplicate_payment_identity"] == 1
    assert violations["unbalanced_payment_allocations"] == 0


def test_schema_activation_refuses_non_mariadb(migration_db):
    with pytest.raises(RuntimeError, match="requires MariaDB"):
        ensure_financial_safety_schema(migration_db)
