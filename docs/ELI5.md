# ELI5: How to Actually Use This Thing

A plain-language handbook. No prior knowledge assumed. If a sentence here uses a
special word, that word is defined before it is used.

Everything in this file was run against the live project before it was written down.

---

## 1. What is this project, in one paragraph?

Ryan has ~70 coding projects scattered across his laptop. Some are finished, some are
half-built, many overlap, and it is genuinely hard to know what works. **This repository
is not those projects.** It is the *control plane* — the clipboard, the inspector, the
scorekeeper that sits above them and answers: what do I actually have, what actually
runs, and what am I still just *claiming* runs?

The single idea underneath everything: **saying a thing works is not evidence that it
works.** Almost every rule in here exists to stop optimism from being recorded as fact.

---

## 2. The two-minute start

```bash
cd /Users/ryanjohnson/Projects/suites

# What exists and what state is it in?
PYTHONPATH=src python3 -m portfolio_suites status

# What should I work on next?
PYTHONPATH=src python3 -m portfolio_suites next

# Open the web dashboard (http://127.0.0.1:8383)
./start.sh
```

That `PYTHONPATH=src` prefix appears on every command. It just tells Python where the
code lives, because the project is not installed system-wide. You can skip it forever by
running `pip install .` once and then using the `suites` command instead.

> **Heads up:** on macOS, plain `python3` is often version 3.9, which is too old for one
> of the gates (§9). Check with `python3 -V`. If it says 3.9, use `python3.12` for the
> packaging gate specifically. Everything else works fine on 3.9.

---

## 3. The vocabulary (learn these six words and you can read anything here)

| Word | What it actually means |
|---|---|
| **Suite** | One of 8 themed groups. "Accessibility", "Operator OS", etc. A suite is a *promise* ("find and fix accessibility problems"), not a folder. |
| **Project / source** | One of the ~70 real repos on disk. Suites are made *out of* projects. |
| **Wave** | One unit of migration work, like `A2` or `B3`. 43 of them exist. A wave says "move this capability from that old project into this suite, and prove it." |
| **Contract** | A strict data shape that suites hand to each other, like `SourceRecord`. If data does not match the contract, it is rejected. There are 6. |
| **Engine action** | A function you can actually run, like `audit_html_snippet`. There are 50. |
| **Promotion level** | *How good is the evidence* for a claim. This is the important one — see §4. |

The 8 suites:

```
accessibility        Find, explain, repair, teach, and track accessibility problems
operator-os          Preserve context and surface the next safe action when bandwidth is low
brand-publishing     Turn brand truth and sourced ideas into approved, traceable publications
production-house     Move creative work through resumable jobs to verified deliverables
model-behavior-lab   Produce reproducible, evidence-linked model capability profiles
discovery-decision   Turn a hard question and typed evidence into a decision record
agent-reliability    Teach and test bounded agent behavior with deterministic gates
game-design          Turn game rules into simulations, balance evidence, and playables
```

---

## 4. The most important concept: the ladder

Every claim this project makes sits on a rung. Rungs go from "I wrote it down" to "it is
genuinely in daily use." You cannot skip rungs, and **nothing promotes itself.**

```
specified                      Someone described it.
prototype                      There's a fake/fixture version. Proves nothing about the real thing.
reviewed_historical_analysis   A human looked at old evidence and reasoned about it.
source_inspected               We read the real donor code, or parsed its real artifacts.
─────────────────── everything above this line means real code actually RAN ───────────────────
source_executed                We invoked the real donor code and kept a receipt of the invocation.
parity_verified                We ran it AND compared old vs new on success and failure cases.
adopted                        Three real uses, on distinct inputs or days.
converged                      One canonical owner; the duplicate is genuinely retired.
```

Today's honest scoreboard (`status` prints this):

```
4 prototype · 1 reviewed historical · 37 source inspected
0 source executed · 1 parity verified · 0 adopted · 0 converged
```

**Read that carefully, because it is the whole point of the project.** All 43 waves are
marked "complete," and it would be easy to call that 100% done. It is not. Complete means
*the scheduled analysis finished*. Only **one** wave (`A2`) has ever been proven to run
for real. 42 of the 43 still owe a live run. The project reports both numbers side by
side, on purpose, so the good-looking one can never hide the honest one.

Two different questions, two different answers:

- *"How much did we schedule and finish?"* → **43/43. 100%.**
- *"How much is actually proven to work?"* → **1 of 43.**

---

## 5. Getting the most out of it: the four things you'll actually do

### A. Ask what's going on

```bash
PYTHONPATH=src python3 -m portfolio_suites status     # the whole scoreboard
PYTHONPATH=src python3 -m portfolio_suites list       # the 8 suites and their promises
PYTHONPATH=src python3 -m portfolio_suites next       # what to work on, hardest evidence gap first
PYTHONPATH=src python3 -m portfolio_suites inspect accessibility   # one suite in detail
```

`next` is the one to build a habit around. It does not just name a wave; it tells you
when *no command can help you*:

```
NEXT RECOVERY MOVE: brand-publishing / B3 (currently prototype)
  owes: Route a real draft through the actual VCC review path and produce the receipt.
  run:  no command discharges this yet — this is hands-on work against the real runtime.
```

That is the tool refusing to pretend. Believe it.

### B. Run the 50 engine actions

This is where the actual capability lives.

```bash
# See everything available, with signatures
PYTHONPATH=src python3 -m portfolio_suites engine

# Run one
PYTHONPATH=src python3 -m portfolio_suites engine accessibility audit_html_snippet \
  --args '{"html_content": "<img src=\"logo.png\"><button></button>"}'
```

That returns two real findings: the image has no `alt`, and the button has no accessible
name. Same actions are clickable in the web UI's **Toolbench** tab.

`docs/test-protocol.md` has a worked, verified example for every suite. It is the fastest
way to see what each engine can do.

### C. Chain actions together

Feed one action's output into the next with `$from`:

```bash
cat > /tmp/chain.json <<'JSON'
[
 {"suite":"operator-os","action":"capture_source","arguments":{"source_id":"src-sample","origin":"notes/wcag.md","content":"WCAG 2.1 AA requires 4.5:1 contrast.","media_type":"text/markdown","author":"Operator"}},
 {"suite":"accessibility","action":"create_ai_assisted_finding","arguments":{"finding_id":"find-1","rule_id":"wcag-1.4.3-contrast","summary":"Low contrast","target":"p.subtle","hypothesis":{"$from":0,"path":"origin"}}}
]
JSON
PYTHONPATH=src python3 -m portfolio_suites chain /tmp/chain.json
```

**Two things that will trip you up:**

1. **Steps are numbered from 0.** The first step is `step 0`, not step 1. Writing
   `{"$from": 1}` in the second step means "refer to myself" and fails.
2. **`path` must name a field that actually exists.** `SourceRecord` carries
   `source_id`, `origin`, `sha256`, `size_bytes`, `media_type`, `acquired_at`, and
   `provenance` — it deliberately does **not** carry the text you captured. Asking for
   `path: "content"` fails closed with a precise error rather than inventing something.

In the web UI, don't hand-type references at all — click **Use as argument** on a tray
entry and it inserts the correct index for you.

### D. Check for drift

Drift = one of the 70 real projects changed on disk since it was last fingerprinted.

```bash
PYTHONPATH=src python3 -m portfolio_suites drift
```

```
Live Drift Report: 4 drifted out of 58 monitored repos
DRIFT aerocafe    snap=main@3acf28c live=main@3acf28c (dirty=1)
```

Same commit, but one uncommitted file — so it counts as drifted. That is intentional
strictness. Drift is *live* state, which is why no document in this repo ever writes down
a drift count: it would be stale by morning. The CLI is the only honest source.

---

## 6. The write path, and why it is deliberately annoying

Reading is free. **Writing to your filesystem requires an approval token that this
repository cannot create.** From `approvals.py`:

> *Nothing in this repository can mint an operator approval.*

That is the security model in one line. A compromised engine, a confused agent, or a
buggy chain still cannot write, because the authority lives outside the code that wants
to use it. There is a boolean called `operator_approved`, and it looks like permission —
it is not. It only unlocks read-only and dry-run behavior. **The boolean can never reach
a write.**

Here is the real flow, verified end to end in a sandbox:

**Step 1 — run it and get refused.** The refusal tells you the exact digest it needs.

```
status: error_unverified_approval
approval_payload_sha256: 4721c6121152902c94907ea5bb774565e7fc1ceb...
```

You cannot compute that digest yourself, and that is deliberate. It is a fingerprint of
*this exact action, these exact parameters, and every byte the action inventoried*. If
anything changes between now and the write, the digest changes and the write fails.

**Step 2 — issue an approval out of band** into the JSON file named by the
`PORTFOLIO_OPERATOR_APPROVAL_STORE` environment variable. Every field is required:

```json
{"approvals": [{
  "approval_id":   "apr-demo-1",
  "schema":        "operator-approval-v1",
  "token_sha256":  "<sha256 of your secret token>",
  "operation":     "jarvis_action_execution",
  "action_name":   "backup_data",
  "decision":      "approved",
  "reviewer":      "Ryan",
  "payload_sha256": "<the digest from step 1>",
  "issued_at":     "2026-08-25T19:00:00+00:00",
  "expires_at":    "2026-08-25T19:15:00+00:00"
}]}
```

Tokens look like `opa1.<approval_id>.<secret>`. Miss `expires_at` and you get
`approval has no parseable expires_at`. Expired, future-dated, or backwards dates are all
refused.

**Step 3 — re-run with the token.** Now it works:

```
status: success | operator_approval_verified: True
```

**Step 4 — try it again.** It is refused. Approvals are **single-use**. The token is
consumed atomically, so the same authority can never write twice.

If you ever see `error_approval_commit_unverified`, **stop.** It means the system could
not confirm whether the token was spent. Do not retry and do not reissue — go look at the
approval store first. Retrying is exactly the double-spend that error exists to prevent.

---

## 7. The AI assistant, and how much to trust it

```bash
PYTHONPATH=src python3 -m portfolio_suites ai --status --json    # config, never the key
PYTHONPATH=src python3 -m portfolio_suites ai --suite accessibility --role reviewer "your question"
```

Five roles: `orchestrator`, `analyst`, `reviewer`, `creative`, `accessibility`.

**Three things to know:**

1. **It will refuse to send your secrets.** Paste an API key into a prompt and it is
   rejected locally, before any network connection is opened. The check runs early in the
   send path, well before the request goes out.

2. **The model changes every single call.** `openrouter/free` is a *router*, not a model.
   One observed session served six different models across eight calls. Never expect the
   same answer twice — and be aware a bad draw can route to something that cannot answer
   at all. One real call landed on a content-safety classifier that replied `User Safety:
   safe` and nothing else, wearing a perfectly normal-looking label. If an answer looks
   off-topic, just run it again.

3. **It does not know this project's rules unless you hand them over.** Ask it about the
   promotion ladder cold and it will invent something plausible and wrong. Give it the
   standard and it gets it right:

   ```bash
   PYTHONPATH=src python3 -m portfolio_suites ai --suite discovery-decision --role analyst \
     --context docs/RECOVERY-STANDARD.md "What is required to promote a wave?"
   ```

Every answer is stamped `model-assisted ... human review required`. That label is the
whole deal: provider output is never evidence, and never satisfies a gate.

---

## 8. Which document do I read?

| You want | Read |
|---|---|
| To use the thing (you are here) | `docs/ELI5.md` |
| What a word means | `docs/GLOSSARY.md` |
| Why the project exists, its values | `docs/PROJECT-BIBLE.md` |
| The rules for scoring evidence | `docs/RECOVERY-STANDARD.md` |
| Where it's going, v1.0 plan | `docs/ROADMAP.md` |
| What genuinely got done, dated | `docs/CHANGELOG.md` |
| Step-by-step manual verification | `docs/test-protocol.md` |
| Worked examples of the surface | `docs/100-demos.md` |
| Rules for AI agents in this repo | `AGENTS.md` |

---

## 9. Before you commit: the four gates

```bash
# 1. Fast schema and registry validation (~0.2s)
PYTHONPATH=src python3 -m portfolio_suites validate --fast

# 2. All 43 wave gates, nothing recorded (~11s)
PYTHONPATH=src python3 -m portfolio_suites wave --all --no-record

# 3. Full unit test suite (450 tests, ~70s)
PYTHONPATH=src python3 -m unittest discover -s tests

# 4. Packaging gate — NEEDS Python >= 3.11, not macOS system python3
SUITES_WHEEL_SMOKE=1 PYTHONPATH=src python3.12 -m unittest tests.test_wheel_smoke
```

CI runs all four on every push and PR. Green means the deterministic floor holds. It does
**not** mean any wave got promoted — no test can grant a rung.

---

## 10. The seven rules that explain every "why is it like this?"

1. **Nothing promotes itself.** Evidence promotes things, and a human accepts the evidence.
2. **A passing test is not a working feature.** Fixtures prove the harness, not the product.
3. **Complete ≠ done.** 43/43 waves complete, 42 still owe a live run. Both true at once.
4. **Live state belongs in live output.** Drift counts go in the CLI, never in a document.
5. **The tool cannot grant itself authority.** Approvals come from outside, expire, and burn once.
6. **Fail closed.** Unsure? Refuse and explain. Never guess and proceed.
7. **Label the source.** Automated, model-assisted, manual, and unknown never blur together.

If a change you are about to make breaks one of these, it is the change that is wrong.

---

## 11. Quick fixes for things that will confuse you

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError: portfolio_suites` | Missing `PYTHONPATH=src`. |
| `python3 -m portfolio_suites.cli` prints nothing, exits 0 | Wrong module. Drop `.cli` — use `python3 -m portfolio_suites`. |
| Wheel gate fails on a fresh checkout | Your `python3` is 3.9. Use `python3.12`. |
| `step 1 references step 1` | Chain steps count from **0**. |
| `path 'content' has no key 'content'` | `SourceRecord` holds metadata, not the captured body. |
| `blocked_missing_approval` | Working as designed. You need a real token (§6). |
| `error_approval_commit_unverified` | **Do not retry.** Inspect the approval store first. |
| AI answer is nonsense | Free-router drew a bad model. Re-run it. |
| `secret detected` on an AI prompt | Working as designed. Your prompt contained a credential. |
