import os
import sys
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

# import db_manager as db # Unused in route
import backend.services.property_service as prop_svc
import backend.services.billing_service as bill_svc
import backend.services.payment_service as pay_svc

import backend.services.system_service as sys_svc
from backend.deps import get_current_user, write_access, admin_only, limiter, get_db, Session
from backend.schemas import PropertySaveSchema, BulkUpdateBarangaySchema
from utils.logger import mto_logger

router = APIRouter(prefix="/properties", tags=["Properties"])

@router.get("")
async def list_properties(
    search: str = "",
    limit: int = 50,
    cursor: Optional[int] = None,
    kind: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
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

@router.get("/{property_id}/history")
async def get_property_history(property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
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
            "date": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(r.created_at, "strftime") else str(r.created_at)
        }
        for r in rows
    ]

@router.get("/barangays")
async def list_barangays(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return prop_svc.get_barangays(db_session=db_session)

@router.get("/delinquent")
async def get_delinquent_accounts(
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    return bill_svc.get_delinquent_accounts(limit=limit, offset=offset, db_session=db_session)

@router.get("/deleted", dependencies=[Depends(admin_only)])
async def list_deleted_properties(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return prop_svc.get_deleted_properties(db_session=db_session)

@router.post("/{property_id}/restore", dependencies=[Depends(admin_only)])
async def restore_property(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    prop_svc.restore_property(property_id, current_user, db_session=db_session)
    return {"status": "restored"}

@router.post("/import-assessment")
@limiter.limit("5/minute")
async def import_assessment_roll(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(write_access),
):
    import shutil
    temp_path = f"temp_import_{datetime.now().timestamp()}.xlsx"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        import backend.services.import_service as import_svc
        summary = import_svc.import_assessment_roll_from_excel(temp_path, current_user)
        return summary
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Import Error: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@router.delete("/{property_id}/purge", dependencies=[Depends(admin_only)])
async def purge_property(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    prop_svc.purge_property(property_id, current_user, db_session=db_session)
    return {"status": "purged"}

@router.get("/unspecified")
async def get_unspecified_properties(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return prop_svc.get_unspecified_properties(db_session=db_session)

@router.get("/{property_id}")
async def get_property(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    prop = prop_svc.get_property_by_id(property_id, db_session=db_session)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop

@router.post("")
@limiter.limit("15/minute")
async def create_property(
    request: Request,
    data: PropertySaveSchema, 
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db)
):
    payload = data.dict(by_alias=True)
    if not payload.get("Tax Year") and payload.get("Effectivity Date"):
        eff_date = payload["Effectivity Date"]
        if len(str(eff_date)) >= 4:
            payload["Tax Year"] = str(eff_date)[:4]
        else:
            payload["Tax Year"] = str(datetime.now().year)
    elif not payload.get("Tax Year"):
        payload["Tax Year"] = str(datetime.now().year)

    res = prop_svc.save_property(payload, user=current_user, db_session=db_session)
    if not res:
        raise HTTPException(status_code=400, detail="Failed to create property")
    return res

@router.put("/{property_id}")
@limiter.limit("20/minute")
async def update_property(
    request: Request,
    property_id: int,
    data: PropertySaveSchema,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db)
):
    payload = data.model_dump(by_alias=True)
    if not payload.get("Tax Year") and payload.get("Effectivity Date"):
        eff_date = payload["Effectivity Date"]
        if len(str(eff_date)) >= 4:
            payload["Tax Year"] = str(eff_date)[:4]

    try:
        res = prop_svc.save_property(payload, editing_id=property_id, user=current_user, db_session=db_session)
        if not res:
            raise HTTPException(status_code=400, detail="Failed to update property")
        return res
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
async def delete_property(
    property_id: int, request: Request, current_user: dict = Depends(write_access), db_session: Session = Depends(get_db)
):
    ip = request.client.host
    res = prop_svc.soft_delete_property(property_id, user=current_user, ip_address=ip, db_session=db_session)
    if not res:
        raise HTTPException(status_code=400, detail="Failed to delete property")
    return {"status": "deleted"}

@router.post("/bulk-update-barangay")
async def bulk_update_barangay(data: BulkUpdateBarangaySchema, current_user: dict = Depends(write_access), db_session: Session = Depends(get_db)):
    ids = data.ids
    new_brgy = data.barangay
    count = prop_svc.bulk_update_barangay(ids, new_brgy, user=current_user, db_session=db_session)
    return {"updated": count}

@router.get("/dossier/{td_number}")
async def get_property_dossier(
    td_number: str, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    try:
        raw_prop = prop_svc.get_property_by_td(td_number, db_session=db_session)
        if not raw_prop:
            raise HTTPException(status_code=404, detail=f"Property {td_number} not found")
        
        # Convert ORM to dict if needed, but get_property_by_td should probably return dict or ORM
        # If it's ORM:
        if hasattr(raw_prop, "__table__"):
            prop = {c.name: getattr(raw_prop, c.name) for c in raw_prop.__table__.columns}
        else:
            prop = raw_prop

        def clean_data(obj):
            if obj is None: return None
            if isinstance(obj, dict):
                return {k: (float(v) if hasattr(v, "to_integral_value") else str(v) if hasattr(v, "strftime") else v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [(float(v) if hasattr(v, "to_integral_value") else str(v) if hasattr(v, "strftime") else v) for v in obj]
            return obj

        prop = clean_data(raw_prop)
        # Using the correct service import
        import backend.services.payment_service as payment_svc
        raw_payments = payment_svc.get_payment_ledger(td_number, db_session=db_session)
        payments = [clean_data(p) for p in raw_payments]

        ancestry = []
        prev_td = prop.get("prev_td_number")
        if prev_td and str(prev_td).strip() and str(prev_td).strip() != td_number:
            parent_prop = prop_svc.get_property_by_td(str(prev_td).strip(), db_session=db_session)
            if parent_prop:
                if hasattr(parent_prop, "__table__"):
                    ancestry.append(clean_data({c.name: getattr(parent_prop, c.name) for c in parent_prop.__table__.columns}))
                else:
                    ancestry.append(clean_data(parent_prop))

        from backend.models import AuditLog
        raw_logs = db_session.query(AuditLog).filter(
            AuditLog.table_name == "properties",
            AuditLog.record_id == prop.get("id")
        ).order_by(AuditLog.timestamp.desc()).limit(10).all()
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
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else ""
            }
            for log in raw_logs
        ]
        
        # Use ORM for history
        from backend.models import PropertyAssessmentHistory
        raw_history = db_session.query(PropertyAssessmentHistory).filter(PropertyAssessmentHistory.property_id == prop.get("id")).order_by(PropertyAssessmentHistory.created_at.desc()).all()
        history = [{"id": r.id, "td_number": r.td_number, "assessed_value": float(r.assessed_value or 0), "kind": r.kind_of_property, "tax_year": r.tax_year, "changed_by": r.changed_by, "date": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""} for r in raw_history]

        return {"master": prop, "payments": payments, "ancestry": ancestry, "audit_summary": logs, "assessment_history": history}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Dossier Error: {str(e)}")
