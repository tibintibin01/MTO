"""Read-only recorded payment history, scoped by immutable property IDs."""

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

from backend.models import Payment, Property
from backend.services.assessment_value_service import year_from_value
from backend.services.payment_service import _payment_remarks_expr


class HistoryScopeError(ValueError):
    pass


NOTES = [
    "All payment entries currently recorded in MTO for the listed account IDs. "
    "Unencoded receipts and deleted entries are not reconstructed.",
    "Receipt/payment date, not encoding date. Each Payment ID is counted once. "
    "Distinct payments sharing an OR number remain separate.",
    "Penalty and discount are recorded adjustments, not additional cash. "
    "No charge or outstanding balance is recalculated.",
    "Historical Basic/SEF cash portions are not stored on these payment entries. "
    "They are not inferred from current assessed values or tax rates.",
    "Owner, location and TD details describe the current stored account, "
    "not necessarily the owner or address at the time of payment.",
    "For office reference. This is not a tax clearance, official receipt, "
    "or proof of COA certification.",
]


def _td(value):
    return str(value or "").strip().upper()


def previous_account_scope(records, selected_id):
    """Only an unambiguous, chronological one-to-one predecessor chain.

    No owner matching. Duplicate TD text is never an account key. Archived
    predecessors may be included, explicitly labeled in their own sections.
    A branch, cycle, dangling/conflicting link or unknown year stops expansion.
    """
    by_id = {r["id"]: r for r in records}
    by_td = defaultdict(list)
    for r in records:
        if _td(r["td_number"]):
            by_td[_td(r["td_number"])].append(r["id"])
    parents, errors, children = {}, {}, defaultdict(set)
    for r in records:
        pid, ref, previous_td = (
            r["id"],
            r["previous_property_id"],
            _td(r["prev_td_number"]),
        )
        candidates = by_td.get(previous_td, []) if previous_td else []
        if ref is not None:
            if ref not in by_id or ref == pid:
                errors[pid] = "Missing or self-referencing previous account."
            elif previous_td and previous_td != _td(by_id[ref]["td_number"]):
                errors[pid] = "Previous account ID and TD reference disagree."
            else:
                parents[pid] = ref
            # Conflicting links must still prevent a sibling from claiming
            # this predecessor as an exclusive one-to-one relationship.
            if ref in by_id:
                children[ref].add(pid)
            for candidate in candidates:
                children[candidate].add(pid)
        elif previous_td:
            for candidate in candidates:
                children[candidate].add(pid)
            if len(candidates) == 1 and candidates[0] != pid:
                parents[pid] = candidates[0]
            elif not candidates:
                errors[pid] = (
                    "Previous TD exists only as a reference; no local account is verified."
                )
            else:
                errors[pid] = (
                    "Previous TD reference matches multiple accounts or itself."
                )

    chain, seen, current = [], set(), selected_id
    while True:
        if current in seen:
            raise HistoryScopeError(
                "Previous-TD history has a cycle. Export the selected account only."
            )
        seen.add(current)
        chain.append(current)
        if current in errors:
            raise HistoryScopeError(
                errors[current] + " Export the selected account only."
            )
        parent = parents.get(current)
        if parent is None:
            break
        if children[parent] != {current}:
            raise HistoryScopeError(
                "Previous-TD history branches or has conflicting successors. Export accounts separately."
            )
        child_year = year_from_value(
            by_id[current]["effectivity_date"] or by_id[current]["tax_year"]
        )
        parent_year = year_from_value(
            by_id[parent]["effectivity_date"] or by_id[parent]["tax_year"]
        )
        if child_year is None or parent_year is None or child_year < parent_year:
            raise HistoryScopeError(
                "Previous-TD chronology needs review. Export the selected account only."
            )
        current = parent
    return list(reversed(chain))


def _money(value, *, optional=False):
    if value is None and optional:
        return None
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite()
            or amount < 0
            or amount != amount.quantize(Decimal("0.01"))
        ):
            raise InvalidOperation
        return format(amount, ".2f")
    except (InvalidOperation, ValueError, TypeError):
        raise HistoryScopeError(
            "A recorded payment amount needs review; no export was generated."
        ) from None


def _receipt_date(value):
    """MariaDB may return DATE or DATETIME. Never use encoding timestamps."""
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    raise HistoryScopeError(
        "A recorded receipt date needs review; no export was generated."
    )


def get_property_payment_history(property_id, *, include_previous=False, db_session):
    if type(property_id) is not int or property_id < 1:
        raise HistoryScopeError("Select one property account by its record ID.")
    with db_session.no_autoflush:
        graph = [
            dict(r._mapping)
            for r in db_session.query(
                Property.id,
                Property.td_number,
                Property.previous_property_id,
                Property.prev_td_number,
                Property.effectivity_date,
                Property.tax_year,
            ).all()
        ]
        if property_id not in {r["id"] for r in graph}:
            raise LookupError("Property account not found.")
        expansion_error = None
        try:
            expanded = previous_account_scope(graph, property_id)
        except HistoryScopeError as exc:
            expansion_error, expanded = str(exc), [property_id]
        if include_previous and expansion_error:
            raise HistoryScopeError(expansion_error)
        ids = expanded if include_previous else [property_id]
        properties = (
            db_session.query(
                Property.id,
                Property.td_number,
                Property.owner_name,
                Property.barangay,
                Property.location,
                Property.pin,
                Property.lot_number,
                Property.block_number,
                Property.kind_of_property,
                Property.deleted_at,
                Property.effectivity_date,
            )
            .filter(Property.id.in_(ids))
            .all()
        )
        # No ReceiptHistory or PaymentBilling joins: retained PDFs and year
        # allocations cannot multiply cash rows. All years, no display limit.
        payments = (
            db_session.query(
                Payment.id,
                Payment.property_id,
                Payment.date_paid,
                Payment.or_number,
                Payment.tax_year,
                Payment.penalty,
                Payment.discount,
                Payment.amount,
                _payment_remarks_expr(db_session).label("remarks"),
            )
            .filter(Payment.property_id.in_(ids))
            .all()
        )

    grouped = defaultdict(list)
    for p in payments:
        grouped[p.property_id].append(
            {
                "payment_id": p.id,
                "receipt_date": _receipt_date(p.date_paid),
                "or_number": p.or_number,
                "tax_years": p.tax_year,
                "penalty": _money(p.penalty, optional=True),
                "discount": _money(p.discount, optional=True),
                "cash": _money(p.amount),
                "basic_cash": None,
                "sef_cash": None,
                "remarks": p.remarks,
            }
        )
    metadata = {p.id: p for p in properties}
    sections, all_rows = [], []
    for pid in ids:
        p = metadata[pid]
        rows = sorted(
            grouped[pid],
            key=lambda r: (
                r["receipt_date"] is None,
                r["receipt_date"] or "",
                r["payment_id"],
            ),
        )
        total = sum((Decimal(r["cash"]) for r in rows), Decimal("0.00"))
        sections.append(
            {
                "property_id": pid,
                "td_number": p.td_number,
                "current_owner": p.owner_name,
                "current_barangay": p.barangay,
                "current_location": p.location,
                "pin": p.pin,
                "lot_number": p.lot_number,
                "block_number": p.block_number,
                "classification": p.kind_of_property,
                "effectivity": p.effectivity_date,
                "archived": p.deleted_at is not None,
                "selected": pid == property_id,
                "payments": rows,
                "payment_count": len(rows),
                "recorded_cash_total": format(total, ".2f"),
            }
        )
        all_rows.extend(rows)
    dates = [r["receipt_date"] for r in all_rows if r["receipt_date"]]
    payload = {
        "format_version": 1,
        "selected_property_id": property_id,
        "include_previous": bool(include_previous),
        "sections": sections,
        "previous_available": expansion_error is None and len(expanded) > 1,
        "previous_scope_note": expansion_error
        or "Only unambiguous, chronological one-to-one previous accounts can be included. This does not establish parcel equivalence.",
        "payment_count": len(all_rows),
        "undated_count": sum(r["receipt_date"] is None for r in all_rows),
        "coverage_start": min(dates) if dates else None,
        "coverage_end": max(dates) if dates else None,
        "recorded_cash_total": format(
            sum((Decimal(r["cash"]) for r in all_rows), Decimal("0.00")), ".2f"
        ),
        "notes": NOTES,
    }
    payload["fingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
    payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    return payload
