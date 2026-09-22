from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from clients.desktop.theme_manager import ModernTheme
from scripts import phase8_accessibility_preflight as preflight
from ui.accessibility import bind_keyboard_activation, contrast_ratio


class FakeCanvas:
    def __init__(self):
        self.configured = {}
        self.bindings = {}

    def configure(self, **kwargs):
        self.configured.update(kwargs)

    def bind(self, sequence, command, add=None):
        self.bindings[sequence] = (command, add)


class FakeButton:
    def __init__(self, state="normal"):
        self._canvas = FakeCanvas()
        self._state = state
        self._border_width = 0
        self._border_color = "#000000"
        self.configurations = []

    def configure(self, **kwargs):
        self.configurations.append(kwargs)


def test_contrast_ratio_matches_wcag_reference_extremes():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)


def test_accessible_surface_tokens_meet_normal_text_contrast():
    assert contrast_ratio("#ffffff", ModernTheme.PRIMARY_SURFACE) >= 4.5
    assert contrast_ratio("#ffffff", ModernTheme.DANGER_SURFACE) >= 4.5
    assert contrast_ratio(ModernTheme.DANGER_TEXT_DARK, "#0a1628") >= 4.5


def test_contrast_rejects_non_rgb_notation():
    with pytest.raises(ValueError, match="six-digit"):
        contrast_ratio("white", "#000000")


def test_keyboard_binding_adds_tab_focus_enter_space_and_focus_ring():
    button = FakeButton()
    command = Mock()

    focus_target = bind_keyboard_activation(button, command)

    assert focus_target is button._canvas
    assert button._canvas.configured["takefocus"] is True
    assert set(button._canvas.bindings) == {
        "<Return>",
        "<space>",
        "<FocusIn>",
        "<FocusOut>",
    }
    assert button._canvas.bindings["<Return>"][0]() == "break"
    assert button._canvas.bindings["<space>"][0]() == "break"
    assert command.call_count == 2
    button._canvas.bindings["<FocusIn>"][0]()
    assert button.configurations[-1]["border_width"] == 2
    button._canvas.bindings["<FocusOut>"][0]()
    assert button.configurations[-1] == {
        "border_width": 0,
        "border_color": "#000000",
    }


def test_keyboard_binding_does_not_invoke_disabled_button():
    button = FakeButton(state="disabled")
    command = Mock()

    bind_keyboard_activation(button, command)
    button._canvas.bindings["<Return>"][0]()

    command.assert_not_called()


def test_phase8_current_source_contracts_and_contrast_pass():
    contracts = preflight.capture_ui_contracts()
    contrast = preflight.capture_contrast_policy()

    assert contracts["status"] == "PASS"
    assert contracts["login_keyboard_binding_count"] >= 4
    assert contracts["navigation_keyboard_binding_count"] >= 4
    assert contrast["status"] == "PASS"


def test_phase8_contracts_reject_stale_mouse_only_shell(tmp_path):
    for relative_name in preflight.TARGET_FILES:
        path = tmp_path / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# placeholder\n", encoding="utf-8")
    main = tmp_path / "clients" / "desktop" / "main.py"
    main.write_text('self.peek_lbl = object()\nVERSION = "v2.1.0"\n', encoding="utf-8")

    report = preflight.capture_ui_contracts(tmp_path)
    codes = {finding["code"] for finding in report["findings"]}

    assert report["status"] == "FAIL"
    assert "STALE_VISIBLE_VERSION" in codes
    assert "MOUSE_ONLY_PASSWORD_CONTROL" in codes


def test_phase8_syntax_gate_reports_missing_and_invalid_sources(tmp_path):
    first = tmp_path / preflight.TARGET_FILES[0]
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("if :\n", encoding="utf-8")

    report = preflight.capture_python_syntax(tmp_path)
    codes = {finding["code"] for finding in report["findings"]}

    assert report["status"] == "FAIL"
    assert "UI_SOURCE_INVALID" in codes
    assert "ACCESSIBILITY_MODULE_MISSING" in codes


def test_phase8_report_write_is_atomic_json(tmp_path):
    destination = preflight.write_report(
        {"status": "PASS", "findings": []}, tmp_path / "reports" / "phase8.json"
    )

    assert destination.is_file()
    assert destination.read_text(encoding="utf-8").endswith("\n")
