const withSerwist = require('@serwist/next').default({
  swSrc: 'app/sw.ts',
  swDest: 'public/sw.js',
  disable: process.env.NODE_ENV === 'development',
  register: true,
});

/** @type {import('next').NextConfig} */

// Security headers applied to every response from the Next.js server.
// These complement the headers set by the FastAPI backend and provide
// defence-in-depth for the public-facing portal.
const securityHeaders = [
  // Prevent MIME-type sniffing
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  // Block clickjacking
  { key: 'X-Frame-Options', value: 'DENY' },
  // Disable legacy XSS filter (modern browsers use CSP)
  { key: 'X-XSS-Protection', value: '0' },
  // Don't leak TD numbers in referrer headers to third-party sites
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  // HSTS: force HTTPS for 1 year (only effective when served over HTTPS)
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
  // Disable unused browser features
  {
    key: 'Permissions-Policy',
    value: 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  },
  // Content Security Policy for the public portal.
  // Next.js requires:
  //   'unsafe-inline' — for hydration scripts injected at runtime
  // 'unsafe-eval' is intentionally REMOVED from production.
  // It was previously included for webpack dev HMR. The service worker is
  // disabled in development, so eval is only needed in dev mode.
  // The PWA service worker requires worker-src 'self'.
  // Fonts from Google are not used (Inter is self-hosted via next/font),
  // so font-src 'self' is sufficient.
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      // Next.js needs unsafe-inline for hydration.
      // unsafe-eval is only added in development (webpack HMR requires it).
      process.env.NODE_ENV === 'development'
        ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
        : "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self'",
      // Same-origin API calls via Next.js proxy
      "connect-src 'self'",
      // PWA service worker
      "worker-src 'self'",
      // Block all framing
      "frame-ancestors 'none'",
    ].join('; '),
  },
];

const nextConfig = {
  reactStrictMode: true,

  // The updater builds into a staging directory, then swaps it into .next
  // only after a successful build. Normal npm start continues to use .next.
  distDir: process.env.MTO_NEXT_DIST_DIR || '.next',

  // Security headers on every response
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: securityHeaders,
      },
    ];
  },

};

module.exports = withSerwist(nextConfig);
