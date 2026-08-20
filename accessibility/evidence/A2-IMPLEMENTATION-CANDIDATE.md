# A2 — ARIA error-association recovery receipt

Status: parity-verified runtime recovery at clean Ally commit `f2b4c6e`.

## Recovered behavior

The canonical Ally ARIA validator checks controls marked `aria-invalid="true"`. An `unverified`
WCAG 3.3.1 finding is created when neither `aria-errormessage` nor `aria-describedby` is present,
or when all named targets are missing or contain no text. The evidence records the reference IDs and
resolved text. A valid non-empty error target does not report.

The donor repository remains unchanged and recoverable. A2 does not authorize freezing, retiring,
moving, or deleting WCAG Auditor.

## Authentic parity gate

The suite-owned adapter now:

1. imports WCAG Auditor's real `InputAssistanceRule` from its recorded source checkout;
2. invokes that class to capture the exact JavaScript expression it sends to Playwright;
3. executes the donor expression in the already-installed Playwright Chromium runtime;
4. executes Ally's canonical validator against the same three representative DOM cases;
5. compares captured donor and destination outcomes rather than using expected booleans; and
6. retains source, dependency, command, input, output, failure, and rerun-safety evidence.

The formal receipt is [`A2-WCAG-331-EVIDENCE.json`](A2-WCAG-331-EVIDENCE.json). It records:

- authentic donor source and browser-runtime invocation;
- three matching donor/destination outcomes;
- 6 focused tests, 127 full Ally tests, and 7 full-audit integration tests passing;
- clean source commits and lockfile/tested-file SHA-256 fingerprints for both repositories;
- zero operational errors; and
- a read-only, partial-state-free, rerun-safe recovery boundary.

## Environment boundary

If tsx, npm, or Playwright cannot execute because of socket, browser, or permission restrictions,
the current run is `unverifiable_environment`. It is neither a pass nor a product failure. Nonzero
exits from focused, full-suite, full-audit, donor-source, donor-browser, and destination-evaluation
stages all enter the same operational-error channel. Only an explicit `--record` run may replace the
retained receipt.
