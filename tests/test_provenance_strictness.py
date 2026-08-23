import unittest

from portfolio_suites.provenance import is_meaningful_git_fingerprint, is_sensitive_path


def valid_fingerprint():
    return {
        "branch": "main",
        "head": "a" * 40,
        "tested_files_fingerprint": {"src/main.py": "b" * 64},
    }


class ProvenanceStrictnessTests(unittest.TestCase):
    def test_revision_must_be_a_full_git_object_id(self):
        for head in ("x", "a" * 7, "A" * 40, "unavailable"):
            with self.subTest(head=head):
                self.assertFalse(is_meaningful_git_fingerprint({**valid_fingerprint(), "head": head}))

    def test_placeholders_are_rejected_case_insensitively(self):
        for branch in ("Unavailable", "NONE", "n/a", "missing"):
            with self.subTest(branch=branch):
                self.assertFalse(is_meaningful_git_fingerprint({**valid_fingerprint(), "branch": branch}))

    def test_tested_files_are_safe_relative_paths_with_sha256_values(self):
        for mapping in (
            {"../secret": "b" * 64},
            {"/etc/passwd": "b" * 64},
            {".env": "b" * 64},
            {"README.md": "short"},
        ):
            with self.subTest(mapping=mapping):
                self.assertFalse(
                    is_meaningful_git_fingerprint(
                        {**valid_fingerprint(), "tested_files_fingerprint": mapping}
                    )
                )

    def test_invalid_path_input_fails_closed_as_sensitive(self):
        self.assertTrue(is_sensitive_path(None))
        self.assertTrue(is_sensitive_path(42))
        for path in (".git-credentials", ".npmrc", ".aws/credentials", ".docker/config.json"):
            self.assertTrue(is_sensitive_path(path))


if __name__ == "__main__":
    unittest.main()
