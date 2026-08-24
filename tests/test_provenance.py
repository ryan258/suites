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

    def test_donor_environment_withholds_capabilities_that_are_not_named_like_secrets(self):
        """The inherited capability is rarely spelled out in the variable's name.

        Every value here is credential-bearing or credential-reaching, and not one of them
        matches KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL.
        """
        capabilities = {
            "SSH_AUTH_SOCK": "/private/tmp/ssh-agent.sock",       # a live agent socket
            "GPG_AGENT_INFO": "/private/tmp/gpg:0:1",
            "DOCKER_CONFIG": "/home/example/.docker",             # holds registry auth
            "KUBECONFIG": "/home/example/.kube/config",           # holds cluster certs
            "AWS_PROFILE": "production",
            "PIP_INDEX_URL": "https://user:hunter2@pypi.example.com/simple",
            "HTTPS_PROXY": "http://user:hunter2@proxy.example.com:8080",
            "PORTFOLIO_OPERATOR_APPROVAL_STORE": "/private/tmp/approvals.json",
            "HOME": "/home/example",                              # reaches all of the above
        }
        with patch.dict(os.environ, capabilities):
            env = common.donor_env()

        for name, value in capabilities.items():
            with self.subTest(variable=name):
                self.assertNotIn(name, env)
                self.assertNotIn(value, env.values())
        self.assertNotIn("hunter2", " ".join(env.values()))
        # Git must not be able to reach a credential helper or block on a prompt.
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_withholding_home_does_not_change_what_git_considers_untracked(self):
        """Security hardening must not silently reclassify every donor's working tree.

        Git's global excludes live under HOME, which donors no longer get. Losing them would
        flip clean donors to dirty across the whole ledger -- a change to the migration
        record wearing a security fix's clothes.
        """
        env = common.donor_env()
        self.assertNotIn("HOME", env)
        if common._global_excludes_file() is None:
            self.skipTest("no global gitignore configured on this machine")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "core.excludesFile")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], common._global_excludes_file())
        self.assertEqual(env["GIT_CONFIG_COUNT"], "1")

    def test_a_gate_cannot_pass_a_credential_through_the_explicit_addition(self):
        with self.assertRaises(ValueError):
            common.donor_env({"DONOR_API_KEY": "sk-live"})


if __name__ == "__main__":
    unittest.main()
