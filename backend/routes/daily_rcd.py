"""Admin-only daily RPT RCD preview, register and controlled Excel export."""

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.deps import admin_only, get_db
from backend.services.auth_service import get_username
from backend.services.system_service import log_action
from backend.services.rcd_register_service import (
    RcdRegisterUnavailable,
    read_register,
    register_officer,
    register_booklet,
    officer_dict,
    booklet_dict,
)
from backend.services.daily_rcd_service import (
    build_daily_rcd,
    RcdSnapshotChanged,
    validate_stock_history,
)
from backend.services.daily_rcd_excel import generate_daily_rcd_excel
from utils.rcd_remittance import build_remittance_review

router = APIRouter(prefix="/rcd", tags=["Daily RPT RCD"])


class OfficerInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class BookletInput(BaseModel):
    collector_id: int = Field(..., gt=0)
    first_or: str = Field(..., min_length=1, max_length=80)
    last_or: str = Field(..., min_length=1, max_length=80)
    issued_on: str = Field(..., min_length=10, max_length=10)


class ReviewedDailyExport(BaseModel):
    model_config = {"extra": "forbid"}
    collector_id: int = Field(..., gt=0)
    report_date: str = Field(..., min_length=10, max_length=10)
    report_number: str = Field(..., min_length=1, max_length=64)
    expected_signature: str = Field(..., min_length=64, max_length=64)
    review: dict


def _failure(db, error):
    db.rollback()
    if isinstance(error, RcdSnapshotChanged):
        raise HTTPException(409, str(error)) from error
    if isinstance(error, (RcdRegisterUnavailable, DBAPIError)) and not isinstance(
        error, IntegrityError
    ):
        detail = (
            str(error)
            if isinstance(error, RcdRegisterUnavailable)
            else "RCD data is unavailable. No schema or financial repair was attempted."
        )
        raise HTTPException(503, detail) from error
    if isinstance(error, IntegrityError):
        raise HTTPException(
            409,
            "The register entry conflicts with existing records. Reload and review it.",
        ) from error
    if isinstance(error, ValueError):
        raise HTTPException(422, str(error)) from error
    raise HTTPException(
        500, "RCD operation failed; no automatic repair was performed."
    ) from error


@router.get("/register")
def get_register(current_user=Depends(admin_only), db: Session = Depends(get_db)):
    try:
        return read_register(db)
    except Exception as error:
        _failure(db, error)


@router.post("/officers")
def add_officer(
    data: OfficerInput, current_user=Depends(admin_only), db: Session = Depends(get_db)
):
    try:
        item = register_officer(db, data.name, get_username(current_user))
        result = officer_dict(item)
        log_action(
            user=current_user,
            action="Registered RCD collecting officer: "
            + json.dumps(result, ensure_ascii=True),
            db_session=db,
        )
        db.commit()
        return result
    except Exception as error:
        _failure(db, error)


@router.post("/booklets")
def add_booklet(
    data: BookletInput, current_user=Depends(admin_only), db: Session = Depends(get_db)
):
    try:
        item = register_booklet(
            db,
            data.collector_id,
            data.first_or,
            data.last_or,
            data.issued_on,
            get_username(current_user),
        )
        result = booklet_dict(item)
        log_action(
            user=current_user,
            action="Registered immutable RCD booklet assignment: " + json.dumps(result),
            db_session=db,
        )
        db.commit()
        return result
    except Exception as error:
        _failure(db, error)


@router.get("/daily")
def get_daily(
    collector_id: int = Query(..., gt=0),
    report_date: str | None = None,
    current_user=Depends(admin_only),
    db: Session = Depends(get_db),
):
    try:
        return build_daily_rcd(db, collector_id, report_date)
    except Exception as error:
        _failure(db, error)


@router.get("/daily/excel")
def export_daily(
    collector_id: int = Query(..., gt=0),
    report_date: str = Query(...),
    report_number: str = Query(..., min_length=1, max_length=64),
    expected_signature: str = Query(..., min_length=64, max_length=64),
    current_user=Depends(admin_only),
    db: Session = Depends(get_db),
):
    try:
        payload = build_daily_rcd(
            db, collector_id, report_date, expected_signature=expected_signature
        )
        buffer = generate_daily_rcd_excel(payload, report_number)
        log_action(
            user=current_user,
            action=f"Exported daily RPT RCD 100/200: date={payload['report_date']} collector_id={collector_id} signature={payload['source_signature']}",
            db_session=db,
        )
        db.commit()
        filename = (
            f"RPT_RCD_100_200_{payload['report_date']}_collector_{collector_id}.xlsx"
        )
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as error:
        _failure(db, error)


@router.post("/daily/excel")
def export_reviewed_daily(
    data: ReviewedDailyExport,
    current_user=Depends(admin_only),
    db: Session = Depends(get_db),
):
    try:
        payload = build_daily_rcd(
            db,
            data.collector_id,
            data.report_date,
            expected_signature=data.expected_signature,
        )
        reviewed = build_remittance_review(payload, data.review)
        if reviewed["stock"] is not None:
            validate_stock_history(db, payload, reviewed["stock"])
        buffer = generate_daily_rcd_excel(
            payload, data.report_number, review=reviewed["details"]
        )
        log_action(
            user=current_user,
            action="Exported operator-reviewed daily RPT RCD (not receiver/bank acceptance): "
            + json.dumps(
                {
                    "collector_id": data.collector_id,
                    "report_date": payload["report_date"],
                    "report_number": data.report_number,
                    "source_signature": payload["source_signature"],
                    "review_signature": reviewed["review_signature"],
                    "declared_review": reviewed["details"],
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            db_session=db,
        )
        db.commit()
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="RPT_RCD_100_200_{payload["report_date"]}_collector_{data.collector_id}.xlsx"'
            },
        )
    except Exception as error:
        _failure(db, error)
