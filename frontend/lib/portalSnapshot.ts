import "server-only";

import { get, put } from "@vercel/blob";
import { createHmac } from "crypto";
import { readFile, stat } from "fs/promises";

export const PORTAL_SNAPSHOT_BLOB_PATH = "portal/portal_snapshot_latest.json";
export const PORTAL_SNAPSHOT_SCHEMA_VERSION = 2;
const DEFAULT_MAX_SNAPSHOT_AGE_HOURS = 36;
const BLOB_CACHE_TTL_MS = 30_000;

type SnapshotRecord = Record<string, any>;
type PortalSnapshot = {
  schema_version?: number;
  published_at?: string;
  record_count?: number;
  checksum?: string;
  properties?: SnapshotRecord[];
  owner_lookup_index?: Record<string, number[]>;
};

export class PortalSnapshotConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PortalSnapshotConfigError";
  }
}

export class PortalSnapshotDataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PortalSnapshotDataError";
  }
}

let localSnapshotCache: {
  signature: string;
  snapshot: PortalSnapshot;
} | null = null;

let blobSnapshotCache: {
  expiresAt: number;
  snapshot: PortalSnapshot;
} | null = null;

const propertyIndexCache = new WeakMap<object, Map<string, SnapshotRecord>>();

function requireLookupSecret(): string {
  const secret = process.env.MTO_PORTAL_LOOKUP_SECRET?.trim();
  if (!secret) {
    throw new PortalSnapshotConfigError("MTO_PORTAL_LOOKUP_SECRET is not configured.");
  }
  return secret;
}

export function normalizeLookup(value: string): string {
  return String(value || "").trim().toUpperCase();
}

function ownerTokens(value: string): string[] {
  return Array.from(new Set(normalizeLookup(value).match(/[A-Z0-9]+/g) || []))
    .filter((token) => token.length >= 3);
}

export function lookupHash(value: string, length = 64): string {
  const secret = requireLookupSecret();
  return createHmac("sha256", secret).update(normalizeLookup(value)).digest("hex").slice(0, length);
}

async function streamToText(stream: ReadableStream<Uint8Array>): Promise<string> {
  return new Response(stream).text();
}

function validateSnapshot(snapshot: PortalSnapshot, lookupSecret: string): PortalSnapshot {
  if (!snapshot || !Array.isArray(snapshot.properties)) {
    throw new PortalSnapshotDataError("Portal snapshot is missing a properties array.");
  }
  if (snapshot.schema_version !== PORTAL_SNAPSHOT_SCHEMA_VERSION) {
    throw new PortalSnapshotDataError(
      `Portal snapshot schema ${snapshot.schema_version ?? "unknown"} is not supported.`,
    );
  }
  if (typeof snapshot.record_count === "number" && snapshot.record_count !== snapshot.properties.length) {
    throw new PortalSnapshotDataError("Portal snapshot record_count does not match properties length.");
  }
  if (!snapshot.owner_lookup_index || typeof snapshot.owner_lookup_index !== "object") {
    throw new PortalSnapshotDataError("Portal snapshot is missing the owner lookup index.");
  }

  // Detect a backend/frontend secret mismatch during loading instead of making
  // every valid TDN silently return 404. A single complete record is enough to
  // prove that the snapshot was generated with the configured lookup secret.
  const sample = snapshot.properties.find((record) => record?.td_number && record?.td_lookup_hash);
  if (sample) {
    const expectedHash = createHmac("sha256", lookupSecret)
      .update(normalizeLookup(sample.td_number))
      .digest("hex");
    if (expectedHash !== sample.td_lookup_hash) {
      throw new PortalSnapshotDataError("Portal snapshot lookup configuration does not match the published data.");
    }
  } else if (snapshot.properties.length > 0) {
    throw new PortalSnapshotDataError("Portal snapshot has no usable property lookup records.");
  }
  return snapshot;
}

function parseSnapshot(raw: string, lookupSecret: string): PortalSnapshot {
  try {
    return validateSnapshot(JSON.parse(raw), lookupSecret);
  } catch (error) {
    if (error instanceof PortalSnapshotDataError) throw error;
    throw new PortalSnapshotDataError("Portal snapshot contains invalid JSON.");
  }
}

export async function loadPortalSnapshot(): Promise<PortalSnapshot | null> {
  const lookupSecret = requireLookupSecret();
  const localPath = process.env.MTO_PORTAL_SNAPSHOT_PATH?.trim();

  if (localPath) {
    let file;
    try {
      file = await stat(localPath);
    } catch (error: any) {
      if (error?.code === "ENOENT") {
        throw new PortalSnapshotDataError("Portal snapshot has not been generated yet.");
      }
      throw error;
    }
    const signature = `${localPath}:${file.size}:${file.mtimeMs}`;
    if (localSnapshotCache?.signature === signature) {
      return localSnapshotCache.snapshot;
    }

    const raw = await readFile(localPath, "utf8");
    const snapshot = parseSnapshot(raw, lookupSecret);
    localSnapshotCache = { signature, snapshot };
    return snapshot;
  }

  if (blobSnapshotCache && blobSnapshotCache.expiresAt > Date.now()) {
    return blobSnapshotCache.snapshot;
  }

  const blob = await get(PORTAL_SNAPSHOT_BLOB_PATH, { access: "private", useCache: false });
  if (!blob || blob.statusCode !== 200 || !blob.stream) {
    return null;
  }

  const raw = await streamToText(blob.stream);
  const snapshot = parseSnapshot(raw, lookupSecret);
  blobSnapshotCache = { expiresAt: Date.now() + BLOB_CACHE_TTL_MS, snapshot };
  return snapshot;
}

export async function storePortalSnapshot(snapshot: PortalSnapshot) {
  validateSnapshot(snapshot, requireLookupSecret());
  const body = JSON.stringify(snapshot);
  const result = await put(PORTAL_SNAPSHOT_BLOB_PATH, body, {
    access: "private",
    allowOverwrite: true,
    contentType: "application/json; charset=utf-8",
    cacheControlMaxAge: 60,
  });
  blobSnapshotCache = null;
  return result;
}

export function findSnapshotProperty(snapshot: PortalSnapshot, query: string): SnapshotRecord | null {
  const hash = lookupHash(query);
  let index = propertyIndexCache.get(snapshot);
  if (!index) {
    index = new Map<string, SnapshotRecord>();
    for (const record of snapshot.properties || []) {
      if (record?.td_lookup_hash) index.set(record.td_lookup_hash, record);
      if (record?.pin_lookup_hash) index.set(record.pin_lookup_hash, record);
    }
    propertyIndexCache.set(snapshot, index);
  }
  return index.get(hash) || null;
}

export async function portalSnapshotHealth() {
  const snapshot = await loadPortalSnapshot();
  if (!snapshot) {
    return { ok: false, status: "missing", detail: "Portal data has not been published yet." };
  }

  const publishedAt = snapshot.published_at ? new Date(snapshot.published_at) : null;
  const publishedAtMs = publishedAt?.getTime() ?? Number.NaN;
  const ageHours = Number.isFinite(publishedAtMs)
    ? Math.max(0, (Date.now() - publishedAtMs) / 3_600_000)
    : null;
  const configuredMaxAge = Number(process.env.MTO_PORTAL_MAX_SNAPSHOT_AGE_HOURS);
  const maxAgeHours = Number.isFinite(configuredMaxAge) && configuredMaxAge > 0
    ? configuredMaxAge
    : DEFAULT_MAX_SNAPSHOT_AGE_HOURS;
  const fresh = ageHours !== null && ageHours <= maxAgeHours;

  return {
    ok: fresh,
    status: fresh ? "ready" : "stale",
    schema_version: snapshot.schema_version,
    published_at: snapshot.published_at || null,
    age_hours: ageHours === null ? null : Number(ageHours.toFixed(1)),
    max_age_hours: maxAgeHours,
    record_count: snapshot.properties?.length || 0,
  };
}

export function publicProperty(record: SnapshotRecord, snapshot: PortalSnapshot) {
  return {
    td_number: record.td_number,
    pin: record.pin_masked || null,
    owner_name: record.owner_name || "Taxpayer",
    barangay: record.barangay || null,
    location: record.location || record.barangay || null,
    kind: record.kind || null,
    assessed_value: Number(record.assessed_value || 0),
    assessment_as_of_year: Number(record.assessment_as_of_year || 0) || null,
    future_assessment: record.future_assessment || null,
    status: record.status || "PENDING",
    balance: Number(record.balance || 0),
    total_credit: Number(record.total_credit || 0),
    total_due: Number(record.total_due || 0),
    total_paid: Number(record.total_paid || 0),
    billing_breakdown: Array.isArray(record.billing_breakdown) ? record.billing_breakdown : [],
    last_payment: record.last_payment || null,
    as_of: snapshot.published_at ? String(snapshot.published_at).slice(0, 10) : null,
  };
}

export function publicPaymentHistory(record: SnapshotRecord) {
  return Array.isArray(record.payment_history) ? record.payment_history : [];
}

export function findOwnerMatches(snapshot: PortalSnapshot, name: string, barangay?: string) {
  const tokens = ownerTokens(name);
  if (tokens.length === 0) {
    return [];
  }

  const index = snapshot.owner_lookup_index || {};
  let candidates: Set<number> | null = null;

  for (const token of tokens) {
    const tokenHash = lookupHash(token, 24);
    const matches = new Set(index[tokenHash] || []);
    candidates = candidates === null
      ? matches
      : new Set(Array.from(candidates).filter((idx) => matches.has(idx)));
    if (candidates.size === 0) break;
  }

  const cleanBarangay = normalizeLookup(barangay || "");
  return Array.from(candidates || new Set<number>())
    .sort((a, b) => a - b)
    .map((idx) => snapshot.properties?.[idx])
    .filter(Boolean)
    .filter((record) => !cleanBarangay || cleanBarangay === "ALL" || normalizeLookup(record.barangay || "") === cleanBarangay);
}

export function findResult(record: SnapshotRecord) {
  const td = String(record.td_number || "");
  return {
    owner_name: record.owner_name || "Taxpayer",
    td_tail: td ? `...${td.slice(-4)}` : "...",
    td_number: td,
    barangay: record.barangay || null,
    kind: record.kind || null,
  };
}
