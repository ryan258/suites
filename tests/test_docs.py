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
        from portfolio_suites.registry import get_portfolio_summary

        roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
        summary = get_portfolio_summary()

        contract_line = next(line for line in roadmap.splitlines() if "Shared contracts implemented" in line)
        self.assertEqual(
            sorted(name for name in CONTRACTS if name in contract_line),
            sorted(CONTRACTS),
            f"roadmap contract list is stale: {contract_line}",
        )
        prototypes = summary["total_waves"] - summary["completed_waves"]
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


if __name__ == "__main__":
    unittest.main()
