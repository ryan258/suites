import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites import contracts, registry
from portfolio_suites.adapters.common import is_meaningful_git_fingerprint as adapter_predicate
from portfolio_suites.adapters import common
from portfolio_suites.paths import SUITES_ROOT
from portfolio_suites.provenance import is_meaningful_git_fingerprint


class ProvenanceTests(unittest.TestCase):
    def test_all_control_plane_modules_share_the_canonical_checkout_root(self):
        self.assertEqual(
            {registry.SUITES_ROOT, contracts.SUITES_ROOT, common.SUITES_ROOT},
            {SUITES_ROOT},
        )

    def test_adapter_and_registry_share_one_fail_closed_fingerprint_predicate(self):
        self.assertIs(adapter_predicate, is_meaningful_git_fingerprint)
        self.assertIs(registry.is_meaningful_git_fingerprint, is_meaningful_git_fingerprint)
        valid = {
            "branch": "main",
            "head": "a" * 40,
            "tested_files_fingerprint": {"README.md": "b" * 64},
        }
        self.assertTrue(is_meaningful_git_fingerprint(valid))
        for invalid in (
            None,
            {},
            {**valid, "branch": "unknown"},
            {**valid, "head": ""},
            {**valid, "tested_files_fingerprint": {}},
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(is_meaningful_git_fingerprint(invalid))

    def test_dirty_secret_files_are_neither_hashed_nor_named_in_fingerprints(self):
        with tempfile.TemporaryDirectory() as raw_root:
            repo = Path(raw_root)

            def git(*args: str) -> None:
                subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

            git("init", "-q")
            (repo / "README.md").write_text("donor\n")
            git("add", "README.md")
            git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")
            (repo / ".env").write_text("OPENROUTER_API_KEY=sk-live-secret\n")
            (repo / "notes.md").write_text("ordinary\n")

            fingerprint = common.get_git_fingerprint(repo, tracked_files=["README.md"])

        self.assertEqual(fingerprint["dirty_files_count"], 2)
        self.assertIn("?? <redacted-sensitive-path>", fingerprint["dirty_files"])
        self.assertNotIn(".env", " ".join(fingerprint["dirty_files"]))
        self.assertNotIn(".env", fingerprint["tested_files_fingerprint"])
        self.assertIn("notes.md", fingerprint["tested_files_fingerprint"])

    def test_donor_subprocess_environment_drops_control_plane_secrets(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-live", "AWS_SECRET_ACCESS_KEY": "x"}):
            env = common.donor_env()
        self.assertNotIn("OPENROUTER_API_KEY", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertIn("PATH", env)


if __name__ == "__main__":
    unittest.main()
