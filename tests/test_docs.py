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
        for tier_name, tier in RECOVERY_TIERS.items():
            target_str = f"{tier['target_score']:.1f}/10"
            self.assertIn(target_str, roadmap, f"roadmap missing target score {target_str} for {tier_name}")

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
