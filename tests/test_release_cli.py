import io
import unittest
from contextlib import redirect_stdout

from portfolio_suites.cli import main


class ReleaseCLIIntegrationTests(unittest.TestCase):
    def test_release_blockers_lists_open_and_held(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["release", "blockers"])

        self.assertEqual(code, 2)
        rendered = output.getvalue()
        self.assertIn("4 open release blocker(s):", rendered)
        self.assertIn("phase0.release-ledger (actionable)", rendered)
        self.assertIn("phase1.contract-state-freeze (actionable)", rendered)
        self.assertIn("phase1.stable-surface (actionable)", rendered)
        self.assertIn("brand-publishing.v1.b1-runtime (held)", rendered)
        self.assertIn("owes obligations: brand-publishing/B1", rendered)
        self.assertIn("Open criteria: 14, suites under score target: 8.", rendered)
        self.assertIn("Release ready: no (criteria or score deficits remain)", rendered)

    def test_release_summary_reports_counts(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["release", "summary"])

        self.assertEqual(code, 2)
        rendered = output.getvalue()
        self.assertIn("8 suites", rendered)
        self.assertIn("14 criteria (0 closed, 14 open)", rendered)
        self.assertIn("4 open, 3 actionable", rendered)
        self.assertIn("Zero release blockers: no", rendered)

    @staticmethod
    def _fake_summary(**overrides):
        summary = {
            "ledger_id": "portfolio-release-completion-v1",
            "suites": 8,
            "criteria_total": 14,
            "criteria_open": 0,
            "criteria_closed": 14,
            "open_blockers": 0,
            "actionable_blockers": 0,
            "suites_under_score_target": 0,
            "release_phases": {"supported": 8},
            "closure_outcomes": {},
            "has_no_blockers": True,
        }
        summary.update(overrides)
        summary["release_ready"] = (
            summary["has_no_blockers"] and summary["suites_under_score_target"] == 0
        )
        return summary

    def _run_summary(self, summary):
        from unittest.mock import patch

        output = io.StringIO()
        with patch(
            "portfolio_suites.cli.release_state_summary", return_value=summary
        ), redirect_stdout(output):
            code = main(["release", "summary"])
        return code, output.getvalue()

    def test_release_summary_zero_blockers_and_scores_met_returns_ok(self):
        code, rendered = self._run_summary(self._fake_summary())

        self.assertEqual(code, 0)
        self.assertIn("Suites at tier score target: 8/8", rendered)
        self.assertIn("Zero release blockers: yes", rendered)
        self.assertIn("Release ready: yes", rendered)

    def test_release_summary_zero_blockers_but_sub_target_scores_is_not_ready(self):
        """Zero blockers alone must not report release-ready: a suite short of its tier
        score target is still an open v1 claim."""
        code, rendered = self._run_summary(
            self._fake_summary(suites_under_score_target=3)
        )

        self.assertEqual(code, 2)
        self.assertIn("Suites at tier score target: 5/8", rendered)
        self.assertIn("Zero release blockers: yes", rendered)
        self.assertIn("Release ready: no", rendered)

    def test_release_blockers_empty_queue_but_not_ready_is_incomplete(self):
        """An empty blocker queue must not report the portfolio satisfies its release
        ledger while criteria or score deficits remain -- the blockers exit mirrors the
        full release_ready truth, not just the absence of an explicit queue."""
        from unittest.mock import patch

        empty_state = {
            "open_blockers": [],
            "open_blocker_count": 0,
            "actionable_blockers": [],
        }
        sub_target_summary = self._fake_summary(criteria_open=14, suites_under_score_target=8)
        output = io.StringIO()
        with patch(
            "portfolio_suites.cli.resolve_release_state", return_value=empty_state
        ), patch(
            "portfolio_suites.cli.release_state_summary", return_value=sub_target_summary
        ), redirect_stdout(output):
            code = main(["release", "blockers"])

        self.assertEqual(code, 2)
        rendered = output.getvalue()
        self.assertIn("No open release blockers.", rendered)
        self.assertIn("Release ready: no", rendered)


if __name__ == "__main__":
    unittest.main()
