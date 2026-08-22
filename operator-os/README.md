# Low-Bandwidth Knowledge and Operations OS

Promise: preserve context and expose the next safe action when bandwidth is low.

The architecture is layered: `dotfiles` owns capture/control and daily commands; PKOS owns
immutable acquisition, provenance, normalization, search, and recovery; Obsidian Observer owns the
derived vault projection; JARVIS owns the accessible interaction surface; `vaults/ai-vault` is an
instance/corpus. No interface may invent another canonical store.

Verified: O1, O2 (2/6). O1 proved a single `SourceRecord` path from `dotfiles` capture into
authentic PKos content-addressed storage, SQLite normalization, and a fenced Observer projection
that refuses re-ingestion. O2 inventoried `ryos` and `master-upgrade-plan` against current
`dotfiles`/Observer state. Both are analysis milestones; their runtime follow-ups (real daily
intake volume, executed ports) remain outstanding.

Next wave: O3 — model a JARVIS action preview receipt with an approval boundary in the
suite-local engine — dry-run only, against a fingerprinted JARVIS source.

