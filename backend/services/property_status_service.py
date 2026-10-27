"""Read-only, tax-year-aware TD status counts. Never archive or modify a TD."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from backend.models import Property, PropertyAssessmentHistory
from backend.services.assessment_value_service import year_from_value

PH_TIMEZONE = timezone(timedelta(hours=8))
STATUS_KEYS = (
    "active",
    "inactive_replaced",
    "future_effective",
    "archived",
    "needs_review",
)


def current_property_tax_year():
    return datetime.now(PH_TIMEZONE).year


def _td(value):
    return str(value or "").strip().upper()


def classify_property_records(records, assessment_years, *, as_of_year):
    """Partition stored accounts, retaining distinct IDs even for duplicate TDs.

    A replacement is not automatically backdated by an older AV snapshot. A
    linked future TD with earlier history needs review until its recorded year:
    the stored fields cannot prove whether that history is copied prior AV or
    the same TD's earlier existence. Standalone TDs can use their own history.
    """
    if type(as_of_year) is not int or not 1900 <= as_of_year <= 2299:
        raise ValueError("A supported tax year is required.")
    rows = {int(row["id"]): dict(row) for row in records}
    if len(rows) != len(records):
        raise ValueError("Property record IDs must be unique.")
    live = {pid for pid, row in rows.items() if row["deleted_at"] is None}
    by_td = defaultdict(list)
    for pid in live:
        if _td(rows[pid]["td_number"]):
            by_td[_td(rows[pid]["td_number"])].append(pid)

    first_year, uncertain_timeline = {}, set()
    historical = defaultdict(list)
    for item in assessment_years:
        year = year_from_value(item["tax_year"])
        if year:
            historical[int(item["property_id"])].append(year)
    for pid, row in rows.items():
        current = year_from_value(row["effectivity_date"] or row["tax_year"])
        known = [current] if current else []
        linked = row["previous_property_id"] is not None or _td(row["prev_td_number"])
        if not linked:
            known.extend(historical[pid])
        elif pid in live and (
            current is None
            or any(year <= as_of_year < current for year in historical[pid])
        ):
            uncertain_timeline.add(pid)
        first_year[pid] = min(known) if known else None

    def possibly_effective(pid):
        return (
            first_year[pid] is None
            or first_year[pid] <= as_of_year
            or pid in uncertain_timeline
        )

    parents, unclear, ambiguous = {}, set(uncertain_timeline), {}
    unclear.update(pid for pid in live if not _td(rows[pid]["td_number"]))
    external_references = 0
    for pid in live:
        row = rows[pid]
        parent_id = row["previous_property_id"]
        previous_td = _td(row["prev_td_number"])
        if parent_id is not None:
            if parent_id not in rows or parent_id == pid:
                unclear.add(pid)
                continue
            if previous_td and previous_td != _td(rows[parent_id]["td_number"]):
                unclear.add(pid)
                if possibly_effective(pid):
                    unclear.add(parent_id)
                continue
            parents[pid] = parent_id
        elif previous_td:
            matches = by_td.get(previous_td, [])
            if len(matches) == 1 and matches[0] != pid:
                parents[pid] = matches[0]
            elif matches:
                unclear.add(pid)
                ambiguous[pid] = matches
            else:
                # Previous TD can legitimately exist only in the office ledger.
                # No local predecessor is hidden or fabricated in that case.
                external_references += 1

    # A future ambiguous successor must not prematurely hide existing accounts.
    for pid, matches in ambiguous.items():
        if possibly_effective(pid):
            unclear.update(matches)
    for pid in uncertain_timeline:
        if pid in parents:
            unclear.add(parents[pid])

    for pid, parent_id in parents.items():
        child_year, parent_year = first_year[pid], first_year[parent_id]
        if (
            child_year is not None
            and parent_year is not None
            and child_year < parent_year
        ):
            unclear.update((pid, parent_id))

    # Iterative cycle detection also handles long chains without recursion limits.
    visited = set()
    for start in parents:
        path, positions = [], {}
        current = start
        while current in parents and current not in visited:
            if current in positions:
                unclear.update(path[positions[current] :])
                break
            positions[current] = len(path)
            path.append(current)
            current = parents[current]
        visited.update(path)

    replaced = {
        parent_id
        for pid, parent_id in parents.items()
        if pid not in unclear
        and first_year[pid] is not None
        and first_year[pid] <= as_of_year
    }
    counts = dict.fromkeys(STATUS_KEYS, 0)
    for pid in rows:
        if pid not in live:
            status = "archived"
        elif pid in unclear:
            status = "needs_review"
        elif pid in replaced:
            status = "inactive_replaced"
        elif first_year[pid] is None:
            status = "needs_review"
        elif first_year[pid] <= as_of_year:
            status = "active"
        else:
            status = "future_effective"
        counts[status] += 1
    return {
        "format_version": 1,
        "as_of_tax_year": as_of_year,
        **counts,
        "registered_records": len(live),
        "total_records": len(rows),
        "external_previous_td_references": external_references,
    }


def get_property_status_counts(db_session, *, as_of_year=None):
    """Read metadata only, without autoflush, commit, billing or cache writes."""
    year = current_property_tax_year() if as_of_year is None else as_of_year
    with db_session.no_autoflush:
        records = db_session.query(
            Property.id,
            Property.td_number,
            Property.previous_property_id,
            Property.prev_td_number,
            Property.effectivity_date,
            Property.tax_year,
            Property.deleted_at,
        ).all()
        assessment_years = (
            db_session.query(
                PropertyAssessmentHistory.property_id,
                PropertyAssessmentHistory.tax_year,
            )
            .filter(PropertyAssessmentHistory.assessed_value > 0)
            .all()
        )
    return classify_property_records(
        [row._mapping for row in records],
        [row._mapping for row in assessment_years],
        as_of_year=year,
    )
