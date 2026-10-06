# Local platform checks and recovery

The canonical installation model is a **source workspace**, optionally driven by an
installed wheel whose `SUITES_ROOT` points to that workspace. Projects keep their
own launchers and state. A wheel does not contain the private portfolio or create a
second copy of its ledgers. An installed command without a valid workspace fails
with a setup instruction.

## Short commands

| Need | Command | Effect |
|---|---|---|
| Inspect local prerequisites | `./s doctor` | Offline presence/capability checks only |
| Inspect the release queue | `./s release blockers --json` | Includes recovery-program requirements and dependencies |
| Identify source for review | `./s release candidate` | Read-only source digest |
| Retain the complete digest inventory | `./s release candidate --json` | JSON on stdout; redirect outside the source tree |
| Back up return points | `./s state backup` | Creates a private local backup and prints its name |
| Preview the latest backup | `./s state restore` | No filename or retyping required |
| Preview a restore | `./s state restore BACKUP.json` | Lists changed identities without modifying the ledger |
| Apply that restore | `./s state restore BACKUP.json --apply` | Saves an undo backup, then atomically replaces operator fields |

The first four commands do not run donors, contact providers, install dependencies,
record milestone evidence, or confer approval. JSON release inspection returns exit
2 while release work remains. Candidate and doctor return 0 for a complete source
observation or available required local prerequisites respectively, otherwise 2.
Neither success means the suites have passed runtime or release verification.

## Source identity

`portfolio-source-candidate-v1` binds HEAD, the staged index's object IDs and modes,
all tracked working-tree bytes/deletions/modes, and non-ignored untracked source
bytes. Two observations must agree. Reads are descriptor-confined and refuse links,
hard links, special files, unreadable content, conflicts, and changing observations.
The bounded scan refuses more than 20,000 inventory entries, a 100 MiB file, or
512 MiB of source bytes. Incomplete observations return no candidate digest.

Ignored runtime state, build products, and `.git` metadata are outside this source
identity. The Git ignore policy, including configured global excludes, determines
that scope. The reviewed, tracked root `.env.example` is source; credential-shaped
files otherwise prevent complete identification. Reports contain hashes and source
paths, never file contents. Review them locally before sharing source-path metadata.
Record artifact and runtime-state hashes separately when verifying a release.

This is a drift detector, not an atomic filesystem snapshot. Quiesce writers and
compare it again after verification. Saving a report inside a non-ignored source
directory changes the candidate; write reports outside the checkout. A dirty
candidate can be reviewed, but this command never stages, commits, or approves it.

## Return-point backup and rollback

Backups live under `operator-os/state/control-layer/`, already excluded from Git.
They have private file permissions, exclusive filenames, a schema version and a
SHA-256 over the payload. They contain local project names/paths and operator notes;
they are private working data rather than release receipts.

Only `purpose`, `resume`, `attention`, `now_order`, `next_action`, `waiting_trigger`,
`done_for_now`, and `restart_note` are restored. Canonical identities, owner,
location, and operator-schema versions must still match. New or removed projects,
unknown versions, corrupted checksums, invalid Now order/ceiling, or a Waiting
record without a trigger are refused. Identity changes need deliberate reconciliation;
the restore does not guess a migration.

Current release dispositions, source fingerprints, evidence, approvals, and catalog
relationships survive unchanged. Live revisions increase so stale browser drafts
cannot overwrite restored data. Restoring a saved resume observation does not update
its hash; changed targets remain visibly changed. Browser drafts are not backed up.

Every applied restore first saves the current return points as an undo backup. Use
that printed filename with the same preview/apply commands to reverse the restore.
Omitting the filename (or using `latest`) selects the most recently modified valid
backup filename. The preview prints the selected file. Use its exact name when you
need a particular earlier snapshot; an applied restore's undo backup becomes latest.
The existing sidecar lock serializes cooperating writers; compare-and-swap protects
against an outside replacement. A conflict reports refusal. A failure after the
commit point reports `committed_unverified` and the undo filename; reload and inspect
the ledger before retrying. Keep the backup until durability and the resulting state
are verified. No restore auto-opens a target or invokes a launcher.

## Compatibility boundary

The CLI/API surface, exit codes, and error categories are governed separately by
[the stable-surface policy](STABLE-SURFACE.md).

| Persisted surface | Current reader/boundary | Compatibility behavior |
|---|---|---|
| Six shared contracts | `contracts/*.schema.json`, `contracts.py` | Existing required fields and semantic validation remain authoritative. Samples: `./s contract NAME sample`; validation: `./s contract NAME validate FILE`. |
| Project ledger | Existing ledger plus catalog/operator `1.0.0` | Legacy migration consumers retain `projects`; absent catalog requires reconciliation before operator use. |
| Return-point backup | `portfolio-operator-backup-v1` | Current-version restore only; unknown/partial versions are refused with original backup preserved. |
| Approval authority | `operator-approval-v1`, out-of-band store | Never copied or restored by return-point recovery. Single-use consumption is not rolled back. |
| Runtime and lifecycle evidence | Receipt-specific versions in `receipts.py` and `recovery_program.py` | Existing validators govern retained evidence; local backups cannot promote it. |
| Release completion | `portfolio-release-completion-v1`, schema `1.0.0` | Authored ledger checked against governed policy, criteria and recovery obligations. |
| Browser drafts | Catalog form's versioned local-storage key and saved revision | Best-effort drafts only; durable ledger is authoritative. |

The contract/state freeze now binds format validators and this policy instead of the
changing project ledger's current values. Saving a return point must not invalidate
an interface freeze. Any format-policy or validator change invalidates its recorded
freeze digest and requires review. CLI/API freeze includes server, catalog, recovery,
candidate, and diagnostic entry points. The freeze remains **open**: narrow producer/consumer proofs exist for `ExperimentRun` (ai-ethics-comparator stats),
`SourceRecord` (PKos CAS acquisition), `A11yFinding` (allys-tools aria-validator), and
`InvestigationRecord` (Forge loading a retained model-driven investigation), and `ProductionJob`
(Production House's engine running its Groundwire tasks on a private temp state; `filelock` is
stubbed when not installed and the probe reports it); each runs the
donor out of process, recomputes donor claims host-side, and validates in a separate consumer
process (`tests/test_donor_*_probe.py`). They map donor output to the contract in this repository,
so they show the mapping is accepted, not that the donor emits the contract natively.
`BrandPackage` is unproven; `BrandPackage` needs a
real owner-approved brand and no fixture substitutes for that approval. Migration fixtures for
every retained prerelease format are supplied only as inventoried below. Migration inventory (October 5, 2026): the only retained
pre-v1 state shape is the project ledger before the catalog extension (`projects` only, as
committed in `5e64694`); `tests/fixtures/legacy-project-ledger-5e64694.json` proves it stays
readable and is refused for operator use until reconciled. The other persisted formats
(return-point backup, release ledger, recovery program, execution trace, approvals) have
exactly one version, so there is no earlier form to fixture; unversioned retained evidence
receipts remain governed by their wave-specific validators. The focused return-point rollback drill is narrower than
a complete platform upgrade/rollback acceptance.

## Environment and distribution

Python 3.11+ is declared in `pyproject.toml`. POSIX descriptor/locking operations are
required. The October 5, 2026 focused checks ran on macOS with Python 3.14.7. The hermetic CI job is
configured for Linux Python 3.11 (the declared floor) and 3.12, and macOS Python 3.14; its first results
are not yet recorded, so this is not a completed support matrix.
Other Python/OS combinations, donor Node versions, and assistive-technology/browser
combinations still need the roadmap's clean-install and real-use evidence.

`SUITES_ROOT` overrides workspace discovery. `PORTFOLIO_OPERATOR_APPROVAL_STORE`
selects out-of-band authority and is never printed by doctor. Provider settings are
documented in the root `.env.example`; local `.env`/environment settings are handled
by the existing AI boundary. Optional providers are unnecessary for catalog,
validation, diagnostics, candidate inspection, and return-point recovery. Missing
provider configuration does not make those paths unavailable.

`doctor` reports executable presence, package assets, ownership/permission metadata,
and installed build-prerequisite presence; it does not execute version probes or
read credentials. Permission metadata cannot prove durable writes. Donor environments
and receipt requirements come from `release blockers --json`, with acceptance still
owned by the recovery program.

The opt-in wheel smoke gate now uses `--no-index --no-build-isolation --no-deps` for
building and an offline fresh-venv install. The invoking interpreter must already have
pip, setuptools >=68, and wheel. Missing build tools are a prerequisite failure,
never an invitation to fetch them implicitly. The gate checks `catalog.js` alongside
the other web/probe assets. Ryan runs this heavier gate after provisioning a suitable
interpreter; no wheel, sdist, clean-install matrix, or distribution is claimed from
the focused local checks.

## Remaining release boundaries

The queue covers all governed recovery obligations through Phase 5, including their
freeze and predecessor gates. It does not yet model Phase 6 candidate acceptance,
Phase 7 authorized distribution, or Phase 8 stabilization as executable closure
gates. JSON and Toolbench expose those omissions; release readiness remains withheld.
Scores remain insufficient until the evidence-derived scorer exists and authentic
dimension evidence is available. No process closure, personal acceptance, authentic
runtime/adoption use, or release authorization was manufactured during this work.
