import inspect
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "clients" / "desktop"))

from ui.portfolio import _portfolio_name_error
from ui.users import RegisterUserModal


def test_portfolio_name_validation_limits():
    assert "at least 2" in _portfolio_name_error("")
    assert "at least 2" in _portfolio_name_error("A")
    assert _portfolio_name_error("AB") == ""
    assert _portfolio_name_error(" " + ("A" * 255) + " ") == ""
    assert "cannot exceed" in _portfolio_name_error("A" * 256)


def test_portfolio_rename_requires_a_changed_name():
    assert "different name" in _portfolio_name_error("Corporate", "Corporate")
    assert _portfolio_name_error("Corporate Properties", "Corporate") == ""


def test_registration_actions_are_outside_scrollable_form():
    source = inspect.getsource(RegisterUserModal.setup_ui)
    footer_position = source.index('btn_fr.pack(fill="x", side="bottom")')
    form_position = source.index("form = ctk.CTkScrollableFrame(")
    assert footer_position < form_position
    assert 'self.create_btn.pack(side="right"' in source
