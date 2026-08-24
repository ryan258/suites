"""Source adapter for Production House Suite connecting production-house, elevenlabs-screenplay-formatter, and writers-room."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION, compute_sha256
from ..engines.production_house import ProductionHouseEngine
from .common import (
    donor_file_record,
    first_existing_donor_file,
    get_git_fingerprint,
    get_repo_path,
    is_meaningful_git_fingerprint,
    read_donor_text,
)

PRODUCTION_HOUSE_DIR = get_repo_path("production-house", "PRODUCTION_HOUSE_DIR")
FORMATTER_DIR = get_repo_path("elevenlabs-screenplay-formatter", "FORMATTER_DIR")
WRITERS_ROOM_DIR = get_repo_path("writers-room", "WRITERS_ROOM_DIR")
GROUNDWIRE_DIR = get_repo_path("production-house_audio-plays--ambient-horror", "GROUNDWIRE_DIR")

GROUNDWIRE_TRACKED = ["config.toml", "voices.json", "README.md", "MANUAL.md"]
FORMATTER_TRACKED = ["EXAMPLE_FOUNTAIN.md", "README.md", "ARCHITECTURE.md", "pyproject.toml"]
WRITERS_ROOM_TRACKED = ["PIPELINE.md", "README.md", "main.py", "pyproject.toml"]
PRODUCTION_HOUSE_TRACKED = ["README.md", "pyproject.toml", "docs/DOMAIN_TEMPLATES.md"]


def _episode_script(slug_prefix: str | None = None) -> tuple[Path, str, dict[str, Any]] | None:
    """Return a real Groundwire episode script, its text, and a suite-local parse."""
    episodes = GROUNDWIRE_DIR / "episodes"
    if not episodes.is_dir():
        return None
    try:
        dirs = sorted(path for path in episodes.iterdir() if path.is_dir() and not path.name.startswith("."))
    except OSError:
        return None
    if slug_prefix:
        dirs = [path for path in dirs if path.name.startswith(slug_prefix)] + [
            path for path in dirs if path.name.startswith(slug_prefix) is False
        ]
    for episode in dirs:
        script = first_existing_donor_file(episode, ["script.md", "script_draft.md", "script.fountain"])
        if script is None:
            continue
        text = read_donor_text(script)
        if not text:
            continue
        parsed = ProductionHouseEngine.parse_episode_script(
            text, source_name=f"episodes/{episode.name}/{script.name}"
        )
        if parsed.get("word_count", 0) < 40:
            continue
        return script, text, parsed
    return None


def _formatter_play() -> tuple[Path, str, dict[str, Any]] | None:
    play = first_existing_donor_file(
        FORMATTER_DIR,
        ["plays/the-echo.md", "plays/the-signal.md", "EXAMPLE_FOUNTAIN.md", "EXAMPLE_SCREENPLAY.md"],
    )
    if play is None:
        return None
    text = read_donor_text(play)
    if not text:
        return None
    try:
        relative = str(play.relative_to(FORMATTER_DIR)).replace("\\", "/")
    except ValueError:
        relative = play.name
    parsed = ProductionHouseEngine.parse_episode_script(text, source_name=relative)
    return play, text, parsed


def _writers_room_handoff() -> dict[str, Any] | None:
    path = first_existing_donor_file(
        WRITERS_ROOM_DIR,
        [
            "final/260409_the-desert-ridge-herald-a-mockumentary_final.md",
            "final/260409_the-lake-house_final.md",
            "PIPELINE.md",
        ],
    )
    if path is None:
        return None
    record = donor_file_record(path, WRITERS_ROOM_DIR)
    text = read_donor_text(path)
    if record is None or not text:
        return None
    parsed = ProductionHouseEngine.parse_episode_script(text, source_name=record["path"])
    return {"record": record, "parsed": parsed, "text": text}


def _writers_room_revisions() -> list[dict[str, Any]]:
    pipelines = WRITERS_ROOM_DIR / "pipelines"
    revisions: list[dict[str, Any]] = []
    try:
        dirs = sorted(path for path in pipelines.iterdir() if path.is_dir() and not path.name.startswith("."))
    except OSError:
        return []
    for index, pipeline in enumerate(dirs, start=1):
        status = first_existing_donor_file(pipeline, ["status.md", "index.md"])
        if status is None:
            continue
        record = donor_file_record(status, WRITERS_ROOM_DIR)
        text = read_donor_text(status)
        if record is None or not text:
            continue
        heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), pipeline.name)
        revisions.append({
            "scene_number": index,
            "revision_id": pipeline.name[:48],
            "author": "writers-room-donor",
            "change_summary": heading[:200],
            "source_path": record["path"],
            "sha256": record["sha256"],
        })
        if len(revisions) >= 4:
            break
    return revisions


class ProductionHouseSourceAdapter:
    """Inspect Production House donors and project hashed artifacts into ProductionJob."""

    @classmethod
    def execute_p1_groundwire_fingerprint(cls) -> dict[str, Any]:
        """P1: Parse a real Groundwire episode script and project it into ProductionJob."""
        prod_fp = get_git_fingerprint(PRODUCTION_HOUSE_DIR, PRODUCTION_HOUSE_TRACKED)
        gw_fp = get_git_fingerprint(GROUNDWIRE_DIR, GROUNDWIRE_TRACKED)
        fmt_fp = get_git_fingerprint(FORMATTER_DIR, FORMATTER_TRACKED)
        selected = _episode_script("0000_")
        if selected is None:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "P1",
                "status": "source_unverified",
                "source_verification_passed": False,
                "episode_artifacts_read": False,
                "external_runtime_invoked": False,
                "fixture_output_only": True,
                "all_stages_passed": False,
            }
        _script, _text, parsed = selected
        slug = Path(parsed["source_name"]).parts[1] if "/" in parsed["source_name"] else "groundwire-episode"
        job = ProductionHouseEngine.build_groundwire_pipeline_job(slug, parsed["sha256"])
        sources_verified = all(
            is_meaningful_git_fingerprint(fingerprint)
            for fingerprint in (prod_fp, gw_fp, fmt_fp)
        )
        all_stages_passed = (
            sources_verified
            and parsed.get("character_count", 0) >= 1
            and job.get("status") == "completed"
            and job.get("inputs", [{}])[0].get("sha256") == parsed["sha256"]
            and len(job.get("outputs", [])) == 3
            and job.get("external_runtime_invoked") is False
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P1",
            "status": "source_episode_script_projected" if all_stages_passed else "source_unverified",
            "job": job,
            "script": parsed,
            "production_house_fingerprint": prod_fp,
            "groundwire_fingerprint": gw_fp,
            "formatter_fingerprint": fmt_fp,
            "source_verification_passed": sources_verified,
            "episode_artifacts_read": True,
            "external_runtime_invoked": False,
            "fixture_output_only": True,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_p2_formatter_job(cls) -> dict[str, Any]:
        """P2: Hash a real formatter play and project it into ProductionJob without invoking the formatter."""
        fmt_fp = get_git_fingerprint(FORMATTER_DIR, FORMATTER_TRACKED)
        selected = _formatter_play()
        if selected is None or not is_meaningful_git_fingerprint(fmt_fp):
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "P2",
                "status": "source_unverified",
                "formatter_fingerprint": fmt_fp,
                "source_verification_passed": False,
                "external_formatter_invoked": False,
                "fixture_output_only": True,
                "all_stages_passed": False,
            }
        play, _text, parsed = selected
        job = ProductionHouseEngine.create_job(
            "job-gw-formatter-play",
            "groundwire-formatter-source-projection",
            "project-hashed-formatter-play",
            [{"name": parsed["source_name"], "type": "script", "sha256": parsed["sha256"]}],
        )
        job = ProductionHouseEngine.advance_job_stage(
            job,
            "formatter_source_intake",
            status="running",
            notes=f"Hashed {parsed['source_name']}; external formatter not invoked",
        )
        job = ProductionHouseEngine.advance_job_stage(
            job,
            "formatter_output_projection",
            [{"name": f"{play.stem}-stems.zip", "type": "audio_stems", "sha256": compute_sha256(parsed["sha256"].encode("utf-8"))}],
            status="completed",
            notes="Projected a content-addressed output from the hashed play; no ElevenLabs synthesis was performed",
        )
        job["execution_kind"] = "source_script_projection"
        job["external_runtime_invoked"] = False
        job["fixture_output_only"] = True
        all_stages_passed = (
            job.get("status") == "completed"
            and job.get("inputs", [{}])[0].get("sha256") == parsed["sha256"]
            and parsed.get("word_count", 0) >= 40
            and job.get("external_runtime_invoked") is not True
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P2",
            "status": "source_play_projected" if all_stages_passed else "source_unverified",
            "job": job,
            "script": parsed,
            "formatter_fingerprint": fmt_fp,
            "source_verification_passed": True,
            "external_formatter_invoked": False,
            "fixture_output_only": True,
            "all_stages_passed": all_stages_passed,
        }

    @classmethod
    def execute_p3_writers_room_handoff(cls) -> dict[str, Any]:
        """P3: Project a real Writers Room final into ProductionJob without invoking that runtime."""
        wr_fp = get_git_fingerprint(WRITERS_ROOM_DIR, WRITERS_ROOM_TRACKED)
        handoff = _writers_room_handoff()
        if handoff is None or not is_meaningful_git_fingerprint(wr_fp):
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "P3",
                "status": "source_unverified",
                "writers_room_fingerprint": wr_fp,
                "source_verification_passed": False,
                "writers_room_runtime_invoked": False,
                "signoff_observed": False,
                "all_stages_passed": False,
            }
        record = handoff["record"]
        parsed = handoff["parsed"]
        job = ProductionHouseEngine.create_job(
            job_id="job-wr-handoff-source",
            domain="writers-room-handoff-source-projection",
            task="validate-hashed-story-state-shape",
            inputs=[{
                "name": record["path"],
                "version": "source",
                "status": "source_input_signoff_not_observed",
                "sha256": record["sha256"],
            }],
        )
        job["execution_kind"] = "source_script_projection"
        job["external_runtime_invoked"] = False
        job["signoff_observed"] = False
        passed = (
            job.get("status") == "queued"
            and job.get("inputs", [{}])[0].get("sha256") == record["sha256"]
            and parsed.get("word_count", 0) >= 40
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P3",
            "status": "source_handoff_projected" if passed else "source_unverified",
            "job": job,
            "script": parsed,
            "writers_room_fingerprint": wr_fp,
            "source_verification_passed": True,
            "writers_room_runtime_invoked": False,
            "signoff_observed": False,
            "all_stages_passed": passed,
        }

    @classmethod
    def execute_p4_documentary_pipeline(cls) -> dict[str, Any]:
        """P4: Project a structurally distinct Groundwire episode plus production-house domain docs."""
        prod_fp = get_git_fingerprint(PRODUCTION_HOUSE_DIR, PRODUCTION_HOUSE_TRACKED)
        gw_fp = get_git_fingerprint(GROUNDWIRE_DIR, GROUNDWIRE_TRACKED)
        selected = _episode_script("0016_")
        domain = donor_file_record(PRODUCTION_HOUSE_DIR / "docs" / "DOMAIN_TEMPLATES.md", PRODUCTION_HOUSE_DIR)
        if selected is None or domain is None:
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "P4",
                "status": "source_unverified",
                "external_runtime_invoked": False,
                "fixture_output_only": True,
                "all_stages_passed": False,
            }
        _script, _text, parsed = selected
        slug = Path(parsed["source_name"]).parts[1] if "/" in parsed["source_name"] else "documentary-episode"
        job = ProductionHouseEngine.build_investigative_documentary_job(slug, parsed["sha256"])
        sources_verified = all(is_meaningful_git_fingerprint(fp) for fp in (prod_fp, gw_fp))
        passed = (
            sources_verified
            and job.get("status") == "completed"
            and len(job.get("outputs", [])) == 3
            and job.get("inputs", [{}])[0].get("sha256") == parsed["sha256"]
            and job.get("external_runtime_invoked") is False
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P4",
            "status": "source_documentary_script_projected" if passed else "source_unverified",
            "job": job,
            "script": parsed,
            "domain_template": domain,
            "production_house_fingerprint": prod_fp,
            "groundwire_fingerprint": gw_fp,
            "external_runtime_invoked": False,
            "fixture_output_only": True,
            "all_stages_passed": passed,
        }

    @classmethod
    def execute_p5_writers_room_event_stream(cls) -> dict[str, Any]:
        """P5: Map real Writers Room pipeline status files into a ProductionJob event stream."""
        wr_fp = get_git_fingerprint(WRITERS_ROOM_DIR, WRITERS_ROOM_TRACKED)
        revisions = _writers_room_revisions()
        if len(revisions) < 2 or not is_meaningful_git_fingerprint(wr_fp):
            return {
                "schema_version": SCHEMA_VERSION,
                "wave": "P5",
                "status": "source_unverified",
                "writers_room_fingerprint": wr_fp,
                "writers_room_runtime_invoked": False,
                "runtime_consolidation_performed": False,
                "all_stages_passed": False,
            }
        mapping = ProductionHouseEngine.map_writers_room_events("writers-room-pipelines", revisions)
        passed = mapping.get("mapped_job", {}).get("status") == "completed"
        mapping["source_revision_count"] = len(revisions)
        mapping["source_paths"] = [item["source_path"] for item in revisions]
        return {
            "schema_version": SCHEMA_VERSION,
            "wave": "P5",
            "status": "source_event_stream_projected" if passed else "source_unverified",
            "mapping": mapping,
            "writers_room_fingerprint": wr_fp,
            "writers_room_runtime_invoked": False,
            "runtime_consolidation_performed": False,
            "all_stages_passed": passed,
        }
