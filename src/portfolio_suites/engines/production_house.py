"""Production House engine: resumable ProductionJob flows plus deterministic script inspection.

NOTE: This is a control-plane engine and fixture comparator, not a replacement for external
canonical project runtimes (e.g. Groundwire, writers-room). Script parsing is local and
read-only; no audio, formatter, or Writers Room runtime is invoked from these methods.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


SHA256 = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_STATUSES = {"completed", "cancelled"}
TRANSITIONS = {
    "queued": {"running", "blocked", "failed", "cancelled"},
    "running": {"running", "blocked", "failed", "completed", "cancelled"},
    "blocked": {"running", "failed", "cancelled"},
    "failed": {"queued", "running", "cancelled"},
}


def _artifact_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _validate_artifacts(name: str, artifacts: Any) -> list[dict[str, Any]]:
    if not isinstance(artifacts, list):
        raise ValueError(f"{name} must be a list of artifact objects")
    validated = []
    seen_names: set[str] = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise ValueError(f"{name}[{index}] must be an object")
        artifact_name = artifact.get("name")
        digest = artifact.get("sha256")
        if not isinstance(artifact_name, str) or not artifact_name.strip():
            raise ValueError(f"{name}[{index}].name must be a non-empty string")
        if artifact_name in seen_names:
            raise ValueError(f"{name} contains duplicate artifact name {artifact_name!r}")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f"{name}[{index}].sha256 must be a lowercase SHA-256 digest")
        seen_names.add(artifact_name)
        validated.append(dict(artifact))
    return validated


_CHARACTER_CUE = re.compile(r"^\*\*([A-Z][A-Z0-9][A-Z0-9_ \-]{0,40})\*\*", re.M)
_MARKDOWN_HEADING = re.compile(r"^#{1,3}\s+(.+)$", re.M)
_FOUNTAIN_SCENE = re.compile(r"^(?:INT\.|EXT\.|INT/EXT\.|EST\.)[^\n]+", re.M | re.I)
_FOUNTAIN_CHARACTER = re.compile(r"^([A-Z][A-Z0-9][A-Z0-9 \-']{1,40})$", re.M)


class ProductionHouseEngine:
    """Manage resumable ProductionJob lifecycles and creative execution pipelines."""

    @staticmethod
    def parse_episode_script(script_text: str, source_name: str = "script.md") -> dict[str, Any]:
        """Parse a Groundwire/Fountain-shaped episode script into deterministic structure.

        This is a local text parse of bytes the caller already holds. It does not open a
        donor path, invoke a formatter, mix audio, or claim QC of a rendered master.
        """
        if not isinstance(source_name, str) or not source_name.strip() or len(source_name) > 240:
            raise ValueError("source_name must be a non-empty string up to 240 characters")
        if not isinstance(script_text, str) or not script_text.strip():
            raise ValueError("script_text must be a non-empty string")
        if len(script_text) > 1_048_576:
            raise ValueError("script_text exceeds the 1 MiB parse bound")
        characters = sorted({
            match.group(1).strip()
            for match in _CHARACTER_CUE.finditer(script_text)
        })
        if not characters:
            characters = sorted({
                match.group(1).strip()
                for match in _FOUNTAIN_CHARACTER.finditer(script_text)
                if " " not in match.group(1) or match.group(1).isupper()
            })
        headings = [item.strip() for item in _MARKDOWN_HEADING.findall(script_text) if item.strip()]
        fountain_scenes = [item.strip() for item in _FOUNTAIN_SCENE.findall(script_text)]
        encoded = script_text.encode("utf-8")
        return {
            "source_name": source_name.strip(),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
            "word_count": len(script_text.split()),
            "characters": characters[:40],
            "character_count": len(characters),
            "headings": headings[:40],
            "heading_count": len(headings),
            "fountain_scene_count": len(fountain_scenes),
            "parser": "suite_local_episode_script_v1",
            "external_runtime_invoked": False,
        }

    @staticmethod
    def create_job(job_id: str, domain: str, task: str, inputs: list[dict[str, Any]]) -> dict[str, Any]:
        """Initialize a new ProductionJob in queued state."""
        validated_inputs = _validate_artifacts("inputs", inputs)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "domain": domain,
            "task": task,
            "status": "queued",
            "inputs": validated_inputs,
            "outputs": [],
            "events": [
                {"time": now_iso, "stage": "initialization", "status": "job_created"}
            ],
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        return validate_contract("ProductionJob", job)

    @staticmethod
    def advance_job_stage(
        job: dict[str, Any],
        stage_name: str,
        new_outputs: list[dict[str, Any]] | None = None,
        status: str = "running",
        notes: str = "",
    ) -> dict[str, Any]:
        """Advance a job through pipeline stages, logging events and appending outputs."""
        updated = validate_contract("ProductionJob", job)
        current_status = updated["status"]
        if current_status in TERMINAL_STATUSES:
            raise ValueError(f"terminal ProductionJob status {current_status!r} is immutable")
        allowed = TRANSITIONS.get(current_status, set())
        if status not in allowed:
            raise ValueError(f"illegal ProductionJob transition {current_status!r} -> {status!r}")
        if not isinstance(stage_name, str) or not stage_name.strip():
            raise ValueError("stage_name must be a non-empty string")
        if not isinstance(notes, str):
            raise ValueError("notes must be a string")
        validated_outputs = _validate_artifacts("new_outputs", new_outputs or [])
        if status == "completed" and not (updated.get("outputs") or validated_outputs):
            raise ValueError("a completed ProductionJob must retain at least one hashed output")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updated["status"] = status
        updated["updated_at"] = now_iso

        events = list(updated.get("events", []))
        events.append({
            "time": now_iso,
            "stage": stage_name,
            "status": status,
            "notes": notes,
        })
        updated["events"] = events

        if validated_outputs:
            outputs = list(updated.get("outputs", []))
            existing_names = {item.get("name") for item in outputs if isinstance(item, dict)}
            overlap = sorted(existing_names & {item["name"] for item in validated_outputs})
            if overlap:
                raise ValueError(f"new_outputs duplicate existing artifact(s): {', '.join(overlap)}")
            outputs.extend(validated_outputs)
            updated["outputs"] = outputs

        return validate_contract("ProductionJob", updated)

    @staticmethod
    def build_groundwire_pipeline_job(episode_slug: str, script_sha: str) -> dict[str, Any]:
        """Create a completed deterministic fixture model; no external audio runtime is invoked."""
        if not isinstance(episode_slug, str) or not episode_slug.strip():
            raise ValueError("episode_slug must be a non-empty string")
        if not isinstance(script_sha, str) or not SHA256.fullmatch(script_sha):
            raise ValueError("script_sha must be a lowercase SHA-256 digest")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = {
            "schema_version": SCHEMA_VERSION,
            "job_id": f"job-gw-{episode_slug}",
            "domain": "groundwire-audio-play",
            "task": "project-episode-from-hashed-script",
            "status": "completed",
            "inputs": [
                {"name": f"{episode_slug}.fountain", "sha256": script_sha, "type": "script"}
            ],
            "outputs": [
                {"name": f"{episode_slug}-master.flac", "sha256": script_sha, "duration_sec": 784.2},
                {"name": f"{episode_slug}-captions.vtt", "sha256": script_sha, "cues": 142},
                {"name": f"{episode_slug}-qc-report.json", "sha256": script_sha, "lufs": -16.2, "peak_db": -1.0}
            ],
            "events": [
                {"time": now_iso, "stage": "script_intake", "status": "modeled", "notes": "Job input is the hashed episode script; no donor parser subprocess was invoked"},
                {"time": now_iso, "stage": "formatter_projection", "status": "modeled", "notes": "Projected stem metadata from the hashed script; no voice provider was invoked"},
                {"time": now_iso, "stage": "mix_projection", "status": "modeled", "notes": "Projected a -22 dB mix target; no audio was mixed"},
                {"time": now_iso, "stage": "qc_projection", "status": "modeled", "notes": "Projected a -16.2 LUFS result; no broadcast QC was performed"}
            ],
            "created_at": now_iso,
            "updated_at": now_iso,
            "execution_kind": "deterministic_fixture_model",
            "external_runtime_invoked": False,
            "fixture_input_sha256": script_sha,
        }
        return validate_contract("ProductionJob", job)

    @staticmethod
    def build_investigative_documentary_job(episode_slug: str, script_sha: str) -> dict[str, Any]:
        """Create a deterministic documentary fixture model; no media is rendered."""
        if not isinstance(episode_slug, str) or not episode_slug.strip():
            raise ValueError("episode_slug must be a non-empty string")
        if not isinstance(script_sha, str) or not SHA256.fullmatch(script_sha):
            raise ValueError("script_sha must be a lowercase SHA-256 digest")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = {
            "schema_version": SCHEMA_VERSION,
            "job_id": f"job-gw-doc-{episode_slug}",
            "domain": "groundwire-documentary",
            "task": "project-documentary-from-hashed-script",
            "status": "completed",
            "inputs": [
                {"name": f"{episode_slug}.fountain", "sha256": script_sha, "type": "script"},
                {"name": "archival-tape-01.wav", "sha256": script_sha, "type": "field_audio"},
                {"name": "interview-lead-researcher.flac", "sha256": script_sha, "type": "dialogue"}
            ],
            "outputs": [
                {"name": f"{episode_slug}-broadcast-master.wav", "sha256": script_sha, "duration_sec": 1420.5},
                {"name": f"{episode_slug}-transcript.vtt", "sha256": script_sha, "cues": 310},
                {"name": f"{episode_slug}-provenance-manifest.json", "sha256": script_sha, "lufs": -16.0, "sources": 3}
            ],
            "events": [
                {"time": now_iso, "stage": "multi_source_intake", "status": "modeled", "notes": "Projected archival-tape and multi-mic inputs from the hashed script; no media was ingested"},
                {"time": now_iso, "stage": "dialogue_cleanup", "status": "modeled", "notes": "Projected a dereverb step; no noise-reduction runtime was invoked"},
                {"time": now_iso, "stage": "ducking_mix", "status": "modeled", "notes": "Projected a -18 dB ducking target; no audio was mixed"},
                {"time": now_iso, "stage": "broadcast_qc", "status": "modeled", "notes": "Projected an EBU R128 target; compliance was not measured"}
            ],
            "created_at": now_iso,
            "updated_at": now_iso,
            "execution_kind": "deterministic_fixture_model",
            "external_runtime_invoked": False,
            "fixture_input_sha256": script_sha,
        }
        return validate_contract("ProductionJob", job)

    @staticmethod
    def map_writers_room_events(
        story_id: str,
        scene_revisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Project fixture revisions into ProductionJob events without invoking Writers Room."""
        if not isinstance(scene_revisions, list) or not scene_revisions:
            raise ValueError("scene_revisions must be a non-empty list")
        if any(not isinstance(revision, dict) for revision in scene_revisions):
            raise ValueError("scene_revisions must contain only objects")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = ProductionHouseEngine.create_job(
            job_id=f"job-wr-{story_id}",
            domain="writers-room-fixture-projection",
            task="project-collaborative-scene-fixtures",
            inputs=[{
                "name": f"{story_id}-manifest.json",
                "type": "writers_room_manifest",
                "sha256": _artifact_digest(scene_revisions),
            }],
        )

        for rev in scene_revisions:
            job = ProductionHouseEngine.advance_job_stage(
                job=job,
                stage_name=f"scene_{rev.get('scene_number', 1)}_revision_{rev.get('revision_id', 'v1')}",
                new_outputs=[{
                    "name": f"scene-{rev.get('scene_number', 1)}-{rev.get('revision_id', 'v1')}.fountain",
                    "author": rev.get("author", "Ryan"),
                    "sha256": _artifact_digest(rev),
                }],
                status="running",
                notes=rev.get("change_summary", "Collaborative draft update"),
            )

        job = ProductionHouseEngine.advance_job_stage(
            job=job,
            stage_name="fixture_assembly_complete",
            new_outputs=[{
                "name": f"{story_id}-final-screenplay.fountain",
                "type": "modeled_production_ready_script",
                "sha256": _artifact_digest({"story_id": story_id, "revisions": scene_revisions}),
            }],
            status="completed",
            notes="Fixture revisions were assembled; no Writers Room signoff or synthesis was performed.",
        )

        return {
            "story_id": story_id,
            "mapped_job": job,
            "reconciliation": "suite_fixture_events_projected_into_production_job",
            "runtime_consolidation": "not_performed",
            "writers_room_runtime_invoked": False,
            "signoff_observed": False,
        }
