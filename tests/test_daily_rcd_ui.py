"""Desktop daily RCD interactions use stubs, never a running office app/API."""

from datetime import date
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))
from ui import rcd_daily
from api_clients import reports_service


def test_register_posts_cannot_be_queued_as_offline_financial_changes():
    with patch.object(reports_service, "api_request") as request:
        reports_service.register_rcd_officer("SAMPLE OFFICER")
        assert request.call_args.kwargs["queue_offline"] is False
        reports_service.register_rcd_booklet(1, "000123", "000172", "2026-10-01")
        assert request.call_args.kwargs["queue_offline"] is False
        assert request.call_args.kwargs["data"]["collector_id"] == 1


def test_export_request_carries_date_owner_number_and_exact_preview_signature():
    with patch.object(reports_service, "api_download_file") as download:
        reports_service.download_daily_rcd(7, "2026-10-18", "0009", "a" * 64)
    download.assert_called_once_with(
        "GET",
        "/reports/rcd/daily/excel",
        params={
            "collector_id": 7,
            "report_date": "2026-10-18",
            "report_number": "0009",
            "expected_signature": "a" * 64,
        },
    )


def test_scope_uses_registered_id_not_edited_label_or_encoder():
    fake = SimpleNamespace(
        registry={"officers": [{"id": 7, "name": "SAMPLE COLLECTOR"}]}
    )
    selector = SimpleNamespace(get=lambda: "7: SAMPLE COLLECTOR")
    assert rcd_daily.DailyRcdWindow._officer_id(fake, selector) == 7
    with pytest.raises(ValueError):
        rcd_daily.DailyRcdWindow._officer_id(
            fake, SimpleNamespace(get=lambda: "unknown_encoder")
        )


@pytest.mark.skipif(
    os.name != "nt", reason="Invisible Windows Tk layout and interaction test"
)
def test_minimum_layout_preview_invalidation_and_excel_action(tmp_path):
    import customtkinter as ctk

    registry = {
        "revision": 1,
        "officers": [{"id": 7, "name": "SAMPLE COLLECTOR"}],
        "booklets": [
            {
                "id": 1,
                "collector_id": 7,
                "first_or": "000123",
                "last_or": "000172",
                "issued_on": "2026-10-01",
            }
        ],
    }
    preview = {
        "collector": {"id": 7, "name": "SAMPLE COLLECTOR"},
        "report_date": "2026-10-19",
        "source_signature": "a" * 64,
        "issues": [],
        "receipt_count": 1,
        "payment_row_count": 1,
        "other_officer_payment_rows": 0,
        "totals": {"basic_cash": "324.00", "sef_cash": "324.00", "cash": "648.00"},
        "receipts": [
            {
                "or_number": "000123",
                "payment_ids": [1],
                "basic_cash": "324.00",
                "sef_cash": "324.00",
                "cash": "648.00",
            }
        ],
        "limitations": ["Office verification remains required."],
    }
    root = ctk.CTk()
    root.withdraw()
    window = None
    try:
        root.attributes("-alpha", 0)
        with patch.object(
            rcd_daily, "philippine_report_date", return_value=date(2026, 10, 19)
        ):
            window = rcd_daily.DailyRcdWindow(root)
        window.withdraw()
        window.attributes("-alpha", 0)
        window.after_cancel(window._initial_load)
        window.geometry("780x600")
        root.deiconify()
        root.update()
        window.deiconify()
        window.tabs.set("Daily RCD")
        ready = rcd_daily.tk.BooleanVar(master=root, value=False)
        root.after(300, lambda: ready.set(True))
        root.wait_variable(ready)  # Process Windows' deferred top-level mapping.
        for widget in (
            window.day,
            window.collector,
            window.number,
            window.export_button,
        ):
            assert widget.winfo_ismapped()
            assert widget.winfo_width() > 30
            assert (
                widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width()
            )
        assert window.day.get() == "2026-10-19"
        assert window.export_button.cget("state") == "disabled"

        # Synchronous stub requests exercise callbacks without network or threads.
        window._request = lambda operation, callback: callback(operation())
        with patch.object(
            rcd_daily.reports_api, "get_rcd_register", return_value=registry
        ):
            window._load_register()
        with patch.object(rcd_daily.reports_api, "get_daily_rcd", return_value=preview):
            window._load_preview()
        window._update_export()
        assert window.export_button.cget("state") == "normal"
        assert len(window.receipts.get_children()) == 1
        window.number.insert(0, "0009")
        window.remittance_review = {"cash_check_confirmed": True, "checks": []}
        source = tmp_path / "synthetic.xlsx"
        source.write_bytes(b"synthetic-export-only")
        destination = tmp_path / "saved.xlsx"
        with (
            patch.object(
                rcd_daily.filedialog, "asksaveasfilename", return_value=str(destination)
            ) as dialog,
            patch.object(
                rcd_daily.reports_api, "download_daily_rcd", return_value=str(source)
            ) as download,
            patch.object(rcd_daily.messagebox, "showinfo"),
        ):
            window._export()
        assert destination.read_bytes() == source.read_bytes()
        download.assert_called_once_with(
            7,
            "2026-10-19",
            "0009",
            "a" * 64,
            review={"cash_check_confirmed": True, "checks": []},
        )
        assert dialog.call_args.kwargs["filetypes"] == [
            ("Excel workbook (*.xlsx)", "*.xlsx")
        ]

        window.day.delete(0, "end")
        window.day.insert(0, "2026-10-18")
        window._invalidate()
        assert window.preview is None
        assert window.remittance_review is None
        assert not window.receipts.get_children()
        assert window.export_button.cget("state") == "disabled"
        window.tabs.set("Booklet Register")
        root.update()
        for widget in (
            window.book_collector,
            window.book_first,
            window.book_last,
            window.book_date,
        ):
            assert widget.winfo_ismapped()
            assert (
                widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width()
            )
    finally:
        if window is not None:
            window._close()
        root.destroy()
