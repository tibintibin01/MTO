import { NextRequest, NextResponse } from "next/server";
import { createHash } from "crypto";
import { gunzipSync } from "zlib";
import { storePortalSnapshot } from "../../../../lib/portalSnapshot";
import { authorizePublication, boundedBytes, PublicationError } from "../../../../lib/portalPublication";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const MAX_DECOMPRESSED_BYTES = 60 * 1024 * 1024;

function json(status: number, body: Record<string, any>) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

export async function POST(request: NextRequest) {
  try {
  authorizePublication(request);
  const compressedPayload = await boundedBytes(request.body, 4_400_000);
  const expectedPayloadHash = request.headers.get("x-mto-payload-sha256")?.trim().toLowerCase();
  const actualPayloadHash = createHash("sha256").update(compressedPayload).digest("hex");
  if (expectedPayloadHash && expectedPayloadHash !== actualPayloadHash) {
    return json(400, { ok: false, detail: "Payload checksum mismatch." });
  }

  const encoding = request.headers.get("content-encoding") || "";
  const payload = encoding.toLowerCase().includes("gzip")
    ? gunzipSync(compressedPayload, { maxOutputLength: MAX_DECOMPRESSED_BYTES })
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
  } catch (error) {
    return json(error instanceof PublicationError ? error.status : 503,
      { ok: false, code: error instanceof PublicationError ? error.code : "PUBLICATION_STORAGE_UNAVAILABLE" });
  }
}
