# Original Phase 9 — Production-readiness certification

## Purpose

Original roadmap Phase 9 is the governance and production-readiness closeout.
It introduces no business feature, schema migration, or automatic repair. Its
single command composes the approved Phase 4–8 gates, operations monitoring,
manual acceptance, residual-risk register, maintenance schedule, and final
production scorecard into one privacy-safe report.

## Safety boundary

The Phase 9 runner is read-only except for its JSON report. It does not create
or restore a backup, run a migration, restart a service, register a task,
change credentials, modify certificates, install a release, or write business
data. A failed component blocks certification and names the next controlled
action; it never attempts a repair.

## Consolidated automated controls

The runner requires all of these components to pass:

1. Immutable tagged source, dependency locks, release controls, manifest,
   CycloneDX SBOM, desktop trust boundary, client identity, and either valid
   signatures or the active internal-only risk record.
2. Database readiness, registered migrations, financial invariants, audit
   chain, protected backup readiness, API readiness, job queue, and supervised
   runtime.
3. Phase 6 financial reconciliation, including billing/allocation agreement,
   receipt/payment integrity, and complete approval evidence for every active
   duplicate-TD group.
4. Phase 7 critical-screen query thresholds, authenticated API latency,
   database-pool policy, and bounded client timeouts.
5. Phase 8 syntax, keyboard navigation, visible focus, accessible control
   labels, authoritative client version, and WCAG contrast thresholds.
6. Daily backup scheduling, certificate renewal window, free storage,
   operations-health status, the SYSTEM-owned daily health task, a successful
   scheduler smoke run, report retention, and valid local alert state.

External notifications remain disabled. The approved control is local
privacy-safe alert state plus documented same-day or immediate operator
escalation. Adding email, SMS, Teams, or another destination requires separate
privacy, credential, ownership, and delivery-failure approval.

## Automated preflight

Run from an Administrator Command Prompt on the active server. For the current
unsigned internal release, provide the exact staged distribution and accepted
risk record:

```bat
cd /d C:\mto
call venv\Scripts\activate
python -m scripts.phase9_production_readiness_certification --preflight --distribution C:\ProgramData\MTO\releases\vX.Y.Z --distribution-scope internal-municipal --risk-acceptance C:\mto\governance\accepted-risks\original-phase-5-unsigned-internal-only.json --output logs\remediation-original-phase-9-preflight.json
echo Exit code: %ERRORLEVEL%
```

`READY_FOR_MANUAL_ACCEPTANCE` means all automated gates passed. `FAIL` means
the report must be preserved and the named control corrected under its own
safe procedure.

## Manual acceptance record

Final certification requires explicit confirmation of four evidence groups:

1. Desktop workflows: login, logout, reopen, search, ledger, duplicate-TD
   isolation, and one PDF/report workflow.
2. Update delivery and reconnection: immutable server activation, full client
   installation, API restart, and client reconnection.
3. Recovery: a verified backup restored into an isolated database without
   replacing production, with checksum and integrity verification.
4. Operations ownership: named operators accept the maintenance and escalation
   schedule below.

The switches are attestations, not test bypasses. Use them only when the
corresponding evidence was actually reviewed.

## Final certification

After automated preflight and the four manual evidence groups pass:

```bat
python -m scripts.phase9_production_readiness_certification --final --distribution C:\ProgramData\MTO\releases\vX.Y.Z --distribution-scope internal-municipal --risk-acceptance C:\mto\governance\accepted-risks\original-phase-5-unsigned-internal-only.json --confirm-desktop-workflows --confirm-update-and-reconnection --confirm-isolated-restore-drill --confirm-operations-ownership --output logs\remediation-original-phase-9-final.json
echo Exit code: %ERRORLEVEL%
```

The only successful unsigned result is
`PASS_WITH_ACCEPTED_RISK` and the decision
`CERTIFIED_FOR_CONTROLLED_INTERNAL_MUNICIPAL_USE`. Public distribution remains
prohibited.

## Accepted residual-risk register

The certification report includes the active governance record for the
unsigned executable and installer. It records the risk ID, effective and review
dates, internal-only scope, compensating-control count, waived finding, and
restriction without copying personal approval data or secrets. Expiry or a
control mismatch blocks certification automatically.

No other finding is silently accepted. A new residual risk requires its own
time-bounded governance record and code-level validation before it can affect
the certification outcome.

## Maintenance and escalation schedule

- Daily — System Administrator: health report, supervisor/readiness, backup,
  failed jobs, storage, and immediate review of any FAIL.
- Weekly — System Administrator and service owner: report trends, latency,
  failed authentication, privileged events, and source identity.
- Monthly — Administrator, maintainer, and Municipal Treasurer: security
  updates, access review, certificate window, availability, and incidents.
- Quarterly — Service owner and independent reviewer: fresh hybrid backup,
  isolated restore drill, restored financial/audit verification, and incident
  tabletop.
- Annually — Municipality and independent assessor: penetration test,
  credential/signing lifecycle, certificate/CA lifecycle, records retention,
  and recertification.

Critical escalation includes any financial invariant, audit-chain failure,
stale or unverified backup, TLS identity failure, suspected credential
compromise, database corruption, or unexplained financial change. Preserve
evidence and do not repair or restore without a separately controlled action.

## Closure

Original Phase 9 closes only when the consolidated automated score is complete,
all manual controls are confirmed, the residual-risk register contains no
unapproved risk, and the final report returns exit code `0`. Subsequent work is
routine maintenance or a separately approved product change, not another
original remediation phase.
