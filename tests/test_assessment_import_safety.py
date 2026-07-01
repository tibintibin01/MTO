import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, PropertyAssessmentHistory
from backend.services.import_service import (
    commit_assessment_import,
    validate_assessment_import,
)
from ui.dossier import PropertyDossierModal


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def test_assessment_validation_rejects_zero_value():
    db = _session()
    content = b"TD NUMBER,PROPERTY OWNER,ASSESSED VALUE\n06-0004-00024,TEST OWNER,0\n"

    result = validate_assessment_import(content, ".csv", db_session=db)

    assert result["success"] is True
    assert result["valid_rows"] == 0
    assert "greater than zero" in result["report"][0]["message"]


def test_unchanged_assessment_import_does_not_duplicate_history(monkeypatch):
    db = _session()
    prop = Property(
        td_number="06-0004-00024",
        owner_name="TEST OWNER",
        assessed_value=9_170,
        effectivity_date="2023-01-01",
        version=1,
    )
    db.add(prop)
    db.commit()

    monkeypatch.setattr(
        "backend.services.system_service.log_action",
        lambda *_args, **_kwargs: None,
    )

    class _CompletedFuture:
        pass

    def _run_coroutine(coro, _loop):
        coro.close()
        return _CompletedFuture()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _run_coroutine)

    result = commit_assessment_import(
        [{
            "td_number": prop.td_number,
            "owner_name": prop.owner_name,
            "assessed_value": 9_170,
            "location": "",
            "kind_of_property": "",
            "pin": "",
            "tax_year": "",
            "area": "",
            "lot_number": "",
            "block_number": "",
        }],
        {"id": 1, "username": "tester"},
        db_session=db,
    )

    assert result == {"inserted": 0, "updated": 1, "failed": 0, "failed_rows": []}
    assert db.query(PropertyAssessmentHistory).count() == 0
    db.refresh(prop)
    assert float(prop.assessed_value) == 9_170


def test_invalid_assessment_row_cannot_erase_existing_value(monkeypatch):
    db = _session()
    prop = Property(
        td_number="06-0004-00024",
        owner_name="TEST OWNER",
        assessed_value=9_170,
        effectivity_date="2023-01-01",
        version=1,
    )
    db.add(prop)
    db.commit()

    monkeypatch.setattr(
        "backend.services.system_service.log_action",
        lambda *_args, **_kwargs: None,
    )

    result = commit_assessment_import(
        [{"td_number": prop.td_number, "assessed_value": 0}],
        {"id": 1, "username": "tester"},
        db_session=db,
    )

    assert result["failed"] == 1
    db.refresh(prop)
    assert float(prop.assessed_value) == 9_170


def test_dossier_collapses_identical_assessment_history_rows():
    modal = object.__new__(PropertyDossierModal)
    repeated = {
        "td_number": "06-0004-00024",
        "assessed_value": 9_170,
        "kind": "AGRICULTURAL LAND",
        "tax_year": "",
        "change_reason": "Import Update",
    }
    modal.data = {
        "payments": [],
        "ancestry": [],
        "assessment_history": [
            {**repeated, "date": "2026-05-26"},
            {**repeated, "date": "2026-05-19"},
        ],
    }

    events = modal._build_events()

    assert len(events) == 1
    assert events[0]["subtitle"] == "Historical value: P 9,170.00"
