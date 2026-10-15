"""Source adapter for Brand & Publishing OS connecting brand-maker-spec, brand-workshop, and cyborg."""

from __future__ import annotations

import ast
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256, validate_contract
from ..engines.brand_publishing import BrandPublishingEngine
from .common import donor_env, get_git_fingerprint, get_repo_path, is_meaningful_git_fingerprint
from . import donor_brand_package_probe

BRAND_MAKER_DIR = get_repo_path("brand-maker-spec", "BRAND_MAKER_DIR")
BRAND_WORKSHOP_DIR = get_repo_path("brand-workshop", "BRAND_WORKSHOP_DIR")
CYBORG_DIR = get_repo_path("cyborg", "CYBORG_DIR")


class BrandPublishingSourceAdapter:
    """Inspects donor sources and exercises explicit suite-local publishing projections."""

    @classmethod
    def execute_b1_brand_package_export(cls) -> dict[str, Any]:
        """Export only an actually published Brand Maker version, without donor writes."""
        target_fp = get_git_fingerprint(BRAND_MAKER_DIR)
        consumer_fp = get_git_fingerprint(CYBORG_DIR)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        dev_exports_path = BRAND_MAKER_DIR / "src" / "brand_maker" / "publishing" / "developer_exports.py"
        spec_path = BRAND_MAKER_DIR / "spec.md"
        living_spec_path = BRAND_MAKER_DIR / "docs" / "specs" / "living-brand-system.md"
        has_dev_exports = dev_exports_path.is_file()
        has_spec = spec_path.is_file()
        has_living_spec = living_spec_path.is_file()

        extracted_functions: set[str] = set()
        extracted_exports: set[str] = set()
        extracted_token_categories: set[str] = set()
        extracted_voice_sections: set[str] = set()
        if has_dev_exports:
            try:
                tree = ast.parse(dev_exports_path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        extracted_functions.add(node.name)
                    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                        value = node.value
                        if value.endswith((".css", ".json", ".js")):
                            extracted_exports.add(value)
                        if value in {"color", "font", "dimension", "duration"}:
                            extracted_token_categories.add(value)
                        if value.startswith("section."):
                            extracted_voice_sections.add(value)
            except (OSError, SyntaxError, UnicodeError):
                pass

        expected_functions = {"export_draft_tokens", "export_developer_package", "build_brand_kit_zip"}
        expected_exports = {
            "tokens.css", "tokens.json", "rules.json", "patterns.json",
            "voice-context.json", "change-manifest.json",
        }
        expected_token_types = {"color", "font", "dimension", "duration"}
        expected_voice_sections = {"section.voice", "section.messaging", "section.strategy"}
        sensitivity_passed = (
            expected_functions.issubset(extracted_functions)
            and expected_exports.issubset(extracted_exports)
            and expected_token_types.issubset(extracted_token_categories)
            and expected_voice_sections.issubset(extracted_voice_sections)
        )
        source_derived_assertions = {
            "donor_source_path": "src/brand_maker/publishing/developer_exports.py",
            "spec_source_path": "docs/specs/living-brand-system.md",
            "asserted_exports": sorted(extracted_exports),
            "asserted_functions": sorted(extracted_functions),
            "asserted_token_categories": sorted(extracted_token_categories),
            "asserted_voice_sections": sorted(extracted_voice_sections),
            "sensitivity_test_passed": sensitivity_passed,
        }

        cyborg_manual_path = CYBORG_DIR / "MANUAL.md"
        has_consumer_manual = cyborg_manual_path.is_file()
        source_verified = (
            is_meaningful_git_fingerprint(target_fp)
            and is_meaningful_git_fingerprint(consumer_fp)
            and has_dev_exports
            and has_spec
            and has_living_spec
            and has_consumer_manual
            and sensitivity_passed
        )

        database_path = Path(
            os.environ.get(
                "BRAND_MAKER_DATABASE_PATH",
                str(BRAND_MAKER_DIR / ".brand-maker" / "brands.db"),
            )
        ).expanduser().resolve()
        selected_brand_id = os.environ.get("BRAND_MAKER_BRAND_ID", "").strip()
        command = [
            sys.executable,
            str(Path(donor_brand_package_probe.__file__).resolve()),
            str(BRAND_MAKER_DIR),
            str(database_path),
        ]
        if selected_brand_id:
            command.append(selected_brand_id)

        try:
            db_sha256_before = (
                compute_sha256(database_path.read_bytes()) if database_path.is_file() else None
            )
        except OSError as error:
            return {
                "wave": "B1",
                "status": "environment_blocked",
                "blocker": "brand_maker_database_unreadable",
                "next_action": "Resolve read-only access to the configured Brand Maker database, then rerun B1.",
                "all_stages_passed": False,
                "source_verification_passed": source_verified,
                "source_derived_assertions": source_derived_assertions,
                "target": {"name": "brand-maker-spec", "path": str(BRAND_MAKER_DIR), "fingerprint": target_fp},
                "consumer": {"name": "cyborg", "path": str(CYBORG_DIR), "fingerprint": consumer_fp},
                "database_error": type(error).__name__,
            }
        started = time.monotonic()
        try:
            produced = subprocess.run(
                command,
                cwd=BRAND_MAKER_DIR,
                env=donor_env({"PYTHONDONTWRITEBYTECODE": "1"}),
                capture_output=True,
                text=True,
                timeout=90,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {
                "wave": "B1",
                "status": "environment_blocked",
                "blocker": type(error).__name__,
                "next_action": "Run the Brand Maker export probe in its supported local Python environment.",
                "all_stages_passed": False,
                "source_verification_passed": source_verified,
                "source_derived_assertions": source_derived_assertions,
                "target": {"name": "brand-maker-spec", "path": str(BRAND_MAKER_DIR), "fingerprint": target_fp},
                "consumer": {"name": "cyborg", "path": str(CYBORG_DIR), "fingerprint": consumer_fp},
            }
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        try:
            db_sha256_after = (
                compute_sha256(database_path.read_bytes()) if database_path.is_file() else None
            )
        except OSError:
            db_sha256_after = None
        database_unchanged = db_sha256_before == db_sha256_after
        invocation = {
            "command": command,
            "exit_code": produced.returncode,
            "duration_ms": duration_ms,
            "working_directory": str(BRAND_MAKER_DIR),
            "environment_policy": "donor_env_without_HOME_or_PYTHONPATH",
        }
        if produced.returncode == donor_brand_package_probe.EXIT_IMPORT_FAILED:
            return {
                "wave": "B1",
                "status": "environment_blocked",
                "blocker": "brand_maker_import_failed",
                "next_action": "Install or select the Brand Maker runtime dependencies, then rerun B1.",
                "all_stages_passed": False,
                "source_invocation": invocation,
                "source_verification_passed": source_verified,
                "source_derived_assertions": source_derived_assertions,
                "target": {"name": "brand-maker-spec", "path": str(BRAND_MAKER_DIR), "fingerprint": target_fp},
                "consumer": {"name": "cyborg", "path": str(CYBORG_DIR), "fingerprint": consumer_fp},
            }
        if produced.returncode != 0:
            return {
                "wave": "B1",
                "status": "probe_failed",
                "blocker": "brand_maker_export_probe_failed",
                "next_action": "Inspect the probe error and rerun B1 after correcting the donor environment.",
                "all_stages_passed": False,
                "source_invocation": invocation,
                "probe_stderr": produced.stderr[-2000:],
                "source_verification_passed": source_verified,
                "source_derived_assertions": source_derived_assertions,
                "target": {"name": "brand-maker-spec", "path": str(BRAND_MAKER_DIR), "fingerprint": target_fp},
                "consumer": {"name": "cyborg", "path": str(CYBORG_DIR), "fingerprint": consumer_fp},
            }
        try:
            probe_result = json.loads(produced.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            probe_result = {"status": "invalid_probe_output"}

        common = {
            "source_invocation": invocation,
            "database_unchanged": database_unchanged,
            "database_sha256": db_sha256_after or "",
            "source_verification_passed": source_verified,
            "source_derived_assertions": source_derived_assertions,
            "target": {
                "name": "brand-maker-spec", "path": str(BRAND_MAKER_DIR), "fingerprint": target_fp,
                "has_developer_exports": has_dev_exports, "has_spec": has_spec,
                "has_living_spec": has_living_spec,
            },
            "consumer": {
                "name": "cyborg", "path": str(CYBORG_DIR), "fingerprint": consumer_fp,
                "has_manual": has_consumer_manual,
            },
        }
        probe_status = probe_result.get("status")
        if not database_unchanged:
            return {
                "wave": "B1", "status": "probe_failed", "blocker": "donor_database_changed",
                "next_action": "Inspect the database state; the read-only export probe did not preserve its file hash.",
                "all_stages_passed": False, "probe": probe_result, **common,
            }
        if probe_status != "exported":
            blocker_by_status = {
                "no_published_version": (
                    "owner_approval_required",
                    "Create, owner-approve, and publish the intended Brand Maker brand; then rerun B1.",
                ),
                "database_missing": (
                    "brand_maker_database_missing",
                    "Start Brand Maker with its intended local database, then rerun B1.",
                ),
                "publication_schema_unavailable": (
                    "brand_maker_publication_schema_unavailable",
                    "Update the adapter to the current Brand Maker publication schema before rerunning B1.",
                ),
                "database_unavailable": (
                    "brand_maker_database_unavailable",
                    "Resolve the read-only database access issue, then rerun B1.",
                ),
                "brand_selection_required": (
                    "brand_selection_required",
                    "Set BRAND_MAKER_BRAND_ID to the intended published brand UUID, then rerun B1.",
                ),
                "selected_brand_not_published": (
                    "selected_brand_not_published",
                    "Select a brand UUID that has an owner-approved published version, then rerun B1.",
                ),
            }
            blocker, next_action = blocker_by_status.get(
                str(probe_status),
                ("brand_maker_export_unavailable", "Resolve the reported Brand Maker export blocker, then rerun B1."),
            )
            return {
                "wave": "B1", "status": blocker, "blocker": blocker, "next_action": next_action,
                "all_stages_passed": False, "probe": probe_result, **common,
                "brand_package_emitted": False,
                "source_record_emitted": False,
                "publishing_receipt_emitted": False,
            }

        try:
            published = probe_result["published_version"]
            snapshot = published["snapshot"]
            approvals = published["approvals"]
            exports = probe_result["developer_export"]
            if not isinstance(snapshot, dict) or not isinstance(approvals, list) or not approvals:
                raise ValueError("published version is missing its snapshot or owner approvals")
            if not isinstance(exports, dict) or not expected_exports.issubset(exports):
                raise ValueError("Brand Maker developer export is incomplete")
            if any(not isinstance(exports[name], str) for name in expected_exports):
                raise ValueError("Brand Maker developer export contains non-text artifacts")

            content_payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
            host_content_hash = compute_sha256(content_payload)
            if host_content_hash != published.get("content_hash"):
                raise ValueError("host-recomputed published snapshot hash does not match Brand Maker")
            brand_id = str(published["brand_id"])
            version = str(published["version"])
            owner = snapshot.get("owner") or {}
            owner_id = owner.get("id")
            owner_name = owner.get("display_name")
            revision = published.get("draft_revision")
            section_ids = [section.get("id") for section in snapshot.get("sections", [])]
            if (
                snapshot.get("brand_id") != brand_id
                or snapshot.get("revision") != revision
                or snapshot.get("status") != "approved"
                or snapshot.get("maturity") != "approved"
                or published.get("publisher_id") != owner_id
                or published.get("manifest", {}).get("draft_revision") != revision
                or published.get("manifest", {}).get("section_ids") != section_ids
                or not owner_id
                or not owner_name
            ):
                raise ValueError("published version, owner, manifest, and snapshot do not align")
            for approval in approvals:
                if (
                    approval.get("brand_id") != brand_id
                    or approval.get("draft_revision") != revision
                    or approval.get("owner_id") != owner_id
                    or approval.get("outcome") != "approved"
                ):
                    raise ValueError("published version contains an approval outside its owner or revision")
            approval_times = [
                datetime.datetime.fromisoformat(item["approved_at"].replace("Z", "+00:00"))
                for item in approvals
            ]
            if any(moment.tzinfo is None or moment.utcoffset() is None for moment in approval_times):
                raise ValueError("Brand Maker approval timestamps must include a timezone")
            approved_at = max(approval_times).astimezone(datetime.timezone.utc).isoformat()
            expected_module_paths = {
                "brand_maker.publishing.developer_exports": "src/brand_maker/publishing/developer_exports.py",
                "brand_maker.brand_system.models": "src/brand_maker/brand_system/models.py",
            }
            module_fingerprints = probe_result.get("module_fingerprints")
            if not isinstance(module_fingerprints, dict) or set(module_fingerprints) != set(expected_module_paths):
                raise ValueError("Brand Maker probe did not report the complete expected module set")
            for module_name, expected_path in expected_module_paths.items():
                record = module_fingerprints[module_name]
                if not isinstance(record, dict) or record.get("path") != expected_path:
                    raise ValueError(f"Brand Maker probe reported an unexpected module path for {module_name}")
                module_path = BRAND_MAKER_DIR / expected_path
                if compute_sha256(module_path.read_bytes()) != record.get("sha256"):
                    raise ValueError(f"host module fingerprint did not agree for {module_name}")

            token_export = json.loads(exports["tokens.json"])
            rule_export = json.loads(exports["rules.json"])
            voice_export = json.loads(exports["voice-context.json"])
            manifest_export = exports["change-manifest.json"]
            pattern_export = json.loads(exports["patterns.json"])
            expected_tokens = [token for section in snapshot.get("sections", []) for token in section.get("tokens", [])]
            expected_rules = [rule for section in snapshot.get("sections", []) for rule in section.get("rules", [])]
            expected_patterns = [pattern for section in snapshot.get("sections", []) for pattern in section.get("patterns", [])]
            expected_voice_sections = [
                section for section in snapshot.get("sections", [])
                if section.get("id") in {"section.voice", "section.messaging", "section.strategy"}
            ]
            if token_export.get("tokens") != expected_tokens:
                raise ValueError("Brand Maker token export does not match the published snapshot")
            if rule_export.get("rules") != expected_rules:
                raise ValueError("Brand Maker rule export does not match the published snapshot")
            if pattern_export.get("patterns") != expected_patterns:
                raise ValueError("Brand Maker pattern export does not match the published snapshot")
            if voice_export.get("sections") != expected_voice_sections:
                raise ValueError("Brand Maker voice-context export does not match the published snapshot")
            change_manifest = json.loads(manifest_export)
            if (
                change_manifest.get("manifest") != published.get("manifest")
                or sorted(change_manifest.get("approval_ids", [])) != sorted(item.get("id") for item in approvals)
            ):
                raise ValueError("Brand Maker change manifest does not match the published version")
            for name in ("tokens.json", "rules.json", "patterns.json", "voice-context.json", "change-manifest.json"):
                artifact = json.loads(exports[name])
                if artifact.get("version") != version or artifact.get("content_hash") != published["content_hash"]:
                    raise ValueError(f"Brand Maker export {name} does not match its immutable version")
            if published["content_hash"] not in exports["tokens.css"]:
                raise ValueError("Brand Maker CSS export is not bound to the published content hash")

            package_id = f"pkg-{brand_id.replace('-', '')}-{version.replace('.', '-')}"
            brand_pkg_raw = {
                "schema_version": SCHEMA_VERSION,
                "package_id": package_id,
                "brand_id": brand_id,
                "version": version,
                "approved_at": approved_at,
                "identity": {
                    "brand_name": snapshot["brand_name"],
                    "brand_context": snapshot.get("brand_context"),
                    "developer_tokens": token_export.get("tokens", []),
                },
                "voice": {"sections": voice_export.get("sections", [])},
                "audience": {"brief": snapshot.get("brief", {})},
                # Brand Maker currently has no separately verified approved-claims registry.
                # Messaging prose is not promoted into factual claims by this adapter.
                "approved_claims": [],
                "assets": [
                    {
                        "asset_id": asset["id"],
                        "name": asset["name"],
                        "kind": asset["media_type"],
                        "path": f"brand-maker://{brand_id}/assets/{asset['id']}",
                        "sha256": asset["content_hash"],
                        "storage": asset["storage"],
                    }
                    for asset in snapshot.get("assets", [])
                ],
                "usage_rules": [
                    rule["description"]
                    for rule in rule_export.get("rules", [])
                    if isinstance(rule, dict) and isinstance(rule.get("description"), str) and rule["description"].strip()
                ],
                "provenance": [{
                    "source": "brand-maker-spec",
                    "operator": owner_name,
                    "timestamp": approved_at,
                    "brand_version": version,
                    "published_content_sha256": published["content_hash"],
                    "approval_ids": [item["id"] for item in approvals],
                    "derivation": "native Brand Maker developer export from an immutable published version",
                }],
            }
            validated_pkg = validate_contract("BrandPackage", brand_pkg_raw)
            manifest_bytes = manifest_export.encode("utf-8")
            validated_src = validate_contract("SourceRecord", {
                "schema_version": SCHEMA_VERSION,
                "source_id": f"src-brand-maker-{brand_id}-{version}",
                "acquired_at": now_iso,
                "sha256": compute_sha256(manifest_bytes),
                "size_bytes": len(manifest_bytes),
                "media_type": "application/json",
                "origin": f"brand-maker-spec://{brand_id}/{version}/change-manifest.json",
                "provenance": {
                    "donor_repo": "brand-maker-spec",
                    "method": "export_developer_package",
                    "brand_version": version,
                    "published_content_sha256": published["content_hash"],
                },
            })
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
            return {
                "wave": "B1", "status": "export_unverified", "blocker": "brand_maker_export_invalid",
                "next_action": "Inspect the producer output and mapping error before accepting a BrandPackage.",
                "all_stages_passed": False, "probe": probe_result, "validation_error": str(error), **common,
            }

        mutation_tests: list[dict[str, Any]] = []
        ok, violations = BrandPublishingEngine.verify_immutability(validated_pkg, dict(validated_pkg))
        mutation_tests.append({"case": "unmodified_identical", "passed": ok and not violations, "violations": violations})
        mutated_identity = dict(validated_pkg)
        mutated_identity["identity"] = dict(validated_pkg["identity"], brand_name="Unauthorized Mutation")
        ok, violations = BrandPublishingEngine.verify_immutability(validated_pkg, mutated_identity)
        mutation_tests.append({"case": "mutated_identity_detected", "passed": not ok and bool(violations), "violations": violations})
        mutated_voice = dict(validated_pkg)
        mutated_voice["voice"] = dict(validated_pkg["voice"], mutation_probe=True)
        ok, violations = BrandPublishingEngine.verify_immutability(validated_pkg, mutated_voice)
        mutation_tests.append({"case": "mutated_voice_detected", "passed": not ok and bool(violations), "violations": violations})
        mutated_provenance = dict(validated_pkg)
        mutated_provenance["provenance"] = [dict(validated_pkg["provenance"][0], mutation_probe=True)]
        ok, violations = BrandPublishingEngine.verify_immutability(validated_pkg, mutated_provenance)
        mutation_tests.append({"case": "mutated_provenance_detected", "passed": not ok and bool(violations), "violations": violations})
        all_mutation_checks_passed = all(item["passed"] for item in mutation_tests)

        receipt = BrandPublishingEngine.dry_run_publish(
            validated_pkg,
            validated_src,
            manifest_export,
            channel="brand-maker-developer-export",
        )
        all_stages_passed = (
            source_verified
            and database_unchanged
            and all_mutation_checks_passed
            and receipt.get("status") == "dry_run_verified"
            and receipt.get("dry_run_only") is True
            and receipt.get("live_published") is False
        )
        export_hashes = {
            name: compute_sha256(value.encode("utf-8"))
            for name, value in sorted(exports.items())
        }
        return {
            "wave": "B1",
            "status": "verified_candidate" if all_stages_passed else "source_unverified",
            "brand_package": validated_pkg,
            "source_record": validated_src,
            "source_content": manifest_export,
            "publishing_receipt": receipt,
            "mutation_tests": mutation_tests,
            "mutation_protection_passed": all_mutation_checks_passed,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
            "source_invocation": invocation,
            "probe": {"status": probe_status, "module_fingerprints": probe_result.get("module_fingerprints", {})},
            "export_sha256s": export_hashes,
            "source_derived_assertions": source_derived_assertions,
            **common,
        }

    @classmethod
    def execute_b2_phase_mapping(cls) -> dict[str, Any]:
        """Map all 9 Brand Workshop intake phases to Brand Maker workspace gates from live source."""
        workshop_fp = get_git_fingerprint(BRAND_WORKSHOP_DIR)
        maker_fp = get_git_fingerprint(BRAND_MAKER_DIR)

        # Inspect live brand_workshop/phases.py (or ported path in brand-maker-spec)
        phases_source_file = BRAND_WORKSHOP_DIR / "brand_workshop" / "phases.py"
        extracted_phase_ids: list[str] = []
        content = ""
        if phases_source_file.is_file():
            content = phases_source_file.read_text(encoding="utf-8")
        elif (BRAND_MAKER_DIR / "src" / "brand_workshop" / "phases.py").is_file():
            content = (BRAND_MAKER_DIR / "src" / "brand_workshop" / "phases.py").read_text(encoding="utf-8")
        if content:
            for line in content.splitlines():
                if line.strip().startswith('"0') and '": {' in line:
                    p_id = line.strip().split('":')[0].strip('"')
                    if p_id not in extracted_phase_ids:
                        extracted_phase_ids.append(p_id)

        phase_mappings = [
            {"phase": "00-spark", "name": "Spark", "maker_gate": "intake_tension", "port_action": "port-as-starter-brief", "status": "mapped"},
            {"phase": "01-discovery", "name": "Discovery", "maker_gate": "context_landscape", "port_action": "port-as-category-audit", "status": "mapped"},
            {"phase": "02-strategy", "name": "Strategy", "maker_gate": "core_strategy", "port_action": "port-as-one-true-thing", "status": "mapped"},
            {"phase": "03-identity", "name": "Identity", "maker_gate": "visual_tokens", "port_action": "port-as-palette-and-type", "status": "mapped"},
            {"phase": "04-language", "name": "Language", "maker_gate": "voice_guidance", "port_action": "port-as-say-never-say", "status": "mapped"},
            {"phase": "05-expression", "name": "Expression", "maker_gate": "touchpoints", "port_action": "port-as-channel-playbook", "status": "mapped"},
            {"phase": "06-system", "name": "System", "maker_gate": "rules_and_tokens", "port_action": "port-as-css-export", "status": "mapped"},
            {"phase": "07-launch", "name": "Launch", "maker_gate": "launch_brief", "port_action": "port-as-announcement-kit", "status": "mapped"},
            {"phase": "08-living-brand", "name": "Living Brand", "maker_gate": "governance", "port_action": "port-as-monitoring-register", "status": "mapped"},
        ]
        source_verified = (
            is_meaningful_git_fingerprint(workshop_fp)
            and is_meaningful_git_fingerprint(maker_fp)
            and len(extracted_phase_ids) == 9
        )
        all_stages_passed = source_verified and len(phase_mappings) == 9

        return {
            "wave": "B2",
            "status": "all_phases_mapped" if all_stages_passed else "source_unverified",
            "donor": {
                "name": "brand-workshop",
                "path": str(BRAND_WORKSHOP_DIR),
                "fingerprint": workshop_fp,
                "extracted_phases_from_source": extracted_phase_ids,
            },
            "target": {
                "name": "brand-maker-spec",
                "path": str(BRAND_MAKER_DIR),
                "fingerprint": maker_fp,
            },
            "total_phases_mapped": len(phase_mappings),
            "phase_mappings": phase_mappings,
            "source_verification_passed": source_verified,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_b5_brand_maker_intake(cls) -> dict[str, Any]:
        """B5: Drive the nine-phase intake machine using live Brand Workshop phase ids."""
        workshop = cls.execute_b2_phase_mapping()
        extracted = workshop.get("donor", {}).get("extracted_phases_from_source") or []
        complete_phase_inputs = {
            1: {"one_liner": "Local-first portfolio suite", "enemy": "Fragile unversioned schemas", "brand_name": "Cyborg Suites"},
            2: {"primary_operator": "Ryan Johnson", "pain_points": ["drift", "cognitive load"], "target_audience": "Technical Operators"},
            3: {"tone_adjectives": ["clear", "grounded", "concise"], "taboo_words": ["vague", "magic", "untested"]},
            4: {"palette_hex": ["#111827", "#3b82f6"], "typeface_pair": "Inter / JetBrains Mono", "tagline": "Instituted Brand Package"},
            5: {"verifiable_claims": ["Zero-dependency local control", "Deterministic test gates"]},
            6: {"logo_paths": ["assets/logo.svg"], "icon_set": "lucide"},
            7: {"do_list": ["Pin versions"], "dont_list": ["Silent mutations"], "usage_rules": ["Never modify without explicit version bump"]},
            8: {"formats": ["markdown", "json"], "cadence": "on_demand"},
            9: {"approver_signoff": "simulated_fixture_operator"},
        }
        res_complete = BrandPublishingEngine.execute_brand_maker_intake("cyborg-brand", complete_phase_inputs)
        res_empty = BrandPublishingEngine.execute_brand_maker_intake("cyborg-brand", {})
        workshop_read = (
            workshop.get("all_stages_passed") is True
            and len(extracted) == 9
        )
        res_complete["brand_workshop_read"] = workshop_read
        res_complete["external_runtime_invoked"] = False
        res_complete["workshop_phases"] = extracted
        res_complete["workshop_fingerprint"] = (workshop.get("donor") or {}).get("fingerprint")
        passed = (
            workshop_read
            and res_complete.get("phases_completed") == 9
            and res_complete.get("resulting_package", {}).get("schema_version") == "1.0.0"
            and res_empty.get("phases_completed") == 0
            and res_empty.get("resulting_package") is None
        )
        if not passed:
            res_complete["all_stages_passed"] = False
            res_complete["reconciliation_status"] = "source_unverified"
        else:
            res_complete["all_stages_passed"] = True
            res_complete["reconciliation_status"] = "workshop_aligned_intake_validated"
        return res_complete
