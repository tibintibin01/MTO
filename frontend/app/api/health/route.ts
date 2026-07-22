import { NextResponse } from "next/server";
import {
  portalSnapshotHealth,
  PortalSnapshotConfigError,
  PortalSnapshotDataError,
} from "../../../lib/portalSnapshot";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const health = await portalSnapshotHealth();
    return NextResponse.json(health, {
      status: health.ok ? 200 : 503,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const known = error instanceof PortalSnapshotConfigError || error instanceof PortalSnapshotDataError;
    if (!known) console.error("Portal readiness check failed", error);
    return NextResponse.json(
      {
        ok: false,
        status: known ? "unavailable" : "error",
        detail: "Portal snapshot is not ready.",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
