"""Headless desktop regressions: no GUI, production data, download or cloud."""

from queue import Queue
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ui.tax_bill import TaxBillDialog, tax_bill_year, validate_candidates


def candidate(pid=8):
    return dict(
        id=pid,
        td_number="SYNTHETIC-TD",
        owner_name="SYNTHETIC OWNER",
        pin="PIN-X",
        lot_number="LOT-X",
        block_number="",
        location="TEST",
        barangay="TEST",
        effectivity="2027-01-01",
    )


def page(*ids, more=False):
    return {
        "items": [candidate(pid) for pid in ids],
        "has_more": more,
        "next_cursor": ids[-1] if more and ids else None,
    }


def dialog():
    d = SimpleNamespace(
        closed=False,
        busy=False,
        request_id=1,
        results=Queue(),
        items={"8": candidate()},
        next_cursor=None,
        loaded_term="SYNTHETIC",
        preferred_id=None,
        search_var=Mock(),
        year_var=Mock(),
        tree=Mock(),
        status=Mock(),
        selected_label=Mock(),
        generate_btn=Mock(),
        search_btn=Mock(),
        search_entry=Mock(),
        year_entry=Mock(),
        more_btn=Mock(),
        run=Mock(),
        after=Mock(),
        after_cancel=Mock(),
        destroy=Mock(),
        _poll_id="poll-1",
    )
    d.search_var.get.return_value = "SYNTHETIC"
    d.year_var.get.return_value = "2027"
    d.tree.selection.return_value = ("8",)
    d.tree.get_children.return_value = ("8",)
    d.after.return_value = "next-poll"
    for name in (
        "selected_account",
        "update_controls",
        "selection_changed",
        "render_page",
        "poll",
    ):
        setattr(d, name, MethodType(getattr(TaxBillDialog, name), d))
    return d


@pytest.mark.parametrize("value", ["2027", " 2027 ", 1900, 2200])
def test_tax_bill_year_validation_accepts_explicit_year(value):
    assert 1900 <= tax_bill_year(value) <= 2200


@pytest.mark.parametrize(
    "value", ["2027.0", "2027,2028", "2027-01-01", "", 1899, 2201, True, "２０２７"]
)
def test_invalid_year_does_not_reach_download(value):
    with pytest.raises(ValueError):
        tax_bill_year(value)
    d = dialog()
    d.year_var.get.return_value = value
    with patch("ui.tax_bill.messagebox.showwarning") as warning:
        TaxBillDialog.generate(d)
    warning.assert_called_once()
    d.run.assert_not_called()


def test_duplicate_td_rows_are_distinct_valid_accounts():
    assert [r["id"] for r in validate_candidates(page(9, 8))] == [9, 8]


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"items": [], "has_more": "true"},
        page(8, 8),
        page(8, 9),
        page(True),
        page(-1),
        page(8, more=True) | {"next_cursor": 7},
        page(1, more=True) | {"next_cursor": True},
        page(8) | {"next_cursor": 8},
        page(more=True),
        {"items": [candidate() | {"effectivity": None}], "has_more": False},
    ],
)
def test_malformed_candidates_fail_closed(bad):
    with pytest.raises(ValueError):
        validate_candidates(bad)


def test_more_page_rejects_repeated_or_out_of_cursor_accounts():
    with pytest.raises(ValueError):
        validate_candidates(page(8), cursor=8)
    with pytest.raises(ValueError):
        validate_candidates(page(7), cursor=8, existing_ids=[7])


def test_no_selection_no_pdf_and_cancel_confirmation_no_pdf():
    d = dialog()
    d.tree.selection.return_value = ()
    with patch("ui.tax_bill.messagebox.showwarning") as warning:
        TaxBillDialog.generate(d)
    warning.assert_called_once()
    d.run.assert_not_called()
    d.tree.selection.return_value = ("8",)
    with patch("ui.tax_bill.messagebox.askyesno", return_value=False) as ask:
        TaxBillDialog.generate(d)
    assert "account #8" in ask.call_args.args[1]
    d.run.assert_not_called()


def test_download_captures_exact_id_and_tax_year_not_td_or_compliance_year():
    d = dialog()
    with (
        patch("ui.tax_bill.messagebox.askyesno", return_value=True),
        patch("ui.tax_bill.billing_service.download_tax_bill_pdf") as download,
    ):
        TaxBillDialog.generate(d)
        d.items["8"] = candidate(99)
        d.year_var.get.return_value = "2028"
        operation, work, context = d.run.call_args.args
        assert operation == "pdf" and context == (8, 2027)
        work()
        download.assert_called_once_with(8, 2027)


def test_search_change_invalidates_selection_and_more_but_year_is_independent():
    d = dialog()
    d.year_var.get.return_value = "2028"
    assert d.selected_account()["id"] == 8
    d.search_var.get.return_value = "ANOTHER ACCOUNT"
    assert d.selected_account() is None
    d.update_controls()
    assert d.generate_btn.configure.call_args.kwargs["state"] == "disabled"
    assert d.more_btn.configure.call_args.kwargs["state"] == "disabled"


def test_search_requires_input_and_new_search_clears_old_selection():
    d = dialog()
    d.search_var.get.return_value = " "
    TaxBillDialog.search(d)
    d.run.assert_not_called()
    d.search_var.get.return_value = "NEW DECLARATION"
    d.tree.selection.return_value = ()
    TaxBillDialog.search(d)
    assert d.items == {} and d.loaded_term == "NEW DECLARATION"
    operation, work, context = d.run.call_args.args
    assert operation == "search" and context == ("NEW DECLARATION", None)
    with patch("ui.tax_bill.property_service.search_tax_bill_properties") as search:
        work()
    search.assert_called_once_with("NEW DECLARATION", cursor=None)


def test_load_more_uses_server_cursor_and_keeps_previous_rows():
    d = dialog()
    d.next_cursor = 8
    TaxBillDialog.search(d, more=True)
    assert "8" in d.items
    assert d.run.call_args.args[2] == ("SYNTHETIC", 8)


def test_page_does_not_auto_choose_a_duplicate_td_but_can_restore_exact_preselection():
    d = dialog()
    d.items = {}
    d.render_page(page(9, 8), ("SYNTHETIC", None))
    d.tree.selection_set.assert_not_called()
    d.preferred_id = 8
    d.items = {}
    d.render_page(page(9, 8), ("SYNTHETIC", None))
    d.tree.selection_set.assert_called_once_with("8")


def test_busy_or_closed_dialog_cannot_repeat_generate_or_search():
    for flag in ("busy", "closed"):
        d = dialog()
        setattr(d, flag, True)
        TaxBillDialog.generate(d)
        TaxBillDialog.search(d)
        d.run.assert_not_called()


def test_stale_worker_result_and_closed_dialog_cannot_open_pdf():
    d = dialog()
    d.results.put((0, "pdf", "synthetic.pdf", None, (8, 2027)))
    with patch("ui.tax_bill.os.startfile", create=True) as open_pdf:
        d.poll()
    open_pdf.assert_not_called()
    d.results.put((1, "pdf", "synthetic.pdf", None, (8, 2027)))
    TaxBillDialog.close(d)
    d.poll()
    d.after_cancel.assert_called_once_with("next-poll")
    d.destroy.assert_called_once()
    assert d.results.qsize() == 1


def test_server_rejection_restores_controls_without_retarget_or_repeat():
    d = dialog()
    d.busy = True
    d.results.put((1, "pdf", None, "No assessment is effective", (8, 2027)))
    with (
        patch("ui.tax_bill.messagebox.showerror") as error,
        patch("ui.tax_bill.os.startfile", create=True) as open_pdf,
    ):
        d.poll()
    assert d.busy is False
    error.assert_called_once()
    open_pdf.assert_not_called()
    d.run.assert_not_called()


def test_invalid_search_result_removes_prior_selection_and_disables_pdf():
    d = dialog()
    d.results.put((1, "search", page(8, 8), None, ("SYNTHETIC", None)))
    d.poll()
    assert d.items == {} and d.next_cursor is None
    assert d.generate_btn.configure.call_args.kwargs["state"] == "disabled"


def test_compliant_page_can_open_tax_bill_search_with_an_empty_compliant_list(
    monkeypatch,
):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "clients" / "desktop")
    )
    from ui.compliant_dashboard import CompliantDashboardPage

    d = SimpleNamespace(
        _selected_property_id=lambda: None, _selected_year=2026, container=Mock()
    )
    with patch("ui.compliant_dashboard.TaxBillDialog") as open_search:
        CompliantDashboardPage._generate_tax_bill(d)
    open_search.assert_called_once_with(
        d.container, initial_year=2027, initial_search="", preferred_id=None
    )


def test_worker_only_enqueues_results_and_main_thread_handles_the_failure():
    d = dialog()

    def fail():
        raise ValueError("Synthetic server refusal")

    with (
        patch("ui.tax_bill.threading.Thread") as thread,
        patch("ui.tax_bill.messagebox.showerror") as error,
    ):
        TaxBillDialog.run(d, "pdf", fail, (8, 2027))
        thread.assert_called_once()
        assert thread.call_args.kwargs["daemon"] is True
        d.status.configure.assert_not_called()
        thread.call_args.kwargs["target"]()
        error.assert_not_called()
        assert d.busy is True and d.results.qsize() == 1
        d.poll()
        error.assert_called_once()
        assert d.busy is False


def test_success_opens_only_the_completed_confirmed_pdf():
    d = dialog()
    d.results.put((1, "pdf", "synthetic-2027.pdf", None, (8, 2027)))
    with patch("ui.tax_bill.os.startfile", create=True) as open_pdf:
        d.poll()
    open_pdf.assert_called_once_with("synthetic-2027.pdf")
    assert "account #8" in d.status.configure.call_args.kwargs["text"]


def test_closed_during_confirmation_does_not_start_generation():
    d = dialog()

    def close_then_accept(*_args, **_kwargs):
        d.closed = True
        return True

    with patch("ui.tax_bill.messagebox.askyesno", side_effect=close_then_accept):
        TaxBillDialog.generate(d)
    d.run.assert_not_called()
