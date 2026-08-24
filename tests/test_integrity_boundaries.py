"""Negative-path regression tests for the 4 core P1 trust-boundary integrity guarantees:
1. Approval store single-use token consumption cannot be bypassed via symlink/hardlink aliases.
2. Wave evidence recording cannot escape suite boundary via symlinked evidence directories.
3. Git drift detection discovers byte modifications in untracked candidate donor files.
4. Shared contract schema validation rejects malformed nested structures recursively.
"""

import errno
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites import approvals, contracts, registry, waves
from portfolio_suites.approvals import (
    APPROVAL_SCHEMA,
    STORE_ENV,
    ApprovalError,
    canonical_digest,
    token_sha256,
    verify_operator_approval,
)
from portfolio_suites.contracts import ContractError, validate_contract
from portfolio_suites.registry import check_project_git_drift, validate_registry
from portfolio_suites.paths import open_confined_directory
from portfolio_suites.waves import _record_evidence


def _issue_approval(tmpdir: str) -> tuple[str, str, dict[str, str]]:
    bindings = {"operation": "vcc_release", "decision": "approved", "payload_sha256": canonical_digest("draft")}
    record = {
        "approval_id": "apr-p1-probe",
        "schema": APPROVAL_SCHEMA,
        "reviewer": "Ryan Johnson",
        "issued_at": "2026-08-20T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        **bindings,
    }
    token = f"opa1.{record['approval_id']}.s3cret"
    record["token_sha256"] = token_sha256(token)
    store = os.path.join(tmpdir, "real_authority.json")
    with open(store, "w", encoding="utf-8") as f:
        json.dump({"approvals": [record]}, f)
    return store, token, bindings


class IntegrityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, STORE_ENV, None)

    # 1. Approval token alias replay probe
    def test_p1_approval_replay_via_symlink_alias_is_refused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_store, token, bindings = _issue_approval(tmpdir)
            symlink_store = os.path.join(tmpdir, "alias_store.json")
            os.symlink(real_store, symlink_store)

            # Configuring alias store must fail closed and refuse symlinks
            os.environ[STORE_ENV] = symlink_store
            with self.assertRaises(ApprovalError):
                verify_operator_approval(token, bindings)

            # Real authority store must remain unconsumed
            with open(real_store, encoding="utf-8") as f:
                data = json.load(f)
            self.assertFalse(data["approvals"][0].get("consumed", False))

            # Pointing to real store verifies once and only once
            os.environ[STORE_ENV] = real_store
            verified = verify_operator_approval(token, bindings)
            self.assertTrue(verified["consumed"])

            # Second attempt on real store must fail due to single-use consumption
            with self.assertRaises(ApprovalError):
                verify_operator_approval(token, bindings)

    # 2. Cross-suite evidence symlink confinement probe
    def test_p1_cross_suite_evidence_symlink_redirection_is_refused(self):
        wave = {
            "id": "P1",
            "evidence": "production-house/evidence/P1-RECEIPT.json",
            "recovery_claim": {
                "kind": "analysis",
                "level": "prototype",
                "evidence_basis": ["wave"],
            },
        }
        manifests = {"production-house": {"id": "production-house", "waves": [wave]}}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "suites"
            root.mkdir()
            operator_evidence = root / "operator-os" / "evidence"
            operator_evidence.mkdir(parents=True)
            prod_dir = root / "production-house"
            prod_dir.mkdir()
            (prod_dir / "evidence").symlink_to(operator_evidence)

            with self.assertRaises(OSError) as ctx:
                open_confined_directory(root, "production-house/evidence", create=True)
            self.assertIn(
                ctx.exception.errno,
                {errno.ELOOP, errno.ENOTDIR},
                "confined open must refuse the symlink, not follow it",
            )

            with (
                patch("portfolio_suites.waves.SUITES_ROOT", root),
                patch("portfolio_suites.waves.load_suites", return_value=manifests),
                patch("portfolio_suites.waves.write_temp_payload") as writer,
            ):
                result = _record_evidence(
                    wave,
                    {"wave": "P1"},
                    write_evidence=True,
                    passed=True,
                )

            self.assertIsNone(result, "recorder must refuse cross-suite symlinked evidence directory")
            writer.assert_not_called()
            self.assertEqual(list(operator_evidence.iterdir()), [], "bytes must not leak into another suite")

    # 3. Untracked file content mutation drift probe
    def test_p1_untracked_content_modification_triggers_drift(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "donor-candidate"
            repo_dir.mkdir()

            # Initialize a git repo
            os.system(f"git -C '{repo_dir}' init -q")
            os.system(f"git -C '{repo_dir}' config user.name 'Test' && git -C '{repo_dir}' config user.email 'test@test'")
            tracked_file = repo_dir / "README.md"
            tracked_file.write_text("initial tracked content\n", encoding="utf-8")
            os.system(f"git -C '{repo_dir}' add README.md && git -C '{repo_dir}' commit -q -m 'Initial'")

            # Add an untracked file
            untracked_file = repo_dir / "candidate.py"
            untracked_file.write_text("print('version 1')\n", encoding="utf-8")

            # Capture baseline drift snapshot
            with patch("portfolio_suites.registry.PROJECTS_ROOT", Path(tmpdir)):
                initial_row = {
                    "source_snapshot": {
                        "git": True,
                        "head": "dummy",
                        "branch": "main",
                    }
                }
                # Populate snapshot values from initial state
                initial_drift = check_project_git_drift("donor-candidate", initial_row)
                self.assertIsNotNone(initial_drift)

                row_with_snapshot = {
                    "primary_suite": "production-house",
                    "source_snapshot": {
                        "git": True,
                        "head": initial_drift["current_head"],
                        "branch": initial_drift["current_branch"],
                        "status_lines": initial_drift["current_lines"],
                        "status_sha256": initial_drift["current_status_sha256"],
                        "patch_sha256": initial_drift["current_patch_sha256"],
                    },
                }

                # Verify clean before changes
                drift_before = check_project_git_drift("donor-candidate", row_with_snapshot)
                self.assertFalse(drift_before["content_drift"])
                self.assertFalse(drift_before["has_drift"])

                # Mutate untracked candidate file bytes without renaming
                untracked_file.write_text("print('version 2 - modified bytes')\n", encoding="utf-8")

                drift_after = check_project_git_drift("donor-candidate", row_with_snapshot)
                self.assertTrue(drift_after["content_drift"], "untracked byte changes must trigger content_drift")
                self.assertTrue(drift_after["has_drift"])

                # Verify validator emits warning on content drift
                with patch("portfolio_suites.registry.load_ledger", return_value={"schema_version": "1.0.0", "projects": [dict(name="donor-candidate", **row_with_snapshot)]}):
                    report = validate_registry(check_live=True)
                    self.assertTrue(any("untracked/status content drifted" in w for w in report.warnings))

    # 4. Shared contract nested structure validation probes
    def test_p1_nested_contract_malformed_structures_are_rejected(self):
        # A11yFinding.evidence = [42]
        finding_sample = contracts.generate_sample("A11yFinding")
        finding_bad = {**finding_sample, "evidence": [42]}
        with self.assertRaisesRegex(ContractError, r"A11yFinding\.evidence\[0\] must be a JSON object"):
            validate_contract("A11yFinding", finding_bad)

        # SourceRecord.provenance = {}
        source_sample = contracts.generate_sample("SourceRecord")
        source_bad = {**source_sample, "provenance": {}}
        with self.assertRaisesRegex(ContractError, r"SourceRecord\.provenance must contain at least 1 propert\(y/ies\)"):
            validate_contract("SourceRecord", source_bad)

        # BrandPackage.approved_claims = ["not-an-object"]
        brand_sample = contracts.generate_sample("BrandPackage")
        brand_bad_claim = {**brand_sample, "approved_claims": ["not-an-object"]}
        with self.assertRaisesRegex(ContractError, r"BrandPackage\.approved_claims\[0\] must be a JSON object"):
            validate_contract("BrandPackage", brand_bad_claim)

        # BrandPackage.assets = [None]
        brand_bad_asset = {**brand_sample, "assets": [None]}
        with self.assertRaisesRegex(ContractError, r"BrandPackage\.assets\[0\] must be a JSON object"):
            validate_contract("BrandPackage", brand_bad_asset)

        # BrandPackage.provenance = [42]
        brand_bad_prov = {**brand_sample, "provenance": [42]}
        with self.assertRaisesRegex(ContractError, r"BrandPackage\.provenance\[0\] must be a JSON object"):
            validate_contract("BrandPackage", brand_bad_prov)


if __name__ == "__main__":
    unittest.main()
