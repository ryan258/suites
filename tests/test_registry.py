import unittest
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from portfolio_suites.registry import (
    SUITES_ROOT,
    _analysis_evidence_errors,
    apply_snapshot_updates,
    _analysis_receipt_semantic_errors,
    _git_value,
    _runtime_parity_receipt_errors,
    get_portfolio_summary,
    load_ledger,
    load_recovery_standard,
    load_suites,
    validate_registry,
)
from portfolio_suites.registry import evidence_errors as registry_evidence_errors


class RegistryTests(unittest.TestCase):
    def test_git_probe_is_bounded_and_reports_timeout_as_unavailable(self):
        with patch(
            "portfolio_suites.registry.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["git", "status"], timeout=5),
        ) as run:
            value = _git_value(Path("/tmp/example"), "status", "--porcelain")
        self.assertEqual(value, "unavailable")
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    def test_eight_suite_boundaries_exist(self):
        self.assertEqual(len(load_suites()), 8)

    def test_every_snapshot_directory_has_a_disposition(self):
        rows = load_ledger()["projects"]
        self.assertEqual(len(rows), 70)
        self.assertTrue(all(row["disposition"] and row["migration"] for row in rows))

    def test_a_tool_config_directory_is_not_an_unreviewed_source(self):
        """A leading dot at portfolio root is tool config, not a capability to disposition."""
        ledger_names = {row["name"] for row in load_ledger()["projects"]}
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ledger_names:
                (root / name).mkdir()
            (root / ".claude").mkdir()   # what an editor writes, not a portfolio source
            with patch("portfolio_suites.registry.PROJECTS_ROOT", root):
                report = validate_registry(check_live=True)
        unreviewed = [e for e in report.errors if "unreviewed top-level directory" in e]
        self.assertEqual(unreviewed, [])

    def test_registry_and_live_tree_are_consistent(self):
        report = validate_registry(check_live=True)
        self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_accessibility_parity_fixture_catalog_is_complete(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "accessibility/evidence/A1-parity-cases.json").read_text())
        ids = [case["id"] for case in data["cases"]]
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(case["setup"] and case["expected"] for case in data["cases"]))

    def test_nine_out_of_ten_recovery_standard_is_enforced(self):
        standard = load_recovery_standard()
        self.assertEqual(standard["target_score"], 9.0)
        self.assertEqual(sum(row["weight"] for row in standard["dimensions"]), 100)
        self.assertEqual(standard["enforcement"]["minimum_authentic_uses_for_adoption"], 3)
        classified = [suite for tier in standard["portfolio_tiers"] for suite in tier["suites"]]
        self.assertEqual(sorted(classified), sorted(load_suites()))

    def test_recovery_enforcement_cannot_be_disabled(self):
        standard = deepcopy(load_recovery_standard())
        standard["enforcement"]["retirement_requires_owner_approval"] = False
        standard["enforcement"]["prototype_never_counts_as_recovered"] = False
        with patch("portfolio_suites.registry.load_recovery_standard", return_value=standard):
            report = validate_registry(check_live=False)
        self.assertIn(
            "recovery enforcement rules do not match the fail-closed policy",
            report.errors,
        )

    def test_recovery_tier_targets_are_enforced(self):
        standard = deepcopy(load_recovery_standard())
        standard["portfolio_tiers"][0]["target_score"] = 1.0
        with patch("portfolio_suites.registry.load_recovery_standard", return_value=standard):
            report = validate_registry(check_live=False)
        self.assertIn(
            "recovery tiers, targets, or suite assignments do not match policy",
            report.errors,
        )

    def test_recovery_dimensions_are_exact_and_well_formed(self):
        standard = deepcopy(load_recovery_standard())
        standard["dimensions"] = [{"id": "anything", "weight": 100, "requirement": "weak"}]
        with patch("portfolio_suites.registry.load_recovery_standard", return_value=standard):
            report = validate_registry(check_live=False)
        self.assertIn(
            "recovery standard dimensions or weights do not match the adopted rubric",
            report.errors,
        )

    def test_runtime_parity_receipt_requires_authentic_donor_evidence(self):
        with TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            receipt.write_text(json.dumps({"all_stages_passed": True}), encoding="utf-8")
            errors = _runtime_parity_receipt_errors(receipt, "accessibility-wcag-331-v1")
        self.assertIn(
            "runtime parity receipt must prove authentic donor execution and parity",
            errors,
        )

    def test_analysis_evidence_must_contain_its_declared_basis(self):
        with TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            receipt.write_text(json.dumps({"job": {}, "formatter_fingerprint": "abc"}), encoding="utf-8")
            self.assertEqual(_analysis_evidence_errors(receipt, {"job", "formatter_fingerprint"}), [])
            self.assertEqual(
                _analysis_evidence_errors(receipt, {"job", "output_parity"}),
                ["analysis evidence does not contain its declared basis: output_parity"],
            )

            prose = Path(directory) / "receipt.md"
            prose.write_text("# A1\n\n## Retirement gate\n", encoding="utf-8")
            self.assertEqual(_analysis_evidence_errors(prose, {"## Retirement gate"}), [])
            self.assertEqual(
                _analysis_evidence_errors(prose, {"## Missing section"}),
                ["analysis evidence does not contain its declared basis: ## Missing section"],
            )

    def test_analysis_receipt_rejects_null_and_empty_semantic_values(self):
        errors = _analysis_receipt_semantic_errors(
            {"id": "P2"},
            {
                "wave": "P2",
                "status": "formatter_executed",
                "all_stages_passed": True,
                "job": None,
                "formatter_fingerprint": "",
            },
        )
        self.assertTrue(any("job must be a non-empty object" in error for error in errors))
        self.assertTrue(any("meaningful source fingerprint" in error for error in errors))

    def test_analysis_receipt_accepts_expected_false_boundary_value(self):
        fingerprint = {
            "branch": "main",
            "head": "a" * 40,
            "tested_files_fingerprint": {"README.md": "b" * 64},
        }
        errors = _analysis_receipt_semantic_errors(
            {"id": "O6"},
            {
                "wave_id": "O6",
                "status": "checkpoint_lifecycle_verified",
                "multi_action_lifecycle_passed": True,
                "disk_mutations_performed": False,
                "fail_closed_test": {"verified": True},
                "preview_test": {"verified": True},
                "jarvis_fingerprint": fingerprint,
            },
        )
        self.assertEqual(errors, [])

    def test_a3_v2_receipt_requires_verified_donor_measurements(self):
        errors = _analysis_receipt_semantic_errors(
            {"id": "A3"},
            {
                "receipt_version": "accessibility-a3-analysis-v2",
                "canonical_target": "kb-overlay",
                "recommendation": "candidate only",
                "source_verification": {
                    "passed": False,
                    "errors": ["donor missing"],
                    "donors_checked": 3,
                },
                "matrix": {
                    name: {"features": ["spatial_nav"], "code_size_bytes": 1}
                    for name in (
                        "kb-overlay",
                        "keyboard-nav-overlay",
                        "keyboard-nav-overlay-94bf7e",
                    )
                },
            },
        )
        self.assertTrue(any("clean three-donor pass" in error for error in errors))
        self.assertTrue(any("verified source measurements" in error for error in errors))

    def test_a3_receipt_containing_only_source_inventory_cannot_claim_parity_verified(self):
        errors = _analysis_receipt_semantic_errors(
            {
                "id": "A3",
                "recovery_claim": {
                    "kind": "analysis",
                    "level": "parity_verified",
                    "real_runtime": False,
                },
            },
            {
                "receipt_version": "accessibility-a3-analysis-v2",
                "canonical_target": "kb-overlay",
                "recommendation": "candidate only",
                "source_verification": {
                    "passed": True,
                    "errors": [],
                    "donors_checked": 3,
                },
                "matrix": {
                    name: {
                        "source_available": True,
                        "manifest_valid": True,
                        "fingerprint_verified": True,
                        "features": ["spatial_nav"],
                        "code_size_bytes": 100,
                        "git_fingerprint": {"branch": "main", "head": "a" * 40},
                    }
                    for name in (
                        "kb-overlay",
                        "keyboard-nav-overlay",
                        "keyboard-nav-overlay-94bf7e",
                    )
                },
            },
        )
        self.assertTrue(any("cannot substantiate a parity_verified claim" in error for error in errors))

    def test_a3_parity_guard_survives_missing_or_unknown_receipt_version(self):
        def receipt(**overrides):
            document = {
                "receipt_version": "accessibility-a3-analysis-v2",
                "canonical_target": "kb-overlay",
                "recommendation": "candidate only",
                "matrix": {
                    name: {"features": ["spatial_nav"], "code_size_bytes": 100}
                    for name in ("kb-overlay", "keyboard-nav-overlay", "keyboard-nav-overlay-94bf7e")
                },
            }
            document.update(overrides)
            if overrides.get("receipt_version") is None and "receipt_version" in overrides:
                del document["receipt_version"]
            return document

        wave = {
            "id": "A3",
            "recovery_claim": {"kind": "analysis", "level": "parity_verified", "real_runtime": False},
        }
        for overrides in ({"receipt_version": None}, {"receipt_version": ""}, {"receipt_version": "accessibility-a3-analysis-v1"}):
            errors = _analysis_receipt_semantic_errors(wave, receipt(**overrides))
            self.assertTrue(any("cannot substantiate a parity_verified claim" in error for error in errors), overrides)
            self.assertTrue(any("receipt_version must be" in error for error in errors), overrides)

    def test_summary_separates_analysis_from_runtime_recovery(self):
        summary = get_portfolio_summary()
        self.assertEqual(summary["recovery_target_score"], 9.0)
        self.assertEqual(summary["verified_analysis_milestones"], 42)
        self.assertEqual(summary["recovered_runtime_behaviors"], 1)
        self.assertEqual(summary["adopted_runtime_behaviors"], 0)
        self.assertEqual(summary["converged_runtime_behaviors"], 0)

    def test_validate_rejects_a_corrupted_prototype_receipt(self):
        """A retained prototype receipt is re-checked by the canonical validator, not only at record time."""
        suites = deepcopy(load_suites())
        wave = next(w for w in suites["model-behavior-lab"]["waves"] if w["id"] == "M1")
        scratch = SUITES_ROOT / "model-behavior-lab" / "evidence" / ".validate-regression.json"
        retained = json.loads((SUITES_ROOT / wave["evidence"]).read_text(encoding="utf-8"))
        retained["field_parity"]["all_fields_match"] = False
        wave["evidence"] = "model-behavior-lab/evidence/.validate-regression.json"
        try:
            scratch.write_text(json.dumps(retained), encoding="utf-8")
            with patch("portfolio_suites.registry.load_suites", return_value=suites):
                report = validate_registry(check_live=False)
        finally:
            scratch.unlink(missing_ok=True)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("M1" in error and "field_parity.all_fields_match" in error for error in report.errors),
            report.errors,
        )

    def test_validate_checks_every_declared_claim_not_only_completed_waves(self):
        inspected: list[str] = []
        real_errors = registry_evidence_errors

        def spy(wave, path, suite_id=None):
            inspected.append(str(wave.get("id")))
            return real_errors(wave, path, suite_id)

        with patch("portfolio_suites.registry.evidence_errors", side_effect=spy):
            validate_registry(check_live=False)
        for wave_id in ("M1", "D3", "R5", "G2", "A6"):
            with self.subTest(wave=wave_id):
                self.assertIn(wave_id, inspected)

    def test_completed_wave_promotion_level_rules(self):
        """A completed analysis wave may hold level: 'prototype', while specified level or runtime prototype errors."""
        suites = deepcopy(load_suites())

        # Baseline check: completed analysis wave at prototype validates cleanly
        a5 = next(w for w in suites["accessibility"]["waves"] if w["id"] == "A5")
        self.assertEqual(a5["status"], "complete")
        self.assertEqual(a5["recovery_claim"]["kind"], "analysis")
        self.assertEqual(a5["recovery_claim"]["level"], "prototype")
        with patch("portfolio_suites.registry.load_suites", return_value=suites):
            report = validate_registry(check_live=False)
        self.assertTrue(report.ok, report.errors)

        # Rejection 1: completed wave claiming 'specified' level fails validation
        suites_specified = deepcopy(suites)
        a5_spec = next(w for w in suites_specified["accessibility"]["waves"] if w["id"] == "A5")
        a5_spec["recovery_claim"]["level"] = "specified"
        with patch("portfolio_suites.registry.load_suites", return_value=suites_specified):
            report = validate_registry(check_live=False)
        self.assertFalse(report.ok)
        self.assertTrue(any("completed wave cannot claim a specified level" in e for e in report.errors), report.errors)

        # Rejection 2: completed runtime wave claiming 'prototype' level fails validation
        suites_runtime = deepcopy(suites)
        a2_runtime = next(w for w in suites_runtime["accessibility"]["waves"] if w["id"] == "A2")
        self.assertEqual(a2_runtime["status"], "complete")
        self.assertEqual(a2_runtime["recovery_claim"]["kind"], "runtime")
        a2_runtime["recovery_claim"]["level"] = "prototype"
        with patch("portfolio_suites.registry.load_suites", return_value=suites_runtime):
            report = validate_registry(check_live=False)
        self.assertFalse(report.ok)
        self.assertTrue(any("completed runtime wave cannot claim a prototype level" in e for e in report.errors), report.errors)


if __name__ == "__main__":
    unittest.main()


class UnsupportedEvidenceContractTests(unittest.TestCase):
    """A receipt no contract can check must be refused, not silently accepted."""

    def _wave(self, kind, level="adopted"):
        return {
            "id": "X1",
            "recovery_claim": {"kind": kind, "level": level, "evidence_basis": ["something"]},
        }

    def test_claim_kinds_without_a_receipt_contract_are_refused(self):
        from portfolio_suites.registry import evidence_errors

        missing = Path("/nonexistent/receipt.json")
        for kind in ("adoption", "convergence", "resolution"):
            with self.subTest(kind=kind):
                errors = evidence_errors(self._wave(kind), missing)
                self.assertTrue(errors)
                self.assertIn("no versioned evidence receipt contract", errors[0])

    def test_runtime_below_parity_is_refused(self):
        from portfolio_suites.registry import evidence_errors

        errors = evidence_errors(self._wave("runtime", "source_verified"), Path("/nonexistent/receipt.json"))
        self.assertTrue(errors)
        self.assertIn("no versioned evidence receipt contract", errors[0])

    def test_contracted_claim_kinds_are_still_evaluated(self):
        from portfolio_suites.registry import evidence_errors

        errors = evidence_errors(self._wave("runtime", "parity_verified"), Path("/nonexistent/receipt.json"))
        self.assertTrue(errors)
        self.assertNotIn("no versioned evidence receipt contract", errors[0])


class ApplySnapshotUpdatesTest(unittest.TestCase):
    LEDGER = (
        '{\n  "projects": [\n'
        '    {"name":"alpha","source_snapshot":{"git":true,"head":"aaa","status_lines":0}},\n'
        '    {"name":"beta","source_snapshot":{"git":true,"head":"bbb","status_lines":2,"status_sha256":"kept"}},\n'
        '    {"name":"gamma","source_snapshot":{"git":false}}\n'
        '  ]\n}\n'
    )

    def test_rewrites_only_named_rows_and_preserves_layout(self):
        text, updated = apply_snapshot_updates(
            self.LEDGER,
            {
                "alpha": {"git": True, "head": "aaa", "status_lines": 0, "status_sha256": "deadbeef"},
                "beta": {"git": True, "head": "bbb", "status_lines": 2, "status_sha256": "kept"},
            },
        )
        self.assertEqual(updated, ["alpha"])  # beta is unchanged, so it is not reported
        rows = json.loads(text)["projects"]
        self.assertEqual(rows[0]["source_snapshot"]["status_sha256"], "deadbeef")
        self.assertEqual(rows[1]["source_snapshot"]["status_sha256"], "kept")
        self.assertNotIn("status_sha256", rows[2]["source_snapshot"])
        self.assertEqual(text.count("\n"), self.LEDGER.count("\n"))

    def test_accepting_new_state_replaces_the_whole_snapshot(self):
        text, updated = apply_snapshot_updates(
            self.LEDGER,
            {"beta": {"git": True, "branch": "main", "head": "ccc", "status_lines": 0, "status_sha256": "fresh"}},
        )
        self.assertEqual(updated, ["beta"])
        snapshot = json.loads(text)["projects"][1]["source_snapshot"]
        self.assertEqual(snapshot, {"git": True, "branch": "main", "head": "ccc", "status_lines": 0, "status_sha256": "fresh"})


class RuntimeFollowupRuleTests(unittest.TestCase):
    """A completed analysis wave has left its runtime work undone by definition. Without a
    written followup that work is not deferred, it is lost."""

    def test_every_completed_analysis_wave_records_its_deferred_runtime_work(self):
        missing = [
            f"{suite_id}/{wave['id']}"
            for suite_id, manifest in load_suites().items()
            for wave in manifest.get("waves", [])
            if wave.get("status") == "complete"
            and (wave.get("recovery_claim") or {}).get("kind") == "analysis"
            and not str(wave.get("runtime_followup") or "").strip()
        ]
        self.assertEqual(missing, [])


class WorktreeDriftTests(unittest.TestCase):
    """`git status --porcelain` carries no file content, so the patch closes that hole."""

    @staticmethod
    def _git(repo, *args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    def _dirty_repo(self, root):
        repo = root / "donor"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "t@example.com")
        self._git(repo, "config", "user.name", "t")
        (repo / "f.txt").write_text("committed\n", encoding="utf-8")
        self._git(repo, "add", "f.txt")
        self._git(repo, "commit", "-qm", "init")
        (repo / "f.txt").write_text("dirty edit one\n", encoding="utf-8")
        return repo

    def test_editing_an_already_dirty_file_is_drift(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._dirty_repo(root)
            with patch("portfolio_suites.registry.PROJECTS_ROOT", root):
                from portfolio_suites.registry import check_project_git_drift

                first = check_project_git_drift("donor", {"source_snapshot": {"git": True}})
                baseline = {
                    "git": True,
                    "branch": first["current_branch"],
                    "head": first["current_head"],
                    "status_lines": first["current_lines"],
                    "status_sha256": first["current_status_sha256"],
                    "patch_sha256": first["current_patch_sha256"],
                }
                self.assertFalse(check_project_git_drift("donor", {"source_snapshot": baseline})["has_drift"])

                # Same file, still modified, different content: porcelain does not move.
                (repo / "f.txt").write_text("a completely different dirty edit\n", encoding="utf-8")
                after = check_project_git_drift("donor", {"source_snapshot": baseline})

        self.assertEqual(after["current_status_sha256"], baseline["status_sha256"])
        self.assertFalse(after["content_drift"], "porcelain hash is content-blind, as expected")
        self.assertTrue(after["patch_drift"], "patch hash must catch the content change")
        self.assertTrue(after["has_drift"])

    def test_a_baseline_without_a_patch_fingerprint_does_not_fail_open_silently(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._dirty_repo(root)
            with patch("portfolio_suites.registry.PROJECTS_ROOT", root):
                from portfolio_suites.registry import check_project_git_drift

                drift = check_project_git_drift("donor", {"source_snapshot": {"git": True}})
        self.assertTrue(drift["patch_unfingerprinted"], "must be reported so `baseline` backfills it")
        self.assertFalse(drift["patch_drift"], "an absent baseline field cannot itself be drift")


class ReceiptSpecTableTests(unittest.TestCase):
    """A duplicate key in the receipt table silently discards a gate's spec.

    Python keeps the last of a duplicated dict key, so by import time the shadowed
    entry is already gone and no runtime check can see it. The source is the only
    place the duplication still exists, so that is where it is checked.
    """

    def test_receipt_spec_keys_are_declared_once(self):
        import ast

        source = (SUITES_ROOT / "src" / "portfolio_suites" / "registry.py").read_text(encoding="utf-8")
        table = next(
            node.value
            for node in ast.parse(source).body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                getattr(t, "id", None) == "ANALYSIS_RECEIPT_SPECS"
                for t in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
            )
        )
        keys = [k.value for k in table.keys if isinstance(k, ast.Constant)]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        self.assertEqual(duplicates, [], f"receipt specs declared more than once: {duplicates}")


class AnalysisPromotionLevelTests(unittest.TestCase):
    """An analysis claim states no runtime ran, so it cannot hold a runtime promotion level.

    `parity_verified` and above assert a donor and a destination were both executed and
    compared. Only the runtime branch of `validate_registry` carries evidence that can
    substantiate that, and nothing was applying it to analysis claims -- six shipped waves
    sat at `parity_verified` with `real_runtime: false`.
    """

    @staticmethod
    def _suite_with_claim(level, kind="analysis"):
        return {
            "id": "accessibility",
            "schema_version": "1.0.0",
            "promise": "p",
            "anchors": ["allys-tools"],
            "contracts": [],
            "members": [{"project": "allys-tools", "relationship": "anchor"}],
            "completion_criteria": ["c"],
            "waves": [{
                "id": "A1",
                "order": 1,
                "status": "complete",
                "objective": "o",
                "acceptance": "a",
                "runtime_followup": "deferred runtime work",
                "evidence": "accessibility/evidence/A1-WCAG-AUDITOR-PARITY.md",
                "recovery_claim": {
                    "kind": kind,
                    "level": level,
                    "real_runtime": kind == "runtime",
                    "evidence_basis": ["parity_matrix"],
                },
            }],
        }

    def _errors_for(self, level, kind="analysis"):
        suites = {"accessibility": self._suite_with_claim(level, kind)}
        with patch("portfolio_suites.registry.load_suites", return_value=suites):
            report = validate_registry(check_live=False)
        return report.errors

    def test_analysis_claim_cannot_hold_a_runtime_promotion_level(self):
        for level in ("parity_verified", "adopted", "converged"):
            with self.subTest(level=level):
                errors = self._errors_for(level)
                self.assertTrue(
                    any("cannot occupy the runtime promotion level" in error for error in errors),
                    f"{level} was accepted for an analysis claim: {errors}",
                )

    def test_analysis_claim_may_still_reach_source_verified(self):
        errors = self._errors_for("source_verified")
        self.assertFalse(
            any("cannot occupy the runtime promotion level" in error for error in errors),
            errors,
        )

    def test_runtime_claim_is_untouched_by_the_analysis_guard(self):
        errors = self._errors_for("parity_verified", kind="runtime")
        self.assertFalse(
            any("cannot occupy the runtime promotion level" in error for error in errors),
            errors,
        )

    def test_no_shipped_wave_claims_a_runtime_level_without_a_runtime(self):
        """The manifests themselves, not a fixture: this is what the guard was written for."""
        offenders = [
            f"{suite_id}/{wave['id']}"
            for suite_id, manifest in load_suites().items()
            for wave in manifest.get("waves", [])
            if (wave.get("recovery_claim") or {}).get("kind") == "analysis"
            and (wave.get("recovery_claim") or {}).get("level") in {"parity_verified", "adopted", "converged"}
        ]
        self.assertEqual(offenders, [], f"analysis waves claiming a runtime level: {offenders}")


class ReceiptSpecLookupTests(unittest.TestCase):
    """Receipt specs are keyed by suite and wave so two suites may share a wave letter."""

    def test_every_spec_key_names_a_real_suite_and_wave(self):
        from portfolio_suites.registry import ANALYSIS_RECEIPT_SPECS

        declared = {
            f"{suite_id}/{wave['id']}"
            for suite_id, manifest in load_suites().items()
            for wave in manifest.get("waves", [])
        }
        unknown = sorted(set(ANALYSIS_RECEIPT_SPECS) - declared)
        self.assertEqual(unknown, [], f"receipt specs for waves no manifest declares: {unknown}")

    def test_suite_id_selects_that_suites_spec(self):
        from portfolio_suites.registry import _lookup_receipt_spec, ANALYSIS_RECEIPT_SPECS

        spec, error, key = _lookup_receipt_spec("accessibility", "A3")
        self.assertIsNone(error)
        self.assertEqual(key, "accessibility/A3")
        self.assertIs(spec, ANALYSIS_RECEIPT_SPECS["accessibility/A3"])

    def test_wrong_suite_refuses_rather_than_borrowing_another_spec(self):
        from portfolio_suites.registry import _lookup_receipt_spec

        spec, error, key = _lookup_receipt_spec("game-design", "A3")
        self.assertIsNone(key)
        self.assertIsNone(spec)
        self.assertIn("no ANALYSIS_RECEIPT_SPECS definition", error)

    def test_bare_wave_id_resolves_only_while_it_is_unambiguous(self):
        from portfolio_suites.registry import _lookup_receipt_spec, ANALYSIS_RECEIPT_SPECS

        spec, error, key = _lookup_receipt_spec(None, "A3")
        self.assertIsNone(error)
        self.assertEqual(key, "accessibility/A3")
        self.assertIs(spec, ANALYSIS_RECEIPT_SPECS["accessibility/A3"])

        collision = dict(ANALYSIS_RECEIPT_SPECS)
        collision["game-design/A3"] = {"equals": {}}
        with patch("portfolio_suites.registry.ANALYSIS_RECEIPT_SPECS", collision):
            spec, error, key = _lookup_receipt_spec(None, "A3")
        self.assertIsNone(spec, "an ambiguous wave letter must not resolve to one suite's spec")
        self.assertIn("matches several suites", error)


class DurableLedgerWriteTests(unittest.TestCase):
    """The ledger cannot be rebuilt from the suites, so it is replaced atomically."""

    def test_ledger_is_replaced_atomically_not_truncated_in_place(self):
        from portfolio_suites import registry

        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "project-ledger.json"
            original = '{"schema_version":"1.0.0","projects":[]}'
            ledger.write_text(original, encoding="utf-8")

            seen_during_write = {}

            real_replace = __import__("os").replace

            def watched_replace(src, dst):
                # Mid-write, the destination must still hold the complete old document.
                seen_during_write["content"] = Path(dst).read_text(encoding="utf-8")
                return real_replace(src, dst)

            with patch.object(registry, "_LEDGER_PATH", ledger), \
                 patch.object(registry, "pending_snapshots", return_value={}), \
                 patch.object(registry, "apply_snapshot_updates", return_value=("NEW", ["proj"])), \
                 patch("portfolio_suites.paths.os.replace", side_effect=watched_replace):
                registry.fingerprint_baselines(dry_run=False)

            self.assertEqual(seen_during_write["content"], original)
            self.assertEqual(ledger.read_text(encoding="utf-8"), "NEW")

    def test_a_failed_ledger_write_leaves_the_previous_document_intact(self):
        from portfolio_suites import registry

        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "project-ledger.json"
            original = '{"schema_version":"1.0.0","projects":[]}'
            ledger.write_text(original, encoding="utf-8")

            with patch.object(registry, "_LEDGER_PATH", ledger), \
                 patch.object(registry, "pending_snapshots", return_value={}), \
                 patch.object(registry, "apply_snapshot_updates", return_value=("NEW", ["proj"])), \
                 patch("portfolio_suites.paths.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    registry.fingerprint_baselines(dry_run=False)

            self.assertEqual(ledger.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(tmp).iterdir()), [ledger], "temporary file was left behind")


class RuntimeDebtInAggregateTests(unittest.TestCase):
    """Scheduling progress and recovery are different quantities.

    `suites next` listed the deferred live runs wave by wave, but the aggregate reported
    43/43 (100.0%) and stopped there -- so the headline read as done while 42 completed
    waves still owed a real runtime. The count now travels with the summary the CLI and
    dashboard both render.
    """

    def test_summary_counts_every_completed_wave_owing_a_live_run(self):
        summary = get_portfolio_summary()
        expected = sum(
            1
            for manifest in load_suites().values()
            for wave in manifest.get("waves", [])
            if wave.get("status") == "complete" and str(wave.get("runtime_followup") or "").strip()
        )
        self.assertEqual(summary["waves_owing_runtime_followup"], expected)

    def test_per_suite_debt_sums_to_the_portfolio_total(self):
        summary = get_portfolio_summary()
        self.assertEqual(
            sum(s["waves_owing_runtime_followup"] for s in summary["suites"]),
            summary["waves_owing_runtime_followup"],
        )

    def test_debt_never_exceeds_the_completed_waves_it_is_measured_against(self):
        summary = get_portfolio_summary()
        self.assertLessEqual(summary["waves_owing_runtime_followup"], summary["completed_waves"])
        for suite in summary["suites"]:
            with self.subTest(suite=suite["id"]):
                self.assertLessEqual(suite["waves_owing_runtime_followup"], suite["waves_complete"])

    def test_a_hundred_percent_headline_is_never_printed_alone(self):
        """The regression this guards: full scheduling progress with the debt left unsaid."""
        import io
        from contextlib import redirect_stdout
        from portfolio_suites.cli import _status

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _status()
        output = buffer.getvalue()

        summary = get_portfolio_summary()
        if summary["waves_owing_runtime_followup"]:
            self.assertIn("still owe a live run", output)
            self.assertIn(str(summary["waves_owing_runtime_followup"]), output)

    def test_dashboard_renders_the_same_field_the_summary_publishes(self):
        """The tile and the CLI must read one number, not two hand-maintained ones."""
        web = SUITES_ROOT / "src" / "portfolio_suites" / "web"
        self.assertIn("waves_owing_runtime_followup", (web / "app.js").read_text(encoding="utf-8"))
        self.assertIn('id="card-runtime-debt"', (web / "index.html").read_text(encoding="utf-8"))


class DurableWriteModeTests(unittest.TestCase):
    """A durable replace must not quietly narrow the target's permissions.

    `mkstemp` creates its file 0600. Replacing the 0644 project ledger with it strips group
    and other read access, and Git cannot report the loss because it tracks only the
    executable bit -- both modes are `100644` to Git.
    """

    def test_existing_permissions_survive_the_replacement(self):
        import os
        import stat as stat_module
        from portfolio_suites.paths import durable_write_text

        with TemporaryDirectory() as tmp:
            for mode in (0o644, 0o640, 0o600):
                with self.subTest(mode=oct(mode)):
                    target = Path(tmp) / f"ledger{mode:o}.json"
                    target.write_text("{}", encoding="utf-8")
                    os.chmod(target, mode)
                    durable_write_text(target, '{"projects": []}')
                    self.assertEqual(stat_module.S_IMODE(target.stat().st_mode), mode)
                    self.assertEqual(target.read_text(encoding="utf-8"), '{"projects": []}')

    def test_a_new_file_keeps_the_private_default(self):
        import stat as stat_module
        from portfolio_suites.paths import durable_write_text

        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "brand-new.json"
            durable_write_text(target, "{}")
            self.assertEqual(stat_module.S_IMODE(target.stat().st_mode), 0o600)

    def test_the_tracked_ledger_keeps_its_mode_through_baseline(self):
        """The file this actually protects, at the mode it actually ships with."""
        import os
        import stat as stat_module
        from portfolio_suites import registry

        live_mode = stat_module.S_IMODE((SUITES_ROOT / "portfolio" / "project-ledger.json").stat().st_mode)
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "project-ledger.json"
            ledger.write_text('{"schema_version":"1.0.0","projects":[]}', encoding="utf-8")
            os.chmod(ledger, live_mode)
            with patch.object(registry, "_LEDGER_PATH", ledger), \
                 patch.object(registry, "pending_snapshots", return_value={}), \
                 patch.object(registry, "apply_snapshot_updates", return_value=("NEW", ["proj"])):
                registry.fingerprint_baselines(dry_run=False)
            self.assertEqual(stat_module.S_IMODE(ledger.stat().st_mode), live_mode)


class SuiteQualifiedSemanticRuleTests(unittest.TestCase):
    """The extra receipt rules belong to the suite whose spec was selected.

    Keying the spec table by `<suite>/<wave>` was not enough while the special branches
    still switched on the bare letter: a future `game-design/A3` inherited accessibility's
    keyboard-overlay matrix and receipt-version requirements.
    """

    @staticmethod
    def _with_extra_spec():
        from portfolio_suites.registry import ANALYSIS_RECEIPT_SPECS

        specs = dict(ANALYSIS_RECEIPT_SPECS)
        specs["game-design/A3"] = {"equals": {"ok": True}}
        return specs

    def test_another_suites_wave_letter_does_not_inherit_the_rules(self):
        from portfolio_suites import registry

        with patch.object(registry, "ANALYSIS_RECEIPT_SPECS", self._with_extra_spec()):
            errors = registry._analysis_receipt_semantic_errors(
                {"id": "A3", "recovery_claim": {"kind": "analysis", "level": "source_verified"}},
                {"ok": True},
                "game-design",
            )
        self.assertEqual(errors, [], f"accessibility rules leaked into game-design: {errors}")

    def test_the_owning_suite_is_still_fully_enforced(self):
        from portfolio_suites import registry

        with patch.object(registry, "ANALYSIS_RECEIPT_SPECS", self._with_extra_spec()):
            errors = registry._analysis_receipt_semantic_errors(
                {"id": "A3", "recovery_claim": {"kind": "analysis", "level": "source_verified"}},
                {"ok": True},
                "accessibility",
            )
        self.assertTrue(any("three declared overlay sources" in e for e in errors), errors)
        self.assertTrue(any("receipt_version must be" in e for e in errors), errors)

    def test_every_special_branch_is_reachable_only_through_its_own_suite(self):
        """Each hard-coded rule set must name a suite/wave that really declares it."""
        import re as _re

        source = (SUITES_ROOT / "src" / "portfolio_suites" / "registry.py").read_text(encoding="utf-8")
        body = source[source.index("def _analysis_receipt_semantic_errors"):]
        keys = set(_re.findall(r'spec_key (?:==|in) \{?"([a-z-]+/[A-Z]\d)"', body))
        keys |= {k for k in _re.findall(r'"([a-z-]+/[A-Z]\d)"', body.split("return errors")[0])}
        declared = {
            f"{suite_id}/{wave['id']}"
            for suite_id, manifest in load_suites().items()
            for wave in manifest.get("waves", [])
        }
        self.assertTrue(keys, "no suite-qualified branches found; did dispatch regress to bare wave ids?")
        self.assertEqual(sorted(keys - declared), [], "branch keys naming no declared wave")

    def test_no_special_branch_switches_on_a_bare_wave_id(self):
        import re as _re

        source = (SUITES_ROOT / "src" / "portfolio_suites" / "registry.py").read_text(encoding="utf-8")
        body = source[source.index("def _analysis_receipt_semantic_errors"):source.index("def _runtime_parity_receipt_errors")]
        top_level = [
            line for line in body.splitlines()
            if _re.match(r'    (if|elif) wave_id (==|in) ', line)
        ]
        self.assertEqual(top_level, [], f"branches still dispatch on a bare wave id: {top_level}")
