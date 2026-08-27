import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


class ArtifactTests(unittest.TestCase):
    def test_json_artifacts_parse(self):
        for path in ROOT.rglob("*.json"):
            with self.subTest(path=path.relative_to(ROOT)):
                json.loads(path.read_text(encoding="utf-8"))

    def test_local_markdown_links_resolve(self):
        failures = []
        for path in ROOT.rglob("*.md"):
            for target in LINK.findall(path.read_text(encoding="utf-8")):
                target = target.split("#", 1)[0].strip()
                if not target or "://" in target or target.startswith("/"):
                    continue
                if not (path.parent / target).resolve().exists():
                    failures.append(f"{path.relative_to(ROOT)} -> {target}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_roadmap_matches_machine_state(self):
        """The roadmap restates numbers the registry already knows; keep the two from drifting apart."""
        from portfolio_suites.contracts import CONTRACTS
        from portfolio_suites.registry import get_portfolio_summary, load_suites

        roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
        summary = get_portfolio_summary()

        contract_line = next(line for line in roadmap.splitlines() if "Shared contracts implemented" in line)
        self.assertEqual(
            sorted(name for name in CONTRACTS if name in contract_line),
            sorted(CONTRACTS),
            f"roadmap contract list is stale: {contract_line}",
        )
        queue = {}
        for line in roadmap.splitlines():
            if not line.startswith("|") or "---" in line or "Verified" in line:
                continue
            m = re.search(
                r"\|\s*([A-Za-z0-9 +]+?)\s*\|\s*(\d+)/(\d+)\s*\|\s*(?:`([A-Z]\d+)`|(\w+))\s*\|\s*(?:.*?(\d+)\s*runtime follow-ups? remain.*?)?\|",
                line,
            )
            if m:
                completed_count = int(m.group(2))
                total_count = int(m.group(3))
                target = m.group(4) if m.group(4) else None
                followups = int(m.group(6)) if m.group(6) is not None else None
                s_name = m.group(1).lower().replace("+", "").split()[0]
                for s_id, s_manifest in load_suites().items():
                    if s_id.startswith(s_name) or s_manifest["name"].lower().startswith(s_name):
                        prefix = s_manifest["waves"][0]["id"][0]
                        queue[prefix] = (completed_count, total_count, target, followups)
        for suite_id, manifest in load_suites().items():
            waves = manifest.get("waves", [])
            completed = sum(1 for w in waves if w.get("status") == "complete")
            upcoming = next((w["id"] for w in waves if w.get("status") != "complete"), None)
            followup_count = sum(1 for w in waves if w.get("runtime_followup"))
            with self.subTest(suite=suite_id):
                self.assertEqual(
                    queue.get(waves[0]["id"][0]),
                    (completed, len(waves), upcoming, followup_count),
                    f"ROADMAP promotion queue row for {suite_id} is stale",
                )

        from portfolio_suites.recovery_policy import RECOVERY_TIERS

        tier_rows = {}
        for line in roadmap.splitlines():
            if not line.startswith("|") or "---" in line:
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != 3:
                continue
            tier_ids = [
                tier_id for tier_id in re.findall(r"`([^`]+)`", cells[0])
                if tier_id in RECOVERY_TIERS
            ]
            if len(tier_ids) != 1:
                continue
            score = re.fullmatch(r"(\d+(?:\.\d+)?)/10", cells[2])
            self.assertIsNotNone(score, f"roadmap recovery tier has an invalid score: {line}")
            tier_rows[tier_ids[0]] = {
                "suites": re.findall(r"`([^`]+)`", cells[1]),
                "target_score": float(score.group(1)),
            }

        expected_tiers = {
            tier_name: {
                "suites": tier["suites"],
                "target_score": float(tier["target_score"]),
            }
            for tier_name, tier in RECOVERY_TIERS.items()
        }
        self.assertEqual(
            tier_rows,
            expected_tiers,
            "roadmap recovery tier, suite membership, or score mapping is stale",
        )

        for token in (
            f"{len(CONTRACTS)} Shared contracts",
            f"{summary['completed_waves']}/{summary['total_waves']}",
            f"{summary['total_waves']} Migration wave specifications",
            f"{summary['total_projects']} Top-level projects",
            # The promotion axis, read off `recovery_claim.level` rather than inferred from
            # incompleteness. Deriving prototypes as `total - completed` is what let 35
            # prototype-level claims be reported as zero while every wave was complete.
            f"{summary['promotion_counts']['prototype']}/{summary['total_waves']} prototype-level claims",
            f"{summary['promotion_counts']['reviewed_historical_analysis']}/{summary['total_waves']} reviewed historical analysis",
            f"{summary['promotion_counts']['source_inspected']}/{summary['total_waves']} source-inspected claims",
            f"{summary['promotion_counts']['source_executed']}/{summary['total_waves']} source-executed claims",
            f"{summary['promotion_counts']['parity_verified']}/{summary['total_waves']} parity-verified runtime recoveries",
            f"{summary['waves_owing_runtime_followup']}/{summary['total_waves']} completed waves still owe a live run",
        ):
            self.assertIn(token, roadmap, f"roadmap does not state current {token!r}")

    def test_readme_states_both_axes_not_only_milestone_progress(self):
        """The README kickstart block restates the same counts; drift there is a reporting defect."""
        from portfolio_suites.engine_actions import list_actions
        from portfolio_suites.registry import get_portfolio_summary

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        summary = get_portfolio_summary()
        levels = summary["promotion_counts"]
        total_actions = sum(len(c["actions"]) for c in list_actions().values())
        # Both halves of the split, not `completed_waves` relabelled: 43 completed waves are
        # 42 analysis milestones plus one runtime wave, and calling all 43 "analysis
        # milestones" is the same overstatement the promotion axis exists to prevent.
        self.assertIn(
            f"WORK STATE: {summary['completed_waves']}/{summary['total_waves']} waves complete "
            f"({summary['completed_analysis_milestones']} analysis milestones "
            f"+ {summary['recovered_runtime_behaviors']} runtime wave)",
            readme,
        )
        self.assertIn(
            f"EVIDENCE PROMOTION: {levels['prototype']} prototype "
            f"| {levels['reviewed_historical_analysis']} reviewed historical "
            f"| {levels['source_inspected']} source inspected "
            f"| {levels['source_executed']} source executed",
            readme,
        )
        self.assertIn(
            f"{levels['parity_verified']} parity verified | {levels['adopted']} adopted "
            f"| {levels['converged']} converged | {summary['resolved_capabilities']} resolved",
            readme,
        )
        self.assertIn(
            f"OUTSTANDING: {summary['waves_owing_runtime_followup']}/{summary['total_waves']} "
            "completed waves still owe a live run",
            readme,
        )
        self.assertIn(f"{summary['total_projects']} Projects Dispositioned", readme)
        self.assertIn(f"list all {total_actions} actions", readme)

    def test_changelog_matches_machine_state(self):
        """The changelog summary block restates current milestone counts and evidence; check against the registry."""
        from portfolio_suites.registry import get_portfolio_summary, load_suites

        changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
        summary = get_portfolio_summary()

        completed = summary["completed_waves"]
        total = summary["total_waves"]
        heading = f"### Verified Wave Milestones Completed ({completed}/{total})"
        self.assertIn(
            heading,
            changelog,
            f"CHANGELOG summary heading does not match registry completed wave count ({completed}/{total})",
        )

        summary_block = changelog.split("### Verified Wave Milestones Completed", 1)[1].split("\n---", 1)[0]

        suites = load_suites()
        for suite_id, manifest in suites.items():
            for wave in manifest.get("waves", []):
                if wave.get("status") == "complete":
                    wave_id = wave["id"]
                    self.assertIn(
                        f"`{wave_id}`",
                        summary_block,
                        f"CHANGELOG summary block missing entry for completed wave {suite_id}/{wave_id}",
                    )
                    evidence_rel = wave.get("evidence")
                    if evidence_rel:
                        self.assertIn(
                            evidence_rel,
                            summary_block,
                            f"CHANGELOG summary block does not link to correct evidence path for {suite_id}/{wave_id}: {evidence_rel}",
                        )


    def test_suite_readmes_track_registry_state(self):
        """Each suite README restates its own verified count and next wave; a promotion drifts both."""
        from portfolio_suites.registry import load_suites

        for suite_id, manifest in load_suites().items():
            waves = manifest.get("waves", [])
            completed = sum(1 for w in waves if w.get("status") == "complete")
            readme = (ROOT / suite_id / "README.md").read_text(encoding="utf-8")
            with self.subTest(suite=suite_id):
                self.assertIn(
                    f"({completed}/{len(waves)})",
                    readme,
                    f"{suite_id}/README.md does not state its current verified count {completed}/{len(waves)}",
                )
                upcoming = next((w for w in waves if w.get("status") != "complete"), None)
                if upcoming:
                    self.assertIn(
                        f"Next wave: {upcoming['id']}",
                        readme,
                        f"{suite_id}/README.md names the wrong next wave; registry says {upcoming['id']}",
                    )


class WaveDemoTaxonomyTests(unittest.TestCase):
    def test_wave_all_demo_counts_match_registry_and_runner_classification(self):
        """Demo 58/59 counts are projections of the registry, not hand-maintained folklore."""
        from portfolio_suites.registry import load_suites
        from portfolio_suites.waves import classify_wave_spec

        demos = (ROOT / "docs" / "100-demos.md").read_text(encoding="utf-8")
        taxonomy_demos = demos.split("### 58.", 1)[1].split("### 60.", 1)[0]
        normalized_demos = " ".join(taxonomy_demos.split())
        classified = [
            (classify_wave_spec(wave), (wave.get("recovery_claim") or {}).get("level"))
            for manifest in load_suites().values()
            for wave in manifest.get("waves", [])
        ]

        prototypes = sum(level == "prototype" for _, level in classified)
        historical = sum(level == "reviewed_historical_analysis" for _, level in classified)
        inspected = sum(level == "source_inspected" for _, level in classified)
        source_runs = sum(kind == "verified_source_execution" for kind, _ in classified)
        verified_analyses = sum(
            kind == "verified_analysis" and level != "prototype"
            for kind, level in classified
        )
        runtime_slots = sum(kind == "verified_runtime_recovery" for kind, _ in classified)

        self.assertEqual(runtime_slots, 1, "demo wording assumes one depth-dependent runtime slot")
        self.assertIn(
            f"{verified_analyses} verified analyses, {source_runs} source execution, and "
            f"{prototypes} prototype checks passed",
            normalized_demos,
        )
        for displayed_count in (
            f"{prototypes} [PROTOTYPE]",
            f"{inspected} [INSPECTED]",
            f"{historical} [HISTORICAL]",
            f"{source_runs} [SOURCE-RUN]",
            f"{runtime_slots} [FAST-PROBE]",
            f"{runtime_slots} [UNVERIFIABLE]",
        ):
            self.assertIn(
                displayed_count,
                taxonomy_demos,
                f"wave demo taxonomy is stale: {displayed_count}",
            )


class DocumentedCommandTests(unittest.TestCase):
    """The README teaches the CLI. A command it teaches has to exist.

    Removing `ai-config` deleted the module, its tests and its guide, but left the
    README still telling the reader to run it. Nothing caught that: the link checker
    only sees markdown links, and no test read the usage block.
    """

    SUBPARSER = re.compile(r'sub\.add_parser\(\s*"([a-z][a-z0-9-]*)"')
    INVOCATION = re.compile(r"python3 -m portfolio_suites ([a-z][a-z0-9-]*)")

    def test_every_command_the_readme_teaches_is_a_real_subcommand(self):
        available = set(
            self.SUBPARSER.findall((ROOT / "src" / "portfolio_suites" / "cli.py").read_text(encoding="utf-8"))
        )
        self.assertIn("validate", available, "subcommand discovery found nothing; the regex is stale")

        doc_paths = [ROOT / "README.md", ROOT / "SKILL.md", ROOT / "AGENTS.md"] + [
            p for p in (ROOT / "docs").glob("*.md")
            if not p.name.startswith("PORTFOLIO-REVIEW-")
        ]
        for path in doc_paths:
            with self.subTest(doc=path.name):
                documented = set(self.INVOCATION.findall(path.read_text(encoding="utf-8")))
                self.assertEqual(
                    documented - available,
                    set(),
                    f"{path.name} documents commands the CLI does not define",
                )


if __name__ == "__main__":
    unittest.main()


class CITestCoverageTests(unittest.TestCase):
    """Every test module must be a deliberate CI decision, not an oversight.

    The hermetic PR job names its modules one by one, so adding a test file runs it
    locally and nowhere else until somebody remembers to edit the workflow. That is how
    `tests.test_integrity_boundaries` -- which needs no donor checkout -- ended up
    unrun on every pull request. A module that genuinely needs the provisioned donor
    portfolio belongs in DONOR_DEPENDENT, where the exclusion is visible and reviewed;
    the manual `portfolio-integration` job runs the full `discover` and covers those.
    """

    # Verified by running each module against a checkout with no donor siblings and a
    # scratch HOME: these are the ones that cannot pass without the real portfolio.
    DONOR_DEPENDENT = frozenset({
        "test_accessibility_adapter",
        "test_ai",
        "test_cli",
        "test_engines",
        "test_flagship_semantic_guards",
        "test_operator_o1_runtime_candidate",
        "test_registry",
        "test_source_waves",
        "test_wave_recording_hardening",
        "test_waves",
        "test_wheel_smoke",  # self-skips unless SUITES_WHEEL_SMOKE=1, which only that job sets
    })

    def test_hermetic_job_runs_every_module_that_does_not_need_donors(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        listed = set(re.findall(r"tests\.(test_\w+)", workflow))
        on_disk = {p.stem for p in (ROOT / "tests").glob("test_*.py")}

        stale = sorted(self.DONOR_DEPENDENT - on_disk)
        self.assertEqual(stale, [], "DONOR_DEPENDENT names modules that no longer exist")

        missing = sorted(on_disk - self.DONOR_DEPENDENT - listed)
        self.assertEqual(
            missing, [],
            "these modules need no donors but the hermetic CI job never runs them; "
            "add them to .github/workflows/ci.yml or to DONOR_DEPENDENT",
        )

    def test_the_integration_job_still_runs_everything(self):
        """The donor-dependent exclusions are only safe while some job runs discover."""
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("unittest discover -s tests", workflow)
