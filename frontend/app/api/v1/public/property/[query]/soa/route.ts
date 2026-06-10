import { NextRequest } from "next/server";
import { findSnapshotProperty, loadPortalSnapshot, publicProperty, PortalSnapshotConfigError } from "../../../../../../../lib/portalSnapshot";

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
  const rows = (data.billing_breakdown || []).map((row: any) => `
    <tr>
      <td>${escapeHtml(row.tax_year)}</td>
      <td class="num">${peso(row.assessed_value)}</td>
      <td class="num">${peso(row.basic)}</td>
      <td class="num">${peso(row.sef)}</td>
      <td class="num">${peso(row.penalty)}</td>
      <td class="num">${peso(row.discount)}</td>
      <td class="num">${peso(row.balance)}</td>
    </tr>`).join("");

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Statement of Account - ${escapeHtml(data.td_number)}</title>
  <style>
    body { font-family: Arial, sans-serif; color: #111827; margin: 36px; }
    .header { text-align: center; border-bottom: 2px solid #1f4e78; padding-bottom: 14px; margin-bottom: 24px; }
    .small { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: #526173; }
    h1 { margin: 8px 0 0; color: #1f4e78; font-size: 24px; }
    .box { border: 1px solid #d7dee8; padding: 16px; margin-bottom: 18px; }
    .grid { display: grid; grid-template-columns: 160px 1fr 160px 1fr; gap: 10px 14px; font-size: 13px; }
    .label { color: #607083; font-weight: 700; text-transform: uppercase; font-size: 11px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th { text-align: left; background: #1f4e78; color: white; padding: 9px; }
    td { border-bottom: 1px solid #e5e7eb; padding: 8px 9px; }
    .num { text-align: right; }
    .total { margin-top: 18px; text-align: right; font-size: 20px; font-weight: 800; color: #b91c1c; }
    .note { margin-top: 24px; color: #607083; font-size: 11px; line-height: 1.5; }
    @media print { body { margin: 18mm; } button { display: none; } }
  </style>
</head>
<body>
  <button onclick="window.print()" style="float:right;padding:8px 14px">Print</button>
  <div class="header">
    <div class="small">Republic of the Philippines</div>
    <div class="small">Municipality of Dipaculao, Province of Aurora</div>
    <h1>Statement of Account</h1>
    <div class="small">Municipal Treasury Office</div>
  </div>

  <div class="box grid">
    <div class="label">TD Number</div><div>${escapeHtml(data.td_number)}</div>
    <div class="label">As Of</div><div>${escapeHtml(data.as_of || "")}</div>
    <div class="label">Owner</div><div>${escapeHtml(data.owner_name)}</div>
    <div class="label">PIN</div><div>${escapeHtml(data.pin || "")}</div>
    <div class="label">Barangay</div><div>${escapeHtml(data.barangay || data.location || "")}</div>
    <div class="label">Classification</div><div>${escapeHtml(data.kind || "")}</div>
  </div>

  <table>
    <thead><tr><th>Year</th><th class="num">Assessed</th><th class="num">Basic</th><th class="num">SEF</th><th class="num">Penalty</th><th class="num">Discount</th><th class="num">Balance</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="7">No billing rows available.</td></tr>'}</tbody>
  </table>

  <div class="total">Outstanding Balance: ${peso(data.balance)}</div>
  <div class="note">This public statement is generated from the latest read-only snapshot published by the Municipal Treasury Office. For official payment, correction, or certification, please visit the office with your TD number and a valid ID.</div>
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
    if (error instanceof PortalSnapshotConfigError) {
      return new Response(error.message, { status: 503, headers: { "Cache-Control": "no-store" } });
    }
    console.error("Portal SOA generation failed", error);
    return new Response("Unable to generate statement.", { status: 500, headers: { "Cache-Control": "no-store" } });
  }
}