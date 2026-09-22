# Original Phase 7 — Performance and Timeout Runbook

## Purpose

Original roadmap Phase 7 resolves performance and timeout problems without
weakening financial, audit, TLS, or release controls.  The first control is a
privacy-safe, read-only production assessment.  It measures representative
critical-screen queries and authenticated HTTPS readiness, then verifies that
desktop waits and database-pool waits are explicitly bounded.

This phase is distinct from a stress test.  The production preflight performs
only a small, fixed number of reads inside a read-only transaction.  It does
not post payments, generate PDFs, submit jobs, refresh caches, run migrations,
restart services, or create load.

## Approved thresholds

The server-side critical-query ceilings are:

| Critical workflow | Maximum |
| --- | ---: |
| Exact property search | 1.00 s |
| Recent payments | 0.75 s |
| Assessment-roll page | 0.75 s |
| Payment ledger | 1.00 s |
| Delinquent-account page | 2.00 s |
| Compliant-account page | 2.50 s |
| Compliance summary | 2.50 s |
| Operational analytics | 3.00 s |

Authenticated HTTPS readiness must complete within 2.00 seconds.  Every
operation is sampled three times by default; readiness is sampled five times.
The maximum observed sample is enforced, while median and p95 timings are kept
as evidence.

Desktop and pool policy must also satisfy these controls:

- connection establishment is bounded to five seconds;
- ordinary API requests, downloads, and queued SOA polling have finite waits;
- the desktop does not declare an outage after only one transient failure;
- the SQLAlchemy pool has at least twenty total connections including overflow;
- pool checkout waits are bounded to thirty seconds;
- connections are pre-pinged and recycled within thirty minutes; and
- live pool utilization below eighty percent passes without review.

These thresholds are release controls.  Increasing them to hide a regression
is not remediation and requires documented operational justification.

## Read-only production assessment

Run from an Administrator command prompt on the server after activating the
approved virtual environment:

```bat
cd /d C:\mto
call venv\Scripts\activate
git rev-parse --short HEAD
git status --short
python -m scripts.phase7_performance_timeout_preflight --require-ready --output logs\remediation-original-phase-7-assessment.json
echo Exit code: %ERRORLEVEL%
```

Exit code `0` means every component passed.  Exit code `2` means a blocking
finding or a review item was present while `--require-ready` was selected.
Without `--require-ready`, a review-only result exits `4`.

The report contains no taxpayer names, TD numbers, OR numbers, tokens, or
credentials.  Representative database identifiers are held only in memory and
are never serialized.

## Interpreting findings

- `CRITICAL_SCREEN_QUERY_LATENCY_EXCEEDED` — one named workflow exceeded its
  server-side ceiling.  Capture its query plan and index coverage before
  changing code or schema.
- `CRITICAL_SCREEN_QUERY_FAILED` — the representative service operation raised
  an exception.  Treat this as functional failure, not only a performance issue.
- `DATABASE_POOL_PRESSURE_HIGH` — at least eighty percent of available
  connections were checked out.  Re-run during representative operations and
  inspect session ownership before changing pool size.
- `DATABASE_POOL_EXHAUSTED` — no database connection capacity remained.  This
  blocks Phase 7.
- `CLIENT_*_TIMEOUT_UNBOUNDED` — the desktop can wait indefinitely or for an
  operationally excessive period.
- `API_LATENCY_EXCEEDED` — the authenticated TLS readiness path exceeded two
  seconds.

Any index, query, timeout, pool, cache, or concurrency change discovered by the
assessment is a separately validated Phase 7 hotfix.  Database changes require
a fresh protected backup, an idempotent migration, and before/after financial
invariant evidence.

## Load and stress testing

Do not run the k6 load or stress scenario against the production database.  It
uses repeated logins and concurrent critical-screen requests and is approved
only for an isolated staging environment containing synthetic data.

Before a staging load test:

1. use a staging hostname and a trusted staging CA;
2. use dedicated, non-production test accounts;
3. remove example credentials and taxpayer-like identifiers from the command;
4. start with the one-user smoke scenario;
5. retain p50, p95, p99, error-rate, pool-pressure, and rate-limit evidence; and
6. stop immediately if error rate exceeds one percent or database health
   degrades.

## Closure criteria

Phase 7 can close only when:

1. the production read-only gate passes with no findings;
2. each critical-screen threshold has recorded evidence;
3. client and pool waits are bounded;
4. no financial, audit, backup, TLS, or runtime regression is present;
5. a desktop pilot confirms property search, payment ledger, delinquency,
   analytics, SOA generation, and reconnection remain responsive; and
6. any staging load test uses synthetic data and records its capacity boundary.

The production gate establishes current single-request health.  It does not by
itself certify a claimed concurrent-user capacity.
