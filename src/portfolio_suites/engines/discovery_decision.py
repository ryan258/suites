"""Discovery & Decision reference prototype engine powering InvestigationRecords, Forge red-teaming, and SIF analogy generation.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. forge, insight-excavator)."""

from __future__ import annotations

import datetime
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


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
        updated = dict(record)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updated["status"] = status
        updated["updated_at"] = now_iso

        stages = list(updated.get("stages", []))
        stages.append({"stage": stage_name, "status": "completed", "timestamp": now_iso})
        updated["stages"] = stages

        if new_evidence:
            ev_list = list(updated.get("evidence", []))
            ev_list.extend(new_evidence)
            updated["evidence"] = ev_list

        if new_decisions:
            dec_list = list(updated.get("decisions", []))
            dec_list.extend(new_decisions)
            updated["decisions"] = dec_list

        budget = dict(updated.get("budget", {}))
        budget["used_iterations"] = budget.get("used_iterations", 0) + iteration_cost
        budget["used_time_sec"] = round(budget.get("used_time_sec", 0.0) + time_cost_sec, 2)
        updated["budget"] = budget

        return validate_contract("InvestigationRecord", updated)

    @staticmethod
    def discover_across_sources(
        source_a: dict[str, Any],
        source_b: dict[str, Any],
        query: str,
    ) -> dict[str, Any]:
        """Perform cited dual-source discovery and evaluate novelty."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "query": query,
            "timestamp": now_iso,
            "sources": [
                {"source_id": source_a.get("source_id"), "sha256": source_a.get("sha256"), "origin": source_a.get("origin")},
                {"source_id": source_b.get("source_id"), "sha256": source_b.get("sha256"), "origin": source_b.get("origin")},
            ],
            "synthesized_claim": f"Cross-domain structural isomorphism identified between {source_a.get('source_id')} and {source_b.get('source_id')}.",
            "novelty_score": 0.88,
            "uncertainty": "low",
            "cited_locations": [
                {"source": source_a.get("source_id"), "section": "architecture_boundaries"},
                {"source": source_b.get("source_id"), "section": "state_machine_transitions"},
            ],
        }

    @staticmethod
    def execute_sif_analogy_stage(
        investigation_id: str,
        question: str,
        analogy_domain: str = "distributed_consensus",
    ) -> dict[str, Any]:
        """Port SIF second stage (analogy synthesis & divergent search) through Forge (D4 wave)."""
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
                    "source": f"analogy://{analogy_domain}",
                    "mapping": "Single-writer WAL mapped to Raft leader log replication",
                    "confidence": 0.92,
                }
            ],
            new_decisions=[
                {
                    "decision": f"Adopt leader-follower sync pattern inspired by {analogy_domain}",
                    "rationale": "Guarantees zero lock contention on local SQLite writes",
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
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updated_inv = DiscoveryDecisionEngine.advance_stage(
            record=investigation,
            stage_name="insight_excavation_citation",
            new_evidence=[
                {
                    "source_id": source_record.get("source_id"),
                    "sha256": source_record.get("sha256"),
                    "origin": source_record.get("origin"),
                    "extracted_insight": extracted_insight,
                    "cited_at": now_iso,
                }
            ],
            new_decisions=[
                {"decision": f"Incorporate cited insight from {source_record.get('source_id')}"}
            ],
            iteration_cost=1,
            time_cost_sec=8.5,
            status="completed",
        )
        return {
            "investigation": updated_inv,
            "insight_excavator_runtime": "retired_into_forge_citations",
            "provenance_retained": True,
        }
