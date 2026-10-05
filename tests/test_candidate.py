from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.candidate import inspect_candidate
from portfolio_suites.diagnostics import PACKAGE_ASSETS, inspect_environment


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        (self.root / "file.txt").write_text("base\n")
        self.git("add", "file.txt")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, env={"PATH": os.environ["PATH"],
                              "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})

    def candidate(self):
        result = inspect_candidate(self.root)
        self.assertTrue(result["complete"], result)
        return result

    def test_identity_covers_staging_and_equal_length_tracked_and_untracked_edits(self):
        before = self.candidate()
        self.assertEqual(before, self.candidate())
        (self.root / "file.txt").write_text("edit\n")
        edited = self.candidate()
        self.assertNotEqual(before["sha256"], edited["sha256"])
        self.git("add", "file.txt")
        staged = self.candidate()
        self.assertNotEqual(edited["sha256"], staged["sha256"])
        self.assertEqual(edited["working_tree_sha256"], staged["working_tree_sha256"])
        (self.root / "new.txt").write_text("one")
        one = self.candidate()
        (self.root / "new.txt").write_text("two")
        self.assertNotEqual(one["sha256"], self.candidate()["sha256"])

    def test_deletion_and_executable_mode_change_identity(self):
        before = self.candidate()
        (self.root / "file.txt").chmod(0o755)
        self.assertNotEqual(before["sha256"], self.candidate()["sha256"])
        (self.root / "file.txt").unlink()
        self.assertEqual(self.candidate()["files"], [{"path": "file.txt", "state": "deleted"}])

    def test_ignored_bytes_are_explicitly_outside_scope(self):
        (self.root / ".gitignore").write_text("cache/\n")
        (self.root / "cache").mkdir()
        baseline = self.candidate()
        (self.root / "cache/data").write_text("runtime data")
        self.assertEqual(baseline, self.candidate())
        self.assertFalse(baseline["ignored_files_included"])

    def test_unsafe_files_and_sensitive_paths_never_receive_a_digest(self):
        target = self.root / "unsafe"
        for kind in ("symlink", "hardlink", "fifo", "sensitive"):
            with self.subTest(kind=kind):
                if kind == "symlink": target.symlink_to("file.txt")
                elif kind == "hardlink": os.link(self.root / "file.txt", target)
                elif kind == "fifo": os.mkfifo(target)
                else:
                    target = self.root / "credentials.json"
                    target.write_text("DO-NOT-READ")
                result = inspect_candidate(self.root)
                self.assertFalse(result["complete"])
                self.assertIsNone(result["sha256"])
                self.assertNotIn("DO-NOT-READ", json.dumps(result))
                self.assertNotIn(str(target), json.dumps(result))
                target.unlink()

    def test_budget_and_mid_scan_change_fail_closed(self):
        with patch("portfolio_suites.candidate.MAX_FILE_BYTES", 2):
            self.assertFalse(inspect_candidate(self.root)["complete"])
        with patch("portfolio_suites.candidate._observe", side_effect=[{"one": 1}, {"one": 2}]):
            result = inspect_candidate(self.root)
        self.assertEqual(result["errors"], ["candidate_changed_during_observation"])
        self.assertIsNone(result["sha256"])

    def test_nested_repository_root_is_refused(self):
        child = self.root / "child"
        child.mkdir()
        self.assertEqual(inspect_candidate(child)["errors"], ["workspace_is_not_repository_root"])


class DiagnosticsTests(unittest.TestCase):
    def test_missing_assets_and_private_configuration_are_reported_without_values(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "SUITES_ROOT": "/private/workspace", "PORTFOLIO_OPERATOR_APPROVAL_STORE": "/private/secret-store",
            "OPENROUTER_API_KEY": "DO-NOT-DISCLOSE",
        }):
            root = Path(temp)
            result = inspect_environment(root, root)
        self.assertFalse(result["ok"])
        self.assertIn("web/catalog.js", [c["name"] for c in result["checks"] if c["status"] == "blocked"])
        for secret in ("/private/workspace", "/private/secret-store", "DO-NOT-DISCLOSE"):
            self.assertNotIn(secret, json.dumps(result))

    def test_assets_share_the_distribution_inventory(self):
        from tests.test_wheel_smoke import REQUIRED_PACKAGE_DATA
        self.assertEqual(set(REQUIRED_PACKAGE_DATA), {"portfolio_suites/" + p for p in PACKAGE_ASSETS})
