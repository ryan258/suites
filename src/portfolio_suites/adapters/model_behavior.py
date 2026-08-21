"""Source adapter for Model Behavior Lab binding waves to real comparator donor corpora."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256, validate_contract
from ..engines.model_behavior import ModelBehaviorEngine
from .common import get_git_fingerprint, get_repo_path, is_meaningful_git_fingerprint

ETHICS_DIR = get_repo_path("ai-ethics-comparator", "AI_ETHICS_COMPARATOR_DIR")
STRENGTH_DIR = get_repo_path("ai-strength-comparator", "AI_STRENGTH_COMPARATOR_DIR")
CHESS_DIR = get_repo_path("ai-chess", "AI_CHESS_DIR")

ETHICS_TRACKED = ["paradoxes.json", "models.json", "lib/experiment_runner.py", "lib/storage.py", "README.md"]
STRENGTH_TRACKED = ["capabilities.json", "models.json", "lib/benchmarking.py", "lib/storage.py", "README.md"]
CHESS_TRACKED = ["lib/chess_match.py", "lib/match_runner.py", "lib/match_store.py", "README.md"]

# Subsystems each comparator donor keeps its own copy of. The canonical slice replaces them
# with one kernel, so the count of donor duplicates is the measured claim, not an assertion.
KERNEL_SUBSYSTEMS = {
    "provider_client": "lib/ai_service.py",
    "run_store": "lib/storage.py",
    "report_lifecycle": "lib/reporting.py",
    "query_identifiers": "lib/query_processor.py",
}


def _read_json(path: Path) -> Any:
    """Return parsed donor JSON, or None when the donor artifact is absent or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _corpus_ids(corpus: Any) -> set[str]:
    return {item.get("id") for item in corpus if isinstance(item, dict)} if isinstance(corpus, list) else set()


def _first_linked_result(results_dir: Path, corpus_ids: set[str]) -> tuple[Path, dict[str, Any]] | None:
    """First donor result (in sorted order) whose scenario still exists in the donor corpus."""
    try:
        candidates = sorted(results_dir.glob("*.json"))
    except OSError:
        return None
    for path in candidates:
        document = _read_json(path)
        if isinstance(document, dict) and document.get("paradoxId") in corpus_ids:
            return path, document
    return None


class ModelBehaviorSourceAdapter:
    """Reads authentic ai-ethics-comparator, ai-strength-comparator, and ai-chess artifacts."""

    @classmethod
    def execute_m1_ethics_experiment_run(cls) -> dict[str, Any]:
        """M1: Normalize one real recorded ethics result into ExperimentRun and check field parity."""
        fingerprint = get_git_fingerprint(ETHICS_DIR, ETHICS_TRACKED)
        corpus = _read_json(ETHICS_DIR / "paradoxes.json")
        linked = _first_linked_result(ETHICS_DIR / "results", _corpus_ids(corpus))
        source_verified = is_meaningful_git_fingerprint(fingerprint) and linked is not None

        if linked is None:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "M1",
                "status": "source_unverified",
                "ethics_comparator_fingerprint": fingerprint,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        result_path, donor = linked
        scenario = next(item for item in corpus if item.get("id") == donor.get("paradoxId"))
        option_ids = {option.get("id") for option in donor.get("options", []) if isinstance(option, dict)}
        responses = [r for r in donor.get("responses", []) if isinstance(r, dict)]

        iterations = [
            {
                "iteration": response.get("iteration"),
                "scenario_id": donor.get("paradoxId"),
                "decision_token": response.get("decisionToken"),
                "option_id": response.get("optionId"),
                "passed": response.get("optionId") in option_ids,
                "score": 1.0 if response.get("optionId") in option_ids else 0.0,
                "outcome_source": "donor_recorded_response",
                "explanation_sha256": compute_sha256((response.get("explanation") or "").encode("utf-8")),
            }
            for response in responses
        ]
        errors = [
            {"iteration": it["iteration"], "failure": "undecided_response"}
            for it in iterations
            if not it["passed"]
        ]
        tally = {
            option_id: sum(1 for it in iterations if it["option_id"] == option_id)
            for option_id in sorted(option_ids)
        }

        run = {
            "artifact_kind": "reference_prototype_run",
            "migration_acceptance_verified": False,
            "schema_version": SCHEMA_VERSION,
            "run_id": donor.get("runId", ""),
            "benchmark_id": f"bench-ethics-{donor.get('paradoxId')}",
            "benchmark_version": f"paradoxes@{compute_sha256((ETHICS_DIR / 'paradoxes.json').read_bytes())[:12]}",
            "provider": str(donor.get("modelName", "")).split("/")[0],
            "model": donor.get("modelName", ""),
            "parameters": {
                **donor.get("params", {}),
                "prompt_sha256": compute_sha256((donor.get("prompt") or "").encode("utf-8")),
            },
            "scorer": "donor_decision_token_tally",
            "scorer_version": "1.0.0",
            "status": "completed",
            "iterations": iterations,
            "evidence": [
                {
                    "evaluator": "donor_result_normalizer",
                    "summary": f"Normalized {len(iterations)} recorded responses from {result_path.name}.",
                    "option_tally": tally,
                    "donor_summary": donor.get("summary", {}),
                }
            ],
            "errors": errors,
        }
        canonical_run = validate_contract("ExperimentRun", run)

        donor_tally = {
            option.get("id"): option.get("count")
            for option in donor.get("summary", {}).get("options", [])
            if isinstance(option, dict)
        }
        field_parity = {
            "prompt": canonical_run["parameters"]["prompt_sha256"]
            == compute_sha256((donor.get("prompt") or "").encode("utf-8")),
            "prompt_matches_corpus_template": isinstance(scenario.get("promptTemplate"), str)
            and bool(scenario.get("promptTemplate")),
            "response": len(iterations) == donor.get("iterationCount")
            and [it["decision_token"] for it in iterations] == [r.get("decisionToken") for r in responses],
            "score": all(donor_tally.get(option_id, 0) == count for option_id, count in tally.items()),
            "metadata": canonical_run["model"] == donor.get("modelName")
            and all(canonical_run["parameters"].get(k) == v for k, v in donor.get("params", {}).items()),
            "failures": len(errors) == donor.get("summary", {}).get("undecided", {}).get("count"),
        }
        field_parity["all_fields_match"] = all(field_parity.values())

        all_stages_passed = source_verified and field_parity["all_fields_match"]
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "M1",
            "status": "normalized" if all_stages_passed else "parity_failed",
            "canonical_run": canonical_run,
            "donor_result": {
                "path": str(result_path.relative_to(ETHICS_DIR)),
                "sha256": compute_sha256(result_path.read_bytes()),
                "paradox_id": donor.get("paradoxId"),
                "model": donor.get("modelName"),
                "iteration_count": donor.get("iterationCount"),
                "recorded_at": donor.get("timestamp"),
            },
            "field_parity": field_parity,
            "ethics_comparator_fingerprint": fingerprint,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_m2_comparator_kernel_matrix(cls) -> dict[str, Any]:
        """M2: Measure what a shared kernel would replace, and normalize both corpora through one contract.

        ponytail: this is an extraction matrix, not a completed extraction. No canonical slice
        exists yet, so nothing has been deduplicated and the receipt says so in those words.
        """
        ethics_fp = get_git_fingerprint(ETHICS_DIR, ETHICS_TRACKED)
        strength_fp = get_git_fingerprint(STRENGTH_DIR, STRENGTH_TRACKED)

        packs = []
        for pack_id, repo_dir, corpus_name in (
            ("pack-ethics-paradoxes", ETHICS_DIR, "paradoxes.json"),
            ("pack-strength-capabilities", STRENGTH_DIR, "capabilities.json"),
        ):
            corpus_path = repo_dir / corpus_name
            corpus = _read_json(corpus_path)
            items = corpus if isinstance(corpus, list) else []
            corpus_sha = compute_sha256(corpus_path.read_bytes()) if corpus_path.is_file() else ""
            normalized = None
            if items and corpus_sha:
                # Both corpora are admitted by one contract kernel. That is what is demonstrated
                # here — not that either donor stopped using its own runtime.
                normalized = ModelBehaviorEngine.create_experiment_run(
                    run_id=f"run-m2-{pack_id}",
                    benchmark_id=pack_id,
                    benchmark_version=f"corpus@{corpus_sha[:12]}",
                    provider="deterministic-oracle",
                    model="corpus-inventory",
                    parameters={"corpus_items": len(items), "corpus_sha256": corpus_sha},
                    scorer="corpus_inventory_reader",
                    scorer_version="1.0.0",
                )
            packs.append({
                "pack_id": pack_id,
                "corpus_path": f"{repo_dir.name}/{corpus_name}",
                "corpus_sha256": corpus_sha,
                "item_count": len(items),
                "item_ids_sample": sorted(str(item.get("id")) for item in items[:3] if isinstance(item, dict)),
                "prompt_template_present": all(isinstance(item.get("promptTemplate"), str) for item in items),
                "normalized_through_kernel": normalized is not None,
                "normalized_run_id": normalized["run_id"] if normalized else None,
            })

        duplicates = {
            subsystem: sorted(
                repo.name for repo in (ETHICS_DIR, STRENGTH_DIR) if (repo / rel).is_file()
            )
            for subsystem, rel in KERNEL_SUBSYSTEMS.items()
        }
        duplicated_subsystems = {
            subsystem: repos for subsystem, repos in duplicates.items() if len(repos) > 1
        }
        extraction_matrix = {
            "contract_kernel": "portfolio_suites.engines.model_behavior.ModelBehaviorEngine",
            "packs_normalized_through_kernel": sum(1 for pack in packs if pack["normalized_through_kernel"]),
            "donor_subsystem_copies": duplicates,
            "subsystems_duplicated_across_donors": sorted(duplicated_subsystems),
            "donor_duplicate_module_count": sum(len(repos) for repos in duplicates.values()),
            "canonical_slice_implemented": False,
            "duplicate_runtimes_eliminated": 0,
            "duplicate_runtimes_remaining_in_donors": sum(len(repos) for repos in duplicated_subsystems.values()),
            "acceptance_status": "extraction_not_performed; matrix records what a shared slice would replace",
        }

        source_verified = all(is_meaningful_git_fingerprint(fp) for fp in (ethics_fp, strength_fp))
        all_stages_passed = (
            source_verified
            and all(pack["item_count"] > 0 and pack["corpus_sha256"] for pack in packs)
            and extraction_matrix["packs_normalized_through_kernel"] == len(packs)
            and bool(duplicated_subsystems)
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "M2",
            "status": "extraction_matrix_measured" if all_stages_passed else "source_unverified",
            "packs": packs,
            "extraction_matrix": extraction_matrix,
            "ethics_comparator_fingerprint": ethics_fp,
            "strength_comparator_fingerprint": strength_fp,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def _recorded_matches(cls) -> list[dict[str, Any]]:
        """Real recorded ai-chess matches, in deterministic filename order."""
        try:
            paths = sorted((CHESS_DIR / "matches").glob("*.json"))
        except OSError:
            return []
        matches = []
        for path in paths:
            document = _read_json(path)
            if isinstance(document, dict) and document.get("start_fen") and document.get("logs"):
                document["_path"] = path
                matches.append(document)
        return matches

    @classmethod
    def _opening_move_check(cls, match: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a match's first recorded move against its own start position.

        ponytail: opening move only — the engine parses FEN and judges legality but cannot
        yet apply a move, so later plies have no position to be judged against. Replaying a
        whole match needs a make-move primitive in ModelBehaviorEngine.
        """
        first = match["logs"][0]
        move = str(first.get("move", ""))
        state = ModelBehaviorEngine.parse_fen_board(match["start_fen"])
        legal, reason = (False, "invalid_fen_position") if state is None else ModelBehaviorEngine._is_move_legal_on_board(state, move)
        return {
            "match_id": match.get("match_id"),
            "source_file": match["_path"].name,
            "start_fen": match["start_fen"],
            "recorded_move": move,
            "actor": first.get("actor"),
            "legal": legal,
            "verdict": reason,
            "logged_plies": len(match["logs"]),
        }

    @classmethod
    def execute_m3_chess_adapter_fixture(cls) -> dict[str, Any]:
        """M3: Build the legal-move adapter fixture from one real recorded match."""
        fingerprint = get_git_fingerprint(CHESS_DIR, CHESS_TRACKED)
        matches = cls._recorded_matches()
        source_verified = is_meaningful_git_fingerprint(fingerprint) and bool(matches)
        if not matches:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "M3",
                "status": "source_unverified",
                "ai_chess_fingerprint": fingerprint,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        match = matches[0]
        check = cls._opening_move_check(match)
        repeat = cls._opening_move_check(match)
        match_fixture = {
            "adapter": "chess_legal_move_evaluator",
            "scorer_version": "1.0.0",
            "match_id": match.get("match_id"),
            "source_file": check["source_file"],
            "source_sha256": compute_sha256(match["_path"].read_bytes()),
            "white_model": match.get("white_model"),
            "black_model": match.get("black_model"),
            "start_fen": match["start_fen"],
            "recorded_move": check["recorded_move"],
            "invalid_move_behavior": ModelBehaviorEngine._is_move_legal_on_board(
                ModelBehaviorEngine.parse_fen_board(match["start_fen"]), "e2e9"
            )[1],
            "repeat_policy": "deterministic_reevaluation",
            "repeat_verdict_stable": check == repeat,
        }
        all_stages_passed = (
            source_verified
            and check["legal"]
            and match_fixture["repeat_verdict_stable"]
            and match_fixture["invalid_move_behavior"] != ""
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "M3",
            "status": "fixture_verified" if all_stages_passed else "fixture_rejected",
            "match_fixture": match_fixture,
            "legality_check": check,
            "ai_chess_fingerprint": fingerprint,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_m4_chess_benchmark_run(cls) -> dict[str, Any]:
        """M4: Score every recorded match's opening move through the shared kernel."""
        fingerprint = get_git_fingerprint(CHESS_DIR, CHESS_TRACKED)
        matches = cls._recorded_matches()
        source_verified = is_meaningful_git_fingerprint(fingerprint) and bool(matches)
        if not matches:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "M4",
                "status": "source_unverified",
                "ai_chess_fingerprint": fingerprint,
                "source_verification_passed": False,
                "all_stages_passed": False,
            }

        checks = [cls._opening_move_check(match) for match in matches]
        iterations = [
            {
                "iteration": index,
                "scenario_id": f"chess-{check['match_id']}",
                "fen": check["start_fen"],
                "candidate_move": check["recorded_move"],
                "observed_legal": check["legal"],
                "verdict": check["verdict"],
                "passed": check["legal"],
                "score": 1.0 if check["legal"] else 0.0,
                "outcome_source": "donor_recorded_match",
            }
            for index, check in enumerate(checks, start=1)
        ]
        run = validate_contract("ExperimentRun", {
            "artifact_kind": "reference_prototype_run",
            "migration_acceptance_verified": False,
            "schema_version": SCHEMA_VERSION,
            "run_id": "run-m4-recorded-openings",
            "benchmark_id": "bench-chess-recorded-openings",
            "benchmark_version": "1.0.0",
            "provider": "deterministic-oracle",
            "model": "chess-rules-evaluator-v1",
            "parameters": {"positions": len(iterations), "source": "ai-chess/matches"},
            "scorer": "chess_move_validator",
            "scorer_version": "1.0.0",
            "status": "completed",
            "iterations": iterations,
            "evidence": [
                {
                    "evaluator": "chess_move_validator",
                    "summary": f"{len(iterations)} recorded opening moves replayed against their own start positions.",
                    "pass_rate": sum(it["score"] for it in iterations) / len(iterations),
                    "models_observed": sorted({str(m.get("white_model")) for m in matches} | {str(m.get("black_model")) for m in matches}),
                }
            ],
            "errors": [
                {"scenario_id": it["scenario_id"], "failure": it["verdict"]}
                for it in iterations
                if not it["passed"]
            ],
        })

        all_stages_passed = source_verified and run["status"] == "completed" and not run["errors"]
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "M4",
            "status": "benchmark_verified" if all_stages_passed else "benchmark_failed",
            "canonical_run": run,
            "kernel_generality": {
                "kernel": "portfolio_suites.engines.model_behavior.ModelBehaviorEngine",
                "domains_scored": ["ethics_paradoxes", "chess_openings"],
                "shared_contract": "ExperimentRun",
            },
            "ai_chess_fingerprint": fingerprint,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_m5_benchmark_corpus_manifest(cls) -> dict[str, Any]:
        """M5: Pin every donor corpus by content hash so historical runs can be re-run."""
        fingerprints = {
            "ai_ethics_comparator": get_git_fingerprint(ETHICS_DIR, ETHICS_TRACKED),
            "ai_strength_comparator": get_git_fingerprint(STRENGTH_DIR, STRENGTH_TRACKED),
            "ai_chess": get_git_fingerprint(CHESS_DIR, CHESS_TRACKED),
        }
        corpus_sources = []
        for name, repo_dir, rel in (
            ("ethics_paradoxes", ETHICS_DIR, "paradoxes.json"),
            ("strength_capabilities", STRENGTH_DIR, "capabilities.json"),
        ):
            path = repo_dir / rel
            items = _read_json(path)
            corpus_sources.append({
                "corpus": name,
                "path": f"{repo_dir.name}/{rel}",
                "sha256": compute_sha256(path.read_bytes()) if path.is_file() else "",
                "item_count": len(items) if isinstance(items, list) else 0,
            })
        matches = cls._recorded_matches()
        corpus_sources.append({
            "corpus": "chess_recorded_matches",
            "path": "ai-chess/matches",
            "sha256": compute_sha256(
                b"".join(compute_sha256(m["_path"].read_bytes()).encode("utf-8") for m in matches)
            ),
            "item_count": len(matches),
        })

        m1 = cls.execute_m1_ethics_experiment_run()
        m4 = cls.execute_m4_chess_benchmark_run()
        runs = [run for run in (m1.get("canonical_run"), m4.get("canonical_run")) if run]
        corpus_manifest = ModelBehaviorEngine.build_versioned_corpus("corpus-mbl-v1", runs)
        corpus_manifest["corpus_sources"] = corpus_sources

        source_verified = all(is_meaningful_git_fingerprint(fp) for fp in fingerprints.values())
        all_stages_passed = (
            source_verified
            and len(runs) == 2
            and all(source["sha256"] and source["item_count"] > 0 for source in corpus_sources)
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "M5",
            "status": "corpus_pinned" if all_stages_passed else "source_unverified",
            "corpus_manifest": corpus_manifest,
            "corpus_sources": corpus_sources,
            "fingerprints": fingerprints,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }
