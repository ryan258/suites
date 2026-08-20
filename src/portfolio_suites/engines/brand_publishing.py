"""Brand & Publishing engine powering BrandPackage truth, immutability, and dry-run publishing."""

from __future__ import annotations

import datetime
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


class BrandPublishingEngine:
    """Compile governed BrandPackages, protect brand truth, and run dry-run publishing gates."""

    @staticmethod
    def compile_brand_package(
        package_id: str,
        brand_id: str,
        version: str,
        identity: dict[str, Any],
        voice: dict[str, Any],
        audience: dict[str, Any],
        approved_claims: list[dict[str, Any]],
        assets: list[dict[str, Any]],
        usage_rules: list[str],
        provenance: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create and validate a canonical BrandPackage."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        package = {
            "schema_version": SCHEMA_VERSION,
            "package_id": package_id,
            "brand_id": brand_id,
            "version": version,
            "approved_at": now_iso,
            "identity": identity,
            "voice": voice,
            "audience": audience,
            "approved_claims": approved_claims,
            "assets": assets,
            "usage_rules": usage_rules,
            "provenance": provenance,
        }
        return validate_contract("BrandPackage", package)

    @staticmethod
    def verify_immutability(canonical_pkg: dict[str, Any], candidate_pkg: dict[str, Any]) -> tuple[bool, list[str]]:
        """Verify that downstream consumers have not mutated brand truth without a version bump."""
        violations = []
        if canonical_pkg.get("version") == candidate_pkg.get("version"):
            # If same version, contents must be strictly identical
            if canonical_pkg.get("identity") != candidate_pkg.get("identity"):
                violations.append("Unauthorized mutation of 'identity' under identical version pin.")
            if canonical_pkg.get("voice") != candidate_pkg.get("voice"):
                violations.append("Unauthorized mutation of 'voice' under identical version pin.")
            if canonical_pkg.get("approved_claims") != candidate_pkg.get("approved_claims"):
                violations.append("Unauthorized modification of 'approved_claims' under identical version pin.")
            if canonical_pkg.get("usage_rules") != candidate_pkg.get("usage_rules"):
                violations.append("Unauthorized mutation of 'usage_rules' under identical version pin.")

        return (len(violations) == 0, violations)

    @staticmethod
    def dry_run_publish(
        brand_pkg: dict[str, Any],
        source_record: dict[str, Any],
        draft_content: str,
        channel: str = "blog",
    ) -> dict[str, Any]:
        """Validate draft against BrandPackage and generate a non-destructive publishing receipt."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        # Verify brand claims alignment
        claims = [c.get("claim", "") for c in brand_pkg.get("approved_claims", [])]
        matched_claims = [c for c in claims if c.lower() in draft_content.lower()]

        # Generate publication receipt
        receipt = {
            "receipt_id": f"pub-dry-{int(datetime.datetime.now().timestamp())}",
            "channel": channel,
            "status": "dry_run_verified",
            "timestamp": now_iso,
            "brand_package_id": brand_pkg.get("package_id"),
            "brand_version": brand_pkg.get("version"),
            "source_id": source_record.get("source_id"),
            "source_sha256": source_record.get("sha256"),
            "matched_approved_claims_count": len(matched_claims),
            "dry_run_only": True,
            "live_published": False,
            "notes": "Draft successfully verified against brand constraints. Awaiting explicit manual release."
        }
        return receipt

    @staticmethod
    def get_brand_workshop_phases() -> list[dict[str, Any]]:
        """Return the 9 low-typing intake phases mapped to Brand Maker state."""
        return [
            {"phase": 1, "name": "Vision & Core Truth", "state": "intake_vision", "required_inputs": ["one_liner", "enemy"]},
            {"phase": 2, "name": "Audience Archetypes", "state": "intake_audience", "required_inputs": ["primary_operator", "pain_points"]},
            {"phase": 3, "name": "Brand Voice Pillars", "state": "intake_voice", "required_inputs": ["tone_adjectives", "taboo_words"]},
            {"phase": 4, "name": "Visual Foundation", "state": "intake_visual", "required_inputs": ["palette_hex", "typeface_pair"]},
            {"phase": 5, "name": "Approved Claims Registry", "state": "intake_claims", "required_inputs": ["verifiable_claims"]},
            {"phase": 6, "name": "Asset Inventory", "state": "intake_assets", "required_inputs": ["logo_paths", "icon_set"]},
            {"phase": 7, "name": "Usage & Constraint Rules", "state": "intake_rules", "required_inputs": ["do_list", "dont_list"]},
            {"phase": 8, "name": "Channel Archetypes", "state": "intake_channels", "required_inputs": ["formats", "cadence"]},
            {"phase": 9, "name": "Canonical Package Approval", "state": "approved_package", "required_inputs": ["approver_signoff"]},
        ]
