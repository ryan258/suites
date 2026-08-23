# Low-Bandwidth Knowledge and Operations OS

Promise: preserve context and expose the next safe action when bandwidth is low.

The architecture is layered: `dotfiles` owns capture/control and daily commands; PKOS owns
immutable acquisition, provenance, normalization, search, and recovery; Obsidian Observer owns the
derived vault projection; JARVIS owns the accessible interaction surface; `vaults/ai-vault` is an
instance/corpus. No interface may invent another canonical store.

The suite-local engine provides four reviewed JARVIS handlers:

- `audit_secrets`: bounded, read-only scanning with sensitive-path and workspace confinement.
- `backup_data`: deterministic, content-addressed ZIP plus an external manifest; dry-run by default.
- `sync_obsidian_notes`: additive UTF-8 Markdown transfer that refuses conflicts and rolls back a
  partially created destination on failure.
- `rotate_local_cache`: an explicit cache-directory-only atomic rename plus empty replacement,
  with the original retained as the recovery source.

Caller booleans can request read-only or dry-run work but never authorize a write. Active mutations
require an independently issued, exact-payload, single-use approval from the configured
`PORTFOLIO_OPERATOR_APPROVAL_STORE`. This repository verifies and consumes those approvals but
cannot mint them.

Verified: O1, O2, O3, O4, O5, O6 (6/6) analysis milestones. Runtime adoption of the donor ports
and real-world JARVIS workflows remains outstanding.
