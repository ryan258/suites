"""Operator OS engine powering source capture, PKOS indexing, Observer projections, and JARVIS actions."""

from __future__ import annotations

import datetime
import hashlib
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


class OperatorOSEngine:
    """Capture raw notes into SourceRecords, build PKOS citations, and project safe Observer notes."""

    @staticmethod
    def capture_source(
        content: str,
        origin: str,
        source_id: str,
        media_type: str = "text/markdown",
        author: str = "Ryan",
        collector: str = "portfolio_suites.engines.operator_os",
    ) -> dict[str, Any]:
        """Convert arbitrary text into a content-addressed, validated SourceRecord."""
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = {
            "schema_version": SCHEMA_VERSION,
            "source_id": source_id,
            "acquired_at": now_iso,
            "sha256": digest,
            "size_bytes": len(encoded),
            "media_type": media_type,
            "origin": origin,
            "provenance": {
                "author": author,
                "collector": collector,
                "intake_method": "source_capture",
                "raw_preview": content[:120].strip(),
            },
        }
        return validate_contract("SourceRecord", record)

    @staticmethod
    def project_to_observer(source_record: dict[str, Any], title: str, summary: str, body: str) -> str:
        """Create a derived Obsidian Observer note fenced against accidental re-ingestion."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        src_id = source_record.get("source_id", "unknown")
        sha = source_record.get("sha256", "unknown")

        return f"""---
title: "{title}"
type: observer_projection
source_id: "{src_id}"
source_sha256: "{sha}"
projected_at: "{now_iso}"
generator: "portfolio_suites.operator_os"
status: derived
fenced_from_reingestion: true
---

<!-- FENCE: DO NOT RE-INGEST INTO PKOS CANONICAL CORPUS -->

# {title}

> **Source Citation:** `{src_id}` (SHA: `{sha[:12]}...`)
> **Acquired Origin:** `{source_record.get("origin")}`

## Summary
{summary}

## Extracted Analysis
{body}

---
*Derived via Operator OS projection engine. Immutable canonical truth lives in PKOS.*
"""

    @staticmethod
    def preview_jarvis_action(action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Generate a dry-run preview receipt for a user-approved JARVIS command."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "action_id": f"act-jarvis-{int(datetime.datetime.now().timestamp())}",
            "action_name": action_name,
            "parameters": parameters,
            "state": "preview_ready",
            "preview_at": now_iso,
            "requires_human_approval": True,
            "destructive": False,
            "recovery_path": "undo_via_backup_or_clean_revert",
        }
