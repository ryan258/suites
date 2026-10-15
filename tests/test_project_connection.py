"""Read-only tests for the optional project-root ``.suites`` descriptor."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from portfolio_suites import catalog
from portfolio_suites.project_connection import (
    MAX_CONNECTION_BYTES,
    ProjectConnectionError,
    read_project_connection,
    validate_project_connection,
)


class ProjectConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write(self, value):
        (self.root / ".suites").write_text(json.dumps(value), encoding="utf-8")

    def test_absent_file_is_not_connected(self):
        self.assertEqual(read_project_connection(self.root)["state"], "not_connected")

    def test_valid_file_exposes_only_identity_and_declarations(self):
        self.write({
            "schema_version": "1.0.0",
            "project_id": "example-project",
            "capabilities": ["resume.read.v1", "evidence.read-v1"],
            "future_field": {"ignored": True},
        })
        result = read_project_connection(self.root)
        self.assertEqual(result["state"], "declared")
        self.assertEqual(result["project_id"], "example-project")
        self.assertEqual(result["schema_version"], "1.0.0")
        self.assertEqual(result["declared_capabilities"], ["resume.read.v1", "evidence.read-v1"])
        self.assertFalse(result["runtime_verified"])
        self.assertEqual(result["errors"], [])

    def test_invalid_descriptors_fail_closed(self):
        for payload in (
            [],
            {"schema_version": "2.0.0", "project_id": "example", "capabilities": []},
            {"schema_version": "1.0.0", "project_id": "../outside", "capabilities": []},
            {"schema_version": "1.0.0", "project_id": "example", "capabilities": ["Run arbitrary command"]},
            {"schema_version": "1.0.0", "project_id": "example", "capabilities": ["x" * 97]},
            {"schema_version": "1.0.0", "project_id": "example", "capabilities": ["resume.v1", "resume.v1"]},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ProjectConnectionError):
                    validate_project_connection(payload)

    def test_duplicate_json_keys_are_refused(self):
        (self.root / ".suites").write_text(
            '{"schema_version":"1.0.0","project_id":"first","project_id":"second","capabilities":[]}',
            encoding="utf-8",
        )
        result = read_project_connection(self.root)
        self.assertEqual(result["state"], "invalid")

    def test_oversized_and_symlink_files_are_refused(self):
        manifest = self.root / ".suites"
        manifest.write_bytes(b" " * (MAX_CONNECTION_BYTES + 1))
        self.assertEqual(read_project_connection(self.root)["state"], "invalid")
        manifest.unlink()
        outside = self.root.parent / (self.root.name + "-outside")
        outside.write_text('{"schema_version":"1.0.0","project_id":"example","capabilities":[]}', encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        manifest.symlink_to(outside)
        self.assertEqual(read_project_connection(self.root)["state"], "invalid")

    def test_non_regular_manifest_is_refused_without_reading(self):
        manifest = self.root / ".suites"
        os.mkfifo(manifest)
        self.assertEqual(read_project_connection(self.root)["state"], "invalid")

    def test_project_root_symlink_is_unavailable(self):
        linked_root = self.root.parent / (self.root.name + "-link")
        linked_root.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(lambda: linked_root.unlink(missing_ok=True))
        self.assertEqual(read_project_connection(linked_root)["state"], "unavailable")

    def test_non_absolute_project_location_is_unavailable(self):
        self.assertEqual(read_project_connection("relative/project")["state"], "unavailable")

    def test_project_view_includes_the_opt_in_descriptor(self):
        row = {
            "name": "example-project",
            "disposition": "catalog-only",
            "operator": {
                "id": "example-project",
                "location": str(self.root),
                "primary_home": "independent",
                "attention": None,
                "resume": None,
            },
        }
        self.write({
            "schema_version": "1.0.0",
            "project_id": "example-project",
            "capabilities": ["catalog.identity.v1"],
        })
        view = catalog.project_view(row)
        self.assertEqual(view["project_connection"]["state"], "declared")
        self.assertEqual(view["project_connection"]["project_id"], "example-project")
        self.assertFalse(view["project_connection"]["runtime_verified"])


if __name__ == "__main__":
    unittest.main()
