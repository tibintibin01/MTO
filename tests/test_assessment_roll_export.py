# -*- coding: utf-8 -*-
"""Regression tests for Assessment Roll export batching."""

from backend.routes import billing


def test_fetch_all_assessment_roll_items_reads_past_first_batch(monkeypatch):
    calls = []
    pages = {
        None: [(5, "TD-5"), (4, "TD-4")],
        4: [(3, "TD-3"), (2, "TD-2")],
        2: [(1, "TD-1")],
    }

    def fake_search_properties(*args, **kwargs):
        calls.append(kwargs.copy())
        return pages[kwargs.get("cursor")]

    monkeypatch.setattr(billing.prop_svc, "search_properties", fake_search_properties)

    rows = billing._fetch_all_assessment_roll_items(
        db_session=object(),
        barangay="BAYABAS",
        as_of_year=2026,
        batch_size=2,
    )

    assert [row[1] for row in rows] == ["TD-5", "TD-4", "TD-3", "TD-2", "TD-1"]
    assert [call["cursor"] for call in calls] == [None, 4, 2]
    assert all(call["barangay"] == "BAYABAS" for call in calls)
    assert all(call["as_of_year"] == 2026 for call in calls)
