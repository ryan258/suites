"""Explicit local registration of independent ``.suites`` projects."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from portfolio_suites import registry
from portfolio_suites.cli import main
from portfolio_suites.project_registration import connect_project
from portfolio_suites.catalog import CatalogError


class ProjectRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.control_plane = self.root / "control-plane"
        (self.control_plane / "portfolio").mkdir(parents=True)
        source_ledger = Path(registry.SUITES_ROOT) / "portfolio" / "project-ledger.json"
        self.ledger = self.control_plane / "portfolio" / "project-ledger.json"
        shutil.copyfile(source_ledger, self.ledger)
        self.initial_catalog_additions = len(
            json.loads(self.ledger.read_text(encoding="utf-8"))["catalog_additions"]
        )
        self.suites_root_patch = patch.object(registry, "SUITES_ROOT", self.control_plane)
        self.suites_root_patch.start()
        self.addCleanup(self.suites_root_patch.stop)

    def make_project(self, name="example-project", capabilities=None):
        project = self.projects / name
        project.mkdir()
        descriptor = {
            "schema_version": "1.0.0",
            "project_id": name,
            "capabilities": capabilities or [],
        }
        manifest = project / ".suites"
        manifest.write_text(json.dumps(descriptor), encoding="utf-8")
        return project, manifest

    def test_connect_registers_declarations_without_enrollment_or_donor_writes(self):
        project, manifest = self.make_project(capabilities=["resume.read.v1", "notes.search.v1"])
        original_descriptor = manifest.read_bytes()
        original_digest = hashlib.sha256(original_descriptor).hexdigest()

        view = connect_project(project)

        self.assertEqual(view["id"], "example-project")
        self.assertEqual(view["project_connection"]["state"], "declared")
        self.assertEqual(
            view["project_connection"]["declared_capabilities"],
            ["resume.read.v1", "notes.search.v1"],
        )
        self.assertFalse(view["project_connection"]["runtime_verified"])
        self.assertFalse(view["migration"]["enrolled"])
        self.assertEqual(manifest.read_bytes(), original_descriptor)

        ledger = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["catalog_additions"]), self.initial_catalog_additions + 1)
        row = next(row for row in ledger["catalog_additions"] if row["name"] == "example-project")
        self.assertIsNone(row["primary_suite"])
        self.assertEqual(row["disposition"], "catalog-only")
        provenance = row["operator"]["provenance"][0]
        self.assertEqual(provenance["source"], str(manifest))
        self.assertEqual(provenance["sha256"], original_digest)

    def test_connect_is_idempotent_and_leaves_ledger_bytes_unchanged_on_repeat(self):
        project, _manifest = self.make_project()

        first = connect_project(project)
        saved_ledger = self.ledger.read_bytes()
        second = connect_project(project)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.ledger.read_bytes(), saved_ledger)

    def test_duplicate_id_at_another_location_is_refused_without_mutation(self):
        first, _ = self.make_project("shared-id")
        second, _ = self.make_project("second-directory")
        (second / ".suites").write_text(
            json.dumps({"schema_version": "1.0.0", "project_id": "shared-id", "capabilities": []}),
            encoding="utf-8",
        )
        connect_project(first)
        saved_ledger = self.ledger.read_bytes()

        with self.assertRaisesRegex(CatalogError, "already connected at another location"):
            connect_project(second)

        self.assertEqual(self.ledger.read_bytes(), saved_ledger)

    def test_changed_identity_at_an_already_registered_location_is_refused(self):
        project, manifest = self.make_project("first-id")
        connect_project(project)
        saved_ledger = self.ledger.read_bytes()
        manifest.write_text(
            json.dumps({"schema_version": "1.0.0", "project_id": "second-id", "capabilities": []}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(CatalogError, "already registered as first-id"):
            connect_project(project)

        self.assertEqual(self.ledger.read_bytes(), saved_ledger)

    def test_invalid_descriptor_and_relative_path_are_refused(self):
        project, manifest = self.make_project()
        manifest.write_text("{}", encoding="utf-8")
        before = self.ledger.read_bytes()

        with self.assertRaisesRegex(CatalogError, "valid .suites descriptor"):
            connect_project(project)
        with self.assertRaisesRegex(CatalogError, "absolute path"):
            connect_project("relative/project")

        self.assertEqual(self.ledger.read_bytes(), before)

    def test_cli_json_connects_and_reports_catalog_only_declaration(self):
        project, _ = self.make_project(capabilities=["resume.read.v1"])
        output = io.StringIO()

        with redirect_stdout(output):
            code = main(["connect", str(project), "--json"])

        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["id"], "example-project")
        self.assertEqual(result["project_connection"]["declared_capabilities"], ["resume.read.v1"])
        self.assertFalse(result["migration"]["enrolled"])

    def test_cli_json_refuses_invalid_descriptor(self):
        project, manifest = self.make_project()
        manifest.write_text("not json", encoding="utf-8")
        before = self.ledger.read_bytes()
        output = io.StringIO()

        with redirect_stdout(output):
            code = main(["connect", str(project), "--json"])

        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "refused")
        self.assertIn("valid .suites descriptor", result["message"])
        self.assertEqual(self.ledger.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
