/** @type {import('next').NextConfig} */
const withPWA = require('next-pwa')({
  dest: 'public',
  disable: process.env.NODE_ENV === 'development',
  register: true,
  skipWaiting: true,
  // Never cache API routes — financial data (payment status, assessed values)
  // must always be fetched live. Serving stale tax data from cache could show
  // a property as DELINQUENT after it was already paid that day.
  // Auth routes are also excluded — a cached 401 would lock users out offline.
  runtimeCaching: [
    {
      // Static Next.js assets — cache-first, long TTL
      urlPattern: /^\/_next\/static\/.*/i,
      handler: 'CacheFirst',
      options: {
        cacheName: 'next-static',
        expiration: { maxEntries: 200, maxAgeSeconds: 365 * 24 * 60 * 60 },
      },
    },
    {
      // Next.js image optimisation
      urlPattern: /^\/_next\/image\?.*/i,
      handler: 'StaleWhileRevalidate',
      options: {
        cacheName: 'next-image',
        expiration: { maxEntries: 64, maxAgeSeconds: 24 * 60 * 60 },
      },
    },
    {
      // Self-hosted fonts (Inter via next/font)
      urlPattern: /\.(?:woff|woff2|ttf|otf|eot)$/i,
      handler: 'CacheFirst',
      options: {
        cacheName: 'fonts',
        expiration: { maxEntries: 10, maxAgeSeconds: 365 * 24 * 60 * 60 },
      },
    },
    {
      // Static images (logo, seal, icons)
      urlPattern: /\.(?:png|jpg|jpeg|svg|gif|ico|webp)$/i,
      handler: 'StaleWhileRevalidate',
      options: {
        cacheName: 'images',
        expiration: { maxEntries: 32, maxAgeSeconds: 7 * 24 * 60 * 60 },
      },
    },
    {
      // API routes — NetworkOnly: NEVER cache financial or auth data.
      // If the network is unavailable the request fails and the app shows
      // an error rather than serving potentially outdated tax information.
      urlPattern: /^\/api\/.*/i,
      handler: 'NetworkOnly',
    },
    {
      // Offline fallback page — precached so it's available without network
      urlPattern: /^\/offline$/i,
      handler: 'CacheFirst',
      options: {
        cacheName: 'offline-page',
        expiration: { maxEntries: 1, maxAgeSeconds: 365 * 24 * 60 * 60 },
      },
    },
    {
      // All other same-origin pages — NetworkFirst with offline fallback
      urlPattern: ({ url }) => url.origin === self.location.origin,
      handler: 'NetworkFirst',
      options: {
        cacheName: 'pages',
        networkTimeoutSeconds: 10,
        expiration: { maxEntries: 32, maxAgeSeconds: 24 * 60 * 60 },
      },
    },
  ],
});

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
  // Disable unused browser features
  {
    key: 'Permissions-Policy',
    value: 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  },
  // Content Security Policy for the public portal.
  // Next.js 14 requires:
  //   'unsafe-inline' — for hydration scripts injected at runtime
  // 'unsafe-eval' is intentionally REMOVED from production.
  // It was previously included for webpack dev HMR, but next-pwa already
  // sets `disable: process.env.NODE_ENV === 'development'`, so eval is
  // only needed in dev mode. We gate it on NODE_ENV here to match.
  // The PWA service worker requires:
  //   worker-src 'self' — for the Workbox service worker registration
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

  // Security headers on every response
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: securityHeaders,
      },
    ];
  },

  // Proxy API calls to the FastAPI backend
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001'}/:path*`,
      },
    ];
  },
};

module.exports = withPWA(nextConfig);
