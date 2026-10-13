"""Privacy-safe, read-only counts for reviewing the Reports correction impact."""

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_

from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.services.billing_service import _billing_allocation_totals_subquery
from backend.services.report_payload_service import report_read_session


def review_report_accuracy_impact(db_session):
    with report_read_session(db_session) as db:
        linked = _billing_allocation_totals_subquery(db)
        cached_adjustment_mismatches = (
            db.query(PropertyBilling.id)
            .join(Property, Property.id == PropertyBilling.property_id)
            .join(linked, linked.c.billing_id == PropertyBilling.id)
            .filter(
                Property.deleted_at == None,
                or_(
                    func.abs(PropertyBilling.penalty - linked.c.linked_penalty) > 0.005,
                    func.abs(PropertyBilling.discount - linked.c.linked_discount)
                    > 0.005,
                ),
            )
            .count()
        )
        undated_adjustments = (
            db.query(PropertyBilling.id)
            .join(Property, Property.id == PropertyBilling.property_id)
            .outerjoin(linked, linked.c.billing_id == PropertyBilling.id)
            .filter(
                Property.deleted_at == None,
                linked.c.billing_id == None,
                or_(PropertyBilling.penalty != 0, PropertyBilling.discount != 0),
            )
            .count()
        )
        allocated = func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
        receipts = (
            db.query(
                Payment.id,
                func.count(PaymentBilling.id).label("links"),
                allocated.label("allocated"),
                Payment.amount,
                Payment.penalty,
                Payment.discount,
            )
            .join(Property, Property.id == Payment.property_id)
            .outerjoin(PaymentBilling, PaymentBilling.payment_id == Payment.id)
            .group_by(Payment.id, Payment.amount, Payment.penalty, Payment.discount)
            .subquery()
        )
        no_links = (
            db.query(receipts)
            .filter(and_(receipts.c.links == 0, receipts.c.amount > 0))
            .count()
        )
        receipt_gaps = (
            db.query(receipts)
            .filter(
                receipts.c.links > 0,
                func.abs(receipts.c.allocated - receipts.c.amount) > 0.005,
            )
            .count()
        )
        multi_adjustments = (
            db.query(receipts)
            .filter(
                receipts.c.links > 1,
                or_(receipts.c.penalty != 0, receipts.c.discount != 0),
            )
            .count()
        )
        wrong_accounts = (
            db.query(PaymentBilling.id)
            .join(Payment, Payment.id == PaymentBilling.payment_id)
            .join(PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id)
            .join(Property, Property.id == Payment.property_id)
            .filter(
                PropertyBilling.property_id != Payment.property_id,
            )
            .count()
        )
        counts = {
            "positive_receipts_without_dates": db.query(Payment.id)
            .join(Property, Property.id == Payment.property_id)
            .filter(
                Payment.date_paid == None,
                Payment.amount > 0,
            )
            .count(),
            "cached_billing_adjustment_mismatches": cached_adjustment_mismatches,
            "billing_adjustments_without_receipt_date_for_historical_review": undated_adjustments,
            "unlinked_positive_receipts": no_links,
            "linked_receipt_cash_mismatches": receipt_gaps,
            "cross_account_allocation_links": wrong_accounts,
            "multi_year_receipts_with_adjustments_for_convention_review": multi_adjustments,
        }
        return {
            "report_type": "MTO_REPORTS_ACCURACY_IMPACT_REVIEW",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "REVIEW_REQUIRED" if any(counts.values()) else "NO_FLAGGED_CASES",
            "counts": counts,
            "read_only": True,
            "financial_records_changed": False,
            "personal_fields_included": False,
            "limitations": [
                "Counts are not a production certification or authorization to repair data.",
                "Multi-year adjustments use the existing equal-share convention; exact original per-year adjustments are not stored.",
                "Review historical evidence before authorizing any cache repair or financial-history change.",
            ],
        }
