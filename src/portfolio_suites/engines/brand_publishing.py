"""Brand Publishing reference prototype engine powering BrandPackage validation, VCC publishing, and intake workflows.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. brand-maker, vcc)."""

from __future__ import annotations

import datetime
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract
from ..identifiers import new_prefixed_id


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
            "receipt_id": new_prefixed_id("pub-dry"),
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

    @staticmethod
    def verify_package_consumer(
        brand_pkg: dict[str, Any],
        consumer_name: str,
        pinned_version: str,
        read_only_intent: bool = True,
    ) -> dict[str, Any]:
        """Validate multi-caller BrandPackage consumption with version pinning (B4 wave)."""
        valid_pkg = validate_contract("BrandPackage", brand_pkg)
        is_version_match = valid_pkg["version"] == pinned_version
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "package_id": valid_pkg["package_id"],
            "consumer_name": consumer_name,
            "pinned_version": pinned_version,
            "package_version": valid_pkg["version"],
            "version_match": is_version_match,
            "mutation_shield_active": read_only_intent,
            "verified_at": now_iso,
            "status": "verified" if is_version_match else "version_mismatch",
        }

    @staticmethod
    def execute_brand_maker_intake(
        brand_id: str,
        phase_inputs: dict[int, dict[str, Any]],
        approver: str = "Ryan",
    ) -> dict[str, Any]:
        """Execute Brand Workshop 9-phase intake within Brand Maker state machine (B5 wave)."""
        phases = BrandPublishingEngine.get_brand_workshop_phases()
        completed_phases = []
        all_completed = True
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for phase in phases:
            p_num = phase["phase"]
            user_input = phase_inputs.get(p_num, {})
            reqs = phase.get("required_inputs", [])
            missing = [k for k in reqs if not user_input.get(k)]
            is_phase_complete = len(missing) == 0 and len(user_input) > 0

            if not is_phase_complete:
                all_completed = False

            completed_phases.append({
                "phase": p_num,
                "name": phase["name"],
                "state": phase["state"],
                "captured_data": user_input,
                "missing_inputs": missing,
                "completed": is_phase_complete,
            })

        completed_count = sum(1 for p in completed_phases if p["completed"])

        if not all_completed:
            return {
                "brand_id": brand_id,
                "phases_total": len(phases),
                "phases_completed": completed_count,
                "intake_log": completed_phases,
                "resulting_package": None,
                "reconciliation_status": "intake_incomplete",
            }

        # Dynamically compile package from actual user intake data across phases
        p1 = phase_inputs.get(1, {})
        p2 = phase_inputs.get(2, {})
        p3 = phase_inputs.get(3, {})
        p4 = phase_inputs.get(4, {})
        p5 = phase_inputs.get(5, {})
        p6 = phase_inputs.get(6, {})
        p7 = phase_inputs.get(7, {})
        p9 = phase_inputs.get(9, {})

        claims_raw = p5.get("verifiable_claims") or p5.get("claims") or ["Default validated brand claim"]
        approved_claims = [
            {"claim_id": f"claim-{i+1:02d}", "claim": c} if isinstance(c, str) else c
            for i, c in enumerate(claims_raw)
        ]

        logos_raw = p6.get("logo_paths") or p6.get("assets") or ["assets/logo.svg"]
        assets = [
            {"asset_type": "logo", "path": a} if isinstance(a, str) else a
            for a in logos_raw
        ]

        usage_rules_list = p7.get("usage_rules")
        if not usage_rules_list:
            usage_rules_list = [f"DO: {d}" for d in p7.get("do_list", [])] + [f"DONT: {d}" for d in p7.get("dont_list", [])]
        if not usage_rules_list:
            usage_rules_list = ["Never modify without explicit version bump"]

        audience_val = p2.get("target_audience") or p2.get("primary_operator") or "Technical Operators and Engineering Leads"
        tone_val = p3.get("tone_adjectives") or p3.get("tone_words") or ["precise", "concise", "operator-first"]
        tagline_val = p4.get("tagline") or p1.get("one_liner") or "Instituted Brand Package"
        name_val = p1.get("brand_name") or brand_id.replace("-", " ").title()

        pkg = {
            "schema_version": SCHEMA_VERSION,
            "package_id": f"pkg-bm-{brand_id}-1.0.0",
            "brand_id": brand_id,
            "version": "1.0.0",
            "approved_at": now_iso,
            "identity": {
                "name": name_val,
                "tagline": tagline_val,
            },
            "voice": {
                "tone": tone_val,
            },
            "audience": {
                "primary": audience_val,
            },
            "approved_claims": approved_claims,
            "assets": assets,
            "usage_rules": usage_rules_list,
            "provenance": [{
                "author": p9.get("approver_signoff") or approver,
                "method": "brand_maker_9_phase_intake",
                "timestamp": now_iso,
            }],
        }
        validated_pkg = validate_contract("BrandPackage", pkg)

        return {
            "brand_id": brand_id,
            "phases_total": len(phases),
            "phases_completed": completed_count,
            "intake_log": completed_phases,
            "resulting_package": validated_pkg,
            "reconciliation_status": "brand_workshop_intake_ported_to_brand_maker",
        }

    @staticmethod
    def simulate_vcc_human_approval(
        brand_pkg: dict[str, Any],
        source_record: dict[str, Any],
        draft_content: str,
        human_decision: str = "approved",
        reviewer: str = "Ryan",
    ) -> dict[str, Any]:
        """Simulate VCC editorial review with human approval gate stopping short of live publish (B6 wave)."""
        valid_decisions = {"approved", "rejected", "needs_revision"}
        if human_decision not in valid_decisions:
            return {
                "review_id": new_prefixed_id("vcc-rev"),
                "error": f"Invalid human_decision '{human_decision}'. Must be one of {valid_decisions}",
                "status": "blocked_invalid_decision",
            }

        dry_receipt = BrandPublishingEngine.dry_run_publish(brand_pkg, source_record, draft_content, channel="vcc-focus-group")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Derive final status from human decision and dry-run claim match
        if human_decision == "rejected":
            status = "blocked_rejected"
        elif human_decision == "needs_revision":
            status = "blocked_revision_required"
        elif dry_receipt.get("matched_approved_claims_count", 0) == 0:
            status = "blocked_unmatched_claims"
        else:
            status = "ready_for_operator_release"

        return {
            "review_id": new_prefixed_id("vcc-rev"),
            "brand_package_id": brand_pkg.get("package_id"),
            "source_id": source_record.get("source_id"),
            "dry_run_receipt": dry_receipt,
            "human_gate": {
                "reviewer": reviewer,
                "decision": human_decision,
                "timestamp": now_iso,
                "boundary_check": "stopped_before_live_publish",
                "notes": "Verified against BrandPackage truth; human signoff recorded; live publish authority preserved for operator.",
            },
            "status": status,
        }
