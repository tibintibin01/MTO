from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

import backend.services.property_service as prop_svc
import backend.services.billing_service as bill_svc
from backend.deps import get_current_user, write_access, admin_only, limiter, user_limiter, get_db, Session
from backend.schemas import PropertySaveSchema, BulkUpdateBarangaySchema
from utils.logger import mto_logger

router = APIRouter(prefix="/properties", tags=["Properties"])


@router.get("/duplicate-td-policy")
def duplicate_td_policy(current_user: dict = Depends(get_current_user)):
    """Expose rollout state without disclosing configuration secrets."""
    return {
        "enabled": prop_svc.verified_duplicate_td_feature_enabled(),
        "admin_authorized": str(current_user.get("role") or "").lower() == "admin",
        "requirements": [
            "Administrator role",
            "Assessor reference",
            "Reason",
            "Explicit TD confirmation",
        ],
    }

@router.get("")
def list_properties(
    search: str = "",
    limit: int = 50,
    cursor: Optional[int] = None,
    kind: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    as_of_year: Optional[int] = None,
    barangay: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    results = prop_svc.search_properties(
        search,
        limit=limit + 1,
        cursor=cursor,
        kind=kind,
        year_start=year_start,
        year_end=year_end,
        as_of_year=as_of_year,
        barangay=barangay,
        db_session=db_session
    )
    
    has_more = len(results) > limit
    items = results[:limit]
    next_cursor = items[-1][0] if has_more and items else None
    
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items)
    }

@router.get("/unspecified")
def get_unspecified_properties(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return prop_svc.get_unspecified_properties(db_session=db_session)

@router.get("/{property_id}/history")
def get_property_history(property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    from backend.models import PropertyAssessmentHistory
    
    rows = db_session.query(PropertyAssessmentHistory).filter(
        PropertyAssessmentHistory.property_id == property_id
    ).order_by(PropertyAssessmentHistory.created_at.desc()).all()
    
    return [
        {
            "id": r.id,
            "td_number": r.td_number,
            "assessed_value": float(r.assessed_value or 0),
            "kind": r.kind_of_property,
            "tax_year": r.tax_year,
            "changed_by": r.changed_by,
            "change_reason": r.change_reason,
            "date": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(r.created_at, "strftime") else str(r.created_at)
        }
        for r in rows
    ]

@router.get("/barangays")
def list_barangays(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return prop_svc.get_barangays(db_session=db_session)


@router.get("/payment-target")
def resolve_payment_target(
    td_number: str,
    tax_year: int,
    property_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    try:
        result = prop_svc.resolve_payment_target(
            td_number,
            tax_year,
            property_id=property_id,
            db_session=db_session,
        )
    except prop_svc.AmbiguousPropertyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "td_number": exc.td_number,
                "matches": [
                    {
                        "id": prop.id,
                        "td_number": prop.td_number,
                        "owner_name": prop.owner_name,
                        "pin": prop.pin,
                        "lot_number": prop.lot_number,
                        "barangay": prop.barangay or prop.location,
                        "kind_of_property": prop.kind_of_property,
                    }
                    for prop in exc.matches
                ],
            },
        )
    if not result:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No active TD in this chain is effective for tax year {tax_year}. "
                "Use the TD record active for that year, or add the missing Previous TD first."
            ),
        )
    return result

@router.get("/delinquent")
def get_delinquent_accounts(
    limit: int = 50,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return bill_svc.get_delinquent_accounts(limit=limit, cursor=cursor, db_session=db_session)

@router.get("/deleted", dependencies=[Depends(admin_only)])
def list_deleted_properties(
    limit: int = 50,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    return prop_svc.get_deleted_properties(limit=limit, cursor=cursor, db_session=db_session)

@router.post("/{property_id}/restore", dependencies=[Depends(admin_only)])
def restore_property(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    prop_svc.restore_property(property_id, current_user, db_session=db_session)
    return {"status": "restored"}

@router.delete("/{property_id}/purge", dependencies=[Depends(admin_only)])
def purge_property(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    prop_svc.purge_property(property_id, current_user, db_session=db_session)
    return {"status": "purged"}

@router.get("/{property_id}")
def get_property(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    prop = prop_svc.get_property_by_id(property_id, db_session=db_session)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop

@router.post("")
@limiter.limit("15/minute")
@user_limiter.limit("15/minute")
def create_property(
    request: Request,
    data: PropertySaveSchema, 
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db)
):
    payload = data.model_dump(by_alias=True, exclude_unset=True)
    if not payload.get("Tax Year") and payload.get("Effectivity Date"):
        eff_date = payload["Effectivity Date"]
        if len(str(eff_date)) >= 4:
            payload["Tax Year"] = str(eff_date)[:4]
        else:
            payload["Tax Year"] = str(datetime.now(timezone.utc).year)
    elif not payload.get("Tax Year"):
        payload["Tax Year"] = str(datetime.now(timezone.utc).year)

    res = prop_svc.save_property(payload, user=current_user, db_session=db_session)
    if not res:
        raise HTTPException(status_code=400, detail="Failed to create property")
    return res

@router.put("/{property_id}")
@limiter.limit("20/minute")
@user_limiter.limit("20/minute")
def update_property(
    request: Request,
    property_id: int,
    data: PropertySaveSchema,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db)
):
    payload = data.model_dump(by_alias=True, exclude_unset=True)
    if not payload.get("Tax Year") and payload.get("Effectivity Date"):
        eff_date = payload["Effectivity Date"]
        if len(str(eff_date)) >= 4:
            payload["Tax Year"] = str(eff_date)[:4]

    try:
        res = prop_svc.save_property(payload, editing_id=property_id, user=current_user, db_session=db_session)
        if not res:
            raise HTTPException(status_code=400, detail="Failed to update property")
        return res
    except HTTPException:
        raise
    except Exception as e:
        if getattr(e, "is_sync_conflict", False):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content=jsonable_encoder({
                    "detail": "This property was changed after you opened it. Please reload the record and try again.",
                    "server_data": getattr(e, "server_data", {}),
                    "client_data": payload
                })
            )
        error_type = f"{type(e).__module__}.{type(e).__name__}"
        mto_logger.error(f"Property Update Failed ({error_type}): {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error [{error_type}]: {str(e)}")

@router.delete("/{property_id}")
def delete_property(
    property_id: int, request: Request, current_user: dict = Depends(write_access), db_session: Session = Depends(get_db)
):
    ip = request.client.host
    res = prop_svc.soft_delete_property(property_id, user=current_user, ip_address=ip, db_session=db_session)
    if not res:
        raise HTTPException(status_code=400, detail="Failed to delete property")
    return {"status": "deleted", **res}

@router.post("/bulk-update-barangay")
def bulk_update_barangay(data: BulkUpdateBarangaySchema, current_user: dict = Depends(write_access), db_session: Session = Depends(get_db)):
    ids = data.ids
    new_brgy = data.barangay
    count = prop_svc.bulk_update_barangay(ids, new_brgy, user=current_user, db_session=db_session)
    return {"updated": count}

def _clean_dossier_data(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {
            key: (
                float(value)
                if hasattr(value, "to_integral_value")
                else str(value)
                if hasattr(value, "strftime")
                else value
            )
            for key, value in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [
            float(value)
            if hasattr(value, "to_integral_value")
            else str(value)
            if hasattr(value, "strftime")
            else value
            for value in obj
        ]
    return obj


def _build_property_dossier(raw_prop, db_session: Session):
    if hasattr(raw_prop, "__table__"):
        raw_prop = {
            column.name: getattr(raw_prop, column.name)
            for column in raw_prop.__table__.columns
        }
    prop = _clean_dossier_data(raw_prop)
    property_id = int(prop["id"])

    import backend.services.payment_service as payment_svc

    payments = [
        _clean_dossier_data(payment)
        for payment in payment_svc.get_payment_ledger(
            property_id, db_session=db_session
        )
    ]

    ancestry = []
    ancestry_ambiguous = []
    prev_td = str(prop.get("prev_td_number") or "").strip()
    if prev_td and prev_td.upper() != str(prop.get("td_number") or "").strip().upper():
        parent_matches = prop_svc.get_active_properties_by_td(
            prev_td, db_session=db_session
        )
        if len(parent_matches) == 1:
            parent = parent_matches[0]
            ancestry.append(
                _clean_dossier_data(
                    {
                        column.name: getattr(parent, column.name)
                        for column in parent.__table__.columns
                    }
                )
            )
        elif len(parent_matches) > 1:
            ancestry_ambiguous = [
                {
                    "id": parent.id,
                    "td_number": parent.td_number,
                    "owner_name": parent.owner_name,
                }
                for parent in parent_matches
            ]

    from backend.models import AuditLog, PropertyAssessmentHistory

    raw_logs = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.table_name == "properties",
            AuditLog.record_id == property_id,
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(10)
        .all()
    )
    logs = [
        {
            "id": log.id,
            "user_id": log.user_id,
            "username": log.username,
            "action": log.action,
            "table_name": log.table_name,
            "record_id": log.record_id,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "ip_address": log.ip_address,
            "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if log.timestamp
            else "",
        }
        for log in raw_logs
    ]
    raw_history = (
        db_session.query(PropertyAssessmentHistory)
        .filter(PropertyAssessmentHistory.property_id == property_id)
        .order_by(PropertyAssessmentHistory.created_at.desc())
        .all()
    )
    history = [
        {
            "id": row.id,
            "td_number": row.td_number,
            "assessed_value": float(row.assessed_value or 0),
            "kind": row.kind_of_property,
            "tax_year": row.tax_year,
            "changed_by": row.changed_by,
            "change_reason": row.change_reason,
            "date": row.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if row.created_at
            else "",
        }
        for row in raw_history
    ]
    return {
        "master": prop,
        "payments": payments,
        "ancestry": ancestry,
        "ancestry_ambiguous": ancestry_ambiguous,
        "audit_summary": logs,
        "assessment_history": history,
    }


@router.get("/dossier-by-id/{property_id}")
def get_property_dossier_by_id(
    property_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    prop = prop_svc.get_property_by_id(property_id, db_session=db_session)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return _build_property_dossier(prop, db_session)


@router.get("/dossier/{td_number}")
def get_property_dossier(
    td_number: str,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    try:
        prop = prop_svc.get_property_by_td(td_number, db_session=db_session)
    except prop_svc.AmbiguousPropertyError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(exc.matches)} properties use TD {exc.td_number}. "
                "Select a property row before opening its dossier."
            ),
        )
    if not prop:
        raise HTTPException(status_code=404, detail=f"Property {td_number} not found")
    return _build_property_dossier(prop, db_session)
