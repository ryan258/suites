# OpenRouter Configuration

OpenRouter is the single provider boundary for future provider-backed AI work in Portfolio Suites.
Deterministic engines and fixtures remain local; only work that actually requires a model should
cross this boundary.

## Local setup

The repository includes a git-ignored `.env` with an empty key slot. Add the key locally:

```dotenv
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

For a fresh checkout, copy `.env.example` to `.env` and keep the resulting file local. The loader
does not execute shell syntax or interpolate command substitutions, and process environment values
override `.env` values for CI or temporary sessions.

The official default endpoint is `https://openrouter.ai/api/v1`. Optional `HTTP-Referer` and
`X-OpenRouter-Title` attribution headers are derived from `OPENROUTER_APP_URL` and
`OPENROUTER_APP_TITLE`.

## Roles

| Role | Purpose | Default behavior |
|---|---|---|
| `orchestrator` | Route bounded work across suites and contracts | Low-temperature planning |
| `analyst` | Synthesize source-linked evidence | Low-temperature analysis, larger budget |
| `reviewer` | Challenge correctness, safety, and release claims | Deterministic temperature |
| `creative` | Draft governed creative artifacts | Higher-temperature exploration |
| `accessibility` | Explain findings without flattening manual review | Deterministic temperature |

Every role defaults to `openrouter/auto`. Override a role's `*_MODEL` variable with a concrete
OpenRouter model slug when a workflow needs a pinned version. An auto-routed response must retain
the concrete model returned by OpenRouter; a reproducible benchmark must use and record a concrete
model slug rather than the auto router or a moving `latest` alias.

Role variables follow this pattern:

```dotenv
OPENROUTER_ROLE_REVIEWER_MODEL=openrouter/auto
OPENROUTER_ROLE_REVIEWER_TEMPERATURE=0.0
OPENROUTER_ROLE_REVIEWER_MAX_TOKENS=4096
```

## Evidence boundary

Provider-backed evidence must retain the requested role, requested model, resolved concrete model,
provider, request identifier, token usage, timestamps, inputs or input hashes, scorer version,
errors, and limitations. Donor subprocesses launched by suite adapters inherit a scrubbed
environment: `adapters.common.donor_env()` removes any variable whose name matches
`KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL`, so `OPENROUTER_API_KEY` never reaches a donor
runtime. Never write the API key, authorization header, or full local `.env` into
an evidence file, terminal diagnostic, test fixture, or exception.

`portfolio_suites.ai_config.load_openrouter_config()` loads and validates the configuration.
Pass `require_api_key=True` only at the network boundary; local validation and deterministic tests
can inspect role configuration without requiring or exposing a secret.
