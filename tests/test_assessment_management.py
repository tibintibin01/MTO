"""Headless regression coverage for the consolidated property workspace."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))
from ui.assessment_roll import AssessmentRollPage
from ui.navigation import NavigationSidebar


@pytest.fixture
def page():
    result = object.__new__(AssessmentRollPage)
    result.parent = MagicMock()
    result.container = MagicMock()
    result.user = {"username": "test-admin", "role": "admin"}
    result.view_mode = result.CURRENT_MODE
    result.is_loading = False
    result._rows_current = True
    result._refresh_generation = 0
    result.page_cursors = [None]
    result.current_page = 0
    result.page_size = 50
    result.all_loaded = False
    result.search_ent = MagicMock()
    result.search_ent.get.return_value = ""
    result.brgy_var = MagicMock()
    result.brgy_var.get.return_value = "ALL"
    result.as_of_year_ent = MagicMock()
    result.as_of_year_ent.get.return_value = "2025"
    result.tree = MagicMock()
    result.tree.selection.return_value = ("row-2",)
    result.tree.item.return_value = {
        "values": [9002, "SHARED-TD", "PIN", "LOT", "SECOND OWNER"]
    }
    result.tree.get_children.return_value = ()
    for name in (
        "prev_btn",
        "next_btn",
        "page_lbl",
        "empty_state",
        "mode_hint",
        "add_btn",
        "edit_btn",
        "delete_btn",
        "import_btn",
        "cleanup_btn",
        "details_btn",
    ):
        setattr(result, name, MagicMock())
    result._loaded_query = result._query_context()
    return result


@pytest.mark.parametrize(
    "role,edit,delete,import_allowed",
    [
        ("admin", True, True, True),
        ("encoder", True, False, False),
        ("cashier", False, False, False),
        ("viewer", False, False, False),
        ("unknown", False, False, False),
    ],
)
def test_role_gates_all_management_controls(page, role, edit, delete, import_allowed):
    page.user["role"] = role
    page._update_action_states()
    for name, allowed in (
        ("add_btn", edit),
        ("edit_btn", edit),
        ("cleanup_btn", edit),
        ("delete_btn", delete),
        ("import_btn", import_allowed),
    ):
        getattr(page, name).configure.assert_called_with(
            state="normal" if allowed else "disabled"
        )


def test_edit_uses_internal_id_not_shared_td(page):
    with patch("ui.assessment_roll.PropertyEditModal") as editor:
        page.open_edit_modal()
    editor.assert_called_once_with(
        page.parent, "Edit Property", 9002, page.refresh_table, user=page.user
    )


@pytest.mark.parametrize("role", ["admin", "encoder", "cashier", "viewer"])
def test_historical_mode_blocks_all_mutations_even_when_called_directly(page, role):
    page.user["role"] = role
    page.view_mode = page.HISTORY_MODE
    with (
        patch("ui.assessment_roll.PropertyEditModal") as editor,
        patch("ui.assessment_roll.BulkBarangayUpdateModal") as cleanup,
        patch("ui.assessment_roll.ImportWizardModal") as importer,
        patch("ui.assessment_roll.prop_svc.delete_property") as delete,
    ):
        page.open_add_modal()
        page.open_edit_modal()
        page.open_bulk_update()
        page.open_import_wizard()
        page.confirm_delete()
        page._launch_import("assessment", MagicMock())
        for action in (editor, cleanup, importer, delete):
            action.assert_not_called()
    page._update_action_states()
    page.details_btn.configure.assert_called_with(state="disabled")
    page.add_btn.configure.assert_called_with(state="disabled")


def test_loading_blocks_management(page):
    page.is_loading = True
    assert not page._can_manage("property_edit")
    assert page._selected_property() is None


def test_filter_change_clears_selection_and_invalidates_pending_response(page):
    page._filters_edited(SimpleNamespace(keysym="a"))
    page.tree.selection_remove.assert_called_once_with("row-2")
    assert page._refresh_generation == 1
    assert page._selected_property() is None
    assert not page._is_current_refresh(0)


def test_programmatic_filter_change_also_blocks_old_selection(page):
    page.search_ent.get.return_value = "DIFFERENT OWNER"
    assert page._selected_property() is None


def test_mode_change_clears_table_and_disables_management(page):
    page.tree.get_children.return_value = ("row-2",)
    page._change_mode(page.HISTORY_MODE)
    page.tree.delete.assert_called_once_with("row-2")
    page.as_of_year_ent.configure.assert_called_with(state="normal")
    page.edit_btn.configure.assert_called_with(state="disabled")
    assert page._loaded_query is None


def test_current_mode_ignores_old_historical_year(page):
    page.as_of_year_ent.get.return_value = "not-a-year"
    assert page._query_as_of_year() is None


def test_historical_mode_requires_valid_year(page):
    page.view_mode = page.HISTORY_MODE
    page.as_of_year_ent.get.return_value = ""
    with pytest.raises(ValueError, match="Enter an As of Year"):
        page._query_as_of_year()
    page.as_of_year_ent.get.return_value = "2025"
    assert page._query_as_of_year() == 2025


def test_delete_only_selected_duplicate_account_and_preserves_recycle_semantics(page):
    page.refresh_table = MagicMock()
    with (
        patch("ui.assessment_roll.messagebox.askyesno", return_value=True) as confirm,
        patch("ui.assessment_roll.messagebox.showinfo"),
        patch(
            "ui.assessment_roll.prop_svc.delete_property",
            return_value={"status": "deleted"},
        ) as delete,
    ):
        page.confirm_delete()
    assert "Account ID: 9002" in confirm.call_args.args[1]
    assert "Recycle Bin" in confirm.call_args.args[1]
    delete.assert_called_once_with(9002, user=page.user)
    page.refresh_table.assert_called_once_with()


def test_delete_cancel_does_not_call_server(page):
    with (
        patch("ui.assessment_roll.messagebox.askyesno", return_value=False),
        patch("ui.assessment_roll.prop_svc.delete_property") as delete,
    ):
        page.confirm_delete()
    delete.assert_not_called()


def test_mode_change_during_confirmation_blocks_delete(page):
    def change_mode(*args, **kwargs):
        page.view_mode = page.HISTORY_MODE
        return True

    with (
        patch("ui.assessment_roll.messagebox.askyesno", side_effect=change_mode),
        patch("ui.assessment_roll.prop_svc.delete_property") as delete,
    ):
        page.confirm_delete()
    delete.assert_not_called()


@pytest.mark.parametrize("mode", ["property", "assessment"])
def test_both_existing_import_formats_are_preserved(page, mode):
    chooser = MagicMock()
    with patch("ui.assessment_roll.ImportWizardModal") as importer:
        page._launch_import(mode, chooser)
    chooser.destroy.assert_called_once_with()
    importer.assert_called_once_with(
        page.container.winfo_toplevel(), mode=mode, on_complete=page.refresh_table
    )


def test_import_rejects_unsupported_mode(page):
    with patch("ui.assessment_roll.ImportWizardModal") as importer:
        page._launch_import("payments", MagicMock())
    importer.assert_not_called()


def test_sidebar_has_one_assessment_destination_and_no_legacy_property_entry():
    sidebar = object.__new__(NavigationSidebar)
    sidebar.user_data = {"role": "admin"}
    sidebar._section_label = MagicMock()
    sidebar._add_nav = MagicMock()
    sidebar._set_active = MagicMock()
    sidebar._setup_nav_links()
    keys = [call.args[0] for call in sidebar._add_nav.call_args_list]
    assert keys.count("assessment") == 1
    assert "property" not in keys


def test_refresh_captures_current_mode_and_rejects_response_after_switch(page):
    queued = []
    page.container.after.side_effect = lambda delay, callback: queued.append(callback)
    with (
        patch("ui.assessment_roll.threading.Thread") as thread,
        patch("ui.assessment_roll.LoadingOverlay"),
        patch(
            "ui.assessment_roll.prop_svc.search_properties",
            return_value={"items": [], "has_more": False},
        ) as search,
    ):
        page.refresh_table()
        thread.call_args.kwargs["target"]()
        search.assert_called_once_with(
            "",
            limit=50,
            cursor=None,
            barangay=None,
            as_of_year=None,
            year_start=None,
            year_end=None,
        )
        page.view_mode = page.HISTORY_MODE
        page._invalidate_selection()
        page._update_table = MagicMock()
        for callback in queued:
            callback()
        page._update_table.assert_not_called()


def test_historical_export_passes_year_and_current_export_does_not(page):
    page._pdf_btn = MagicMock()
    page._export_with_feedback = lambda button, worker, fmt: worker()
    with patch("ui.assessment_roll.billing.download_assessment_roll_pdf") as export:
        page._export_roll_pdf()
        export.assert_called_with(barangay=None, as_of_year=None)
        page.view_mode = page.HISTORY_MODE
        page._export_roll_pdf()
        export.assert_called_with(barangay=None, as_of_year=2025)


def test_current_effectivity_range_is_preserved_but_ignored_in_history(page):
    page.year_from_ent = MagicMock()
    page.year_to_ent = MagicMock()
    page.year_from_ent.get.return_value = "2023"
    page.year_to_ent.get.return_value = "2026"
    assert page._query_year_range() == (2023, 2026)
    page.view_mode = page.HISTORY_MODE
    assert page._query_year_range() == (None, None)


def test_inverted_year_range_is_rejected(page):
    page.year_from_ent = MagicMock()
    page.year_to_ent = MagicMock()
    page.year_from_ent.get.return_value = "2026"
    page.year_to_ent.get.return_value = "2023"
    with pytest.raises(ValueError, match="From year"):
        page._query_year_range()
