import { NextResponse } from "next/server";
import { authorizePublication, controlBody, commitPublication, PublicationError } from "../../../../lib/portalPublication";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;
export async function POST(request: Request) {
  try {
    authorizePublication(request);
    const body = await controlBody(request);
    if (!body || Object.keys(body).length !== 1 || !Object.hasOwn(body, "ticket")) throw new PublicationError("INVALID_COMMIT_FIELDS");
    const result = await commitPublication(body.ticket);
    return NextResponse.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const known = error instanceof PublicationError;
    return NextResponse.json({ ok: false, code: known ? error.code : "PUBLICATION_STORAGE_UNAVAILABLE" },
      { status: known ? error.status : 503, headers: { "Cache-Control": "no-store" } });
  }
}
