"""Source adapter for Discovery + Decision binding waves to real SIF, Forge, and Excavator artifacts."""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256, validate_contract
from ..engines.discovery_decision import DiscoveryDecisionEngine
from .common import get_git_fingerprint, get_repo_path, is_meaningful_git_fingerprint

FORGE_DIR = get_repo_path("breaking-chains", "BREAKING_CHAINS_DIR")
SIF_DIR = get_repo_path("sif", "SIF_DIR")
INSIGHT_DIR = get_repo_path("insight-excavator", "INSIGHT_EXCAVATOR_DIR")

FORGE_TRACKED = ["src/forge/config.py", "src/forge/cli.py", "pyproject.toml", "README.md"]
SIF_TRACKED = ["src/sif/nodes.py", "src/sif/graph.py", "src/sif/schemas.py", "pyproject.toml", "README.md"]
INSIGHT_TRACKED = ["server.py", "import.py", "config.json", "README.md"]

# What each SIF phase produces, and the Forge stage that has to cover it for the port to hold.
SIF_PHASE_ROLES = {
    "phase1": ("premise_extraction", "intake"),
    "phase2": ("divergent_path_search", "connections_generated"),
    "phase3a": ("red_team_analysis", "red_team"),
    "phase3b": ("analogy_synthesis", "analogy"),
    "phase4": ("external_verification", "verification"),
    "phase5": ("synthesis", "decided"),
}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _sif_phase_nodes() -> list[str]:
    """Phase node names declared by the real SIF graph, in source order."""
    source = _read_text(SIF_DIR / "src" / "sif" / "nodes.py") or ""
    seen: list[str] = []
    for name in re.findall(r"async def (phase\w+?)_node\(", source):
        if name not in seen:
            seen.append(name)
    return seen


def _forge_budgets() -> dict[str, int]:
    """Per-mode call budgets as configured in the real Forge runtime."""
    source = _read_text(FORGE_DIR / "src" / "forge" / "config.py") or ""
    return {
        mode: int(value)
        for mode, value in re.findall(r"(\w+)_max_calls: PositiveInt = (\d+)", source)
    }


def _latest_sif_run() -> Path | None:
    """Newest SIF run directory that actually retained phase artifacts."""
    try:
        runs = sorted((SIF_DIR / "runs").iterdir(), reverse=True)
    except OSError:
        return None
    for run in runs:
        if run.is_dir() and any(run.glob("phase*.md")):
            return run
    return None


def _forge_investigation() -> tuple[Path, dict[str, str]] | None:
    """First recorded Forge investigation document, parsed from its own Overview block."""
    try:
        documents = sorted((FORGE_DIR / "outputs" / "investigations").glob("inv_*.md"))
    except OSError:
        return None
    for path in documents:
        text = _read_text(path) or ""
        fields = dict(re.findall(r"^- \*\*(ID|Stage|Status|Depth|Created|Updated):\*\* (.+)$", text, re.M))
        if {"ID", "Stage", "Depth"} <= set(fields):
            return path, {key: value.strip() for key, value in fields.items()}
    return None


def _excavator_document(path: Path) -> dict[str, Any] | None:
    """A real Excavator source with a byte-anchored excerpt that can be re-verified."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    header, separator, body = text.partition("\n---\n")
    if not separator or not body.strip():
        return None
    fields = dict(
        line.split(":", 1) for line in header.splitlines() if ":" in line
    )
    excerpt = body.strip()[:400]
    offset = raw.find(excerpt.encode("utf-8"))
    if offset < 0:
        return None
    excerpt_bytes = excerpt.encode("utf-8")
    return {
        "origin": f"{INSIGHT_DIR.name}/{path.relative_to(INSIGHT_DIR)}",
        "tag": fields.get("tag", "").strip(),
        "label": fields.get("label", "").strip(),
        "excerpt": excerpt,
        "excerpt_offset": offset,
        "excerpt_bytes": len(excerpt_bytes),
        "excerpt_sha256": compute_sha256(excerpt_bytes),
        "excerpt_verified": compute_sha256(raw[offset:offset + len(excerpt_bytes)]) == compute_sha256(excerpt_bytes),
    }


def _shared_terms(first: str, second: str) -> list[str]:
    """Distinctive words present in both documents, measured rather than asserted."""
    def terms(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z]{5,}", text.lower())}
    return sorted(terms(first) & terms(second))


def _source_record(path: Path, origin_repo: Path) -> dict[str, Any] | None:
    """Contract-valid SourceRecord for one real donor document, or None when it cannot be read."""
    try:
        raw = path.read_bytes()
        modified_at = path.stat().st_mtime
    except OSError:
        return None
    return validate_contract("SourceRecord", {
        "schema_version": SCHEMA_VERSION,
        "source_id": f"src-{path.stem[:24]}",
        "origin": f"{origin_repo.name}/{path.relative_to(origin_repo)}",
        "media_type": "text/plain",
        "sha256": compute_sha256(raw),
        "size_bytes": len(raw),
        "acquired_at": datetime.datetime.fromtimestamp(modified_at, datetime.timezone.utc).isoformat(),
        "provenance": {
            "captured_by": "insight_excavator_import",
            "donor_repo": origin_repo.name,
            "retained_locally": True,
        },
    })


def _insight_sources(count: int) -> list[dict[str, Any]]:
    """Deterministically chosen real Excavator source documents as SourceRecords."""
    try:
        paths = sorted((INSIGHT_DIR / "sources").glob("*.txt"))[:count]
    except OSError:
        return []
    records = [_source_record(path, INSIGHT_DIR) for path in paths]
    return [record for record in records if record is not None]


class DiscoveryDecisionSourceAdapter:
    """Reads authentic breaking-chains (Forge), sif, and insight-excavator artifacts."""

    @classmethod
    def execute_d1_sif_forge_stage_matrix(cls) -> dict[str, Any]:
        """D1: Build the SIF-to-Forge parity matrix from real phase nodes, budgets, and artifacts."""
        sif_fp = get_git_fingerprint(SIF_DIR, SIF_TRACKED)
        forge_fp = get_git_fingerprint(FORGE_DIR, FORGE_TRACKED)
        phases = _sif_phase_nodes()
        budgets = _forge_budgets()
        run_dir = _latest_sif_run()
        artifacts = sorted(path.name for path in run_dir.glob("phase*.md")) if run_dir else []

        matrix = []
        for phase in phases:
            role, forge_stage = SIF_PHASE_ROLES.get(phase, ("unmapped", "unmapped"))
            artifact = f"{phase}.md"
            has_artifact = artifact in artifacts
            matrix.append({
                "sif_phase": phase,
                "role": role,
                "forge_stage": forge_stage,
                "typed_inputs": ["question", "prior_stage_output"] if phase != "phase1" else ["question"],
                "typed_outputs": [artifact],
                "budget_calls": budgets.get("standard"),
                "failure_mode": "stage_output_missing",
                "resume_from": "last_completed_stage_artifact",
                "artifact_observed": has_artifact,
                "disposition": "accept" if has_artifact else "reject_no_retained_artifact",
            })

        source_verified = all(is_meaningful_git_fingerprint(fp) for fp in (sif_fp, forge_fp))
        all_stages_passed = (
            source_verified
            and len(matrix) >= 5
            and bool(budgets)
            and all(row["forge_stage"] != "unmapped" for row in matrix)
            and sum(1 for row in matrix if row["disposition"] == "accept") >= 5
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "D1",
            "status": "parity_mapped" if all_stages_passed else "source_unverified",
            "matrix": matrix,
            "forge_budgets": budgets,
            "sif_run_sampled": {
                "run": run_dir.name if run_dir else None,
                "artifacts": artifacts,
            },
            "sif_fingerprint": sif_fp,
            "forge_fingerprint": forge_fp,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def _stage_from_sif_artifact(
        cls,
        wave: str,
        phase: str,
        investigation_id: str,
        stage_name: str,
        mode: str,
    ) -> dict[str, Any]:
        """Carry one real SIF phase artifact into an InvestigationRecord stage under a Forge budget."""
        sif_fp = get_git_fingerprint(SIF_DIR, SIF_TRACKED)
        forge_fp = get_git_fingerprint(FORGE_DIR, FORGE_TRACKED)
        run_dir = _latest_sif_run()
        budgets = _forge_budgets()
        artifact = run_dir / f"{phase}.md" if run_dir else None
        text = _read_text(artifact) if artifact else None
        source_verified = (
            all(is_meaningful_git_fingerprint(fp) for fp in (sif_fp, forge_fp))
            and bool(text)
            and bool(budgets)
        )

        if not source_verified:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": wave,
                "status": "source_unverified",
                "sif_fingerprint": sif_fp,
                "forge_fingerprint": forge_fp,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        headline = next(
            (line.strip("*- ").strip() for line in text.splitlines() if line.strip() and not line.startswith("#")),
            "",
        )
        record = DiscoveryDecisionEngine.create_investigation(
            investigation_id,
            f"SIF {phase} finding ported into Forge {stage_name}",
            mode=mode,
            max_iterations=budgets.get(mode, budgets.get("standard", 10)),
        )
        record = DiscoveryDecisionEngine.advance_stage(
            record,
            stage_name,
            [{
                "kind": "donor_artifact",
                "origin": f"sif/runs/{run_dir.name}/{phase}.md",
                "sha256": compute_sha256(artifact.read_bytes()),
                "bytes": artifact.stat().st_size,
                "headline": headline[:280],
            }],
            [{"decision": f"Adopt {phase} output as the {stage_name} stage of record."}],
            iteration_cost=1,
            status="completed",
        )
        budget = record.get("budget", {})
        all_stages_passed = (
            record.get("status") == "completed"
            and budget.get("used_iterations") == 1
            and budget.get("max_iterations") == budgets.get(mode, budgets.get("standard"))
            and budget["used_iterations"] <= budget["max_iterations"]
            and len(record.get("evidence", [])) == 1
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": wave,
            "status": "stage_ported" if all_stages_passed else "stage_rejected",
            "investigation": record,
            "donor_artifact": record["evidence"][0],
            "budget_source": {"mode": mode, "forge_max_calls": budgets.get(mode)},
            "sif_fingerprint": sif_fp,
            "forge_fingerprint": forge_fp,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_d2_forge_redteam_record(cls) -> dict[str, Any]:
        """D2: Port the real SIF red-team phase behind a bounded Forge mode."""
        return cls._stage_from_sif_artifact("D2", "phase3a", "inv-forge-redteam-01", "red_team", "quick")

    @classmethod
    def execute_d3_insight_excavator_discovery(cls) -> dict[str, Any]:
        """D3: Cite two real Excavator documents by content, with re-verifiable byte anchors.

        ponytail: this reads and anchors donor text; it does not synthesize a discovery. The
        prototype engine's fixed claim, novelty score, and section names are deliberately not
        used — an invented citation is worse than an absent one.
        """
        insight_fp = get_git_fingerprint(INSIGHT_DIR, INSIGHT_TRACKED)
        sources = _insight_sources(2)
        try:
            paths = sorted((INSIGHT_DIR / "sources").glob("*.txt"))[:2]
        except OSError:
            paths = []
        documents = [document for document in (_excavator_document(path) for path in paths) if document]
        source_verified = (
            is_meaningful_git_fingerprint(insight_fp)
            and len(sources) == 2
            and len(documents) == 2
        )
        if not source_verified:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "D3",
                "status": "source_unverified",
                "insight_excavator_fingerprint": insight_fp,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        shared = _shared_terms(documents[0]["excerpt"], documents[1]["excerpt"])
        lexical_overlap = {
            "method": "words of five or more letters occurring in both retained excerpts",
            "shared_terms": shared,
            "shared_term_count": len(shared),
            "semantic_relation_asserted": False,
        }
        all_stages_passed = (
            source_verified
            and all(document["excerpt_verified"] for document in documents)
            and all(document["tag"] and document["label"] for document in documents)
            and all(record["sha256"] and record["size_bytes"] > 0 for record in sources)
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "D3",
            "status": "sources_cited_with_excerpts" if all_stages_passed else "citation_rejected",
            "document_excerpts": documents,
            "lexical_overlap": lexical_overlap,
            "cited_sources": sources,
            "primary_source": sources[0],
            "discovery_limitations": {
                "semantic_discovery_performed": False,
                "novelty_score_measured": False,
                "uncertainty_measured": False,
                "reason": "no Excavator runtime was executed; only donor text was read and anchored",
            },
            "insight_excavator_fingerprint": insight_fp,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_d4_sif_analogy_forge_record(cls) -> dict[str, Any]:
        """D4: Port the real SIF analogy phase through the same bounded Forge path."""
        return cls._stage_from_sif_artifact("D4", "phase3b", "inv-forge-analogy-01", "analogy", "deep")

    @classmethod
    def execute_d5_insight_excavator_citation(cls) -> dict[str, Any]:
        """D5: Fold a real Excavator source into a real Forge investigation as a retained citation."""
        insight_fp = get_git_fingerprint(INSIGHT_DIR, INSIGHT_TRACKED)
        forge_fp = get_git_fingerprint(FORGE_DIR, FORGE_TRACKED)
        parsed = _forge_investigation()
        sources = _insight_sources(1)
        source_verified = (
            all(is_meaningful_git_fingerprint(fp) for fp in (insight_fp, forge_fp))
            and parsed is not None
            and len(sources) == 1
        )
        if not source_verified:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "D5",
                "status": "source_unverified",
                "insight_excavator_fingerprint": insight_fp,
                "forge_fingerprint": forge_fp,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        path, fields = parsed
        record = DiscoveryDecisionEngine.create_investigation(
            fields["ID"],
            f"Forge investigation {fields['ID']} with Excavator citation",
            mode=fields["Depth"] if fields["Depth"] in {"preview", "quick", "standard", "deep", "manual"} else "standard",
        )
        folded = DiscoveryDecisionEngine.ingest_insight_excavator_source(
            record,
            sources[0],
            f"Excavator source retained as citation for Forge stage '{fields.get('Stage')}'.",
        )
        # The engine returns "retired_into_forge_citations" unconditionally, so that string is
        # evidence of nothing. What is checkable is whether the citation carried the source's
        # own provenance into the investigation record.
        citation = next(
            (
                entry
                for entry in folded.get("investigation", {}).get("evidence", [])
                if entry.get("source_id") == sources[0]["source_id"]
            ),
            {},
        )
        retirement = {
            "retirement_performed": False,
            "owner_approval_required": True,
            "standalone_excavator_runtime_removed": False,
            "forge_ingests_source_directly": False,
            "engine_disposition_string": folded.get("insight_excavator_runtime"),
            "engine_disposition_is_prototype_constant": True,
        }
        all_stages_passed = (
            citation.get("sha256") == sources[0]["sha256"]
            and citation.get("origin") == sources[0]["origin"]
            and folded.get("provenance_retained") is True
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "D5",
            "status": "retirement_proposed" if all_stages_passed else "citation_rejected",
            "folded_investigation": folded,
            "retirement": retirement,
            "citation_provenance": citation,
            "forge_investigation": {
                "path": f"breaking-chains/{path.relative_to(FORGE_DIR)}",
                "sha256": compute_sha256(path.read_bytes()),
                **fields,
            },
            "cited_sources": sources,
            "primary_source": sources[0],
            "insight_excavator_fingerprint": insight_fp,
            "forge_fingerprint": forge_fp,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }
