"""Desktop-only export-dialog regressions; no database, network or live UI."""

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import sys

import pytest

# Use the same desktop-safe imports as the packaged client and UI tests.
project = Path(__file__).resolve().parents[1]
desktop = str(project / "clients" / "desktop")
if desktop in sys.path:
    sys.path.remove(desktop)
sys.path.insert(0, desktop)

import ui.reports as reports_ui


@pytest.mark.parametrize(
    "export_format,extension,label",
    [
        ("excel", ".xlsx", "Excel workbook (*.xlsx)"),
        ("pdf", ".pdf", "PDF document (*.pdf)"),
    ],
)
def test_dialog_offers_only_the_button_format(export_format, extension, label):
    options = reports_ui.report_export_dialog_options(
        f"Report_2026{extension}", export_format
    )
    assert options["initialfile"] == f"Report_2026{extension}"
    assert options["defaultextension"] == extension
    assert options["filetypes"] == [(label, f"*{extension}")]


def test_dialog_normalizes_case_without_changing_format():
    options = reports_ui.report_export_dialog_options("Report.XLSX", " Excel ")
    assert options["initialfile"] == "Report.xlsx"
    assert options["defaultextension"] == ".xlsx"


@pytest.mark.parametrize(
    "path,export_format",
    [("Report.pdf", "excel"), ("Report.xlsx", "pdf"), ("Report", "excel")],
)
def test_download_format_mismatch_is_rejected(path, export_format):
    with pytest.raises(ValueError, match="generated report does not match"):
        reports_ui.report_export_dialog_options(path, export_format)


def test_unsupported_export_format_is_rejected():
    with pytest.raises(ValueError, match="Unsupported report export"):
        reports_ui.report_export_dialog_options("Report.csv", "csv")


@pytest.mark.parametrize(
    "method,button_name,format_name,client_function,report_type,selected_year,expected_year",
    [
        (
            "_export_receivables_excel",
            "receiv_export_excel_btn",
            "excel",
            "export_report_excel",
            "receivables",
            "2026",
            "2026",
        ),
        (
            "_export_brgy_excel",
            "brgy_export_excel_btn",
            "excel",
            "export_report_excel",
            "receivables_by_barangay",
            "All Years",
            "All",
        ),
        (
            "_export_receivables_barangay_pdf",
            "receiv_export_brgy_btn",
            "pdf",
            "download_receivables_by_barangay_pdf",
            None,
            "2026",
            2026,
        ),
        (
            "_export_brgy_pdf",
            "brgy_export_pdf_btn",
            "pdf",
            "download_receivables_by_barangay_pdf",
            None,
            "All Years",
            None,
        ),
    ],
)
def test_each_button_selects_its_own_format_and_keeps_year_scope(
    method,
    button_name,
    format_name,
    client_function,
    report_type,
    selected_year,
    expected_year,
):
    page = reports_ui.ReportsPage.__new__(reports_ui.ReportsPage)
    page.receiv_year_cb = SimpleNamespace(get=lambda: selected_year)
    page.brgy_year_cb = SimpleNamespace(get=lambda: selected_year)
    button = MagicMock()
    setattr(page, button_name, button)
    page._export_with_feedback = MagicMock()
    with patch.object(reports_ui.billing, client_function) as client:
        getattr(page, method)()
        arguments = page._export_with_feedback.call_args.args
        assert arguments[0] is button
        assert arguments[2] == format_name
        arguments[1]()
        if report_type:
            client.assert_called_once_with(report_type, year=expected_year)
        else:
            client.assert_called_once_with(year=expected_year)


def export_fixture(
    stack,
    *,
    source="Report.xlsx",
    destination="Saved.xlsx",
    export_format="excel",
    worker_error=None,
):
    page = reports_ui.ReportsPage.__new__(reports_ui.ReportsPage)
    page.container = MagicMock()
    page._open_file = MagicMock()
    callbacks = []
    page.container.after.side_effect = lambda delay, callback: callbacks.append(
        callback
    )
    button = MagicMock()
    button.cget.return_value = (
        "EXPORT EXCEL" if export_format == "excel" else "EXPORT PDF"
    )

    def thread_factory(*, target, daemon):
        assert daemon is True
        thread = MagicMock()
        thread.start.side_effect = target
        return thread

    stack.enter_context(
        patch.object(reports_ui.threading, "Thread", side_effect=thread_factory)
    )
    dialog = stack.enter_context(
        patch.object(
            reports_ui.filedialog, "asksaveasfilename", return_value=destination
        )
    )
    copy = stack.enter_context(patch.object(reports_ui.shutil, "copy2"))
    ask_open = stack.enter_context(
        patch.object(reports_ui.messagebox, "askyesno", return_value=False)
    )
    show_error = stack.enter_context(patch.object(reports_ui.messagebox, "showerror"))
    worker = MagicMock(return_value=source, side_effect=worker_error)
    page._export_with_feedback(button, worker, export_format)
    assert button.configure.call_args.kwargs["state"] == "disabled"
    # Native dialogs, filesystem copies and button restoration happen only
    # after the queued UI callback, not in the background generation worker.
    dialog.assert_not_called()
    copy.assert_not_called()
    assert len(callbacks) == 1
    return SimpleNamespace(
        page=page,
        button=button,
        callback=callbacks[0],
        dialog=dialog,
        copy=copy,
        ask_open=ask_open,
        show_error=show_error,
    )


@pytest.mark.parametrize(
    "extension,export_format", [(".xlsx", "excel"), (".pdf", "pdf")]
)
def test_save_callback_uses_one_format_and_copies_the_generated_report(
    extension, export_format
):
    with ExitStack() as stack:
        run = export_fixture(
            stack,
            source=f"Report{extension}",
            destination=f"Saved{extension}",
            export_format=export_format,
        )
        run.callback()
        assert run.dialog.call_args.kwargs["defaultextension"] == extension
        assert len(run.dialog.call_args.kwargs["filetypes"]) == 1
        run.copy.assert_called_once_with(f"Report{extension}", f"Saved{extension}")
        run.show_error.assert_not_called()
        run.page._open_file.assert_not_called()
        assert run.button.configure.call_args.kwargs["state"] == "normal"


def test_cancel_restores_the_button_without_saving_or_opening():
    with ExitStack() as stack:
        run = export_fixture(stack, destination="")
        run.callback()
        run.copy.assert_not_called()
        run.ask_open.assert_not_called()
        run.show_error.assert_not_called()
        assert run.button.configure.call_args.kwargs == {
            "text": "EXPORT EXCEL",
            "state": "normal",
        }


@pytest.mark.parametrize("destination", ["Saved.pdf", "Saved.xlsx.pdf", "Saved"])
def test_wrong_typed_extension_does_not_save_excel_bytes_as_another_format(destination):
    with ExitStack() as stack:
        run = export_fixture(stack, destination=destination)
        run.callback()
        run.copy.assert_not_called()
        run.ask_open.assert_not_called()
        assert (
            "Changing the filename does not convert" in run.show_error.call_args.args[1]
        )
        assert run.button.configure.call_args.kwargs["state"] == "normal"


def test_failed_download_restores_the_button_without_a_save_dialog():
    with ExitStack() as stack:
        run = export_fixture(
            stack, worker_error=RuntimeError("Synthetic download failure")
        )
        run.callback()
        run.dialog.assert_not_called()
        run.copy.assert_not_called()
        run.show_error.assert_called_once_with(
            "Export Failed", "Synthetic download failure"
        )
        assert run.button.configure.call_args.kwargs["state"] == "normal"


def test_wrong_download_format_does_not_reach_the_save_dialog():
    with ExitStack() as stack:
        run = export_fixture(stack, source="Report.pdf", export_format="excel")
        run.callback()
        run.dialog.assert_not_called()
        run.copy.assert_not_called()
        assert "generated report does not match" in run.show_error.call_args.args[1]
        assert run.button.configure.call_args.kwargs["state"] == "normal"


@pytest.mark.parametrize("failing_operation", ["dialog", "copy"])
def test_save_failure_shows_an_error_and_restores_the_button(failing_operation):
    with ExitStack() as stack:
        run = export_fixture(stack)
        getattr(run, failing_operation).side_effect = PermissionError(
            "Synthetic save failure"
        )
        run.callback()
        run.ask_open.assert_not_called()
        run.show_error.assert_called_once_with(
            "Export Failed", "Synthetic save failure"
        )
        assert run.button.configure.call_args.kwargs["state"] == "normal"


def test_successfully_saved_report_opens_only_when_approved():
    with ExitStack() as stack:
        run = export_fixture(stack)
        run.ask_open.return_value = True
        run.callback()
        run.copy.assert_called_once_with("Report.xlsx", "Saved.xlsx")
        run.page._open_file.assert_called_once_with("Saved.xlsx")
        assert run.button.configure.call_args.kwargs["state"] == "normal"


def test_clearer_coverage_label_keeps_cash_plus_advance_payment_calculation():
    page = reports_ui.ReportsPage.__new__(reports_ui.ReportsPage)
    page.receiv_content = MagicMock()
    page.receiv_content.winfo_children.return_value = []
    labels = []

    def label(*args, **kwargs):
        labels.append(kwargs.get("text", ""))
        return MagicMock()

    with (
        patch.object(reports_ui.ctk, "CTkFrame", return_value=MagicMock()),
        patch.object(reports_ui.ctk, "CTkLabel", side_effect=label),
        patch.object(reports_ui.ctk, "CTkProgressBar", return_value=MagicMock()),
        patch.object(reports_ui.ttk, "Treeview", return_value=MagicMock()),
    ):
        page._update_receiv_summary(
            {
                "report_year": 2026,
                "beginning_receivable": 100000,
                "current_year_assessment": 0,
                "collections": 30000,
                "prepaid_current_year": 3800,
                "adjustments": 0,
                "ending_receivable": 66200,
                "ending_credit": 0,
            },
            [],
        )
    assert f"{reports_ui.RECEIVABLES_COVERAGE_LABEL}: 33.8%" in labels
    assert reports_ui.RECEIVABLES_COVERAGE_HELP in labels
    assert "CASH + ADVANCE PAYMENTS APPLIED" in labels
    assert not any("Applied Cash/Credit Coverage" in text for text in labels)


def test_barangay_footer_names_the_same_separate_credit_value():
    page = reports_ui.ReportsPage.__new__(reports_ui.ReportsPage)
    page.brgy_tree = MagicMock()
    page.brgy_tree.get_children.return_value = []
    page.brgy_empty_state = MagicMock()
    page.brgy_year_lbl = MagicMock()
    page.brgy_total_lbl = MagicMock()
    page._update_brgy_table([["SYNTHETIC", 200000, 4000, 0, 0, 2500, 2000, 500]], 2026)
    text = page.brgy_total_lbl.configure.call_args.kwargs["text"]
    assert f"{reports_ui.RECORDED_CREDIT_BALANCE_LABEL}: P 500.00" in text
    assert "2,000.00" in text


def test_pdf_credit_header_wraps_within_the_existing_column_without_smaller_font():
    from backend.generators import report_gen
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth

    canvas = MagicMock()
    label = reports_ui.RECORDED_CREDIT_BALANCE_LABEL.replace(" Credit ", "\nCredit ")
    bottom = report_gen._draw_table_header_row(
        canvas, 0, 100, [(label, 32 * mm)], multiline=True
    )
    canvas.setFont.assert_called_once_with("Helvetica-Bold", 7.5)
    assert bottom == 100 - 9 * mm
    calls = canvas.drawCentredString.call_args_list
    assert [call.args[2] for call in calls] == ["RECORDED", "CREDIT BALANCE"]
    for call in calls:
        assert bottom < call.args[1] < 100
        assert stringWidth(call.args[2], "Helvetica-Bold", 7.5) <= 32 * mm - 3 * mm


def test_existing_pdf_header_layout_stays_unchanged_unless_wrapping_is_requested():
    from backend.generators import report_gen
    from reportlab.lib.units import mm

    canvas = MagicMock()
    bottom = report_gen._draw_table_header_row(canvas, 0, 100, [("TD No.", 32 * mm)])
    assert bottom == 100 - 7 * mm
    canvas.drawCentredString.assert_called_once_with(16 * mm, 100 - 5 * mm, "TD NO.")
