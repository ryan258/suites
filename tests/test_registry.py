import unittest
import json
from pathlib import Path

from portfolio_suites.registry import load_ledger, load_suites, validate_registry


class RegistryTests(unittest.TestCase):
    def test_eight_suite_boundaries_exist(self):
        self.assertEqual(len(load_suites()), 8)

    def test_every_snapshot_directory_has_a_disposition(self):
        rows = load_ledger()["projects"]
        self.assertEqual(len(rows), 70)
        self.assertTrue(all(row["disposition"] and row["migration"] for row in rows))

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


if __name__ == "__main__":
    unittest.main()
