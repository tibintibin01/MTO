import { NextRequest, NextResponse } from "next/server";
import { createHash, timingSafeEqual } from "crypto";
import { gunzipSync } from "zlib";
import { storePortalSnapshot } from "../../../../lib/portalSnapshot";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_DECOMPRESSED_BYTES = 60 * 1024 * 1024;

function json(status: number, body: Record<string, any>) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

function safeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

function bearerToken(request: NextRequest): string {
  const header = request.headers.get("authorization") || "";
  return header.startsWith("Bearer ") ? header.slice(7).trim() : "";
}

export async function POST(request: NextRequest) {
  const configuredToken = process.env.MTO_PORTAL_PUBLISH_TOKEN?.trim();
  if (!configuredToken) {
    return json(503, { ok: false, detail: "MTO_PORTAL_PUBLISH_TOKEN is not configured on the portal." });
  }
  if (!safeEqual(bearerToken(request), configuredToken)) {
    return json(401, { ok: false, detail: "Unauthorized." });
  }

  const compressedPayload = Buffer.from(await request.arrayBuffer());
  const expectedPayloadHash = request.headers.get("x-mto-payload-sha256")?.trim().toLowerCase();
  const actualPayloadHash = createHash("sha256").update(compressedPayload).digest("hex");
  if (expectedPayloadHash && expectedPayloadHash !== actualPayloadHash) {
    return json(400, { ok: false, detail: "Payload checksum mismatch." });
  }

  const encoding = request.headers.get("content-encoding") || "";
  const payload = encoding.toLowerCase().includes("gzip")
    ? gunzipSync(compressedPayload)
    : compressedPayload;

  if (payload.byteLength > MAX_DECOMPRESSED_BYTES) {
    return json(413, { ok: false, detail: "Snapshot is too large." });
  }

  let snapshot: any;
  try {
    snapshot = JSON.parse(payload.toString("utf8"));
  } catch {
    return json(400, { ok: false, detail: "Invalid JSON snapshot." });
  }

  if (!snapshot || !Array.isArray(snapshot.properties)) {
    return json(400, { ok: false, detail: "Snapshot must include a properties array." });
  }
  if (snapshot.record_count !== snapshot.properties.length) {
    return json(400, { ok: false, detail: "record_count does not match properties length." });
  }

  const expectedRecords = Number(request.headers.get("x-mto-snapshot-records") || snapshot.record_count);
  if (Number.isFinite(expectedRecords) && expectedRecords !== snapshot.properties.length) {
    return json(400, { ok: false, detail: "Record-count header mismatch." });
  }

  const expectedSnapshotChecksum = request.headers.get("x-mto-snapshot-checksum")?.trim().toLowerCase();
  if (expectedSnapshotChecksum && expectedSnapshotChecksum !== String(snapshot.checksum || "").toLowerCase()) {
    return json(400, { ok: false, detail: "Snapshot checksum header mismatch." });
  }

  const blob = await storePortalSnapshot(snapshot);
  return json(200, {
    ok: true,
    status: "uploaded",
    uploaded: true,
    record_count: snapshot.record_count,
    checksum: snapshot.checksum,
    payload_sha256: actualPayloadHash,
    published_at: snapshot.published_at,
    blob_path: blob.pathname,
  });
}