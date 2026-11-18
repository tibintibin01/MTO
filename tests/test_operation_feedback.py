"""Synthetic tests for feedback around writes. No real accounts or API calls."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))

from api_clients.api_helper import ApiResponseError
from api_clients import api_helper
from ui import ledger, property as property_ui
from ui.accessibility import contrast_ratio
from ui.operation_feedback import PALETTES, SavedRecord, save_failure_feedback


def test_http_conflict_keeps_legacy_message_and_exposes_status(monkeypatch):
    response = requests.Response()
    response.status_code = 409
    response._content = b'{"detail":"This Official Receipt is already recorded for the selected property and tax year."}'
    monkeypatch.setattr(api_helper, "_SESSION_TOKEN", None)
    monkeypatch.setattr(api_helper.requests, "request", Mock(return_value=response))
    with pytest.raises(ApiResponseError) as raised:
        api_helper.api_request("PUT", "/properties/18", data={})
    assert str(raised.value) == f"Error: {raised.value.detail}"
    assert raised.value.status_code == 409
    assert (
        save_failure_feedback(raised.value, payment=True).title
        == "Payment already recorded"
    )


def test_payment_delete_confirmation_does_not_operate_on_a_changed_selection(
    monkeypatch,
):
    page = object.__new__(ledger.LedgerPage)
    page.container = Mock()
    page.tree = Mock()
    page.tree.selection.side_effect = [("first",), ("second",)]
    page.tree.item.return_value = {"values": [10, "2026-11-01", "TEST-OR"]}
    confirm = Mock(return_value=True)
    delete = Mock()
    monkeypatch.setattr(ledger, "confirm_action", confirm)
    monkeypatch.setattr(ledger.payment, "delete_payment", delete)
    page.delete_payment()
    assert confirm.call_args.kwargs == {"action": "Delete Payment", "destructive": True}
    delete.assert_not_called()


@pytest.mark.parametrize("conflict", [False, True])
def test_assessment_save_uses_existing_version_and_keeps_edits_on_conflict(
    monkeypatch, conflict
):
    data = dict.fromkeys(
        (
            "td_number",
            "owner_name",
            "pin",
            "lot_number",
            "area",
            "location",
            "kind_of_property",
            "prev_td_number",
            "effectivity_date",
            "assessed_value",
            "prior_assessed_value",
            "prior_effectivity_year",
        ),
        "",
    )
    data.update(
        td_number="SYNTHETIC", owner_name="Synthetic Owner", assessed_value="25000"
    )
    form = SimpleNamespace(
        vars={k: SimpleNamespace(get=lambda value=v: value) for k, v in data.items()},
        payment_mode=False,
        property_id=18,
        _loaded_version=4,
        _original_prev_td="",
        _original_td="SYNTHETIC",
        _loaded_duplicate_verified=False,
        _selected_previous_property_id=None,
        user={"role": "encoder"},
        on_saved=Mock(),
        destroy=Mock(),
        save_btn=Mock(),
        _show_save_feedback=Mock(),
    )
    save_property = Mock(return_value={"ok": True, "property_id": 18, "new_version": 5})
    if conflict:
        save_property.side_effect = ApiResponseError(
            "Conflict",
            status_code=409,
            detail="This property was changed after you opened it.",
        )
    monkeypatch.setattr(
        property_ui.prop_svc, "find_properties_by_td_number", Mock(return_value=[])
    )
    monkeypatch.setattr(property_ui.prop_svc, "save_property", save_property)
    monkeypatch.setattr(
        property_ui.messagebox,
        "showinfo",
        Mock(side_effect=AssertionError("No routine popup")),
    )
    property_ui.PropertyEditModal.save(form)
    assert save_property.call_args.args[0]["version"] == 4
    assert save_property.call_args.kwargs["editing_id"] == 18
    if conflict:
        form.destroy.assert_not_called()
        form.on_saved.assert_not_called()
        assert form.vars["assessed_value"].get() == "25000"
        assert "since you opened" in form._show_save_feedback.call_args.args[0].title
    else:
        form.destroy.assert_called_once_with()
        form.on_saved.assert_called_once_with(
            SavedRecord("Property updated", "TD SYNTHETIC", 18, "SYNTHETIC")
        )


@pytest.mark.parametrize("status", [500, 502, 503, 504, "N/A"])
def test_uncertain_server_responses_do_not_claim_nothing_was_saved(status):
    error = ApiResponseError("Failed", status_code=status, detail="internal detail")
    feedback = save_failure_feedback(error, payment=True)
    assert feedback.uncertain
    assert "Check the ledger" in feedback.detail
    assert "internal detail" not in feedback.detail


@pytest.mark.parametrize(
    "detail",
    [
        "An identical financial operation is already being processed. Retry shortly.",
        "This idempotency key was already used for different request data.",
    ],
)
def test_in_flight_or_reused_payment_keys_are_not_a_duplicate_receipt(detail):
    error = ApiResponseError("Conflict", status_code=409, detail=detail)
    feedback = save_failure_feedback(error, payment=True)
    assert feedback.uncertain
    assert feedback.duplicate_id is None


def test_assessment_error_targets_assessed_value_and_retains_conflict_guidance():
    error = ApiResponseError(
        "Validation",
        status_code=422,
        detail="Request validation failed.",
        errors=[{"loc": ["body", "Assessed Value"], "input": "do not echo"}],
    )
    feedback = save_failure_feedback(error, payment=False)
    assert feedback.field == "assessed_value"
    assert "do not echo" not in feedback.detail
    conflict = save_failure_feedback(
        ApiResponseError(
            "409",
            status_code=409,
            detail="This property was changed after you opened it.",
        ),
        payment=False,
    )
    assert "Review the current property" in conflict.detail


def test_receipt_constraint_without_id_does_not_guess_existing_payment():
    error = ApiResponseError(
        "Duplicate",
        status_code=409,
        detail="This Official Receipt is already recorded for the selected property and tax year.",
    )
    feedback = save_failure_feedback(error, payment=True)
    assert feedback.title == "Payment already recorded"
    assert feedback.duplicate_id is None
    assert not feedback.uncertain


@pytest.mark.parametrize("matching", [True, False])
def test_view_existing_payment_requires_exact_account_and_receipt(
    monkeypatch, matching
):
    error = ApiResponseError(
        "Duplicate",
        status_code=409,
        detail="Payment already exists for OR 10, tax year 2027, and date 2026-11-01 (payment ID 30).",
    )
    duplicate = save_failure_feedback(error, payment=True)
    scheduled = []
    form = SimpleNamespace(
        _save_feedback=duplicate,
        _duplicate_check_timer=None,
        _save_banner=Mock(),
        after=lambda _delay, callback: scheduled.append(callback) or "timer",
    )
    get_details = Mock(
        return_value={
            "property_id": 18 if matching else 19,
            "payment_id": 30,
            "or_number": "10",
            "tax_year": "2027",
            "date_paid": "2026-11-01T09:00:00",
            "amount": "850.50",
        }
    )
    monkeypatch.setattr(
        property_ui.payment_svc, "get_payment_receipt_details", get_details
    )
    monkeypatch.setattr(
        property_ui.threading,
        "Thread",
        lambda *, target, daemon: SimpleNamespace(start=target),
    )
    property_ui.PropertyEditModal._view_duplicate_payment(
        form, duplicate, (18, "10", "2026-11-01", ["2027"])
    )
    scheduled.pop()()
    get_details.assert_called_once_with(30, require_fresh=True)
    message = form._save_banner.show.call_args.args[2]
    assert (
        ("₱850.50" in message and "Account #18" in message)
        if matching
        else "could not be verified" in message
    )
    assert "Account #19" not in message


@pytest.mark.parametrize("refresh_succeeds", [True, False])
def test_saved_ledger_loads_server_selected_account_and_preserves_confirmed_outcome(
    monkeypatch, refresh_succeeds
):
    page = object.__new__(ledger.LedgerPage)
    page._record_feedback = Mock()
    page.is_loading = False
    page.search_btn = Mock()
    page.tree = Mock()
    page.tree.get_children.return_value = ()
    page._set_empty_state = Mock()
    page._update_ui = Mock()
    page.container = SimpleNamespace(
        after=lambda _delay, callback, *args: callback(*args)
    )
    get_ledger = Mock(return_value=[[300, "2026-11-01", "10", "2027"]])
    if not refresh_succeeds:
        get_ledger.side_effect = OSError
    monkeypatch.setattr(ledger.payment, "get_payment_ledger", get_ledger)
    monkeypatch.setattr(
        ledger.threading,
        "Thread",
        lambda *, target, daemon: SimpleNamespace(start=target),
    )
    monkeypatch.setattr(
        ledger,
        "LoadingOverlay",
        Mock(side_effect=AssertionError("Post-save feedback should not open a window")),
    )
    page._on_payment_saved(SavedRecord("Payment saved", "OR 10", 18, "SYNTHETIC TD"))
    get_ledger.assert_called_once_with(property_id=18, require_fresh=True)
    if refresh_succeeds:
        assert page._update_ui.call_args.args[2]["property_id"] == 18
        assert page._record_feedback.show.call_args.args[:2] == (
            "success",
            "Payment saved",
        )
    else:
        page._update_ui.assert_not_called()
        state, title, text = page._record_feedback.show.call_args.args
        assert (state, title) == ("warning", "Payment saved")
        assert "do not enter it again" in text


@pytest.mark.parametrize("level", list(PALETTES))
def test_contrast_is_readable_in_both_modes(level):
    backgrounds, accents, _ = PALETTES[level]
    assert all(
        contrast_ratio(text, background) >= 4.5
        for background, text in zip(backgrounds, accents)
    )
