import { NextResponse } from "next/server";
import { PORTAL_RELEASE, PUBLICATION_PROTOCOL, COMMIT_REVISION, MAX_COMPRESSED_BYTES, MAX_EXPANDED_BYTES } from "../../../lib/portalPublication";
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
    return NextResponse.json({ ...health, portal_release: PORTAL_RELEASE,
      publication_protocol: { name: PUBLICATION_PROTOCOL, commit_revision: COMMIT_REVISION, max_compressed_bytes: MAX_COMPRESSED_BYTES,
        max_expanded_bytes: MAX_EXPANDED_BYTES },
      deployment_commit: process.env.VERCEL_GIT_COMMIT_SHA || null }, {
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
