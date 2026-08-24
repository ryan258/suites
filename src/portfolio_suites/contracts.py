"""Dependency-free validation and builders for the portfolio's cross-suite contracts."""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .paths import SUITES_ROOT

SCHEMA_VERSION = "1.0.0"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$")


class ContractError(ValueError):
    """Raised when a cross-suite artifact violates its stable contract."""


@dataclass(frozen=True)
class ContractSpec:
    required: frozenset[str]
    list_fields: frozenset[str] = frozenset()
    mapping_fields: frozenset[str] = frozenset()
    enums: Mapping[str, frozenset[str]] | None = None
    description: str = ""


CONTRACTS: dict[str, ContractSpec] = {
    "A11yFinding": ContractSpec(
        required=frozenset(
            {"schema_version", "finding_id", "rule_id", "severity", "summary", "target",
             "evidence", "evidence_kind", "needs_review", "status"}
        ),
        list_fields=frozenset({"evidence"}),
        enums={
            "severity": frozenset({"info", "minor", "moderate", "serious", "critical"}),
            "evidence_kind": frozenset({"deterministic", "ai-assisted", "manual"}),
            "status": frozenset({"open", "accepted", "fixed", "false-positive", "deferred"}),
        },
        description="Structured accessibility issue finding with provenance and review boundary.",
    ),
    "SourceRecord": ContractSpec(
        required=frozenset(
            {"schema_version", "source_id", "acquired_at", "sha256", "size_bytes",
             "media_type", "origin", "provenance"}
        ),
        mapping_fields=frozenset({"provenance"}),
        description="Immutable content-addressed record of ingested source artifact.",
    ),
    "BrandPackage": ContractSpec(
        required=frozenset(
            {"schema_version", "package_id", "brand_id", "version", "approved_at", "identity",
             "voice", "audience", "approved_claims", "assets", "usage_rules", "provenance"}
        ),
        list_fields=frozenset({"approved_claims", "assets", "usage_rules", "provenance"}),
        mapping_fields=frozenset({"identity", "voice", "audience"}),
        description="Governed brand truth package with version pinning and mutation protection.",
    ),
    "ProductionJob": ContractSpec(
        required=frozenset(
            {"schema_version", "job_id", "domain", "task", "status", "inputs", "outputs",
             "events", "created_at", "updated_at"}
        ),
        list_fields=frozenset({"inputs", "outputs", "events"}),
        enums={"status": frozenset({"queued", "running", "blocked", "failed", "completed", "cancelled"})},
        description="Resumable production job state machine tracking multi-step creative tasks.",
    ),
    "ExperimentRun": ContractSpec(
        required=frozenset(
            {"schema_version", "run_id", "benchmark_id", "benchmark_version", "provider", "model",
             "parameters", "scorer", "scorer_version", "status", "iterations", "evidence", "errors"}
        ),
        list_fields=frozenset({"iterations", "evidence", "errors"}),
        mapping_fields=frozenset({"parameters"}),
        enums={"status": frozenset({"planned", "running", "partial", "failed", "completed"})},
        description="Reproducible model evaluation run with parameter matrix and scoring evidence.",
    ),
    "InvestigationRecord": ContractSpec(
        required=frozenset(
            {"schema_version", "investigation_id", "question", "mode", "status", "premises",
             "evidence", "stages", "decisions", "budget", "created_at", "updated_at"}
        ),
        list_fields=frozenset({"premises", "evidence", "stages", "decisions"}),
        mapping_fields=frozenset({"budget"}),
        enums={
            "mode": frozenset({"preview", "quick", "standard", "deep", "manual"}),
            "status": frozenset({"draft", "running", "paused", "failed", "completed"}),
        },
        description="Resumable first-principles investigation record with typed stages and budgets.",
    ),
}


SCHEMA_DIR = SUITES_ROOT / "contracts"
JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}

RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


@lru_cache(maxsize=1)
def _published_schema_documents() -> dict[str, dict[str, Any]]:
    """Full published JSON Schema documents, keyed by contract title."""
    paths = sorted(SCHEMA_DIR.glob("*.schema.json"))
    if not paths:
        raise ContractError(f"published contract schemas are missing from {SCHEMA_DIR}")

    schemas: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ContractError(f"published contract schema cannot be loaded: {path}: {error}") from error
        if not isinstance(document, dict):
            raise ContractError(f"published contract schema must be an object: {path}")
        title = document.get("title")
        if not isinstance(title, str):
            raise ContractError(f"published contract schema needs string title: {path}")
        if title in schemas:
            raise ContractError(f"duplicate published contract schema title: {title}")
        schemas[title] = document

    missing = sorted(set(CONTRACTS) - set(schemas))
    unknown = sorted(set(schemas) - set(CONTRACTS))
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown: {', '.join(unknown)}")
        raise ContractError(f"published contract schema coverage is incomplete ({'; '.join(details)})")
    return schemas


def _resolve_ref(schema_doc: dict[str, Any], ref: str) -> dict[str, Any]:
    if ref.startswith("#/$defs/"):
        def_name = ref[len("#/$defs/"):]
        defs = schema_doc.get("$defs", {})
        if isinstance(defs, dict) and def_name in defs and isinstance(defs[def_name], dict):
            return defs[def_name]
    raise ContractError(f"unresolvable schema ref: {ref}")


def _validate_schema_node(
    schema_doc: dict[str, Any],
    node_schema: dict[str, Any],
    value: Any,
    path: str,
) -> None:
    if "$ref" in node_schema:
        target = _resolve_ref(schema_doc, node_schema["$ref"])
        _validate_schema_node(schema_doc, target, value, path)
        return

    if "const" in node_schema and value != node_schema["const"]:
        raise ContractError(f"{path} must equal {node_schema['const']!r}")

    if "enum" in node_schema:
        if value not in node_schema["enum"]:
            options = ", ".join(str(opt) for opt in node_schema["enum"])
            raise ContractError(f"{path} must be one of {options}")

    expected = node_schema.get("type")
    if isinstance(expected, str):
        allowed = JSON_TYPES.get(expected)
        if allowed and (
            not isinstance(value, allowed)
            or (expected in {"integer", "number"} and isinstance(value, bool))
        ):
            raise ContractError(f"{path} must be a JSON {expected}")
    elif isinstance(expected, (list, tuple, set)):
        types_allowed = tuple(t for exp in expected if exp in JSON_TYPES for t in JSON_TYPES[exp])
        if not isinstance(value, types_allowed):
            raise ContractError(f"{path} must be one of JSON types {list(expected)}")

    if node_schema.get("format") == "date-time":
        if not isinstance(value, str) or not RFC3339_DATE_TIME.fullmatch(value):
            raise ContractError(f"{path} must be an RFC 3339 date-time with timezone")
        try:
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ContractError(f"{path} must be a valid RFC 3339 date-time") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ContractError(f"{path} must include a timezone")

    minimum = node_schema.get("minimum")
    if minimum is not None:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < minimum:
            raise ContractError(f"{path} must be at least {minimum}")

    min_length = node_schema.get("minLength")
    if min_length is not None and (not isinstance(value, str) or len(value) < min_length):
        raise ContractError(f"{path} must contain at least {min_length} character(s)")

    pattern = node_schema.get("pattern")
    if isinstance(pattern, str) and (not isinstance(value, str) or re.search(pattern, value) is None):
        raise ContractError(f"{path} does not match its published pattern")

    if isinstance(value, list):
        min_items = node_schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            raise ContractError(f"{path} must contain at least {min_items} item(s)")
        items_schema = node_schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(value):
                _validate_schema_node(schema_doc, items_schema, item, f"{path}[{i}]")

    if isinstance(value, dict):
        min_properties = node_schema.get("minProperties")
        if min_properties is not None and len(value) < min_properties:
            raise ContractError(f"{path} must contain at least {min_properties} propert(y/ies)")

        required_props = node_schema.get("required")
        if isinstance(required_props, (list, set, tuple)):
            missing_props = [k for k in required_props if k not in value]
            if missing_props:
                raise ContractError(f"{path} missing required fields: {', '.join(missing_props)}")

    if "anyOf" in node_schema:
        variants = node_schema["anyOf"]
        if isinstance(variants, list):
            passed_any = False
            for variant in variants:
                try:
                    _validate_schema_node(schema_doc, variant, value, path)
                    passed_any = True
                    break
                except ContractError:
                    continue
            if not passed_any:
                raise ContractError(f"{path} does not match any allowed schema variant in anyOf")

    if "oneOf" in node_schema:
        variants = node_schema["oneOf"]
        if isinstance(variants, list):
            match_count = 0
            for variant in variants:
                try:
                    _validate_schema_node(schema_doc, variant, value, path)
                    match_count += 1
                except ContractError:
                    continue
            if match_count != 1:
                raise ContractError(f"{path} must match exactly one schema variant in oneOf (matched {match_count})")

    if isinstance(value, dict):
        properties = node_schema.get("properties")
        if isinstance(properties, dict):
            for prop_name, prop_schema in properties.items():
                if prop_name in value and isinstance(prop_schema, dict):
                    _validate_schema_node(schema_doc, prop_schema, value[prop_name], f"{path}.{prop_name}")


def _check_published_types(name: str, payload: Mapping[str, Any]) -> None:
    """Enforce the published JSON schema recursively for the payload."""
    doc = _published_schema_documents().get(name)
    if not doc:
        return
    _validate_schema_node(doc, doc, payload, name)


def _check_strict_json(value: Any, path: str) -> None:
    """Reject values Python's permissive encoder would coerce into non-strict JSON."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"{path} must not contain NaN or infinity")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{path} object keys must be strings")
            _check_strict_json(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _check_strict_json(child, f"{path}[{index}]")
        return
    raise ContractError(f"{path} contains non-JSON value {type(value).__name__}")


def _require_identifier(field: str, value: Any) -> None:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractError(f"{field} must be a stable 3-128 character identifier")


def validate_contract(name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a detached, JSON-safe contract payload."""
    if name not in CONTRACTS:
        raise ContractError(f"unknown contract: {name}")
    if not isinstance(payload, Mapping):
        raise ContractError(f"{name} must be a JSON object")

    _check_strict_json(payload, name)

    spec = CONTRACTS[name]
    missing = sorted(spec.required - payload.keys())
    if missing:
        raise ContractError(f"{name} missing required fields: {', '.join(missing)}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"{name} schema_version must be {SCHEMA_VERSION}")

    # Keep the stable, domain-specific diagnostics for constraints that predate the generic
    # published-keyword validator; callers use these messages to explain remediation.
    if name == "BrandPackage" and (
        not isinstance(payload.get("version"), str)
        or not SEMVER.fullmatch(payload.get("version", ""))
    ):
        raise ContractError("BrandPackage.version must be semantic x.y.z")
    if name == "ExperimentRun":
        if not isinstance(payload.get("benchmark_version"), str) or not payload.get("benchmark_version"):
            raise ContractError("ExperimentRun.benchmark_version is required")
        if not isinstance(payload.get("scorer_version"), str) or not payload.get("scorer_version"):
            raise ContractError("ExperimentRun.scorer_version is required")

    _check_published_types(name, payload)

    for field in spec.list_fields:
        if not isinstance(payload.get(field), list):
            raise ContractError(f"{name}.{field} must be a list")
    for field in spec.mapping_fields:
        if not isinstance(payload.get(field), Mapping):
            raise ContractError(f"{name}.{field} must be an object")
    for field, values in (spec.enums or {}).items():
        value = payload.get(field)
        if not isinstance(value, str) or value not in values:
            raise ContractError(f"{name}.{field} must be one of {', '.join(sorted(values))}")

    id_field = {
        "A11yFinding": "finding_id",
        "SourceRecord": "source_id",
        "BrandPackage": "package_id",
        "ProductionJob": "job_id",
        "ExperimentRun": "run_id",
        "InvestigationRecord": "investigation_id",
    }[name]
    _require_identifier(id_field, payload.get(id_field))

    if name == "A11yFinding":
        if payload.get("evidence_kind") == "deterministic" and not payload.get("evidence"):
            raise ContractError("deterministic A11yFinding requires evidence")
        if payload.get("evidence_kind") == "ai-assisted" and payload.get("needs_review") is not True:
            raise ContractError("AI-assisted A11yFinding must remain needs_review")
    elif name == "SourceRecord":
        if not isinstance(payload.get("sha256"), str) or not SHA256.fullmatch(payload.get("sha256", "")):
            raise ContractError("SourceRecord.sha256 must be a lowercase SHA-256 digest")
        if not isinstance(payload.get("size_bytes"), int) or payload.get("size_bytes", -1) < 0:
            raise ContractError("SourceRecord.size_bytes must be a non-negative integer")
    elif name == "BrandPackage":
        if not isinstance(payload.get("version"), str) or not SEMVER.fullmatch(payload.get("version", "")):
            raise ContractError("BrandPackage.version must be semantic x.y.z")
        if not payload.get("provenance"):
            raise ContractError("BrandPackage requires at least one provenance reference")
    elif name == "ExperimentRun":
        if not isinstance(payload.get("benchmark_version"), str) or not payload.get("benchmark_version"):
            raise ContractError("ExperimentRun.benchmark_version is required")
        if not isinstance(payload.get("scorer_version"), str) or not payload.get("scorer_version"):
            raise ContractError("ExperimentRun.scorer_version is required")

    try:
        return json.loads(json.dumps(dict(payload), allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ContractError(f"{name} must be JSON serializable: {error}") from error


def validate_json_str(name: str, raw_json: str) -> dict[str, Any]:
    """Parse string and validate against named contract."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON syntax: {exc}") from exc
    return validate_contract(name, data)


def compute_sha256(content: str | bytes) -> str:
    """Compute sha256 hex digest for string or bytes."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def generate_sample(name: str) -> dict[str, Any]:
    """Generate a clean, validated sample payload for any of the 6 contracts."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dummy_sha = hashlib.sha256(b"sample content").hexdigest()

    samples: dict[str, dict[str, Any]] = {
        "A11yFinding": {
            "schema_version": SCHEMA_VERSION,
            "finding_id": "find-wcag-331-001",
            "rule_id": "wcag-3.3.1-error-identification",
            "severity": "critical",
            "summary": "Form input error message missing aria-describedby linkage",
            "target": "form#checkout input#billing-zip",
            "evidence": [
                {
                    "dom_snippet": "<input id=\"billing-zip\" class=\"is-invalid\">",
                    "error_element": "<span class=\"error-msg\">Zip required</span>",
                    "selector": "#billing-zip",
                    "timestamp": now_iso
                }
            ],
            "evidence_kind": "deterministic",
            "needs_review": False,
            "status": "open"
        },
        "SourceRecord": {
            "schema_version": SCHEMA_VERSION,
            "source_id": "src-2026-08-brand-notes",
            "acquired_at": now_iso,
            "sha256": dummy_sha,
            "size_bytes": 1024,
            "media_type": "text/markdown",
            "origin": "local://notes/brand-brief.md",
            "provenance": {
                "author": "Ryan",
                "collector": "portfolio_suites.engines.operator_os",
                "intake_method": "file_watch"
            }
        },
        "BrandPackage": {
            "schema_version": SCHEMA_VERSION,
            "package_id": "pkg-brand-cyborg-v1",
            "brand_id": "brand-cyborg-systems",
            "version": "1.0.0",
            "approved_at": now_iso,
            "identity": {
                "name": "Cyborg Systems",
                "tagline": "Cognitive amplifier for high-signal operators",
                "palette": {"primary": "#00f0ff", "surface": "#0a0d14", "accent": "#7928ca"}
            },
            "voice": {
                "tone": "direct, grounded, recoverable",
                "guidelines": ["No hype", "Lead with outcomes", "Clear recovery steps"]
            },
            "audience": {
                "primary": "Autonomous technical operators and high-cognitive builders"
            },
            "approved_claims": [
                {"id": "clm-1", "claim": "Zero-dependency local-first portfolio control plane"}
            ],
            "assets": [
                {"asset_id": "logo-svg", "type": "image/svg+xml", "path": "assets/logo.svg"}
            ],
            "usage_rules": [
                "Always pair cyan accent with dark surface",
                "Never omit provenance links"
            ],
            "provenance": [
                {"source_id": "src-brand-canon-v1", "applied_by": "brand_maker"}
            ]
        },
        "ProductionJob": {
            "schema_version": SCHEMA_VERSION,
            "job_id": "job-gw-ep12-render",
            "domain": "groundwire-audio-play",
            "task": "render-dialogue-stems",
            "status": "completed",
            "inputs": [
                {"name": "script.fountain", "sha256": dummy_sha}
            ],
            "outputs": [
                {"name": "master-audio.wav", "sha256": dummy_sha, "duration_sec": 420.5}
            ],
            "events": [
                {"time": now_iso, "stage": "parse_script", "status": "ok"},
                {"time": now_iso, "stage": "synthesize_voices", "status": "ok"}
            ],
            "created_at": now_iso,
            "updated_at": now_iso
        },
        "ExperimentRun": {
            "schema_version": SCHEMA_VERSION,
            "run_id": "run-mbl-ethics-042",
            "benchmark_id": "bench-ethics-scenarios",
            "benchmark_version": "2.1.0",
            "provider": "openrouter",
            "model": "openrouter/auto",
            "parameters": {
                "temperature": 0.2,
                "max_tokens": 2048,
                "seed": 42
            },
            "scorer": "deterministic_logic_scorer",
            "scorer_version": "1.4.0",
            "status": "completed",
            "iterations": [
                {"iteration": 1, "passed": True, "score": 0.96, "latency_ms": 840}
            ],
            "evidence": [
                {"prompt_sha": dummy_sha, "response_sha": dummy_sha, "metrics": {"alignment": 0.98}}
            ],
            "errors": []
        },
        "InvestigationRecord": {
            "schema_version": SCHEMA_VERSION,
            "investigation_id": "inv-db-consolidation-q3",
            "question": "Should the telemetry store be unified into SQLite WAL mode?",
            "mode": "standard",
            "status": "completed",
            "premises": [
                {"id": "p1", "text": "Single operator writes; high read concurrency required."}
            ],
            "evidence": [
                {"id": "ev1", "source": "benchmarks/sqlite-wal.json", "finding": "12000 writes/sec achieved"}
            ],
            "stages": [
                {"stage": "divergent_search", "status": "done"},
                {"stage": "red_team_analysis", "status": "done"},
                {"stage": "synthesis", "status": "done"}
            ],
            "decisions": [
                {"decision": "Adopt SQLite WAL mode with 60s checkpointing."}
            ],
            "budget": {
                "max_iterations": 10,
                "used_iterations": 3,
                "max_time_sec": 300,
                "used_time_sec": 42.1
            },
            "created_at": now_iso,
            "updated_at": now_iso
        }
    }
    sample = samples.get(name)
    if not sample:
        raise ContractError(f"no sample available for {name}")
    return validate_contract(name, sample)
