"""Source adapter for Production House Suite connecting production-house, elevenlabs-screenplay-formatter, and writers-room."""

from __future__ import annotations

from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256
from ..engines.production_house import ProductionHouseEngine
from .common import get_git_fingerprint, get_repo_path, is_meaningful_git_fingerprint

PRODUCTION_HOUSE_DIR = get_repo_path("production-house", "PRODUCTION_HOUSE_DIR")
FORMATTER_DIR = get_repo_path("elevenlabs-screenplay-formatter", "FORMATTER_DIR")
WRITERS_ROOM_DIR = get_repo_path("writers-room", "WRITERS_ROOM_DIR")
GROUNDWIRE_DIR = get_repo_path("production-house_audio-plays--ambient-horror", "GROUNDWIRE_DIR")


class ProductionHouseSourceAdapter:
    """Fingerprint Production House donors and build explicit suite-local fixture projections."""

    @classmethod
    def execute_p1_groundwire_fingerprint(cls) -> dict[str, Any]:
        """P1: Record donor fingerprints and project a Groundwire fixture into ProductionJob."""
        prod_fp = get_git_fingerprint(PRODUCTION_HOUSE_DIR)
        gw_fp = get_git_fingerprint(GROUNDWIRE_DIR)
        fmt_fp = get_git_fingerprint(FORMATTER_DIR)

        script_sha = compute_sha256(b"SCENE 1: EXT. DESOLATE RADIO TOWER - NIGHT\nThe wind howls through the lattice steel.")
        job = ProductionHouseEngine.build_groundwire_pipeline_job("episode-12-ambient-horror", script_sha)
        sources_verified = all(
            is_meaningful_git_fingerprint(fingerprint)
            for fingerprint in (prod_fp, gw_fp, fmt_fp)
        )

        all_stages_passed = (
            sources_verified
            and job.get("status") == "completed"
            and len(job.get("outputs", [])) == 3
            and job.get("external_runtime_invoked") is False
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P1",
            "status": (
                "source_fingerprints_with_fixture_projection_verified"
                if all_stages_passed
                else "source_unverified"
            ),
            "job": job,
            "production_house_fingerprint": prod_fp,
            "groundwire_fingerprint": gw_fp,
            "formatter_fingerprint": fmt_fp,
            "source_verification_passed": sources_verified,
            "episode_artifacts_read": False,
            "external_runtime_invoked": False,
            "fixture_output_only": True,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_p2_formatter_job(cls) -> dict[str, Any]:
        """P2: Project an episode fixture into ProductionJob against a formatter fingerprint."""
        fmt_fp = get_git_fingerprint(FORMATTER_DIR)
        job = ProductionHouseEngine.create_job(
            "job-gw-ep12-formatter",
            "groundwire-formatter-fixture-projection",
            "project-formatter-output-fixture",
            [{"name": "script.fountain", "type": "script", "sha256": compute_sha256(b"fountain script content")}],
        )
        job = ProductionHouseEngine.advance_job_stage(
            job,
            "formatter_fixture_preparation",
            status="running",
            notes="Prepared deterministic formatter adapter fixture; external formatter not invoked",
        )
        job = ProductionHouseEngine.advance_job_stage(
            job,
            "fixture_output_projection",
            [{"name": "stems.zip", "type": "audio_stems", "sha256": compute_sha256(b"stems zip archive")}],
            status="completed",
            notes="Projected a deterministic fixture artifact; no ElevenLabs synthesis was performed",
        )
        job["execution_kind"] = "deterministic_fixture_projection"
        job["external_runtime_invoked"] = False
        job["fixture_output_only"] = True
        source_verified = is_meaningful_git_fingerprint(fmt_fp)
        all_stages_passed = (
            source_verified
            and job.get("status") == "completed"
            and len(job.get("outputs", [])) >= 1
            and job.get("external_runtime_invoked") is not True
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P2",
            "status": "fixture_output_projection_verified" if all_stages_passed else "source_unverified",
            "job": job,
            "formatter_fingerprint": fmt_fp,
            "source_verification_passed": source_verified,
            "external_formatter_invoked": False,
            "fixture_output_only": True,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_p3_writers_room_handoff(cls) -> dict[str, Any]:
        """P3: Project a handoff fixture into ProductionJob against a Writers Room fingerprint."""
        wr_fp = get_git_fingerprint(WRITERS_ROOM_DIR)
        job = ProductionHouseEngine.create_job(
            job_id="job-gw-ep12-handoff",
            domain="writers-room-handoff-fixture-projection",
            task="validate-fixture-story-state-shape",
            inputs=[{
                "name": "arc-season-2.fountain",
                "version": "1.2.0",
                "status": "fixture_input_not_observed_signoff",
                "sha256": compute_sha256(b"writers-room handoff fixture"),
            }],
        )
        job["execution_kind"] = "deterministic_fixture_projection"
        job["external_runtime_invoked"] = False
        job["signoff_observed"] = False
        source_verified = is_meaningful_git_fingerprint(wr_fp)
        passed = source_verified and job.get("status") == "queued" and len(job.get("inputs", [])) == 1
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P3",
            "status": "fixture_handoff_projection_verified" if passed else "source_unverified",
            "job": job,
            "writers_room_fingerprint": wr_fp,
            "source_verification_passed": source_verified,
            "writers_room_runtime_invoked": False,
            "signoff_observed": False,
            "all_stages_passed": passed,
        }

    @classmethod
    def execute_p4_documentary_pipeline(cls) -> dict[str, Any]:
        """P4: Run structural episode variant (investigative documentary) through generic engine."""
        doc_sha = compute_sha256(b"INVESTIGATIVE REPORT: Shadow Grid Power Outage Analysis")
        job = ProductionHouseEngine.build_investigative_documentary_job("episode-14-shadow-grid", doc_sha)
        passed = job.get("status") == "completed" and len(job.get("outputs", [])) == 3
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P4",
            "status": "documentary_fixture_model_verified" if passed else "fixture_model_failed",
            "job": job,
            "external_runtime_invoked": False,
            "fixture_output_only": True,
            "all_stages_passed": passed,
        }

    @classmethod
    def execute_p5_writers_room_event_stream(cls) -> dict[str, Any]:
        """P5: Map Writers Room collaborative story revisions into canonical ProductionJob event stream."""
        scene_revs = [
            {"scene_number": 1, "revision_id": "rev-1", "author": "Ryan", "change_summary": "Initial intro dialogue"},
            {"scene_number": 2, "revision_id": "rev-2", "author": "Ryan", "change_summary": "Added ambient sound cue"},
        ]
        mapping = ProductionHouseEngine.map_writers_room_events("arc-season-3", scene_revs)
        passed = mapping.get("mapped_job", {}).get("status") == "completed"
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P5",
            "status": "fixture_event_projection_verified" if passed else "fixture_projection_failed",
            "mapping": mapping,
            "writers_room_runtime_invoked": False,
            "runtime_consolidation_performed": False,
            "all_stages_passed": passed,
        }
