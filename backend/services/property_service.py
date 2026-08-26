# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone
from sqlalchemy import text, func, cast, Integer, exists, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from backend.models import (
    Property,
    PropertyAssessmentHistory,
    PropertyBilling,
    Payment,
    AuditLog,
    TaxPolicy,
)
from backend.services.auth_service import get_username, require_permission
import backend.services.billing_service as billing
import backend.services.payment_service as payment
from backend.services.assessment_value_service import (
    assessment_snapshot_for_year,
    assessment_snapshots,
    money as assessment_money,
    upsert_history_version,
    year_from_value as assessment_year,
)
from fastapi import HTTPException
from utils.sanitizer import sanitize_string


# ---------------------------------------------------------------------------
# Tax rate helpers for Python-side calculations (search result formatting).
# These cache the policy lookup per-session to avoid N+1 queries.
# ---------------------------------------------------------------------------
_rate_cache: dict = {}


def _get_policy_rates(tax_year_str, db_session: Session):
    """Returns (basic_rate, sef_rate) for a given tax year, with caching."""
    if not tax_year_str or not db_session:
        return (0.01, 0.01)
    # Parse the first year from multi-year strings like "2023, 2024"
    try:
        year_val = int(str(tax_year_str).strip().split(",")[0].split("-")[0].strip())
    except (ValueError, TypeError):
        return (0.01, 0.01)

    cache_key = id(db_session)
    if cache_key not in _rate_cache:
        _rate_cache[cache_key] = {}
    if year_val in _rate_cache[cache_key]:
        return _rate_cache[cache_key][year_val]

    policy = db_session.query(TaxPolicy).filter(TaxPolicy.tax_year == year_val).first()
    if policy:
        rates = (float(policy.basic_rate), float(policy.sef_rate))
    else:
        rates = (0.01, 0.01)
    _rate_cache[cache_key][year_val] = rates
    return rates


def _get_basic_rate(prop, db_session):
    basic, _ = _get_policy_rates(prop.tax_year, db_session)
    return basic


def _get_sef_rate(prop, db_session):
    _, sef = _get_policy_rates(prop.tax_year, db_session)
    return sef


def _get_total_rate(prop, db_session):
    basic, sef = _get_policy_rates(prop.tax_year, db_session)
    return basic + sef


class SyncConflictError(Exception):
    """Custom exception raised when a version mismatch is detected during save."""

    def __init__(self, server_data, client_data):
        self.server_data = server_data
        self.client_data = client_data
        self.is_sync_conflict = True  # Marker for cross-module identification
        super().__init__("Offline Sync Conflict Detected.")


class AmbiguousPropertyError(ValueError):
    """Raised when a TD lookup matches more than one active property."""

    def __init__(self, td_number, matches):
        self.td_number = _td_text(td_number)
        self.matches = list(matches or [])
        super().__init__(
            f"{len(self.matches)} active properties use TD {self.td_number}. "
            "Select the correct property account before continuing."
        )


def clean_currency(value):
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip() or 0.0)
    except (ValueError, TypeError):
        return 0.0


def _normalize_effectivity_date(value):
    """
    Stores effectivity as a real DATE-compatible value.

    The desktop form intentionally accepts a plain year because assessment
    rolls commonly record effectivity by year. MariaDB DATE columns need a full
    date, so YYYY is stored as YYYY-01-01 while still preserving the year used
    by billing and assessment filters.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()

    raw = str(value).strip()
    if not raw:
        return None

    if raw.isdigit() and len(raw) == 4:
        year = int(raw)
        if 1900 <= year <= 2200:
            return f"{year}-01-01"

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass

    raise HTTPException(
        status_code=422,
        detail="Effectivity must be a year like 2023 or a date like 2023-01-01.",
    )


def _effectivity_year_expr(model):
    year_source = func.coalesce(
        func.nullif(func.trim(model.effectivity_date), ""), model.tax_year
    )
    return cast(func.substr(year_source, 1, 4), Integer)


def _history_year_expr():
    return cast(
        func.substr(func.trim(PropertyAssessmentHistory.tax_year), 1, 4),
        Integer,
    )


def _assessment_effective_by_year(model, as_of_year):
    history_is_effective = (
        exists()
        .where(PropertyAssessmentHistory.property_id == model.id)
        .where(PropertyAssessmentHistory.assessed_value > 0)
        .where(_history_year_expr() <= int(as_of_year))
    )
    return or_(
        _effectivity_year_expr(model) <= int(as_of_year),
        history_is_effective,
    )


def search_properties(
    term,
    limit=100,
    cursor=None,
    kind=None,
    year_start=None,
    year_end=None,
    as_of_year=None,
    barangay=None,
    db_session: Session = None,
):
    """
    Enhanced search with optional filters and fuzzy owner-name matching.

    Search strategy:
      - TD number / PIN (contains dashes or is all-digits): exact SQL match only.
        Fuzzy matching on structured identifiers produces false positives.
      - Owner name / location (contains letters, no dashes): SQL LIKE for
        candidate retrieval, then Python-side fuzzy re-ranking using
        difflib.SequenceMatcher. This catches typos, missing spaces, and
        slight misspellings without any new dependencies.

    Fuzzy threshold: 0.55 similarity ratio (0–1 scale).
      - "dela crus" vs "DELA CRUZ"  → ~0.89 ✅
      - "delacrus"  vs "DELA CRUZ"  → ~0.72 ✅
      - "juan"      vs "JUAN DELA CRUZ" → ~0.44 ❌ (too short, use LIKE instead)
    Results are sorted by similarity score descending so the best match
    appears first.
    """
    import difflib

    query = db_session.query(Property).filter(Property.deleted_at == None)

    # Determine search mode from the term
    is_id_search = False
    if term:
        clean_term = str(term).strip()
        if " " in clean_term and not any(c.isalpha() for c in clean_term):
            # Looks like a spaced TD number — convert spaces to dashes
            dashed_term = clean_term.replace(" ", "-")
            query = query.filter(
                (Property.td_number == dashed_term)
                | (Property.pin == dashed_term)
                | (Property.prev_td_number == dashed_term)
                | (Property.td_number.like(f"%{dashed_term}%"))
                | (Property.pin.like(f"%{dashed_term}%"))
                | (Property.prev_td_number.like(f"%{dashed_term}%"))
            )
            is_id_search = True
        elif "-" in clean_term:
            normalized_term = clean_term.upper()
            # Structured TD number / PIN — exact match only
            query = query.filter(
                (func.upper(func.trim(Property.td_number)) == normalized_term)
                | (func.upper(func.trim(Property.pin)) == normalized_term)
                | (func.upper(func.trim(Property.prev_td_number)) == normalized_term)
            )
            is_id_search = True
        else:
            # Name / location search — broad LIKE to pull candidates, then fuzzy-rank
            like_term = f"%{clean_term}%"
            query = query.filter(
                (Property.td_number.like(like_term))
                | (Property.prev_td_number.like(like_term))
                | (Property.owner_name.like(like_term))
                | (Property.payor_name.like(like_term))
                | (Property.pin.like(like_term))
                | (Property.location.like(like_term))
            )

    if kind and kind != "ALL":
        query = query.filter(Property.kind_of_property == kind)

    if as_of_year:
        as_of = int(as_of_year)
        replacement = aliased(Property)
        replaced_td_numbers = (
            db_session.query(func.trim(replacement.prev_td_number))
            .filter(
                replacement.deleted_at == None,
                replacement.prev_td_number != None,
                func.trim(replacement.prev_td_number) != "",
                _assessment_effective_by_year(replacement, as_of),
            )
            .scalar_subquery()
        )
        query = query.filter(_assessment_effective_by_year(Property, as_of))
        query = query.filter(~func.trim(Property.td_number).in_(replaced_td_numbers))
    elif year_start or year_end:
        # effectivity_date is legacy text and may contain either "2024" or
        # full dates like "2024-01-01". Compare on the extracted year so the
        # "TO" filter includes full dates within that year.
        effectivity_year = _effectivity_year_expr(Property)
        if year_start:
            query = query.filter(effectivity_year >= int(year_start))
        if year_end:
            query = query.filter(effectivity_year <= int(year_end))

    if barangay and barangay != "ALL":
        query = query.filter(Property.barangay == barangay)

    if cursor:
        query = query.filter(Property.id < int(cursor))

    # Fetch a larger candidate pool when fuzzy matching will be applied so
    # we have enough results to rank before trimming to the requested limit.
    fetch_limit = limit if is_id_search or not term else min(limit * 4, 400)
    results = query.order_by(Property.id.desc()).limit(fetch_limit).all()

    # ── Fuzzy re-ranking for name searches ──────────────────────────────────
    # Only apply when the term contains letters and is not a structured ID.
    FUZZY_THRESHOLD = 0.55

    if term and not is_id_search and any(c.isalpha() for c in str(term).strip()):
        search_upper = str(term).strip().upper()

        def _score(prop) -> float:
            """
            Returns the best similarity ratio across the searchable text fields.
            Uses SequenceMatcher which handles insertions, deletions, and
            substitutions — good for name typos and missing spaces.
            """
            candidates = [
                prop.owner_name or "",
                prop.payor_name or "",
                prop.location or "",
                prop.td_number or "",
                prop.prev_td_number or "",
            ]
            if any(search_upper in c.upper() for c in candidates):
                return 1.0
            return max(
                difflib.SequenceMatcher(None, search_upper, c.upper()).ratio()
                for c in candidates
            )

        scored = [(p, _score(p)) for p in results]
        # Keep only results above the threshold, sorted best-first
        scored = [(p, s) for p, s in scored if s >= FUZZY_THRESHOLD]
        scored.sort(key=lambda x: x[1], reverse=True)
        results = [p for p, _ in scored[:limit]]
    else:
        results = results[:limit]

    history_by_property = {}
    if as_of_year and results:
        property_ids = [prop.id for prop in results]
        history_rows = (
            db_session.query(PropertyAssessmentHistory)
            .filter(PropertyAssessmentHistory.property_id.in_(property_ids))
            .order_by(
                PropertyAssessmentHistory.property_id.asc(),
                PropertyAssessmentHistory.id.asc(),
            )
            .all()
        )
        for history_row in history_rows:
            history_by_property.setdefault(history_row.property_id, []).append(
                history_row
            )

    rows = []
    for prop in results:
        selected_value = float(prop.assessed_value or 0)
        selected_kind = prop.kind_of_property
        selected_effectivity = prop.effectivity_date
        rate_year = prop.tax_year

        if as_of_year:
            snapshots = assessment_snapshots(
                prop,
                db_session,
                history_rows=history_by_property.get(prop.id, []),
            )
            snapshot = assessment_snapshot_for_year(
                prop,
                int(as_of_year),
                db_session,
                snapshots=snapshots,
            )
            if snapshot:
                selected_value = float(snapshot["assessed_value"])
                selected_kind = snapshot["kind_of_property"]
                selected_effectivity = snapshot["effective_year"]
            rate_year = int(as_of_year)

        basic_rate, sef_rate = _get_policy_rates(rate_year, db_session)
        rows.append(
            (
                prop.id,
                prop.td_number,
                prop.owner_name,
                prop.payor_name,
                prop.lot_number,
                prop.area,
                prop.location,
                selected_kind,
                prop.accountable_officer,
                selected_value,
                selected_value * basic_rate,
                selected_value * sef_rate,
                float(prop.penalty or 0),
                float(prop.discount or 0),
                selected_value * (basic_rate + sef_rate)
                + float(prop.penalty or 0)
                - float(prop.discount or 0),
                prop.or_number,
                prop.or_date,
                prop.tax_year,
                prop.pin,
                prop.block_number,
                prop.prev_td_number,
                selected_effectivity,
                prop.barangay,
            )
        )

    return rows


def get_barangays(db_session: Session):
    """Returns a list of all unique barangay names in the database."""
    results = (
        db_session.query(Property.barangay)
        .filter(Property.barangay != None, Property.barangay != "")
        .distinct()
        .order_by(Property.barangay.asc())
        .all()
    )
    return [r[0] for r in results]


def get_property_by_id(property_id, db_session: Session):
    return (
        db_session.query(Property)
        .filter(Property.id == property_id, Property.deleted_at == None)
        .first()
    )


def _property_effectivity_year(prop):
    return assessment_year(
        getattr(prop, "effectivity_date", None) or getattr(prop, "tax_year", None)
    )


def _td_text(value):
    return str(value or "").strip().upper()


def get_active_properties_by_td(td_number, db_session: Session, exclude_id=None):
    """Return every exact active TD match in a stable, reviewable order."""
    td = _td_text(td_number)
    if not td:
        return []
    query = db_session.query(Property).filter(
        Property.deleted_at == None,
        func.upper(func.trim(Property.td_number)) == td,
    )
    if exclude_id is not None:
        query = query.filter(Property.id != int(exclude_id))
    return query.order_by(Property.id.asc()).all()


def _one_active_property_by_td(td_number, db_session: Session, exclude_id=None):
    matches = get_active_properties_by_td(
        td_number, db_session=db_session, exclude_id=exclude_id
    )
    if len(matches) > 1:
        raise AmbiguousPropertyError(td_number, matches)
    return matches[0] if matches else None


def _td_chain_for_property(seed_prop, db_session: Session):
    """Return all active TD records connected by Previous TD, oldest to newest."""
    if not seed_prop:
        return []

    by_id = {seed_prop.id: seed_prop}
    current = seed_prop
    visited = {seed_prop.id}

    # Walk backwards through Previous TD links.
    while current and _td_text(current.prev_td_number):
        parent = _one_active_property_by_td(current.prev_td_number, db_session)
        if not parent or parent.id in visited:
            break
        by_id[parent.id] = parent
        visited.add(parent.id)
        current = parent

    # Walk forwards through replacement links. Refuse to choose automatically
    # when a former TD has several successors (for example, a subdivision).
    queue = list(by_id.values())
    scanned = set()
    while queue:
        current = queue.pop(0)
        if current.id in scanned:
            continue
        scanned.add(current.id)
        children = (
            db_session.query(Property)
            .filter(
                Property.deleted_at == None,
                func.upper(func.trim(Property.prev_td_number))
                == _td_text(current.td_number),
            )
            .all()
        )
        if len(children) > 1:
            # One former TD may legitimately lead to several subdivided
            # properties. That is a selection problem, not a condition where
            # the server may choose a child based on sort order.
            raise AmbiguousPropertyError(current.td_number, children)
        children.sort(key=lambda p: (_property_effectivity_year(p) or 9999, p.id or 0))
        for child in children:
            if child.id not in by_id:
                by_id[child.id] = child
                queue.append(child)

    chain = list(by_id.values())
    chain.sort(key=lambda p: (_property_effectivity_year(p) or 0, p.id or 0))
    return chain


def resolve_property_for_tax_year(
    td_number, tax_year, db_session: Session, property_id=None
):
    """Resolve the TD record that should receive a payment for a tax year.

    A searched TD can be an old TD, current TD, or a Previous TD value on a
    newer record. The selected payment target must be the chain member whose
    effectivity covers the tax year being paid.
    """
    td = _td_text(td_number)
    if not td or not tax_year:
        return None
    try:
        year = int(str(tax_year).strip()[:4])
    except (TypeError, ValueError):
        return None

    seed = None
    if property_id is not None:
        seed = get_property_by_id(int(property_id), db_session)
    else:
        seed = _one_active_property_by_td(td, db_session)
    if not seed:
        previous_matches = (
            db_session.query(Property)
            .filter(
                Property.deleted_at == None,
                func.upper(func.trim(Property.prev_td_number)) == td,
            )
            .order_by(Property.id.asc())
            .all()
        )
        if len(previous_matches) > 1:
            raise AmbiguousPropertyError(td, previous_matches)
        seed = previous_matches[0] if previous_matches else None
    if not seed:
        return None

    chain = _td_chain_for_property(seed, db_session)
    eligible = [
        prop
        for prop in chain
        if _property_effectivity_year(prop) is None
        or _property_effectivity_year(prop) <= year
    ]
    if not eligible:
        return None
    latest_year = max(_property_effectivity_year(prop) or 0 for prop in eligible)
    latest = [
        prop
        for prop in eligible
        if (_property_effectivity_year(prop) or 0) == latest_year
    ]
    if len(latest) > 1:
        raise AmbiguousPropertyError(td, latest)
    return latest[0]


def resolve_payment_property_for_tax_year(
    td_number, tax_year, db_session: Session, property_id=None
):
    """Resolve the property that owns the concrete billing obligation.

    A non-archived PropertyBilling row on the exact TD selected by the user is
    authoritative for payment posting. Assessment-chain effectivity is used
    only when that TD has no billing row for the requested year. This prevents
    a malformed Previous TD link or duplicate old/new assessment chain from
    silently moving a payment to a different parcel.
    """
    td = _td_text(td_number)
    try:
        year = int(str(tax_year).strip()[:4])
    except (TypeError, ValueError):
        return None

    requested_property = (
        get_property_by_id(int(property_id), db_session)
        if property_id is not None
        else _one_active_property_by_td(td, db_session)
    )
    if requested_property:
        direct_billing = (
            db_session.query(PropertyBilling.id)
            .filter(
                PropertyBilling.property_id == requested_property.id,
                PropertyBilling.tax_year == year,
                PropertyBilling.is_archived == False,
            )
            .first()
        )
        if direct_billing:
            return requested_property

    return resolve_property_for_tax_year(
        td,
        year,
        db_session,
        property_id=requested_property.id if requested_property else None,
    )


def resolve_payment_target(
    td_number, tax_year, db_session: Session, property_id=None
):
    target = resolve_payment_property_for_tax_year(
        td_number, tax_year, db_session, property_id=property_id
    )
    if not target:
        return None
    chain = _td_chain_for_property(target, db_session)
    return {
        "id": target.id,
        "td_number": target.td_number,
        "owner_name": target.owner_name,
        "effectivity_date": target.effectivity_date,
        "effectivity_year": _property_effectivity_year(target),
        "chain": [
            {
                "id": prop.id,
                "td_number": prop.td_number,
                "owner_name": prop.owner_name,
                "prev_td_number": prop.prev_td_number,
                "effectivity_date": prop.effectivity_date,
                "effectivity_year": _property_effectivity_year(prop),
            }
            for prop in chain
        ],
    }


def _has_payment_payload(data):
    return bool(
        str(data.get("OR Number") or "").strip()
        or str(data.get("Amount Paid") or "").strip()
    )


def _payment_only_payload(prop, data, user=None):
    """Use the live property record for payment posting without rewriting it."""
    payload = dict(data)
    payload["TD Number"] = prop.td_number
    payload["Owner Name"] = prop.owner_name
    payload["Payor"] = payload.get("Payor") or prop.payor_name or prop.owner_name
    payload["Assessed Value"] = prop.assessed_value
    payload["Barangay"] = prop.barangay
    payload["Location"] = prop.location
    payload["Kind of Property"] = prop.kind_of_property
    payload["PIN"] = prop.pin
    payload["Previous TD Number"] = prop.prev_td_number
    payload["Effectivity Date"] = prop.effectivity_date
    payload["Accountable Officer"] = payload.get("Accountable Officer") or get_username(
        user
    )
    return payload


def save_property(data, editing_id=None, user=None, db_session: Session = None):
    """
    Main orchestrator for saving or updating a property using ORM.
    """
    from backend.services.validation_service import (
        enforce_property_rules,
        ValidationError,
    )
    from backend.services.history_service import log_data_change

    try:
        # 1. Validate
        enforce_property_rules(data)

        # 2. Get or Create Property
        if editing_id:
            prop = db_session.query(Property).filter(Property.id == editing_id).first()
            if not prop:
                raise HTTPException(status_code=404, detail="Property not found")

            if _has_payment_payload(data):
                tax_years = billing.normalize_tax_years(data.get("Tax Year"))
                target_prop = prop
                if tax_years:
                    target_props = [
                        resolve_payment_property_for_tax_year(
                            prop.td_number,
                            year,
                            db_session,
                            property_id=prop.id,
                        )
                        for year in tax_years
                    ]
                    missing_years = [
                        year
                        for year, target in zip(tax_years, target_props)
                        if target is None
                    ]
                    if missing_years:
                        first_year = missing_years[0]
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"TD {prop.td_number} is not effective for tax year {first_year}. "
                                "Post the payment to the TD record that was active for that year, "
                                "or add the missing Previous TD record first."
                            ),
                        )
                    target_ids = {item.id for item in target_props if item}
                    if len(target_ids) > 1:
                        summary = ", ".join(
                            f"{year}: {target.td_number}"
                            for year, target in zip(tax_years, target_props)
                            if target
                        )
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                "This payment spans TD changes. Post the payment by TD/effectivity group instead: "
                                f"{summary}."
                            ),
                        )
                    if target_props and target_props[0]:
                        target_prop = target_props[0]

                payment_posted = _sync_financial_records(
                    target_prop.id,
                    _payment_only_payload(target_prop, data, user=user),
                    db_session,
                )
                db_session.commit()
                if payment_posted:
                    _refresh_dashboard_stats_after_payment(db_session)
                return {
                    "ok": True,
                    "property_id": target_prop.id,
                    "td_number": target_prop.td_number,
                    "target_changed": target_prop.id != prop.id,
                    "requested_property_id": prop.id,
                    "requested_td_number": prop.td_number,
                    "new_version": target_prop.version,
                    "payment_only": True,
                    "billing_sync": {"updated": 0, "years": []},
                    "prior_assessment_sync": {"updated": 0, "years": []},
                }

            # Conflict Detection
            client_version = data.get("version", 0)
            if client_version is not None and int(client_version) < prop.version:
                raise SyncConflictError(prop.__dict__, data)

            action = "UPDATE"
            before_data = {
                c.name: getattr(prop, c.name) for c in prop.__table__.columns
            }
        else:
            prop = Property()
            db_session.add(prop)
            action = "CREATE"
            before_data = None

        # 3. Map Fields (Normalize)
        def _up(v):
            cleaned = sanitize_string(v)
            return cleaned.upper() if cleaned else None

        new_td_number = _up(data.get("TD Number", prop.td_number))
        duplicate_query = db_session.query(Property).filter(
            Property.td_number == new_td_number
        )
        if prop.id:
            duplicate_query = duplicate_query.filter(Property.id != prop.id)
        duplicate = duplicate_query.first()
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"TD Number {new_td_number} is already used by property "
                    f"ID {duplicate.id}: {duplicate.owner_name}"
                ),
            )

        prop.td_number = new_td_number
        prop.owner_name = _up(data.get("Owner Name", prop.owner_name))
        prop.payor_name = _up(
            data.get("Payor", prop.payor_name)
            or data.get("Owner Name", prop.owner_name)
        )
        prop.lot_number = _up(data.get("Lot Number", prop.lot_number))
        prop.area = _up(data.get("Area", prop.area))
        prop.location = _up(data.get("Location", prop.location))
        prop.kind_of_property = _up(data.get("Kind of Property", prop.kind_of_property))
        prop.accountable_officer = _up(
            data.get("Accountable Officer", prop.accountable_officer)
        )
        prop.assessed_value = clean_currency(
            data.get("Assessed Value", prop.assessed_value)
        )
        prop.penalty = clean_currency(data.get("Penalty", prop.penalty))
        prop.discount = clean_currency(data.get("Discount", prop.discount))
        prop.or_number = _up(data.get("OR Number", prop.or_number))
        prop.or_date = data.get("OR Date", prop.or_date)
        prop.tax_year = _up(data.get("Tax Year", prop.tax_year))
        prop.pin = _up(data.get("PIN", prop.pin))
        prop.block_number = _up(data.get("Block Number", prop.block_number))
        prop.prev_td_number = _up(data.get("Previous TD Number", prop.prev_td_number))
        prop.effectivity_date = _normalize_effectivity_date(
            data.get("Effectivity Date", prop.effectivity_date)
        )
        prop.barangay = _up(
            data.get("Barangay", prop.barangay) or data.get("Location", prop.location)
        )

        if editing_id:
            prop.version += 1
        else:
            prop.version = 1
            prop.deleted_at = None

        db_session.flush()  # Get ID for new properties

        # 4. Log Change
        after_data = {c.name: getattr(prop, c.name) for c in prop.__table__.columns}
        log_data_change(
            user["id"] if user else 0,
            "properties",
            prop.id,
            action,
            before=before_data,
            after=after_data,
            username=get_username(user) if user else "unknown",
            db_session=db_session,
        )

        # 5. Financial Sync
        payment_posted = _sync_financial_records(prop.id, data, db_session)

        billing_sync = {"updated": 0, "years": []}
        old_assessed = (
            clean_currency(before_data.get("assessed_value")) if before_data else None
        )
        new_assessed = clean_currency(prop.assessed_value)
        old_kind = (
            str(before_data.get("kind_of_property") or "").strip().upper()
            if before_data
            else ""
        )
        new_kind = str(prop.kind_of_property or "").strip().upper()
        assessment_changed = old_assessed is not None and (
            abs(old_assessed - new_assessed) > 0.009 or old_kind != new_kind
        )
        username = get_username(user) if user else "unknown"
        new_effective_year = assessment_year(prop.effectivity_date or prop.tax_year)

        # Preserve the superseded assessment before applying a later valuation
        # or classification.
        if before_data and assessment_changed:
            old_effective_year = assessment_year(
                before_data.get("effectivity_date") or before_data.get("tax_year")
            )
            if old_effective_year and (
                new_effective_year is None or old_effective_year < new_effective_year
            ):
                upsert_history_version(
                    prop,
                    old_effective_year,
                    old_assessed,
                    username,
                    "Superseded by later assessment",
                    db_session,
                    kind_of_property=before_data.get("kind_of_property"),
                )

        # Optional correction for records whose prior AV was never captured.
        prior_value_raw = data.get("Prior Assessed Value")
        prior_year_raw = data.get("Prior Effectivity Year")
        has_prior_value = prior_value_raw not in (None, "")
        has_prior_year = prior_year_raw not in (None, "")
        prior_sync = {"updated": 0, "years": []}
        if has_prior_value != has_prior_year:
            raise HTTPException(
                status_code=422,
                detail="Prior Assessed Value and Prior Effectivity Year must be entered together.",
            )
        if has_prior_value:
            prior_year = assessment_year(prior_year_raw)
            prior_value = assessment_money(prior_value_raw)
            if not prior_year or prior_value <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Prior assessment requires a valid positive value and a 4-digit year.",
                )
            if not new_effective_year or prior_year >= new_effective_year:
                raise HTTPException(
                    status_code=422,
                    detail="Prior assessment year must be earlier than the current Effectivity year.",
                )

            upsert_history_version(
                prop,
                prior_year,
                prior_value,
                username,
                "Historical assessment correction",
                db_session,
            )
            corrected_years = []
            rows = (
                db_session.query(PropertyBilling)
                .filter(
                    PropertyBilling.property_id == prop.id,
                    PropertyBilling.is_archived == False,
                    PropertyBilling.tax_year >= prior_year,
                    PropertyBilling.tax_year < new_effective_year,
                )
                .with_for_update()
                .all()
            )
            for row in rows:
                if assessment_money(row.assessed_value) != prior_value:
                    row.assessed_value = prior_value
                    row.updated_at = datetime.now(timezone.utc)
                    corrected_years.append(int(row.tax_year))
            prior_sync = {
                "updated": len(corrected_years),
                "years": sorted(corrected_years),
            }

        if old_assessed is None or abs(old_assessed - new_assessed) > 0.009:
            billing_sync = billing.sync_existing_billing_assessed_value(
                prop.id,
                prop.assessed_value,
                effective_year=prop.effectivity_date or prop.tax_year,
                db_session=db_session,
            )

        db_session.commit()

        # The payment and its billing allocation are already committed. Refresh
        # the dashboard cache afterward so manual receipt entry is visible on
        # the next Dashboard load. A statistics failure must never roll back or
        # report failure for a payment that was successfully saved.
        if payment_posted:
            _refresh_dashboard_stats_after_payment(db_session)

        return {
            "ok": True,
            "property_id": prop.id,
            "new_version": prop.version,
            "billing_sync": billing_sync,
            "prior_assessment_sync": prior_sync,
        }

    except Exception as e:
        db_session.rollback()
        if isinstance(e, (HTTPException, ValidationError, SyncConflictError)):
            raise
        if isinstance(e, IntegrityError) and "uq_properties_td_number" in str(e):
            raise HTTPException(
                status_code=409,
                detail="TD Number is already used by another property.",
            )
        raise HTTPException(status_code=500, detail=f"Save failed: {str(e)}")


def _refresh_dashboard_stats_after_payment(db_session: Session):
    """Refresh dashboard cache without endangering an already-saved payment."""
    try:
        from backend.services.stats_service import refresh_system_stats

        refresh_system_stats(db_session=db_session)
    except Exception as stats_err:
        from utils import log_error_to_file

        log_error_to_file(
            "Stats refresh failed after manual payment posting",
            stats_err,
        )


def _sync_financial_records(prop_id, data, db_session: Session):
    """Synchronizes property billings and payments based on the saved property data."""
    tax_years = billing.normalize_tax_years(data.get("Tax Year"))
    av = clean_currency(data.get("Assessed Value"))
    pen = clean_currency(data.get("Penalty"))
    disc = clean_currency(data.get("Discount"))

    # Penalty/discount entered for a multi-year receipt are split across years
    # for backward compatibility. Assessed value is not split: each tax year
    # gets the historical value effective for that year.
    pen_shares = billing.split_amount_across_years(pen, len(tax_years))
    disc_shares = billing.split_amount_across_years(disc, len(tax_years))

    or_no = str(data.get("OR Number") or "").strip()
    should_pay = bool(or_no)
    paid = clean_currency(data.get("Amount Paid")) if should_pay else 0.0
    or_dt_raw = data.get("OR Date")
    normalized_or_date = billing.normalize_date_input(or_dt_raw) if should_pay else None
    if should_pay:
        if not billing.looks_like_valid_or_number(or_no):
            raise HTTPException(
                status_code=422, detail="Enter a valid Official Receipt number."
            )
        if paid <= 0:
            raise HTTPException(
                status_code=422, detail="A posted payment must be greater than zero."
            )
        if not normalized_or_date:
            raise HTTPException(
                status_code=422, detail="A valid Official Receipt date is required."
            )

    billing_rows = []

    for year, p_s, d_s in zip(tax_years, pen_shares, disc_shares):
        a_s = billing.resolve_assessed_value_for_billing_year(
            prop_id,
            year,
            av,
            db_session=db_session,
        )
        billing_rows.append(
            # Payment allocations are the only source that may mark a billing
            # row paid. Pre-filling every selected year as fully paid causes a
            # partial multi-year receipt to settle years that received nothing.
            billing.sync_property_billing(
                prop_id, year, a_s, p_s, d_s, has_payment=False, db_session=db_session
            )
        )

    if should_pay:
        allocated = billing.allocate_payment_amount(billing_rows, paid)

        # Every legitimate installment is immutable and receives its own
        # Payment row. Previously this code reused a row by property + OR +
        # date, so posting another tax year with the same receipt/date replaced
        # the old tax year and deleted its PaymentBilling allocation.
        from backend.models import Payment

        or_dt = datetime.strptime(normalized_or_date, "%Y-%m-%d")

        payor_name = data.get("Payor") or data.get("Owner Name")
        tax_year_str = billing.format_tax_years(data.get("Tax Year"))
        posted_by = data.get("Accountable Officer")
        remarks = str(data.get("Remarks") or "").strip()[:500] or None

        duplicate = payment.find_duplicate_payment_entry(
            prop_id,
            or_no,
            or_dt_raw,
            tax_year_str,
            db_session=db_session,
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Payment already exists for OR {or_no}, tax year {tax_year_str}, "
                    f"and date {billing.normalize_date_input(or_dt_raw)} (payment ID {duplicate['payment_id']}). "
                    "Use Edit Payment if the existing entry needs correction."
                ),
            )

        can_store_remarks = payment.has_payment_remarks_column(db_session)
        pay_obj = Payment(property_id=prop_id)
        db_session.add(pay_obj)

        pay_obj.amount = paid
        pay_obj.or_number = or_no
        pay_obj.date_paid = or_dt
        pay_obj.tax_year = tax_year_str
        pay_obj.posted_by = posted_by
        if can_store_remarks:
            pay_obj.remarks = remarks
        pay_obj.payor_name = payor_name
        pay_obj.penalty = pen  # store penalty on Payment record
        pay_obj.discount = disc  # store discount on Payment record

        db_session.flush()  # Get payment_id
        billing.sync_payment_billings(pay_obj.id, allocated, db_session=db_session)

    return should_pay


@require_permission("property_edit")
def update_property_details(prop_id, data, user):
    """Wrapper to update property details with professional permission check."""
    return save_property(data, editing_id=prop_id, user=user)


@require_permission("property_delete")
def soft_delete_property(
    property_id, user=None, ip_address=None, db_session: Session = None
):
    """Soft deletes a property - requires 'property_delete' permission."""
    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return 0

    old_data = {c.name: getattr(prop, c.name) for c in prop.__table__.columns}
    prop.deleted_at = datetime.now(timezone.utc)

    if user:
        audit = AuditLog(
            user_id=user.get("id"),
            username=user.get("username", "unknown"),
            action="SOFT_DELETE",
            table_name="properties",
            record_id=property_id,
            old_values=json.dumps(old_data, default=str),
            new_values=json.dumps(
                {
                    "deleted_at": (
                        prop.deleted_at.isoformat()
                        if hasattr(prop.deleted_at, "isoformat")
                        else str(prop.deleted_at)
                    )
                }
            ),
            ip_address=ip_address,
            timestamp=datetime.now(timezone.utc),
        )
        db_session.add(audit)

    deleted_at = prop.deleted_at
    db_session.commit()
    return {
        "id": prop.id,
        "td_number": prop.td_number,
        "deleted_at": deleted_at.strftime("%Y-%m-%d %H:%M") if deleted_at else None,
    }


def get_deleted_properties(limit=50, cursor=None, db_session: Session = None):
    """Fetches soft-deleted properties using cursor-based pagination."""
    safe_limit = min(max(1, int(limit)), 200)

    query = db_session.query(Property).filter(Property.deleted_at != None)
    if cursor:
        query = query.filter(Property.id < int(cursor))

    rows = (
        query.order_by(Property.deleted_at.desc(), Property.id.desc())
        .limit(safe_limit + 1)
        .all()
    )

    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    next_cursor = items[-1].id if has_more and items else None

    return {
        "items": [
            (
                prop.id,
                prop.td_number,
                prop.owner_name,
                prop.barangay or prop.location,
                prop.assessed_value,
                prop.deleted_at.strftime("%Y-%m-%d %H:%M") if prop.deleted_at else "",
            )
            for prop in items
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


@require_permission("property_edit")
def restore_property(property_id, user=None, db_session: Session = None):
    """Restores a soft-deleted property."""
    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return 0

    prop.deleted_at = None

    if user:
        from datetime import datetime, timezone

        audit = AuditLog(
            user_id=user.get("id"),
            username=user.get("username", "unknown"),
            action="RESTORE",
            table_name="properties",
            record_id=property_id,
            old_values=str({"deleted_at": "deleted"}),
            new_values=str({"deleted_at": None}),
            timestamp=datetime.now(timezone.utc),
        )
        db_session.add(audit)

    db_session.commit()
    return 1


@require_permission("property_delete")
def purge_property(property_id, user=None, db_session: Session = None):
    """
    Permanently deletes a property and ALL its child records from the database.

    Deletion order matters — FK constraints with RESTRICT must be satisfied:
      1. payment_billings  (FK → payments.id CASCADE, but delete explicitly first)
      2. receipt_history   (FK → properties.id RESTRICT)
      3. property_assessment_history (FK → properties.id RESTRICT)
      4. property_billings (FK → properties.id RESTRICT)
      5. payments          (FK → properties.id RESTRICT)
      6. property          (the record itself)
    """
    from backend.models import PaymentBilling, ReceiptHistory, PropertyAssessmentHistory

    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return 0

    full_data = {c.name: getattr(prop, c.name) for c in prop.__table__.columns}

    try:
        # 1. payment_billings — must go before payments
        payment_ids = [
            r[0]
            for r in db_session.query(Payment.id)
            .filter(Payment.property_id == property_id)
            .all()
        ]
        if payment_ids:
            db_session.query(PaymentBilling).filter(
                PaymentBilling.payment_id.in_(payment_ids)
            ).delete(synchronize_session=False)

        # 2. receipt_history
        db_session.query(ReceiptHistory).filter(
            ReceiptHistory.property_id == property_id
        ).delete(synchronize_session=False)

        # 3. property_assessment_history
        db_session.query(PropertyAssessmentHistory).filter(
            PropertyAssessmentHistory.property_id == property_id
        ).delete(synchronize_session=False)

        # 4. property_billings
        db_session.query(PropertyBilling).filter(
            PropertyBilling.property_id == property_id
        ).delete(synchronize_session=False)

        # 5. payments
        db_session.query(Payment).filter(Payment.property_id == property_id).delete(
            synchronize_session=False
        )

        # 6. the property itself
        db_session.delete(prop)
        db_session.flush()

        # Audit log
        if user:
            from backend.services.history_service import log_data_change

            log_data_change(
                user_id=user.get("id") if isinstance(user, dict) else 0,
                username=get_username(user),
                table_name="properties",
                record_id=property_id,
                action="PURGE",
                before=full_data,
                after=None,
                db_session=db_session,
            )

        db_session.commit()
        return 1

    except Exception:
        db_session.rollback()
        raise


def get_unspecified_properties(db_session: Session = None):
    """Fetches all properties where barangay is NULL, empty, or 'UNSPECIFIED'."""
    results = (
        db_session.query(Property)
        .filter(
            Property.deleted_at == None,
            (Property.barangay == None)
            | (text("TRIM(barangay) = ''"))
            | (Property.barangay == "UNSPECIFIED"),
        )
        .order_by(Property.owner_name.asc())
        .all()
    )

    return [(p.id, p.td_number, p.owner_name, p.location, p.barangay) for p in results]


@require_permission("property_edit")
def bulk_update_barangay(
    property_ids, new_barangay, user=None, db_session: Session = None
):
    """Updates the barangay for multiple properties at once."""
    if not property_ids or not new_barangay:
        return 0
    try:
        count = (
            db_session.query(Property)
            .filter(Property.id.in_(property_ids))
            .update({Property.barangay: new_barangay}, synchronize_session=False)
        )
        if count and user:
            from backend.services.history_service import log_data_change

            log_data_change(
                user_id=user.get("id") if isinstance(user, dict) else 0,
                username=get_username(user),
                table_name="properties",
                record_id=0,
                action="BULK_UPDATE_BARANGAY",
                before={"ids": property_ids},
                after={"barangay": new_barangay},
                db_session=db_session,
            )
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    return count


def get_property_by_td(td_number, db_session: Session = None):
    prop = _one_active_property_by_td(td_number, db_session)
    if not prop:
        return None
    return {c.name: getattr(prop, c.name) for c in prop.__table__.columns}


def get_assessment_roll(limit=100, cursor=None, db_session: Session = None):
    """
    Returns a paginated assessment roll using cursor-based pagination.
    Cursor is the last seen Property.id — avoids OFFSET degradation on large tables.
    """
    safe_limit = min(max(1, int(limit)), 200)  # hard cap at 200

    query = db_session.query(
        Property.id,
        Property.td_number,
        Property.owner_name,
        Property.location,
        Property.kind_of_property,
        Property.assessed_value,
        Property.barangay,
    ).filter(Property.deleted_at == None)

    if cursor:
        query = query.filter(Property.id > int(cursor))

    # Fetch one extra row to determine if there are more pages
    rows = query.order_by(Property.id.asc()).limit(safe_limit + 1).all()

    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    next_cursor = items[-1][0] if has_more and items else None

    return {
        "items": [
            {
                "id": r[0],
                "td_number": r[1],
                "owner_name": r[2],
                "location": r[3],
                "kind_of_property": r[4],
                "assessed_value": float(r[5] or 0),
                "barangay": r[6],
            }
            for r in items
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


def get_receivables_by_barangay(
    report_year: int = None, data_start_year: int = 2023, db_session: Session = None
):
    """
    Returns receivables breakdown by barangay.

    Parameters
    ----------
    report_year : int, optional
        Show cumulative receivables up to and including this year.
        If None, shows all-time totals.
    data_start_year : int
        The earliest year to include in the report. Defaults to 2023.
        Billing records before this year (created by the sync from old
        effectivity_date values) are excluded.
    """
    close_session = False
    if not db_session:
        from backend.database import SessionLocal

        db_session = SessionLocal()
        close_session = True

    try:
        from backend.models import PaymentBilling

        year_filter = str(report_year) if report_year else None

        # 1. Total Due per barangay — sum all billing records up to report_year
        # Join TaxPolicy per billing year so the rate reflects any policy changes.
        # Uses COALESCE to fall back to 1%+1%=2% if no policy row exists for a year.
        from backend.models import TaxPolicy as _TaxPolicy

        tp_alias = db_session.query(_TaxPolicy).subquery()

        due_query = (
            db_session.query(
                func.coalesce(Property.barangay, "UNSPECIFIED").label("barangay"),
                func.sum(PropertyBilling.assessed_value).label("total_assessed"),
                func.sum(
                    (
                        PropertyBilling.assessed_value
                        * func.coalesce(
                            db_session.query(
                                _TaxPolicy.basic_rate + _TaxPolicy.sef_rate
                            )
                            .filter(_TaxPolicy.tax_year == PropertyBilling.tax_year)
                            .correlate(PropertyBilling)
                            .scalar_subquery(),
                            0.02,
                        )
                    )
                    + PropertyBilling.penalty
                    - PropertyBilling.discount
                ).label("total_due"),
                func.sum(PropertyBilling.penalty).label("total_penalty"),
                func.sum(PropertyBilling.discount).label("total_discount"),
            )
            .join(PropertyBilling, PropertyBilling.property_id == Property.id)
            .filter(Property.deleted_at == None)
        )
        if year_filter:
            due_query = due_query.filter(PropertyBilling.tax_year <= year_filter)
        # Always apply the data start year floor to exclude pre-data billing records
        due_query = due_query.filter(PropertyBilling.tax_year >= str(data_start_year))

        due_results = due_query.group_by(Property.barangay).all()

        # 2. Total Collected per barangay.
        #
        # Keep this on the same basis as Total Due: billing tax years. Using
        # Payment.date_paid here mixes cash posting date with billing-year due,
        # which lets future-year prepayments or imported date mistakes distort
        # receivable balances by barangay.
        coll_query = (
            db_session.query(
                func.coalesce(Property.barangay, "UNSPECIFIED").label("barangay"),
                func.sum(PaymentBilling.amount_paid).label("total_collected"),
            )
            .join(PropertyBilling, PropertyBilling.property_id == Property.id)
            .join(PaymentBilling, PaymentBilling.billing_id == PropertyBilling.id)
            .filter(Property.deleted_at == None)
        )
        if year_filter:
            coll_query = coll_query.filter(PropertyBilling.tax_year <= year_filter)
        # Also apply data_start_year floor to collections
        coll_query = coll_query.filter(PropertyBilling.tax_year >= str(data_start_year))

        coll_results = coll_query.group_by(Property.barangay).all()

        # Merge into a single dict keyed by barangay
        data = {}
        for r in due_results:
            brgy = r[0] or "UNSPECIFIED"
            data[brgy] = {
                "barangay": brgy,
                "total_assessed": float(r[1] or 0),
                "total_due": float(r[2] or 0),
                "total_penalty": float(r[3] or 0),
                "total_discount": float(r[4] or 0),
                "total_collected": 0.0,
            }

        for r in coll_results:
            brgy = r[0] or "UNSPECIFIED"
            if brgy not in data:
                data[brgy] = {
                    "barangay": brgy,
                    "total_assessed": 0.0,
                    "total_due": 0.0,
                    "total_penalty": 0.0,
                    "total_discount": 0.0,
                    "total_collected": 0.0,
                }
            data[brgy]["total_collected"] = float(r[1] or 0)

        # Build result tuples: (brgy, assessed, due, penalty, discount, collected, receivable)
        results = []
        for brgy, d in sorted(
            data.items(),
            key=lambda x: x[1]["total_due"]
            - x[1]["total_discount"]
            - x[1]["total_collected"],
            reverse=True,
        ):
            # Correct formula: Total Due already has discount subtracted in the SQL
            # (assessed*0.02 + penalty - discount), so receivable = total_due - collected
            # BUT total_due in the query is: (assessed*0.02) + penalty - discount
            # so discount is already baked in. The displayed "Total Discount" column
            # is informational. Receivable = total_due - total_collected is correct.
            # However the sort should use the same formula for consistency.
            receivable = d["total_due"] - d["total_collected"]
            results.append(
                (
                    brgy,
                    d["total_assessed"],
                    d["total_due"],
                    d["total_penalty"],
                    d["total_discount"],
                    d["total_collected"],
                    receivable,
                )
            )

        return results

    finally:
        if close_session:
            db_session.close()
