"""Read-only, SQL-exact comparison of deployed and proposed compliance rules."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from backend.models import Property, PropertyBilling, TaxPolicy
from backend.services.billing_service import (
    COMPLIANCE_MONEY_TOLERANCE,
    _billing_effective_amount_exprs,
    _compliance_property_scope,
    _compliance_v2_per_property,
    compliance_v2_data_start_year,
    compliance_v2_excludes_archived_billings,
    _legacy_compliance_per_property,
    _legacy_compliant_condition,
    _v2_compliant_condition,
)


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _classification_map(per_property, compliant_condition, db_session: Session):
    rows = (
        db_session.query(
            per_property.c.property_id,
            per_property.c.total_due,
            per_property.c.total_paid,
            per_property.c.years_covered,
        )
        .select_from(per_property)
        .all()
    )
    compliant_ids = {
        int(row[0])
        for row in (
            db_session.query(per_property.c.property_id)
            .select_from(per_property)
            .filter(compliant_condition)
            .all()
        )
    }
    return {
        int(row[0]): {
            "compliant": int(row[0]) in compliant_ids,
            "total_due": _money(row[1]),
            "total_paid": _money(row[2]),
            "years_covered": int(row[3] or 0),
        }
        for row in rows
    }, compliant_ids


def _proposed_year_balances(rows: list[dict[str, Any]]):
    start_year = compliance_v2_data_start_year()
    exclude_archived = compliance_v2_excludes_archived_billings()
    active_rows = [
        row
        for row in rows
        if (start_year is None or row["tax_year"] >= start_year)
        and (not exclude_archived or not row["is_archived"])
    ]
    by_year: dict[int, dict[str, float]] = defaultdict(
        lambda: {"due": 0.0, "paid": 0.0}
    )
    for row in active_rows:
        year = int(row["tax_year"])
        by_year[year]["due"] += row["proposed_due"]
        by_year[year]["paid"] += row["effective_paid"]

    result = []
    for year in sorted(by_year):
        due = _money(by_year[year]["due"])
        paid = _money(by_year[year]["paid"])
        result.append(
            {
                "tax_year": year,
                "due": due,
                "paid": paid,
                "balance": _money(max(due - paid, 0)),
                "credit": _money(max(paid - due, 0)),
            }
        )
    return result


def _change_reasons(
    rows: list[dict[str, Any]],
    legacy_compliant: bool,
    proposed_compliant: bool,
    year_balances: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    tolerance = float(COMPLIANCE_MONEY_TOLERANCE)
    start_year = compliance_v2_data_start_year()
    exclude_archived = compliance_v2_excludes_archived_billings()
    if proposed_compliant and not legacy_compliant:
        if start_year is not None and any(
            row["tax_year"] < start_year
            and row["legacy_due"] > row["effective_paid"] + tolerance
            for row in rows
        ):
            reasons.append("pre_policy_start_year_balance_excluded")
        if exclude_archived and any(
            row["is_archived"] and row["legacy_due"] > row["effective_paid"] + tolerance
            for row in rows
        ):
            reasons.append("archived_balance_excluded")
    elif legacy_compliant and not proposed_compliant:
        has_open_year = any(year["balance"] > tolerance for year in year_balances)
        has_credit_year = any(year["credit"] > tolerance for year in year_balances)
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
    """Compare the exact service classifiers without changing database rows."""
    selected_year = int(as_of_year or datetime.now(timezone.utc).year)
    safe_limit = min(max(int(detail_limit), 1), 5_000)

    legacy_per_property = _legacy_compliance_per_property(selected_year, db_session)
    legacy_condition = _legacy_compliant_condition(legacy_per_property)
    legacy, legacy_compliant_ids = _classification_map(
        legacy_per_property, legacy_condition, db_session
    )
    strict_legacy_ids = {
        int(row[0])
        for row in (
            db_session.query(legacy_per_property.c.property_id)
            .select_from(legacy_per_property)
            .filter(
                and_(
                    legacy_per_property.c.total_due > 0,
                    legacy_per_property.c.total_paid > 0,
                    legacy_per_property.c.total_paid >= legacy_per_property.c.total_due,
                )
            )
            .all()
        )
    }

    proposed_per_property = _compliance_v2_per_property(selected_year, db_session)
    proposed, _ = _classification_map(
        proposed_per_property,
        _v2_compliant_condition(proposed_per_property),
        db_session,
    )

    rates = {
        int(year): float(basic or 0.01) + float(sef or 0.01)
        for year, basic, sef in db_session.query(
            TaxPolicy.tax_year,
            TaxPolicy.basic_rate,
            TaxPolicy.sef_rate,
        ).all()
    }
    effective = _billing_effective_amount_exprs(db_session)
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
            effective["paid"],
            effective["penalty"],
            effective["discount"],
        )
        .join(PropertyBilling, PropertyBilling.property_id == Property.id)
        .filter(Property.deleted_at == None)
        .filter(PropertyBilling.tax_year <= selected_year)
        .filter(*_compliance_property_scope(selected_year, db_session))
        .order_by(
            Property.id.asc(),
            PropertyBilling.tax_year.asc(),
            PropertyBilling.id.asc(),
        )
        .all()
    )

    properties: dict[int, dict[str, Any]] = {}
    for row in billing_rows:
        property_id = int(row[0])
        tax_year = int(row[4])
        rate = rates.get(tax_year, 0.02)
        assessed = float(row[5] or 0)
        stored_penalty = float(row[6] or 0)
        stored_discount = float(row[7] or 0)
        effective_penalty = float(row[11] or 0)
        effective_discount = float(row[12] or 0)
        account = properties.setdefault(
            property_id,
            {
                "property_id": property_id,
                "td_number": row[1],
                "barangay": row[2],
                "rows": [],
            },
        )
        account["rows"].append(
            {
                "billing_id": int(row[3]),
                "tax_year": tax_year,
                "legacy_due": assessed * rate + effective_penalty - effective_discount,
                "proposed_due": assessed * rate + stored_penalty - stored_discount,
                "stored_paid": float(row[8] or 0),
                "effective_paid": float(row[10] or 0),
                "is_archived": bool(row[9]),
            }
        )

    counts = {
        "unchanged_compliant": 0,
        "newly_compliant": 0,
        "removed_from_compliant": 0,
        "unchanged_noncompliant": 0,
    }
    affected: list[dict[str, Any]] = []
    property_ids = sorted(set(legacy) | set(proposed))
    empty = {
        "compliant": False,
        "total_due": 0.0,
        "total_paid": 0.0,
        "years_covered": 0,
    }
    for property_id in property_ids:
        account = properties[property_id]
        rows = account["rows"]
        legacy_result = legacy.get(property_id, empty)
        proposed_result = proposed.get(property_id, empty)
        legacy_ok = bool(legacy_result["compliant"])
        proposed_ok = bool(proposed_result["compliant"])
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
            year_balances = _proposed_year_balances(rows)
            affected.append(
                {
                    "property_id": account["property_id"],
                    "td_number": account["td_number"],
                    "barangay": account["barangay"],
                    "change": category,
                    "reasons": _change_reasons(
                        rows,
                        legacy_ok,
                        proposed_ok,
                        year_balances,
                    ),
                    "legacy": dict(legacy_result),
                    "proposed": {
                        **proposed_result,
                        "year_balances": year_balances,
                    },
                }
            )

    precision_ids = sorted(legacy_compliant_ids - strict_legacy_ids)
    precision_details = []
    for property_id in precision_ids[:safe_limit]:
        account = properties[property_id]
        totals = legacy[property_id]
        precision_details.append(
            {
                "property_id": property_id,
                "td_number": account["td_number"],
                "barangay": account["barangay"],
                "total_due": totals["total_due"],
                "total_paid": totals["total_paid"],
            }
        )

    changed_total = counts["newly_compliant"] + counts["removed_from_compliant"]
    return {
        "mode": "read_only_preview",
        "baseline_classification_version": "legacy_currency_safe",
        "proposed_classification_version": "v2_per_year",
        "classification_date_semantics": "obligations_through_selected_year_using_all_linked_payments",
        "as_of_year": selected_year,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "billing_data_start_year": compliance_v2_data_start_year(),
        "exclude_archived_billings": compliance_v2_excludes_archived_billings(),
        "money_tolerance": float(COMPLIANCE_MONEY_TOLERANCE),
        "properties_evaluated": len(property_ids),
        "changed_total": changed_total,
        "detail_limit": safe_limit,
        "details_truncated": changed_total > len(affected),
        "counts": counts,
        "affected_accounts": affected,
        "currency_precision_corrections": {
            "count": len(precision_ids),
            "details_truncated": len(precision_ids) > len(precision_details),
            "accounts": precision_details,
        },
    }
