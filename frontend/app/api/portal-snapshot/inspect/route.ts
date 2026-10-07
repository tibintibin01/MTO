import { NextResponse } from "next/server";
import { authorizePublication, controlBody, inspectPublication, PublicationError } from "../../../../lib/portalPublication";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;
export async function POST(request: Request) {
  try {
    authorizePublication(request);
    const body = await controlBody(request);
    if (!body || Object.keys(body).length !== 1 || !Object.hasOwn(body, "ticket")) throw new PublicationError("INVALID_INSPECTION_FIELDS");
    return NextResponse.json(await inspectPublication(body.ticket), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const known = error instanceof PublicationError;
    return NextResponse.json({ ok: false, code: known ? error.code : "INSPECTION_STORAGE_UNAVAILABLE" },
      { status: known ? error.status : 503, headers: { "Cache-Control": "no-store" } });
  }
}
