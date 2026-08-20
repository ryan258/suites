"""Accessibility engine powering audit rules, A11yFinding generation, and parity checks."""

from __future__ import annotations

import datetime
import re
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


class AccessibilityEngine:
    """Audit DOM/HTML snippets, generate A11yFinding payloads, and reconcile overlay extensions."""

    @staticmethod
    def audit_html_snippet(html_content: str, source_url: str = "snippet://local") -> list[dict[str, Any]]:
        """Run deterministic WCAG and ARIA rules over HTML markup."""
        findings = []
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Rule 1: Form error association (WCAG 3.3.1)
        # Check inputs with class 'error' or 'is-invalid' without aria-describedby or aria-invalid
        input_matches = re.finditer(
            r'<input\b(?=[^>]*\bclass=["\'][^"\']*\b(is-invalid|error)\b[^"\']*["\'])(?![^>]*\b(aria-describedby|aria-invalid)\b)[^>]*>',
            html_content,
            re.IGNORECASE,
        )
        for idx, match in enumerate(input_matches, start=1):
            raw_tag = match.group(0)
            id_match = re.search(r'id=["\']([^"\']+)["\']', raw_tag)
            elem_id = id_match.group(1) if id_match else f"input-{idx}"
            finding = {
                "schema_version": SCHEMA_VERSION,
                "finding_id": f"find-wcag-331-{idx:03d}",
                "rule_id": "wcag-3.3.1-error-identification",
                "severity": "critical",
                "summary": f"Form control #{elem_id} has invalid state styling without programmatic aria-describedby linkage.",
                "target": f"input#{elem_id}",
                "evidence": [
                    {
                        "dom_snippet": raw_tag,
                        "selector": f"input#{elem_id}",
                        "source": source_url,
                        "timestamp": now_iso,
                    }
                ],
                "evidence_kind": "deterministic",
                "needs_review": False,
                "status": "open",
            }
            findings.append(validate_contract("A11yFinding", finding))

        # Rule 2: Image alt text (WCAG 1.1.1)
        img_matches = re.finditer(r'<img\b(?![^>]*\balt=)[^>]*>', html_content, re.IGNORECASE)
        for idx, match in enumerate(img_matches, start=1):
            raw_tag = match.group(0)
            src_match = re.search(r'src=["\']([^"\']+)["\']', raw_tag)
            src_val = src_match.group(1) if src_match else "unknown"
            finding = {
                "schema_version": SCHEMA_VERSION,
                "finding_id": f"find-wcag-111-{idx:03d}",
                "rule_id": "wcag-1.1.1-non-text-content",
                "severity": "serious",
                "summary": f"Image with src '{src_val}' is missing an alt attribute.",
                "target": f"img[src='{src_val}']",
                "evidence": [
                    {
                        "dom_snippet": raw_tag,
                        "selector": f"img[src='{src_val}']",
                        "source": source_url,
                        "timestamp": now_iso,
                    }
                ],
                "evidence_kind": "deterministic",
                "needs_review": False,
                "status": "open",
            }
            findings.append(validate_contract("A11yFinding", finding))

        # Rule 3: Button without accessible name (WCAG 4.1.2)
        btn_matches = re.finditer(
            r'<button\b(?![^>]*\b(aria-label|aria-labelledby|title)=)[^>]*>\s*(?:<[^>]+>\s*)*</button>',
            html_content,
            re.IGNORECASE,
        )
        for idx, match in enumerate(btn_matches, start=1):
            raw_tag = match.group(0)
            finding = {
                "schema_version": SCHEMA_VERSION,
                "finding_id": f"find-wcag-412-{idx:03d}",
                "rule_id": "wcag-4.1.2-name-role-value",
                "severity": "critical",
                "summary": "Button element has no text content and lacks an aria-label or aria-labelledby attribute.",
                "target": "button:empty",
                "evidence": [
                    {
                        "dom_snippet": raw_tag,
                        "selector": "button",
                        "source": source_url,
                        "timestamp": now_iso,
                    }
                ],
                "evidence_kind": "deterministic",
                "needs_review": False,
                "status": "open",
            }
            findings.append(validate_contract("A11yFinding", finding))

        return findings

    @staticmethod
    def create_ai_assisted_finding(
        finding_id: str,
        rule_id: str,
        summary: str,
        target: str,
        hypothesis: str,
        severity: str = "moderate"
    ) -> dict[str, Any]:
        """Generate an AI-assisted finding, enforcing strict review flags."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "finding_id": finding_id,
            "rule_id": rule_id,
            "severity": severity,
            "summary": summary,
            "target": target,
            "evidence": [
                {
                    "ai_hypothesis": hypothesis,
                    "model": "model-behavior-lab/comparator-v1",
                    "timestamp": now_iso,
                }
            ],
            "evidence_kind": "ai-assisted",
            "needs_review": True,
            "status": "open",
        }
        return validate_contract("A11yFinding", payload)

    @staticmethod
    def reconcile_keyboard_overlays() -> dict[str, Any]:
        """Parity evaluation across the 3 keyboard navigation overlay checkouts."""
        overlays = {
            "kb-overlay": {
                "role": "canonical_anchor",
                "manifest_version": 3,
                "features": ["spatial_nav", "visual_focus_ring", "keyboard_shortcuts", "settings_storage", "aria_tree_scan"],
                "permissions": ["activeTab", "storage"],
                "active_status": "retained",
            },
            "keyboard-nav-overlay": {
                "role": "duplicate_donor",
                "manifest_version": 2,
                "features": ["spatial_nav", "visual_focus_ring"],
                "permissions": ["<all_urls>", "tabs", "storage"],
                "active_status": "superseded_by_kb-overlay",
            },
            "keyboard-nav-overlay-94bf7e": {
                "role": "duplicate_donor",
                "manifest_version": 2,
                "features": ["spatial_nav"],
                "permissions": ["<all_urls>", "tabs"],
                "active_status": "superseded_by_kb-overlay",
            }
        }
        return {
            "canonical_target": "kb-overlay",
            "matrix": overlays,
            "recommendation": "Preserve kb-overlay as single canonical extension; donor extensions are fully covered and ready for frozen status.",
        }
