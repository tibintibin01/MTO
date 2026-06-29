import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))

from ui.reports import ReportsPage


def test_reconciliation_excel_includes_payment_year_gap_summary(tmp_path):
    destination = tmp_path / "reconciliation.xlsx"
    payload = {
        "year": 2026,
        "prepared_at": "2026-06-29 09:00 AM",
        "status": "NEEDS REVIEW",
        "balanced": False,
        "equation": {
            "variance": 100.0,
            "beginning_receivable": 1000.0,
            "adjustments": 0.0,
            "tracker_variance": 0.0,
            "raw_tracker_variance": 0.0,
            "total_collectible": 3000.0,
            "collections": 1000.0,
            "ending_receivable": 2000.0,
            "equation_variance": 0.0,
            "collection_rate": 33.33,
        },
        "assessor": {
            "total_assessed_value": 100000.0,
            "basic_tax_rate": 1.0,
            "total_rpt_rate": 2.0,
            "taxable_properties": 1,
            "current_penalty": 0.0,
            "current_discount": 0.0,
            "current_levy": 2000.0,
            "current_net": 2000.0,
        },
        "treasury": {
            "basic_tax_collected": 500.0,
            "cash_collected_this_year": 1000.0,
            "prepaid_current_year": 0.0,
            "future_year_prepayments": 0.0,
            "accounts_paid": 1,
            "partial_payments": 0,
            "total_collected": 1000.0,
        },
        "delinquency": {
            "prior_year_receivables": 1000.0,
            "current_year_receivables": 1000.0,
            "delinquent_accounts": 1,
            "penalties_interest": 0.0,
            "ending_receivable": 2000.0,
        },
        "diagnostic_counts": {
            "payment_link_issues": 0,
            "overpaid_credits": 0,
            "payment_year_gaps": 1,
            "timing_prepayment_groups": 0,
        },
        "diagnostic_rows": [
            (
                "Unpaid prior year before a later paid year",
                "06-0001-00001",
                2025,
                "NORTH POBLACION | Unpaid | Later paid: 2026",
                2000.0,
            )
        ],
        "top_barangays": [],
    }

    page = ReportsPage.__new__(ReportsPage)
    page._write_reconciliation_excel(payload, str(destination))

    workbook = load_workbook(destination, data_only=True)
    diagnostics = workbook["Diagnostics"]
    assert diagnostics["E8"].value == "Payment-year gaps"
    assert diagnostics["F8"].value == 1
    assert diagnostics["A11"].value == "Unpaid prior year before a later paid year"
    assert diagnostics["B11"].value == "06-0001-00001"
