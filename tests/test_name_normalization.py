import asyncio

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property
from backend.routes.admin_tools import normalize_property_names
from backend.schemas import PropertySaveSchema, UserCreateSchema
from backend.services.import_service import DataCleanser
from utils.sanitizer import sanitize_string


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_sanitizer_decodes_repeated_entities_without_storing_html_escapes():
    assert sanitize_string("MUNICIPAL GOV&#x27;T OF DIPACULAO") == "MUNICIPAL GOV'T OF DIPACULAO"
    assert sanitize_string("SPS. DIONCO &amp;amp; ESTRELLA") == "SPS. DIONCO & ESTRELLA"
    assert sanitize_string("<b>JUAN</b> DELA CRUZ") == "JUAN DELA CRUZ"


def test_manual_and_import_inputs_store_plain_names():
    payload = PropertySaveSchema.model_validate({
        "TD Number": "06-0001-00001",
        "Owner Name": "A &amp; B",
        "Assessed Value": "1000",
    }).model_dump(by_alias=True)
    assert payload["Owner Name"] == "A & B"
    assert DataCleanser.to_str("GOV&#x27;T") == "GOV'T"

    password = "Keep&amp;<This>9!"
    user = UserCreateSchema(
        username="tester",
        full_name="Test User",
        password=password,
        role="viewer",
    )
    assert user.password == password


def test_admin_cleanup_previews_then_repairs_existing_names(db):
    prop = Property(
        td_number="06-0025-00001",
        owner_name="MUNICIPAL GOV&#x27;T OF DIPACULAO",
        payor_name="SPS. DIONCO &amp;amp; ESTRELLA",
        assessed_value=1000,
    )
    db.add(prop)
    db.commit()

    preview = asyncio.run(normalize_property_names(
        dry_run=True,
        current_user={"id": 1, "username": "admin"},
        db_session=db,
    ))
    assert preview["properties_affected"] == 1
    assert preview["fields_changed"] == 2
    db.refresh(prop)
    assert prop.owner_name == "MUNICIPAL GOV&#x27;T OF DIPACULAO"

    applied = asyncio.run(normalize_property_names(
        dry_run=False,
        current_user={"id": 1, "username": "admin"},
        db_session=db,
    ))
    assert applied["properties_affected"] == 1
    assert applied["fields_changed"] == 2
    db.refresh(prop)
    assert prop.owner_name == "MUNICIPAL GOV'T OF DIPACULAO"
    assert prop.payor_name == "SPS. DIONCO & ESTRELLA"
