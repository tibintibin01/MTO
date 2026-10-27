"""Year-aware account counts use synthetic data and never rewrite TD history."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from backend.database import Base
from backend.models import Property, PropertyAssessmentHistory, PropertyBilling, Payment
from backend.services.property_status_service import (
    classify_property_records,
    current_property_tax_year,
    get_property_status_counts,
)
from backend.services.system_service import get_dashboard_summary
from ui.property_status_display import validated_property_status


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def row(pid, year=2024, previous=None, previous_td=None, deleted=False, td=None):
    return {
        "id": pid,
        "td_number": td or f"TD-{pid}",
        "effectivity_date": str(year) if year is not None else None,
        "tax_year": str(year) if year is not None else None,
        "previous_property_id": previous,
        "prev_td_number": previous_td,
        "deleted_at": datetime(2026, 1, 1) if deleted else None,
    }


def classify(rows, year=2026, history=()):
    value = classify_property_records(rows, history, as_of_year=year)
    assert (
        sum(
            value[k]
            for k in (
                "active",
                "inactive_replaced",
                "future_effective",
                "archived",
                "needs_review",
            )
        )
        == value["total_records"]
    )
    assert value["registered_records"] + value["archived"] == value["total_records"]
    return value


def test_one_for_one_2027_replacement_keeps_one_active_and_preserves_both_records():
    records = [row(1), row(2, 2027, previous=1, previous_td="TD-1")]
    before = [dict(r) for r in records]
    this_year = classify(records)
    next_year = classify(records, 2027)
    assert (
        this_year["active"],
        this_year["inactive_replaced"],
        this_year["future_effective"],
    ) == (1, 0, 1)
    assert (
        next_year["active"],
        next_year["inactive_replaced"],
        next_year["future_effective"],
    ) == (1, 1, 0)
    assert records == before


def test_unique_legacy_previous_td_link_is_supported_case_insensitively():
    value = classify([row(1), row(2, 2025, previous_td=" td-1 ")])
    assert value["active"] == 1 and value["inactive_replaced"] == 1


def test_duplicate_td_accounts_remain_distinct_and_explicit_id_replaces_only_one():
    value = classify(
        [
            row(1, td="SHARED"),
            row(2, td="SHARED"),
            row(3, 2025, previous=1, previous_td="SHARED"),
        ]
    )
    assert value["active"] == 2 and value["inactive_replaced"] == 1


def test_ambiguous_legacy_link_is_review_not_a_guessed_replacement():
    value = classify(
        [row(1, td="SHARED"), row(2, td="SHARED"), row(3, 2025, previous_td="SHARED")]
    )
    assert value["needs_review"] == 3 and value["inactive_replaced"] == 0


def test_future_ambiguous_link_does_not_hide_current_parents():
    value = classify(
        [row(1, td="SHARED"), row(2, td="SHARED"), row(3, 2027, previous_td="SHARED")]
    )
    assert value["active"] == 2 and value["needs_review"] == 1


def test_archive_is_separate_and_archived_successor_cannot_replace_live_parent():
    value = classify([row(1), row(2, 2025, previous=1, deleted=True)])
    assert (
        value["active"] == 1
        and value["archived"] == 1
        and value["inactive_replaced"] == 0
    )


def test_explicit_link_to_archived_predecessor_keeps_traceable_active_successor():
    value = classify([row(1, deleted=True), row(2, 2025, previous=1)])
    assert value["active"] == 1 and value["archived"] == 1


def test_split_has_two_active_successors_not_an_incorrect_one_for_one_collapse():
    value = classify([row(1), row(2, 2025, previous=1), row(3, 2025, previous=1)])
    assert value["active"] == 2 and value["inactive_replaced"] == 1


def test_successive_future_replacements_switch_only_at_their_tax_year():
    rows = [row(1), row(2, 2027, previous=1), row(3, 2028, previous=2)]
    assert classify(rows)["future_effective"] == 2
    assert classify(rows, 2027)["inactive_replaced"] == 1
    assert classify(rows, 2028)["inactive_replaced"] == 2
    assert all(classify(rows, y)["active"] == 1 for y in (2026, 2027, 2028))


@pytest.mark.parametrize(
    "records",
    [
        [row(1, previous=1)],
        [row(1, previous=99)],
        [row(1, previous=2), row(2, previous=1)],
        [row(1, 2027), row(2, 2026, previous=1)],
        [row(1), row(2, 2025, previous=1, previous_td="WRONG")],
    ],
)
def test_invalid_lineage_is_not_silently_reported_as_valid_active(records):
    value = classify(records)
    assert value["needs_review"] >= 1
    assert value["inactive_replaced"] == 0


def test_undated_archived_successor_cannot_make_live_parent_uncertain():
    value = classify([row(1), row(2, None, previous=1, deleted=True)])
    assert value["active"] == 1 and value["archived"] == 1
    assert value["needs_review"] == 0


def test_missing_td_identity_needs_review_even_when_year_is_present():
    record = row(1)
    record["td_number"] = " "
    assert classify([record])["needs_review"] == 1


def test_unknown_effectivity_is_review_not_future_or_deleted():
    record = row(1, None)
    record["effectivity_date"] = "unknown"
    value = classify([record])
    assert (
        value["needs_review"] == 1 and value["active"] == value["future_effective"] == 0
    )


def test_own_history_is_preserved_but_uncertain_replacement_is_not_backdated():
    history = [{"property_id": 2, "tax_year": "2024"}]
    same_td = classify([row(2, 2027)], history=history)
    assert same_td["active"] == 1
    new_td = classify([row(1), row(2, 2027, previous=1)], history=history)
    assert new_td["needs_review"] == 2
    assert new_td["inactive_replaced"] == 0
    next_year = classify([row(1), row(2, 2027, previous=1)], 2027, history=history)
    assert next_year["active"] == 1 and next_year["inactive_replaced"] == 1


def test_undated_successor_does_not_make_a_potentially_replaced_parent_look_active():
    value = classify([row(1), row(2, None, previous=1)])
    assert value["needs_review"] == 2 and value["active"] == 0


def test_history_does_not_make_a_td_active_before_any_known_year():
    history = [{"property_id": 2, "tax_year": "2027"}]
    value = classify([row(1), row(2, 2028, previous=1)], 2026, history=history)
    assert value["active"] == 1 and value["future_effective"] == 1


def test_external_previous_td_reference_does_not_invent_or_hide_a_local_record():
    value = classify([row(1, previous_td="OFFICE-LEDGER-ONLY")])
    assert value["active"] == 1 and value["external_previous_td_references"] == 1


def test_long_chain_is_linear_and_does_not_hit_recursion_limit():
    rows = [row(pid, previous=pid - 1 if pid > 1 else None) for pid in range(1, 3001)]
    value = classify(rows)
    assert value["active"] == 1 and value["inactive_replaced"] == 2999


@pytest.mark.parametrize("year", [None, True, "2027", 1899, 2300])
def test_invalid_explicit_as_of_year_is_not_coerced(year):
    with pytest.raises(ValueError):
        classify_property_records([], [], as_of_year=year)


def add_replacement(db):
    old = Property(
        td_number="OLD-TEST",
        owner_name="SYNTHETIC",
        assessed_value=1000,
        effectivity_date="2024-01-01",
        tax_year="2024",
    )
    db.add(old)
    db.flush()
    new = Property(
        td_number="NEW-TEST",
        owner_name="SYNTHETIC",
        assessed_value=2000,
        effectivity_date="2027-01-01",
        tax_year="2027",
        previous_property_id=old.id,
        prev_td_number=old.td_number,
    )
    db.add(new)
    db.commit()
    return old, new


def test_database_count_read_issues_only_select_and_never_flushes_or_commits(db):
    old, new = add_replacement(db)
    pending = Property(td_number="UNSAVED", owner_name="SYNTHETIC", assessed_value=1000)
    db.add(pending)
    statements = []

    def reject_writes(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert statement.lstrip().upper().startswith("SELECT")

    event.listen(db.get_bind(), "before_cursor_execute", reject_writes)
    try:
        with patch.object(db, "commit") as commit, patch.object(db, "flush") as flush:
            value = get_property_status_counts(db, as_of_year=2026)
            commit.assert_not_called()
            flush.assert_not_called()
        assert value["total_records"] == 2 and value["future_effective"] == 1
        assert pending.id is None and len(statements) == 2
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", reject_writes)


def test_td_billing_payment_and_assessment_history_are_unchanged(db):
    old, new = add_replacement(db)
    db.add(
        PropertyBilling(
            property_id=old.id, tax_year=2024, assessed_value=1000, amount_paid=20
        )
    )
    db.add(
        Payment(
            property_id=old.id,
            amount=20,
            tax_year="2024",
            or_number="TEST-OR",
            posted_by="test",
        )
    )
    db.add(
        PropertyAssessmentHistory(
            property_id=new.id, tax_year="2024", assessed_value=1000, changed_by="test"
        )
    )
    db.commit()
    tables = [
        Property.__table__,
        PropertyBilling.__table__,
        Payment.__table__,
        PropertyAssessmentHistory.__table__,
    ]
    before = [db.execute(select(table)).all() for table in tables]
    result = get_property_status_counts(db, as_of_year=2027)
    assert result["active"] == 1 and result["inactive_replaced"] == 1
    assert [db.execute(select(table)).all() for table in tables] == before
    assert db.get(Property, old.id).td_number == "OLD-TEST"


def test_dashboard_rollover_bypasses_fresh_legacy_cache(db, monkeypatch):
    add_replacement(db)
    monkeypatch.setattr(
        "backend.services.property_status_service.current_property_tax_year",
        lambda: 2026,
    )
    before = get_dashboard_summary(db_session=db)
    monkeypatch.setattr(
        "backend.services.property_status_service.current_property_tax_year",
        lambda: 2027,
    )
    after = get_dashboard_summary(db_session=db)
    assert before["total_properties"] == after["total_properties"] == 2  # compatibility
    assert before["property_status_counts"]["future_effective"] == 1
    assert after["property_status_counts"]["inactive_replaced"] == 1
    assert after["property_status_counts"]["active"] == 1
    assert after["property_status_counts"]["as_of_tax_year"] == 2027


def valid_payload():
    return {"property_status_counts": classify([row(1), row(2, 2027, previous=1)])}


def test_display_contract_never_uses_legacy_registered_total_as_active():
    assert validated_property_status({"total_properties": 1234}) is None
    assert validated_property_status(valid_payload())["active"] == 1


@pytest.mark.parametrize(
    "key, value",
    [
        ("active", True),
        ("active", -1),
        ("active", "1"),
        ("active", 1.5),
        ("format_version", True),
        ("format_version", 2),
        ("total_records", 999),
        ("registered_records", 999),
        ("as_of_tax_year", "2027"),
    ],
)
def test_display_rejects_inconsistent_or_invalid_counts(key, value):
    payload = valid_payload()
    payload["property_status_counts"][key] = value
    assert validated_property_status(payload) is None


def test_property_clock_uses_philippine_tax_year():
    class NewYear:
        @staticmethod
        def now(tz):
            assert tz.utcoffset(None).total_seconds() == 8 * 3600
            return datetime(2026, 12, 31, 16, 0, tzinfo=timezone.utc).astimezone(tz)

    with patch("backend.services.property_status_service.datetime", NewYear):
        assert current_property_tax_year() == 2027
