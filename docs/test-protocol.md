# Ryan Project Suites — Manual Verification & Testing Protocol

This protocol provides step-by-step instructions, copy-pasteable CLI commands, Toolbench JSON payloads, and structured AI prompts to manually test and verify all 8 product suites, the cross-suite contracts, the action chain engine, and the free OpenRouter AI assistant.

**Bandwidth.** Each section is tagged with what it costs to run, so you can pick one that fits the
day: **[LOW BW]** is copy-paste CLI with no server and no browser; **[HIGH BW]** needs the
dashboard running, a network round-trip, or a payload you compose yourself. High-bandwidth
sections end with a **State safe** block naming what is still running and how to pick the thread
back up. Section 2 is the whole engine surface at low bandwidth — every test there has a CLI
command, so the server in section 1 is only required for sections 3, 4, and 5.

---

## 1. Prerequisites & Server Launch **[HIGH BW]**

Ensure your local virtual environment is active and launch the control plane:

```bash
cd /Users/ryanjohnson/Projects/suites
./start.sh
# Default: http://127.0.0.1:8383
```

Check the OpenRouter AI configuration and host pinning:
```bash
PYTHONPATH=src python3 -m portfolio_suites ai --status --json
```

---

## 2. Interactive Toolbench & Suite Engine Verification **[LOW BW]**

Every action can be executed through the Web UI (**Toolbench** tab at `http://127.0.0.1:8383`) or directly via the CLI:
`PYTHONPATH=src python3 -m portfolio_suites engine <suite_id> <action_name> --args '<json>'`

### Suite 1 — Accessibility (`accessibility`)

#### Test 1.1: Audit HTML Snippet
- **Action:** `audit_html_snippet`
- **Output:** `contract-list` (`A11yFinding`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine accessibility audit_html_snippet \
    --args '{"html_content": "<img src=\"logo.png\"><button></button>"}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "html_content": "<img src=\"logo.png\"><button></button>"
  }
  ```
- **Expected Result:** Two `A11yFinding` objects — `wcag-1.1.1-non-text-content` (image missing `alt`) and
  `wcag-4.1.2-name-role-value` (button with no text content and no `aria-label`).
  Ambiguous link text (`wcag-2.4.4-link-purpose`) is **not** produced by this action; it belongs to
  `audit_rule_families`, covered in Test 1.3.

#### Test 1.2: Create AI-Assisted Finding
- **Action:** `create_ai_assisted_finding`
- **Output:** `contract` (`A11yFinding`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine accessibility create_ai_assisted_finding \
    --args '{"finding_id": "find-ai-001", "rule_id": "wcag-1.4.3-contrast", "summary": "Low text contrast against background", "target": "button.subtle-btn", "hypothesis": "Increasing text brightness fixes the contrast ratio."}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "finding_id": "find-ai-001",
    "rule_id": "wcag-1.4.3-contrast",
    "summary": "Low text contrast against background",
    "target": "button.subtle-btn",
    "hypothesis": "Increasing text brightness fixes the contrast ratio."
  }
  ```
- **Expected Result:** Valid `A11yFinding` contract with `evidence_kind` set to `ai-assisted`, plus
  `needs_review: true` and `status: "open"`.

#### Test 1.3: Audit Extended Rule Families
- **Action:** `audit_rule_families`
- **Output:** `contract-list` (`A11yFinding`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine accessibility audit_rule_families \
    --args '{"html_content": "<img src=\"hero.png\"><a href=\"#\">Click here</a>"}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "html_content": "<img src=\"hero.png\"><a href=\"#\">Click here</a>"
  }
  ```
- **Expected Result:** Two `A11yFinding` objects — `wcag-1.1.1-non-text-content` and
  `wcag-2.4.4-link-purpose` (ambiguous link text `'Click here'`, `evidence_kind: "manual"`).

---

### Suite 2 — Operator OS (`operator-os`)

#### Test 2.1: Capture Source Record
- **Action:** `capture_source`
- **Output:** `contract` (`SourceRecord`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine operator-os capture_source \
    --args '{"source_id": "note-001", "origin": "daily-vault/note-001.md", "content": "# Meeting Notes\nReview portfolio contracts.", "media_type": "text/markdown", "author": "Ryan"}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "source_id": "daily-log-2026-08-25",
    "origin": "daily-vault/2026-08-25.md",
    "content": "# Daily Log\nVerified all 50 engine actions.",
    "media_type": "text/markdown",
    "author": "Ryan"
  }
  ```
- **Expected Result:** A valid `SourceRecord` with computed SHA-256 content hash and ISO-8601 timestamp.

#### Test 2.2: Preview JARVIS Action
- **Action:** `preview_jarvis_action`
- **Output:** `receipt` (`read_only`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine operator-os preview_jarvis_action \
    --args '{"action_name": "secret_audit", "parameters": {"target_directory": "src/portfolio_suites"}}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "action_name": "secret_audit",
    "parameters": {
      "target_directory": "src/portfolio_suites"
    }
  }
  ```
- **Expected Result:** A preview receipt detailing the proposed read-only scan and required operator authority if executed.

---

### Suite 3 — Brand + Publishing (`brand-publishing`)

#### Test 3.1: Compile Brand Package
- **Action:** `compile_brand_package`
- **Output:** `contract` (`BrandPackage`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine brand-publishing compile_brand_package \
    --args '{"package_id": "pkg-cyborg-1", "brand_id": "cyborg", "version": "1.0.0", "identity": {"mission": "High-signal operator leverage"}, "voice": {"tone": ["crisp", "calm"]}, "audience": {"primary": "Engineers"}, "approved_claims": [{"claim": "Local-first"}, {"claim": "Evidence-bound"}], "assets": [{"path": "assets/logo.svg"}], "usage_rules": ["Redact secrets fail-closed"], "provenance": [{"author": "Ryan"}]}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "package_id": "pkg-cyborg-1",
    "brand_id": "cyborg",
    "version": "1.0.0",
    "identity": {
      "mission": "High-signal operator leverage"
    },
    "voice": {
      "tone": ["crisp", "calm"]
    },
    "audience": {
      "primary": "Engineers"
    },
    "approved_claims": [
      {"claim": "Local-first"},
      {"claim": "Evidence-bound"}
    ],
    "assets": [
      {"path": "assets/logo.svg"}
    ],
    "usage_rules": [
      "Redact secrets fail-closed"
    ],
    "provenance": [
      {"author": "Ryan"}
    ]
  }
  ```
- **Expected Result:** Valid `BrandPackage` contract with pinned immutable version and schema conformance.

---

### Suite 4 — Production House (`production-house`)

#### Test 4.1: Build Groundwire Pipeline Job
- **Action:** `build_groundwire_pipeline_job`
- **Output:** `contract` (`ProductionJob`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine production-house build_groundwire_pipeline_job \
    --args '{"episode_slug": "gw-101", "script_sha": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "episode_slug": "gw-101",
    "script_sha": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
  ```
- **Expected Result:** A `ProductionJob` contract with `status: "completed"` and four projected event
  stages: `script_intake`, `formatter_projection`, `mix_projection`, `qc_projection`.

#### Test 4.2: Parse Episode Script
- **Action:** `parse_episode_script`
- **Output:** `data`
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine production-house parse_episode_script \
    --args '{"script_text": "SPEAKER 1: Initiating recovery protocol.\nSPEAKER 2: Confirmed. Verification gates green."}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "script_text": "SPEAKER 1: Initiating recovery protocol.\nSPEAKER 2: Confirmed. Verification gates green."
  }
  ```
- **Expected Result:** Structured scene, line, and speaker counts.

---

### Suite 5 — Model Behavior Lab (`model-behavior-lab`)

#### Test 5.1: Execute Chess Benchmark Run
- **Action:** `execute_chess_benchmark_run`
- **Output:** `contract` (`ExperimentRun`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine model-behavior-lab execute_chess_benchmark_run \
    --args '{"run_id": "chess-run-001", "puzzle_count": 5}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "run_id": "chess-run-001",
    "puzzle_count": 5
  }
  ```
- **Expected Result:** An `ExperimentRun` contract with metrics, evaluation scores, and resolved moves.

#### Test 5.2: Parse FEN Board
- **Action:** `parse_fen_board`
- **Output:** `data`
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine model-behavior-lab parse_fen_board \
    --args '{"fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
  }
  ```
- **Expected Result:** Parsed coordinate-to-piece map with `square_piece_list_v1` representation.

---

### Suite 6 — Discovery + Decision (`discovery-decision`)

#### Test 6.1: Create Investigation Record
- **Action:** `create_investigation`
- **Output:** `contract` (`InvestigationRecord`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine discovery-decision create_investigation \
    --args '{"investigation_id": "inv-2026-001", "question": "What is the safest upgrade path for local state stores?"}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "investigation_id": "inv-2026-001",
    "question": "What is the safest upgrade path for local state stores?"
  }
  ```
- **Expected Result:** Valid `InvestigationRecord` initialized in `evidence_intake` stage.

#### Test 6.2: Discover Across Sources
- **Action:** `discover_across_sources`
- **Output:** `receipt`
- **Expected Inputs:** Two `SourceRecord` objects with **distinct** `source_id` values, generated via
  `operator-os.capture_source`. Because it consumes whole contracts, drive it as a chain:
  ```bash
  cat > /tmp/discover.json <<'JSON'
  [
   {"suite":"operator-os","action":"capture_source","arguments":{"source_id":"src-a","origin":"notes/wcag.md","content":"WCAG 2.1 AA requires minimum 4.5:1 contrast for regular text.","media_type":"text/markdown","author":"Operator"}},
   {"suite":"operator-os","action":"capture_source","arguments":{"source_id":"src-b","origin":"notes/contrast.md","content":"Large text may use a 3:1 contrast ratio under WCAG 2.1 AA.","media_type":"text/markdown","author":"Operator"}},
   {"suite":"discovery-decision","action":"discover_across_sources","arguments":{"source_a":{"$from":0},"source_b":{"$from":1},"query":"What contrast ratios does WCAG 2.1 AA require?"}}
  ]
  JSON
  PYTHONPATH=src python3 -m portfolio_suites chain /tmp/discover.json
  ```
- **Expected Result:** A receipt citing both `source_id`/`sha256` pairs, with
  `semantic_analysis_performed: false` and `novelty_score_kind:
  "metadata_distinctness_not_semantic_novelty"` — the action compares content digests and refuses to
  claim semantic novelty it did not compute. Passing the same `source_id` twice is rejected.

---

### Suite 7 — Agent Reliability Lab (`agent-reliability`)

#### Test 7.1: Run Adversarial Harness
- **Action:** `run_adversarial_harness`
- **Output:** `contract` (`ExperimentRun`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine agent-reliability run_adversarial_harness \
    --args '{}'
  ```
- **Toolbench Payload:**
  ```json
  {}
  ```
- **Expected Result:** `ExperimentRun` documenting blocked containment violations and zero out-of-bounds mutations.

#### Test 7.2: Partition Plan by Budget
- **Action:** `partition_plan_by_budget`
- **Output:** `receipt`
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine agent-reliability partition_plan_by_budget \
    --args '{"steps": ["fetch_data", "heavy_transform", "write_output"], "max_steps": 2}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "steps": [
      "fetch_data",
      "heavy_transform",
      "write_output"
    ],
    "max_steps": 2
  }
  ```
- **Expected Result:** Partitioned step chunks respecting the step budget.

---

### Suite 8 — Game Design + Simulation (`game-design`)

#### Test 8.1: Simulate Tucked in Terrors
- **Action:** `simulate_tucked_in_terrors`
- **Output:** `contract` (`ExperimentRun`)
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine game-design simulate_tucked_in_terrors \
    --args '{"seed": 42, "trials": 100}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "seed": 42,
    "trials": 100
  }
  ```
- **Expected Result:** Simulation statistics (win rate, average turns, tension curve) in an `ExperimentRun` contract.

#### Test 8.2: Build Text Adventure Pack
- **Action:** `build_text_adventure_pack`
- **Output:** `data`
- **CLI Command:**
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites engine game-design build_text_adventure_pack \
    --args '{"pack_id": "adv-pack-001", "rooms_count": 8}'
  ```
- **Toolbench Payload:**
  ```json
  {
    "pack_id": "adv-pack-001",
    "rooms_count": 8
  }
  ```
- **Expected Result:** Storyweaver-compatible text adventure rooms data structure.

---

## 3. Action Chains & Result Tray Verification **[HIGH BW]**

Action chains allow handing output from one suite engine directly into another using `$from` references.

### Test 3.1: Two-Step Capture and Discovery Chain

1. In the Toolbench, run **Operator OS** → `capture_source` with:
   ```json
   {
     "source_id": "src-sample",
     "origin": "notes/wcag.md",
     "content": "WCAG 2.1 AA requires minimum 4.5:1 contrast for regular text.",
     "media_type": "text/markdown",
     "author": "Operator"
   }
   ```
2. Note the newly populated step in the **Result Tray**. Tray steps are **0-indexed**: the first
   result is `step 0`.
3. Select **Accessibility** → `create_ai_assisted_finding`, then click **Use as argument** on the
   tray entry rather than hand-writing the reference — the UI inserts the correct `$from` index for
   you. Add the `path` and the remaining fields:
   ```json
   {
     "finding_id": "find-chain-001",
     "rule_id": "wcag-1.4.3-contrast",
     "summary": "Low text contrast against background",
     "target": "p.subtle",
     "hypothesis": {"$from": 0, "path": "origin"}
   }
   ```
   `SourceRecord` is a metadata contract — it carries `source_id`, `origin`, `sha256`, `size_bytes`,
   `media_type`, `acquired_at`, and `provenance`, but **not** the captured body. A `path` naming a
   field it does not carry (such as `content`) fails closed with
   `path 'content' has no key 'content' in step 0 output`.
4. Click **Run Tool**. Verify the second step resolved the reference: the emitted `A11yFinding`
   carries `evidence[0].ai_hypothesis` equal to step 0's `origin` (`notes/wcag.md`).
5. Click **Copy Chain JSON** and verify the exported JSON contains clean, rebased references.

The same chain from the CLI:

```bash
cat > /tmp/chain.json <<'JSON'
[
 {"suite":"operator-os","action":"capture_source","arguments":{"source_id":"src-sample","origin":"notes/wcag.md","content":"WCAG 2.1 AA requires minimum 4.5:1 contrast for regular text.","media_type":"text/markdown","author":"Operator"}},
 {"suite":"accessibility","action":"create_ai_assisted_finding","arguments":{"finding_id":"find-chain-001","rule_id":"wcag-1.4.3-contrast","summary":"Low text contrast against background","target":"p.subtle","hypothesis":{"$from":0,"path":"origin"}}}
]
JSON
PYTHONPATH=src python3 -m portfolio_suites chain /tmp/chain.json
```

Expected trace:

```
[0] operator-os.capture_source -> SourceRecord
[1] accessibility.create_ai_assisted_finding -> A11yFinding <- step 0
```

> **State safe.** A chain retains nothing; only a chain file you saved yourself survives. The
> server from section 1 is still up on 8383. Returning:
> `PYTHONPATH=src python3 -m portfolio_suites engine` reprints the actions a chain composes.


---

## 4. Free OpenRouter AI Assistant Testing **[HIGH BW]**

Test the 5 specialized roles in the **Free AI Assistant** tab (`http://127.0.0.1:8383/#ai`) or via CLI:
`PYTHONPATH=src python3 -m portfolio_suites ai --suite <suite> --role <role> "<prompt>"`

> [!IMPORTANT]
> **These are non-deterministic checks. Assert shape, never exact content.**
> `openrouter/free` is a *router*, not a model: it selects a different upstream model per call. A
> single observed run served six distinct models across eight calls. The per-role `temperature`
> (reviewer is pinned at `0.0`) constrains sampling within one model and guarantees nothing across
> model substitution. Never gate this section on a specific WCAG number, phrase, or wording — check
> that the answer is on-topic, correctly labelled, and free of unevidenced claims.

> [!WARNING]
> **A free-router draw can return a non-answer that still looks well-formed.** One observed call was
> routed to `nvidia/nemotron-3.5-content-safety:free` — a safety classifier, not a chat model — which
> returned the single line `User Safety: safe` carrying the full, correct attribution footer. Nothing
> in the control plane checks that a provider response is *responsive* to the prompt; the labelling is
> honest but the content was not an answer. If a role returns an off-topic or degenerate response,
> re-run it before recording a failure, and record the served model name from the footer. Treat a
> repeatable off-topic result as a finding, not a flake.

Every response must end with an attribution footer naming the served model, and must never contain a
credential:

```
Model-assisted via OpenRouter: <model> | suite=<suite> | role=<role> | human review required
```

### Role Test Prompts

#### 1. Orchestrator
- **Suite:** `operator-os`
- **Role:** `orchestrator`
- **Prompt:**
  ```text
  I have three modified Markdown notes and one updated JSON schema. Plan the minimal, safe sequence to validate contracts and ingest the notes without duplicate state.
  ```
- **Expected Structure:** An ordered, resumable plan that visibly separates deterministic steps from
  steps needing owner confirmation, and names its unknowns rather than guessing past them. Verified
  shape, not wording — phase headings, a numbered sequence, or a table all satisfy this.

#### 2. Analyst
- **Suite:** `discovery-decision`
- **Role:** `analyst`
- **Prompt:**
  ```text
  Compare our current evidence depth (37 source-inspected vs 1 parity-verified) and analyze what is required to promote a wave from inspected to executed.
  ```
- **Run it with the standard attached.** The role prompts in `ai.py` tell the model not to *claim*
  execution or parity without evidence, but they do not carry the promotion ladder itself, so an
  unaided model will invent plausible-but-wrong semantics. Supply it explicitly:
  ```bash
  PYTHONPATH=src python3 -m portfolio_suites ai --suite discovery-decision --role analyst \
    --context docs/RECOVERY-STANDARD.md \
    "Compare our current evidence depth (37 source-inspected vs 1 parity-verified) and analyze what is required to promote a wave from inspected to executed."
  ```
- **Expected Structure:** A breakdown that does not assert any wave has executed, and that keeps the
  ladder ordering straight — `source_inspected` → `source_executed` → `parity_verified`
  (`recovery_policy.py:16-24`). **Known failure mode:** without `--context`, models describe parity
  verification as the gate *into* executed, inverting two rungs. Treat that inversion as a failed run.

#### 3. Reviewer
- **Suite:** `accessibility`
- **Role:** `reviewer`
- **Prompt:**
  ```text
  Review this finding: an <input type="text"> element lacks an associated <label> or aria-label. What is the severity, WCAG success criterion, and remediation?
  ```
- **Expected Structure:** A severity call, at least one correctly-numbered WCAG Level A success
  criterion for a missing accessible name (1.3.1, 3.3.2, and 4.1.2 are all defensible; observed runs
  cited different subsets), and runnable HTML remediation using `<label for>`. Do **not** gate on a
  specific criterion number — the served model changes per call.

#### 4. Creative
- **Suite:** `brand-publishing`
- **Role:** `creative`
- **Prompt:**
  ```text
  Draft three publication taglines for a local-first, evidence-bounded developer platform that emphasizes recovery speed and high signal.
  ```
- **Expected Structure:** Exactly three distinct options in the crisp, calm tone, with any factual or
  performance claim marked as unverified rather than asserted. An observed run flagged its own
  "recovery in minutes" line as an internal target needing evidence before publication — that is the
  behavior to look for.

#### 5. Accessibility
- **Suite:** `accessibility`
- **Role:** `accessibility`
- **Prompt:**
  ```text
  Explain how to ensure keyboard focus indicators remain visible when applying custom CSS reset rules to interactive buttons.
  ```
- **Expected Structure:** Practical CSS covering `:focus-visible` and focus-indicator contrast.
  Observed: 3/3 retries covered `:focus-visible`; a fourth call routed to a safety classifier and
  returned a non-answer (see the router warning above). Re-run before recording a failure.

---

## 5. Security & Negative-Path Testing **[HIGH BW]**

### Test 5.1: Secret Redaction in Prompts
- **Action:** Paste a fake API key into the AI Prompt:
  ```text
  Here is my key: sk-or-v1-abcdef1234567890abcdef1234567890. Please summarize my project.
  ```
- **Expected Result:** The client and server reject the request locally with a `secret detected` error before any network packet leaves the machine.

### Test 5.2: Unapproved Filesystem Mutation Refusal
- **Action:** Attempt to run `execute_jarvis_action_checkpoint` without an approval token:
  ```json
  {
    "action_name": "backup_vault",
    "parameters": {"target_dir": "backups"},
    "operator_approved": false
  }
  ```
- **Expected Result:** Action fails closed, returning a receipt with `state: "blocked_missing_approval"`
  and no filesystem mutation. This is a structured refusal, not a raised error — the command still exits 0.

> **State safe.** Nothing in sections 4 and 5 writes evidence or mutates the filesystem — a
> provider answer cannot become a receipt, and 5.2 is a refusal by design. The server is still
> running; Ctrl-C its terminal or leave it. Returning:
> `PYTHONPATH=src python3 -m portfolio_suites status`, then `./start.sh` if you want the UI back.


---

## 6. Full Automated Test Battery **[LOW BW]**

Run the deterministic validation and unit test suites. Low bandwidth in the sense that matters:
four commands, no browser, no judgement calls — start it and walk away for a couple of minutes.

```bash
# 1. Fast schema and registry validation (~0.2s)
PYTHONPATH=src python3 -m portfolio_suites validate --fast

# 2. Ephemeral run of all 43 migration wave gates (~11s)
PYTHONPATH=src python3 -m portfolio_suites wave --all --no-record

# 3. Full unit test suite (450 tests, ~70s; 4 skip unless SUITES_WHEEL_SMOKE=1)
PYTHONPATH=src python3 -m unittest discover -s tests

# 4. Packaging and wheel smoke gate -- REQUIRES Python >= 3.11.
#    `python3` on macOS Command Line Tools is 3.9 and this gate fails closed on it.
#    Check with `python3 -V`; substitute a conforming interpreter if it is below 3.11.
SUITES_WHEEL_SMOKE=1 PYTHONPATH=src python3.12 -m unittest tests.test_wheel_smoke
```

Gate 4 builds a wheel in a throwaway venv from `sys.executable`, so it fails with an explicit
`below the requires-python floor` hint rather than a confusing build error when run on 3.9.
