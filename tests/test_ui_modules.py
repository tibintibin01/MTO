import unittest
from unittest.mock import MagicMock
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mocking CustomTkinter to avoid GUI initialization during tests
import customtkinter
customtkinter.set_appearance_mode = MagicMock()
customtkinter.set_default_color_theme = MagicMock()

from ui.navigation import NavigationSidebar
from ui.status_bar import ConnectivityStatusBar
from ui.dashboard_home import DashboardHomePage

class TestNavigationSidebar(unittest.TestCase):
    def setUp(self):
        self.parent = MagicMock()
        self.user_data = {"username": "testuser", "role": "admin"}
        self.callbacks = {
            "load_page": MagicMock(),
            "toggle_theme": MagicMock(),
            "toggle_language": MagicMock(),
            "logout": MagicMock()
        }
        
    def test_sidebar_initialization(self):
        # We can't easily test actual CTK widgets without a mainloop, 
        # but we can verify the logic setup
        sidebar = NavigationSidebar(self.parent, self.user_data, "testuser", self.callbacks)
        self.assertEqual(sidebar.username, "testuser")
        self.assertEqual(sidebar.callbacks, self.callbacks)

class TestStatusBar(unittest.TestCase):
    def setUp(self):
        self.parent = MagicMock()

    def test_status_bar_updates(self):
        # Verify the status bar component creation
        bar = ConnectivityStatusBar(self.parent)
        self.assertIsNotNone(bar.status_lbl)
        self.assertIsNotNone(bar.status_dot)

class TestDashboardHome(unittest.TestCase):
    def setUp(self):
        self.parent = MagicMock()
        self.user = {"role": "admin"}
        self.callbacks = {
            "trigger_backup": MagicMock(),
            "get_summary": MagicMock(return_value={"total_properties": 100}),
            "get_trend": MagicMock(return_value=[])
        }

    def test_dashboard_refresh(self):
        # Verify dashboard uses callbacks correctly
        home = DashboardHomePage(self.parent, self.user, self.callbacks)
        home.refresh_data()
        self.callbacks["get_summary"].assert_called()

if __name__ == "__main__":
    unittest.main()
