// Shared safe metadata only. No database credentials or taxpayer information.
export const DEFAULT_MAX_SNAPSHOT_AGE_HOURS = 36;
export type PortalFreshness = {
  ok: boolean;
  status: "ready" | "stale" | "invalid_timestamp";
  published_at: string | null;
  age_hours: number | null;
  max_age_hours: number;
};

export function snapshotFreshness(publishedAt: unknown, maximum: unknown = 36, now = Date.now()): PortalFreshness {
  const configured = Number(maximum);
  const maxAge = Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_MAX_SNAPSHOT_AGE_HOURS;
  const value = typeof publishedAt === "string" ? publishedAt : null;
  const epoch = value && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : Number.NaN;
  const valid = Number.isFinite(epoch) && epoch <= now + 5 * 60_000;
  const age = valid ? Math.max(0, (now - epoch) / 3_600_000) : null;
  const ready = age !== null && age <= maxAge;
  return {
    ok: ready, status: !valid ? "invalid_timestamp" : ready ? "ready" : "stale",
    published_at: valid ? value : null, age_hours: age === null ? null : Number(age.toFixed(1)), max_age_hours: maxAge,
  };
}

export function formatPublishedAt(value: unknown): string {
  const date = typeof value === "string" ? new Date(value) : null;
  if (!date || !Number.isFinite(date.getTime())) return "Publication time unavailable";
  return new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", year: "numeric", month: "long", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date) + " (Philippine time)";
}

export function publicationDay(value: unknown): string | null {
  const date = typeof value === "string" ? new Date(value) : null;
  if (!date || !Number.isFinite(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Manila",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(date);
  const part = (type: string) => parts.find(p => p.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function formatPublicationShort(value:unknown):string {
  const date=typeof value==="string"?new Date(value):null;
  if(!date||!Number.isFinite(date.getTime()))return "Time unavailable";
  return new Intl.DateTimeFormat("en-PH",{timeZone:"Asia/Manila",year:"numeric",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}).format(date)+" PHT";
}

export function unavailableMessage(payload: any, fallback: string): string {
  if (payload?.code === "PORTAL_SNAPSHOT_STALE") {
    return `Published records are awaiting an update. Last published: ${formatPublishedAt(payload.freshness?.published_at)}. Please confirm current figures with the Treasury Office.`;
  }
  if (payload?.code === "PORTAL_SNAPSHOT_CHANGED") return "Published records changed while loading. Refresh this account to load a matching payment history.";
  return fallback;
}
