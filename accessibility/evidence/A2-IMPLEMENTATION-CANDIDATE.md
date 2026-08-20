# A2 — ARIA error-association implementation candidate

Status: implementation and fixture added; runtime verification incomplete.

## Change

The canonical Ally ARIA validator now checks controls marked `aria-invalid="true"`. A 3.3.1
`unverified` finding is created when neither `aria-errormessage` nor `aria-describedby` is present,
or when all named targets are missing or contain no text. The evidence records the reference IDs and
resolved text. A valid non-empty error target does not report.

Files changed in the source anchor:

- `/Users/ryanjohnson/Projects/allys-tools/a11y-tools/aria-validator/index.ts`
- `/Users/ryanjohnson/Projects/allys-tools/a11y-tools/tests/contracts.test.ts`

The pre-existing untracked `.DS_Store` remains untouched. WCAG Auditor remains unchanged.

## Verification

- TypeScript compilation (`tsc --noEmit`, invoked by `npm run check`) passed before the runtime test
  runner attempted to start.
- `git diff --check` passed.
- The new regression covers a valid association, broken ID, empty target, and missing association;
  it also asserts `unverified` status and structured evidence.
- Runtime focused/full tests are **not passed evidence**. `tsx` could not create its local IPC socket
  in the sandbox (`listen EPERM`), and the required approved retry was rejected because execution
  allowance was exhausted until 2026-08-20 01:00 America/Chicago.

## Completion gate

Do not mark A2 complete until the focused contract test and `npm run check` finish successfully in
an environment that permits the runner's local IPC socket. If they fail, repair the candidate and
re-run both. A live browser probe is optional for this snapshot-driven function but desirable before
folding broader dynamic behavior.

