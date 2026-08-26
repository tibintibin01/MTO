import { NextRequest, NextResponse } from "next/server";
import { findSnapshotProperty, loadPortalSnapshot, publicProperty, PortalSnapshotAmbiguousLookupError, PortalSnapshotConfigError, PortalSnapshotDataError } from "../../../../../../lib/portalSnapshot";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const QUERY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9\-./# ]{0,49}$/;

function json(status: number, body: Record<string, any>) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export async function GET(_request: NextRequest, { params }: { params: { query: string } }) {
  const query = decodeURIComponent(params.query || "").trim();
  if (!QUERY_PATTERN.test(query)) {
    return json(400, { detail: "Invalid query format. Use your TDN or PIN." });
  }

  try {
    const snapshot = await loadPortalSnapshot();
    if (!snapshot) return json(503, { detail: "Portal data has not been published yet." });

    const record = findSnapshotProperty(snapshot, query);
    if (!record) return json(404, { detail: "Property not found." });

    return json(200, publicProperty(record, snapshot));
  } catch (error) {
    if (error instanceof PortalSnapshotAmbiguousLookupError) {
      return json(409, { detail: "More than one property account matches this TDN or PIN. Please contact the Municipal Treasury Office." });
    }
    if (error instanceof PortalSnapshotConfigError || error instanceof PortalSnapshotDataError) {
      return json(503, { detail: "Portal data is temporarily unavailable. Please contact the Municipal Treasury Office." });
    }
    console.error("Portal property lookup failed", error);
    return json(500, { detail: "Unable to load portal data." });
  }
}
