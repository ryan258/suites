# 100 Demos

A hundred things to run against the suites control plane, arranged so that each act teaches you
something the next one assumes. Start at 1 if you are new. Jump to Act VIII if you would rather
try to break it, which is the most instructive way to learn what this thing refuses to do.

**Every command here is written out in full**, including `PYTHONPATH=src`, rather than hidden
behind a shell alias. That is deliberate: `tests/test_docs.py` scans this file and fails if it
teaches a subcommand the CLI does not define, and it can only do that if the invocations are
literal. Typos in this file are a test failure, not a surprise at your terminal.

Run everything from the checkout root:

```bash
cd ~/Projects/suites
```

**Safety.** Demos leave your working tree alone unless they carry a **[WRITES]** tag. There are
six of those — 63, 67, 70, 71, 94, and 96 — and each says exactly what it touches and how to undo it.
Demo 96 only removes the `mktemp -d` directory demo 94 created, and refuses to remove anything else.
Scratch files under `/tmp` are used freely and are not tagged. Nothing here stages, commits,
pushes, or publishes anything, and nothing reaches the network except the AI demos in Act VII.

Demo 100 ends by checking `git status` is clean, so you can confirm all of that for yourself
rather than taking this paragraph's word for it.

**Bandwidth.** Every act header carries the cost of running it, so you can match the act to the
day rather than discovering halfway through that it needed a browser and a Node runtime:

- **[LOW BW]** — one-line commands, no setup, no external runtime, each returning in under a
  second. Stop after any demo; nothing is left running.
- **[HIGH BW]** — needs something spun up first (a server, Node + Playwright), a file you
  authored, network access, or a multi-step sequence that has to be held in your head.

Acts tagged **[HIGH BW]** end with a **State safe** block: what is still running or on disk, and
the one command that reorients you when you come back. Low-bandwidth acts do not need one.

---

## Act I — First Contact **[LOW BW]**

You have just cloned a control plane governing eight suites and 43 migration waves. Get oriented.

### 1. Ask what this thing claims to be

```bash
PYTHONPATH=src python3 -m portfolio_suites list
```

Look for: eight suites, each with a one-line promise and a state. The promise is the contract with
yourself; the state is how honest you are being about it today.

### 2. Get the portfolio scoreboard

```bash
PYTHONPATH=src python3 -m portfolio_suites status
```

Look for: completed-wave counts per suite and a retained-evidence health percentage. This is the
number the README and ROADMAP are tested against, so it cannot quietly drift.

### 3. Find out what to do next

```bash
PYTHONPATH=src python3 -m portfolio_suites next
```

Look for: the next incomplete wave in every suite. This is the "I have twenty minutes, what should
I touch" command.

### 4. Inspect a single suite

```bash
PYTHONPATH=src python3 -m portfolio_suites inspect game-design
```

Look for: the suite's promise, its anchor projects, which contracts it speaks, and its members.

### 5. Inspect a project instead of a suite

```bash
PYTHONPATH=src python3 -m portfolio_suites inspect storyweaver
```

Look for: the same command resolves either a suite ID or a project name. One `inspect`, two kinds
of target.

### 6. Validate the whole registry, fast

```bash
PYTHONPATH=src python3 -m portfolio_suites validate --fast
```

Look for: `VALID: 0 error(s), 0 warning(s)` in well under a second. `--fast` skips live git drift,
which is the slow part.

### 7. Validate including live source drift

```bash
PYTHONPATH=src python3 -m portfolio_suites validate
```

Look for: the same verdict, slower, because it now shells out to git across the donor checkouts.
Compare the wall time against demo 6 to feel what `--fast` buys you.

### 8. Get the validation verdict as JSON

```bash
PYTHONPATH=src python3 -m portfolio_suites validate --json --fast
```

Look for: a machine-readable `{"ok": ..., "errors": [...], "warnings": [...]}`. This is what CI
would consume.

### 9. Scan for drift against recorded baselines

```bash
PYTHONPATH=src python3 -m portfolio_suites drift
```

Look for: any donor repository whose working tree has moved since its baseline fingerprint was
recorded. A clean run here means the evidence still describes the code it was taken from.

### 10. Export the entire portfolio as one JSON document

```bash
PYTHONPATH=src python3 -m portfolio_suites export > /tmp/portfolio.json && wc -c /tmp/portfolio.json
```

Look for: a single consolidated document. Everything the dashboard renders comes from this shape.

---

## Act II — The Contract Workbench **[LOW BW]**

Six versioned JSON contracts carry all cross-suite data: `SourceRecord`, `BrandPackage`,
`ProductionJob`, `ExperimentRun`, `InvestigationRecord`, `A11yFinding`. This act is about learning
what they will and will not accept.

### 11. Read a contract's specification

```bash
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord spec
```

Look for: required fields, types, and the published schema keywords the validator enforces.

### 12. Generate a valid sample

```bash
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord sample
```

Look for: a complete, valid instance. Useful as a starting point for anything you hand-write.

### 13. Round-trip a sample through its own validator

```bash
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord sample > /tmp/sr.json && \
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord validate /tmp/sr.json
```

Look for: `VALID`. A generator that emits something its own validator rejects is a bug, and this
one-liner is the check.

### 14. Round-trip all six contracts at once

```bash
for c in SourceRecord BrandPackage ProductionJob ExperimentRun InvestigationRecord A11yFinding; do \
  PYTHONPATH=src python3 -m portfolio_suites contract $c sample > /tmp/$c.json && \
  PYTHONPATH=src python3 -m portfolio_suites contract $c validate /tmp/$c.json; done
```

Look for: six `VALID` lines. This is the fastest whole-contract-layer smoke test there is.

### 15. Break the schema version and watch it refuse

```bash
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord sample \
  | sed 's/"1.0.0"/"9.9.9"/' > /tmp/bad-version.json && \
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord validate /tmp/bad-version.json
```

Look for: a refusal naming `schema_version`. Version pinning is not advisory.

### 16. Feed it a non-finite number

```bash
printf '{"schema_version":"1.0.0","size_bytes":NaN}' > /tmp/nan.json && \
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord validate /tmp/nan.json
```

Look for: a rejection. Python's JSON encoder will happily write `NaN`, which is not valid JSON;
the contract layer refuses it so no receipt can contain one.

### 17. Delete a required field

```bash
PYTHONPATH=src python3 -m portfolio_suites contract A11yFinding sample \
  | python3 -c "import json,sys; d=json.load(sys.stdin); d.pop('rule_id',None); print(json.dumps(d))" \
  > /tmp/no-rule.json && \
PYTHONPATH=src python3 -m portfolio_suites contract A11yFinding validate /tmp/no-rule.json
```

Look for: the error names the missing field, not just "invalid".

### 18. Put a string where a number belongs

```bash
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord sample \
  | python3 -c "import json,sys; d=json.load(sys.stdin); d['size_bytes']='big'; print(json.dumps(d))" \
  > /tmp/wrong-type.json && \
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord validate /tmp/wrong-type.json
```

Look for: a type error citing the published JSON type.

### 19. Try a boolean where an integer belongs

```bash
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord sample \
  | python3 -c "import json,sys; d=json.load(sys.stdin); d['size_bytes']=True; print(json.dumps(d))" \
  > /tmp/bool.json && \
PYTHONPATH=src python3 -m portfolio_suites contract SourceRecord validate /tmp/bool.json
```

Look for: rejection. In Python `True` *is* an `int`, so a naive `isinstance` check would let this
through. This one does not.

### 20. Compare two contracts' specs side by side

```bash
PYTHONPATH=src python3 -m portfolio_suites contract ProductionJob spec > /tmp/pj.txt && \
PYTHONPATH=src python3 -m portfolio_suites contract ExperimentRun spec > /tmp/er.txt && \
diff -y --width=140 /tmp/pj.txt /tmp/er.txt | head -30
```

Look for: how differently a "job that moves through stages" and a "run that produced measurements"
are shaped.

---

## Act III — Meet the Engines **[LOW BW]**

50 reviewed actions across eight suites. `engine` with no arguments prints the whole catalog with
signatures; every action below came from that list.

### 21. Print the entire action catalog

```bash
PYTHONPATH=src python3 -m portfolio_suites engine
```

Look for: eight suites, 50 actions, each with its parameters and what it emits. Adding a method to
an engine class does *not* add it here — the registry is explicit, so nothing becomes remotely
invocable by accident.

### 22. Narrow the catalog to one suite

```bash
PYTHONPATH=src python3 -m portfolio_suites engine accessibility
```

Look for: seven accessibility actions and their signatures.

### 23. Audit an HTML snippet for accessibility problems

```bash
PYTHONPATH=src python3 -m portfolio_suites engine accessibility audit_html_snippet \
  --args '{"html_content":"<img src=x><button></button><a href=#>click here</a>"}'
```

Look for: a list of `A11yFinding` contract objects. Three deliberate sins in that markup: an image
with no alt, an empty button, and a meaningless link label.

### 24. Run the broader WCAG rule families

```bash
PYTHONPATH=src python3 -m portfolio_suites engine accessibility audit_rule_families \
  --args '{"html_content":"<html><body><h3>Skipped heading levels</h3><input></body></html>"}'
```

Look for: findings from the wider rule set ported in the A4 wave, including the unlabelled input.

### 25. Write a finding that is honest about being a hypothesis

```bash
PYTHONPATH=src python3 -m portfolio_suites engine accessibility create_ai_assisted_finding \
  --args '{"finding_id":"f-demo-1","rule_id":"image-alt","summary":"Hero image lacks a text alternative","target":"img.hero","hypothesis":"Likely decorative; confirm with the designer before using empty alt"}'
```

Look for: the finding carries its `hypothesis` and is labelled as assisted. A guess that announces
itself is useful; a guess wearing the costume of a measurement is not.

### 26. Reconcile three keyboard overlay implementations

```bash
PYTHONPATH=src python3 -m portfolio_suites engine accessibility reconcile_keyboard_overlays
```

Look for: a comparison receipt recommending the canonical anchor. Note the wording — it *compared*
implementations; it did not consolidate any runtime.

### 27. Close out the overlay reconciliation

```bash
PYTHONPATH=src python3 -m portfolio_suites engine accessibility finalize_overlay_reconciliation
```

Look for: the finalisation receipt that the A3 wave gate checks.

### 28. Evaluate a backlog of WCAG rule candidates

```bash
PYTHONPATH=src python3 -m portfolio_suites engine accessibility evaluate_wcag_auditor_backlog_catalog \
  --args '{"cases":[{"rule_id":"image-alt","html":"<img src=x>"},{"rule_id":"label","html":"<input>"}]}'
```

Look for: a per-case verdict on whether each candidate rule is worth porting.

### 29. Capture a source record with provenance

```bash
PYTHONPATH=src python3 -m portfolio_suites engine operator-os capture_source \
  --args '{"content":"Users abandon onboarding at step 3.","origin":"notebook://ux-research","source_id":"src-demo-1"}'
```

Look for: a `SourceRecord` with a content digest and origin. Everything downstream traces back to
one of these.

### 30. Capture a whole batch of notes at once

```bash
PYTHONPATH=src python3 -m portfolio_suites engine operator-os capture_live_pkos_stream \
  --args '{"notes_batch":[{"content":"Ship the demo doc","origin":"voice://memo-1","source_id":"pk-1"},{"content":"Ask about step 3 drop-off","origin":"voice://memo-2","source_id":"pk-2"}]}'
```

Look for: each note becomes its own fingerprinted record.

### 31. Catch a projection trying to sneak back in as a source

```bash
PYTHONPATH=src python3 -m portfolio_suites engine operator-os detect_reingestion_violation \
  --args '{"content":"fenced_from_reingestion: true\n\nSummary of yesterday."}'
```

Look for: `true`. A document this system generated is fenced, so re-ingesting it as fresh source
would launder a projection into evidence. This is the guard that notices.

### 32. Confirm ordinary content is not fenced

```bash
PYTHONPATH=src python3 -m portfolio_suites engine operator-os detect_reingestion_violation \
  --args '{"content":"Just a note I typed myself."}'
```

Look for: `false`. The guard is specific, not paranoid.

### 33. Preview a filesystem action without doing it

```bash
PYTHONPATH=src python3 -m portfolio_suites engine operator-os preview_jarvis_action \
  --args '{"action_name":"backup_data","parameters":{"vault":"demo","dry_run":true}}'
```

Look for: `mutation_requested` and `requires_verified_operator_token`. Preview tells you what
authority the real thing would demand, before you commit to it.

### 34. Reconcile the RyOS disposition

```bash
PYTHONPATH=src python3 -m portfolio_suites engine operator-os reconcile_ryos_disposition
```

Look for: the disposition receipt behind the operator-os wave gate.

### 35. Roll a seeded game simulation

```bash
PYTHONPATH=src python3 -m portfolio_suites engine game-design simulate_tucked_in_terrors \
  --args '{"seed":7,"trials":200}'
```

Look for: an `ExperimentRun`. The seed is in the `model` field, which is how a "random" result
stays reproducible.

### 36. Prove the seed actually determines the outcome

```bash
strip() { python3 -c "
import json,sys
def clean(v):
    if isinstance(v,dict): return {k:clean(x) for k,x in v.items() if k!='timestamp'}
    if isinstance(v,list): return [clean(x) for x in v]
    return v
print(json.dumps(clean(json.load(sys.stdin)),sort_keys=True))"; }
PYTHONPATH=src python3 -m portfolio_suites engine game-design simulate_tucked_in_terrors \
  --args '{"seed":7,"trials":200}' | strip > /tmp/a.json
PYTHONPATH=src python3 -m portfolio_suites engine game-design simulate_tucked_in_terrors \
  --args '{"seed":7,"trials":200}' | strip > /tmp/b.json
diff /tmp/a.json /tmp/b.json && echo "IDENTICAL"
```

Look for: `IDENTICAL`, including identical `win_rate` and `avg_turn_count`. The `strip` helper
removes every `timestamp` at any depth — the *results* are fully determined by the seed, but each
run is stamped with the wall-clock moment it happened, and one of those stamps is nested inside
`evidence[]`. Now change one seed to `8` and watch the rest of the document light up.

### 37. Tilt the difficulty and see the balance move

```bash
PYTHONPATH=src python3 -m portfolio_suites engine game-design simulate_tucked_in_terrors \
  --args '{"seed":7,"trials":200,"difficulty_modifier":1.8}'
```

Look for: the same seed, a harder game, a different pass rate. This is the loop a designer actually
wants.

### 38. Build a playable text-adventure pack

```bash
PYTHONPATH=src python3 -m portfolio_suites engine game-design build_text_adventure_pack \
  --args '{"pack_id":"pack-demo","rooms_count":6}'
```

Look for: a playable pack structure. Authored content stays owned by its author; the engine only
arranges it.

### 39. Audit the authored-game boundary

```bash
PYTHONPATH=src python3 -m portfolio_suites engine game-design audit_authored_game_boundary
```

Look for: the check that generated material has not quietly absorbed authored material.

### 40. Parse a chess position from FEN

```bash
PYTHONPATH=src python3 -m portfolio_suites engine model-behavior-lab parse_fen_board \
  --args '{"fen":"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"}'
```

Look for: 32 squares in `a1`-style coordinates, sorted. The engine's internal board is keyed by
integer tuples, which JSON cannot express, so the action projects it into a square/piece list.

### 41. Run a deterministic chess benchmark

```bash
PYTHONPATH=src python3 -m portfolio_suites engine model-behavior-lab execute_chess_benchmark_run \
  --args '{"run_id":"run-demo-chess","puzzle_count":5}'
```

Look for: an `ExperimentRun` scoring real move legality — piece movement, attack boundaries, and
king safety — not a stubbed pass rate.

### 42. Run an ethics scenario evaluation

```bash
PYTHONPATH=src python3 -m portfolio_suites engine model-behavior-lab execute_ethics_scenario_run \
  --args '{"run_id":"run-demo-ethics","provider":"local-fixture","model":"fixture-v1","scenario_count":4}'
```

Look for: benchmark and scorer versions pinned into the run. An eval you cannot version is an
anecdote.

### 43. Repair a malformed agent plan

```bash
PYTHONPATH=src python3 -m portfolio_suites engine agent-reliability recover_plan \
  --args '{"raw_plan":"{\"steps\": [1, 2,], \"mode\": \"quick\",}"}'
```

Look for: `"status": "repaired"` and clean JSON. Those trailing commas are the single most common
way a model's JSON output fails.

### 44. Confirm it refuses what it cannot honestly repair

```bash
PYTHONPATH=src python3 -m portfolio_suites engine agent-reliability recover_plan \
  --args '{"raw_plan":"{ unquoted_key: 123"}'
```

Look for: `"status": "unrecoverable"` and a null plan. A repairer that always "succeeds" is
guessing, and a guessed plan is worse than no plan.

---

## Act IV — Chain Reactions **[HIGH BW]**

A chain feeds one action's output into a later action's argument using `{"$from": <step>}`, with an
optional `"path"` to select part of it. The CLI reads a chain from a file; `/dev/stdin` lets you
pipe one inline.

### 45. Your first chain: simulate, then report

```bash
printf '%s' '[{"suite":"game-design","action":"simulate_tucked_in_terrors","arguments":{"seed":3,"trials":80}},{"suite":"game-design","action":"generate_printable_balance_sheet","arguments":{"sim_result":{"$from":0}}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin
```

Look for: two steps, the second consuming the first, and a Markdown balance sheet at the end.

### 46. Watch just the trace, not the payload

```bash
printf '%s' '[{"suite":"game-design","action":"simulate_tucked_in_terrors","arguments":{"seed":3,"trials":80}},{"suite":"game-design","action":"generate_printable_balance_sheet","arguments":{"sim_result":{"$from":0}}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin --quiet
```

Look for: `[0] ... -> ExperimentRun` and `[1] ... <- step 0`. The arrows show what each step emitted
and which earlier steps it drew from.

### 47. Cross a suite boundary mid-chain

```bash
printf '%s' '[{"suite":"operator-os","action":"capture_source","arguments":{"content":"Users abandon onboarding at step 3.","origin":"notes://ux","source_id":"src-a"}},{"suite":"operator-os","action":"capture_source","arguments":{"content":"Support tickets spike on step 3 errors.","origin":"tickets://helpdesk","source_id":"src-b"}},{"suite":"discovery-decision","action":"discover_across_sources","arguments":{"source_a":{"$from":0},"source_b":{"$from":1},"query":"step 3"}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin --quiet
```

Look for: two Operator OS captures feeding one Discovery action. This is the whole point of shared
contracts — the third step never knew where its inputs came from.

### 48. Select part of an earlier output with `path`

```bash
printf '%s' '[{"suite":"model-behavior-lab","action":"execute_chess_benchmark_run","arguments":{"run_id":"run-chain-chess","puzzle_count":3}},{"suite":"model-behavior-lab","action":"build_versioned_corpus","arguments":{"corpus_id":"corpus-chain","runs":[{"$from":0}]}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin --quiet
```

Look for: a run wrapped into a corpus. Add `"path": "run_id"` to the reference and re-run to see
`path` pull out a single field instead of the whole object.

### 49. Build a job and advance it in one chain

```bash
printf '%s' '[{"suite":"production-house","action":"create_job","arguments":{"job_id":"job-chain","domain":"video","task":"rough cut","inputs":[{"name":"take-1.mov","sha256":"74ee5a187d2a2b658edad85532be5d79087b15d62f09b03094bd4a9085261ef7"}]}},{"suite":"production-house","action":"advance_job_stage","arguments":{"job":{"$from":0},"stage_name":"assembly"}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin --quiet
```

Look for: one `ProductionJob` carried through two stages, accumulating events.

### 50. Chain an investigation forward through a stage

```bash
printf '%s' '[{"suite":"discovery-decision","action":"create_investigation","arguments":{"investigation_id":"inv-chain","question":"Why do users stall at step 3?"}},{"suite":"discovery-decision","action":"advance_stage","arguments":{"record":{"$from":0},"stage_name":"triage","iteration_cost":1}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin --quiet
```

Look for: the budget ticking down. An investigation that cannot run out of budget never has to
decide anything.

### 51. Reference a step that has not run yet

```bash
printf '%s' '[{"suite":"game-design","action":"generate_printable_balance_sheet","arguments":{"sim_result":{"$from":1}}},{"suite":"game-design","action":"simulate_tucked_in_terrors","arguments":{"seed":1}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin
```

Look for: a **preflight** failure naming step 0, before anything executes. References only point
backwards, and the whole chain is checked before step zero runs.

### 52. Reference a step that does not exist at all

```bash
printf '%s' '[{"suite":"game-design","action":"simulate_tucked_in_terrors","arguments":{"seed":1}},{"suite":"game-design","action":"generate_printable_balance_sheet","arguments":{"sim_result":{"$from":99}}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin
```

Look for: refusal at preflight, again before execution.

### 53. Call an action that is not in the registry

```bash
printf '%s' '[{"suite":"game-design","action":"delete_everything","arguments":{}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin
```

Look for: `is not a reviewed action`. The allowlist is the security boundary; a method existing on
an engine class is not enough.

### 54. Pass an argument the action does not accept

```bash
printf '%s' '[{"suite":"game-design","action":"simulate_tucked_in_terrors","arguments":{"seed":1,"cheat_mode":true}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin
```

Look for: `does not accept: cheat_mode`. Unknown parameters are rejected rather than ignored.

### 55. Omit a required argument

```bash
printf '%s' '[{"suite":"discovery-decision","action":"create_investigation","arguments":{"investigation_id":"inv-x"}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin
```

Look for: `is missing: question`, caught at preflight.

### 56. Watch a chain fail mid-flight and report its completed prefix

```bash
printf '%s' '[{"suite":"game-design","action":"simulate_tucked_in_terrors","arguments":{"seed":5,"trials":20}},{"suite":"production-house","action":"create_job","arguments":{"job_id":"job-doomed","domain":"video","task":"edit","inputs":{"not":"a list"}}},{"suite":"game-design","action":"audit_authored_game_boundary","arguments":{}}]' \
  | PYTHONPATH=src python3 -m portfolio_suites chain /dev/stdin
```

Look for: `CHAIN FAILED [step 1]`, and a `completed_steps` block containing step 0's full result.
A long chain should tell you where it broke and what survived, not merely that it did. Note this
failure is caught at *execution*, not preflight: preflight checks that `inputs` is present, and
only the engine knows it has to be a list of artifact objects.

> **State safe.** Chains are stdin-fed and retain nothing. If you wrote a chain to a file, that
> file is the only thing left. Returning: `PYTHONPATH=src python3 -m portfolio_suites engine`
> reprints the action catalog a chain is built from.


---

## Act V — The Wave Runner **[HIGH BW]**

43 migration waves, each with an objective, an acceptance condition, and — if it is complete — a
retained evidence receipt. Running a wave is *ephemeral* by default: it re-derives the result and
throws it away, leaving the retained receipt untouched.

### 57. Run one wave

```bash
PYTHONPATH=src python3 -m portfolio_suites wave game-design G1
```

Look for: an `[INSPECTED]` tag and a one-line result. Nothing was written.

### 58. Run every wave in the portfolio

```bash
PYTHONPATH=src python3 -m portfolio_suites wave --all
```

Look for: 43 results in about ten seconds, ending in a summary line that counts each outcome kind
separately. Without `--full` you should see 36 verified analyses, 2 source execution, and 4
prototype checks passed. `A2` occupies the remaining slot: its shallow run reports 1 fast probe
when the browser runtime is available, or 1 environment-unverifiable when that runtime cannot be
opened. The latter is an honest "cannot check" rather than a failure.

### 59. Read the tag vocabulary

```bash
PYTHONPATH=src python3 -m portfolio_suites wave --all | grep -oE '^\[[A-Z-]+\]' | sort | uniq -c
```

Look for: `4 [PROTOTYPE]`, `35 [INSPECTED]`, `1 [HISTORICAL]`, `2 [SOURCE-RUN]`, and one
`A2` depth tag: either `1 [FAST-PROBE]` or `1 [UNVERIFIABLE]`. Each tag is a different strength
of claim and they are deliberately not interchangeable — `[RECOVERED]` does not appear here at
all, because earning it requires the full-depth run in demo 61.

### 60. Run the one real runtime-recovery wave

```bash
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2
```

Look for: without `--full` this reports `[FAST-PROBE]` when its shallow browser stages run, or
`[UNVERIFIABLE]` when that runtime cannot be opened — never `[RECOVERED]`. A probe that skipped
the expensive stages says so rather than inheriting the manifest's historical claim.

### 61. Demand full depth

```bash
PYTHONPATH=src python3 -m portfolio_suites wave accessibility A2 --full
```

Look for: either a genuine `[RECOVERED]` or an environment-blocked `[UNVERIFIABLE]` result. Depth
is requested explicitly and never implied by `--record`.

### 62. Ask a wave to record, and be told why it will not

```bash
PYTHONPATH=src python3 -m portfolio_suites wave game-design G5 --record
```

Look for: if nothing is written, a `record_note` explaining which of the distinct causes applied —
gate failure, ineligibility, or a rejected candidate. "Not written" has several meanings and they
are never conflated.

### 63. **[WRITES]** Re-record one wave's evidence

```bash
PYTHONPATH=src python3 -m portfolio_suites wave game-design G1 --record
```

Writes: `game-design/evidence/` for the G1 receipt only, and only if the gate passes *and* the
candidate validates. A rejected candidate leaves the prior receipt byte-for-byte unchanged.

### 64. Confirm the recording did not change anything

```bash
git status --porcelain game-design/evidence/
```

Look for: usually empty. The receipt is content-addressed, so re-recording an unchanged result
produces identical bytes.

### 65. Read a retained receipt directly

```bash
python3 -m json.tool game-design/evidence/G1-*.json | head -40
```

Look for: structured JSON with git fingerprints and typed fields. Receipts are pure JSON; any
Markdown lives inside string fields so the invariants stay machine-checkable.

### 66. Verify every retained receipt still satisfies its contract

```bash
PYTHONPATH=src python3 -m portfolio_suites validate --fast && echo "ALL RECEIPTS VALID"
```

Look for: the same validator the recorder uses. A receipt that records successfully cannot then
fail validation — they share one code path on purpose.

### 67. **[WRITES]** Tamper with a receipt and watch validation catch it

```bash
cp game-design/evidence/G1-*.json /tmp/G1-backup.json && \
python3 -c "import json,glob; p=glob.glob('game-design/evidence/G1-*.json')[0]; d=json.load(open(p)); d['tampered']=True; json.dump(d,open(p,'w'))" && \
PYTHONPATH=src python3 -m portfolio_suites validate --fast; \
cp /tmp/G1-backup.json $(ls game-design/evidence/G1-*.json)
```

Look for: validation complains, then the last line restores the original. Check with
`git status --porcelain game-design/evidence/` that you are clean again.

### 68. Prove an ephemeral run leaves retained evidence untouched

```bash
git status --porcelain -- '*/evidence/' > /tmp/before.txt && \
PYTHONPATH=src python3 -m portfolio_suites wave --all > /dev/null 2>&1 && \
git status --porcelain -- '*/evidence/' > /tmp/after.txt && \
diff /tmp/before.txt /tmp/after.txt && echo "43 WAVES RAN, ZERO RECEIPTS TOUCHED"
```

Look for: the confirmation line. Running every gate in the portfolio re-derives 43 results and
writes none of them. Recording is a separate, explicitly requested operation — which is exactly
why `--record` exists as its own flag.

### 69. Inspect a suite's wave list with objectives

```bash
PYTHONPATH=src python3 -m portfolio_suites inspect accessibility
```

Look for: six waves, A1 through A6, each with its objective and acceptance condition.

### 70. **[WRITES]** Record baseline fingerprints, dry-run first

```bash
PYTHONPATH=src python3 -m portfolio_suites baseline --dry-run
```

Writes: nothing, with `--dry-run`. Look for what *would* be fingerprinted. Only add `--accept` when
you have read that list and agree with it.

> **State safe.** `wave --all --no-record` takes about ten seconds and retains nothing; `--full`
> needs Node plus the Playwright runtime and is the only genuinely slow demo here. Demos 63, 67,
> and 70 touch evidence files. Returning: `PYTHONPATH=src python3 -m portfolio_suites validate`
> re-reads every retained receipt, and `git status` shows anything a recording demo left behind.


---

## Act VI — The Launchpad in a Browser **[HIGH BW]**

A loopback-only dashboard. Everything the CLI does, plus an evidence viewer and a Toolbench.

### 71. **[WRITES]** Start the server

```bash
PYTHONPATH=src python3 -m portfolio_suites serve --port 8383
```

Writes: nothing to disk, but it binds a port. Leave it running and open a second terminal for the
next demos. Open <http://127.0.0.1:8383> to see the dashboard.

### 72. Hit the portfolio API

```bash
curl -s http://127.0.0.1:8383/api/summary | python3 -m json.tool | head -20
```

Look for: the same coverage figures `suites status` prints, served locally. `/api/suites`,
`/api/projects`, `/api/drift`, and `/api/graph` are the neighbouring routes worth poking at.

### 73. Read the browser security headers

```bash
curl -sI http://127.0.0.1:8383/ | grep -iE "content-security|x-frame|x-content-type|referrer|permissions"
```

Look for: a CSP with `script-src 'self'`, plus frame, sniffing, referrer, and permissions policies.
The page carries no inline scripts, so the CSP costs nothing and blocks a whole class of injection.

### 74. Watch it refuse a DNS-rebinding Host header

```bash
curl -s -H "Host: evil.example.com" http://127.0.0.1:8383/api/summary
```

Look for: refusal. A non-loopback `Host` means the request was aimed here by name, which is how a
rebinding attack reaches a local server.

### 75. Confirm a legitimate loopback Host still works

```bash
curl -s -H "Host: localhost:8383" http://127.0.0.1:8383/api/suites | head -5
```

Look for: success. The validator accepts the loopback authorities and nothing else.

### 76. Fetch the wave list with live evidence status

```bash
curl -s http://127.0.0.1:8383/api/waves | python3 -m json.tool | head -30
```

Look for: each wave's `evidence_valid`, `evidence_errors`, and `verification_depth`. The dashboard
does not trust the manifest's `status` alone; it re-checks the receipt.

### 77. Ask the server for its redaction policy

```bash
curl -s http://127.0.0.1:8383/api/security-policy | python3 -m json.tool
```

Look for: one regex, served from Python. The browser Toolbench builds its redaction from *this*
rather than keeping a second copy that could drift out of agreement.

### 78. Watch cross-origin execution get refused

```bash
curl -s -X POST http://127.0.0.1:8383/api/engines/game-design/simulate_tucked_in_terrors/run \
  -H "Origin: http://evil.example.com" -H "Content-Type: application/json" -d '{"seed":1}'
```

Look for: `403` and a refusal. A browser on another origin does not get to drive your engines.

### 79. Run an engine action over HTTP, properly

```bash
curl -s -X POST http://127.0.0.1:8383/api/engines/game-design/simulate_tucked_in_terrors/run \
  -H "Content-Type: application/json" -d '{"seed":11,"trials":50}' | python3 -m json.tool | head -20
```

Look for: the same result the CLI gives, plus `emits` and `output_kind` metadata.

### 80. Confirm secrets are redacted from the echoed arguments

```bash
curl -s -X POST http://127.0.0.1:8383/api/engines/operator-os/preview_jarvis_action/run \
  -H "Content-Type: application/json" \
  -d '{"action_name":"backup_data","parameters":{"vault":"demo","api_key":"sk-live-do-not-log-me"}}' \
  | python3 -m json.tool | grep -A3 arguments
```

Look for: `[REDACTED: supply a new one-time secret]` where your key was. Then `curl` the same
endpoint with the key under a plain `token` field and confirm that is caught too.

> **State safe.** Demo 71 left a server running on port 8383 — Ctrl-C the terminal it owns, or
> leave it up, since Act VIII's last three demos need it again. Returning: `./start.sh` restarts
> it, and `PYTHONPATH=src python3 -m portfolio_suites status` reorients you without the browser.


---

## Act VII — Your Free AI Sidekick **[HIGH BW]**

Explicitly provider-assisted, free-only by default, and structurally unable to create evidence.
These demos reach OpenRouter over the network.

### 81. Check the AI configuration without exposing a credential

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --status
```

Look for: `configured`, the credential *source* (never its bytes), the free-only policy, and the
per-role model and budget table.

### 82. Get the same status as JSON

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --status --json
```

Look for: `evidence_boundary` spelled out in the payload. The boundary travels with the data.

### 83. Ask the orchestrator for a plan

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --suite operator-os \
  "What is the smallest safe next step to improve source capture?"
```

Look for: the answer, and the label saying it is model-assisted and requires human review.

### 84. Switch roles and feel the temperature change

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --suite game-design --role creative \
  "Give me three unsettling bedtime-monster mechanics for Tucked In Terrors."
```

Look for: the `creative` role runs at temperature 0.7 while `reviewer` runs at 0.0. Same provider,
deliberately different postures.

### 85. Get a review instead of an invention

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --suite agent-reliability --role reviewer \
  "What negative paths would you expect a plan-recovery function to miss?"
```

Look for: findings led by the most consequential one, per that role's system prompt.

### 86. Feed it a file as context

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --suite accessibility --role accessibility \
  --context docs/RECOVERY-STANDARD.md "Summarise the promotion policy in plain language."
```

Look for: the file is confined to the Projects workspace and size-capped before it is sent.

### 87. Watch it refuse to send a sensitive file

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --suite operator-os --context .env "Summarise this"
```

Look for: a refusal before any network call. The check is on the path, so the bytes never leave.

### 88. Watch it refuse a prompt containing a credential

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --suite operator-os \
  "Here is my key sk-or-v1-abcdefghijklmnopqrstuvwxyz012345 please debug it"
```

Look for: refusal naming the credential *type* without echoing the value. Failing closed is the
point; so is not repeating the secret in the error.

> **State safe.** The AI demos retain nothing locally and write no evidence — a provider answer
> cannot become a receipt. Nothing to clean up; your `.env` is where you left it.


---

## Act VIII — Try to Break It **[LOW BW]**

The most useful act. Every demo here should *fail*, and the interesting part is the shape of the
refusal. A system's boundaries are the part you can actually trust.

Almost all of these are one-liners you can run cold. Two exceptions: 94–96 create and then remove
a `mktemp -d` directory and want the same shell kept open across all three, and 98–100 need the
server from demo 71 running.

### 89. Ask for a suite that does not exist

```bash
PYTHONPATH=src python3 -m portfolio_suites inspect not-a-real-suite
```

Look for: a clean "not found", not a traceback.

### 90. Ask for a contract that does not exist

```bash
PYTHONPATH=src python3 -m portfolio_suites contract NotAContract sample
```

Look for: a refusal listing the six real contracts.

### 91. Run a wave that does not exist

```bash
PYTHONPATH=src python3 -m portfolio_suites wave game-design G99
```

Look for: `Wave G99 not found in game-design`, tagged `[ERROR]`.

### 92. Try to escape the workspace with a path

```bash
PYTHONPATH=src python3 -m portfolio_suites engine agent-reliability verify_path_confinement \
  --args '{"workspace_root":"/tmp/ws","target_path":"/tmp/ws/../../etc/passwd"}'
```

Look for: the traversal is refused. This is the engine whose entire job is noticing that.

### 93. Try the same escape with a symlink-shaped path

```bash
PYTHONPATH=src python3 -m portfolio_suites engine agent-reliability verify_path_confinement \
  --args '{"workspace_root":"/tmp/ws","target_path":"/tmp/ws/link-to-elsewhere"}'
```

Look for: confinement is decided on the resolved path, not the literal one.

### 94. **[WRITES]** Demand a real mutation without any approval

First give the rotation something real to aim at, so it reaches the approval gate rather than
stopping at "that directory does not exist":

```bash
DEMO_PARENT="$(mktemp -d "$PWD/.demo-rotate-XXXXXX")" && DEMO_CACHE="$DEMO_PARENT/.cache" && \
mkdir "$DEMO_CACHE" && touch "$DEMO_CACHE/tmpfile" && \
PYTHONPATH=src python3 -m portfolio_suites engine operator-os execute_jarvis_action_checkpoint \
  --args "{\"action_name\":\"rotate_local_cache\",\"parameters\":{\"cache_dir\":\"$DEMO_CACHE\",\"dry_run\":false}}"
```

The randomized part is the *parent*: rotation only accepts a directory explicitly named `cache`,
`.cache`, or `*-cache`, so a randomized `.demo-cache-XXXXXX` name is refused as an invalid target
before any approval question is reached, and demos 95 and 96 would never get to the failures they
exist to show. `mktemp -d` still keeps this off a `.cache` you already had: the tree is created
fresh, its absolute path is held in `$DEMO_PARENT`, and demo 96 removes that exact path and nothing
else. Keep the same shell open through demo 96.

Look for: `"status": "blocked_missing_approval"` and `operator_approval_verified: false`. This is
the outer gate; the request never even gets as far as asking about a token.

### 95. Bluff by claiming you were approved

```bash
PYTHONPATH=src python3 -m portfolio_suites engine operator-os execute_jarvis_action_checkpoint \
  --args "{\"action_name\":\"rotate_local_cache\",\"parameters\":{\"cache_dir\":\"$DEMO_CACHE\",\"dry_run\":false},\"operator_approved\":true}"
```

Look for: `"status": "error_unverified_approval"`. This is the demo that matters. Claiming approval
gets you *past* the outer gate and straight into the real one, where an actual verified token is
demanded and you do not have one. `operator_approved` is caller confirmation; authority is
something else entirely, and the engine will not confuse the two or mint one for itself.

### 96. **[WRITES]** Present a forged approval token, then clean up demo 94

```bash
PYTHONPATH=src python3 -m portfolio_suites engine operator-os execute_jarvis_action_checkpoint \
  --args "{\"action_name\":\"rotate_local_cache\",\"parameters\":{\"cache_dir\":\"$DEMO_CACHE\",\"dry_run\":false},\"operator_approved\":true,\"operator_approval_token\":\"approval.fake.deadbeef\"}" \
  ; ls "$DEMO_CACHE/" \
  ; case "$DEMO_PARENT" in "$PWD"/.demo-rotate-??????) rm -rf "$DEMO_PARENT";; *) echo "refusing to remove $DEMO_PARENT";; esac
```

An approval for `backup_data` or `sync_obsidian_notes` binds more than the arguments above: its
digest covers the content hash of every byte the run will write. Run the command once without a
token and the refusal reports the `approval_payload_sha256` to have approved — editing a source
file afterwards changes that digest and the token stops verifying.

Look for: the token is rejected on its shape before any digest lookup happens, `tmpfile` is still
sitting in `$DEMO_CACHE`, and the last command removes only the tree demo 94 created — the
`case` guard refuses any `$DEMO_PARENT` that is not the `mktemp -d` path under this checkout. Real tokens are `opa1`-prefixed,
compared with a constant-time digest check, bound to the exact payload, and single-use.

### 97. Feed the JSON boundary something JSON cannot hold

```bash
PYTHONPATH=src python3 -m portfolio_suites engine game-design simulate_tucked_in_terrors \
  --args '{"seed": Infinity}'
```

Look for: refusal. `Infinity` is a Python float and a JSON impossibility, and the boundary is where
that difference gets caught.

### 98. Send malformed JSON to the HTTP API

```bash
curl -s -X POST http://127.0.0.1:8383/api/engines/game-design/simulate_tucked_in_terrors/run \
  -H "Content-Type: application/json" -d '{"seed": NaN}'
```

Look for: `400` naming non-finite numbers. Requires the server from demo 71.

### 99. Lie about Content-Length

```bash
curl -s -X POST http://127.0.0.1:8383/api/contracts/SourceRecord/validate \
  -H "Content-Type: application/json" -H "Content-Length: 9999" -d '{"a":1}' --max-time 5
```

Look for: a refusal rather than a hang. A body that ends before its declared length is an error,
not something to wait on forever.

### 100. Confirm the whole thing still agrees with itself

```bash
PYTHONPATH=src python3 -m pytest -q && \
PYTHONPATH=src python3 -m portfolio_suites validate && \
git status --porcelain && echo "CLEAN — 100 demos, nothing broken, nothing left behind"
```

Look for: a green suite, a clean validation, and an empty `git status` proving that a hundred demos
left your working tree exactly as they found it. If `git status` is *not* empty, demo 63 recorded
evidence and demo 67 restored a receipt — check those two before assuming something is wrong.

---

## Where to go next

- [README.md](../README.md) — the short version of everything above.
- [PROJECT-BIBLE.md](PROJECT-BIBLE.md) — why the suites are shaped this way.
- [RECOVERY-STANDARD.md](RECOVERY-STANDARD.md) — what a claim has to survive to be called verified.
- [ROADMAP.md](ROADMAP.md) — which waves are next.
- [CHANGELOG.md](CHANGELOG.md) — what has actually shipped, with dates.
