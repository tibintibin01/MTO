"""Desktop navigation/export checks use synthetic state only; no live API."""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))
import ui.reports as reports_ui
from ui.report_workspace_state import ReportViewState


def page_for_period(month="11", year="2026", search="", order="Newest posted"):
    page = reports_ui.ReportsPage.__new__(reports_ui.ReportsPage)
    selection = [month, year, search, order]
    page.month_cb = SimpleNamespace(get=lambda: selection[0])
    page.year_cb = SimpleNamespace(get=lambda: selection[1])
    page.coll_search = SimpleNamespace(get=lambda: selection[2])
    page.coll_order_cb = SimpleNamespace(get=lambda: selection[3])
    state = ReportViewState()
    state.begin(tuple(selection))
    state.accept(state.selected, {})
    page._workspace_states = {"collection": state}
    page.export_collection_btn = SimpleNamespace(_workspace_export_busy=False)
    page._export_with_feedback = MagicMock()
    return page, selection


@pytest.mark.parametrize(
    "month,year", [("11", "2026"), ("All", "2026"), ("All", "All")]
)
def test_register_export_requests_whole_period_not_the_visible_page(month, year):
    page, selection = page_for_period(month, year)
    page._coll_page = 3
    page._coll_page_size = 100
    with patch.object(reports_ui.billing, "export_report_excel") as export:
        page._export_collection_excel()
        button, worker, file_format = page._export_with_feedback.call_args.args
        assert button is page.export_collection_btn
        assert file_format == "excel"
        # Changing filters while the worker runs cannot retarget its request.
        selection[0], selection[1] = "12", "2027"
        worker()
    export.assert_called_once_with("collections", month=month, year=year)


@pytest.mark.parametrize("status", ["ready", "loading", "empty", "error", "changed"])
def test_register_export_requires_successfully_loaded_filters(status):
    page, _ = page_for_period()
    page._workspace_states["collection"].status = status
    with patch.object(reports_ui.messagebox, "showinfo"):
        page._export_collection_excel()
    page._export_with_feedback.assert_not_called()


def test_register_export_refuses_changed_unrefreshed_period():
    page, selection = page_for_period()
    selection[1] = "2027"
    with patch.object(reports_ui.messagebox, "showinfo") as message:
        page._export_collection_excel()
    message.assert_called_once()
    page._export_with_feedback.assert_not_called()


def test_register_export_search_guard_explains_scope():
    page, _ = page_for_period(search="SYNTHETIC")
    with patch.object(reports_ui.messagebox, "showinfo") as message:
        page._export_collection_excel()
    assert message.call_args.args[0] == "Clear search to export"
    assert "whole selected period" in message.call_args.args[1]
    page._export_with_feedback.assert_not_called()


def test_busy_register_export_is_not_started_twice():
    page, _ = page_for_period()
    page.export_collection_btn._workspace_export_busy = True
    page._export_collection_excel()
    page._export_with_feedback.assert_not_called()


@pytest.mark.parametrize(
    "page_number,count,has_more,expected",
    [
        (0, 100, True, "Page 1  ·  1–100 of 706 receipts"),
        (1, 100, True, "Page 2  ·  101–200 of 706 receipts"),
        (7, 6, False, "Page 8  ·  701–706 of 706 receipts"),
    ],
)
def test_pager_shows_receipt_range_and_total(page_number, count, has_more, expected):
    page, _ = page_for_period()
    page._coll_page = page_number
    page._coll_page_size = 100
    page._coll_cursors = [None] * (page_number + 1)
    page.coll_tree = MagicMock()
    page.coll_tree.get_children.return_value = []
    page.coll_empty_state = MagicMock()
    page._coll_page_lbl = MagicMock()
    page._coll_prev_btn = MagicMock()
    page._coll_next_btn = MagicMock()
    page._update_coll_table(
        {
            "items": [
                ["2026-11-01", "DEMO", "DEMO", "SYNTHETIC", "LOT", "2026", 1, "DEMO"]
            ]
            * count,
            "total_count": 706,
            "has_more": has_more,
            "next_cursor": "SYNTHETIC" if has_more else None,
        }
    )
    page._coll_page_lbl.configure.assert_called_once_with(text=expected)
    page._coll_next_btn.configure.assert_called_once_with(
        state="normal" if has_more else "disabled"
    )
    page._coll_prev_btn.configure.assert_called_once_with(
        state="normal" if page_number else "disabled"
    )


def test_both_exports_share_the_existing_stale_and_search_guards():
    page, selection = page_for_period()
    page._workspace_labels = {"collection": MagicMock()}
    page.export_collection_btn = MagicMock(_workspace_export_busy=False)
    page.export_rcd_btn = MagicMock(_workspace_export_busy=False)
    page._workspace_exports = {
        "collection": (page.export_collection_btn, page.export_rcd_btn)
    }
    page._sync_workspace("collection")
    for button in page._workspace_exports["collection"]:
        assert button.configure.call_args.kwargs["state"] == "normal"
    state = page._workspace_states["collection"]
    selection[2] = "SYNTHETIC"
    state.begin(tuple(selection))
    state.accept(state.selected, {})
    page._sync_workspace("collection")
    for button in page._workspace_exports["collection"]:
        assert button.configure.call_args.kwargs["state"] == "disabled"


@pytest.mark.parametrize(
    "available,natural,expected",
    [
        (700, 500, 386),
        (480, 500, 210),
        (1000, 300, 240),
    ],
)
def test_controls_height_reserves_table_space_and_does_not_loop(
    available, natural, expected
):
    page = reports_ui.ReportsPage.__new__(reports_ui.ReportsPage)
    height = [0]
    configure = MagicMock(side_effect=lambda **kw: height.__setitem__(0, kw["height"]))
    page.coll_controls_fr = SimpleNamespace(
        _get_widget_scaling=lambda: 1.25,
        winfo_reqheight=lambda: natural,
        cget=lambda name: height[0],
        configure=configure,
    )
    page.coll_body_fr = SimpleNamespace(winfo_height=lambda: available)
    page.coll_pagination_fr = SimpleNamespace(winfo_reqheight=lambda: 60)
    page._fit_collection_controls()
    page._fit_collection_controls()
    configure.assert_called_once_with(height=expected)


def test_workspace_wrap_handler_measures_parent_not_text_widget():
    source = Path(reports_ui.__file__).read_text(encoding="utf-8")
    assert (
        'parent.bind("<Configure>", lambda e: self._wrap_report_label(label, e.width), add="+")'
        in source
    )
    assert (
        'label.bind("<Configure>", lambda e: self._wrap_report_label(label, e.width))'
        not in source
    )


def test_pagination_is_reserved_before_header_and_table():
    source = Path(reports_ui.__file__).read_text(encoding="utf-8")
    start = source.index("    def setup_collection_tab(self):")
    end = source.index("    def _fit_collection_controls", start)
    collection = source[start:end]
    assert collection.index(
        "self._setup_collection_pagination(collection_fr)"
    ) < collection.index("controls_fr =")
    assert collection.index(
        "self._setup_collection_pagination(collection_fr)"
    ) < collection.index("self.coll_table_fr =")
