"""Discovery & Decision reference prototype engine powering InvestigationRecords, Forge red-teaming, and SIF analogy generation.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. forge, insight-excavator)."""

from __future__ import annotations

import datetime
import math
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


INVESTIGATION_MODES = {"preview", "quick", "standard", "deep", "manual"}
ADVANCE_STATUSES = {"running", "paused", "failed", "completed"}
MAX_INVESTIGATION_ITERATIONS = 10_000
MAX_INVESTIGATION_TIME_SEC = 86_400
MAX_STAGE_ITEMS = 1_000


def _require_text(name: str, value: Any, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise ValueError(f"{name} must be at most {max_length} characters")
    return cleaned


def _bounded_integer(name: str, value: Any, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _finite_number(name: str, value: Any, *, minimum: float = 0.0) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{name} must be finite and at least {minimum}")
    return number


def _object_list(name: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list of objects")
    if len(value) > MAX_STAGE_ITEMS:
        raise ValueError(f"{name} must contain at most {MAX_STAGE_ITEMS} items")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must contain only objects")
    return value


class DiscoveryDecisionEngine:
    """Manage first-principles investigation lifecycles, stage transitions, and cited discoveries."""

    @staticmethod
    def create_investigation(
        investigation_id: str,
        question: str,
        mode: str = "standard",
        max_iterations: int = 10,
        max_time_sec: int = 300,
    ) -> dict[str, Any]:
        """Initialize a new InvestigationRecord."""
        _require_text("investigation_id", investigation_id, max_length=128)
        question = _require_text("question", question, max_length=10_000)
        if mode not in INVESTIGATION_MODES:
            raise ValueError(f"mode must be one of {', '.join(sorted(INVESTIGATION_MODES))}")
        _bounded_integer(
            "max_iterations",
            max_iterations,
            minimum=1,
            maximum=MAX_INVESTIGATION_ITERATIONS,
        )
        _bounded_integer(
            "max_time_sec",
            max_time_sec,
            minimum=1,
            maximum=MAX_INVESTIGATION_TIME_SEC,
        )
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        inv = {
            "schema_version": SCHEMA_VERSION,
            "investigation_id": investigation_id,
            "question": question,
            "mode": mode,
            "status": "draft",
            "premises": [],
            "evidence": [],
            "stages": [
                {"stage": "intake", "status": "initialized", "timestamp": now_iso}
            ],
            "decisions": [],
            "budget": {
                "max_iterations": max_iterations,
                "used_iterations": 0,
                "max_time_sec": max_time_sec,
                "used_time_sec": 0.0,
            },
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        return validate_contract("InvestigationRecord", inv)

    @staticmethod
    def advance_stage(
        record: dict[str, Any],
        stage_name: str,
        new_evidence: list[dict[str, Any]] | None = None,
        new_decisions: list[dict[str, Any]] | None = None,
        iteration_cost: int = 1,
        time_cost_sec: float = 5.0,
        status: str = "running",
    ) -> dict[str, Any]:
        """Advance an investigation through a Forge mode stage, updating budget counters."""
        if not isinstance(record, dict):
            raise ValueError("record must be an InvestigationRecord object")
        updated = validate_contract("InvestigationRecord", record)
        stage_name = _require_text("stage_name", stage_name, max_length=128)
        if status not in ADVANCE_STATUSES:
            raise ValueError(f"status must be one of {', '.join(sorted(ADVANCE_STATUSES))}")
        _bounded_integer(
            "iteration_cost",
            iteration_cost,
            minimum=0,
            maximum=MAX_INVESTIGATION_ITERATIONS,
        )
        time_cost = _finite_number(
            "time_cost_sec",
            time_cost_sec,
            minimum=0.0,
        )
        evidence_items = _object_list("new_evidence", new_evidence or [])
        decision_items = _object_list("new_decisions", new_decisions or [])

        budget = dict(updated["budget"])
        max_iterations = _bounded_integer(
            "record.budget.max_iterations",
            budget.get("max_iterations"),
            minimum=1,
            maximum=MAX_INVESTIGATION_ITERATIONS,
        )
        used_iterations = _bounded_integer(
            "record.budget.used_iterations",
            budget.get("used_iterations"),
            minimum=0,
            maximum=max_iterations,
        )
        max_time = _finite_number(
            "record.budget.max_time_sec",
            budget.get("max_time_sec"),
            minimum=0.000001,
        )
        if max_time > MAX_INVESTIGATION_TIME_SEC:
            raise ValueError(
                f"record.budget.max_time_sec must be at most {MAX_INVESTIGATION_TIME_SEC}"
            )
        used_time = _finite_number(
            "record.budget.used_time_sec",
            budget.get("used_time_sec"),
            minimum=0.0,
        )
        if used_time > max_time:
            raise ValueError("record budget is already over its time limit")
        if used_iterations + iteration_cost > max_iterations:
            raise ValueError("stage would exceed the investigation iteration budget")
        if used_time + time_cost > max_time:
            raise ValueError("stage would exceed the investigation time budget")

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updated["status"] = status
        updated["updated_at"] = now_iso

        stages = list(updated["stages"])
        stages.append({"stage": stage_name, "status": status, "timestamp": now_iso})
        updated["stages"] = stages

        if evidence_items:
            ev_list = list(updated["evidence"])
            ev_list.extend(evidence_items)
            updated["evidence"] = ev_list

        if decision_items:
            dec_list = list(updated["decisions"])
            dec_list.extend(decision_items)
            updated["decisions"] = dec_list

        budget["used_iterations"] = used_iterations + iteration_cost
        budget["used_time_sec"] = round(used_time + time_cost, 2)
        updated["budget"] = budget

        return validate_contract("InvestigationRecord", updated)

    @staticmethod
    def discover_across_sources(
        source_a: dict[str, Any],
        source_b: dict[str, Any],
        query: str,
    ) -> dict[str, Any]:
        """Compare two cited SourceRecords without inventing semantic conclusions."""
        if not isinstance(source_a, dict) or not isinstance(source_b, dict):
            raise ValueError("source_a and source_b must be SourceRecord objects")
        source_a = validate_contract("SourceRecord", source_a)
        source_b = validate_contract("SourceRecord", source_b)
        query = _require_text("query", query, max_length=10_000)
        if source_a["source_id"] == source_b["source_id"]:
            raise ValueError("source_a and source_b must be independently addressable records")

        same_digest = source_a["sha256"] == source_b["sha256"]
        same_origin = source_a["origin"] == source_b["origin"]
        # Backwards-compatible score field, now explicitly scoped to metadata distinctness.
        # It is not evidence that the source contents contain a novel semantic relationship.
        metadata_distinctness = 0.6
        if not same_digest:
            metadata_distinctness += 0.25
        if not same_origin:
            metadata_distinctness += 0.15
        metadata_distinctness = round(min(metadata_distinctness, 1.0), 2)
        if same_digest:
            claim = (
                f"{source_a['source_id']} and {source_b['source_id']} reference the same "
                "content digest; no content-level relationship was inferred."
            )
        else:
            claim = (
                f"{source_a['source_id']} and {source_b['source_id']} reference distinct "
                "content digests; semantic comparison still requires an evidence-producing stage."
            )
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "query": query,
            "timestamp": now_iso,
            "sources": [
                {"source_id": source_a["source_id"], "sha256": source_a["sha256"], "origin": source_a["origin"]},
                {"source_id": source_b["source_id"], "sha256": source_b["sha256"], "origin": source_b["origin"]},
            ],
            "synthesized_claim": claim,
            "novelty_score": metadata_distinctness,
            "novelty_score_kind": "metadata_distinctness_not_semantic_novelty",
            "semantic_analysis_performed": False,
            "requires_review": True,
            "uncertainty": "high",
            "cited_locations": [
                {"source": source_a["source_id"], "field": "sha256", "value": source_a["sha256"]},
                {"source": source_b["source_id"], "field": "sha256", "value": source_b["sha256"]},
            ],
        }

    @staticmethod
    def execute_sif_analogy_stage(
        investigation_id: str,
        question: str,
        analogy_domain: str = "distributed_consensus",
    ) -> dict[str, Any]:
        """Port SIF second stage (analogy synthesis & divergent search) through Forge (D4 wave)."""
        analogy_domain = _require_text("analogy_domain", analogy_domain, max_length=128)
        safe_domain = analogy_domain.replace(" ", "_")
        inv = DiscoveryDecisionEngine.create_investigation(
            investigation_id=investigation_id,
            question=question,
            mode="deep",
            max_iterations=15,
            max_time_sec=600,
        )
        inv = DiscoveryDecisionEngine.advance_stage(
            record=inv,
            stage_name="analogy_synthesis",
            new_evidence=[
                {
                    "source": f"analogy://{safe_domain}",
                    "mapping": (
                        f"Candidate analogy between the investigation question and "
                        f"{analogy_domain}; no live SIF or model evaluation was performed."
                    ),
                    "confidence": 0.0,
                    "evidence_kind": "deterministic_prototype_candidate",
                    "semantic_validation_performed": False,
                }
            ],
            new_decisions=[
                {
                    "decision": f"Retain the {analogy_domain} analogy as an unvalidated hypothesis",
                    "rationale": "A canonical runtime or reviewer must validate it before adoption.",
                    "decision_status": "proposed",
                }
            ],
            iteration_cost=2,
            time_cost_sec=25.0,
            status="completed",
        )
        return inv

    @staticmethod
    def ingest_insight_excavator_source(
        investigation: dict[str, Any],
        source_record: dict[str, Any],
        extracted_insight: str,
    ) -> dict[str, Any]:
        """Fold Insight Excavator into Forge as cited discovery without separate runtime (D5 wave)."""
        if not isinstance(investigation, dict) or not isinstance(source_record, dict):
            raise ValueError("investigation and source_record must be objects")
        investigation = validate_contract("InvestigationRecord", investigation)
        source_record = validate_contract("SourceRecord", source_record)
        extracted_insight = _require_text(
            "extracted_insight",
            extracted_insight,
            max_length=10_000,
        )
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updated_inv = DiscoveryDecisionEngine.advance_stage(
            record=investigation,
            stage_name="insight_excavation_citation",
            new_evidence=[
                {
                    "source_id": source_record["source_id"],
                    "sha256": source_record["sha256"],
                    "origin": source_record["origin"],
                    "extracted_insight": extracted_insight,
                    "cited_at": now_iso,
                }
            ],
            new_decisions=[
                {
                    "decision": f"Retain cited insight from {source_record['source_id']}",
                    "decision_status": "proposed",
                }
            ],
            iteration_cost=1,
            time_cost_sec=8.5,
            status="completed",
        )
        return {
            "investigation": updated_inv,
            # Compatibility label retained for existing consumers; the explicit truth fields
            # below make clear that this prototype call does not retire or remove any runtime.
            "insight_excavator_runtime": "retired_into_forge_citations",
            "runtime_disposition_kind": "prototype_target_label",
            "retirement_performed": False,
            "standalone_runtime_removed": False,
            "provenance_retained": True,
        }
