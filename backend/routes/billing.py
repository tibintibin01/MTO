import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
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

class BillingBulkRequest(BaseModel):
    property_ids: List[int]
    filename_prefix: str = "Bulk_SOA"





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
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    # This service doesn't support db_session yet, but let's add it for consistency if we refactor it
    return prop_svc.get_assessment_roll(limit=limit, offset=offset)

@router.get("/billing/report-details")
async def get_report_details(
    month: str = "All",
    year: str = "All",
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    return bill_svc.get_report_details(month, year, db_session=db_session)

@router.get("/billing/receivables-summary")
async def get_receivables_summary(
    year: str, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    return bill_svc.get_rpt_receivables_summary(year, db_session=db_session)

@router.get("/billing/delinquents")
async def get_delinquent_list(
    limit: int = 100, offset: int = 0, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    return bill_svc.get_delinquent_accounts(limit, offset, db_session=db_session)

@router.get("/reports/receivables-by-barangay")
async def get_receivables_by_barangay(current_user: dict = Depends(get_current_user)):
    # This service doesn't support db_session yet
    return prop_svc.get_receivables_by_barangay()

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
async def get_analytics_dashboard(user: str = Depends(get_current_user)):
    """Returns a comprehensive set of treasury analytics data."""
    return {
        "summary": analytics.get_collection_summary(),
        "trend": analytics.get_monthly_revenue_trend(),
        "barangays": analytics.get_barangay_distribution(),
        "years": analytics.get_tax_year_distribution()
    }

@router.post("/billing/bulk-soa", dependencies=[Depends(write_access)])
async def generate_bulk_soa_pdf(
    request: BillingBulkRequest, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    """Generates a merged PDF of Statements of Account for multiple properties."""
    data_list = []
    for prop_id in request.property_ids:
        stmt_data = bill_svc.get_property_statement_data(prop_id, db_session=db_session)
        if stmt_data:
            data_list.append(stmt_data)

    if not data_list:
        raise HTTPException(status_code=400, detail="No valid property data found for bulk generation.")
    
    # ... logic for bulk PDF ...
    return {"status": "success", "message": "Bulk PDF generation logic here"}





    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import receipt_generator as old_rg
    pdf_path = old_rg.bulk_generate_soa(data_list, base_dir, filename_prefix=request.filename_prefix)
    
    return FileResponse(pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path))

@router.get("/properties/{property_id}/computation-pdf", tags=["Financial"])
async def generate_computation_pdf(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    try:
        details = bill_svc.get_property_statement_data(property_id, db_session=db_session)
        if not details:
            raise HTTPException(status_code=404, detail="Property billing data not found")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = computation_gen.generate_delinquency_computation(details, base_dir)
        file_name = os.path.basename(pdf_path)

        if storage_service.enabled:
            s3_key = f"computations/{file_name}"
            uploaded_key = storage_service.upload_file(pdf_path, s3_key)
            if uploaded_key:
                presigned_url = storage_service.generate_presigned_url(s3_key)
                if presigned_url:
                    try:
                        os.remove(pdf_path)
                    except Exception as cleanup_err:
                        mto_logger.warning(f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}")
                    return RedirectResponse(presigned_url, status_code=307)

        return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)
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
        pdf_path = soa_gen.generate_statement_of_account(details, base_dir)
        file_name = os.path.basename(pdf_path)

        if storage_service.enabled:
            s3_key = f"statements/{file_name}"
            uploaded_key = storage_service.upload_file(pdf_path, s3_key)
            if uploaded_key:
                presigned_url = storage_service.generate_presigned_url(s3_key)
                if presigned_url:
                    try:
                        os.remove(pdf_path)
                    except Exception as cleanup_err:
                        mto_logger.warning(f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}")
                    return RedirectResponse(presigned_url, status_code=307)

        return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)
    except Exception as e:
        import traceback
        mto_logger.error(f"Failed to generate SOA PDF for property {property_id} | Error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"PDF Generation Failed: {str(e)}")

@router.get("/properties/{property_id}/notice-pdf", tags=["Financial"])
async def generate_notice_pdf(
    property_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    try:
        details = bill_svc.get_property_statement_data(property_id, db_session=db_session)
        if not details:
            raise HTTPException(status_code=404, detail="Property billing data not found")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = notice_gen.generate_delinquency_notice(details, base_dir)
        file_name = os.path.basename(pdf_path)

        if storage_service.enabled:
            s3_key = f"notices/{file_name}"
            uploaded_key = storage_service.upload_file(pdf_path, s3_key)
            if uploaded_key:
                presigned_url = storage_service.generate_presigned_url(s3_key)
                if presigned_url:
                    try:
                        os.remove(pdf_path)
                    except Exception as cleanup_err:
                        mto_logger.warning(f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}")
                    return RedirectResponse(presigned_url, status_code=307)

        return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)
    except Exception as e:
        import traceback
        mto_logger.error(f"Failed to generate Notice PDF for property {property_id} | Error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"PDF Generation Failed: {str(e)}")


@router.get("/analytics", response_class=HTMLResponse)
async def serve_analytics_dashboard():
    """Serves a premium, web-based analytics dashboard using Apache ECharts."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MTO Treasury Insights</title>
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-color: #f8fafc;
                --card-bg: #ffffff;
                --text-primary: #1e293b;
                --text-secondary: #64748b;
                --accent: #38bdf8;
                --emerald: #10b981;
                --border: #e2e8f0;
            }
            [data-theme='dark'] {
                --bg-color: #0f172a;
                --card-bg: #1e293b;
                --text-primary: #f1f5f9;
                --text-secondary: #94a3b8;
                --accent: #38bdf8;
                --border: #334155;
            }
            body { 
                margin: 0; padding: 20px; 
                background: var(--bg-color); 
                color: var(--text-primary);
                font-family: 'Inter', sans-serif;
                transition: background 0.3s, color 0.3s;
            }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; }
            .card { 
                background: var(--card-bg); 
                border-radius: 12px; padding: 24px; 
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                border: 1px solid var(--border);
                transition: transform 0.2s;
                animation: fadeInUp 0.6s ease-out forwards;
                opacity: 0;
            }
            .card:hover { transform: translateY(-4px); }
            @keyframes fadeInUp {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }
            .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
            .stat-card { background: var(--card-bg); padding: 20px; border-radius: 12px; border: 1px solid var(--border); border-left: 4px solid var(--accent); }
            .stat-val { font-size: 1.8rem; font-weight: 600; color: var(--accent); margin-top: 5px; }
            .stat-label { font-size: 0.85rem; color: var(--text-secondary); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
            .chart-container { height: 350px; width: 100%; margin-top: 10px; }
            h2 { margin: 0; font-weight: 600; font-size: 1.1rem; color: var(--text-primary); }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🏛️ Treasury Insights Portal</h1>
            <div id="last-update" style="opacity: 0.5; font-size: 0.9rem;"></div>
        </div>

        <div class="stat-grid">
            <div class="stat-card"><div class="stat-label">Today's Collection</div><div id="stat-today" class="stat-val">₱0.00</div></div>
            <div class="stat-card" style="border-left-color: var(--emerald);"><div class="stat-label">Transactions Today</div><div id="stat-count" class="stat-val">0</div></div>
            <div class="stat-card"><div class="stat-label">Monthly Velocity</div><div id="stat-month" class="stat-val">₱0.00</div></div>
            <div class="stat-card"><div class="stat-label">Annual Revenue</div><div id="stat-year" class="stat-val">₱0.00</div></div>
        </div>

        <div class="grid">
            <div class="card"><h2>Revenue Velocity (Last 12 Months)</h2><div id="trend-chart" class="chart-container"></div></div>
            <div class="card"><h2>Top Barangay Collections</h2><div id="barangay-chart" class="chart-container"></div></div>
            <div class="card"><h2>Tax Year Distribution</h2><div id="year-chart" class="chart-container"></div></div>
        </div>

        <script>
            async function fetchData() {
                // SECURITY FIX (#12): Do NOT read JWT from URL params (?t=...).
                // The desktop WebView injects window.__MTO_TOKEN__ before page load.
                // This keeps the token out of browser history, logs, and referrer headers.
                const token = window.__MTO_TOKEN__ || null;
                const theme = new URLSearchParams(window.location.search).get('theme') || 'dark';

                document.documentElement.setAttribute('data-theme', theme);

                const headers = {
                    "X-Requested-With": "XMLHttpRequest"
                };
                if (token) {
                    headers["Authorization"] = "Bearer " + token;
                }

                const res = await fetch('/api/analytics/dashboard', { headers: headers });

                if (res.status === 401) {
                    document.body.innerHTML = '<div style="display:flex; height:100vh; align-items:center; justify-content:center; color:white;"><h1>🚫 UNAUTHORIZED: Please launch from the Treasury Desktop App.</h1></div>';
                    return;
                }

                const data = await res.json();
                
                document.getElementById('last-update').innerText = 'System Pulse: ' + new Date().toLocaleTimeString();
                document.getElementById('stat-today').innerText = '₱' + data.summary.today.toLocaleString();
                document.getElementById('stat-count').innerText = data.summary.count;
                document.getElementById('stat-month').innerText = '₱' + data.summary.month.toLocaleString();
                document.getElementById('stat-year').innerText = '₱' + data.summary.year.toLocaleString();

                renderTrendChart(data.trend);
                renderBarangayChart(data.barangays);
                renderYearChart(data.years);
            }

            function renderTrendChart(trend) {
                const theme = document.documentElement.getAttribute('data-theme');
                const chart = echarts.init(document.getElementById('trend-chart'), theme === 'dark' ? 'dark' : null);
                chart.setOption({
                    backgroundColor: 'transparent',
                    tooltip: { trigger: 'axis' },
                    xAxis: { type: 'category', data: trend.map(d => d.month), axisLine: { show: false } },
                    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
                    series: [{
                        data: trend.map(d => d.total),
                        type: 'line',
                        smooth: true,
                        lineStyle: { width: 4, color: '#38bdf8' },
                        areaStyle: {
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                { offset: 0, color: 'rgba(56, 189, 248, 0.4)' },
                                { offset: 1, color: 'rgba(56, 189, 248, 0)' }
                            ])
                        },
                        symbol: 'none'
                    }]
                });
            }

            function renderBarangayChart(data) {
                const theme = document.documentElement.getAttribute('data-theme');
                const chart = echarts.init(document.getElementById('barangay-chart'), theme === 'dark' ? 'dark' : null);
                chart.setOption({
                    backgroundColor: 'transparent',
                    tooltip: { trigger: 'item' },
                    series: [{
                        type: 'pie',
                        radius: ['40%', '70%'],
                        avoidLabelOverlap: false,
                        itemStyle: { borderRadius: 10, borderColor: '#1e293b', borderWidth: 2 },
                        label: { show: false },
                        emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
                        data: data
                    }]
                });
            }

            function renderYearChart(data) {
                const theme = document.documentElement.getAttribute('data-theme');
                const chart = echarts.init(document.getElementById('year-chart'), theme === 'dark' ? 'dark' : null);
                chart.setOption({
                    backgroundColor: 'transparent',
                    tooltip: { trigger: 'axis' },
                    xAxis: { type: 'value', splitLine: { show: false } },
                    yAxis: { type: 'category', data: data.map(d => d.year) },
                    series: [{
                        type: 'bar',
                        data: data.map(d => d.total),
                        itemStyle: {
                            color: new echarts.graphic.LinearGradient(1, 0, 0, 0, [
                                { offset: 0, color: '#10b981' },
                                { offset: 1, color: '#38bdf8' }
                            ]),
                            borderRadius: [0, 5, 5, 0]
                        }
                    }]
                });
            }

            fetchData();
            setInterval(fetchData, 60000);
            window.addEventListener('resize', () => {
                echarts.getInstanceByDom(document.getElementById('trend-chart')).resize();
                echarts.getInstanceByDom(document.getElementById('barangay-chart')).resize();
                echarts.getInstanceByDom(document.getElementById('year-chart')).resize();
            });
        </script>
    </body>
    </html>
    """
