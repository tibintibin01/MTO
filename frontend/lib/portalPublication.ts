/** Server-only, authenticated publication control. File bytes go directly to private Blob. */
import { createHash, createHmac, timingSafeEqual } from "crypto";
import { gunzipSync } from "zlib";
import { get, head, put, del, issueSignedToken, presignUrl, BlobPreconditionFailedError } from "@vercel/blob";
import { PORTAL_SNAPSHOT_BLOB_PATH, storePortalSnapshot } from "./portalSnapshot";

export const PORTAL_RELEASE = "20261007-capacity-ux";
export const PUBLICATION_PROTOCOL = "private-direct-v1";
export const MAX_COMPRESSED_BYTES = 32 * 1024 * 1024;
export const MAX_EXPANDED_BYTES = 60 * 1024 * 1024;
export const MAX_CONTROL_BYTES = 16 * 1024;
const STAGING_PREFIX = "portal/publication-staging/";
const ID = /^[a-f0-9]{32}$/;
const HASH = /^[a-f0-9]{64}$/;
const LIFETIME_MS = 20 * 60 * 1000;

export class PublicationError extends Error {
  constructor(public code: string, public status = 400) { super(code); }
}
function need(condition: unknown, code: string, status = 400): asserts condition {
  if (!condition) throw new PublicationError(code, status);
}
export function sha256(bytes: Buffer | string) { return createHash("sha256").update(bytes).digest("hex"); }
function equal(a: string, b: string) {
  const left = Buffer.from(a), right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}
function publishSecret() {
  need(!process.env.VERCEL_ENV || process.env.VERCEL_ENV === "production", "PUBLICATION_DISABLED_FOR_PREVIEW", 503);
  const secret = process.env.MTO_PORTAL_PUBLISH_TOKEN?.trim();
  need(secret && secret.length >= 32, "PUBLICATION_NOT_CONFIGURED", 503);
  return secret;
}
export function authorizePublication(request: Request) {
  const secret = publishSecret();
  const header = request.headers.get("authorization") || "";
  need(header.startsWith("Bearer ") && equal(header.slice(7).trim(), secret), "UNAUTHORIZED", 401);
}
export async function boundedBytes(stream: ReadableStream<Uint8Array> | null, limit: number): Promise<Buffer> {
  need(stream, "EMPTY_BODY");
  const reader = stream.getReader(), buffers: Buffer[] = []; let length = 0;
  try {
    while (true) {
      const part = await reader.read(); if (part.done) break;
      length += part.value.byteLength;
      if (length > limit) { await reader.cancel(); throw new PublicationError("BODY_TOO_LARGE", 413); }
      buffers.push(Buffer.from(part.value));
    }
    return Buffer.concat(buffers, length);
  } finally { reader.releaseLock(); }
}
export async function controlBody(request: Request) {
  try { return JSON.parse((await boundedBytes(request.body, MAX_CONTROL_BYTES)).toString("utf8")); }
  catch (error) { if (error instanceof PublicationError) throw error; throw new PublicationError("INVALID_JSON"); }
}
export type Manifest = {
  protocol: string; upload_id: string; compressed_bytes: number; expanded_bytes: number;
  payload_sha256: string; expanded_payload_sha256: string; checksum: string;
  record_count: number; published_at: string;
};
type Ticket = Manifest & { expires_at_ms: number; baseline_etag: string };
export function validateManifest(value: any, now = Date.now(), checkFreshness = true): Manifest {
  need(value && typeof value === "object" && !Array.isArray(value), "INVALID_MANIFEST");
  const allowed = ["protocol", "upload_id", "compressed_bytes", "expanded_bytes", "payload_sha256",
    "expanded_payload_sha256", "checksum", "record_count", "published_at"];
  need(Object.keys(value).length === allowed.length && allowed.every(key => Object.hasOwn(value, key)), "INVALID_MANIFEST_FIELDS");
  need(value.protocol === PUBLICATION_PROTOCOL && typeof value.upload_id === "string" && ID.test(value.upload_id), "INVALID_UPLOAD_ID");
  need(Number.isInteger(value.compressed_bytes) && value.compressed_bytes > 0 && value.compressed_bytes <= MAX_COMPRESSED_BYTES,
    "COMPRESSED_LIMIT_EXCEEDED", 413);
  need(Number.isInteger(value.expanded_bytes) && value.expanded_bytes > 0 && value.expanded_bytes <= MAX_EXPANDED_BYTES,
    "EXPANDED_LIMIT_EXCEEDED", 413);
  need(Number.isInteger(value.record_count) && value.record_count > 0 && value.record_count <= 500000, "INVALID_RECORD_COUNT");
  for (const key of ["payload_sha256", "expanded_payload_sha256", "checksum"]) need(typeof value[key] === "string" && HASH.test(value[key]), "INVALID_HASH");
  need(typeof value.published_at === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value.published_at), "INVALID_PUBLICATION_TIME");
  const date = Date.parse(value.published_at);
  need(Number.isFinite(date), "INVALID_PUBLICATION_TIME");
  if (checkFreshness) need(date <= now + 120000 && date >= now - 60 * 60 * 1000, "PUBLICATION_NOT_CURRENT");
  return value;
}
function encodeTicket(value: Ticket, secret: string) {
  const payload = Buffer.from(JSON.stringify(value)).toString("base64url");
  const mac = createHmac("sha256", secret).update("MTO-PORTAL-DIRECT-V1\0" + payload).digest("hex");
  return payload + "." + mac;
}
export function decodeTicket(ticket: unknown, secret: string, now = Date.now(), inspectionOnly = false): Ticket {
  need(typeof ticket === "string" && ticket.length < 4096 && /^[A-Za-z0-9_-]+\.[a-f0-9]{64}$/.test(ticket), "INVALID_TICKET");
  const [payload, mac] = ticket.split(".");
  const expected = createHmac("sha256", secret).update("MTO-PORTAL-DIRECT-V1\0" + payload).digest("hex");
  need(equal(mac, expected), "TICKET_AUTHENTICATION_FAILED", 401);
  let value: Ticket;
  try { value = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")); } catch { throw new PublicationError("INVALID_TICKET"); }
  const { expires_at_ms, baseline_etag, ...manifest } = value;
  validateManifest(manifest, now, !inspectionOnly);
  need(Number.isInteger(expires_at_ms) && expires_at_ms > 0 && expires_at_ms <= now + LIFETIME_MS + 120000, "INVALID_TICKET");
  if (!inspectionOnly) need(expires_at_ms > now, "TICKET_EXPIRED", 409);
  need(typeof baseline_etag === "string" && baseline_etag.length > 0 && baseline_etag.length <= 256, "INVALID_BASELINE");
  return value;
}
function stagingPath(id: string) { need(ID.test(id), "INVALID_UPLOAD_ID"); return STAGING_PREFIX + id + ".json.gz"; }

// Injection is for synthetic tests; production always uses the existing private store.
type IO = { get: typeof get; head: typeof head; put: typeof put; del: typeof del;
  issueSignedToken: typeof issueSignedToken; presignUrl: typeof presignUrl; store: typeof storePortalSnapshot };
const storage: IO = { get, head, put, del, issueSignedToken, presignUrl, store: storePortalSnapshot };
export async function preparePublication(body: unknown, io: IO = storage, now = Date.now()) {
  const manifest = validateManifest(body, now), secret = publishSecret(), pathname = stagingPath(manifest.upload_id);
  // Never issue a wildcard/store-wide credential or rights to read/delete other files.
  const baseline = await io.head(PORTAL_SNAPSHOT_BLOB_PATH);
  need(baseline.etag, "BASELINE_UNAVAILABLE", 503);
  const expires = now + LIFETIME_MS;
  const token = await io.issueSignedToken({ pathname, operations: ["put"], validUntil: expires,
    allowedContentTypes: ["application/gzip"], maximumSizeInBytes: manifest.compressed_bytes });
  const signed = await io.presignUrl(token, { pathname, operation: "put", access: "private", validUntil: expires,
    allowedContentTypes: ["application/gzip"], maximumSizeInBytes: manifest.compressed_bytes,
    addRandomSuffix: false, allowOverwrite: false, cacheControlMaxAge: 60 });
  const target = new URL(signed.presignedUrl);
  need(target.origin === "https://vercel.com" && target.pathname === "/api/blob/" &&
    target.searchParams.get("pathname") === pathname && !target.username && !target.password && !target.hash,
    "UPLOAD_DESTINATION_NOT_APPROVED", 503);
  return { ok: true, status: "prepared", protocol: PUBLICATION_PROTOCOL, upload_id: manifest.upload_id,
    ticket: encodeTicket({ ...manifest, expires_at_ms: expires, baseline_etag: baseline.etag }, secret),
    upload_url: signed.presignedUrl, expires_at_ms: expires };
}

export function validatePayload(compressed: Buffer, ticket: Ticket) {
  need(compressed.length === ticket.compressed_bytes && sha256(compressed) === ticket.payload_sha256, "PAYLOAD_HASH_MISMATCH");
  let raw: Buffer;
  try { raw = gunzipSync(compressed, { maxOutputLength: MAX_EXPANDED_BYTES }); }
  catch { throw new PublicationError("INVALID_OR_OVERSIZED_GZIP", 413); }
  need(raw.length === ticket.expanded_bytes && sha256(raw) === ticket.expanded_payload_sha256, "EXPANDED_HASH_MISMATCH");
  for (const key of [process.env.MTO_PORTAL_PUBLISH_TOKEN, process.env.MTO_PORTAL_LOOKUP_SECRET]) {
    need(!key || !raw.includes(Buffer.from(key)), "CREDENTIAL_PAYLOAD_REJECTED");
  }
  let snapshot: any;
  try { snapshot = JSON.parse(raw.toString("utf8")); } catch { throw new PublicationError("INVALID_JSON"); }
  need(snapshot && snapshot.schema_version === 2 && snapshot.owner_lookup_version === 2 &&
    Array.isArray(snapshot.properties) && snapshot.properties.length === ticket.record_count &&
    snapshot.record_count === ticket.record_count && snapshot.checksum === ticket.checksum &&
    snapshot.published_at === ticket.published_at, "SNAPSHOT_IDENTITY_MISMATCH");
  const accounts = new Set();
  for (const record of snapshot.properties) {
    need(record && HASH.test(record.public_account_key) && !accounts.has(record.public_account_key), "ACCOUNT_ISOLATION_FAILED");
    accounts.add(record.public_account_key);
    need(typeof record.owner_name === "string" && (record.owner_name === "Taxpayer" ||
      /^[^\s*](?:\*{3})?(?: [^\s*](?:\*{3})?)*$/u.test(record.owner_name)), "UNMASKED_OWNER_REJECTED");
    need(record.pin_masked == null || record.pin_masked === "PIN-****" || /^.{4}\*{4}.{4}$/u.test(record.pin_masked), "UNMASKED_PIN_REJECTED");
    need(Array.isArray(record.payment_history), "INVALID_HISTORY");
    for (const row of record.payment_history) need(row.or_number == null || row.or_number === "***" || /^.{3}\*{4}$/u.test(row.or_number), "UNMASKED_RECEIPT_REJECTED");
  }
  return { raw, snapshot };
}
export async function commitPublication(ticketInput: unknown, io: IO = storage, now = Date.now()) {
  const ticket = decodeTicket(ticketInput, publishSecret(), now), pathname = stagingPath(ticket.upload_id);
  const current = await io.get(PORTAL_SNAPSHOT_BLOB_PATH, { access: "private", useCache: false });
  need(current?.statusCode === 200, "BASELINE_UNAVAILABLE", 503);
  const currentRaw = await boundedBytes(current.stream, MAX_EXPANDED_BYTES);
  let replay = false;
  if (sha256(currentRaw) === ticket.expanded_payload_sha256) {
    let snapshot: any;
    try { snapshot = JSON.parse(currentRaw.toString("utf8")); } catch { throw new PublicationError("INVALID_CURRENT_SNAPSHOT", 503); }
    need(snapshot.checksum === ticket.checksum && snapshot.published_at === ticket.published_at &&
      snapshot.record_count === ticket.record_count && snapshot.properties?.length === ticket.record_count,
      "SNAPSHOT_IDENTITY_MISMATCH");
    replay = true;
  }
  if (!replay) {
    need(current.blob.etag === ticket.baseline_etag, "PUBLICATION_CHANGED_REVIEW_REQUIRED", 409);
    const staged = await io.get(pathname, { access: "private", useCache: false });
    need(staged?.statusCode === 200 && staged.blob.size === ticket.compressed_bytes, "UPLOAD_NOT_COMPLETE", 409);
    const compressed = await boundedBytes(staged.stream, MAX_COMPRESSED_BYTES);
    const { raw, snapshot } = validatePayload(compressed, ticket);
    // Conditional write closes the race with another publisher. Preserve exact
    // Python JSON bytes (including numeric spelling) for cryptographic readback.
    try { await io.store(snapshot, { rawBody: raw, ifMatch: ticket.baseline_etag }); }
    catch (error) {
      if (error instanceof BlobPreconditionFailedError) throw new PublicationError("PUBLICATION_CHANGED_REVIEW_REQUIRED", 409);
      throw error;
    }
  }
  let stagingRemoved = false;
  // Only this exact helper-owned staging file, never a prefix or financial backup.
  try { await io.del(pathname); stagingRemoved = true; } catch { /* Report cleanup pending; do not mask committed data. */ }
  return { ok: true, status: "uploaded", uploaded: true, protocol: PUBLICATION_PROTOCOL,
    upload_id: ticket.upload_id, record_count: ticket.record_count, published_at: ticket.published_at,
    checksum: ticket.checksum, payload_sha256: ticket.payload_sha256,
    expanded_payload_sha256: ticket.expanded_payload_sha256, replay_verified: replay,
    staging_removed: stagingRemoved };
}

/** Inspection never calls store, put, signing or deletion. Expired MAC-valid
 * tickets may be inspected, but commit always uses the original expiry guard. */
export async function inspectPublication(ticketInput: unknown, io: IO = storage, now = Date.now()) {
  const ticket = decodeTicket(ticketInput, publishSecret(), now, true);
  const pathname = stagingPath(ticket.upload_id);
  const currentHead = await io.head(PORTAL_SNAPSHOT_BLOB_PATH);
  const current = await io.get(PORTAL_SNAPSHOT_BLOB_PATH, { access: "private", useCache: false });
  need(current?.statusCode === 200, "BASELINE_UNAVAILABLE", 503);
  const currentRaw = await boundedBytes(current.stream, MAX_EXPANDED_BYTES);
  let metadata: any;
  try { metadata = JSON.parse(currentRaw.toString("utf8")); } catch { throw new PublicationError("INVALID_CURRENT_SNAPSHOT", 503); }
  const staged = await io.get(pathname, { access: "private", useCache: false });
  let storedBytes = 0, bytesMatch = false, expandedMatch = false, validationCode: string | null = null;
  if (staged?.statusCode === 200) {
    const compressed = await boundedBytes(staged.stream, MAX_COMPRESSED_BYTES);
    storedBytes = compressed.length; bytesMatch = sha256(compressed) === ticket.payload_sha256;
    try { validatePayload(compressed, ticket); expandedMatch = true; }
    catch (error) { validationCode = error instanceof PublicationError ? error.code : "PAYLOAD_VALIDATION_UNAVAILABLE"; }
  }
  const currentMatches = sha256(currentRaw) === ticket.expanded_payload_sha256;
  const etagMatches = current.blob.etag === ticket.baseline_etag;
  const sizeMatches = staged?.statusCode === 200 && staged.blob.size === ticket.compressed_bytes;
  const expired = ticket.expires_at_ms <= now;
  const code = expired ? "TICKET_EXPIRED" : currentMatches ? "CURRENT_BYTES_MATCH_CANDIDATE" :
    !etagMatches ? "PUBLICATION_CHANGED_REVIEW_REQUIRED" : !sizeMatches ? "UPLOAD_NOT_COMPLETE" :
    validationCode || "READY_FOR_COMMIT_REVIEW";
  return { ok: true, report_type: "MTO_PRIVATE_PUBLICATION_INSPECTION", read_only: true, code,
    expired, record_count: ticket.record_count, candidate_published_at: ticket.published_at,
    current_record_count: metadata.record_count, current_published_at: metadata.published_at,
    current_bytes_match_candidate: currentMatches,
    head_etag_matches_ticket: currentHead.etag === ticket.baseline_etag,
    get_etag_matches_ticket: etagMatches,
    head_etag_fingerprint: sha256(currentHead.etag).slice(0,16),
    get_etag_fingerprint: sha256(current.blob.etag).slice(0,16),
    ticket_etag_fingerprint: sha256(ticket.baseline_etag).slice(0,16),
    head_etag_quoted: currentHead.etag.startsWith('"'),
    get_etag_quoted: current.blob.etag.startsWith('"'),
    get_etag_weak: current.blob.etag.startsWith('W/'),
    staged_present: staged?.statusCode === 200,
    staged_reported_bytes: staged?.statusCode === 200 ? staged.blob.size : null,
    staged_actual_bytes: storedBytes, expected_compressed_bytes: ticket.compressed_bytes,
    staged_payload_hash_matches: bytesMatch, staged_expanded_integrity_matches: expandedMatch,
    payload_validation_code: validationCode };
}
