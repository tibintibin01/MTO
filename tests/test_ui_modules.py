import unittest
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
from ui.dashboard_home import DashboardHomePage
from ui.assessment_roll import (
    AssessmentRollPage,
    parse_assessment_roll_as_of_year,
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


class TestDashboardHome(unittest.TestCase):
    def test_dashboard_refresh_schedules_render_with_service_data(self):
        home = object.__new__(DashboardHomePage)
        home.parent = MagicMock()
        home.callbacks = {
            "trigger_backup": MagicMock(),
            "get_summary": MagicMock(return_value={"total_properties": 100}),
            "get_trend": MagicMock(return_value=[]),
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
        scheduled_render()
        home._update_ui.assert_called_once_with(
            {"total_properties": 100, "infra_stats": {"pool": {}}},
            [],
        )


if __name__ == "__main__":
    unittest.main()
