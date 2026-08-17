from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import AuditLog, Property
from backend.models_portfolio import PropertyPortfolioLink
from backend.services import portfolio_service


USER = {"id": 7, "username": "portfolio_admin", "role": "admin"}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
    )()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _make_property(db, td_number, **values):
    prop = Property(
        td_number=td_number,
        owner_name=values.pop("owner_name", "TEST OWNER"),
        barangay=values.pop("barangay", "LIPIT"),
        kind_of_property=values.pop("kind_of_property", "RESIDENTIAL"),
        assessed_value=values.pop("assessed_value", Decimal("125000.00")),
        **values,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def test_create_link_and_list_portfolio_with_audit_trail(db):
    prop = _make_property(db, "06-0017-09001")

    created = portfolio_service.create_portfolio(
        "Acme Holdings",
        USER,
        db_session=db,
    )
    linked = portfolio_service.link_property(
        created["id"],
        prop.id,
        USER,
        db_session=db,
    )

    assert linked["name"] == "Acme Holdings"
    assert linked["property_count"] == 1
    assert linked["properties"][0]["property_id"] == prop.id
    assert linked["properties"][0]["td_number"] == prop.td_number

    listed = portfolio_service.list_portfolios(db_session=db)
    assert [(item["name"], item["property_count"]) for item in listed] == [
        ("Acme Holdings", 1)
    ]

    actions = [
        row.action
        for row in db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    ]
    assert actions == ["CREATE", "LINK_PROPERTY"]


def test_one_property_cannot_be_linked_to_two_portfolios(db):
    prop = _make_property(db, "06-0017-09002")
    first = portfolio_service.create_portfolio(
        "First Folder",
        USER,
        db_session=db,
    )
    second = portfolio_service.create_portfolio(
        "Second Folder",
        USER,
        db_session=db,
    )
    portfolio_service.link_property(
        first["id"],
        prop.id,
        USER,
        db_session=db,
    )

    with pytest.raises(
        portfolio_service.PortfolioConflictError,
        match="already linked",
    ):
        portfolio_service.link_property(
            second["id"],
            prop.id,
            USER,
            db_session=db,
        )

    assert db.query(PropertyPortfolioLink).count() == 1


def test_deactivate_retains_links_and_blocks_new_links(db):
    first_prop = _make_property(db, "06-0017-09003")
    second_prop = _make_property(db, "06-0017-09004")
    portfolio = portfolio_service.create_portfolio(
        "Inactive Test",
        USER,
        db_session=db,
    )
    portfolio_service.link_property(
        portfolio["id"],
        first_prop.id,
        USER,
        db_session=db,
    )

    deactivated = portfolio_service.update_portfolio(
        portfolio["id"],
        is_active=False,
        user=USER,
        db_session=db,
    )
    assert deactivated["is_active"] is False
    assert deactivated["property_count"] == 1
    assert portfolio_service.list_portfolios(db_session=db) == []
    assert len(
        portfolio_service.list_portfolios(
            include_inactive=True,
            db_session=db,
        )
    ) == 1

    with pytest.raises(
        portfolio_service.PortfolioValidationError,
        match="Reactivate",
    ):
        portfolio_service.link_property(
            portfolio["id"],
            second_prop.id,
            USER,
            db_session=db,
        )

    assert db.query(PropertyPortfolioLink).count() == 1


def test_unlink_changes_only_association_not_property_record(db):
    prop = _make_property(
        db,
        "06-0017-09005",
        owner_name="ORIGINAL OWNER",
        assessed_value=Decimal("456789.25"),
        lot_number="LOT-17",
    )
    portfolio = portfolio_service.create_portfolio(
        "Non Destructive",
        USER,
        db_session=db,
    )
    portfolio_service.link_property(
        portfolio["id"],
        prop.id,
        USER,
        db_session=db,
    )

    result = portfolio_service.unlink_property(
        portfolio["id"],
        prop.id,
        USER,
        db_session=db,
    )

    db.expire_all()
    unchanged = db.get(Property, prop.id)
    assert result["property_count"] == 0
    assert db.query(PropertyPortfolioLink).count() == 0
    assert unchanged.td_number == "06-0017-09005"
    assert unchanged.owner_name == "ORIGINAL OWNER"
    assert unchanged.assessed_value == Decimal("456789.25")
    assert unchanged.lot_number == "LOT-17"
    assert unchanged.deleted_at is None


@pytest.mark.parametrize(
    "state",
    [
        {"deleted_at": datetime.now(timezone.utc)},
        {"archived": True},
    ],
)
def test_deleted_or_archived_property_cannot_be_newly_linked(db, state):
    prop = _make_property(db, f"06-0017-09{len(state)}06", **state)
    portfolio = portfolio_service.create_portfolio(
        f"Restricted {len(state)}",
        USER,
        db_session=db,
    )

    with pytest.raises(
        portfolio_service.PortfolioNotFoundError,
        match="Active property not found",
    ):
        portfolio_service.link_property(
            portfolio["id"],
            prop.id,
            USER,
            db_session=db,
        )

    assert db.query(PropertyPortfolioLink).count() == 0


def test_portfolio_names_are_unique_case_insensitively(db):
    portfolio_service.create_portfolio(
        "Municipal Holdings",
        USER,
        db_session=db,
    )

    with pytest.raises(portfolio_service.PortfolioConflictError):
        portfolio_service.create_portfolio(
            "municipal holdings",
            USER,
            db_session=db,
        )
