/**
 * Next.js Edge Middleware — Server-side authentication guard.
 *
 * Runs on the Edge Runtime before every request to /admin/* routes.
 * Redirects unauthenticated users to /admin/login WITHOUT rendering
 * the protected page first.
 *
 * Why this matters:
 * The previous client-side auth check (useEffect in layout.tsx) had a
 * flash-of-content problem — the protected page rendered briefly before
 * the redirect fired. This middleware prevents that entirely by intercepting
 * the request at the edge before any React code runs.
 *
 * How it works:
 * The backend sets an httpOnly `access_token` cookie on login. This
 * middleware checks for the presence of that cookie. If it's missing,
 * the user is redirected to login immediately.
 *
 * NOTE: This is a presence check only — the cookie's JWT signature is
 * NOT verified here (Edge Runtime cannot run the full jose/jsonwebtoken
 * stack efficiently). Full cryptographic verification still happens in
 * the FastAPI backend on every API call. This middleware only prevents
 * the UI flash and improves UX — it is not a security boundary by itself.
 *
 * For stronger server-side verification, use the `jose` library to verify
 * the JWT in middleware (requires NEXT_PUBLIC_JWT_SECRET in env).
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Routes that require authentication
const PROTECTED_PREFIXES = ["/admin/dashboard", "/admin/properties", "/admin/cashier", "/admin/system", "/admin/users"];

// Routes that are always public (no redirect)
const PUBLIC_PATHS = ["/admin/login"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip middleware for public paths
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Only apply to protected admin routes
  const isProtected = PROTECTED_PREFIXES.some((p) => pathname.startsWith(p));
  if (!isProtected) {
    return NextResponse.next();
  }

  // Check for the httpOnly access_token cookie set by the backend on login
  const accessToken = request.cookies.get("access_token");

  if (!accessToken?.value) {
    // No token — redirect to login, preserving the intended destination
    const loginUrl = new URL("/admin/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Token present — allow the request through.
  // The FastAPI backend will verify the signature on the first API call.
  return NextResponse.next();
}

export const config = {
  // Only run middleware on admin routes — skip API routes, static files, etc.
  matcher: ["/admin/:path*"],
};
