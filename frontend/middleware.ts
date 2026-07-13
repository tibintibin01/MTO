/**
 * The hosted portal is intentionally public and read-only. Staff operations
 * remain in the office desktop application, so legacy /admin routes are not
 * exposed from the internet-facing portal.
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  return NextResponse.redirect(new URL("/", request.url));
}

export const config = {
  // Public search and snapshot API routes are unaffected.
  matcher: ["/admin/:path*"],
};
