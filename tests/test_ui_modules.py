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
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

customtkinter.set_appearance_mode = MagicMock()
customtkinter.set_default_color_theme = MagicMock()

from ui.navigation import (
    NAV_ACTIVE_BG,
    NAV_IDLE_BG,
    NAV_IDLE_BORDER,
    NavigationSidebar,
)
from ui.status_bar import ConnectivityStatusBar
from ui.dashboard_home import (
    DashboardHomePage,
    _dashboard_month_label,
    _recent_payment_display,
)
from ui.ledger import LedgerPage
from ui.empty_state import EmptyTableState
from ui.property import PropertyPage
from ui.reports import ReportsPage
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
from ui_components import ModernChartWidget


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

    def test_navigation_uses_visible_card_and_accessible_active_surfaces(self):
        self.assertEqual(NAV_IDLE_BG, ("#eef3f8", "#172338"))
        self.assertEqual(NAV_IDLE_BORDER, ("#d5e0eb", "#2b405c"))
        self.assertEqual(NAV_ACTIVE_BG, ("#0369a1", "#0369a1"))

        setup_source = inspect.getsource(NavigationSidebar._setup_nav_links)
        self.assertIn('_section_label("MAIN")', setup_source)
        self.assertIn('_section_label("REPORTS & TOOLS")', setup_source)
        self.assertIn('_section_label("SUPPORT")', setup_source)


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
            patch("ui.status_bar.manager.get_quarantined_count", return_value=2),
        ):
            bar.update_status()

        bar.status_dot.configure.assert_called_once_with(text_color="#e74c3c")
        bar.status_lbl.configure.assert_called_once_with(
            text="OFFLINE - READ-ONLY CACHE ONLY"
        )
        bar.queue_lbl.configure.assert_called_once_with(
            text="REVIEW REQUIRED: 2 BLOCKED LEGACY ITEMS"
        )
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
        page.empty_state = MagicMock()

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
        page.empty_state.hide.assert_called_once_with()

    def test_assessment_roll_empty_result_shows_guidance(self):
        page = object.__new__(AssessmentRollPage)
        page.current_page = 0
        page.page_size = 50
        page.page_lbl = MagicMock()
        page.prev_btn = MagicMock()
        page.next_btn = MagicMock()
        page.tree = MagicMock()
        page.tree.get_children.return_value = []
        page.empty_state = MagicMock()

        page._update_table([], has_more=False)

        page.empty_state.show.assert_called_once()
        self.assertEqual(
            page.empty_state.show.call_args.kwargs["title"],
            "No matching assessments",
        )

    def test_duplicate_legend_uses_neutral_authorization_wording(self):
        setup_source = inspect.getsource(AssessmentRollPage.setup_ui)

        self.assertIn("Authorized duplicate TD accounts", setup_source)
        self.assertNotIn("Assessor-authorized", setup_source)


class TestOtherEmptyStates(unittest.TestCase):
    def test_shared_notice_can_change_message_and_hide(self):
        icon = MagicMock()
        title = MagicMock()
        message = MagicMock()
        with patch("ui.empty_state.ctk.CTkFrame") as frame_class, patch(
            "ui.empty_state.ctk.CTkLabel", side_effect=[icon, title, message]
        ):
            state = EmptyTableState(MagicMock(), "Search to begin.")
            state.show("Try another search.", title="No matching records")
            state.hide()

        self.assertEqual(frame_class.return_value.place.call_count, 2)
        title.configure.assert_called_with(text="No matching records")
        message.configure.assert_called_with(text="Try another search.")
        frame_class.return_value.place_forget.assert_called_once_with()

    def test_property_empty_result_shows_guidance(self):
        page = object.__new__(PropertyPage)
        page.current_page = 0
        page.page_lbl = MagicMock()
        page.prev_btn = MagicMock()
        page.next_btn = MagicMock()
        page.tree = MagicMock()
        page.tree.get_children.return_value = []
        page.empty_state = MagicMock()
        page.on_selection_change = MagicMock()

        page._update_table([], has_more=False)

        page.empty_state.show.assert_called_once()
        self.assertEqual(
            page.empty_state.show.call_args.kwargs["title"],
            "No matching properties",
        )

    def test_collection_report_hides_empty_state_after_rows_arrive(self):
        page = object.__new__(ReportsPage)
        page._coll_page = 0
        page._coll_cursors = [None]
        page.coll_tree = MagicMock()
        page.coll_tree.get_children.return_value = []
        page.coll_empty_state = MagicMock()
        page._coll_page_lbl = MagicMock()
        page._coll_prev_btn = MagicMock()
        page._coll_next_btn = MagicMock()

        page._update_coll_table({"items": [], "has_more": False})
        page.coll_empty_state.show.assert_called_once()
        page._update_coll_table({
            "items": [["2026-01-01", "OR-1", "TD-1", "Owner", "RPT", 2026, 50]],
            "has_more": False,
        })
        page.coll_empty_state.hide.assert_called_once_with()
        page.coll_tree.insert.assert_called_once()

    def test_barangay_report_shows_empty_and_hides_for_rows(self):
        page = object.__new__(ReportsPage)
        page.brgy_tree = MagicMock()
        page.brgy_tree.get_children.return_value = []
        page.brgy_empty_state = MagicMock()
        page.brgy_year_lbl = MagicMock()
        page.brgy_total_lbl = MagicMock()

        page._update_brgy_table([], 2026)
        page.brgy_empty_state.show.assert_called_once()
        page._update_brgy_table([["NORTH", 1, 2, 3, 4, 5, 6]], 2026)
        page.brgy_empty_state.hide.assert_called_once_with()
        page.brgy_tree.insert.assert_called_once()

    def test_receivables_no_data_uses_inline_notice(self):
        page = object.__new__(ReportsPage)
        page.receiv_content = MagicMock()
        page.receiv_content.winfo_children.return_value = []
        with patch("ui.reports.show_empty_content") as show:
            page._update_receiv_summary(None)
        self.assertEqual(show.call_args.kwargs["title"], "No receivables data")

    def test_reconciliation_no_data_disables_exports_and_shows_notice(self):
        page = object.__new__(ReportsPage)
        page.recon_content = MagicMock()
        page.recon_content.winfo_children.return_value = []
        page.recon_export_excel_btn = MagicMock()
        page.recon_export_pdf_btn = MagicMock()
        page._last_reconciliation_payload = {"stale": True}
        with patch("ui.reports.show_empty_content") as show:
            page._update_reconciliation(None)
        self.assertIsNone(page._last_reconciliation_payload)
        page.recon_export_excel_btn.configure.assert_called_once_with(state="disabled")
        page.recon_export_pdf_btn.configure.assert_called_once_with(state="disabled")
        self.assertEqual(show.call_args.kwargs["title"], "No reconciliation data")

class TestLedgerColumns(unittest.TestCase):
    def test_pdf_status_is_internal_and_not_a_visible_column(self):
        setup_source = inspect.getsource(LedgerPage.setup_ui)
        update_source = inspect.getsource(LedgerPage._update_ui)

        self.assertNotIn('"pdf_copy"', setup_source)
        self.assertNotIn("ledger.table.status", setup_source)
        self.assertIn("self.column_labels", setup_source)
        self.assertIn(
            "self._ledger_receipt_statuses[item_id] = status_code", update_source
        )
        self.assertNotIn("f_r.append(status)", update_source)

    def test_empty_state_can_be_shown_with_guidance_and_hidden_for_rows(self):
        ledger = object.__new__(LedgerPage)
        ledger.empty_state = MagicMock()
        ledger.empty_state_title = MagicMock()
        ledger.empty_state_message = MagicMock()

        ledger._set_empty_state(
            True,
            title="No matching records",
            message="Check the search and try again.",
        )

        ledger.empty_state_title.configure.assert_called_once_with(
            text="No matching records"
        )
        ledger.empty_state_message.configure.assert_called_once_with(
            text="Check the search and try again."
        )
        ledger.empty_state.place.assert_called_once_with(
            relx=0.5, rely=0.54, anchor="center"
        )
        ledger.empty_state.tkraise.assert_called_once_with()

        ledger._set_empty_state(False)
        ledger.empty_state.place_forget.assert_called_once_with()

    def test_ledger_distinguishes_initial_empty_and_no_payment_states(self):
        setup_source = inspect.getsource(LedgerPage.setup_ui)
        update_source = inspect.getsource(LedgerPage._update_ui)

        self.assertIn("No records to display", setup_source)
        self.assertIn("No payments recorded", update_source)
        self.assertIn("No matching records", update_source)


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

    def test_dashboard_uses_recent_rows_from_summary_snapshot(self):
        home = object.__new__(DashboardHomePage)
        home.parent = MagicMock()
        recent = [{"id": 9, "or_number": "OR-9", "amount": 397.42}]
        home.callbacks = {
            "get_summary": MagicMock(
                return_value={"total_properties": 100, "recent_payments": recent}
            ),
            "get_trend": MagicMock(return_value=[]),
            "get_recent": MagicMock(return_value=[]),
        }
        home._update_ui = MagicMock()
        home._hide_loading = MagicMock()

        with patch(
            "ui.dashboard_home.system.get_system_stats", return_value={"pool": {}}
        ):
            home.refresh_data()

        home.callbacks["get_recent"].assert_not_called()
        scheduled_render = home.parent.after.call_args.args[1]
        scheduled_render()
        args = home._update_ui.call_args.args
        self.assertEqual(args[2], recent)
        self.assertIsNone(args[3])

    def test_dashboard_recent_rows_survive_chart_render_failure(self):
        home = object.__new__(DashboardHomePage)
        home.parent = MagicMock()
        home._hide_loading = MagicMock()
        home._render_recent_collections = MagicMock()
        home.bar_chart = MagicMock()
        home.bar_chart.draw.side_effect = RuntimeError("chart failed")
        home.stat_cards = {
            name: MagicMock()
            for name in (
                "total_properties",
                "collections_today",
                "receipts_today",
                "collections_month",
            )
        }
        home.stat_cards["total_properties"].winfo_exists.return_value = True
        recent = [{"id": 9, "or_number": "OR-9", "amount": 397.42}]

        with (
            patch("ui.dashboard_home.show_toast"),
            patch("utils.log_error_to_file") as log_error,
        ):
            home._update_ui(
                {
                    "total_properties": 100,
                    "collections_today": 0,
                    "receipts_today": 0,
                    "collections_month": 397.42,
                },
                [{"month": "2026-09", "total": 397.42}],
                recent,
            )

        home._render_recent_collections.assert_called_once_with(recent, load_error=None)
        log_error.assert_called_once()

    def test_chart_draw_completes_with_plain_currency_formatter(self):
        chart = object.__new__(ModernChartWidget)
        chart.matplotlib = object()
        chart.figure = Figure()
        chart.ax = chart.figure.add_subplot(111)
        chart.canvas = MagicMock()

        chart.draw(["Sep 26"], [47975.49])

        self.assertIsInstance(chart.ax.yaxis.get_major_formatter(), FuncFormatter)
        chart.canvas.draw.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
