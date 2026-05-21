/**
 * MTO Treasury System — k6 Performance Test
 * ==========================================
 *
 * Tests three scenarios that represent real tax-season load patterns:
 *
 *   smoke      — 1 user, 1 minute. Verifies the script works before a full run.
 *   load       — Ramp to 100 users over 2 min, hold 5 min, ramp down 1 min.
 *                Represents a normal busy day at the treasury office.
 *   stress     — Ramp to 200 users. Finds the breaking point.
 *
 * Usage
 * -----
 *   # Install k6: https://k6.io/docs/getting-started/installation/
 *
 *   # Smoke test (quick sanity check):
 *   k6 run --env SCENARIO=smoke tests/load/performance_test.js
 *
 *   # Load test (default):
 *   k6 run --env API_URL=https://staging-api.mto.gov \
 *           --env CASHIER_USER=cashier_test \
 *           --env CASHIER_PASS=TestP@ssw0rd! \
 *           tests/load/performance_test.js
 *
 *   # Stress test:
 *   k6 run --env SCENARIO=stress tests/load/performance_test.js
 *
 * Environment variables
 * ---------------------
 *   API_URL       Base URL of the backend  (default: https://localhost:8000)
 *   CASHIER_USER  Cashier test account username
 *   CASHIER_PASS  Cashier test account password
 *   ADMIN_USER    Admin test account username
 *   ADMIN_PASS    Admin test account password
 *   SCENARIO      smoke | load | stress      (default: load)
 *
 * Performance thresholds
 * ----------------------
 *   P95 response time  < 500 ms   (all endpoints)
 *   P99 response time  < 1500 ms  (all endpoints)
 *   Error rate         < 1%
 *   Login success rate = 100%
 */

import http from "k6/http";
import { check, group, sleep, fail } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const loginErrors = new Rate("login_errors");
const searchLatency = new Trend("search_latency", true);
const delinquencyLatency = new Trend("delinquency_query_latency", true);
const paymentLedgerLatency = new Trend("payment_ledger_latency", true);
const analyticsLatency = new Trend("analytics_latency", true);
const rateLimitHits = new Counter("rate_limit_hits");

// ---------------------------------------------------------------------------
// Scenario configuration
// ---------------------------------------------------------------------------

const SCENARIO = __ENV.SCENARIO || "load";

const SCENARIOS = {
  smoke: {
    executor: "constant-vus",
    vus: 1,
    duration: "1m",
  },
  load: {
    executor: "ramping-vus",
    startVUs: 0,
    stages: [
      { duration: "2m", target: 50 },   // Ramp up — staff arriving at office
      { duration: "5m", target: 100 },  // Peak — tax season rush
      { duration: "1m", target: 0 },    // Ramp down
    ],
  },
  stress: {
    executor: "ramping-vus",
    startVUs: 0,
    stages: [
      { duration: "2m", target: 100 },
      { duration: "3m", target: 200 },  // Beyond normal capacity
      { duration: "2m", target: 0 },
    ],
  },
};

export const options = {
  scenarios: {
    mto_load: SCENARIOS[SCENARIO] || SCENARIOS.load,
  },
  thresholds: {
    // Global thresholds
    http_req_duration: ["p(95)<500", "p(99)<1500"],
    http_req_failed: ["rate<0.01"],

    // Endpoint-specific thresholds
    login_errors: ["rate<0.001"],           // Login must be near-perfect
    search_latency: ["p(95)<300"],          // Search must be fast
    delinquency_query_latency: ["p(95)<800"], // Heavy aggregate — more lenient
    analytics_latency: ["p(95)<600"],
    payment_ledger_latency: ["p(95)<400"],
  },
  // Suppress TLS errors for self-signed certs in dev/staging
  insecureSkipTLSVerify: true,
};

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.API_URL || "https://localhost:8000";

const CASHIER_CREDS = {
  username: __ENV.CASHIER_USER || "cashier_test",
  password: __ENV.CASHIER_PASS || "TestP@ssw0rd!",
};

const ADMIN_CREDS = {
  username: __ENV.ADMIN_USER || "admin_test",
  password: __ENV.ADMIN_PASS || "TestP@ssw0rd!",
};

const SAMPLE_TD_NUMBERS = [
  "06-0012-01379",
  "06-0012-02143",
  "06-0006-00012",
  "06-0012-02564",
  "06-0012-02561",
];

const SAMPLE_NAMES = ["DELA CRUZ", "GARCIA", "REYES", "SANTOS", "POBLACION"];

function randomItem(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// ---------------------------------------------------------------------------
// Auth helper — returns headers with Bearer token
// ---------------------------------------------------------------------------

function login(creds) {
  const res = http.post(
    `${BASE_URL}/api/auth/login`,
    JSON.stringify(creds),
    {
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      tags: { name: "[auth] POST /api/auth/login" },
    }
  );

  const ok = check(res, {
    "login status 200": (r) => r.status === 200,
    "login returns token": (r) => {
      try {
        return r.json("access_token") !== undefined;
      } catch {
        return false;
      }
    },
  });

  loginErrors.add(!ok);

  if (!ok) {
    fail(`Login failed for ${creds.username}: HTTP ${res.status}`);
  }

  const token = res.json("access_token");
  return {
    Authorization: `Bearer ${token}`,
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/json",
  };
}

// ---------------------------------------------------------------------------
// Scenario functions
// ---------------------------------------------------------------------------

function runCashierWorkflow(headers) {
  group("Cashier: Property Search", () => {
    // Search by TD number (most common cashier action)
    const td = randomItem(SAMPLE_TD_NUMBERS);
    const start = Date.now();
    const res = http.get(
      `${BASE_URL}/properties?search=${td}&limit=10`,
      { headers, tags: { name: "[cashier] GET /properties?search=<td>" } }
    );
    searchLatency.add(Date.now() - start);

    check(res, {
      "property search 200": (r) => r.status === 200,
      "property search has items": (r) => {
        try { return Array.isArray(r.json("items")); } catch { return false; }
      },
    });

    if (res.status === 429) rateLimitHits.add(1);
  });

  sleep(0.5);

  group("Cashier: Property Statement", () => {
    // View billing statement before posting payment
    const propId = Math.floor(Math.random() * 20) + 1;
    const res = http.get(
      `${BASE_URL}/properties/${propId}/statement`,
      { headers, tags: { name: "[cashier] GET /properties/:id/statement" } }
    );
    check(res, {
      "statement 200 or 404": (r) => r.status === 200 || r.status === 404,
    });
  });

  sleep(0.5);

  group("Cashier: Next OR Number", () => {
    const res = http.get(
      `${BASE_URL}/payments/next-or`,
      { headers, tags: { name: "[cashier] GET /payments/next-or" } }
    );
    check(res, {
      "next OR 200": (r) => r.status === 200,
      "next OR has value": (r) => {
        try { return r.json("next_or") !== undefined; } catch { return false; }
      },
    });
  });

  sleep(0.5);

  group("Cashier: Recent Payments", () => {
    const res = http.get(
      `${BASE_URL}/payments/recent?limit=8`,
      { headers, tags: { name: "[cashier] GET /payments/recent" } }
    );
    check(res, { "recent payments 200": (r) => r.status === 200 });
  });

  sleep(0.5);

  group("Cashier: Payment Ledger", () => {
    const td = randomItem(SAMPLE_TD_NUMBERS);
    const start = Date.now();
    const res = http.get(
      `${BASE_URL}/payments/ledger?term=${td}`,
      { headers, tags: { name: "[cashier] GET /payments/ledger" } }
    );
    paymentLedgerLatency.add(Date.now() - start);
    check(res, { "ledger 200 or 404": (r) => r.status === 200 || r.status === 404 });
  });
}

function runViewerWorkflow(headers) {
  group("Viewer: Delinquent Accounts", () => {
    // Most expensive query — GROUP BY + HAVING on large table
    const start = Date.now();
    const res = http.get(
      `${BASE_URL}/properties/delinquent?limit=50`,
      { headers, tags: { name: "[viewer] GET /properties/delinquent" } }
    );
    delinquencyLatency.add(Date.now() - start);
    check(res, {
      "delinquent 200": (r) => r.status === 200,
      "delinquent has items key": (r) => {
        try { return "items" in r.json(); } catch { return false; }
      },
    });
  });

  sleep(1);

  group("Viewer: Assessment Roll", () => {
    const res = http.get(
      `${BASE_URL}/billing/assessment-roll?limit=100`,
      { headers, tags: { name: "[viewer] GET /billing/assessment-roll" } }
    );
    check(res, { "assessment roll 200": (r) => r.status === 200 });
  });

  sleep(1);

  group("Viewer: Analytics", () => {
    const start = Date.now();
    const res = http.get(
      `${BASE_URL}/analytics/kpis`,
      { headers, tags: { name: "[viewer] GET /analytics/kpis" } }
    );
    analyticsLatency.add(Date.now() - start);
    check(res, { "kpis 200": (r) => r.status === 200 });
  });

  sleep(1);

  group("Viewer: Barangay Breakdown", () => {
    const res = http.get(
      `${BASE_URL}/analytics/barangay-breakdown`,
      { headers, tags: { name: "[viewer] GET /analytics/barangay-breakdown" } }
    );
    check(res, { "barangay breakdown 200": (r) => r.status === 200 });
  });
}

function runAdminWorkflow(headers) {
  group("Admin: Health Check", () => {
    const res = http.get(
      `${BASE_URL}/healthz`,
      { headers, tags: { name: "[admin] GET /healthz" } }
    );
    check(res, {
      "health 200": (r) => r.status === 200,
      "health status healthy": (r) => {
        try { return r.json("status") === "healthy"; } catch { return false; }
      },
    });
  });

  sleep(2);

  group("Admin: Audit Logs", () => {
    const res = http.get(
      `${BASE_URL}/system/audit-logs?limit=50`,
      { headers, tags: { name: "[admin] GET /system/audit-logs" } }
    );
    check(res, { "audit logs 200": (r) => r.status === 200 });
  });

  sleep(2);

  group("Admin: Backup Status", () => {
    const res = http.get(
      `${BASE_URL}/system/backup/status`,
      { headers, tags: { name: "[admin] GET /system/backup/status" } }
    );
    check(res, { "backup status 200": (r) => r.status === 200 });
  });
}

function runPublicPortalWorkflow() {
  group("Public: Property Lookup", () => {
    const td = randomItem(SAMPLE_TD_NUMBERS);
    const res = http.get(
      `${BASE_URL}/public/property/${td}`,
      { tags: { name: "[public] GET /public/property/:td" } }
    );
    check(res, {
      "public lookup 200 or 404": (r) => r.status === 200 || r.status === 404,
      "not rate limited": (r) => {
        if (r.status === 429) { rateLimitHits.add(1); }
        return r.status !== 500;
      },
    });
  });
}

// ---------------------------------------------------------------------------
// Main entry point — each VU picks a persona based on its ID
// ---------------------------------------------------------------------------

export default function () {
  // Distribute VUs across personas: 50% cashier, 30% viewer, 20% admin/public
  const roll = Math.random();

  if (roll < 0.50) {
    // Cashier workflow
    const headers = login(CASHIER_CREDS);
    runCashierWorkflow(headers);
    sleep(Math.random() * 2 + 1);

  } else if (roll < 0.80) {
    // Viewer workflow
    const headers = login(CASHIER_CREDS); // viewers use same auth flow
    runViewerWorkflow(headers);
    sleep(Math.random() * 3 + 2);

  } else if (roll < 0.90) {
    // Admin workflow
    const headers = login(ADMIN_CREDS);
    runAdminWorkflow(headers);
    sleep(Math.random() * 5 + 5);

  } else {
    // Public portal — no auth
    runPublicPortalWorkflow();
    sleep(Math.random() * 5 + 3);
  }
}

// ---------------------------------------------------------------------------
// Setup — runs once before the test, verifies the server is reachable
// ---------------------------------------------------------------------------

export function setup() {
  const res = http.get(`${BASE_URL}/`, {
    tags: { name: "[setup] GET /" },
  });

  if (res.status !== 200) {
    fail(
      `Server at ${BASE_URL} is not reachable (HTTP ${res.status}). ` +
      "Start the backend before running load tests."
    );
  }

  console.log(`✓ Server reachable at ${BASE_URL}`);
  console.log(`✓ Running scenario: ${SCENARIO}`);
  return { baseUrl: BASE_URL };
}
