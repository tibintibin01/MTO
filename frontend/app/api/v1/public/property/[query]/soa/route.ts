import { NextRequest } from "next/server";
import { findSnapshotProperty, loadPortalSnapshot, publicProperty, PortalSnapshotConfigError, PortalSnapshotDataError } from "../../../../../../../lib/portalSnapshot";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const QUERY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9\-./# ]{0,49}$/;

function escapeHtml(value: any): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function peso(value: number): string {
  return `PHP ${(Number(value) || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function html(data: any): string {
  const outstanding = Number(data.balance || 0);
  const isClear = outstanding <= 0.005;
  const statusLabel = isClear ? "ACCOUNT UPDATED" : "PAYMENT REQUIRED";
  const statusClass = isClear ? "clear" : "due";
  const reference = `SOA-${String(data.td_number || "").replace(/[^A-Za-z0-9]/g, "")}-${String(data.as_of || "").replaceAll("-", "")}`;
  const rows = (data.billing_breakdown || []).map((row: any) => `
    <tr>
      <td class="year">${escapeHtml(row.tax_year)}</td>
      <td class="num">${peso(row.assessed_value)}</td>
      <td class="num">${peso(row.basic)}</td>
      <td class="num">${peso(row.sef)}</td>
      <td class="num">${peso(row.penalty)}</td>
      <td class="num">${peso(row.discount)}</td>
      <td class="num paid">${peso(row.amount_paid)}</td>
      <td class="num balance ${Number(row.balance || 0) <= 0.005 ? "settled" : "open"}">${peso(row.balance)}</td>
    </tr>`).join("");

  const futureAssessment = data.future_assessment ? `
    <div class="future-note">
      <div>
        <span class="future-label">Future assessment on record</span>
        <strong>${peso(data.future_assessment.assessed_value)}</strong>
      </div>
      <span>Effective ${escapeHtml(data.future_assessment.effective_year)}</span>
    </div>` : "";

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Statement of Account - ${escapeHtml(data.td_number)}</title>
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #edf1f5; color: #172033; font-family: Arial, Helvetica, sans-serif; }
    .toolbar { max-width: 980px; margin: 20px auto 10px; display: flex; justify-content: flex-end; }
    .print-btn { border: 0; border-radius: 6px; background: #174d78; color: #fff; padding: 10px 18px; font-size: 13px; font-weight: 700; cursor: pointer; }
    .print-btn:hover { background: #123d61; }
    .sheet { width: min(980px, calc(100% - 32px)); min-height: 900px; margin: 0 auto 28px; background: #fff; border: 1px solid #d5dde7; box-shadow: 0 12px 30px rgba(15, 35, 60, .10); padding: 34px 38px 28px; }
    .masthead { display: grid; grid-template-columns: 88px 1fr 180px; align-items: center; gap: 20px; padding-bottom: 22px; border-bottom: 3px solid #174d78; }
    .seal { width: 74px; height: 74px; object-fit: contain; }
    .agency { text-align: center; }
    .republic { color: #5a6b7e; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; }
    .municipality { margin-top: 5px; color: #173f67; font-family: Georgia, 'Times New Roman', serif; font-size: 20px; font-weight: 700; }
    .office { margin-top: 3px; color: #536579; font-size: 11px; font-weight: 700; letter-spacing: 1.1px; text-transform: uppercase; }
    .doc-meta { text-align: right; font-size: 10px; line-height: 1.6; color: #65768a; }
    .doc-meta strong { display: block; color: #233b55; font-size: 11px; }
    .title-row { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin: 24px 0 18px; }
    h1 { margin: 0; color: #173f67; font-family: Georgia, 'Times New Roman', serif; font-size: 27px; line-height: 1.1; }
    .subtitle { margin-top: 5px; color: #6a798b; font-size: 11px; }
    .status { border-radius: 999px; padding: 8px 13px; font-size: 10px; font-weight: 800; letter-spacing: .7px; white-space: nowrap; }
    .status.clear { background: #e8f6ee; border: 1px solid #9dd7b5; color: #17643b; }
    .status.due { background: #fff0ec; border: 1px solid #efb1a0; color: #a3311e; }
    .identity { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid #d7e0ea; border-radius: 6px; overflow: hidden; margin-bottom: 16px; }
    .field { min-height: 64px; padding: 13px 15px; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; }
    .field:nth-child(3n) { border-right: 0; }
    .field:nth-last-child(-n+3) { border-bottom: 0; }
    .label { color: #708095; font-size: 9px; font-weight: 800; letter-spacing: .7px; text-transform: uppercase; }
    .value { margin-top: 6px; color: #17283b; font-size: 12px; font-weight: 700; line-height: 1.3; overflow-wrap: anywhere; }
    .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 16px 0 20px; }
    .metric { border: 1px solid #d9e2ec; border-top: 3px solid #7e91a6; border-radius: 5px; padding: 13px 15px; }
    .metric.paid { border-top-color: #248754; }
    .metric.outstanding.clear { border-top-color: #248754; background: #f7fcf9; }
    .metric.outstanding.due { border-top-color: #c44932; background: #fff9f7; }
    .metric-label { color: #718197; font-size: 9px; font-weight: 800; letter-spacing: .65px; text-transform: uppercase; }
    .metric-value { margin-top: 6px; color: #173f67; font-size: 18px; font-weight: 800; }
    .outstanding.clear .metric-value { color: #17643b; }
    .outstanding.due .metric-value { color: #a3311e; }
    .section-title { display: flex; justify-content: space-between; align-items: center; margin: 22px 0 9px; color: #263d56; font-size: 11px; font-weight: 800; letter-spacing: .65px; text-transform: uppercase; }
    .section-title span { color: #7b8999; font-size: 9px; font-weight: 600; letter-spacing: 0; text-transform: none; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 10px; }
    th { background: #174d78; color: #fff; padding: 9px 7px; text-align: right; font-size: 9px; letter-spacing: .2px; }
    th:first-child { width: 54px; text-align: left; }
    td { border-bottom: 1px solid #dfe6ee; padding: 9px 7px; text-align: right; white-space: nowrap; }
    tbody tr:nth-child(even) { background: #f7f9fb; }
    td.year { text-align: left; font-weight: 800; color: #264b6d; }
    td.paid { color: #17643b; }
    td.balance { font-weight: 800; }
    td.balance.settled { color: #17643b; }
    td.balance.open { color: #a3311e; }
    .future-note { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 14px; border-left: 3px solid #d49b25; background: #fffaf0; padding: 11px 14px; color: #5e4a1b; font-size: 11px; }
    .future-note div { display: flex; align-items: center; gap: 10px; }
    .future-label { font-size: 9px; font-weight: 800; letter-spacing: .55px; text-transform: uppercase; }
    .certification { margin-top: 28px; padding-top: 14px; border-top: 1px solid #ced8e3; display: grid; grid-template-columns: 1fr 230px; gap: 32px; color: #64758a; font-size: 9px; line-height: 1.55; }
    .verification { text-align: center; color: #40556d; }
    .signature-line { height: 24px; border-bottom: 1px solid #8797a8; margin-bottom: 5px; }
    .footer { display: flex; justify-content: space-between; margin-top: 22px; color: #7b8999; font-size: 8px; letter-spacing: .2px; }
    @page { size: A4 portrait; margin: 12mm; }
    @media (max-width: 760px) {
      .sheet { width: calc(100% - 16px); padding: 22px 18px; }
      .toolbar { width: calc(100% - 16px); margin: 10px 8px; }
      .print-btn { padding: 9px 13px; }
      .masthead { grid-template-columns: 58px minmax(0, 1fr); gap: 12px; }
      .seal { width: 58px; height: 58px; }
      .agency { min-width: 0; text-align: left; }
      .republic { font-size: 8px; letter-spacing: 1px; }
      .municipality { font-size: 17px; line-height: 1.1; }
      .office { font-size: 8px; letter-spacing: .45px; line-height: 1.35; }
      .doc-meta { grid-column: 1 / -1; display: grid; grid-template-columns: 1fr; gap: 2px; text-align: left; }
      .doc-meta strong { overflow-wrap: anywhere; }
      .title-row { align-items: flex-start; flex-direction: column; }
      h1 { font-size: 25px; }
      .identity { grid-template-columns: 1fr; }
      .field, .field:nth-child(3n), .field:nth-last-child(-n+3) { border-right: 0; border-bottom: 1px solid #e2e8f0; }
      .field:last-child { border-bottom: 0; }
      .summary { grid-template-columns: 1fr; }
      .section-title { align-items: flex-start; flex-direction: column; gap: 4px; }
      .table-wrap { overflow-x: auto; }
      table { min-width: 720px; }
      .future-note { align-items: flex-start; flex-direction: column; gap: 7px; }
      .future-note div { align-items: flex-start; flex-direction: column; gap: 4px; }
      .certification { grid-template-columns: 1fr; }
      .footer { align-items: flex-start; flex-direction: column; gap: 4px; }
    }
    @media print {
      body { background: #fff; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      .toolbar { display: none; }
      .sheet { width: 100%; min-height: 0; margin: 0; padding: 0; border: 0; box-shadow: none; }
      .masthead { padding-top: 0; }
      .identity, .summary, table, .future-note { break-inside: avoid; }
      .certification { margin-top: 22px; }
    }
  </style>
</head>
<body>
  <div class="toolbar"><button class="print-btn" onclick="window.print()">Print Statement</button></div>
  <main class="sheet">
    <header class="masthead">
      <img class="seal" src="/dipaculao-seal.png" alt="Municipality of Dipaculao seal" />
      <div class="agency">
        <div class="republic">Republic of the Philippines</div>
        <div class="municipality">Municipality of Dipaculao</div>
        <div class="office">Municipal Treasury Office · Province of Aurora</div>
      </div>
      <div class="doc-meta">
        <span>Document reference</span>
        <strong>${escapeHtml(reference)}</strong>
        <span>Statement date: ${escapeHtml(data.as_of || "")}</span>
      </div>
    </header>

    <div class="title-row">
      <div>
        <h1>Statement of Account</h1>
        <div class="subtitle">Real Property Tax account summary from the latest published municipal record</div>
      </div>
      <div class="status ${statusClass}">${statusLabel}</div>
    </div>

    <section class="identity">
      <div class="field"><div class="label">Tax Declaration Number</div><div class="value">${escapeHtml(data.td_number)}</div></div>
      <div class="field"><div class="label">Registered Owner</div><div class="value">${escapeHtml(data.owner_name)}</div></div>
      <div class="field"><div class="label">PIN</div><div class="value">${escapeHtml(data.pin || "Not available")}</div></div>
      <div class="field"><div class="label">Barangay / Location</div><div class="value">${escapeHtml(data.barangay || data.location || "Not available")}</div></div>
      <div class="field"><div class="label">Classification</div><div class="value">${escapeHtml(data.kind || "Not available")}</div></div>
      <div class="field"><div class="label">Effective Assessed Value</div><div class="value">${peso(data.assessed_value)}</div></div>
    </section>

    <section class="summary">
      <div class="metric"><div class="metric-label">Total Billed</div><div class="metric-value">${peso(data.total_due)}</div></div>
      <div class="metric paid"><div class="metric-label">Total Paid</div><div class="metric-value">${peso(data.total_paid)}</div></div>
      <div class="metric outstanding ${statusClass}"><div class="metric-label">Outstanding Balance</div><div class="metric-value">${peso(outstanding)}</div></div>
    </section>

    <div class="section-title">Billing Detail <span>Basic Tax + SEF + Penalty − Discount − Payment = Balance</span></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Year</th><th>Assessed</th><th>Basic</th><th>SEF</th><th>Penalty</th><th>Discount</th><th>Paid</th><th>Balance</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="8" style="text-align:center;padding:24px;color:#718197">No billing rows available.</td></tr>'}</tbody>
      </table>
    </div>

    ${futureAssessment}

    <section class="certification">
      <div>
        This public statement is generated from the latest read-only snapshot published by the Municipal Treasury Office. It is intended for account inquiry and does not replace an official tax clearance, certified assessment, or original receipt. For corrections or certification, present your TD number and valid identification at the Municipal Treasury Office.
      </div>
      <div class="verification">
        <div class="signature-line"></div>
        Municipal Treasury Office Verification
      </div>
    </section>

    <footer class="footer">
      <span>Municipality of Dipaculao · Municipal Treasury Office</span>
      <span>${escapeHtml(reference)}</span>
    </footer>
  </main>
</body>
</html>`;
}

export async function GET(_request: NextRequest, { params }: { params: { query: string } }) {
  const query = decodeURIComponent(params.query || "").trim();
  if (!QUERY_PATTERN.test(query)) {
    return new Response("Invalid query format.", { status: 400, headers: { "Cache-Control": "no-store" } });
  }

  try {
    const snapshot = await loadPortalSnapshot();
    if (!snapshot) return new Response("Portal data has not been published yet.", { status: 503, headers: { "Cache-Control": "no-store" } });

    const record = findSnapshotProperty(snapshot, query);
    if (!record) return new Response("Property not found.", { status: 404, headers: { "Cache-Control": "no-store" } });

    return new Response(html(publicProperty(record, snapshot)), {
      status: 200,
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    if (error instanceof PortalSnapshotConfigError || error instanceof PortalSnapshotDataError) {
      return new Response("Portal data is temporarily unavailable. Please contact the Municipal Treasury Office.", { status: 503, headers: { "Cache-Control": "no-store" } });
    }
    console.error("Portal SOA generation failed", error);
    return new Response("Unable to generate statement.", { status: 500, headers: { "Cache-Control": "no-store" } });
  }
}
