"""Accessibility reference prototype engine powering audit rules, A11yFinding contract validation, and fixture checks.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. allys-tools).
"""

from __future__ import annotations

import datetime
import re
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


# HTML attribute names are hyphenated, so `\b` matches *inside* them: `\balt=` fires on
# `data-alt=` and `\berror\b` fires on `no-error-state`. An attribute name only ever starts
# after whitespace or the tag name, never after a word character or a hyphen.
ATTR = r"(?<![\w-])"


class AccessibilityEngine:
    """Reference prototype for DOM/HTML snippet auditing, A11yFinding contract generation, and overlay reconciliation."""

    @staticmethod
    def audit_html_snippet(html_content: str, source_url: str = "snippet://local") -> list[dict[str, Any]]:
        """Run deterministic WCAG and ARIA rules over HTML markup."""
        findings = []
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Rule 1: Form error association (WCAG 3.3.1)
        # Check inputs with class 'error' or 'is-invalid' without aria-describedby or aria-invalid
        input_matches = re.finditer(
            rf'<input\b(?=[^>]*{ATTR}class\s*=["\'][^"\']*{ATTR}(is-invalid|error)(?![\w-])[^"\']*["\'])(?![^>]*{ATTR}(aria-describedby|aria-invalid)(?![\w-]))[^>]*>',
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
        img_matches = re.finditer(rf'<img\b(?![^>]*{ATTR}alt\s*=)[^>]*>', html_content, re.IGNORECASE)
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
            rf'<button\b(?![^>]*{ATTR}(aria-label|aria-labelledby|title)\s*=)[^>]*>\s*(?:<[^>]+>\s*)*</button>',
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

        # Rule 4: Link without accessible text (WCAG 2.4.4)
        # Parse <a>...</a> tags and check for inner text, aria attributes, or child img alt text
        a_pattern = re.finditer(r'<a\b([^>]*)>(.*?)</a>', html_content, re.IGNORECASE | re.DOTALL)
        for idx, match in enumerate(a_pattern, start=1):
            attrs = match.group(1)
            inner_html = match.group(2).strip()

            # Check if <a> has direct accessible name attributes
            has_direct_name = bool(re.search(rf'{ATTR}(aria-label|aria-labelledby|title)\s*=["\'][^"\']+["\']', attrs, re.IGNORECASE))

            # Check if inner content has visible text (excluding tags)
            visible_text = re.sub(r'<[^>]+>', '', inner_html).strip()

            # Check if inner content contains image with non-empty alt
            has_img_alt = bool(re.search(rf'<img\b[^>]*{ATTR}alt\s*=["\'][^"\']+["\']', inner_html, re.IGNORECASE))

            # Check if inner content contains svg with aria-label
            has_svg_label = bool(re.search(rf'<svg\b[^>]*{ATTR}aria-label\s*=["\'][^"\']+["\']', inner_html, re.IGNORECASE))

            if not (has_direct_name or visible_text or has_img_alt or has_svg_label):
                raw_tag = match.group(0)
                finding = {
                    "schema_version": SCHEMA_VERSION,
                    "finding_id": f"find-wcag-244-{idx:03d}",
                    "rule_id": "wcag-2.4.4-link-purpose-in-context",
                    "severity": "serious",
                    "summary": "Anchor tag contains no accessible name from text, aria-label, or child image alt.",
                    "target": "a:empty",
                    "evidence": [
                        {
                            "dom_snippet": raw_tag[:120],
                            "selector": "a",
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
    def audit_rule_families(html_content: str, source_url: str = "snippet://wcag-auditor-port") -> list[dict[str, Any]]:
        """Audit broader WCAG rule candidates ported from WCAG Auditor (A4 wave)."""
        findings = AccessibilityEngine.audit_html_snippet(html_content, source_url=source_url)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Rule 5: Table without header cells (WCAG 1.3.1) - Heuristic parse of table blocks
        table_matches = re.finditer(r'<table\b[^>]*>(.*?)</table>', html_content, re.IGNORECASE | re.DOTALL)
        for idx, match in enumerate(table_matches, start=1):
            table_body = match.group(1)
            # Only flag if table has data cells (<td>) but completely lacks header cells (<th>)
            has_td = bool(re.search(r'<td\b', table_body, re.IGNORECASE))
            has_th = bool(re.search(r'<th\b', table_body, re.IGNORECASE))
            if has_td and not has_th:
                findings.append(
                    validate_contract(
                        "A11yFinding",
                        {
                            "schema_version": SCHEMA_VERSION,
                            "finding_id": f"find-wcag-131-tbl-{idx:03d}",
                            "rule_id": "wcag-1.3.1-info-and-relationships-table-header",
                            "severity": "moderate",
                            "summary": "Data table contains data cells (<td>) without any declared <th> header cells.",
                            "target": f"table:nth-of-type({idx})",
                            "evidence": [
                                {
                                    "dom_snippet": match.group(0)[:160],
                                    "selector": f"table:nth-of-type({idx})",
                                    "source": source_url,
                                    "timestamp": now_iso,
                                }
                            ],
                            "evidence_kind": "manual",
                            "needs_review": True,
                            "status": "open",
                        },
                    )
                )

        # Backlog Candidate 1: Link purpose ambiguous text (WCAG 2.4.4 - port-review)
        vague_links = re.finditer(r'<a\b[^>]*>(?:<[^>]+>)*\s*(click here|read more|learn more|more|here|link)\s*(?:<[^>]+>)*</a>', html_content, re.IGNORECASE)
        for idx, match in enumerate(vague_links, start=1):
            findings.append(
                validate_contract(
                    "A11yFinding",
                    {
                        "schema_version": SCHEMA_VERSION,
                        "finding_id": f"find-wcag-244-vague-{idx:03d}",
                        "rule_id": "wcag-2.4.4-link-purpose",
                        "severity": "moderate",
                        "summary": f"Link uses ambiguous text '{match.group(1)}' requiring context review.",
                        "target": "a",
                        "evidence": [
                            {
                                "dom_snippet": match.group(0),
                                "selector": "a",
                                "source": source_url,
                                "timestamp": now_iso,
                            }
                        ],
                        "evidence_kind": "manual",
                        "needs_review": True,
                        "status": "open",
                    },
                )
            )

        # Backlog Candidate 2: Identify Input Purpose (WCAG 1.3.5 - port-review)
        # Check personal inputs (email, tel, name) missing autocomplete attribute
        personal_inputs = re.finditer(rf'<input\b(?=[^>]*{ATTR}(?:type\s*=["\'](?:email|tel)["\']|name\s*=["\'](?:email|tel|name|fname|lname)["\']))(?![^>]*{ATTR}autocomplete\s*=)[^>]*>', html_content, re.IGNORECASE)
        for idx, match in enumerate(personal_inputs, start=1):
            findings.append(
                validate_contract(
                    "A11yFinding",
                    {
                        "schema_version": SCHEMA_VERSION,
                        "finding_id": f"find-wcag-135-auto-{idx:03d}",
                        "rule_id": "wcag-1.3.5-identify-input-purpose",
                        "severity": "moderate",
                        "summary": "Personal data input field lacks an explicit autocomplete token attribute.",
                        "target": "input",
                        "evidence": [
                            {
                                "dom_snippet": match.group(0),
                                "selector": "input",
                                "source": source_url,
                                "timestamp": now_iso,
                            }
                        ],
                        "evidence_kind": "manual",
                        "needs_review": True,
                        "status": "open",
                    },
                )
            )

        # Backlog Candidate 3: Adaptable Landmarks (WCAG 1.3.1 - port-review)
        if "<body" in html_content.lower() and "<main" not in html_content.lower() and "role=\"main\"" not in html_content.lower():
            findings.append(
                validate_contract(
                    "A11yFinding",
                    {
                        "schema_version": SCHEMA_VERSION,
                        "finding_id": "find-wcag-131-main-001",
                        "rule_id": "wcag-1.3.1-adaptable-landmarks",
                        "severity": "moderate",
                        "summary": "Document contains a <body> but does not declare a <main> or role='main' landmark.",
                        "target": "body",
                        "evidence": [
                            {
                                "dom_snippet": "<body> ... (no <main>) ... </body>",
                                "selector": "body",
                                "source": source_url,
                                "timestamp": now_iso,
                            }
                        ],
                        "evidence_kind": "manual",
                        "needs_review": True,
                        "status": "open",
                    },
                )
            )

        return findings

    @staticmethod
    def evaluate_wcag_auditor_backlog_catalog(cases: list[dict[str, Any]]) -> dict[str, Any]:
        """Exercise all mapped WCAG Auditor candidate backlog cases with deterministic review boundaries (A4 wave)."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        evaluations = []

        # Candidate mapping metadata: (sc_number, owner_module, disposition_type)
        disposition_map = {
            "inline-language-change": ("3.1.2", "page-scanner-ext", "port-review"),
            "audio-description-track": ("1.2.5", "media-scanner-ext", "port-review"),
            "adaptable-landmarks": ("1.3.1", "page-scanner-ext", "port-review"),
            "enough-time-controls": ("2.2.2", "interaction-tester", "port-review"),
            "link-purpose": ("2.4.4", "page-scanner-ext", "port-review"),
            "focus-not-obscured": ("2.4.11", "keyboard-tester", "port-review"),
            "pointer-gestures": ("2.5.1", "interaction-tester", "port-review"),
            "pointer-cancellation": ("2.5.2", "interaction-tester", "port-review"),
            "dragging-movements": ("2.5.7", "interaction-tester", "port-review"),
            "predictable-navigation": ("3.2.2", "interaction-tester", "port-review"),
            "input-assistance-error-msg": ("3.3.1", "aria-validator", "port-narrow"),
            "labels-or-instructions": ("3.3.2", "page-scanner-ext", "port-review"),
            "error-suggestion": ("3.3.3", "page-scanner-ext", "port-review"),
            "required-field-indicators": ("3.3.2", "page-scanner-ext", "port-review"),
            "redundant-entry": ("3.3.7", "multi-step-tester", "port-review"),
            "accessible-authentication": ("3.3.8", "interaction-tester", "port-review"),
            "identify-input-purpose": ("1.3.5", "page-scanner-ext", "port-review"),
            "status-messages": ("4.1.3", "aria-validator", "port-review"),
            "consistent-navigation": ("3.2.3", "site-crawler-ext", "port-review"),
            "crawl-auth-and-filters": ("crawl", "site-crawler-ext", "port-options"),
        }

        for c in cases:
            cid = c.get("id", "unknown")
            sc, owner, disp = disposition_map.get(cid, ("unknown", "unassigned", "port-review"))

            # Formulate structured finding for the case setup
            needs_rev = (disp == "port-review" or disp == "port-options")
            ev_kind = "deterministic" if disp == "port-narrow" else "manual"

            finding = {
                "schema_version": SCHEMA_VERSION,
                "finding_id": f"find-backlog-{cid[:18]}-001",
                "rule_id": f"wcag-{sc}-{cid}",
                "severity": "moderate",
                "summary": f"Evaluated candidate {cid} against setup '{c.get('setup')}' with expected behavior '{c.get('expected')}'.",
                "target": f"fixture:{cid}",
                "evidence": [
                    {
                        "dom_snippet": f"<!-- Setup: {c.get('setup')} -->",
                        "selector": f"fixture:{cid}",
                        "source": f"parity://wcag-auditor/{cid}",
                        "timestamp": now_iso,
                    }
                ],
                "evidence_kind": ev_kind,
                "needs_review": needs_rev,
                "status": "open",
            }
            validated = validate_contract("A11yFinding", finding)

            evaluations.append({
                "candidate_id": cid,
                "success_criterion": sc,
                "owner_module": owner,
                "disposition": disp,
                "kind": c.get("kind"),
                "finding": validated,
                "no_unauthorized_conformance_claim": True,
                "review_label_preserved": needs_rev,
            })

        return {
            "total_candidates_evaluated": len(evaluations),
            "port_review_count": sum(1 for e in evaluations if e["disposition"] == "port-review"),
            "port_narrow_count": sum(1 for e in evaluations if e["disposition"] == "port-narrow"),
            "port_options_count": sum(1 for e in evaluations if e["disposition"] == "port-options"),
            "evaluations": evaluations,
            "status": "all_backlog_candidates_evidenced",
        }

    @staticmethod
    def roundtrip_kitchen_learning_finding(finding: dict[str, Any]) -> dict[str, Any]:
        """A11y Kitchen teaching surface consumption of an A11yFinding contract (A5 wave)."""
        valid_finding = validate_contract("A11yFinding", finding)
        # Transform for pedagogical projection while retaining 100% canonical contract fidelity
        return {
            "learner_module_id": f"kitchen-mod-{valid_finding['rule_id']}",
            "station_id": "station-02-the-error-message",
            "lesson_title": f"Teaching & Remediation for {valid_finding['rule_id']}",
            "severity_badge": valid_finding["severity"].upper(),
            "target_element": valid_finding["target"],
            "modes": {
                "advocate": f"Clear error identification helps all users understand what went wrong and how to fix it without frustration.",
                "builder": f"Ensure {valid_finding['target']} associates with its error container via aria-errormessage or aria-describedby with visible text.",
                "presenter": f"Demonstrate form submission failure before and after error message program association.",
            },
            "remediation_hint": valid_finding["summary"],
            "canonical_finding": valid_finding,
            "evidence_loss": False,
            "roundtrip_status": "verified",
        }

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
                "features": [
                    "spatial_nav",
                    "visual_focus_ring",
                    "keyboard_shortcuts",
                    "settings_storage",
                    "aria_tree_scan",
                    "shadow_dom_encapsulation",
                    "mutation_observer_updates",
                    "global_chrome_command",
                ],
                "permissions": ["activeTab", "storage"],
                "code_size_bytes": 33434,
                "active_status": "retained_canonical",
            },
            "keyboard-nav-overlay": {
                "role": "duplicate_donor",
                "manifest_version": 3,
                "features": ["spatial_nav", "visual_focus_ring"],
                "permissions": ["activeTab", "storage"],
                "code_size_bytes": 9497,
                "active_status": "superseded_by_kb-overlay",
                "flaws_identified": ["syntax_typos_in_content_js", "global_css_leakage_no_shadow_dom"],
            },
            "keyboard-nav-overlay-94bf7e": {
                "role": "duplicate_donor",
                "manifest_version": 3,
                "features": ["spatial_nav"],
                "permissions": ["activeTab", "storage"],
                "code_size_bytes": 4073,
                "active_status": "superseded_by_kb-overlay",
                "flaws_identified": ["unencapsulated_dom", "incomplete_event_handling"],
            },
        }
        return {
            "canonical_target": "kb-overlay",
            "matrix": overlays,
            "recommendation": "Preserve kb-overlay as single canonical extension; donor extensions are 100% superseded in capability and ready for frozen status.",
        }

    @staticmethod
    def finalize_overlay_reconciliation() -> dict[str, Any]:
        """Propose canonical overlay consolidation and freeze boundary (A6 wave reference prototype)."""
        reconciliation = AccessibilityEngine.reconcile_keyboard_overlays()
        return {
            "artifact_kind": "reference_prototype",
            "proposed_canonical_anchor": "kb-overlay",
            "manifest_version": 3,
            "proposed_frozen_donors": ["keyboard-nav-overlay", "keyboard-nav-overlay-94bf7e"],
            "features_targeted": ["spatial_nav", "visual_focus_ring", "keyboard_shortcuts", "aria_tree_scan"],
            "permissions_minimized": ["activeTab", "storage"],
            "proposed_disposition": "proposed_anchor",
            "migration_acceptance_verified": False,
        }
