# Original Phase 8 — Code Quality and UI/UX Accessibility Runbook

## Purpose

Original roadmap Phase 8 improves the maintainability and accessibility of the
desktop shell without changing financial calculations, database schema, API
authorization, or production records. The release focuses on shared controls
that affect every operator before broad screen-by-screen refinement.

## Closed findings

The Phase 8 implementation closes these concrete findings:

1. The login footer used a stale hard-coded release version.
2. Password visibility was implemented as a mouse-only icon label.
3. Sidebar actions had no shared tab-order, Enter/Space, or focus-ring policy.
4. Theme and language controls relied on icons instead of visible labels.
5. White active-navigation text did not meet normal-text contrast on sky blue.
6. The Help guide documented a shortcut that was not globally implemented and
   omitted tab, button activation, and F1 guidance.

## Implemented controls

- The visible version comes from `mto_version.PRODUCT_VERSION`.
- Username receives initial keyboard focus on the login screen.
- Password visibility is a labeled Show/Hide button.
- Shared controls enter the Windows tab order, show a yellow focus ring, and
  activate with Enter or Space while respecting disabled state.
- Navigation, theme, language, and logout controls use the shared adapter.
- Active and destructive button surfaces meet WCAG AA normal-text contrast.
- F1 opens the in-application Help guide.
- The Help guide lists only implemented global keyboard behavior.

## Read-only gate

The Phase 8 gate parses the affected Python files, checks source cleanliness,
validates the UI contracts, and calculates WCAG contrast ratios. It imports no
production database code and performs no network, service, schema, or data
operation.

```bat
cd /d C:\mto
call venv\Scripts\activate
python -m scripts.phase8_accessibility_preflight --require-ready --output logs\remediation-original-phase-8-assessment.json
echo Exit code: %ERRORLEVEL%
```

Exit code `0` means all static controls passed. A nonzero result blocks Phase 8
closure until the finding is fixed or separately documented.

## Desktop acceptance

On one approved pilot workstation:

1. Confirm the login footer displays the installed release version.
2. Confirm initial focus is in Username and Tab proceeds through the form.
3. Focus Show/Hide and activate it with both Enter and Space.
4. Log in and use Tab to reach sidebar navigation, Theme, Language, and Logout.
5. Confirm focused buttons show a visible yellow outline.
6. Confirm Enter and Space activate the focused control once.
7. Press F1 and confirm the Help guide opens.
8. Confirm light and dark modes keep labels legible.
9. Complete a property search and open a ledger to verify no workflow regression.

## Closure criteria

Phase 8 closes when the automated gate, full regression suite, immutable release
validation, and desktop acceptance all pass with no accessibility finding.
