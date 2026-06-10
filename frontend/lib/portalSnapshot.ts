import "server-only";

import { get, put } from "@vercel/blob";
import { createHmac } from "crypto";
import { readFile } from "fs/promises";

export const PORTAL_SNAPSHOT_BLOB_PATH = "portal/portal_snapshot_latest.json";
const CACHE_TTL_MS = 30_000;

type SnapshotRecord = Record<string, any>;
type PortalSnapshot = {
  schema_version?: number;
  published_at?: string;
  record_count?: number;
  checksum?: string;
  properties?: SnapshotRecord[];
  owner_lookup_index?: Record<string, number[]>;
};

let cachedSnapshot: { value: PortalSnapshot; expiresAt: number } | null = null;

export class PortalSnapshotConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PortalSnapshotConfigError";
  }
}

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

function validateSnapshot(snapshot: PortalSnapshot): PortalSnapshot {
  if (!snapshot || !Array.isArray(snapshot.properties)) {
    throw new Error("Portal snapshot is missing a properties array.");
  }
  if (typeof snapshot.record_count === "number" && snapshot.record_count !== snapshot.properties.length) {
    throw new Error("Portal snapshot record_count does not match properties length.");
  }
  return snapshot;
}

export async function loadPortalSnapshot(): Promise<PortalSnapshot | null> {
  const now = Date.now();
  if (cachedSnapshot && cachedSnapshot.expiresAt > now) {
    return cachedSnapshot.value;
  }

  const localPath = process.env.MTO_PORTAL_SNAPSHOT_PATH?.trim();
  let raw: string | null = null;

  if (localPath) {
    raw = await readFile(localPath, "utf8");
  } else {
    const blob = await get(PORTAL_SNAPSHOT_BLOB_PATH, { access: "private", useCache: false });
    if (!blob || blob.statusCode !== 200 || !blob.stream) {
      return null;
    }
    raw = await streamToText(blob.stream);
  }

  const snapshot = validateSnapshot(JSON.parse(raw));
  cachedSnapshot = { value: snapshot, expiresAt: now + CACHE_TTL_MS };
  return snapshot;
}

export async function storePortalSnapshot(snapshot: PortalSnapshot) {
  validateSnapshot(snapshot);
  const body = JSON.stringify(snapshot);
  cachedSnapshot = { value: snapshot, expiresAt: Date.now() + CACHE_TTL_MS };
  return put(PORTAL_SNAPSHOT_BLOB_PATH, body, {
    access: "private",
    allowOverwrite: true,
    contentType: "application/json; charset=utf-8",
    cacheControlMaxAge: 60,
  });
}

export function findSnapshotProperty(snapshot: PortalSnapshot, query: string): SnapshotRecord | null {
  const hash = lookupHash(query);
  return (snapshot.properties || []).find((record) =>
    record?.td_lookup_hash === hash || record?.pin_lookup_hash === hash
  ) || null;
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
    status: record.status || "PENDING",
    balance: Number(record.balance || 0),
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