"""Read-only, exact-account credit drill-down using the report's existing basis."""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_

from backend.models import Property, PropertyBilling, TaxPolicy
from backend.services.billing_service import (
    _billing_effective_amount_exprs,
    _paid_to_billing_expr,
)


class CreditScopeChanged(ValueError):
    """The user must refresh rather than mix two different credit snapshots."""


def _money(value):
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def _credit_query(db, year, *, positive_only=True):
    effective = _billing_effective_amount_exprs(db, year_lte=year)
    paid = _paid_to_billing_expr(db, year_lte=year)
    rate = func.coalesce(TaxPolicy.basic_rate, 0.01) + func.coalesce(
        TaxPolicy.sef_rate, 0.01
    )
    charge = (
        PropertyBilling.assessed_value * rate
        + effective["penalty"]
        - effective["discount"]
    )
    barangay = func.coalesce(
        func.nullif(func.trim(Property.barangay), ""), "UNSPECIFIED"
    )
    query = (
        db.query(
            PropertyBilling.id.label("billing_id"),
            Property.id.label("property_id"),
            Property.td_number.label("td_number"),
            Property.owner_name.label("owner_name"),
            barangay.label("barangay"),
            PropertyBilling.tax_year.label("tax_year"),
            charge.label("recorded_charge"),
            paid.label("applied_payment"),
            (paid - charge).label("credit"),
        )
        .join(Property, Property.id == PropertyBilling.property_id)
        .outerjoin(TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year)
        .filter(Property.deleted_at.is_(None))
    )
    if positive_only:
        query = query.filter(paid - charge > 0)
    if year is not None:
        query = query.filter(PropertyBilling.tax_year <= year)
    return query


def credit_scope(db, year):
    """Hash the complete positive-credit set, not the sampled diagnostic rows."""
    rows = _credit_query(db, year).order_by(PropertyBilling.id).all()
    identity = [
        [
            r.billing_id,
            r.property_id,
            r.td_number,
            r.owner_name,
            r.barangay,
            r.tax_year,
            _money(r.recorded_charge),
            _money(r.applied_payment),
        ]
        for r in rows
    ]
    signature = hashlib.sha256(
        json.dumps([year, identity], ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "signature": signature,
        "billing_count": len(rows),
        "account_count": len({r.property_id for r in rows}),
        "credit_total": _money(sum((Decimal(str(r.credit)) for r in rows), Decimal(0))),
    }


def build_credit_accounts_report(
    year,
    db_session,
    *,
    barangay=None,
    search="",
    limit=100,
    offset=0,
    expected_signature=None,
):
    from backend.services.report_payload_service import report_read_session

    year = int(year) if year is not None else None
    if year is not None and not 1900 <= year <= 2100:
        raise ValueError("Select a fiscal year between 1900 and 2100.")
    if not 1 <= int(limit) <= 200 or int(offset) < 0:
        raise ValueError("Invalid credit page size or offset.")
    search = str(search or "").strip()
    if len(search) > 100:
        raise ValueError("Search is limited to 100 characters.")
    with report_read_session(db_session) as db:
        scope = credit_scope(db, year)
        if expected_signature and scope["signature"] != expected_signature:
            raise CreditScopeChanged(
                "Credit accounts changed. Refresh the parent report before reviewing details."
            )
        query = _credit_query(db, year)
        if barangay is not None:
            query = query.filter(
                func.coalesce(
                    func.nullif(func.trim(Property.barangay), ""), "UNSPECIFIED"
                )
                == barangay
            )
        if search:
            query = query.filter(
                or_(
                    Property.td_number.contains(search, autoescape=True),
                    Property.owner_name.contains(search, autoescape=True),
                )
            )
        subquery = query.subquery()
        count, total = (
            db.query(func.count(), func.coalesce(func.sum(subquery.c.credit), 0))
            .select_from(subquery)
            .one()
        )
        rows = query.order_by(PropertyBilling.id).offset(offset).limit(limit).all()
        return {
            "report_year": year,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": scope,
            "barangay": barangay,
            "search": search,
            "count": count,
            "credit_total": _money(total),
            "offset": offset,
            "has_more": offset + len(rows) < count,
            "items": [
                {
                    **dict(r._mapping),
                    "recorded_charge": _money(r.recorded_charge),
                    "applied_payment": _money(r.applied_payment),
                    "credit": _money(r.credit),
                }
                for r in rows
            ],
            "basis": "Positive payments above recorded charges on each billing; never netted across accounts or years.",
            "read_only": True,
        }


def build_credit_account_ledger(property_id, year, db_session, expected_signature=None):
    from backend.services.report_payload_service import report_read_session

    with report_read_session(db_session) as db:
        scope = credit_scope(db, year)
        if expected_signature and scope["signature"] != expected_signature:
            raise CreditScopeChanged(
                "Credit accounts changed. Refresh the parent report."
            )
        prop = (
            db.query(Property)
            .filter(Property.id == property_id, Property.deleted_at.is_(None))
            .one_or_none()
        )
        if prop is None:
            raise LookupError("Account not found.")
        rows = (
            _credit_query(db, year, positive_only=False)
            .filter(Property.id == property_id)
            .order_by(PropertyBilling.tax_year, PropertyBilling.id)
            .all()
        )
        return {
            "property_id": prop.id,
            "td_number": prop.td_number,
            "owner_name": prop.owner_name,
            "report_year": year,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "basis": (
                f"Balances at December 31, {year}"
                if year
                else "All billing years / all recorded payment dates"
            ),
            "items": [
                {
                    "tax_year": r.tax_year,
                    "billing_id": r.billing_id,
                    "recorded_charge": _money(r.recorded_charge),
                    "applied_payment": _money(r.applied_payment),
                    "receivable": _money(
                        max(
                            Decimal(str(r.recorded_charge))
                            - Decimal(str(r.applied_payment)),
                            0,
                        )
                    ),
                    "credit": _money(max(Decimal(str(r.credit)), 0)),
                }
                for r in rows
            ],
            "read_only": True,
        }
