"""Read-only checks that support the annual tax-year rollover warning."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from backend.models import Property, PropertyBilling, TaxPolicy


PHILIPPINE_TIMEZONE = timezone(timedelta(hours=8))


def philippine_today() -> date:
    """Return the municipal office date even when the API runs in UTC."""
    return datetime.now(PHILIPPINE_TIMEZONE).date()


def get_tax_year_readiness(
    db_session: Session,
    current_date: date | None = None,
) -> dict:
    """Return a lightweight, read-only rollover readiness summary.

    December is a preparation window for the coming tax year. January is the
    action window for checking current-year billing coverage. Outside those
    months no database scan is performed.
    """
    office_date = current_date or philippine_today()
    month = office_date.month

    if month not in (12, 1):
        return {
            "season_active": False,
            "action_required": False,
            "status": "OUTSIDE_ROLLOVER_WINDOW",
            "office_date": office_date.isoformat(),
            "target_year": office_date.year,
        }

    is_preparation = month == 12
    target_year = office_date.year + 1 if is_preparation else office_date.year

    active_properties = (
        db_session.query(func.count(Property.id))
        .filter(Property.deleted_at == None)
        .scalar()
        or 0
    )
    billed_properties = (
        db_session.query(func.count(distinct(PropertyBilling.property_id)))
        .join(Property, Property.id == PropertyBilling.property_id)
        .filter(
            Property.deleted_at == None,
            PropertyBilling.tax_year == target_year,
        )
        .scalar()
        or 0
    )
    missing_billing_properties = max(
        int(active_properties) - int(billed_properties),
        0,
    )
    tax_policy_configured = (
        db_session.query(TaxPolicy.id).filter(TaxPolicy.tax_year == target_year).first()
        is not None
    )

    if is_preparation:
        policy_note = (
            "The tax policy is configured. Confirm assessment changes before year-end."
            if tax_policy_configured
            else "Configure and approve the new tax-year policy before billing is created."
        )
        return {
            "season_active": True,
            "action_required": True,
            "status": "PREPARATION_REQUIRED",
            "severity": "warning",
            "office_date": office_date.isoformat(),
            "target_year": target_year,
            "title": f"Prepare the {target_year} Tax Year",
            "message": (
                f"{policy_note} On or after January 1, create a database backup, "
                "then preview Sync Billing Years."
            ),
            "active_properties": int(active_properties),
            "billed_properties": int(billed_properties),
            "missing_billing_properties": int(missing_billing_properties),
            "tax_policy_configured": tax_policy_configured,
            "sync_available": False,
            "recommended_tab": "Tax Policy",
        }

    action_required = missing_billing_properties > 0 or not tax_policy_configured
    if not action_required:
        return {
            "season_active": True,
            "action_required": False,
            "status": "READY",
            "severity": "success",
            "office_date": office_date.isoformat(),
            "target_year": target_year,
            "title": f"{target_year} Tax Year Ready",
            "message": (
                f"All {int(active_properties):,} active properties have a {target_year} "
                "billing record and the tax policy is configured."
            ),
            "active_properties": int(active_properties),
            "billed_properties": int(billed_properties),
            "missing_billing_properties": 0,
            "tax_policy_configured": True,
            "sync_available": True,
            "recommended_tab": "Database & Backup",
        }

    instructions = []
    recommended_tab = "Database & Backup"
    if not tax_policy_configured:
        instructions.append(f"Configure the {target_year} tax policy first.")
        recommended_tab = "Tax Policy"
    if missing_billing_properties:
        instructions.append(
            f"{missing_billing_properties:,} active properties do not have a "
            f"{target_year} billing record. Create a database backup, then preview "
            "Sync Billing Years."
        )

    return {
        "season_active": True,
        "action_required": True,
        "status": "ACTION_REQUIRED",
        "severity": "error",
        "office_date": office_date.isoformat(),
        "target_year": target_year,
        "title": f"{target_year} Billing Readiness Requires Action",
        "message": " ".join(instructions),
        "active_properties": int(active_properties),
        "billed_properties": int(billed_properties),
        "missing_billing_properties": int(missing_billing_properties),
        "tax_policy_configured": tax_policy_configured,
        "sync_available": True,
        "recommended_tab": recommended_tab,
    }
