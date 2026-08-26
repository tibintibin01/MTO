# -*- coding: utf-8 -*-
"""
Admin data-quality tools: TD number audit/fix, shadow duplicate cleanup,
tax policy management, and billing year sync.

Split from the monolithic system.py to keep each router focused.
"""

from typing import Optional  # noqa: F401 — used in type hints within function bodies
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import func

from backend.deps import get_current_user, admin_only, read_only, get_db, Session
from utils.logger import mto_logger

router = APIRouter(tags=["Admin Tools"])


# ---------------------------------------------------------------------------
# TD Number Audit
# ---------------------------------------------------------------------------

@router.get("/system/td-number-audit")
async def td_number_audit(
    current_user: dict = Depends(read_only),
    db_session: Session = Depends(get_db),
):
    """
    Scans all active properties and payments for:
      1. Malformed TD numbers
      2. Duplicate TD numbers
      3. Duplicate payments (same OR + same tax year)
      4. Shadow duplicates (malformed TD that resolves to an existing correct TD)
    """
    import re
    from backend.models import Property, Payment

    PATTERN = re.compile(r"^\d{2}-\d{4}-\d{5}$")

    rows = (
        db_session.query(
            Property.id,
            Property.td_number,
            Property.owner_name,
            Property.duplicate_td_verified,
            Property.duplicate_td_reference,
            Property.duplicate_td_reason,
            Property.duplicate_td_approved_by,
            Property.duplicate_td_approved_at,
        )
        .filter(Property.deleted_at == None)
        .order_by(Property.id.asc())
        .all()
    )

    # ── 1. Malformed TD numbers ───────────────────────────────────────────────
    invalid = []
    for row in rows:
        prop_id, td, owner = row[:3]
        td_str = (td or "").strip()
        if not td_str:
            reason = "Empty TD number"
        elif not PATTERN.match(td_str):
            parts = td_str.split("-")
            if len(parts) != 3:
                reason = f"Wrong number of segments (expected 3, got {len(parts)})"
            elif len(parts[0]) != 2:
                reason = f"First segment should be 2 digits, got '{parts[0]}' ({len(parts[0])} chars)"
            elif len(parts[1]) != 4:
                reason = f"Second segment should be 4 digits, got '{parts[1]}' ({len(parts[1])} chars)"
            elif len(parts[2]) != 5:
                reason = f"Third segment should be 5 digits, got '{parts[2]}' ({len(parts[2])} chars)"
            elif not parts[0].isdigit() or not parts[1].isdigit() or not parts[2].isdigit():
                reason = "Contains non-numeric characters"
            else:
                reason = "Does not match 06-XXXX-XXXXX format"
        else:
            continue
        invalid.append({"id": prop_id, "td_number": td_str or "(empty)", "owner_name": owner or "", "reason": reason})

    # ── 2. Duplicate TD numbers ───────────────────────────────────────────────
    td_groups: dict = defaultdict(list)
    for row in rows:
        prop_id, td, owner = row[:3]
        verified, reference, reason, approved_by, approved_at = row[3:]
        td_str = (td or "").strip()
        if td_str:
            td_groups[td_str].append({
                "id": prop_id,
                "owner_name": owner or "",
                "verified": bool(verified),
                "reference": reference or "",
                "reason": reason or "",
                "approved_by": approved_by or "",
                "approved_at": approved_at.isoformat() if approved_at else "",
            })

    duplicate_tds = []
    verified_duplicate_tds = []
    for td_str, entries in td_groups.items():
        if len(entries) > 1:
            is_verified_group = all(entry["verified"] for entry in entries)
            for entry in entries:
                result = {
                    "id": entry["id"], "td_number": td_str,
                    "owner_name": entry["owner_name"],
                    "reference": entry["reference"],
                    "authorization_reason": entry["reason"],
                    "approved_by": entry["approved_by"],
                    "approved_at": entry["approved_at"],
                    "reason": (
                        f"Verified duplicate — shared by {len(entries)} properties"
                        if is_verified_group
                        else f"Unresolved duplicate — shared by {len(entries)} properties "
                             f"(IDs: {', '.join(str(e['id']) for e in entries)})"
                    ),
                }
                if is_verified_group:
                    verified_duplicate_tds.append(result)
                else:
                    duplicate_tds.append(result)

    # ── 3. Duplicate payments ─────────────────────────────────────────────────
    pay_rows = (
        db_session.query(Payment.property_id, Payment.id, Payment.or_number,
                         Payment.tax_year, Payment.amount, Payment.date_paid,
                         Property.td_number, Property.owner_name)
        .join(Property, Property.id == Payment.property_id)
        .filter(Payment.or_number != None, Payment.or_number != "")
        .order_by(Payment.property_id.asc(), Payment.or_number.asc(), Payment.tax_year.asc())
        .all()
    )

    pay_groups: dict = defaultdict(list)
    for property_id, pay_id, or_no, tax_yr, amount, date_paid, td_no, owner in pay_rows:
        key = (
            int(property_id),
            str(or_no).strip(),
            str(tax_yr).strip() if tax_yr else "",
        )
        pay_groups[key].append({
            "property_id": int(property_id),
            "payment_id": pay_id, "or_number": str(or_no).strip(),
            "tax_year": str(tax_yr) if tax_yr else "", "amount": float(amount or 0),
            "date_paid": date_paid.strftime("%Y-%m-%d") if date_paid else "",
            "td_number": td_no or "", "owner_name": owner or "",
        })

    duplicate_payments = []
    for (_property_id, or_no, tax_yr), entries in pay_groups.items():
        if len(entries) > 1:
            sorted_entries = sorted(entries, key=lambda e: e["payment_id"])
            original_id = sorted_entries[0]["payment_id"]
            all_ids = ", ".join(str(e["payment_id"]) for e in sorted_entries)
            for entry in sorted_entries[1:]:
                duplicate_payments.append({
                    **entry,
                    "reason": (
                        f"Same property account, OR and tax year — keep ID "
                        f"{original_id}, review this copy (all IDs: {all_ids})"
                    ),
                })

    # ── 4. Shadow duplicates ──────────────────────────────────────────────────
    valid_td_set = {
        (row[1] or "").strip()
        for row in rows
        if PATTERN.match((row[1] or "").strip())
    }

    def apply_fix_rules(td: str):
        parts = td.split("-")
        if len(parts) != 3:
            return None
        s1, s2, s3 = parts
        r3 = re.match(r"^(\d{2})(\d{4})-(\d{5})$", td)
        if r3:
            candidate = f"{r3.group(1)}-{r3.group(2)}-{r3.group(3)}"
            if PATTERN.match(candidate):
                return candidate
        if len(s2) == 3 and s2.isdigit():
            s2 = "0" + s2
        if len(s3) == 6 and s3.isdigit() and s3[0] == "0":
            s3 = s3[1:]
        candidate = f"{s1}-{s2}-{s3}"
        return candidate if PATTERN.match(candidate) else None

    td_lookup = {
        (row[1] or "").strip(): (row[0], row[2] or "")
        for row in rows
    }
    shadow_duplicates = []
    for row in rows:
        prop_id, td, owner = row[:3]
        td_str = (td or "").strip()
        if not td_str or PATTERN.match(td_str):
            continue
        fixed = apply_fix_rules(td_str)
        if fixed and fixed in valid_td_set:
            correct_id, correct_owner = td_lookup.get(fixed, (None, ""))
            shadow_duplicates.append({
                "bad_id": prop_id, "bad_td": td_str, "bad_owner": owner or "",
                "correct_id": correct_id, "correct_td": fixed, "correct_owner": correct_owner,
                "action": f"Delete property ID {prop_id} (bad TD) — keep ID {correct_id} (correct TD)",
            })

    return {
        "total_scanned": len(rows),
        "total_payments_scanned": len(pay_rows),
        "invalid_count": len(invalid),
        "duplicate_td_count": len(duplicate_tds),
        "verified_duplicate_td_count": len(verified_duplicate_tds),
        "duplicate_payment_count": len(duplicate_payments),
        "shadow_duplicate_count": len(shadow_duplicates),
        "invalid": invalid,
        "duplicate_tds": duplicate_tds,
        "verified_duplicate_tds": verified_duplicate_tds,
        "duplicate_payments": duplicate_payments,
        "shadow_duplicates": shadow_duplicates,
        "format": "DD-DDDD-DDDDD (e.g. 06-0014-00239)",
    }


# ---------------------------------------------------------------------------
# TD Number Auto-Fix
# ---------------------------------------------------------------------------

@router.post("/system/td-number-fix")
async def td_number_fix(
    dry_run: bool = True,
    current_user: dict = Depends(admin_only),
    db_session: Session = Depends(get_db),
):
    """
    Auto-fixes malformed TD numbers using three rules.
    dry_run=true → preview only. dry_run=false → applies fixes.
    """
    import re
    from backend.models import Property

    VALID = re.compile(r"^\d{2}-\d{4}-\d{5}$")

    def try_fix(td: str):
        td = td.strip()
        if VALID.match(td):
            return td, None
        r3 = re.match(r"^(\d{2})(\d{4})-(\d{5})$", td)
        if r3:
            fixed = f"{r3.group(1)}-{r3.group(2)}-{r3.group(3)}"
            if VALID.match(fixed):
                return fixed, "Rule 3: inserted dash after first 2 digits"
        r3b = re.match(r"^(\d{2})(\d{4})-(\d+)$", td)
        if r3b:
            td = f"{r3b.group(1)}-{r3b.group(2)}-{r3b.group(3)}"
        parts = td.split("-")
        if len(parts) != 3:
            return None, f"Cannot fix: {len(parts)} segments (expected 3)"
        seg1, seg2, seg3 = parts
        if len(seg2) == 3 and seg2.isdigit():
            seg2 = "0" + seg2
            td = f"{seg1}-{seg2}-{seg3}"
        if len(seg3) == 6 and seg3.isdigit() and seg3[0] == "0":
            seg3 = seg3[1:]
            td = f"{seg1}-{seg2}-{seg3}"
        if VALID.match(td):
            rules = []
            if len(parts[1]) == 3:
                rules.append("Rule 2: added leading zero to second segment")
            if len(parts[2]) == 6:
                rules.append("Rule 1: removed first zero from third segment")
            return td, "; ".join(rules) if rules else "Fixed"
        return None, f"Unfixable after rules: result '{td}'"

    rows = db_session.query(Property).filter(Property.deleted_at == None).order_by(Property.id.asc()).all()
    fixed_list, unfixable_list = [], []
    already_valid = 0
    td_to_prop_id = {(p.td_number or "").strip(): p.id for p in rows if (p.td_number or "").strip()}
    planned_fixed_tds: set = set()

    for prop in rows:
        td_orig = (prop.td_number or "").strip()
        if VALID.match(td_orig):
            already_valid += 1
            continue
        fixed_td, rule = try_fix(td_orig)
        if fixed_td and VALID.match(fixed_td):
            existing_prop_id = td_to_prop_id.get(fixed_td)
            if existing_prop_id is not None and existing_prop_id != prop.id:
                unfixable_list.append({"id": prop.id, "td_number": td_orig, "owner_name": prop.owner_name or "",
                                       "reason": f"Fixed TD '{fixed_td}' already belongs to property ID {existing_prop_id}"})
                continue
            if fixed_td in planned_fixed_tds:
                unfixable_list.append({"id": prop.id, "td_number": td_orig, "owner_name": prop.owner_name or "",
                                       "reason": f"Fixed TD '{fixed_td}' is duplicated by another planned fix"})
                continue
            planned_fixed_tds.add(fixed_td)
            fixed_list.append({"id": prop.id, "original": td_orig, "fixed": fixed_td,
                                "owner_name": prop.owner_name or "", "rule": rule})
        else:
            unfixable_list.append({"id": prop.id, "td_number": td_orig, "owner_name": prop.owner_name or "",
                                   "reason": rule or "No rule matched"})

    if dry_run:
        return {"dry_run": True, "total_scanned": len(rows), "already_valid": already_valid,
                "will_fix": len(fixed_list), "unfixable": len(unfixable_list),
                "fixes": fixed_list, "unfixable_list": unfixable_list}

    existing_tds = {r[0] for r in db_session.query(Property.td_number).filter(Property.deleted_at == None).all()}
    safe_fixes, collision_list = [], []
    for item in fixed_list:
        check_set = existing_tds - {item["original"]}
        if item["fixed"] in check_set:
            collision_list.append({**item, "reason": f"Collision: '{item['fixed']}' already exists"})
        else:
            safe_fixes.append(item)
            existing_tds.add(item["fixed"])
            existing_tds.discard(item["original"])

    applied = 0
    for item in safe_fixes:
        prop = db_session.query(Property).filter(Property.id == item["id"]).first()
        if prop:
            prop.td_number = item["fixed"]
            applied += 1

    if applied > 0:
        db_session.flush()
        from backend.services.history_service import log_data_change
        log_data_change(
            user_id=current_user.get("id", 0), table_name="properties", record_id=0,
            action="TD_NUMBER_AUTO_FIX",
            before={"count": applied, "note": "batch fix"},
            after={"fixed": applied, "unfixable": len(unfixable_list), "collisions": len(collision_list)},
            username=current_user.get("username", "system"), db_session=db_session,
        )

    db_session.commit()
    mto_logger.info(f"TD number auto-fix: {applied} fixed, {len(unfixable_list)} unfixable, {len(collision_list)} collisions",
                    user=current_user.get("username"))
    return {"dry_run": False, "total_scanned": len(rows), "already_valid": already_valid,
            "fixed": applied, "unfixable": len(unfixable_list), "unfixable_list": unfixable_list,
            "collisions": len(collision_list), "collision_list": collision_list}


# ---------------------------------------------------------------------------
# Shadow Duplicate Cleanup
# ---------------------------------------------------------------------------

class ShadowDeleteRequest(BaseModel):
    bad_ids: list


@router.post("/system/shadow-duplicate-cleanup")
async def shadow_duplicate_cleanup(
    data: ShadowDeleteRequest,
    current_user: dict = Depends(admin_only),
    db_session: Session = Depends(get_db),
):
    """Batch soft-deletes bad TD property records from shadow duplicate pairs."""
    from backend.models import Property, Payment
    from backend.services.system_service import log_action

    if not data.bad_ids:
        raise HTTPException(status_code=400, detail="bad_ids list is required.")

    bad_ids = [int(i) for i in data.bad_ids][:1000]
    props = {p.id: p for p in db_session.query(Property).filter(Property.id.in_(bad_ids)).all()}
    pay_counts = {
        r[0]: r[1]
        for r in db_session.query(Payment.property_id, func.count(Payment.id))
        .filter(Payment.property_id.in_(bad_ids)).group_by(Payment.property_id).all()
    }

    deleted, skipped = [], []
    now = datetime.now(timezone.utc)

    for pid in bad_ids:
        prop = props.get(pid)
        if not prop:
            skipped.append({"id": pid, "reason": "Property not found"})
            continue
        pay_count = pay_counts.get(pid, 0)
        if pay_count > 0:
            skipped.append({"id": pid, "td_number": prop.td_number, "owner_name": prop.owner_name,
                            "reason": f"Has {pay_count} payment(s) — manual review required"})
            continue
        prop.deleted_at = now
        deleted.append({"id": pid, "td_number": prop.td_number, "owner_name": prop.owner_name})

    if deleted:
        log_action(current_user,
                   f"Shadow duplicate cleanup: {len(deleted)} soft-deleted, {len(skipped)} skipped.",
                   db_session=db_session)
        db_session.commit()

    mto_logger.info(f"Shadow cleanup: {len(deleted)} deleted, {len(skipped)} skipped",
                    user=current_user.get("username"))
    return {"deleted": len(deleted), "skipped": len(skipped),
            "deleted_list": deleted, "skipped_list": skipped[:50]}


@router.post("/system/normalize-property-names")
async def normalize_property_names(
    dry_run: bool = True,
    current_user: dict = Depends(admin_only),
    db_session: Session = Depends(get_db),
):
    """Preview or decode HTML entities stored in property owner/payor names."""
    from backend.models import Property
    from backend.services.history_service import log_data_change
    from utils.sanitizer import sanitize_string

    # Match the dashboard's definition of a property. Archived/soft-deleted
    # records remain available for history, but they should not inflate this
    # operator-facing scan count or be modified by a routine cleanup.
    properties = (
        db_session.query(Property)
        .filter(Property.deleted_at.is_(None))
        .order_by(Property.id.asc())
        .all()
    )
    affected = 0
    fields_changed = 0
    sample = []

    for prop in properties:
        changes = {}
        for field_name in ("owner_name", "payor_name"):
            old_value = getattr(prop, field_name, None)
            if old_value is None:
                continue
            new_value = sanitize_string(old_value)
            if new_value != old_value:
                changes[field_name] = {"before": old_value, "after": new_value}

        if not changes:
            continue

        affected += 1
        fields_changed += len(changes)
        if len(sample) < 25:
            sample.append({
                "property_id": prop.id,
                "td_number": prop.td_number,
                "before": changes.get("owner_name", {}).get("before", prop.owner_name),
                "after": changes.get("owner_name", {}).get("after", prop.owner_name),
                "fields": sorted(changes),
            })

        if not dry_run:
            for field_name, values in changes.items():
                setattr(prop, field_name, values["after"])

    if not dry_run and affected:
        log_data_change(
            user_id=current_user.get("id", 0),
            table_name="properties",
            record_id=0,
            action="NORMALIZE_PROPERTY_NAME_ENTITIES",
            before={"properties_affected": affected, "fields_changed": fields_changed},
            after={"properties_normalized": affected, "fields_changed": fields_changed},
            username=current_user.get("username", "system"),
            db_session=db_session,
        )
        db_session.commit()

    return {
        "dry_run": bool(dry_run),
        "properties_scanned": len(properties),
        "properties_affected": affected,
        "fields_changed": fields_changed,
        "sample": sample,
    }


# ---------------------------------------------------------------------------
# Tax Policy
# ---------------------------------------------------------------------------

class TaxPolicyUpdateSchema(BaseModel):
    basic_rate: float
    sef_rate: float
    penalty_rate: float


@router.get("/system/tax-policy")
async def list_tax_policies(
    current_user: dict = Depends(read_only),
    db_session: Session = Depends(get_db),
):
    """Returns all configured tax policies ordered by tax year descending."""
    from backend.models import TaxPolicy
    rows = db_session.query(TaxPolicy).order_by(TaxPolicy.tax_year.desc()).all()
    return [{"id": r.id, "tax_year": r.tax_year, "basic_rate": float(r.basic_rate),
             "sef_rate": float(r.sef_rate), "penalty_rate": float(r.penalty_rate)} for r in rows]


@router.put("/system/tax-policy/{tax_year}")
async def update_tax_policy(
    tax_year: int,
    data: TaxPolicyUpdateSchema,
    current_user: dict = Depends(admin_only),
    db_session: Session = Depends(get_db),
):
    """Creates or updates the tax policy for a given tax year. Admin only."""
    from backend.models import TaxPolicy
    from decimal import Decimal

    for field, val in [("basic_rate", data.basic_rate), ("sef_rate", data.sef_rate),
                       ("penalty_rate", data.penalty_rate)]:
        if not (0 <= val <= 0.10):
            raise HTTPException(status_code=400, detail=f"{field} must be between 0 and 10%.")

    policy = db_session.query(TaxPolicy).filter(TaxPolicy.tax_year == tax_year).first()
    if policy:
        policy.basic_rate = Decimal(str(data.basic_rate))
        policy.sef_rate = Decimal(str(data.sef_rate))
        policy.penalty_rate = Decimal(str(data.penalty_rate))
    else:
        policy = TaxPolicy(tax_year=tax_year, basic_rate=Decimal(str(data.basic_rate)),
                           sef_rate=Decimal(str(data.sef_rate)), penalty_rate=Decimal(str(data.penalty_rate)))
        db_session.add(policy)

    db_session.commit()
    mto_logger.info(f"Tax policy updated for {tax_year}", user=current_user.get("username"))
    return {"status": "ok", "tax_year": tax_year}


# ---------------------------------------------------------------------------
# Billing AV Snapshot Repair
# ---------------------------------------------------------------------------

@router.post("/system/repair-billing-av", dependencies=[Depends(admin_only)])
async def repair_billing_assessed_values(
    dry_run: bool = True,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """Repairs stale PropertyBilling assessed_value snapshots after AV updates."""
    from backend.services.billing_service import repair_billing_assessed_value_snapshots
    from backend.services.system_service import log_action

    result = repair_billing_assessed_value_snapshots(
        dry_run=dry_run,
        db_session=db_session,
    )

    if dry_run:
        return result

    if result.get("rows_updated", 0):
        log_action(
            current_user,
            (
                "Billing AV snapshot repair: "
                f"{result.get('rows_updated', 0)} row(s) updated across "
                f"{result.get('properties_affected', 0)} property/properties."
            ),
            db_session=db_session,
        )
    db_session.commit()
    mto_logger.info(
        "Billing AV snapshot repair completed",
        user=current_user.get("username"),
        rows_updated=result.get("rows_updated", 0),
        properties_affected=result.get("properties_affected", 0),
    )
    return result


@router.post("/system/repair-payment-links", dependencies=[Depends(admin_only)])
async def repair_payment_billing_links(
    dry_run: bool = True,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """Repairs missing/stale payment-to-billing allocation links."""
    from backend.services.billing_service import repair_payment_billing_allocations
    from backend.services.system_service import log_action

    result = repair_payment_billing_allocations(
        dry_run=dry_run,
        db_session=db_session,
    )

    if dry_run:
        return result

    changed = (
        int(result.get("missing_links", 0) or 0)
        + int(result.get("stale_link_amounts", 0) or 0)
        + int(result.get("stale_billing_summaries", 0) or 0)
        + int(result.get("billing_rows_recalculated", 0) or 0)
    )
    if changed:
        log_action(
            current_user,
            (
                "Payment allocation repair: "
                f"{result.get('missing_links', 0)} missing link(s), "
                f"{result.get('stale_link_amounts', 0)} stale link amount(s), "
                f"{result.get('stale_billing_summaries', 0)} stale billing summary row(s), "
                f"{result.get('billing_rows_recalculated', 0)} billing row(s) recalculated across "
                f"{result.get('properties_affected', 0)} property/properties."
            ),
            db_session=db_session,
        )
    db_session.commit()
    mto_logger.info(
        "Payment allocation repair completed",
        user=current_user.get("username"),
        missing_links=result.get("missing_links", 0),
        stale_link_amounts=result.get("stale_link_amounts", 0),
        stale_billing_summaries=result.get("stale_billing_summaries", 0),
        billing_rows_recalculated=result.get("billing_rows_recalculated", 0),
        properties_affected=result.get("properties_affected", 0),
    )
    return result


# ---------------------------------------------------------------------------
# Billing Year Sync
# ---------------------------------------------------------------------------

@router.post("/system/sync-billing-years", dependencies=[Depends(admin_only)])
async def sync_billing_years(
    background_tasks: BackgroundTasks,
    dry_run: bool = False,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """Creates missing PropertyBilling records for all active properties."""
    from backend.services.billing_sync_service import sync_billing_years as _sync

    mto_logger.info(f"Billing year sync requested (dry_run={dry_run})",
                    user=current_user.get("username"))

    if dry_run:
        return _sync(db_session=db_session, dry_run=True)

    from backend.services.job_service import submit_job
    job_id = submit_job(job_type="sync_billing_years", submitted_by=current_user["username"],
                        payload={}, db_session=db_session)
    return {"job_id": job_id, "status": "queued",
            "message": "Billing year sync queued. Poll /jobs/{job_id} for progress."}
