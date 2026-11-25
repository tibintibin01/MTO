"""Report presentation regressions; synthetic totals, no production records."""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))
import ui.reports as reports
from utils.report_labels import BARANGAY_APPLIED_RATE_HELP


def report_row(due=1000, paid=600, remaining=400, credit=0):
    return ["SYNTHETIC", 50000, due, 0, 0, paid, remaining, credit]


def test_synthetic_totals_can_legitimately_produce_53_9_with_separate_credit():
    # Entirely fictional totals; live municipal evidence stays outside source.
    row = report_row(2000000, 1078000, 1012000, 90000)
    original = deepcopy(row)
    _, due, paid, remaining, credit, rate = reports.barangay_receivables_comparison(row)
    assert due + credit == pytest.approx(paid + remaining)
    assert f"{rate:.1f}%" == "53.9%"
    assert f"{paid / (paid + remaining) * 100:.1f}%" == "51.6%"
    assert row == original


@pytest.mark.parametrize(
    "due,paid,remaining,credit,rate",
    [
        (1000, 600, 400, 0, 60),
        (4000, 2500, 2000, 500, 62.5),
        (1000, 1500, 0, 500, 150),
        (1000, 0, 1000, 0, 0),
        (0, 0, 0, 0, None),
        (0, 500, 0, 500, None),
        (-100, 500, 0, 600, None),
    ],
)
def test_rate_keeps_due_denominator_and_never_caps_credits_or_nets_accounts(
    due, paid, remaining, credit, rate
):
    result = reports.barangay_receivables_comparison(
        report_row(due, paid, remaining, credit)
    )
    assert result == ("SYNTHETIC", due, paid, remaining, credit, rate)


def test_decimal_inputs_and_legacy_missing_credit_do_not_invent_values():
    row = report_row(
        Decimal("3000.00"), Decimal("1000.00"), Decimal("2000.00"), Decimal("0.00")
    )
    assert reports.barangay_receivables_comparison(row)[-1] == pytest.approx(100 / 3)
    assert reports.barangay_receivables_comparison(row[:-1])[-2] is None
    with pytest.raises(ValueError, match="missing required totals"):
        reports.barangay_receivables_comparison(row[:6])


def render_table(rows, year=2026, limit=7):
    page = reports.ReportsPage.__new__(reports.ReportsPage)
    parent = MagicMock()
    labels, label_widgets, trees = [], [], []

    def label(*args, **kwargs):
        labels.append(kwargs)
        widget = MagicMock()
        widget._get_widget_scaling.return_value = 1.25
        widget.cget.return_value = kwargs["wraplength"]
        label_widgets.append(widget)
        return widget

    def tree(*args, **kwargs):
        result = MagicMock()
        trees.append((kwargs, result))
        return result

    with (
        patch.object(reports.ctk, "CTkFrame", return_value=MagicMock()),
        patch.object(reports.ctk, "CTkLabel", side_effect=label),
        patch.object(reports.ttk, "Treeview", side_effect=tree),
        patch.object(reports.ttk, "Scrollbar", return_value=MagicMock()) as scrollbar,
    ):
        page._render_barangay_comparison(parent, rows, year=year, limit=limit)
    return SimpleNamespace(
        parent=parent,
        labels=labels,
        label_widgets=label_widgets,
        kwargs=trees[0][0],
        tree=trees[0][1],
        scrollbar=scrollbar,
    )


def test_table_shows_denominator_credit_unpaid_and_formula_from_same_row():
    rendered = render_table([report_row(2000000, 1078000, 1012000, 90000)])
    assert rendered.kwargs["columns"] == (
        "Barangay",
        "Total Due",
        "Payments Applied",
        "Remaining Unpaid",
        "Recorded Credit",
        "Applied / Due",
    )
    assert rendered.tree.insert.call_args.kwargs["values"] == (
        "SYNTHETIC",
        "2,000,000.00",
        "1,078,000.00",
        "1,012,000.00",
        "90,000.00",
        "53.9%",
    )
    note = rendered.labels[0]["text"]
    assert BARANGAY_APPLIED_RATE_HELP in note
    assert "not only cash received in 2026" in note
    assert "All billing years through 2026" in note
    rendered.scrollbar.assert_called_once()
    assert rendered.scrollbar.call_args.kwargs["orient"] == "horizontal"
    assert "xscrollcommand" in rendered.tree.configure.call_args.kwargs
    for call in rendered.tree.column.call_args_list:
        if "width" in call.kwargs:
            assert call.kwargs["minwidth"] == call.kwargs["width"]
            assert call.kwargs["stretch"] is False


def test_explanation_wrap_is_dpi_aware_and_uses_existing_idempotent_handler():
    rendered = render_table([report_row()])
    note = rendered.label_widgets[0]
    note.bind.assert_not_called()
    callback = rendered.parent.bind.call_args.args[1]
    callback(SimpleNamespace(width=1000))
    note.configure.assert_called_once_with(wraplength=774)
    note.cget.return_value = 774
    callback(SimpleNamespace(width=1000))
    note.configure.assert_called_once()


def test_display_retains_ranking_limit_and_unavailable_values():
    first = report_row(0, 500, 0, 500)[:-1]
    second = report_row(2000, 0, 2000)
    first[0], second[0] = "FIRST", "SECOND"
    rendered = render_table([first, second], limit=1)
    assert rendered.tree.insert.call_count == 1
    assert rendered.tree.insert.call_args.kwargs["values"][0] == "SECOND"
    legacy = render_table([first], year=None)
    assert legacy.tree.insert.call_args.kwargs["values"][-2:] == ("Not supplied", "—")
    assert (
        "All available billing years and recorded payment dates"
        in legacy.labels[0]["text"]
    )
