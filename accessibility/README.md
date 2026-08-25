# Accessibility Suite

Promise: find, explain, repair, teach, and track accessibility without overstating evidence.

`allys-tools` owns the audit and evidence lifecycle. A11y Kitchen owns interactive teaching;
A11y Lab owns reference and curriculum; `kb-overlay` owns browser assistance. ChromaCheck remains
an adapter where separate versioning helps. WCAG Auditor and the older overlays are donors until
feature/parity reviews prove what should be ported.

The suite is complete only when the shared `A11yFinding` round-trips across audit, learning, and
browser surfaces; all fifteen Ally tools remain honestly represented in the proof manifest; the
overlay duplicates are reconciled; and automated evidence remains distinct from manual AT review.

Wave A1 is a reviewed, hand-authored analysis, retained as a structured receipt: [the parity
decision](evidence/A1-WCAG-AUDITOR-PARITY.json), whose `projection_markdown` field carries the
prose verbatim. Its required structure is checked, but the runner does
not execute a donor or runtime gate. The document records 34 registered donor rules: 15 covered, 18
heuristic/narrow port candidates, and one rejected as a standalone WCAG failure. A2 subsequently
ported the narrow `aria-invalid` error-association check into Ally's ARIA validator with regression
and full-suite evidence. A3 compared the three keyboard overlays and retained a canonical-anchor
recommendation without freezing donors or consolidating runtimes, while A4 evaluated 20 candidate
WCAG Auditor rules against live donor rule ASTs with zero false positives on compliant markup —
both as analysis milestones whose runtime follow-ups remain outstanding.

Verified: A1, A2, A3, A4, A5, A6 (6/6). All wave milestones verified.
