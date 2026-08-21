import unittest

from portfolio_suites import ai_config, contracts, registry
from portfolio_suites.adapters.common import is_meaningful_git_fingerprint as adapter_predicate
from portfolio_suites.adapters import common
from portfolio_suites.paths import SUITES_ROOT
from portfolio_suites.provenance import is_meaningful_git_fingerprint


class ProvenanceTests(unittest.TestCase):
    def test_all_control_plane_modules_share_the_canonical_checkout_root(self):
        self.assertEqual(
            {registry.SUITES_ROOT, contracts.SUITES_ROOT, ai_config.SUITES_ROOT, common.SUITES_ROOT},
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


if __name__ == "__main__":
    unittest.main()
