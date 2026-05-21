import os
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from backend.deps import get_current_user, write_access, read_only, get_db, Session
import backend.services.billing_service as bill_svc
import backend.services.property_service as prop_svc
import backend.services.system_service as sys_svc
import backend.services.payment_service as pay_svc
import backend.services.analytics_service as analytics
from backend.generators import soa_gen, computation_gen, notice_gen
from utils.logger import mto_logger
from backend.services.storage_service import storage_service

router = APIRouter(tags=["Billing"])


@router.get("/billing/summary")
async def get_billing_summary(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return sys_svc.get_dashboard_summary(db_session=db_session)

@router.get("/properties/{property_id}/statement")
async def get_property_statement(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    return bill_svc.get_property_statement_data(property_id, db_session=db_session)

@router.get("/billing/assessment-roll")
async def get_assessment_roll(
    limit: int = 100,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return prop_svc.get_assessment_roll(limit=limit, cursor=cursor, db_session=db_session)

@router.get("/billing/report-details")
async def get_report_details(
    month: str = "All",
    year: str = "All",
    limit: int = 200,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    return bill_svc.get_report_details(month, year, limit=limit, cursor=cursor, db_session=db_session)

@router.get("/billing/receivables-summary")
async def get_receivables_summary(
    year: str, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    return bill_svc.get_rpt_receivables_summary(year, db_session=db_session)

@router.get("/billing/delinquents")
async def get_delinquent_list(
    limit: int = 50,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return bill_svc.get_delinquent_accounts(limit=limit, cursor=cursor, db_session=db_session)


@router.get("/billing/compliant")
async def get_compliant_list(
    barangay: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """
    Returns properties with zero outstanding balance (fully paid across all years).
    Optionally filtered by barangay. Cursor-paginated.
    """
    return bill_svc.get_compliant_accounts(
        barangay=barangay, limit=limit, cursor=cursor, db_session=db_session
    )


@router.get("/billing/compliant/summary")
async def get_compliant_summary(
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """
    Returns per-barangay compliance summary:
    total properties, compliant count, delinquent count, compliance rate %.
    Used for the summary cards at the top of the Compliant Properties dashboard.
    """
    return bill_svc.get_compliant_summary_by_barangay(db_session=db_session)

@router.get("/reports/receivables-by-barangay")
async def get_receivables_by_barangay(
    year: Optional[int] = None,
    data_start_year: int = 2023,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return prop_svc.get_receivables_by_barangay(
        report_year=year,
        data_start_year=data_start_year,
        db_session=db_session,
    )

@router.get("/analytics/trends", tags=["Analytics"], dependencies=[Depends(read_only)])
async def get_analytics_trends(months: int = 12, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return pay_svc.get_monthly_collection_trend(months, db_session=db_session)

@router.get("/analytics/barangay-breakdown", tags=["Analytics"], dependencies=[Depends(read_only)])
async def get_barangay_breakdown(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return pay_svc.get_revenue_by_barangay(db_session=db_session)

@router.get("/analytics/kpis", tags=["Analytics"], dependencies=[Depends(read_only)])
async def get_analytics_kpis(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return pay_svc.get_collection_kpis(db_session=db_session)

@router.get("/api/analytics/dashboard")
async def get_analytics_dashboard(user: str = Depends(get_current_user), db_session: Session = Depends(get_db)):
    """Returns a comprehensive set of treasury analytics data."""
    return {
        "summary": analytics.get_collection_summary(db_session=db_session),
        "trend": analytics.get_monthly_revenue_trend(db_session=db_session),
        "barangays": analytics.get_barangay_distribution(db_session=db_session),
        "years": analytics.get_tax_year_distribution(db_session=db_session)
    }





@router.get("/properties/{property_id}/computation-pdf", tags=["Financial"])
async def generate_computation_pdf(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    try:
        details = bill_svc.get_property_statement_data(property_id, db_session=db_session)
        if not details:
            raise HTTPException(status_code=404, detail="Property billing data not found")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = await asyncio.to_thread(
            computation_gen.generate_delinquency_computation, details, base_dir
        )
        file_name = os.path.basename(pdf_path)

        if storage_service.enabled:
            s3_key = f"computations/{file_name}"
            uploaded_key = await asyncio.to_thread(storage_service.upload_file, pdf_path, s3_key)
            if uploaded_key:
                presigned_url = await asyncio.to_thread(storage_service.generate_presigned_url, s3_key)
                if presigned_url:
                    try:
                        os.remove(pdf_path)
                    except Exception as cleanup_err:
                        mto_logger.warning(f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}")
                    return RedirectResponse(presigned_url, status_code=307)

        return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        mto_logger.error(f"Failed to generate computation PDF for property {property_id} | Error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"PDF Generation Failed: {str(e)}")

@router.get("/properties/{property_id}/statement-pdf", tags=["Financial"])
async def generate_statement_pdf(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    try:
        details = bill_svc.get_property_statement_data(property_id, db_session=db_session)
        if not details:
            raise HTTPException(status_code=404, detail="Property billing data not found")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = await asyncio.to_thread(
            soa_gen.generate_statement_of_account, details, base_dir
        )
        file_name = os.path.basename(pdf_path)

        if storage_service.enabled:
            s3_key = f"statements/{file_name}"
            uploaded_key = await asyncio.to_thread(storage_service.upload_file, pdf_path, s3_key)
            if uploaded_key:
                presigned_url = await asyncio.to_thread(storage_service.generate_presigned_url, s3_key)
                if presigned_url:
                    try:
                        os.remove(pdf_path)
                    except Exception as cleanup_err:
                        mto_logger.warning(f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}")
                    return RedirectResponse(presigned_url, status_code=307)

        return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        mto_logger.error(f"Failed to generate SOA PDF for property {property_id} | Error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"PDF Generation Failed: {str(e)}")

class BulkSOARequest(BaseModel):
    property_ids: List[int] = Field(..., min_length=1, max_length=200)


@router.post("/billing/bulk-soa-pdf", tags=["Financial"])
async def generate_bulk_soa_pdf(
    data: BulkSOARequest,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    """
    Generates a single merged PDF containing Statement of Account pages
    for each requested property ID. Returns the file directly or a
    pre-signed S3 URL when cloud storage is enabled.
    """
    statements = []
    missing_ids = []

    for pid in data.property_ids:
        details = bill_svc.get_property_statement_data(pid, db_session=db_session)
        if details:
            statements.append(details)
        else:
            missing_ids.append(pid)

    if missing_ids:
        mto_logger.warning(
            f"Bulk SOA: {len(missing_ids)} property ID(s) not found — skipped",
            missing=missing_ids,
            user=current_user.get("username"),
        )

    if not statements:
        raise HTTPException(
            status_code=404,
            detail="No valid property billing data found for the provided IDs.",
        )

    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = await asyncio.to_thread(soa_gen.bulk_generate_soa, statements, base_dir)
        file_name = os.path.basename(pdf_path)

        mto_logger.info(
            f"Bulk SOA generated: {file_name} ({len(statements)} properties)",
            user=current_user.get("username"),
        )

        if storage_service.enabled:
            s3_key = f"statements/{file_name}"
            uploaded_key = await asyncio.to_thread(storage_service.upload_file, pdf_path, s3_key)
            if uploaded_key:
                presigned_url = await asyncio.to_thread(storage_service.generate_presigned_url, s3_key)
                if presigned_url:
                    try:
                        os.remove(pdf_path)
                    except Exception as cleanup_err:
                        mto_logger.warning(
                            f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}"
                        )
                    return RedirectResponse(presigned_url, status_code=307)

        return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)

    except Exception as e:
        import traceback
        mto_logger.error(
            f"Bulk SOA generation failed | Error: {str(e)}\n{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=500, detail=f"Bulk SOA PDF Generation Failed: {str(e)}"
        )


@router.get("/properties/{property_id}/notice-pdf", tags=["Financial"])
async def generate_notice_pdf(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    try:
        details = bill_svc.get_property_statement_data(property_id, db_session=db_session)
        if not details:
            raise HTTPException(status_code=404, detail="Property billing data not found")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = await asyncio.to_thread(
            notice_gen.generate_delinquency_notice, details, base_dir
        )
        file_name = os.path.basename(pdf_path)

        if storage_service.enabled:
            s3_key = f"notices/{file_name}"
            uploaded_key = await asyncio.to_thread(storage_service.upload_file, pdf_path, s3_key)
            if uploaded_key:
                presigned_url = await asyncio.to_thread(storage_service.generate_presigned_url, s3_key)
                if presigned_url:
                    try:
                        os.remove(pdf_path)
                    except Exception as cleanup_err:
                        mto_logger.warning(f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}")
                    return RedirectResponse(presigned_url, status_code=307)

        return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        mto_logger.error(f"Failed to generate Notice PDF for property {property_id} | Error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"PDF Generation Failed: {str(e)}")


@router.get("/analytics")
async def serve_analytics_dashboard():
    """
    Serves the analytics dashboard HTML from backend/static/analytics.html.
    No HTTP-level auth — the HTML page itself handles authentication by
    reading window.__MTO_TOKEN__ injected by the desktop WebView before load.
    If the token is missing or invalid, the page shows an UNAUTHORIZED message.
    """
    from fastapi.responses import FileResponse
    html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "analytics.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="Analytics dashboard file not found.")
    return FileResponse(html_path, media_type="text/html")
