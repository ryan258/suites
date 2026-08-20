# A1 — WCAG Auditor to Ally parity decision

Snapshot: 2026-08-19, source-only review. No source repository was modified.

## Outcome

WCAG Auditor should not be merged as a second scanner or report lifecycle. Ally already has the
stronger canonical finding identity, error channel, exact producer/page coverage, full-audit proof
manifest, human-gated fixes, reporting, tickets, VPAT workflow, and coverage-aware regression
history. WCAG Auditor remains a donor until its useful behavior is either ported or explicitly
rejected.

Of WCAG Auditor's **34 registered rules**:

- 15 are already covered by axe-core, Ally's dynamic keyboard tester, or Ally's ARIA validator;
- 18 contain a potentially useful heuristic or interaction that must enter Ally as an explicit
  `needs-review` or narrowly justified deterministic finding—never as an automatic conformance
  claim; and
- 1 (`autofocus-inputs`) is rejected as a WCAG failure because `autofocus` by itself does not prove
  a 2.4.3 violation. It may survive only as optional advisory lint.

The donor also has meaningful crawl/workflow features not present in Ally: authenticated storage
state, depth bounds, include/exclude filters, configurable user agent/delay, representative template
sampling, SPA route hints beyond anchors, and a WCAG-EM-style scope/sample summary. Those are
separable options around Ally's existing crawler; they do not justify preserving another finding or
report model.

## Source fingerprints and preservation boundary

| Source | Fingerprint | Working tree at snapshot | Boundary |
|---|---|---|---|
| `allys-tools` | `main@87f21ba` | one untracked `.DS_Store` | Canonical destination; do not overwrite or absorb unrelated local state. |
| `wcag-auditor` | `main@ec899a3` | clean | Donor; no deletion or retirement until all accepted rows below have parity evidence. |

The donor README claims 34 active rules and the registration function in
`wcag_auditor/rules/core_rules.py` registers exactly 34. `MissingAltTextRule` exists in source but is
not registered; `ComplexAltTextRule` is the active replacement. It is not counted as a migration
item.

## Rule-by-rule decision

Status vocabulary:

- **covered** — retain Ally behavior and add a regression comparison only if source outputs differ.
- **port-review** — port only as `needs-review`; the donor logic is heuristic or presence-only.
- **port-narrow** — eligible for an `unverified` deterministic finding if the fixture proves the
  exact DOM condition without implying broader conformance.
- **reject** — do not port as a WCAG failure.

| Donor rule | SC | Decision | Ally owner | Parity basis / required fixture |
|---|---:|---|---|---|
| `missing-labels` | 3.3.2 | covered | page-scanner | axe `label`, `select-name`, and ARIA name rules; compare unlabeled native and ARIA controls. |
| `missing-lang` | 3.1.1 | covered | page-scanner | axe `html-has-lang`, `html-lang-valid`, and mismatch rules are broader. |
| `inline-language-change` | 3.1.2 | port-review | page-scanner extension | axe validates declared `lang` but cannot prove an undeclared language change; multilingual fixture must stay review-only. |
| `empty-links` | 2.4.4 | covered | page-scanner | axe `link-name`/`area-alt` cover programmatic names. |
| `empty-buttons` | 4.1.2 | covered | page-scanner | axe `button-name`, `input-button-name`, and ARIA command-name rules. |
| `missing-title` | 2.4.2 | covered | page-scanner | axe `document-title`. |
| `autofocus-inputs` | 2.4.3 | reject | none / optional lint | Attribute presence is not proof of bad focus order; only keep as advisory if a real workflow needs it. |
| `complex-alt-text` | 1.1.1 | covered | page-scanner + alt-text-writer | axe covers image/SVG/role/input/object alternatives; Ally's writer is gated review, not evidence of conformance. |
| `time-based-media` | 1.2.2 | covered | page-scanner | axe `video-caption`; retain manual review of caption quality. |
| `audio-description-track` | 1.2.5 | port-review | page-scanner extension | Track/alternative presence can be observed; adequacy and applicability require human review. |
| `adaptable-landmarks` | 1.3.1 | port-review | page-scanner extension | A missing `main` is useful structural guidance but not a complete 1.3.1 determination. |
| `reading-sequence` | 1.3.2 | covered | keyboard-tester | Ally already reports positive `tabindex` and measures reached order; donor criterion mapping is less precise. |
| `contrast-minimum` | 1.4.3 | covered | page-scanner + palette-checker | axe handles rendered text contrast; ChromaCheck handles palette evidence. |
| `focus-appearance` | 2.4.7 | covered | keyboard-tester | Ally compares focused/unfocused pixels for real tabbable elements. |
| `keyboard-accessibility` | 2.1.1 | covered | keyboard-tester | Ally performs sequential keyboard traversal; donor mostly infers from markup/handlers. |
| `keyboard-trap` | 2.1.2 | covered | keyboard-tester | Ally tests repeated Tab and reverse escape; donor's markup heuristic is weaker. |
| `enough-time-controls` | 2.2.2 | port-review | page-scanner extension | axe covers blink/marquee; custom carousel/auto-update inference must remain review-only. |
| `navigable-skip-links` | 2.4.1 | covered | page-scanner | axe `bypass`. |
| `link-purpose` | 2.4.4 | port-review | page-scanner extension | Vague-text terms are language/context heuristics; useful queue, not confirmed failure. |
| `focus-not-obscured` | 2.4.11 | port-review | keyboard-tester | Requires focus/viewport/overlay interaction; static sticky-chrome inference cannot be confirmed evidence. |
| `pointer-gestures` | 2.5.1 | port-review | page-scanner extension | Event/data-attribute inference cannot prove the lack of a single-pointer alternative. |
| `pointer-cancellation` | 2.5.2 | port-review | page-scanner extension | Handler-name inference cannot prove behavior; dynamic test design is required. |
| `dragging-movements` | 2.5.7 | port-review | page-scanner extension | `draggable`/drag handlers identify candidates, not absence of alternatives. |
| `target-size-minimum` | 2.5.8 | covered | page-scanner | axe `target-size` is run under the WCAG 2.2 AA tags. |
| `predictable-navigation` | 3.2.2 | port-review | page-scanner extension | `onchange`/navigation-like controls are candidates; only interaction proves an unexpected context change. |
| `input-assistance-error-msg` | 3.3.1 | port-narrow | aria-validator extension | `aria-invalid=true` with no valid error/description target is a precise DOM defect; do not claim all error behavior was tested. |
| `labels-or-instructions` | 3.3.2 | port-review | page-scanner extension | Constraint presence plus absent helper text is useful but context/language dependent. |
| `error-suggestion` | 3.3.3 | port-review | page-scanner extension | Donor language terms cannot establish whether a correction is possible or adequate. |
| `required-field-indicators` | 3.3.2 | port-review | page-scanner extension | Visible indication is language/context dependent; preserve the review label. |
| `redundant-entry` | 3.3.7 | port-review | page-scanner extension | Similar names/fields do not prove repeated information or an unavailable exception. |
| `accessible-authentication` | 3.3.8 | port-review | keyboard/interaction extension | CAPTCHA, paste blocking, password-manager, and alternative-method behavior require interaction and human judgment. |
| `identify-input-purpose` | 1.3.5 | port-review | page-scanner extension | Missing autocomplete on inferred personal-data fields is useful, but field purpose inference is fallible. |
| `aria-validation` | 4.1.2 | covered | aria-validator | Ally uses `aria-query`, validates role/property support, required relationships, values, and ID references. |
| `status-messages` | 4.1.3 | port-review | aria-validator extension | Status-like class/text inference finds candidates; behavior and notification without focus require review/AT evidence. |

## Crawl and sampling decision

| Donor behavior | Current Ally state | Decision | Target |
|---|---|---|---|
| Same-origin live crawl | Present, concurrent, with sitemap discovery and canonical URLs | retain Ally | page-scanner |
| `max_pages` | Present | retain Ally | page-scanner |
| depth bound | Not exposed | port optional `maxDepth` | page-scanner crawl options |
| robots.txt | Present, with explicit skipped URLs | retain Ally | shared browser + manifest |
| sitemap discovery | Ally is stronger | retain Ally | shared browser |
| custom user agent | Not exposed in crawl API | port optional value | shared browser context and robots evaluation |
| authenticated Playwright storage state | Not exposed | port with credential/path safety checks | full-audit/page-scanner options |
| repeatable include/exclude URL filters | Not exposed | port as validated patterns | page-scanner queue |
| polite delay | Not exposed | port optional delay | page-scanner worker scheduling |
| sequential/representative strategy | Ally currently queue/sitemap driven | port representative selection as report metadata, not silent coverage reduction | page-scanner crawl artifact |
| SPA hints (`data-href`, `data-route`, `routerlink`, hash routes, `xlink:href`) | Anchor discovery exists; sitemap also helps | port safe same-origin hints | shared browser discovery |
| per-rule finding cap/truncation | Not exposed | do not suppress canonical findings; add report grouping/capping only | report presentation |
| page templates/types and sample summary | Exact successful URLs exist, but no WCAG-EM-style summary | port derived summary | report/manifest, explicitly non-conformance |
| failed page behavior | Typed `A11yScanError` and exact successful coverage | retain Ally; donor warning model is weaker | finding contract |

Authenticated state is sensitive: the option may consume a user-supplied Playwright storage-state
file but must never copy it into audit output, manifests, fixtures, logs, or source control.

## Finding contract decision

Do not import WCAG Auditor's unversioned dictionaries. Accepted donor rules must produce Ally's
existing `A11yFinding` through `createFinding`:

- stable finding identity version and deterministic ID;
- canonical safe HTTP(S) URL;
- shared selector dialect;
- supported WCAG success criterion;
- explicit severity and `unverified`/`needs-review` status;
- structured evidence; and
- operational failures in `A11yScanError`, never disguised as findings.

The suite-level `A11yFinding` schema in this clean workspace is an interchange envelope. Ally's
internal Zod contract remains the authoritative, stricter implementation until a real second
consumer proves a lossless adapter.

## Deliverable and workflow decision

| Donor surface | Ally equivalent | Decision |
|---|---|---|
| JSON results | schema-valid findings + manifest | retain Ally |
| Markdown/HTML report | report-generator Markdown/HTML/PDF | retain Ally |
| text summary | CLI summaries and manifest | retain Ally; add no second report renderer |
| VPAT 2.5 | full A/AA draft with named-expert export gate | retain Ally; donor ungated VPAT must not replace it |
| baseline suppression | coverage-aware regression watcher | retain Ally; donor fingerprint suppression is weaker |
| SARIF | no full-audit SARIF artifact observed | candidate adapter after A2 only if a real CI consumer exists |
| configurable fail threshold | narrow tool exit codes exist | candidate suite gate, but preserve scan-error exit 2 and explicit coverage |
| WCAG-EM scope/sample metadata | exact coverage exists but no concise methodology block | port derived, explicitly non-certifying summary |
| synthetic screen-reader/cognitive/copywriter pass | screen-reader sim, cognitive scorer, rewriter, visual reviewer | reject duplicate provider/persona lifecycle; retain Ally's labeled review queues |
| remediation snippets | suggested fixes + human-gated fix plan | port only useful snippets through source-aware dry-run proposals |
| always save another Markdown report | versioned audit destination already owns artifacts | reject hidden duplicate output |

## A2 implementation order

The first code migration should be the narrow deterministic 3.3.1 condition:

1. add a fixture for `aria-invalid=true` with missing/broken error references;
2. implement it in Ally's ARIA validator using `createFinding`;
3. prove valid references do not report;
4. prove malformed operational state stays in the error channel;
5. run focused tests and the current full Ally gate; and
6. record output parity against the donor fixture without changing WCAG Auditor.

After that, port crawl options independently. Heuristic rules should be grouped behind one explicit
review-candidate producer rather than creating 17 unrelated pseudo-conformance checks.

## Retirement gate

WCAG Auditor is not ready to retire. Retirement requires accepted rule fixtures, crawl-option
parity, any approved SARIF/WCAG-EM adapter, output migration guidance, clean source reconciliation,
and an owner decision about repository archival. Passing Ally tests alone is insufficient.

