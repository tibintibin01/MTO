"""Desktop payment-preview tests with synthetic accounts and no live API."""

import sys
from pathlib import Path
from queue import SimpleQueue
from time import monotonic, sleep
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))
from ui import property as payment_ui

ORIGIN = {
    "id": 10,
    "td_number": "TEST-TD",
    "owner_name": "Synthetic owner",
    "assessed_value": 100000,
}
TARGET = ORIGIN | {"id": 11, "assessed_value": 130000}
PREVIEW = {
    "penalty_amount": 21.50,
    "discount_amount": 10,
    # Deliberately different from a local 2% estimate.
    "net_amount_due": 2191.50,
    "breakdown": "Synthetic server breakdown",
}


class Variable:
    def __init__(self, value=""):
        self.value = value
        self.changed = lambda: None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.changed()


class Widget:
    def __init__(self):
        self.text = ""
        self.state = None

    def configure(self, **values):
        self.__dict__.update(values)


@pytest.fixture
def form(monkeypatch):
    tasks = {}
    workers = []

    def after(delay, fn, *args):
        token = object()
        tasks[token] = lambda: fn(*args)
        return token

    d = SimpleNamespace(
        vars={
            key: Variable()
            for key in (
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
                "tax_year",
                "or_number",
                "or_date",
                "penalty",
                "discount",
                "amount_paid",
                "remarks",
                "duplicate_td_reason",
                "duplicate_td_reference",
            )
        },
        duplicate_td_var=Variable(),
        property_id=ORIGIN["id"],
        payment_mode=True,
        _payment_origin=ORIGIN,
        _payment_revision=0,
        _payment_preview_timer=None,
        _payment_poll_timer=None,
        _payment_preview_pending=False,
        _payment_results=SimpleQueue(),
        _payment_date_finished=False,
        _payment_net_due=None,
        _applying_payment_preview=False,
        _suggested_amount=False,
        _edited_adjustments=False,
        _compute_btn=Widget(),
        _compute_lbl=Widget(),
        total_lbl=Widget(),
        _payment_breakdown=Widget(),
        _field_entries_by_key={"penalty": Widget(), "discount": Widget()},
        save_btn=Widget(),
        after=after,
        after_cancel=tasks.pop,
        tasks=tasks,
        workers=workers,
    )
    modal = payment_ui.PropertyEditModal
    for name in (
        "_payment_preview_inputs",
        "_finish_payment_date",
        "_payment_input_changed",
        "_invalidate_payment_preview",
        "_clear_suggested_amount",
        "_queue_payment_preview",
        "_recalculate_payment",
        "_start_payment_preview",
        "_poll_payment_preview",
        "_apply_payment_preview",
        "_update_payment_preview_controls",
        "_payment_amount_changed",
        "_payment_can_save",
        "validate",
        "_apply_property_data",
    ):
        setattr(d, name, MethodType(getattr(modal, name), d))
    d._payment_number = modal._payment_number
    for key in ("tax_year", "or_number", "or_date"):
        d.vars[key].changed = lambda key=key: d._payment_input_changed(key)
    for key in ("penalty", "discount", "amount_paid"):
        d.vars[key].changed = lambda key=key: d._payment_amount_changed(key)
    d._apply_property_data(ORIGIN)

    def fake_thread(*, target, daemon):
        return SimpleNamespace(start=lambda: workers.append(target))

    d.resolve = Mock(return_value=ORIGIN)
    d.lookup = Mock(return_value=TARGET)
    d.compute = Mock(return_value=PREVIEW)
    d.post = Mock(side_effect=AssertionError("Preview must never post a payment"))
    monkeypatch.setattr(payment_ui.threading, "Thread", fake_thread)
    monkeypatch.setattr(payment_ui.prop_svc, "resolve_payment_target", d.resolve)
    monkeypatch.setattr(payment_ui.prop_svc, "get_property_by_id", d.lookup)
    monkeypatch.setattr(payment_ui.system_svc, "compute_payment", d.compute)
    monkeypatch.setattr(payment_ui.prop_svc, "save_property", d.post)
    return d


def enter_receipt(d, *, year="2027", date="11-10-2026"):
    d.vars["tax_year"].set(year)
    d.vars["or_number"].set("1234567")
    d.vars["or_date"].set(date)


def run_preview(d):
    d.tasks.pop(d._payment_preview_timer)()
    d.workers.pop(0)()
    d.tasks.pop(d._payment_poll_timer)()


def test_date_completion_uses_exact_server_result_and_never_posts(form):
    enter_receipt(form)
    assert not form.tasks  # No request while typing even a valid date.
    assert form.save_btn.state == "disabled"
    form._finish_payment_date()
    form._finish_payment_date()
    assert len(form.tasks) == 1
    run_preview(form)
    form.resolve.assert_called_once_with("TEST-TD", 2027, property_id=10)
    form.compute.assert_called_once_with(100000, 2027, "2026-11-10", property_id=10)
    assert form.vars["penalty"].get() == "21.50"
    assert form.vars["discount"].get() == "10.00"
    assert form.vars["amount_paid"].get() == "2191.50"
    assert form.total_lbl.text == "CALCULATED ANNUAL DUE: 2,191.50"
    assert form.save_btn.state == "normal"
    form.post.assert_not_called()


def test_out_of_order_inputs_queue_only_after_last_required_field(form):
    form.vars["or_date"].set("2026-11-10")
    form._finish_payment_date()
    form.vars["or_number"].set("1234567")
    form.vars["tax_year"].set("202")
    assert not form.tasks
    form.vars["tax_year"].set("2026")
    form.vars["tax_year"].set("2027")
    assert len(form.tasks) == 1
    run_preview(form)
    assert form.compute.call_args.args[1] == 2027


@pytest.mark.parametrize(
    ("year", "date"),
    [
        ("202", "2026-11-10"),
        ("²⁰²⁶-²⁰²⁷", "2026-11-10"),
        ("2027", "2026-02-30"),
        ("2027", ""),
    ],
)
def test_invalid_inputs_do_not_compute_or_allow_save(form, year, date):
    enter_receipt(form, year=year, date=date)
    form.vars["amount_paid"].set("500.00")
    form._finish_payment_date()
    form._recalculate_payment()
    payment_ui.PropertyEditModal.save(form)
    assert not form.tasks and not form.workers
    form.post.assert_not_called()
    assert form.save_btn.state == "disabled"


def test_partial_payment_survives_pending_result_and_date_recalculation(form):
    enter_receipt(form)
    form._finish_payment_date()
    form.tasks.pop(form._payment_preview_timer)()
    form.vars["amount_paid"].set("400.00")
    form.workers.pop()()
    form.tasks.pop(form._payment_poll_timer)()
    assert form.vars["amount_paid"].get() == "400.00"
    form.vars["or_date"].set("2026-12-01")
    assert form.vars["penalty"].get() == ""
    assert form.vars["discount"].get() == ""
    assert form.save_btn.state == "disabled"
    form._finish_payment_date()
    run_preview(form)
    assert form.vars["amount_paid"].get() == "400.00"
    assert "Amount Paid kept" in form._compute_lbl.text


def test_explicit_save_uses_verified_account_and_entered_cash(form, monkeypatch):
    form.resolve.return_value = TARGET
    enter_receipt(form)
    form.vars["amount_paid"].set("400.00")
    form._finish_payment_date()
    run_preview(form)
    form.post.assert_not_called()
    form._idempotency_key = "test-form-session-key"
    form.user = {"id": 1, "role": "cashier"}
    form.callback = Mock()
    form.destroy = Mock()
    form.on_saved = Mock()
    form.post.side_effect = None
    form.post.return_value = {
        "ok": True,
        "td_number": TARGET["td_number"],
        "property_id": TARGET["id"],
    }
    monkeypatch.setattr(
        payment_ui.prop_svc, "find_properties_by_td_number", Mock(return_value=[])
    )
    popup = Mock()
    monkeypatch.setattr(payment_ui.messagebox, "showinfo", popup)
    payment_ui.PropertyEditModal.save(form)
    form.post.assert_called_once()
    posted = form.post.call_args.args[0]
    assert posted["Amount Paid"] == "400.00"
    assert posted["OR Date"] == "2026-11-10"
    assert form.post.call_args.kwargs["editing_id"] == TARGET["id"]
    assert form.post.call_args.kwargs["idempotency_key"] == form._idempotency_key
    form.destroy.assert_called_once_with()
    record = form.on_saved.call_args.args[0]
    assert record.title == "Payment saved"
    assert record.property_id == TARGET["id"]
    assert "₱400.00" in record.detail
    popup.assert_not_called()
    form.callback.assert_not_called()


@pytest.mark.parametrize("lost_response", [True, False])
def test_save_feedback_keeps_payment_inputs_and_distinguishes_known_duplicate(
    form, monkeypatch, lost_response
):
    form.resolve.return_value = TARGET
    enter_receipt(form)
    form.vars["amount_paid"].set("400.00")
    form._finish_payment_date()
    run_preview(form)
    form._idempotency_key = "test-form-session-key"
    form.user = {"id": 1, "role": "cashier"}
    form.destroy = Mock()
    form.on_saved = Mock()
    form._show_save_feedback = Mock()
    form.post.side_effect = (
        TimeoutError()
        if lost_response
        else payment_ui.api.ApiResponseError(
            "Duplicate",
            status_code=409,
            detail="Payment already exists for OR 1234567, tax year 2027, and date 2026-11-10 (payment ID 402).",
        )
    )
    monkeypatch.setattr(
        payment_ui.prop_svc, "find_properties_by_td_number", Mock(return_value=[])
    )
    payment_ui.PropertyEditModal.save(form)

    feedback = form._show_save_feedback.call_args.args[0]
    form.destroy.assert_not_called()
    form.on_saved.assert_not_called()
    assert form.vars["amount_paid"].get() == "400.00"
    assert form.vars["or_number"].get() == "1234567"
    if lost_response:
        assert feedback.title == "Save not confirmed"
        assert form.save_btn.state == "disabled"
        payment_ui.PropertyEditModal.save(form)
        form.post.assert_called_once()
    else:
        assert feedback.title == "Payment already recorded"
        assert feedback.duplicate_id == 402
        assert "No new payment was saved" in feedback.detail
        assert form._show_save_feedback.call_args.kwargs["entry"] == (
            TARGET["id"],
            "1234567",
            "2026-11-10",
            ["2027"],
        )


def test_late_result_does_not_change_new_account_or_figures(form):
    enter_receipt(form)
    form._finish_payment_date()
    form.tasks.pop(form._payment_preview_timer)()
    old_worker = form.workers.pop()
    form.vars["tax_year"].set("2026")
    form.tasks.pop(form._payment_preview_timer)()

    form.resolve.return_value = TARGET
    form.workers.pop()()
    form.tasks.pop(form._payment_poll_timer)()
    form.lookup.assert_called_once_with(11, require_fresh=True)
    form.compute.assert_called_once_with(130000, 2026, "2026-11-10", property_id=11)
    assert form.property_id == 11

    form.vars["tax_year"].set("2025")
    assert form.property_id == 10
    assert not form.vars["amount_paid"].get()
    form.resolve.return_value = ORIGIN
    form.compute.return_value = PREVIEW | {"net_amount_due": 2000}
    form.tasks.pop(form._payment_preview_timer)()
    form.workers.pop()()
    form.resolve.return_value = TARGET
    form.compute.return_value = PREVIEW | {"net_amount_due": 5000}
    old_worker()
    form.tasks.pop(form._payment_poll_timer)()
    assert form.property_id == 10
    assert form.vars["amount_paid"].get() == "2000.00"
    assert all(call.kwargs["property_id"] == 10 for call in form.resolve.call_args_list)


@pytest.mark.parametrize("failure", ["resolve", "compute", "malformed"])
def test_failed_preview_stays_blocked_until_manual_retry(form, failure):
    enter_receipt(form)
    form._finish_payment_date()
    if failure == "malformed":
        form.compute.return_value = PREVIEW | {"net_amount_due": float("nan")}
    else:
        getattr(form, failure).side_effect = ConnectionError("unavailable")
    run_preview(form)
    assert form.save_btn.state == "disabled"
    assert form._compute_btn.state == "normal"
    assert "Could not calculate" in form._compute_lbl.text
    payment_ui.PropertyEditModal.save(form)
    form.post.assert_not_called()
    form.resolve.side_effect = form.compute.side_effect = None
    form.compute.return_value = PREVIEW
    form._recalculate_payment()
    form.workers.pop()()
    form.tasks.pop(form._payment_poll_timer)()
    assert form.save_btn.state == "normal"


def test_multi_year_receipt_does_not_reuse_single_year_suggestions(form):
    enter_receipt(form)
    form._finish_payment_date()
    run_preview(form)
    form.vars["tax_year"].set("2025-2027")
    assert form.vars["amount_paid"].get() == ""
    assert form.vars["penalty"].get() == ""
    assert form.vars["discount"].get() == ""
    assert form._compute_btn.state == "disabled"
    assert "manually" in form._compute_lbl.text
    assert form._field_entries_by_key["penalty"].state == "normal"
    form.vars["amount_paid"].set("4500")
    assert form.save_btn.state == "normal"
    assert not form.tasks
    assert form.compute.call_count == 1


def test_editing_adjustments_requires_review_of_suggested_cash(form):
    enter_receipt(form)
    form._finish_payment_date()
    run_preview(form)
    form.vars["discount"].set("15")
    assert form.vars["amount_paid"].get() == ""
    assert form.save_btn.state == "disabled"
    assert "before edits" in form.total_lbl.text
    form.vars["amount_paid"].set("450")
    form.vars["penalty"].set("20")
    assert form.vars["amount_paid"].get() == "450"
    assert form.save_btn.state == "normal"


def test_desktop_wires_or_date_focus_out_to_preview(monkeypatch):
    try:
        root = payment_ui.ctk.CTk()
    except payment_ui.tk.TclError:
        pytest.skip("Tk display unavailable")
    root.withdraw()
    dialog = None
    try:
        monkeypatch.setattr(
            payment_ui.prop_svc,
            "get_property_by_id",
            Mock(return_value=ORIGIN | {"tax_year": "2025", "or_number": "9999999"}),
        )
        monkeypatch.setattr(
            payment_ui.prop_svc, "resolve_payment_target", Mock(return_value=ORIGIN)
        )
        compute = Mock(return_value=PREVIEW)
        post = Mock(side_effect=AssertionError("Focus change must not post a payment"))
        monkeypatch.setattr(payment_ui.system_svc, "compute_payment", compute)
        monkeypatch.setattr(payment_ui.prop_svc, "save_property", post)
        dialog = payment_ui.PropertyEditModal(
            root, "Add Payment", 10, None, payment_mode=True
        )
        assert not dialog.vars["tax_year"].get()
        assert not dialog.vars["or_number"].get()
        assert dialog._field_entries_by_key["td_number"].cget("state") == "readonly"
        enter_receipt(dialog)
        root.update()
        compute.assert_not_called()
        dialog._field_entries_by_key["or_date"]._entry.event_generate("<FocusOut>")
        deadline = monotonic() + 3
        while dialog.save_btn.cget("state") == "disabled" and monotonic() < deadline:
            root.update()
            sleep(0.01)
        assert dialog.save_btn.cget("state") == "normal"
        compute.assert_called_once_with(100000, 2027, "2026-11-10", property_id=10)
        post.assert_not_called()
    finally:
        if dialog is not None:
            dialog.destroy()
        root.destroy()
