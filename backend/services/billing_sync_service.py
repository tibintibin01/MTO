# -*- coding: utf-8 -*-
"""
Billing Year Synchronization Service.

Ensures every active property has a PropertyBilling record for every tax year
from its effectivity year up to the current year.

WHY THIS IS NEEDED:
  When properties are imported from Excel, only one billing record is created
  for the tax year specified in the import file. If a property has been
  delinquent since 2023, the system only shows the 2023 balance — not the
  accumulated 2023 + 2024 + 2025 balance.

  This service fills the gaps by creating missing billing records so the
  Delinquency Dashboard shows the true total outstanding balance.

WHAT IT DOES:
  For each active property:
    1. Determine the start year from effectivity_date or tax_year field
    2. For each year from start_year to current_year:
       - If a PropertyBilling row already exists → skip (never overwrite)
       - If no row exists → create one with the property's current assessed value

WHAT IT DOES NOT DO:
  - It does not modify existing billing records
  - It does not create payment records
  - It does not change assessed values on existing records
  - It does not affect properties that are already fully paid
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session

from backend.models import Property, PropertyBilling
from utils.logger import mto_logger


def _extract_start_year(prop: Property) -> int:
    """
    Determines the earliest tax year for a property.

    Priority:
    1. effectivity_date field (e.g. "2023-01-01" or "2023")
    2. tax_year field (e.g. "2023" or "2022, 2023")
    3. created_at timestamp
    4. Fallback: current year
    """
    current_year = datetime.now().year

    # Try effectivity_date first
    if prop.effectivity_date:
        raw = str(prop.effectivity_date).strip()
        # Handle "YYYY-MM-DD", "YYYY/MM/DD", or plain "YYYY"
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                return datetime.strptime(raw, fmt).year
            except ValueError:
                pass
        # Plain 4-digit year
        if raw.isdigit() and len(raw) == 4:
            return int(raw)

    # Try tax_year field — may be "2023" or "2022, 2023, 2024"
    if prop.tax_year:
        raw = str(prop.tax_year).strip()
        years = []
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit() and len(part) == 4:
                years.append(int(part))
        if years:
            return min(years)

    # Fall back to created_at year
    if prop.created_at:
        try:
            return prop.created_at.year
        except Exception:
            pass

    return current_year


def sync_billing_years(
    db_session: Session,
    dry_run: bool = False,
    progress_callback=None,
) -> dict:
    """
    Creates missing PropertyBilling records for all active properties.

    Parameters
    ----------
    db_session : Session
        Active SQLAlchemy session.
    dry_run : bool
        If True, calculate what would be created but don't write to DB.
        Useful for previewing before committing.
    progress_callback : callable, optional
        Called with (current, total, message) during processing.
        Used to update progress bars in the UI.

    Returns
    -------
    dict with keys:
        properties_scanned  : int
        records_created     : int
        records_skipped     : int  (already existed)
        errors              : list of str
        dry_run             : bool
    """
    current_year = datetime.now().year
    created = 0
    skipped = 0
    errors = []

    # Load all active properties
    properties = (
        db_session.query(Property)
        .filter(Property.deleted_at == None)
        .order_by(Property.id.asc())
        .all()
    )

    total = len(properties)
    mto_logger.info(
        f"Billing sync started: {total} properties to scan "
        f"({'DRY RUN' if dry_run else 'LIVE'})"
    )

    for idx, prop in enumerate(properties, 1):
        try:
            start_year = _extract_start_year(prop)

            # Safety: don't go further back than 2000 or further forward than now
            start_year = max(2000, min(start_year, current_year))

            # Fetch existing billing years for this property in one query
            existing_years = set(
                row[0]
                for row in db_session.query(PropertyBilling.tax_year)
                .filter(PropertyBilling.property_id == prop.id)
                .all()
            )

            assessed = Decimal(str(prop.assessed_value or 0))
            basic = (assessed * Decimal("0.01")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            sef = basic  # SEF = 1% same as basic
            total_due = basic + sef  # 2% total, no penalty for new records

            for year in range(start_year, current_year + 1):
                year_str = str(year)

                if year_str in existing_years:
                    skipped += 1
                    continue

                if not dry_run:
                    billing = PropertyBilling(
                        property_id=prop.id,
                        tax_year=year_str,
                        assessed_value=assessed,
                        penalty=Decimal("0.00"),
                        # Discount is intentionally 0 for new billing records.
                        # Discounts are only applied at the time of payment posting,
                        # not pre-emptively. A discount on an unpaid year is incorrect.
                        discount=Decimal("0.00"),
                        amount_paid=Decimal("0.00"),
                    )
                    db_session.add(billing)

                created += 1

            # Commit in batches of 100 properties to avoid huge transactions
            if not dry_run and idx % 100 == 0:
                db_session.flush()

        except Exception as e:
            err_msg = f"Property {prop.td_number} (ID {prop.id}): {e}"
            errors.append(err_msg)
            mto_logger.warning(f"Billing sync error — {err_msg}")

        if progress_callback:
            progress_callback(idx, total, f"Processing {prop.td_number}...")

    if not dry_run and created > 0:
        try:
            db_session.commit()
            mto_logger.info(
                f"Billing sync complete: {created} records created, "
                f"{skipped} skipped, {len(errors)} errors."
            )
        except Exception as e:
            db_session.rollback()
            raise

    return {
        "properties_scanned": total,
        "records_created": created,
        "records_skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }
