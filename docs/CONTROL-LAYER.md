# Find, choose, and resume

The local Toolbench opens on **Your projects & Now**. Start it with `./s serve` and
open <http://127.0.0.1:8383>. Existing `suites` commands also work; `./s` is a
checkout-local shortcut and installs nothing.

| Need | Short command |
|---|---|
| Find a project | `./s p carmen` |
| See its return point | `./s project carmen` |
| Choose it for Now | `./s n carmen` |
| See the chosen order | `./s n` |
| Resume one bounded operator action | `./s a` |
| Inspect its target | `./s r carmen` |
| Deliberately open a verified document or folder | `./s r carmen --open` |
| See release work and dependency gates | `./s next` |

Names resolve by exact identity, app label, unique basename, or unique prefix.
Ambiguous names are refused with the choices shown. `carmen` resolves to
`nonsense/carmen`; differently located `joe` and `joe-site` remain different works.
Use `./s p --home independent` to find Independent Projects. The eight stable IDs
remain unchanged. The home names come from the shared catalog projection used by
both interfaces.

No attention state or priority is inferred from activity. The initial reconciliation
left every project unassigned. Choose **Now**, **In use**, **Waiting**, or **Parked** in
a project's details and choose **Save return point**. Now holds at most three projects;
selecting position 1, 2, or 3 reorders the others. Leaving Now closes the gap. Waiting
requires an observable trigger. Nothing automatically promotes a Waiting project.

A bounded return point can be saved in one invocation:

```sh
./s project carmen --attention now \
  --next 'Review one clue path.' \
  --done 'One clue path checked and a restart note saved.'
```

That is an example, not a selection made for Ryan. The same fields are editable in
the web form, with visible labels and large controls. Blank text is stored as an
explicit unknown. Unknown action, stopping point, or resume target remains visible;
`action` does not skip the first Now choice to invent other work. It returns exit 2
when that action is incomplete or no project is selected. Waiting and Parked records
remain searchable, and never erase obligations or imply retirement.

Use `--attention in-use`, `--attention parked`, or `--attention unassigned` to change
attention. `--attention waiting --trigger 'The named prerequisite arrives.'` records
a pause. `--note` records what to remember. No note is required before stopping.
The saved return record is already durable after a successful save.

## Resume and interruption behavior

Resume targets are existing local documents or directories, HTTP(S) links, or
commands displayed for deliberate use in the project's own terminal. The default
reconciliation selects a source README or another existing entry document, falling
back to the project directory. It does not claim that a launcher or service ran.

```sh
./s project carmen --resume README.md
./s project carmen --kind command --resume './existing-local-launcher'
```

Local targets must stay inside the owning canonical project path. A file's saved
SHA-256 is checked again before opening; changed, missing, unreadable, redirected,
and unsupported targets remain visible and cannot be auto-opened. Review the current
source and save the target again to refresh its observation. Changing attention
alone never refreshes a stale target. The web form includes an explicit checkbox
for refreshing an observation after review. Commands are never executed by the
control layer. Links are opened by the browser only after a click and remain labelled
unverified; no network availability test is performed. OS-open success only means
the request was handed to the opener. The saved hash is checked immediately before the
hand-off, but the opener receives a path, so a file replaced in that instant is not caught;
this is an accepted single-user limit, not a guarantee.

Saved records live in `portfolio/project-ledger.json`, so CLI and Toolbench share
them across process restarts. Writes use the existing sidecar lock and atomic,
content-checked replacement primitive. Record revisions prevent a stale web session
from overwriting newer work; CLI callers can supply `--revision` for the same check.
Concurrent Now selections enforce the ceiling under the same ledger lock.
A failed durability confirmation is reported separately from a refused save.

`./s state backup` preserves the saved return fields in a private local backup.
`./s state restore BACKUP.json` previews a restore; adding `--apply` first preserves
an undo backup, then restores only operator fields with fresh revisions. Release
evidence, approvals, and source fingerprints are outside this operation. See
[the recovery and compatibility boundary](PLATFORM-OPERATIONS.md).

The form pauses editing while a save is pending and enables it again after
success or failure. A successful response clears only the submitted draft; a newer
draft written by another browser tab is preserved.

Unsaved form edits are retained in this browser's local storage. A refresh restores
the draft and its original record revision. If another session changed the record,
the stale draft is shown with an explicit conflict and cannot overwrite it. Copy any
needed wording, discard the draft, and reload. Draft storage is best effort; the
interface reports when it is unavailable. Saved ledger records are the durable source.
Nothing promises to recover an unsaved chat or browser edits made before the input
handler ran.

The interface needs the local server, but no internet connection or remote assets.
Stopping the server leaves already loaded records visible and reports failed reads
or saves; restart it and reload. A completely new browser load while the server is
down cannot load the app. Larger text is remembered locally. Project links survive a
reload, keyboard activation returns focus to the project heading or search field,
and the layout reflows on narrow screens. Browser checks are not assistive-technology
or personal-use acceptance.

## Catalog ownership and compatibility

The owning ledger keeps its existing schema version and dated `projects` migration
inventory. Each existing row gains an `operator` record at version `1.0.0`.
`catalog_additions` in **the same file** owns only newly cataloged identities; no entry
is repeated in both arrays. `catalog.py` projects both into one catalog. Existing
migration APIs, fingerprints, disposition fields, suite manifests, and v1 obligations
keep their meaning. New records have `disposition: catalog-only` and
`migration: not-enrolled`. A catalog home can differ from an existing migration
relationship, which is retained and shown separately.

The ledger's `catalog` metadata records scope, the dated app observation, home labels,
Now ceiling, and unresolved identities. App entries are aliases/references to a
canonical project, or explicitly unresolved entries. `Projects` is a workspace
container shortcut. A cloud app project without a filesystem identity does not
become a guessed local project. The nested-repository ledger retains its historical
classification and adds `catalog_project` references; operator state stays at the
canonical project record.

**Reconciliation observation, October 5, 2026:** 70 original ledger rows preserved;
67 catalog additions; 81 app entries mapped or accounted for. These are different
inventory units, not interchangeable project counts. Scope covered existing ledger
and nested entries, non-hidden top-level project directories, direct `nonsense` and
`vaults` children, the separately named Cyborg works, available app entries, and Git
markers through depth five while pruning hidden/generated/vendor trees. Explicit
historical nested paths were included even outside that census scope. No donor
content, app-sidebar placement, or runtime enrollment was changed.

Unresolved entries include the missing `untitled folder`, empty/unclear directories,
a missing saved curriculum shortcut, and cloud project entries without local paths.
Similar names at different locations retain separate identities. Some records have
unknown purpose or next action; that uncertainty is visible in project details.
Source paths, observation dates, and content hashes retain provenance without
copying donor content. Full donor drift still requires a deliberate live scan.

Read-only catalog endpoints: `GET /api/catalog`, `GET /api/catalog/project?name=…`,
and `GET /api/catalog/release`. Explicit writes use `POST /api/catalog/update` with
`name`, integer `revision`, and an allowlisted `changes` object. `POST /api/catalog/open`
requires the current revision and accepts only the saved verified target. Loopback
Host and same-origin mutation checks apply. Neither endpoint accepts release,
disposition, enrollment, or approval changes. `validate --fast` validates the
versioned operator records without launching donor runtimes.

Release state is resolved from the existing release ledger and recovery program.
The web return view shows unresolved release blockers even for Parked work, and
project details show the retained migration relationship, manifest evidence claims,
and suite release lifecycle. Catalog-only projects receive no invented release
phase. Missing release data is reported as unavailable, independently of whether the
catalog can load. `next` continues to select release/migration work; `action` selects
operator work.

## Focused verification and remaining acceptance

Engineering observations on October 5, 2026:

- The versioned catalog passed `./s validate --fast` with no errors or warnings.
- 34 focused checks passed: 18 catalog/state/API/inventory tests, 5 release CLI checks,
  3 existing CLI checks, 3 web markup/security checks, 4 operating-document checks,
  and the CI module-coverage check. Both JavaScript files passed syntax checking.
  The state tests cover saved-record persistence in a fresh process, the Now ceiling
  and ordering, Waiting triggers, concurrent writers, stale revision conflicts,
  interrupted writes, commit uncertainty, malformed edits, and target freshness and
  confinement. API checks use a temporary ledger and verify shared persistence,
  cross-origin refusal, and separation from release/disposition changes.
- Chromium checks exercised the actual form against an isolated four-project fixture:
  save a Now action and stopping point, reload, preserve a conflicting browser draft,
  and move to Waiting with its required trigger. The real catalog remained unassigned.
- The real catalog rendered at 320 px and 390 px without horizontal overflow with the
  larger-text setting. Form fields had labels, project links and Back worked by
  keyboard, drafts survived reload, and missing or changed targets exposed no Open button.
- Stopping the local server preserved the loaded list and displayed a service error;
  release status became unavailable rather than implying completion. No donor runtime,
  external AI call, full test suite, or live portfolio Git scan was run.

These are deterministic and browser engineering checks. **Ryan's actual resumption
acceptance is pending.** They do not prove suite adoption, runtime parity, assistive-
technology support, or readiness for the eight-suite v1 release.

The smallest real-use walkthrough:

1. Open Your projects and choose one project you actually want to return to. Select
   Now, save one next action and a stopping point, and deliberately open its target.
2. Stop normally whenever needed. Later return with `./s a` or the same browser link.
   Check whether the saved record is sufficient to continue without reconstructing context.
3. Choose In use, Waiting with a trigger, or Parked when appropriate. Record a short
   actual observation only if useful: what resumed, what was missing, and whether the
   return was acceptable. An assistant can save that note after Ryan reports it.

Repeat with a small practical improvement and an optional creative project when
Ryan chooses those uses. Three Now slots are never a quota. Until Ryan reports the
actual interruption and return, C3 personal acceptance remains open; no synthetic
fixture result fills it in.
