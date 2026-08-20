# Low-Bandwidth Knowledge and Operations OS

Promise: preserve context and expose the next safe action when bandwidth is low.

The architecture is layered: `dotfiles` owns capture/control and daily commands; PKOS owns
immutable acquisition, provenance, normalization, search, and recovery; Obsidian Observer owns the
derived vault projection; JARVIS owns the accessible interaction surface; `vaults/ai-vault` is an
instance/corpus. No interface may invent another canonical store.

First move: define and prove a single `SourceRecord` path from capture through PKOS search to a
derived Observer note, with no re-ingestion loop.

