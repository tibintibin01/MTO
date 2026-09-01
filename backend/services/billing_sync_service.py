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

from collections import defaultdict
from datetime import datetime
from sqlalchemy.orm import Session

from backend.models import Property, PropertyAssessmentHistory, PropertyBilling
from backend.services.assessment_value_service import (
    assessed_value_for_year,
    assessment_versions,
    earliest_assessment_year,
)
from backend.services.tax_year_readiness_service import philippine_today
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


def sync_property_billing_years(
    prop: Property,
    db_session: Session,
    through_year: int = None,
    dry_run: bool = False,
    history_rows=None,
    existing_years=None,
) -> dict:
    """Create only the missing billing years for one active property account.

    The caller owns the transaction. Future-effective properties are left
    untouched until their effectivity year arrives, and existing billing rows
    are never overwritten.
    """
    target_year = int(through_year or philippine_today().year)
    versions = assessment_versions(
        prop,
        db_session,
        history_rows=history_rows,
    )
    start_year = earliest_assessment_year(
        prop, db_session, versions=versions
    ) or _extract_start_year(prop)

    if start_year > target_year:
        return {
            "records_created": 0,
            "records_skipped": 0,
            "errors": [],
            "start_year": start_year,
            "through_year": target_year,
            "future_effective": True,
        }

    start_year = max(2000, start_year)
    if existing_years is None:
        existing_years = {
            int(row[0])
            for row in db_session.query(PropertyBilling.tax_year)
            .filter(PropertyBilling.property_id == prop.id)
            .all()
        }
    else:
        existing_years = {int(year) for year in existing_years}
    created = 0
    skipped = 0
    errors = []

    for year in range(start_year, target_year + 1):
        if year in existing_years:
            skipped += 1
            continue

        assessed = assessed_value_for_year(
            prop,
            year,
            db_session,
            versions=versions,
        )
        if assessed is None:
            errors.append(
                f"No assessment version is effective for {year}; billing year skipped"
            )
            continue

        if not dry_run:
            db_session.add(
                PropertyBilling(
                    property_id=prop.id,
                    tax_year=year,
                    assessed_value=assessed,
                    penalty=0,
                    discount=0,
                    amount_paid=0,
                )
            )
        existing_years.add(year)
        created += 1

    return {
        "records_created": created,
        "records_skipped": skipped,
        "errors": errors,
        "start_year": start_year,
        "through_year": target_year,
        "future_effective": False,
    }


def sync_verified_duplicate_td_billings(
    db_session: Session,
    through_year: int = None,
) -> dict:
    """Idempotently repair billing readiness for verified duplicate accounts."""
    properties = (
        db_session.query(Property)
        .filter(
            Property.deleted_at == None,
            Property.duplicate_td_verified == True,
        )
        .order_by(Property.id.asc())
        .all()
    )
    summary = {
        "properties_scanned": len(properties),
        "records_created": 0,
        "records_skipped": 0,
        "errors": [],
    }
    for prop in properties:
        result = sync_property_billing_years(
            prop,
            db_session,
            through_year=through_year,
        )
        summary["records_created"] += result["records_created"]
        summary["records_skipped"] += result["records_skipped"]
        summary["errors"].extend(
            f"Property {prop.id} ({prop.td_number}): {message}"
            for message in result["errors"]
        )
    return summary


def _load_bulk_sync_context(db_session: Session):
    """Load assessment histories and existing billing years in two queries.

    The all-property sync previously repeated both lookups for every property,
    producing more than 30,000 SELECTs on a typical production run. Grouping
    the same read-only data in memory preserves the per-property rules while
    keeping the query count constant as the registry grows.
    """
    history_by_property = defaultdict(list)
    history_rows = (
        db_session.query(PropertyAssessmentHistory)
        .join(Property, Property.id == PropertyAssessmentHistory.property_id)
        .filter(Property.deleted_at == None)
        .order_by(
            PropertyAssessmentHistory.property_id.asc(),
            PropertyAssessmentHistory.id.asc(),
        )
        .all()
    )
    for row in history_rows:
        history_by_property[int(row.property_id)].append(row)

    existing_years_by_property = defaultdict(set)
    billing_rows = (
        db_session.query(PropertyBilling.property_id, PropertyBilling.tax_year)
        .join(Property, Property.id == PropertyBilling.property_id)
        .filter(Property.deleted_at == None)
        .all()
    )
    for property_id, tax_year in billing_rows:
        existing_years_by_property[int(property_id)].add(int(tax_year))

    return history_by_property, existing_years_by_property


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
    current_year = philippine_today().year
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

    history_by_property, existing_years_by_property = _load_bulk_sync_context(
        db_session
    )

    total = len(properties)
    progress_interval = max(1, (total + 99) // 100)
    mto_logger.info(
        f"Billing sync started: {total} properties to scan "
        f"({'DRY RUN' if dry_run else 'LIVE'})"
    )

    for idx, prop in enumerate(properties, 1):
        try:
            result = sync_property_billing_years(
                prop,
                db_session,
                through_year=current_year,
                dry_run=dry_run,
                history_rows=history_by_property.get(prop.id, ()),
                existing_years=existing_years_by_property.get(prop.id, set()),
            )
            created += result["records_created"]
            skipped += result["records_skipped"]
            errors.extend(
                f"Property {prop.td_number}: {message}" for message in result["errors"]
            )

            # Flush in batches while retaining one atomic commit for the run.
            if not dry_run and idx % 100 == 0:
                db_session.flush()

        except Exception as e:
            err_msg = f"Property {prop.td_number} (ID {prop.id}): {e}"
            errors.append(err_msg)
            mto_logger.warning(f"Billing sync error — {err_msg}")

        if progress_callback and (
            idx == 1 or idx == total or idx % progress_interval == 0
        ):
            progress_callback(
                idx,
                total,
                f"Processing {prop.td_number}... ({idx}/{total})",
            )

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
