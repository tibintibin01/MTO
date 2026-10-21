"""Officer/date RPT collection snapshots. Reads posted cash, never rebills taxes."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from backend.models import (
    Payment,
    PaymentBilling,
    RcdCollectingOfficer,
    RcdReceiptBooklet,
    TaxPolicy,
)
from backend.services.coa_rcd_generator import _receipt_components
from backend.services.rcd_register_service import require_rcd_register, booklet_dict
from utils.rcd_booklets import receipt_serial
from utils.rcd_metadata import resolve_rcd_metadata

CENT = Decimal("0.01")
MAX_DAILY_ROWS = 20000


class RcdSnapshotChanged(ValueError):
    pass


def _money(value):
    result = Decimal(str(value or 0)).quantize(CENT)
    if not result.is_finite():
        raise ValueError("Receipt amount is not finite.")
    return result


def _source_row(payment):
    return {
        "id": payment.id,
        "property_id": payment.property_id,
        "or": payment.or_number,
        "date": payment.date_paid.isoformat(),
        "cash": str(payment.amount),
        "penalty": str(payment.penalty),
        "discount": str(payment.discount),
        "tax_year": payment.tax_year,
        "links": sorted(
            (
                link.id,
                link.billing_id,
                link.tax_year,
                str(link.amount_paid),
                link.billing.property_id if link.billing else None,
                link.billing.tax_year if link.billing else None,
            )
            for link in payment.billings
        ),
    }


def build_daily_rcd(db, collector_id, report_date=None, *, expected_signature=None):
    control = require_rcd_register(db)
    collector = db.get(RcdCollectingOfficer, collector_id)
    if collector is None:
        raise ValueError("Select a registered collecting officer.")
    day = resolve_rcd_metadata(report_date=report_date).report_date
    if not 1900 <= day.year <= 2100:
        raise ValueError("Select an OR date between 1900 and 2100.")
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    payments = (
        db.query(Payment)
        .filter(Payment.date_paid >= start, Payment.date_paid < end)
        .options(selectinload(Payment.billings).selectinload(PaymentBilling.billing))
        .order_by(Payment.id)
        .limit(MAX_DAILY_ROWS + 1)
        .all()
    )
    if len(payments) > MAX_DAILY_ROWS:
        raise ValueError(
            "This day exceeds the safe report size; no partial RCD was generated."
        )
    booklets = db.query(RcdReceiptBooklet).order_by(RcdReceiptBooklet.id).all()
    policies = {int(item.tax_year): item for item in db.query(TaxPolicy).all()}
    issues, grouped, source = [], {}, []
    variants, day_serials = set(), set()
    matched_other_officer_rows = 0
    for payment in payments:
        source.append(_source_row(payment))
        try:
            prefix, serial, width = receipt_serial(payment.or_number)
        except ValueError:
            issues.append(
                {
                    "code": "INVALID_OR",
                    "payment_id": payment.id,
                    "message": "A dated payment has a missing or unsupported OR identity.",
                }
            )
            continue
        candidates = [
            book
            for book in booklets
            if book.serial_prefix == prefix
            and book.start_serial <= serial <= book.end_serial
        ]
        if len(candidates) != 1:
            issues.append(
                {
                    "code": "BOOKLET_ASSIGNMENT_REQUIRED",
                    "payment_id": payment.id,
                    "message": "A dated OR has no unique booklet assignment. Review the issuance log.",
                }
            )
            continue
        book = candidates[0]
        day_serials.add((prefix, serial))
        variants.update(
            (
                str(payment.or_number).strip().upper(),
                f"{prefix}{serial}",
                f"{prefix}{serial:0{book.serial_width}d}",
            )
        )
        # Historical imports may have removed or added leading zeroes. Check all
        # supported widths rather than silently treating those as different ORs.
        variants.update(
            f"{prefix}{serial:0{size}d}" for size in range(len(str(serial)), 16)
        )
        if book.issued_on > day:
            issues.append(
                {
                    "code": "OR_BEFORE_BOOKLET_ISSUE",
                    "payment_id": payment.id,
                    "message": "An OR predates the registered booklet issue date.",
                }
            )
            continue
        if book.collector_id != collector_id:
            matched_other_officer_rows += 1
            continue
        try:
            components = _receipt_components(payment, policies)
            if any(
                item["year"] not in policies
                or policies[item["year"]].basic_rate is None
                or policies[item["year"]].sef_rate is None
                for item in components
            ):
                raise ValueError(
                    "A receipt's tax-year rate configuration is missing; the fund split needs review."
                )
            basic = sum(
                (
                    item["basic"] + item["basic_penalty"] - item["basic_discount"]
                    for item in components
                ),
                Decimal(0),
            )
            sef = sum(
                (
                    item["sef"] + item["sef_penalty"] - item["sef_discount"]
                    for item in components
                ),
                Decimal(0),
            )
            cash = _money(payment.amount)
            if min(basic, sef, cash) < 0 or basic + sef != cash:
                raise ValueError(
                    "The Basic/SEF portions do not reconcile to recorded receipt cash."
                )
        except (ValueError, ArithmeticError, AttributeError) as error:
            issues.append(
                {
                    "code": "RECEIPT_REVIEW_REQUIRED",
                    "payment_id": payment.id,
                    "message": (
                        str(error)
                        if isinstance(error, ValueError)
                        else "Receipt allocations need review."
                    ),
                }
            )
            continue
        key = (book.id, serial)
        row = grouped.setdefault(
            key,
            {
                "booklet_id": book.id,
                "form_type": book.form_type,
                "serial": serial,
                "or_number": f"{prefix}{serial:0{book.serial_width}d}",
                "booklet_first": book.first_or,
                "booklet_last": book.last_or,
                "basic_cash": Decimal(0),
                "sef_cash": Decimal(0),
                "cash": Decimal(0),
                "payment_ids": [],
            },
        )
        row["basic_cash"] += basic
        row["sef_cash"] += sef
        row["cash"] += cash
        row["payment_ids"].append(payment.id)

    # One physical OR cannot belong to two payment dates. Same-day multi-property
    # entries remain visible as one receipt with all supporting payment IDs.
    reused = []
    if variants:
        ordered_variants = sorted(variants)
        for offset in range(0, len(ordered_variants), 900):
            reused.extend(
                db.query(Payment.id, Payment.or_number, Payment.date_paid)
                .filter(
                    func.upper(func.trim(Payment.or_number)).in_(
                        ordered_variants[offset : offset + 900]
                    ),
                    or_(Payment.date_paid < start, Payment.date_paid >= end),
                )
                .order_by(Payment.id)
                .all()
            )
        reused.sort(key=lambda item: item.id)
        for item in reused:
            if receipt_serial(item.or_number)[:2] in day_serials:
                issues.append(
                    {
                        "code": "OR_HAS_DIFFERENT_PAYMENT_DATES",
                        "payment_id": item.id,
                        "message": "A matching OR also has an entry under another payment date; review the source receipts.",
                    }
                )

    raw_signature = {
        "collector_id": collector.id,
        "collector_name": collector.name,
        "date": day.isoformat(),
        "registry_revision": control.revision,
        "booklets": [
            (b.id, b.collector_id, b.first_or, b.last_or, b.issued_on.isoformat())
            for b in booklets
        ],
        "payments": source,
        "reused": [(r.id, r.or_number, r.date_paid.isoformat()) for r in reused],
        "policies": sorted(
            (year, str(p.basic_rate), str(p.sef_rate)) for year, p in policies.items()
        ),
    }
    signature = hashlib.sha256(
        json.dumps(raw_signature, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if expected_signature is not None and expected_signature != signature:
        raise RcdSnapshotChanged(
            "Receipts, tax-year rates or booklet assignments changed. Reload the daily preview before exporting."
        )
    receipts = sorted(
        grouped.values(), key=lambda row: (row["booklet_id"], row["serial"])
    )
    ranges = []
    for row in receipts:
        if (
            ranges
            and ranges[-1]["booklet_id"] == row["booklet_id"]
            and ranges[-1]["end_serial"] + 1 == row["serial"]
        ):
            group = ranges[-1]
            group["to_or"] = row["or_number"]
            group["end_serial"] = row["serial"]
            group["count"] += 1
            group["basic_cash"] += row["basic_cash"]
            group["sef_cash"] += row["sef_cash"]
        else:
            ranges.append(
                {
                    "booklet_id": row["booklet_id"],
                    "form_type": row["form_type"],
                    "from_or": row["or_number"],
                    "to_or": row["or_number"],
                    "end_serial": row["serial"],
                    "count": 1,
                    "basic_cash": row["basic_cash"],
                    "sef_cash": row["sef_cash"],
                }
            )
    totals = {
        key: str(sum((row[key] for row in receipts), Decimal(0)).quantize(CENT))
        for key in ("basic_cash", "sef_cash", "cash")
    }
    for row in receipts + ranges:
        for key in ("basic_cash", "sef_cash", "cash"):
            if key in row:
                row[key] = str(row[key].quantize(CENT))
    return {
        "report_type": "MTO_DAILY_RPT_RCD",
        "status": "REVIEW_REQUIRED" if issues else "COLLECTIONS_READY",
        "collector": {"id": collector.id, "name": collector.name},
        "report_date": day.isoformat(),
        "source_signature": signature,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "receipt_count": len(receipts),
        "payment_row_count": sum(len(row["payment_ids"]) for row in receipts),
        "other_officer_payment_rows": matched_other_officer_rows,
        "totals": totals,
        "receipts": receipts,
        "ranges": ranges,
        "stock_booklets": [
            booklet_dict(book)
            for book in booklets
            if book.collector_id == collector_id and book.issued_on <= day
        ],
        "issues": issues,
        "limitations": [
            "OR/payment date, not encoding date. Booklet owner, not encoder username.",
            "Fund portions use the existing RCD tax-year rate and adjustment-allocation convention; no charge is recalculated.",
            "Remittance acceptance, cash/check split and complete physical form-stock movements require office verification.",
        ],
    }


def validate_stock_history(db, payload, stock):
    """Read-only conflict check. Future use is valid for a past unused balance.

    Cancellation is stricter: an OR with ANY saved payment is never silently
    reclassified as a zero-collection cancelled form.
    """
    available = set(map(tuple, stock["available_identities"]))
    cancelled = set(map(tuple, stock["cancelled_identities"]))
    variants = sorted(
        {
            f"{prefix}{serial:0{width}d}"
            for prefix, serial in available
            for width in range(len(str(serial)), 16)
        }
    )
    report_day = resolve_rcd_metadata(report_date=payload["report_date"]).report_date
    for offset in range(0, len(variants), 900):
        rows = (
            db.query(Payment.or_number, Payment.date_paid)
            .filter(
                func.upper(func.trim(Payment.or_number)).in_(
                    variants[offset : offset + 900]
                )
            )
            .limit(MAX_DAILY_ROWS + 1)
            .all()
        )
        if len(rows) > MAX_DAILY_ROWS:
            raise ValueError(
                "Stock history exceeds the safe review size; no partial validation was accepted."
            )
        for row in rows:
            key = receipt_serial(row.or_number)[:2]
            if key not in available:
                continue
            if key in cancelled:
                raise ValueError(
                    "A cancelled/spoiled OR has a saved payment entry. Review the actual records; no payment was cancelled or deleted."
                )
            # Legacy MariaDB DATE columns yield datetime.date, while DATETIME
            # columns yield datetime.datetime. Stock belongs to the recorded OR
            # calendar day, not its time of day. Preserve that day without a
            # timezone shift or changes to any saved payment/schema value.
            paid_on = row.date_paid
            if isinstance(paid_on, datetime):
                paid_on = paid_on.date()
            if paid_on is not None and not isinstance(paid_on, date):
                raise ValueError(
                    "Stock history contains an unsupported receipt date. Review the actual records; no date was inferred."
                )
            if paid_on is None or paid_on < report_day:
                raise ValueError(
                    "Claimed unused opening/received stock includes an earlier or undated payment. Review the stock log; no balance was inferred."
                )
