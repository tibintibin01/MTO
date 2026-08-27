import unittest
import inspect
from unittest.mock import MagicMock, patch
import sys
import os

# Match the packaged desktop application's import precedence: Treasury.spec
# launches from clients/desktop, so its shared UI modules must resolve first.
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
desktop_client_dir = os.path.join(root_dir, "clients", "desktop")
if desktop_client_dir in sys.path:
    sys.path.remove(desktop_client_dir)
sys.path.insert(0, desktop_client_dir)

# Mocking CustomTkinter to avoid GUI initialization during tests
import customtkinter

customtkinter.set_appearance_mode = MagicMock()
customtkinter.set_default_color_theme = MagicMock()

from ui.navigation import NavigationSidebar
from ui.status_bar import ConnectivityStatusBar
from ui.dashboard_home import (
    DashboardHomePage,
    _dashboard_month_label,
    _recent_payment_display,
)
from ui.assessment_roll import (
    AssessmentRollPage,
    assessment_roll_export_dialog_options,
    parse_assessment_roll_as_of_year,
)
from utils.assessment_roll_status import VERIFIED_DUPLICATE_LABEL
from ui.compliant_dashboard import (
    _COMPLIANT_PAYMENTS_LABEL,
    compliance_scope_text,
    suggested_tax_bill_year,
)


class TestNavigationSidebar(unittest.TestCase):
    def test_navigation_sets_active_page_and_calls_loader(self):
        sidebar = object.__new__(NavigationSidebar)
        sidebar.callbacks = {"load_page": MagicMock()}
        sidebar._set_active = MagicMock()
        page_class = object()

        sidebar._navigate("reports", page_class)

        sidebar._set_active.assert_called_once_with("reports")
        sidebar.callbacks["load_page"].assert_called_once_with(page_class)

    def test_legacy_nav_factory_returns_created_button(self):
        sidebar = object.__new__(NavigationSidebar)
        button = object()
        callback = MagicMock()
        sidebar._add_nav = MagicMock(return_value=button)

        result = sidebar.create_nav_btn("Assessment Roll", callback)

        self.assertIs(result, button)
        sidebar._add_nav.assert_called_once_with(
            "assessment_roll", "Assessment Roll", callback
        )


class TestStatusBar(unittest.TestCase):
    def test_status_bar_updates_without_gui_mainloop(self):
        bar = object.__new__(ConnectivityStatusBar)
        bar.status_dot = MagicMock()
        bar.status_lbl = MagicMock()
        bar.queue_lbl = MagicMock()
        bar.winfo_exists = MagicMock(return_value=False)
        bar.after = MagicMock()

        with (
            patch("ui.status_bar.api.get_connection_status", return_value="OFFLINE"),
            patch("ui.status_bar.manager.get_queue_count", return_value=2),
        ):
            bar.update_status()

        bar.status_dot.configure.assert_called_once_with(text_color="#e74c3c")
        bar.status_lbl.configure.assert_called_once_with(
            text="OFFLINE MODE (LOCAL SAVE ACTIVE)"
        )
        bar.queue_lbl.configure.assert_called_once_with(text="PENDING SYNC: 2 ITEMS")
        bar.after.assert_not_called()


class TestAssessmentRollFilters(unittest.TestCase):
    def test_as_of_year_parser_accepts_blank_or_valid_year(self):
        self.assertIsNone(parse_assessment_roll_as_of_year(""))
        self.assertEqual(parse_assessment_roll_as_of_year(" 2026 "), 2026)

    def test_as_of_year_parser_rejects_invalid_values(self):
        for value in ("26", "202A", "1899", "2201"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_assessment_roll_as_of_year(value)

    def test_refresh_generation_rejects_stale_responses(self):
        page = object.__new__(AssessmentRollPage)
        page._refresh_generation = 4

        self.assertTrue(page._is_current_refresh(4))
        self.assertFalse(page._is_current_refresh(3))

    def test_excel_export_dialog_only_offers_xlsx(self):
        options = assessment_roll_export_dialog_options(
            "download.pdf",
            "excel",
        )

        self.assertEqual(options["defaultextension"], ".xlsx")
        self.assertEqual(options["initialfile"], "download.xlsx")
        self.assertEqual(options["filetypes"], [("Excel workbook (*.xlsx)", "*.xlsx")])

    def test_pdf_export_dialog_only_offers_pdf(self):
        options = assessment_roll_export_dialog_options(
            "download.xlsx",
            "pdf",
        )

        self.assertEqual(options["defaultextension"], ".pdf")
        self.assertEqual(options["initialfile"], "download.pdf")
        self.assertEqual(options["filetypes"], [("PDF document (*.pdf)", "*.pdf")])

    def test_verified_duplicate_row_is_amber_and_keeps_internal_property_id(self):
        page = object.__new__(AssessmentRollPage)
        page.current_page = 0
        page.page_size = 50
        page.all_loaded = False
        page.page_lbl = MagicMock()
        page.prev_btn = MagicMock()
        page.next_btn = MagicMock()
        page.tree = MagicMock()
        page.tree.get_children.return_value = []

        row = [None] * 25
        row[0] = 9001
        row[1] = "06-0012-00094"
        row[2] = "SECOND OWNER"
        row[4] = "20-H"
        row[6] = "DINADIAWAN"
        row[7] = "RESIDENTIAL LOT"
        row[9] = 46350
        row[18] = "01-134"
        row[20] = "02-06012-02007-A-PAR"
        row[21] = "2023-01-01"
        row[22] = "DINADIAWAN"
        row[23] = True

        page._update_table([row], has_more=False)

        insert_call = page.tree.insert.call_args
        values = insert_call.kwargs["values"]
        self.assertEqual(values[0], 9001)
        self.assertEqual(values[-1], VERIFIED_DUPLICATE_LABEL)
        self.assertEqual(insert_call.kwargs["tags"], ("verified_duplicate",))


class TestCompliantDashboardLabels(unittest.TestCase):
    def test_payment_kpi_identifies_the_accounts_included(self):
        self.assertEqual(
            _COMPLIANT_PAYMENTS_LABEL,
            "PAID BY COMPLIANT PROPERTIES",
        )

    def test_scope_text_distinguishes_through_year_from_single_year(self):
        text = compliance_scope_text(2026)

        self.assertIn("through 2026", text)
        self.assertIn("all included billing years, not 2026 alone", text)
        self.assertIn("Later billing years are excluded", text)
        self.assertIn("next-year Tax Bill", text)

    def test_tax_bill_defaults_to_the_year_after_the_compliance_scope(self):
        self.assertEqual(suggested_tax_bill_year(2026), 2027)


class TestDashboardHome(unittest.TestCase):
    def test_recent_payment_rows_are_normalized_for_dashboard_display(self):
        row = _recent_payment_display(
            [
                "2026-08-17",
                "7812001",
                "06-0012-00001",
                "DELA CRUZ, JUAN",
                "2026",
                1250.5,
            ]
        )

        self.assertEqual(row["date"], "2026-08-17")
        self.assertEqual(row["or_number"], "7812001")
        self.assertEqual(row["td_number"], "06-0012-00001")
        self.assertEqual(row["owner_year"], "DELA CRUZ, JUAN / 2026")
        self.assertEqual(row["amount"], 1250.5)

    def test_named_recent_payment_rows_are_normalized_for_dashboard_display(self):
        row = _recent_payment_display(
            {
                "date_paid": "2026-08-20T09:15:00",
                "or_number": "7812002",
                "td_number": "06-0012-00002",
                "owner_name": "SANTOS, MARIA",
                "tax_year": "2026",
                "amount": 900.25,
            }
        )

        self.assertEqual(row["date"], "2026-08-20")
        self.assertEqual(row["owner_year"], "SANTOS, MARIA / 2026")
        self.assertEqual(row["amount"], 900.25)

    def test_month_labels_include_year_to_avoid_cross_year_ambiguity(self):
        self.assertEqual(_dashboard_month_label("2026-08"), "Aug 26")
        self.assertEqual(_dashboard_month_label("invalid"), "invalid")

    def test_dashboard_replaces_duplicate_trend_and_direct_backup_action(self):
        setup_source = inspect.getsource(DashboardHomePage.setup_ui)
        class_source = inspect.getsource(DashboardHomePage)

        self.assertNotIn("trend_chart", setup_source)
        self.assertIn("_setup_recent_collections", setup_source)
        self.assertNotIn("trigger_manual_backup", class_source)
        self.assertIn("_open_backup_settings", class_source)

    def test_readiness_check_is_admin_only(self):
        home = object.__new__(DashboardHomePage)
        home.user = {"role": "cashier"}

        with patch(
            "ui.dashboard_home.readiness_service.get_tax_year_readiness"
        ) as get_readiness:
            home.refresh_tax_year_readiness()

        get_readiness.assert_not_called()

    def test_action_required_readiness_is_scheduled_for_render(self):
        home = object.__new__(DashboardHomePage)
        home.user = {"role": "admin"}
        home.parent = MagicMock()
        home._update_tax_year_readiness = MagicMock()
        readiness = {
            "season_active": True,
            "action_required": True,
            "target_year": 2027,
        }

        with patch(
            "ui.dashboard_home.readiness_service.get_tax_year_readiness",
            return_value=readiness,
        ):
            home.refresh_tax_year_readiness()

        scheduled_render = home.parent.after.call_args.args[1]
        scheduled_render()
        home._update_tax_year_readiness.assert_called_once_with(readiness)

    def test_dashboard_refresh_schedules_render_with_service_data(self):
        home = object.__new__(DashboardHomePage)
        home.parent = MagicMock()
        home.callbacks = {
            "get_summary": MagicMock(return_value={"total_properties": 100}),
            "get_trend": MagicMock(return_value=[]),
            "get_recent": MagicMock(return_value=[]),
        }
        home._update_ui = MagicMock()
        home._hide_loading = MagicMock()

        with patch(
            "ui.dashboard_home.system.get_system_stats", return_value={"pool": {}}
        ):
            home.refresh_data()

        home.callbacks["get_summary"].assert_called_once_with()
        home.callbacks["get_trend"].assert_called_once_with(6)
        scheduled_render = home.parent.after.call_args.args[1]
        home.callbacks["get_recent"].assert_called_once_with(6)
        scheduled_render()
        home._update_ui.assert_called_once_with(
            {"total_properties": 100, "infra_stats": {"pool": {}}},
            [],
            [],
            None,
        )

    def test_dashboard_recent_payment_failure_is_rendered_as_an_error(self):
        home = object.__new__(DashboardHomePage)
        home.parent = MagicMock()
        home.callbacks = {
            "get_summary": MagicMock(return_value={"total_properties": 100}),
            "get_trend": MagicMock(return_value=[]),
            "get_recent": MagicMock(side_effect=RuntimeError("endpoint failed")),
        }
        home._update_ui = MagicMock()
        home._hide_loading = MagicMock()

        with (
            patch(
                "ui.dashboard_home.system.get_system_stats", return_value={"pool": {}}
            ),
            patch("utils.log_error_to_file"),
        ):
            home.refresh_data()

        scheduled_render = home.parent.after.call_args.args[1]
        scheduled_render()
        args = home._update_ui.call_args.args
        self.assertEqual(
            args[:3],
            (
                {"total_properties": 100, "infra_stats": {"pool": {}}},
                [],
                [],
            ),
        )
        self.assertIn("endpoint failed", args[3])


if __name__ == "__main__":
    unittest.main()
