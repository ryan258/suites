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
        prototypes = summary["total_waves"] - summary["completed_waves"]
        queue = {
            m.group(3)[0]: (int(m.group(1)), int(m.group(2)), m.group(3))
            for m in (
                re.search(r"\|\s*(\d+)/(\d+)\s*\|\s*`(\w+)`", line)
                for line in roadmap.splitlines()
                if line.startswith("|")
            )
            if m
        }
        for suite_id, manifest in load_suites().items():
            waves = manifest.get("waves", [])
            completed = sum(1 for w in waves if w.get("status") == "complete")
            upcoming = next((w["id"] for w in waves if w.get("status") != "complete"), None)
            with self.subTest(suite=suite_id):
                self.assertEqual(
                    queue.get(waves[0]["id"][0]),
                    (completed, len(waves), upcoming),
                    f"ROADMAP promotion queue row for {suite_id} is stale",
                )

        for token in (
            f"{len(CONTRACTS)} Shared contracts",
            f"{summary['completed_waves']}/{summary['total_waves']}",
            f"{summary['total_waves']} Migration wave specifications",
            f"{summary['total_projects']} Top-level projects",
            f"{prototypes}/{summary['total_waves']} source-backed prototype checks",
        ):
            self.assertIn(token, roadmap, f"roadmap does not state current {token!r}")

    def test_readme_states_the_current_prototype_count(self):
        """The README kickstart block restates the same counts; drift there is a reporting defect."""
        from portfolio_suites.engine_actions import list_actions
        from portfolio_suites.registry import get_portfolio_summary

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        summary = get_portfolio_summary()
        prototypes = summary["total_waves"] - summary["completed_waves"]
        total_actions = sum(len(c["actions"]) for c in list_actions().values())
        self.assertIn(f"PROTOTYPES: {prototypes} source-backed checks passing", readme)
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


if __name__ == "__main__":
    unittest.main()
