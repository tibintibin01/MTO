/// <reference lib="webworker" />

import { defaultCache } from '@serwist/next/worker';
import type { PrecacheEntry, SerwistGlobalConfig } from 'serwist';
import { NetworkOnly, Serwist } from 'serwist';

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

// Financial, authentication, and staff-only routes must always use the live
// server. This rule is deliberately first so no later cache rule can serve a
// stale balance, receipt, delinquency status, or authenticated admin page.
const sensitiveNetworkOnly = {
  matcher: ({ url }: { url: URL }) =>
    url.origin === self.location.origin &&
    (url.pathname.startsWith('/api/') || url.pathname.startsWith('/admin')),
  handler: new NetworkOnly(),
};

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [sensitiveNetworkOnly, ...defaultCache],
  fallbacks: {
    entries: [
      {
        url: '/offline',
        matcher({ request }) {
          return request.destination === 'document';
        },
      },
    ],
  },
});

serwist.addEventListeners();
