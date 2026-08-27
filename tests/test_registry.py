import hashlib
import json
import shlex
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from portfolio_suites.registry import (
    SUITES_ROOT,
    _analysis_evidence_errors,
    apply_snapshot_updates,
    _analysis_receipt_semantic_errors,
    _git_untracked_paths,
    _git_value,
    _is_ignored_junk_line,
    _runtime_parity_receipt_errors,
    _untracked_content_digest,
    check_project_git_drift,
    get_portfolio_summary,
    load_ledger,
    load_recovery_standard,
    load_suites,
    validate_registry,
    RUNTIME_SOURCE_EVIDENCE,
)
from portfolio_suites.registry import evidence_errors as registry_evidence_errors
from portfolio_suites import registry as _registry_module


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
                "status": "fixture_output_projection_verified",
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
        self.assertEqual(summary["completed_analysis_milestones"], 40)
        self.assertEqual(summary["recovered_runtime_behaviors"], 1)
        self.assertEqual(summary["adopted_runtime_behaviors"], 0)
        self.assertEqual(summary["converged_runtime_behaviors"], 0)

    def test_summary_reports_promotion_level_as_its_own_axis(self):
        """Milestone completion must not be able to stand in for evidence depth.

        Every wave is complete, so any count derived from incompleteness reports zero
        prototypes. These counts come from `recovery_claim.level` instead, and the sum
        pins them to the wave total so a level going unclassified cannot pass silently.
        """
        summary = get_portfolio_summary()
        levels = summary["promotion_counts"]
        self.assertEqual(summary["completed_waves"], summary["total_waves"])
        self.assertEqual(levels["prototype"], 4)
        self.assertEqual(levels["reviewed_historical_analysis"], 1)
        self.assertEqual(levels["source_inspected"], 35)
        self.assertEqual(levels["source_executed"], 2)
        self.assertEqual(levels["parity_verified"], 1)
        self.assertEqual(levels["adopted"], 0)
        self.assertEqual(levels["converged"], 0)
        self.assertEqual(summary["resolved_capabilities"], 0)
        self.assertEqual(sum(levels.values()), summary["total_waves"])
        self.assertEqual(summary["prototype_level_claims"], levels["prototype"])

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



class UnsupportedEvidenceContractTests(unittest.TestCase):
    """A receipt no contract can check must be refused, not silently accepted."""

    def _wave(self, kind, level="adopted"):
        return {
            "id": "X1",
            "recovery_claim": {"kind": kind, "level": level, "evidence_basis": ["something"]},
        }

    def test_lifecycle_claims_without_their_receipt_contract_are_refused(self):
        from portfolio_suites.registry import evidence_errors

        missing = Path("/nonexistent/receipt.json")
        for kind in ("adoption", "convergence", "resolution"):
            with self.subTest(kind=kind):
                errors = evidence_errors(self._wave(kind), missing)
                self.assertTrue(errors)
                self.assertIn("requires receipt_contract", errors[0])

    def test_runtime_source_verification_requires_its_versioned_contract(self):
        from portfolio_suites.registry import evidence_errors

        errors = evidence_errors(self._wave("runtime", "source_executed"), Path("/nonexistent/receipt.json"))
        self.assertTrue(errors)
        self.assertIn("requires receipt_contract", errors[0])

    def test_contracted_claim_kinds_are_still_evaluated(self):
        from portfolio_suites.registry import evidence_errors

        errors = evidence_errors(self._wave("runtime", "parity_verified"), Path("/nonexistent/receipt.json"))
        self.assertTrue(errors)
        self.assertIn("requires receipt_contract", errors[0])

    def test_unknown_runtime_level_names_the_level_as_the_unsupported_dimension(self):
        from portfolio_suites.registry import evidence_errors

        errors = evidence_errors(
            self._wave("runtime", "imaginary_level"),
            Path("/nonexistent/receipt.json"),
        )
        self.assertTrue(errors)
        self.assertIn("runtime claim level 'imaginary_level'", errors[0])
        self.assertNotIn("recovery claim kind", errors[0])


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

    def test_ignored_junk_line_detects_dot_store_at_any_depth(self):
        self.assertFalse(_is_ignored_junk_line("?? real-file.json"))
        self.assertTrue(_is_ignored_junk_line("?? .DS_Store"))
        self.assertTrue(_is_ignored_junk_line("?? sub/dir/.DS_Store"))
        self.assertTrue(_is_ignored_junk_line(" M sub/.DS_Store"))
        self.assertFalse(_is_ignored_junk_line("?? backup.DS_Store"))
        self.assertFalse(_is_ignored_junk_line("?? .DS_Store.tmp"))

    def test_finder_dot_store_cannot_fake_a_dirty_tree(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "donor"
            repo.mkdir()
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.email", "t@example.com")
            self._git(repo, "config", "user.name", "t")
            (repo / "f.txt").write_text("committed\n", encoding="utf-8")
            (repo / "lib").mkdir()
            (repo / "lib" / "keep.txt").write_text("tracked\n", encoding="utf-8")
            self._git(repo, "add", "f.txt", "lib/keep.txt")
            self._git(repo, "commit", "-qm", "init")
            with patch("portfolio_suites.registry.PROJECTS_ROOT", root):
                from portfolio_suites.registry import check_project_git_drift

                clean = check_project_git_drift("donor", {"source_snapshot": {"git": True}})
                baseline = {
                    "git": True,
                    "branch": clean["current_branch"],
                    "head": clean["current_head"],
                    "status_lines": clean["current_lines"],
                    "status_sha256": clean["current_status_sha256"],
                    "patch_sha256": clean["current_patch_sha256"],
                }
                (repo / ".DS_Store").write_text("Finder touch\n", encoding="utf-8")
                (repo / "lib" / ".DS_Store").write_text("Finder touch\n", encoding="utf-8")
                after = check_project_git_drift("donor", {"source_snapshot": baseline})

        self.assertFalse(after["has_drift"], ".DS_Store must not re-drift a clean baseline")
        self.assertEqual(after["current_lines"], 0)
        self.assertEqual(after["current_status_sha256"], baseline["status_sha256"])

    def test_untracked_enumeration_timeout_is_explicitly_incomplete(self):
        with patch(
            "portfolio_suites.registry.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["git", "status"], timeout=5),
        ):
            paths, complete = _git_untracked_paths(Path("/tmp/example"))
        self.assertEqual(paths, [])
        self.assertFalse(complete)

    def test_enumeration_failure_is_unresolved_and_cannot_be_baselined(self):
        from portfolio_suites import registry

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "donor").mkdir()

            def git_value(_source, *args):
                if args[:2] == ("rev-parse", "--short"):
                    return "abc123"
                if args[:2] == ("branch", "--show-current"):
                    return "main"
                return ""

            row = {
                "name": "donor",
                "primary_suite": "accessibility",
                "source_snapshot": {
                    "git": True,
                    "head": "abc123",
                    "branch": "main",
                    "status_lines": 0,
                    "status_sha256": hashlib.sha256(b"").hexdigest(),
                    "patch_sha256": hashlib.sha256(b"").hexdigest(),
                },
            }
            with (
                patch("portfolio_suites.registry.PROJECTS_ROOT", root),
                patch("portfolio_suites.registry._git_value", side_effect=git_value),
                patch("portfolio_suites.registry._git_untracked_paths", return_value=([], False)),
            ):
                drift = check_project_git_drift("donor", row)

            self.assertTrue(drift["untracked_incomplete"])
            self.assertFalse(drift["untracked_enumeration_complete"])
            self.assertIn(
                "untracked_path_enumeration_failed",
                drift["untracked_incomplete_reasons"],
            )
            self.assertTrue(drift["has_drift"])
            self.assertIsNone(registry._live_snapshot("donor", drift))

            with (
                patch("portfolio_suites.registry.get_live_drift_report", return_value=[drift]),
                patch("portfolio_suites.registry.load_ledger", return_value={"projects": [row]}),
            ):
                self.assertEqual(registry.pending_snapshots(accept=True), {})

    def test_untracked_symlink_target_text_changes_the_digest_without_following(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("same bytes", encoding="utf-8")
            (root / "b.txt").write_text("same bytes", encoding="utf-8")
            link = root / "choice"
            link.symlink_to("a.txt")
            first_digest, first_incomplete = _untracked_content_digest(root, ["choice"])

            link.unlink()
            link.symlink_to("b.txt")
            second_digest, second_incomplete = _untracked_content_digest(root, ["choice"])

        self.assertFalse(first_incomplete)
        self.assertFalse(second_incomplete)
        self.assertNotEqual(first_digest, second_digest)
        self.assertIn("SYMLINK", first_digest)

    def test_exact_file_cap_is_complete_and_next_entry_truncates(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for index in range(1001):
                name = f"entry-{index:04d}.txt"
                (root / name).write_text(str(index), encoding="utf-8")
                paths.append(name)

            exact_digest, exact_incomplete = _untracked_content_digest(root, paths[:1000])
            overflow_digest, overflow_incomplete = _untracked_content_digest(root, paths)

        self.assertFalse(exact_incomplete)
        self.assertEqual(len(exact_digest.splitlines()), 1000)
        self.assertNotIn("MAX_UNTRACKED_FILES_TRUNCATION", exact_digest)
        self.assertTrue(overflow_incomplete)
        self.assertIn("MAX_UNTRACKED_FILES_TRUNCATION", overflow_digest)

    def test_validation_names_incomplete_untracked_fingerprint(self):
        from portfolio_suites import registry

        drift = {
            "name": "donor",
            "primary_suite": "accessibility",
            "snapshot_head": "abc123",
            "current_head": "abc123",
            "snapshot_branch": "main",
            "current_branch": "main",
            "snapshot_lines": 0,
            "current_lines": 0,
            "head_or_branch_drift": False,
            "lines_drift": False,
            "content_drift": False,
            "patch_drift": False,
            "untracked_incomplete": True,
            "untracked_incomplete_reasons": ["untracked_path_enumeration_failed"],
            "has_drift": True,
        }
        row = {
            "name": "donor",
            "primary_suite": "accessibility",
            "source_snapshot": {"git": True},
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "donor").mkdir()
            with (
                patch("portfolio_suites.registry.PROJECTS_ROOT", root),
                patch(
                    "portfolio_suites.registry.load_ledger",
                    return_value={"schema_version": "1.0.0", "projects": [row]},
                ),
                patch(
                    "portfolio_suites.registry.load_nested_ledger",
                    return_value={"schema_version": "1.0.0", "repositories": []},
                ),
                patch("portfolio_suites.registry.check_project_git_drift", return_value=drift),
            ):
                report = registry.validate_registry(check_live=True)

        self.assertTrue(
            any("untracked content fingerprint is incomplete" in warning for warning in report.warnings),
            report.warnings,
        )


class ReceiptSpecTableTests(unittest.TestCase):
    """A duplicate key in the receipt table silently discards a gate's spec.

    Python keeps the last of a duplicated dict key, so by import time the shadowed
    entry is already gone and no runtime check can see it. The source is the only
    place the duplication still exists, so that is where it is checked.
    """

    def test_receipt_spec_keys_are_declared_once(self):
        import ast

        source = (SUITES_ROOT / "src" / "portfolio_suites" / "receipts.py").read_text(encoding="utf-8")
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
                "evidence": "accessibility/evidence/A1-WCAG-AUDITOR-PARITY.json",
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
        for level in ("source_executed", "parity_verified", "adopted", "converged"):
            with self.subTest(level=level):
                errors = self._errors_for(level)
                self.assertTrue(
                    any("cannot occupy the runtime promotion level" in error for error in errors),
                    f"{level} was accepted for an analysis claim: {errors}",
                )

    def test_source_executed_cannot_be_bought_with_a_manifest_boolean(self):
        """The fail-open this guard replaced.

        `real_runtime: true` was the entire evidence for the strongest claim the ladder can
        make. Nothing required a source invocation, an argv, an exit code, a source
        fingerprint, or any receipt field proving the donor was executed -- so an analysis
        claim could be promoted to `source_executed` with its receipt left untouched, and
        `validate_registry(check_live=False)` still returned valid.
        """
        errors = self._errors_for("source_executed", kind="analysis")
        self.assertTrue(
            any("cannot occupy the runtime promotion level" in error for error in errors),
            f"source_executed was accepted for an analysis claim: {errors}",
        )

    def _source_claim(self, basis=None):
        suite = self._suite_with_claim("source_executed", kind="runtime")
        claim = suite["waves"][0]["recovery_claim"]
        claim["evidence_basis"] = sorted(RUNTIME_SOURCE_EVIDENCE if basis is None else basis)
        claim["receipt_contract"] = "portfolio-runtime-source-v1"
        return suite

    def test_source_executed_runtime_claim_requires_its_declared_evidence_basis(self):
        """Parity is enforced on its marker set; `source_executed` must be too."""
        suite = self._source_claim(
            basis=RUNTIME_SOURCE_EVIDENCE - {"module_fingerprints"}
        )
        with patch(
            "portfolio_suites.registry.load_suites",
            return_value={"accessibility": suite},
        ):
            report = validate_registry(check_live=False)
        self.assertTrue(
            any(
                "source_executed runtime evidence is missing module_fingerprints" in error
                for error in report.errors
            ),
            report.errors,
        )

    def test_source_executed_complete_evidence_basis_is_not_flagged(self):
        suite = self._source_claim()
        with patch(
            "portfolio_suites.registry.load_suites",
            return_value={"accessibility": suite},
        ):
            report = validate_registry(check_live=False)
        self.assertFalse(
            any("runtime evidence is missing" in error for error in report.errors),
            report.errors,
        )

    def test_source_inspected_is_the_highest_analysis_rung(self):
        errors = self._errors_for("source_inspected")
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
        with patch("portfolio_suites.receipts.ANALYSIS_RECEIPT_SPECS", collision):
            spec, error, key = _lookup_receipt_spec(None, "A3")
        self.assertIsNone(spec, "an ambiguous wave letter must not resolve to one suite's spec")
        self.assertIn("matches several suites", error)


class DurableLedgerWriteTests(unittest.TestCase):
    """The ledger cannot be rebuilt from the suites, so it is replaced atomically."""

    def test_ledger_is_replaced_atomically_not_truncated_in_place(self):
        from portfolio_suites import registry
        from portfolio_suites import txn

        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "project-ledger.json"
            original = '{"schema_version":"1.0.0","projects":[]}'
            ledger.write_text(original, encoding="utf-8")

            seen_during_write = {}

            real_exchange = txn.rename_exchange

            def watched_exchange(src, dst, *, directory_fd):
                # The swap is the commit point: mid-write, the destination must still hold
                # the complete old document, never a partial mixture.
                seen_during_write["content"] = ledger.read_text(encoding="utf-8")
                return real_exchange(src, dst, directory_fd=directory_fd)

            with patch.object(registry, "_LEDGER_PATH", ledger), \
                 patch.object(registry, "pending_snapshots", return_value={}), \
                 patch.object(registry, "apply_snapshot_updates", return_value=("NEW", ["proj"])), \
                 patch.object(txn, "rename_exchange", side_effect=watched_exchange):
                registry.fingerprint_baselines(dry_run=False)

            self.assertEqual(seen_during_write["content"], original)
            self.assertEqual(ledger.read_text(encoding="utf-8"), "NEW")

    def test_a_failed_ledger_write_leaves_the_previous_document_intact(self):
        from portfolio_suites import registry
        from portfolio_suites import txn

        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "project-ledger.json"
            original = '{"schema_version":"1.0.0","projects":[]}'
            ledger.write_text(original, encoding="utf-8")

            with patch.object(registry, "_LEDGER_PATH", ledger), \
                 patch.object(registry, "pending_snapshots", return_value={}), \
                 patch.object(registry, "apply_snapshot_updates", return_value=("NEW", ["proj"])), \
                 patch.object(
                     txn, "rename_exchange",
                     side_effect=OSError(5, "Input/output error"),
                 ):
                with self.assertRaises(registry.LedgerConflict):
                    registry.fingerprint_baselines(dry_run=False)

            self.assertEqual(ledger.read_text(encoding="utf-8"), original)
            leftovers = [
                p.name for p in Path(tmp).iterdir()
                if p.name != ledger.name and p.name != ledger.name + ".lock"
            ]
            self.assertEqual(leftovers, [], "temporary file was left behind")


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

    The commit primitive creates its candidate 0600. Replacing the 0644 project ledger with
    it strips group and other read access, and Git cannot report the loss because it tracks
    only the executable bit -- both modes are `100644` to Git.
    """

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

    def test_a_ledger_commit_that_lands_then_fails_is_not_reported_as_unwritten(self):
        """"Cannot write" and "wrote it but cannot prove it survives a crash" are opposite
        operator instructions. The ledger is the only record of all 70 dispositions, so a
        post-commit durability failure must not read as a clean refusal."""
        import os
        import stat as stat_module
        from portfolio_suites import registry
        from portfolio_suites.paths import CommitUnverified

        real_fsync = os.fsync

        def fail_directory_fsync(fd):
            # Directories only: the candidate's own fsync happens before the commit point.
            if os.fstat(fd).st_mode & 0o170000 == 0o040000:
                raise OSError("forced directory fsync failure")
            return real_fsync(fd)

        with TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "project-ledger.json"
            ledger.write_text('{"schema_version":"1.0.0","projects":[]}', encoding="utf-8")
            with patch.object(registry, "_LEDGER_PATH", ledger), \
                 patch.object(registry, "pending_snapshots", return_value={}), \
                 patch.object(registry, "apply_snapshot_updates", return_value=("NEW", ["proj"])), \
                 patch.object(os, "fsync", fail_directory_fsync):
                with self.assertRaises(CommitUnverified):
                    registry.fingerprint_baselines(dry_run=False)

            self.assertEqual(
                ledger.read_text(encoding="utf-8"), "NEW", "the replacement did commit"
            )


class AnalysisReceiptSpecCoverageTests(unittest.TestCase):
    """Every completed analysis wave must reach a spec that can actually check it.

    A wave with no `ANALYSIS_RECEIPT_SPECS` entry used to pass validation silently by
    declaring `.md` evidence: the suffix short-circuited `evidence_errors` before the
    semantic check ran, so the receipt was only scanned for its basis strings as bare
    substrings. Both halves of that hole are guarded here.
    """

    def _complete_analysis_waves(self):
        for suite_id, manifest in load_suites().items():
            for wave in manifest.get("waves", []):
                claim = wave.get("recovery_claim") or {}
                if wave.get("status") == "complete" and claim.get("kind") == "analysis":
                    yield suite_id, wave

    def test_every_completed_analysis_wave_has_a_receipt_spec(self):
        from portfolio_suites.receipts import ANALYSIS_RECEIPT_SPECS

        missing = [
            f"{suite_id}/{wave['id']}"
            for suite_id, wave in self._complete_analysis_waves()
            if f"{suite_id}/{wave['id']}" not in ANALYSIS_RECEIPT_SPECS
        ]
        self.assertEqual(missing, [], "completed analysis waves with no checkable receipt spec")

    def test_every_analysis_receipt_is_json(self):
        from portfolio_suites.registry import resolve_declared_evidence_path

        prose = []
        for suite_id, wave in self._complete_analysis_waves():
            path = resolve_declared_evidence_path(wave.get("evidence"), suite_id)
            if path is not None and path.suffix != ".json":
                prose.append(f"{suite_id}/{wave['id']} -> {path.name}")
        self.assertEqual(prose, [], "analysis receipts must be structured JSON, not prose")

    def test_a_spec_key_names_a_wave_that_exists(self):
        from portfolio_suites.receipts import ANALYSIS_RECEIPT_SPECS

        declared = {
            f"{suite_id}/{wave['id']}"
            for suite_id, manifest in load_suites().items()
            for wave in manifest.get("waves", [])
        }
        self.assertEqual(
            sorted(set(ANALYSIS_RECEIPT_SPECS) - declared), [],
            "spec entries for waves no manifest declares",
        )

    def test_every_analysis_runner_receipt_validates_against_spec(self):
        from portfolio_suites.receipts import ANALYSIS_RECEIPT_SPECS, _analysis_receipt_semantic_errors
        from portfolio_suites.waves import WaveRunner

        suites = load_suites()
        captured: dict[tuple[str, str], Any] = {}
        orig_settle = WaveRunner._settle

        def capture_settle(suite, wave_id, write_evidence, passed, receipt, message, data=None, failure_message=None):
            captured[(suite["id"], wave_id)] = receipt
            return orig_settle(suite, wave_id, write_evidence, passed, receipt, message, data, failure_message)

        with patch.object(WaveRunner, "_settle", side_effect=capture_settle):
            for key in sorted(ANALYSIS_RECEIPT_SPECS):
                suite_id, wave_id = key.split("/", 1)
                if WaveRunner.has_runner(suite_id, wave_id):
                    WaveRunner.run_wave(suite_id, wave_id, write_evidence=False)

        failures = []
        for (suite_id, wave_id), receipt in captured.items():
            wave = next(w for w in suites[suite_id]["waves"] if w["id"] == wave_id)
            basis = set(wave.get("recovery_claim", {}).get("evidence_basis") or [])
            if not isinstance(receipt, dict):
                failures.append(f"{suite_id}/{wave_id}: receipt is not a dict ({type(receipt).__name__})")
                continue
            missing_basis = sorted(basis - set(receipt))
            if missing_basis:
                failures.append(f"{suite_id}/{wave_id}: missing declared basis fields: {missing_basis}")
            semantic_errors = _analysis_receipt_semantic_errors(wave, receipt, suite_id)
            if semantic_errors:
                failures.append(f"{suite_id}/{wave_id}: semantic errors: {semantic_errors}")

        self.assertEqual(failures, [], "runner receipts that failed analysis spec validation")


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
        from portfolio_suites import receipts

        with patch.object(receipts, "ANALYSIS_RECEIPT_SPECS", self._with_extra_spec()):
            errors = receipts._analysis_receipt_semantic_errors(
                {"id": "A3", "recovery_claim": {"kind": "analysis", "level": "source_executed"}},
                {"ok": True},
                "game-design",
            )
        self.assertEqual(errors, [], f"accessibility rules leaked into game-design: {errors}")

    def test_the_owning_suite_is_still_fully_enforced(self):
        from portfolio_suites import receipts

        with patch.object(receipts, "ANALYSIS_RECEIPT_SPECS", self._with_extra_spec()):
            errors = receipts._analysis_receipt_semantic_errors(
                {"id": "A3", "recovery_claim": {"kind": "analysis", "level": "source_executed"}},
                {"ok": True},
                "accessibility",
            )
        self.assertTrue(any("three declared overlay sources" in e for e in errors), errors)
        self.assertTrue(any("receipt_version must be" in e for e in errors), errors)

    def test_every_special_branch_is_reachable_only_through_its_own_suite(self):
        """Each hard-coded rule set must name a suite/wave that really declares it."""
        import re as _re

        source = (SUITES_ROOT / "src" / "portfolio_suites" / "receipts.py").read_text(encoding="utf-8")
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

        source = (SUITES_ROOT / "src" / "portfolio_suites" / "receipts.py").read_text(encoding="utf-8")
        body = source[source.index("def _analysis_receipt_semantic_errors"):source.index("def _runtime_parity_receipt_errors")]
        top_level = [
            line for line in body.splitlines()
            if _re.match(r'    (if|elif) wave_id (==|in) ', line)
        ]
        self.assertEqual(top_level, [], f"branches still dispatch on a bare wave id: {top_level}")


class EvidenceOwnershipTests(unittest.TestCase):
    """Every artifact under a suite's evidence/ directory must be owned by something.

    An undeclared file sitting beside a canonical receipt reads as evidence, passes every
    gate, and can contradict the record it sits next to.
    """

    def test_no_artifact_under_active_evidence_is_undeclared(self):
        suites = load_suites()
        declared = set()
        for suite_id, manifest in suites.items():
            for wave in manifest.get("waves", []):
                declared.add((SUITES_ROOT / wave["evidence"]).resolve(strict=False))
            for entry in manifest.get("supporting_evidence", []):
                declared.add((SUITES_ROOT / entry["path"]).resolve(strict=False))
        undeclared = sorted(
            str(found.relative_to(SUITES_ROOT))
            for suite_id in suites
            for found in (SUITES_ROOT / suite_id / "evidence").rglob("*")
            if found.is_file() and found.resolve(strict=False) not in declared
        )
        self.assertEqual(undeclared, [], f"undeclared artifacts under active evidence: {undeclared}")

    def test_supporting_evidence_declares_a_role_and_a_reason(self):
        for suite_id, manifest in load_suites().items():
            for entry in manifest.get("supporting_evidence", []):
                with self.subTest(suite=suite_id, path=entry.get("path")):
                    self.assertIn(entry.get("role"), {"fixture", "ancillary", "historical"})
                    self.assertTrue(str(entry.get("reason", "")).strip())
                    self.assertTrue((SUITES_ROOT / entry["path"]).is_file())

    def test_historical_narratives_announce_that_they_are_not_evidence(self):
        for suite_id, manifest in load_suites().items():
            for entry in manifest.get("supporting_evidence", []):
                if entry.get("role") != "historical":
                    continue
                with self.subTest(suite=suite_id, path=entry["path"]):
                    text = (SUITES_ROOT / entry["path"]).read_text(encoding="utf-8")
                    self.assertIn("SUPERSEDED", text)
                    self.assertIn("not evidence", text)


class DonorGitIsolationTests(unittest.TestCase):
    """A read-only drift scan must never execute repository-local Git code.

    `core.fsmonitor` names an executable that Git launches during status refreshes. The
    runner strips the parent environment, but environment stripping alone cannot stop local
    configuration from executing code -- `.git/config` ships with the checkout. A drift
    pass across seventy donors would otherwise run seventy donor-controlled programs with
    this process's authority (approval-store path, credentials, agent sockets) behind them.
    """

    _git = staticmethod(WorktreeDriftTests._git)
    _dirty_repo = WorktreeDriftTests._dirty_repo

    def test_repository_local_fsmonitor_executable_is_never_run(self):
        import os as os_module

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._dirty_repo(root)

            sentinel = root / "fsmonitor-sentinel"
            script = root / "rogue-fsmonitor.sh"
            script.write_text(
                "#!/bin/sh\n"
                f"env > {shlex.quote(str(sentinel))}\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            # The hostile setting lives in the donor's own repository config, which no
            # environment variable can suppress.
            self._git(repo, "config", "core.fsmonitor", str(script))

            # The control plane's own authority is in the parent environment, exactly as
            # it is during a real drift pass; the sentinel proves what a launched child
            # would have inherited.
            approval_sentinel = str(root / "approval-store-path")
            os_module.environ["PORTFOLIO_OPERATOR_APPROVAL_STORE"] = approval_sentinel
            self.addCleanup(os_module.environ.pop, "PORTFOLIO_OPERATOR_APPROVAL_STORE", None)

            with patch("portfolio_suites.registry.PROJECTS_ROOT", root):
                from portfolio_suites.registry import check_project_git_drift

                drift = check_project_git_drift("donor", {"source_snapshot": {"git": True}})

            self.assertTrue(
                drift is not None and drift["status_readable"],
                "drift inspection must still work with fsmonitor neutralized",
            )
            self.assertFalse(
                sentinel.exists(),
                "a donor-local core.fsmonitor executable was run by a drift command",
            )


class DriftFailsClosedTests(unittest.TestCase):
    """Unfingerprinted state is unresolved drift, never a clean baseline.

    Both cases hold the pathname and porcelain status shape constant while the bytes move,
    which is exactly the shape that reported `has_drift=false` before.
    """

    _git = staticmethod(WorktreeDriftTests._git)
    _dirty_repo = WorktreeDriftTests._dirty_repo

    def test_sensitive_untracked_content_is_incomplete_not_complete(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._dirty_repo(root)
            (repo / ".env").write_text("SECRET=one\n", encoding="utf-8")
            with patch("portfolio_suites.registry.PROJECTS_ROOT", root):
                from portfolio_suites.registry import check_project_git_drift

                first = check_project_git_drift("donor", {"source_snapshot": {"git": True}})
                self.assertFalse(
                    first["untracked_fingerprint_complete"],
                    "an unfingerprinted secret cannot be reported as a complete fingerprint",
                )
                self.assertIn(
                    "untracked_content_fingerprint_incomplete",
                    first["fingerprint_incomplete_reasons"],
                )
                # The reason must not leak the name or the contents of the sensitive entry.
                self.assertNotIn(".env", " ".join(first["fingerprint_incomplete_reasons"]))
                self.assertNotIn("SECRET", first["current_status_sha256"])

                baseline = {
                    "git": True,
                    "branch": first["current_branch"],
                    "head": first["current_head"],
                    "status_lines": first["current_lines"],
                    "status_sha256": first["current_status_sha256"],
                    "patch_sha256": first["current_patch_sha256"],
                }
                (repo / ".env").write_text("SECRET=two\n", encoding="utf-8")
                after = check_project_git_drift("donor", {"source_snapshot": baseline})
                self.assertTrue(after["has_drift"], "unresolved state must never report clean")
                self.assertIsNone(
                    _registry_module._live_snapshot("donor", after),
                    "an incomplete fingerprint must refuse baseline acceptance",
                )

    def test_an_unreadable_patch_is_incomplete_not_clean(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._dirty_repo(root)
            real_git_value = _registry_module._git_value

            def patch_unavailable(source, *args, **kwargs):
                if args[:1] == ("diff",):
                    return "unavailable"
                return real_git_value(source, *args, **kwargs)

            with patch("portfolio_suites.registry.PROJECTS_ROOT", root), \
                 patch("portfolio_suites.registry._git_value", patch_unavailable):
                from portfolio_suites.registry import check_project_git_drift

                first = check_project_git_drift("donor", {"source_snapshot": {"git": True}})
                self.assertFalse(first["patch_readable"])
                self.assertIn("git_patch_unreadable", first["fingerprint_incomplete_reasons"])

                baseline = {
                    "git": True,
                    "branch": first["current_branch"],
                    "head": first["current_head"],
                    "status_lines": first["current_lines"],
                    "status_sha256": first["current_status_sha256"],
                    "patch_sha256": first["current_patch_sha256"],
                }
                # Byte change to an already-dirty tracked file: porcelain shape is unchanged
                # and the patch -- the only thing that would have caught it -- is unreadable.
                (repo / "f.txt").write_text("a completely different dirty edit\n", encoding="utf-8")
                after = check_project_git_drift("donor", {"source_snapshot": baseline})

                self.assertFalse(after["patch_drift"], "an unreadable patch cannot show drift")
                self.assertTrue(after["has_drift"], "but it must not report clean either")
                self.assertIsNone(
                    _registry_module._live_snapshot("donor", after),
                    "an unreadable patch must refuse baseline acceptance",
                )


class LedgerTransactionTests(unittest.TestCase):
    """The ledger is the single source of truth for all 70 dispositions and cannot be rebuilt.

    Rebuilding the document from text read before a long live-git scan and then replacing
    the file discards whatever another writer committed in between -- and the replace
    succeeds, so nothing reports it.
    """

    def _ledger(self, root, note):
        """One project per line with a source_snapshot field, matching the real ledger shape."""
        path = root / "portfolio" / "project-ledger.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{\n  "schema_version": "1.0.0",\n  "projects": [\n'
            '    {"name":"donor","note":"' + note + '","source_snapshot":{"git":true}}\n'
            "  ]\n}\n",
            encoding="utf-8",
        )
        return path

    def test_a_concurrent_edit_aborts_instead_of_being_overwritten(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = self._ledger(root, "initial")

            def concurrent_writer(_accept):
                # Lands after the transaction's read, while live state is being computed.
                ledger.write_text(
                    ledger.read_text(encoding="utf-8").replace('"note":"initial"', '"note":"writer-b"'),
                    encoding="utf-8",
                )
                return {"donor": {"git": True, "branch": "main", "head": "abc1234",
                                  "status_lines": 0, "status_sha256": "d" * 64, "patch_sha256": ""}}

            with patch.object(_registry_module, "_LEDGER_PATH", ledger), \
                 patch.object(_registry_module, "SUITES_ROOT", root), \
                 patch.object(_registry_module, "pending_snapshots", concurrent_writer):
                with self.assertRaises(_registry_module.LedgerConflict):
                    _registry_module.fingerprint_baselines(accept=True)

            surviving = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(surviving["projects"][0]["note"], "writer-b", "the concurrent edit was lost")

    def test_an_edit_landing_during_the_commit_window_is_not_overwritten(self):
        """The old second-line defence rechecked the digest and then still had to create,
        write, flush, and fsync a temporary before its replacing rename -- so an edit that
        landed inside that interval was silently destroyed. Conflict detection now lives
        inside the commit primitive itself, so this probe must abort the transaction."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = self._ledger(root, "initial")
            real_write_temp = _registry_module.write_temp_payload

            def edit_during_commit(directory_fd, name, payload, **kwargs):
                # Lands after the transaction's read and during the commit preparation:
                # exactly the interval the old digest recheck could not cover.
                ledger.write_text(
                    ledger.read_text(encoding="utf-8").replace('"note":"initial"', '"note":"writer-b"'),
                    encoding="utf-8",
                )
                return real_write_temp(directory_fd, name, payload, **kwargs)

            snapshots = {"donor": {"git": True, "branch": "main", "head": "abc1234",
                                   "status_lines": 0, "status_sha256": "d" * 64, "patch_sha256": ""}}
            with patch.object(_registry_module, "_LEDGER_PATH", ledger), \
                 patch.object(_registry_module, "SUITES_ROOT", root), \
                 patch.object(_registry_module, "write_temp_payload", side_effect=edit_during_commit), \
                 patch.object(_registry_module, "pending_snapshots", return_value=snapshots):
                with self.assertRaises(_registry_module.LedgerConflict):
                    _registry_module.fingerprint_baselines(accept=True)

            surviving = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(
                surviving["projects"][0]["note"], "writer-b",
                "the commit replaced an edit that landed inside the commit window",
            )
            leftovers = [
                p.name for p in ledger.parent.iterdir()
                if p.name != ledger.name and p.name != ledger.name + ".lock"
            ]
            self.assertEqual(leftovers, [], leftovers)

    def test_the_lock_serializes_overlapping_transactions(self):
        import threading

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._ledger(root, "initial")
            overlapped = []
            inside = threading.Event()
            released = threading.Event()

            with patch.object(_registry_module, "SUITES_ROOT", root):
                def hold_the_lock():
                    with _registry_module._ledger_lock():
                        inside.set()
                        released.wait(timeout=5)

                holder = threading.Thread(target=hold_the_lock)
                holder.start()
                self.assertTrue(inside.wait(timeout=5))

                def second_writer():
                    with _registry_module._ledger_lock():
                        overlapped.append(released.is_set())

                contender = threading.Thread(target=second_writer)
                contender.start()
                contender.join(timeout=0.5)
                self.assertTrue(contender.is_alive(), "the second transaction was not blocked")
                released.set()
                contender.join(timeout=5)
                holder.join(timeout=5)

        self.assertEqual(overlapped, [True], "the second transaction ran before the first finished")


if __name__ == "__main__":
    unittest.main()

