# Stable CLI/API Surface (v1 freeze policy)

The supported control-plane surface is pinned by `tests/fixtures/stable-surface.json` and checked by
`tests/test_stable_surface.py`. The golden file records every CLI command, alias, option, positional
and choice, every `/api` route literal in `server.py`, and the exit codes. A failing check means the
surface changed and needs a compatibility decision.

## Frozen

- **Command names, aliases, options, positionals, and choices** in the golden file.
- **Exit codes:** `0` ok, `1` failed (product failure or refused input), `2` incomplete (the gate could
  not run or the work is not finished, such as a blocked environment, an unconfigured provider, or
  `release` not ready). `2` is never a pass.
- **`--json` output** (`validate`, `release`, `export`, `release blockers`): existing keys keep their
  names and meaning.
- **API routes** and their JSON keys: existing keys keep their meaning; HTTP status classes follow
  the same ok / refused / incomplete split.
- **Persisted formats:** governed by the contract/state freeze, see [PLATFORM-OPERATIONS.md](PLATFORM-OPERATIONS.md).

## Error taxonomy

Every API error body is JSON with an `error` key: a string, or an object with `code` and `message`
for the AI endpoints. Status classes are fixed; the golden file pins the exact set the server uses.

| Status | Category | Meaning |
|---|---|---|
| 400 | invalid input | malformed or missing request data |
| 403 | refused | cross-origin, non-loopback, or CLI-only action; fails closed |
| 404 | not found | unknown endpoint, suite, project, document, or evidence file |
| 405 | wrong method | the action needs the documented POST endpoint |
| 409 | conflict | stale revision or concurrent writer; reload and retry |
| 422 | action failed | an engine action ran and reported failure |
| 500 | internal | unexpected fault; details withheld |
| 503 | unavailable | the action could not complete; `save_state` reports whether a commit may have happened |

CLI errors use the exit codes above. AI errors keep their `code` strings (for example
`not_configured`, `invalid_input`, `rate_limited`); `not_configured` and `invalid_input` exit `2`.

## May evolve

- Human-readable (non-`--json`) text, wording, ordering, column widths, and help text.
- Additional JSON keys, new commands, new options, and new `/api` routes (additive).

## Compatibility rules

- **Additive:** a new command, option, route, or JSON key. Update the golden file; no version change.
- **Breaking:** removing or renaming a command, option, route, or JSON key, changing an exit code
  meaning, or changing an option's semantics. It reopens `phase1.stable-surface` and needs a changelog
  entry and an owner decision.
- **Security fixes** may refuse input that was previously accepted; record them in the changelog.

Configuration, environment variables, root discovery, and diagnostics are documented in
[PLATFORM-OPERATIONS.md](PLATFORM-OPERATIONS.md).
