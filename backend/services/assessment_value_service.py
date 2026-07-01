"""Year-aware assessed-value timeline helpers.

The property row stores the latest assessment.  Older assessment versions are
kept in ``property_assessment_history`` and resolved by effective year so a
future revaluation cannot change prior-year billings.
"""

import re
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from backend.models import Property, PropertyAssessmentHistory


MONEY = Decimal("0.01")


def year_from_value(value):
    if value is None:
        return None
    match = re.search(r"(19|20|21|22)\d{2}", str(value).strip())
    return int(match.group(0)) if match else None


def money(value):
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def assessment_versions(prop: Property, db_session: Session, history_rows=None):
    """Return known ``(effective_year, value, source)`` versions in order."""
    versions = []
    rows = history_rows
    if rows is None:
        rows = db_session.query(PropertyAssessmentHistory).filter(
            PropertyAssessmentHistory.property_id == prop.id,
        ).all()
    for row in rows:
        year = year_from_value(row.tax_year)
        value = money(row.assessed_value)
        if year and value > 0:
            versions.append((year, value, "history"))

    current_year = year_from_value(prop.effectivity_date or prop.tax_year)
    current_value = money(prop.assessed_value)
    if current_year and current_value > 0:
        # Current wins when an old duplicate history row has the same year.
        versions.append((current_year, current_value, "current"))

    return sorted(versions, key=lambda item: (item[0], item[2] == "current"))


def assessed_value_for_year(
    prop: Property,
    tax_year: int,
    db_session: Session,
    versions=None,
):
    """Resolve the latest assessment effective on or before ``tax_year``.

    ``None`` is deliberately returned when the current assessment starts in a
    future year and no older version is known.  Guessing in that case would
    silently rewrite historical tax obligations.
    """
    target = int(tax_year)
    versions = versions if versions is not None else assessment_versions(prop, db_session)
    candidates = [item for item in versions if item[0] <= target]
    if candidates:
        return candidates[-1][1]

    current_year = year_from_value(prop.effectivity_date or prop.tax_year)
    current_value = money(prop.assessed_value)
    if current_value > 0 and current_year is None:
        return current_value
    return None


def earliest_assessment_year(prop: Property, db_session: Session, versions=None):
    known_versions = versions if versions is not None else assessment_versions(prop, db_session)
    years = [item[0] for item in known_versions]
    return min(years) if years else None


def upsert_history_version(
    prop: Property,
    effective_year: int,
    assessed_value,
    changed_by: str,
    reason: str,
    db_session: Session,
):
    """Store one historical assessment version per property/effective year."""
    year = int(effective_year)
    value = money(assessed_value)
    if value <= 0:
        return None

    year_text = str(year)
    row = db_session.query(PropertyAssessmentHistory).filter(
        PropertyAssessmentHistory.property_id == prop.id,
        PropertyAssessmentHistory.tax_year == year_text,
    ).order_by(PropertyAssessmentHistory.id.desc()).first()
    if row is None:
        row = PropertyAssessmentHistory(property_id=prop.id, tax_year=year_text)
        db_session.add(row)

    row.td_number = prop.td_number
    row.assessed_value = value
    row.kind_of_property = prop.kind_of_property
    row.changed_by = changed_by or "system"
    row.change_reason = reason
    return row
