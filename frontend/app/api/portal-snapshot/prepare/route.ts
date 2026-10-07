import { NextResponse } from "next/server";
import { authorizePublication, controlBody, preparePublication, PublicationError } from "../../../../lib/portalPublication";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;
export async function POST(request: Request) {
  try {
    authorizePublication(request);
    const result = await preparePublication(await controlBody(request));
    return NextResponse.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    // Never log tokens, signed upload URLs, request bodies or SDK exception text.
    const known = error instanceof PublicationError;
    return NextResponse.json({ ok: false, code: known ? error.code : "PUBLICATION_STORAGE_UNAVAILABLE" },
      { status: known ? error.status : 503, headers: { "Cache-Control": "no-store" } });
  }
}
