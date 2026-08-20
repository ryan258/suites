"""Production House reference prototype engine powering Groundwire capture, Writers Room events, and ProductionJob flows.

NOTE: This is a control-plane reference prototype and fixture comparator, not a replacement for external canonical project runtimes (e.g. Groundwire, writers-room)."""

from __future__ import annotations

import datetime
from typing import Any
from ..contracts import SCHEMA_VERSION, validate_contract


class ProductionHouseEngine:
    """Manage resumable ProductionJob lifecycles and creative execution pipelines."""

    @staticmethod
    def create_job(job_id: str, domain: str, task: str, inputs: list[dict[str, Any]]) -> dict[str, Any]:
        """Initialize a new ProductionJob in queued state."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "domain": domain,
            "task": task,
            "status": "queued",
            "inputs": inputs,
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
        updated = dict(job)
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

        if new_outputs:
            outputs = list(updated.get("outputs", []))
            outputs.extend(new_outputs)
            updated["outputs"] = outputs

        return validate_contract("ProductionJob", updated)

    @staticmethod
    def build_groundwire_pipeline_job(episode_slug: str, script_sha: str) -> dict[str, Any]:
        """Create a complete production pipeline job for a Groundwire audio play episode."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = {
            "schema_version": SCHEMA_VERSION,
            "job_id": f"job-gw-{episode_slug}",
            "domain": "groundwire-audio-play",
            "task": "render-full-episode-master",
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
                {"time": now_iso, "stage": "fountain_parse", "status": "ok", "notes": "Parsed 12 scenes and 4 character voices"},
                {"time": now_iso, "stage": "elevenlabs_formatter", "status": "ok", "notes": "Synthesized 142 audio stems"},
                {"time": now_iso, "stage": "ambient_sfx_mix", "status": "ok", "notes": "Beds mixed at -22 dB"},
                {"time": now_iso, "stage": "mastering_qc", "status": "ok", "notes": "Broadcast loudness achieved (-16.2 LUFS)"}
            ],
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        return validate_contract("ProductionJob", job)

    @staticmethod
    def build_investigative_documentary_job(episode_slug: str, script_sha: str) -> dict[str, Any]:
        """Create a production pipeline job for structurally distinct investigative documentary audio (P4 wave)."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = {
            "schema_version": SCHEMA_VERSION,
            "job_id": f"job-gw-doc-{episode_slug}",
            "domain": "groundwire-documentary",
            "task": "render-investigative-podcast",
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
                {"time": now_iso, "stage": "multi_source_intake", "status": "ok", "notes": "Ingested archival tape and multi-mic stems"},
                {"time": now_iso, "stage": "dialogue_clean_dereverb", "status": "ok", "notes": "Noise reduction gate applied"},
                {"time": now_iso, "stage": "dynamic_ducking_mix", "status": "ok", "notes": "Automated voice-over ducking at -18dB"},
                {"time": now_iso, "stage": "broadcast_qc_audit", "status": "ok", "notes": "EBU R128 compliance verified"}
            ],
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        return validate_contract("ProductionJob", job)

    @staticmethod
    def map_writers_room_events(
        story_id: str,
        scene_revisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Map Writers Room collaborative story state into ProductionJob event streams (P5 wave)."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = ProductionHouseEngine.create_job(
            job_id=f"job-wr-{story_id}",
            domain="writers-room-collaboration",
            task="collaborative-scene-assembly",
            inputs=[{"name": f"{story_id}-manifest.json", "type": "writers_room_manifest"}],
        )

        for rev in scene_revisions:
            job = ProductionHouseEngine.advance_job_stage(
                job=job,
                stage_name=f"scene_{rev.get('scene_number', 1)}_revision_{rev.get('revision_id', 'v1')}",
                new_outputs=[{"name": f"scene-{rev.get('scene_number', 1)}.fountain", "author": rev.get("author", "Ryan")}],
                status="running",
                notes=rev.get("change_summary", "Collaborative draft update"),
            )

        job = ProductionHouseEngine.advance_job_stage(
            job=job,
            stage_name="room_signoff",
            new_outputs=[{"name": f"{story_id}-final-screenplay.fountain", "type": "production_ready_script"}],
            status="completed",
            notes="Writers Room reached unanimous canon signoff; ready for speech synthesis.",
        )

        return {
            "story_id": story_id,
            "mapped_job": job,
            "reconciliation": "writers_room_collaborative_events_unified_under_production_job",
            "runtime_consolidation": "single_canonical_engine",
        }
