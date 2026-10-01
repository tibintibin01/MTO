"""Exercise real Tk widgets at the minimum desktop content size on Windows."""

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))


@pytest.mark.skipif(os.name != "nt", reason="Real Windows Tk layout test")
def test_assessment_controls_fit_minimum_content_width_and_modes_are_distinct():
    import customtkinter as ctk
    from ui.assessment_roll import AssessmentRollPage

    root = ctk.CTk()
    root.withdraw()
    try:
        root.geometry("920x800")
        root.attributes(
            "-alpha", 0
        )  # Test-only invisible window, no live app interaction.
        page = AssessmentRollPage(root, {"role": "admin", "username": "synthetic-test"})
        root.deiconify()
        root.update()
        for widget in (
            page.search_ent,
            page.brgy_cb,
            page.as_of_year_ent,
            page.year_from_ent,
            page.year_to_ent,
            page.refresh_btn,
            page.add_btn,
            page.import_btn,
            page.cleanup_btn,
            page.edit_btn,
            page.delete_btn,
            page.details_btn,
            page.next_btn,
        ):
            assert widget.winfo_ismapped()
            assert widget.winfo_width() > 30
            assert (
                widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width()
            )
        assert page.as_of_year_ent.cget("state") == "disabled"
        assert page.edit_btn.cget("state") == "disabled"
        for button in page.mode_control._buttons_dict.values():
            assert str(button._canvas.cget("takefocus")) in ("1", "True")
        page._change_mode(page.HISTORY_MODE)
        root.update()
        assert page.as_of_year_ent.cget("state") == "normal"
        assert page.year_from_ent.cget("state") == "disabled"
        assert page.add_btn.cget("state") == "disabled"
        assert page.import_btn.cget("state") == "disabled"
    finally:
        root.destroy()
