import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import portfolio_suites.contracts as contracts_module
from portfolio_suites.contracts import (
    CONTRACTS,
    ContractError,
    compute_sha256,
    generate_sample,
    validate_contract,
    validate_json_str,
)

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"


class ContractTests(unittest.TestCase):
    def test_all_contract_samples_are_valid(self):
        for contract_name in CONTRACTS:
            sample = generate_sample(contract_name)
            validated = validate_contract(contract_name, sample)
            self.assertIsInstance(validated, dict)
            self.assertEqual(validated["schema_version"], "1.0.0")

    def test_deterministic_a11y_finding_requires_evidence(self):
        finding = {
            "schema_version": "1.0.0",
            "finding_id": "finding-example-1",
            "rule_id": "html-has-lang",
            "severity": "serious",
            "summary": "Document language is missing",
            "target": "html",
            "evidence": [],
            "evidence_kind": "deterministic",
            "needs_review": False,
            "status": "open",
        }
        with self.assertRaisesRegex(ContractError, "requires evidence"):
            validate_contract("A11yFinding", finding)

    def test_ai_a11y_finding_cannot_skip_review(self):
        finding = {
            "schema_version": "1.0.0",
            "finding_id": "finding-example-2",
            "rule_id": "alt-quality",
            "severity": "moderate",
            "summary": "Alt text may not convey purpose",
            "target": "img.hero",
            "evidence": [{"observation": "Generic wording"}],
            "evidence_kind": "ai-assisted",
            "needs_review": False,
            "status": "open",
        }
        with self.assertRaisesRegex(ContractError, "must remain needs_review"):
            validate_contract("A11yFinding", finding)

    def test_source_record_accepts_content_addressed_evidence(self):
        record = {
            "schema_version": "1.0.0",
            "source_id": "source-example-1",
            "acquired_at": "2026-08-19T12:00:00-05:00",
            "sha256": "a" * 64,
            "size_bytes": 42,
            "media_type": "text/markdown",
            "origin": "/tmp/example.md",
            "provenance": {"method": "copy", "actor": "human"},
        }
        self.assertEqual(validate_contract("SourceRecord", record), record)

    def test_brand_package_requires_semver_and_provenance(self):
        package = {
            "schema_version": "1.0.0",
            "package_id": "brand-package-fieldwell-1",
            "brand_id": "fieldwell",
            "version": "v1",
            "approved_at": "2026-08-19T12:00:00-05:00",
            "identity": {}, "voice": {}, "audience": {},
            "approved_claims": [], "assets": [], "usage_rules": [], "provenance": [],
        }
        with self.assertRaisesRegex(ContractError, "semantic"):
            validate_contract("BrandPackage", package)

    def test_production_job_enums_and_validation(self):
        job = generate_sample("ProductionJob")
        self.assertEqual(job["status"], "completed")
        job["status"] = "invalid-status"
        with self.assertRaisesRegex(ContractError, "must be one of"):
            validate_contract("ProductionJob", job)

    def test_experiment_run_requires_benchmark_and_scorer_version(self):
        run = generate_sample("ExperimentRun")
        self.assertTrue(run["benchmark_version"])
        run["benchmark_version"] = ""
        with self.assertRaisesRegex(ContractError, "benchmark_version is required"):
            validate_contract("ExperimentRun", run)

    def test_investigation_record_mode_enums(self):
        inv = generate_sample("InvestigationRecord")
        self.assertEqual(inv["mode"], "standard")
        inv["mode"] = "invalid-mode"
        with self.assertRaisesRegex(ContractError, "must be one of"):
            validate_contract("InvestigationRecord", inv)

    def test_unhashable_enum_values_raise_contract_errors(self):
        for contract_name, spec in CONTRACTS.items():
            for field in spec.enums or {}:
                sample = generate_sample(contract_name)
                for invalid_value in ([], {}):
                    with self.subTest(
                        contract=contract_name,
                        field=field,
                        invalid_type=type(invalid_value).__name__,
                    ):
                        with self.assertRaisesRegex(ContractError, "must be one of"):
                            validate_contract(
                                contract_name,
                                {**sample, field: invalid_value},
                            )

    def test_compute_sha256(self):
        digest = compute_sha256("test-content")
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, compute_sha256("test-content"))

    def test_validate_json_str(self):
        sample = generate_sample("SourceRecord")
        import json
        raw = json.dumps(sample)
        validated = validate_json_str("SourceRecord", raw)
        self.assertEqual(validated["source_id"], sample["source_id"])


    def test_json_schemas_match_contracts_py(self):
        # ponytail: contracts/*.schema.json duplicate CONTRACTS for dependency-free external
        # consumers (see contracts/README.md); this guards against the two drifting apart.
        schema_files = sorted(CONTRACTS_DIR.glob("*.schema.json"))
        self.assertTrue(schema_files, "expected at least one contracts/*.schema.json file")
        found_titles = set()
        for schema_file in schema_files:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            name = schema["title"]
            found_titles.add(name)
            spec = CONTRACTS[name]
            self.assertEqual(set(schema["required"]), set(spec.required), name)
            for field, enum_values in (spec.enums or {}).items():
                self.assertEqual(
                    set(schema["properties"][field]["enum"]), set(enum_values), f"{name}.{field}"
                )
        self.assertEqual(found_titles, set(CONTRACTS), "schema files do not cover all CONTRACTS")

    def test_validator_rejects_types_the_published_schema_forbids(self):
        """The Python validator and the advertised JSON Schema must not disagree on field types."""
        base = {
            "schema_version": "1.0.0",
            "source_id": "src-001",
            "origin": "https://example.test/a",
            "acquired_at": "2026-08-20T00:00:00+00:00",
            "media_type": "text/html",
            "license": "cc-by-4.0",
            "provenance": {},
            "provenance_chain": [],
            "sha256": "a" * 64,
            "size_bytes": 1,
        }
        validate_contract("SourceRecord", base)
        for field, bad_value in (("acquired_at", 123), ("media_type", 456), ("origin", ["a"])):
            with self.assertRaises(ContractError, msg=f"{field} type gap"):
                validate_contract("SourceRecord", {**base, field: bad_value})

    def test_validator_rejects_a_malformed_timestamp(self):
        sample = generate_sample("InvestigationRecord")
        with self.assertRaises(ContractError):
            validate_contract("InvestigationRecord", {**sample, "created_at": "not-a-timestamp"})

    def test_validator_fails_closed_when_published_schemas_are_missing(self):
        sample = generate_sample("SourceRecord")
        with tempfile.TemporaryDirectory() as tmp:
            contracts_module._published_schemas.cache_clear()
            with patch.object(contracts_module, "SCHEMA_DIR", Path(tmp)):
                with self.assertRaisesRegex(ContractError, "published contract schemas are missing"):
                    validate_contract("SourceRecord", sample)
        contracts_module._published_schemas.cache_clear()


if __name__ == "__main__":
    unittest.main()
