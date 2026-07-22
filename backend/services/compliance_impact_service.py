"""Read-only comparison of deployed and proposed compliance classifications."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import PaymentBilling, Property, PropertyBilling, TaxPolicy
from backend.services.billing_service import (
    BILLING_DATA_START_YEAR,
    _compliance_property_scope,
)


MONEY_TOLERANCE = 0.005


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _legacy_compliant(rows: list[dict[str, Any]]) -> tuple[bool, float, float]:
    total_due = _money(sum(row["due"] for row in rows))
    total_paid = _money(sum(row["stored_paid"] for row in rows))
    compliant = total_due > 0 and total_paid > 0 and total_paid + MONEY_TOLERANCE >= total_due
    return compliant, total_due, total_paid


def _proposed_compliant(rows: list[dict[str, Any]]) -> tuple[bool, float, float, list[dict[str, Any]]]:
    active_rows = [
        row for row in rows
        if row["tax_year"] >= BILLING_DATA_START_YEAR and not row["is_archived"]
    ]
    by_year: dict[int, dict[str, float]] = defaultdict(lambda: {"due": 0.0, "paid": 0.0})
    for row in active_rows:
        year = int(row["tax_year"])
        by_year[year]["due"] += row["due"]
        by_year[year]["paid"] += row["effective_paid"]

    year_balances = []
    for year in sorted(by_year):
        due = _money(by_year[year]["due"])
        paid = _money(by_year[year]["paid"])
        year_balances.append({
            "tax_year": year,
            "due": due,
            "paid": paid,
            "balance": _money(max(due - paid, 0)),
            "credit": _money(max(paid - due, 0)),
        })

    total_due = _money(sum(year["due"] for year in year_balances))
    total_paid = _money(sum(year["paid"] for year in year_balances))
    positive_obligations = [year for year in year_balances if year["due"] > MONEY_TOLERANCE]
    compliant = (
        total_due > MONEY_TOLERANCE
        and total_paid > MONEY_TOLERANCE
        and bool(positive_obligations)
        and all(year["balance"] <= MONEY_TOLERANCE for year in positive_obligations)
    )
    return compliant, total_due, total_paid, year_balances


def _change_reasons(
    rows: list[dict[str, Any]],
    legacy_compliant: bool,
    proposed_compliant: bool,
    year_balances: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    if proposed_compliant and not legacy_compliant:
        if any(row["tax_year"] < BILLING_DATA_START_YEAR and row["due"] > row["stored_paid"] + MONEY_TOLERANCE for row in rows):
            reasons.append("legacy_pre_2023_balance_excluded")
        if any(row["is_archived"] and row["due"] > row["stored_paid"] + MONEY_TOLERANCE for row in rows):
            reasons.append("archived_balance_excluded")
        if any(abs(row["effective_paid"] - row["stored_paid"]) > MONEY_TOLERANCE for row in rows):
            reasons.append("linked_payments_reconcile_stale_billing_cache")
    elif legacy_compliant and not proposed_compliant:
        has_open_year = any(year["balance"] > MONEY_TOLERANCE for year in year_balances)
        has_credit_year = any(year["credit"] > MONEY_TOLERANCE for year in year_balances)
        if has_open_year and has_credit_year:
            reasons.append("cross_year_credit_masks_unpaid_year")
        elif has_open_year:
            reasons.append("one_or_more_tax_years_remain_unpaid")
    return reasons or ["classification_logic_changed"]


def build_compliance_impact_report(
    *,
    as_of_year: int | None = None,
    detail_limit: int = 500,
    db_session: Session,
) -> dict[str, Any]:
    """Compare classifications without committing or updating any database row.

    The deployed baseline uses aggregate stored billing totals. The proposed
    rule uses the supported 2023+ active billing scope, reconciles linked
    allocations, and requires every positive-due tax year to have zero balance.
    """
    selected_year = int(as_of_year or datetime.now(timezone.utc).year)
    safe_limit = min(max(int(detail_limit), 1), 5_000)
    rates = {
        int(year): float(basic or 0.01) + float(sef or 0.01)
        for year, basic, sef in db_session.query(
            TaxPolicy.tax_year,
            TaxPolicy.basic_rate,
            TaxPolicy.sef_rate,
        ).all()
    }

    billing_rows = (
        db_session.query(
            Property.id,
            Property.td_number,
            func.coalesce(Property.barangay, "UNSPECIFIED"),
            PropertyBilling.id,
            PropertyBilling.tax_year,
            PropertyBilling.assessed_value,
            PropertyBilling.penalty,
            PropertyBilling.discount,
            PropertyBilling.amount_paid,
            PropertyBilling.is_archived,
        )
        .join(PropertyBilling, PropertyBilling.property_id == Property.id)
        .filter(Property.deleted_at == None)
        .filter(PropertyBilling.tax_year <= selected_year)
        .filter(*_compliance_property_scope(selected_year, db_session))
        .order_by(Property.id.asc(), PropertyBilling.tax_year.asc(), PropertyBilling.id.asc())
        .all()
    )

    linked_rows = (
        db_session.query(
            PaymentBilling.billing_id,
            func.count(PaymentBilling.id),
            func.coalesce(func.sum(PaymentBilling.amount_paid), 0),
        )
        .join(PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id)
        .join(Property, Property.id == PropertyBilling.property_id)
        .filter(Property.deleted_at == None)
        .filter(PropertyBilling.tax_year <= selected_year)
        .filter(*_compliance_property_scope(selected_year, db_session))
        .group_by(PaymentBilling.billing_id)
        .all()
    )
    linked_by_billing = {
        int(billing_id): (int(link_count or 0), float(linked_paid or 0))
        for billing_id, link_count, linked_paid in linked_rows
    }

    properties: dict[int, dict[str, Any]] = {}
    for row in billing_rows:
        property_id = int(row[0])
        billing_id = int(row[3])
        tax_year = int(row[4])
        rate = rates.get(tax_year, 0.02)
        stored_paid = _money(row[8])
        link_count, linked_paid = linked_by_billing.get(billing_id, (0, 0.0))
        effective_paid = _money(linked_paid if link_count > 0 else stored_paid)
        due = _money(float(row[5] or 0) * rate + float(row[6] or 0) - float(row[7] or 0))
        account = properties.setdefault(property_id, {
            "property_id": property_id,
            "td_number": row[1],
            "barangay": row[2],
            "rows": [],
        })
        account["rows"].append({
            "billing_id": billing_id,
            "tax_year": tax_year,
            "due": due,
            "stored_paid": stored_paid,
            "effective_paid": effective_paid,
            "is_archived": bool(row[9]),
        })

    counts = {
        "unchanged_compliant": 0,
        "newly_compliant": 0,
        "removed_from_compliant": 0,
        "unchanged_noncompliant": 0,
    }
    affected: list[dict[str, Any]] = []
    for account in properties.values():
        rows = account.pop("rows")
        legacy_ok, legacy_due, legacy_paid = _legacy_compliant(rows)
        proposed_ok, proposed_due, proposed_paid, year_balances = _proposed_compliant(rows)
        if legacy_ok and proposed_ok:
            category = "unchanged_compliant"
        elif not legacy_ok and proposed_ok:
            category = "newly_compliant"
        elif legacy_ok and not proposed_ok:
            category = "removed_from_compliant"
        else:
            category = "unchanged_noncompliant"
        counts[category] += 1

        if legacy_ok != proposed_ok and len(affected) < safe_limit:
            affected.append({
                **account,
                "change": category,
                "reasons": _change_reasons(rows, legacy_ok, proposed_ok, year_balances),
                "legacy": {
                    "compliant": legacy_ok,
                    "total_due": legacy_due,
                    "total_paid": legacy_paid,
                },
                "proposed": {
                    "compliant": proposed_ok,
                    "total_due": proposed_due,
                    "total_paid": proposed_paid,
                    "year_balances": year_balances,
                },
            })

    changed_total = counts["newly_compliant"] + counts["removed_from_compliant"]
    return {
        "mode": "read_only_preview",
        "classification_date_semantics": "obligations_through_selected_year_using_all_linked_payments",
        "as_of_year": selected_year,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "billing_data_start_year": BILLING_DATA_START_YEAR,
        "properties_evaluated": len(properties),
        "changed_total": changed_total,
        "detail_limit": safe_limit,
        "details_truncated": changed_total > len(affected),
        "counts": counts,
        "affected_accounts": affected,
    }
