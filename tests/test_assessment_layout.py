"""Exercise real Tk widgets at the minimum desktop content size on Windows."""

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))


@pytest.mark.skipif(os.name != "nt", reason="Real Windows Tk layout test")
def test_assessment_controls_fit_minimum_content_width_and_modes_are_distinct(
    monkeypatch,
):
    import customtkinter as ctk
    from ui.assessment_roll import AssessmentRollPage
    from ui.operation_feedback import SaveFeedback
    from ui.property import PropertyEditModal, prop_svc

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
        page._record_feedback.show(
            "success", "Property updated", "TD SYNTHETIC", dismissible=True
        )
        root.update()
        assert page._record_feedback.winfo_ismapped()
        assert page._record_feedback.winfo_rooty() < page.tree.winfo_rooty()
        assert page._record_feedback.winfo_width() <= page.container.winfo_width()

        monkeypatch.setattr(
            prop_svc,
            "get_property_by_id",
            lambda *_a, **_k: {
                "id": 101,
                "td_number": "SYNTHETIC",
                "owner_name": "Sample",
                "assessed_value": 1000,
            },
        )
        modal = PropertyEditModal(root, "Edit sample property", 101, None)
        modal.attributes("-alpha", 0)
        try:
            modal._show_save_feedback(
                SaveFeedback(
                    "error",
                    "Property not updated",
                    "Check the assessed value.",
                    "assessed_value",
                )
            )
            root.update()
            assert modal._save_banner.winfo_ismapped()
            assert modal._save_banner.winfo_rooty() < modal.scroll_form.winfo_rooty()
            assert modal._save_field_hint.winfo_exists()
        finally:
            modal.destroy()
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
