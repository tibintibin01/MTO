import { NextRequest, NextResponse } from "next/server";
import { findOwnerMatches, findResult, loadPortalSnapshot, PortalSnapshotConfigError, PortalSnapshotDataError } from "../../../../../lib/portalSnapshot";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NAME_PATTERN = /^[A-Za-z0-9 .'\-ñÑ]{3,60}$/;
const BARANGAY_PATTERN = /^[A-Za-z0-9 .\-ñÑ]{1,60}$/;

function json(status: number, body: Record<string, any>) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const name = (searchParams.get("name") || "").trim();
  const barangay = (searchParams.get("barangay") || "").trim();

  if (!NAME_PATTERN.test(name)) {
    return json(400, { detail: "Please enter at least 3 valid characters of the owner's name." });
  }
  if (barangay && barangay.toUpperCase() !== "ALL" && !BARANGAY_PATTERN.test(barangay)) {
    return json(400, { detail: "Invalid barangay format." });
  }

  try {
    const snapshot = await loadPortalSnapshot();
    if (!snapshot) return json(503, { detail: "Portal data has not been published yet." });

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
    if (error instanceof PortalSnapshotConfigError || error instanceof PortalSnapshotDataError) {
      return json(503, { detail: "Portal data is temporarily unavailable. Please contact the Municipal Treasury Office." });
    }
    console.error("Portal owner lookup failed", error);
    return json(500, { detail: "Unable to search portal data." });
  }
}
