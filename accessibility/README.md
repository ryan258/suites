# Accessibility Suite

Promise: find, explain, repair, teach, and track accessibility without overstating evidence.

`allys-tools` owns the audit and evidence lifecycle. A11y Kitchen owns interactive teaching;
A11y Lab owns reference and curriculum; `kb-overlay` owns browser assistance. ChromaCheck remains
an adapter where separate versioning helps. WCAG Auditor and the older overlays are donors until
feature/parity reviews prove what should be ported.

The suite is complete only when the shared `A11yFinding` round-trips across audit, learning, and
browser surfaces; all fifteen Ally tools remain honestly represented in the proof manifest; the
overlay duplicates are reconciled; and automated evidence remains distinct from manual AT review.

Wave A1 is complete in [the parity decision](evidence/A1-WCAG-AUDITOR-PARITY.md). It found 34
registered donor rules: 15 covered, 18 heuristic/narrow port candidates, and one rejected as a
standalone WCAG failure. The next move is A2: port the narrow `aria-invalid` error-association check
into Ally's ARIA validator with regression and full-suite evidence.
