"""Synthetic RCD metadata tests; no office workbook, database or network."""

import asyncio
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import sys

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils import rcd_metadata
from api_clients import reports_service
from backend.routes import reports

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))
from ui import reports as reports_ui


@pytest.mark.parametrize(
    "instant,expected",
    [
        (datetime(2026, 10, 18, 15, 59, tzinfo=timezone.utc), date(2026, 10, 18)),
        (datetime(2026, 10, 18, 16, 1, tzinfo=timezone.utc), date(2026, 10, 19)),
    ],
)
def test_office_date_uses_philippine_midnight(instant, expected):
    clock = MagicMock()
    clock.now.side_effect = lambda zone: instant.astimezone(zone)
    with patch.object(rcd_metadata, "datetime", clock):
        assert rcd_metadata.philippine_report_date() == expected
    clock.now.assert_called_once_with(rcd_metadata.PHILIPPINE_TIMEZONE)


def test_metadata_preserves_official_number_and_fixed_date():
    result = rcd_metadata.resolve_rcd_metadata(
        " 001/2026-10 ", " Sample Accountable Officer ", "2026-10-15", required=True
    )
    assert result.report_number == "001/2026-10"
    assert result.accountable_officer == "Sample Accountable Officer"
    assert result.report_date == date(2026, 10, 15)


def test_older_clients_can_omit_new_fields_and_receive_today():
    with patch.object(
        rcd_metadata, "philippine_report_date", return_value=date(2026, 10, 19)
    ):
        result = rcd_metadata.resolve_rcd_metadata()
    assert result == rcd_metadata.RcdMetadata("", "", date(2026, 10, 19))


@pytest.mark.parametrize("number,officer", [("", "Sample"), ("001", " "), ("", "")])
def test_new_dialog_requires_report_identity(number, officer):
    with pytest.raises(ValueError, match="report number and accountable officer"):
        rcd_metadata.resolve_rcd_metadata(number, officer, required=True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"report_number": "x" * 65},
        {"accountable_officer": "x" * 121},
        {"report_number": "001\n002"},
        {"accountable_officer": "Sample\tOfficer"},
        {"report_date": "2026-02-30"},
        {"report_date": "20261019"},
        {"report_date": ""},
        {"report_date": "2026-10-19T00:00:00"},
    ],
)
def test_invalid_metadata_is_not_silently_replaced(kwargs):
    with pytest.raises(ValueError):
        rcd_metadata.resolve_rcd_metadata(**kwargs)


def test_download_passes_all_three_fields_without_changing_collection_period():
    with patch.object(
        reports_service, "api_download_file", return_value="sample.xlsx"
    ) as download:
        result = reports_service.download_coa_rcd(
            "2026-09-01",
            "2026-09-30",
            "Sample Liquidator",
            "Sample Treasurer",
            report_number="0007",
            accountable_officer="Sample Collector",
            report_date="2026-10-19",
        )
    assert result == "sample.xlsx"
    download.assert_called_once_with(
        "GET",
        "/reports/rcd",
        params={
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "liquidating_officer": "Sample Liquidator",
            "treasurer": "Sample Treasurer",
            "report_number": "0007",
            "accountable_officer": "Sample Collector",
            "report_date": "2026-10-19",
        },
    )


def test_route_forwards_metadata_and_commits_export_audit_only():
    db = MagicMock()
    with (
        patch.object(
            reports, "generate_coa_rcd_excel", return_value=BytesIO(b"sample")
        ) as generate,
        patch.object(reports, "log_action") as audit,
    ):
        response = asyncio.run(
            reports.export_coa_rcd(
                start_date="2026-09-01",
                end_date="2026-09-30",
                liquidating_officer="Sample Liquidator",
                treasurer="Sample Treasurer",
                report_number="0007",
                accountable_officer="Sample Collector",
                report_date="2026-10-19",
                current_user={"id": 1},
                db=db,
            )
        )
    assert response.status_code == 200
    assert generate.call_args.kwargs["report_number"] == "0007"
    assert generate.call_args.kwargs["accountable_officer"] == "Sample Collector"
    assert generate.call_args.kwargs["report_date"] == date(2026, 10, 19)
    assert generate.call_args.kwargs["start_date"] == datetime(2026, 9, 1)
    db.add.assert_not_called()
    db.query.assert_not_called()
    audit.assert_called_once()
    db.commit.assert_called_once()


def test_route_rejects_invalid_report_date_before_generation_or_commit():
    db = MagicMock()
    with patch.object(reports, "generate_coa_rcd_excel") as generate:
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                reports.export_coa_rcd(
                    start_date="2026-09-01",
                    end_date="2026-09-30",
                    report_date="2026-02-30",
                    current_user={"id": 1},
                    db=db,
                )
            )
    assert error.value.status_code == 422
    generate.assert_not_called()
    db.commit.assert_not_called()


def test_http_query_fields_arrive_as_literal_metadata():
    app = FastAPI()
    app.include_router(reports.router)
    db = MagicMock()
    app.dependency_overrides[reports.admin_only] = lambda: {"id": 1}
    app.dependency_overrides[reports.get_db] = lambda: db
    with (
        patch.object(
            reports, "generate_coa_rcd_excel", return_value=BytesIO(b"sample")
        ) as generate,
        patch.object(reports, "log_action"),
        TestClient(app) as client,
    ):
        response = client.get(
            "/reports/rcd",
            params={
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
                "report_number": "001/2026-10",
                "accountable_officer": "Sample Collector",
                "report_date": "2026-10-19",
            },
        )
    assert response.status_code == 200
    assert generate.call_args.kwargs["report_number"] == "001/2026-10"
    assert generate.call_args.kwargs["accountable_officer"] == "Sample Collector"
    assert generate.call_args.kwargs["report_date"] == date(2026, 10, 19)


def _dialog(**overrides):
    values = {
        "report_number_ent": " 0007 ",
        "accountable_officer_ent": " Sample Collector ",
        "report_date_ent": "2026-10-19",
        "officer_ent": "Sample Liquidator",
        "treasurer_ent": "Sample Treasurer",
    }
    values.update(overrides)
    return SimpleNamespace(
        **{
            name: SimpleNamespace(get=lambda value=value: value)
            for name, value in values.items()
        },
        callback=MagicMock(),
        destroy=MagicMock(),
    )


def test_dialog_exports_metadata_separately_from_signatory_names():
    dialog = _dialog()
    reports_ui.SignatoriesModal.on_export(dialog)
    dialog.callback.assert_called_once_with(
        "Sample Liquidator",
        "Sample Treasurer",
        report_number="0007",
        accountable_officer="Sample Collector",
        report_date="2026-10-19",
    )
    dialog.destroy.assert_called_once()


@pytest.mark.parametrize(
    "overrides",
    [
        {"report_number_ent": ""},
        {"accountable_officer_ent": ""},
        {"report_date_ent": "2026-02-30"},
        {"officer_ent": ""},
    ],
)
def test_invalid_dialog_keeps_fields_open_and_does_not_export(overrides):
    dialog = _dialog(**overrides)
    with patch.object(reports_ui.messagebox, "showerror") as showerror:
        reports_ui.SignatoriesModal.on_export(dialog)
    showerror.assert_called_once()
    dialog.callback.assert_not_called()
    dialog.destroy.assert_not_called()


def test_dialog_autofills_officer_and_office_date_but_not_official_number():
    dialog = SimpleNamespace(
        configure=MagicMock(), on_export=MagicMock(), destroy=MagicMock()
    )
    entries = [MagicMock() for _ in range(5)]
    with (
        patch.object(reports_ui.ctk, "CTkFrame"),
        patch.object(reports_ui.ctk, "CTkScrollableFrame"),
        patch.object(reports_ui.ctk, "CTkLabel"),
        patch.object(reports_ui.ctk, "CTkButton"),
        patch.object(reports_ui.ctk, "CTkEntry", side_effect=entries),
        patch.object(
            reports_ui, "philippine_report_date", return_value=date(2026, 10, 19)
        ),
    ):
        reports_ui.SignatoriesModal.setup_ui(dialog, "Sample Collector")
    entries[0].insert.assert_not_called()
    entries[1].insert.assert_called_once_with(0, "Sample Collector")
    entries[2].insert.assert_called_once_with(0, "2026-10-19")
    entries[3].insert.assert_not_called()


def test_export_worker_forwards_dialog_metadata_and_retains_collection_period():
    page = SimpleNamespace(
        get_selected_date_range=lambda: ("2026-09-01", "2026-09-30"),
        _show_loading=MagicMock(),
        _hide_loading=MagicMock(),
        export_rcd_btn=MagicMock(),
        container=SimpleNamespace(after=lambda delay, fn: fn()),
    )
    with (
        patch.object(reports_ui.threading, "Thread") as thread,
        patch.object(
            reports_ui.reports_api, "download_coa_rcd", return_value="sample.xlsx"
        ) as download,
        patch.object(reports_ui.filedialog, "asksaveasfilename", return_value=""),
    ):
        reports_ui.ReportsPage.export_coa_rcd(
            page,
            "Sample Liquidator",
            "Sample Treasurer",
            report_number="0007",
            accountable_officer="Sample Collector",
            report_date="2026-10-19",
        )
        thread.call_args.kwargs["target"]()
    download.assert_called_once_with(
        start_date="2026-09-01",
        end_date="2026-09-30",
        liquidating_officer="Sample Liquidator",
        treasurer="Sample Treasurer",
        report_number="0007",
        accountable_officer="Sample Collector",
        report_date="2026-10-19",
    )
    page._hide_loading.assert_called_once()
