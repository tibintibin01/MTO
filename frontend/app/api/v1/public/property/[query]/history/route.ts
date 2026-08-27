import { NextRequest, NextResponse } from "next/server";
import { findSnapshotProperty, loadPortalSnapshot, publicPaymentHistory, PortalSnapshotAmbiguousLookupError, PortalSnapshotConfigError, PortalSnapshotDataError } from "../../../../../../../lib/portalSnapshot";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const QUERY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9\-./# ]{0,49}$/;
const ACCOUNT_KEY_PATTERN = /^[a-f0-9]{64}$/;

function json(status: number, body: any) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export async function GET(request: NextRequest, { params }: { params: { query: string } }) {
  const query = decodeURIComponent(params.query || "").trim();
  if (!QUERY_PATTERN.test(query)) return json(400, { detail: "Invalid query format." });
  const accountKey = (request.nextUrl.searchParams.get("account") || "").trim().toLowerCase();
  if (accountKey && !ACCOUNT_KEY_PATTERN.test(accountKey)) {
    return json(400, { detail: "Invalid property-account selection." });
  }

  try {
    const snapshot = await loadPortalSnapshot();
    if (!snapshot) return json(503, { detail: "Portal data has not been published yet." });

    const record = findSnapshotProperty(snapshot, query, accountKey || undefined);
    if (!record) return json(404, { detail: "Property not found." });

    return json(200, publicPaymentHistory(record));
  } catch (error) {
    if (error instanceof PortalSnapshotAmbiguousLookupError) {
      return json(409, {
        code: "MULTIPLE_PROPERTY_ACCOUNTS",
        detail: `${error.candidates.length} property accounts use this TDN or PIN. Select the correct property to continue.`,
        count: error.candidates.length,
        matches: error.candidates,
      });
    }
    if (error instanceof PortalSnapshotConfigError || error instanceof PortalSnapshotDataError) {
      return json(503, { detail: "Portal data is temporarily unavailable. Please contact the Municipal Treasury Office." });
    }
    console.error("Portal payment-history lookup failed", error);
    return json(500, { detail: "Unable to load portal data." });
  }
}
