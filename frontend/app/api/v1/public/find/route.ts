import { NextRequest, NextResponse } from "next/server";
import { findOwnerMatches, findResult, loadCurrentPortalSnapshot, PortalSnapshotConfigError, PortalSnapshotDataError, PortalSnapshotStaleError, snapshotUnavailablePayload } from "../../../../../lib/portalSnapshot";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NAME_PATTERN = /^[\p{L}\p{N} .'\-]{3,60}$/u;
const BARANGAY_PATTERN = /^[\p{L}\p{N} .\-]{1,60}$/u;

function json(status: number, body: Record<string, any>) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const name = (searchParams.get("name") || "").trim().normalize("NFKC");
  const barangay = (searchParams.get("barangay") || "").trim().normalize("NFKC");

  if (!NAME_PATTERN.test(name)) {
    return json(400, { detail: "Please enter at least 3 valid characters of the owner's name." });
  }
  if (barangay && barangay.toUpperCase() !== "ALL" && !BARANGAY_PATTERN.test(barangay)) {
    return json(400, { detail: "Invalid barangay format." });
  }

  try {
    const snapshot = await loadCurrentPortalSnapshot();
    if (!snapshot) return json(503, { detail: "Portal data has not been published yet." });
    if (/[^\x00-\x7f]/.test(name) && snapshot.owner_lookup_version !== 2) {
      return json(503, {detail:"The owner-name search index is awaiting an update. Please contact the Municipal Treasury Office for assistance."});
    }

    const matches = findOwnerMatches(snapshot, name, barangay);
    if (matches.length > 10) {
      return json(200, {
        results: [],
        too_many: true,
        message: "Too many matches. Add your barangay or more of your name.",
      });
    }

    return json(200, {
      results: matches.map((record) => findResult(record, snapshot)),
      too_many: false,
      count: matches.length,
    });
  } catch (error) {
    if (error instanceof PortalSnapshotStaleError) return json(503, snapshotUnavailablePayload(error));
    if (error instanceof PortalSnapshotConfigError || error instanceof PortalSnapshotDataError) {
      return json(503, { detail: "Portal data is temporarily unavailable. Please contact the Municipal Treasury Office." });
    }
    console.error("Portal owner lookup failed", error);
    return json(500, { detail: "Unable to search portal data." });
  }
}
