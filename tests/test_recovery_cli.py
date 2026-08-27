import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from portfolio_suites.cli import main
from portfolio_suites.recovery_program import RecoveryProgramError


class RecoveryCLIIntegrationTests(unittest.TestCase):
    def test_next_uses_dependency_aware_recovery_program(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["next"])

        self.assertEqual(code, 0)
        rendered = output.getvalue()
        self.assertIn(
            "Recovery program: 44 obligations (42 wave follow-ups + 2 lifecycle).",
            rendered,
        )
        self.assertIn(
            "Dependency state: 18 ready, 24 blocked by undischarged dependencies.",
            rendered,
        )
        self.assertIn(
            "NEXT RECOVERY OBLIGATION: brand-publishing/B1",
            rendered,
        )
        self.assertIn(
            "state: dependency-ready; environment and owner availability not inferred",
            rendered,
        )
        self.assertIn("receipt: portfolio-runtime-parity-v1", rendered)
        # The adoption contract surfaces in the dependency-ready queue rows.
        self.assertIn("portfolio-adoption-v1", rendered)
        # O1 is discharged, so the queue names its adoption follow-on and not O1 itself.
        self.assertIn("operator-os/O1-adoption", rendered)
        self.assertNotIn("operator-os/O1  ", rendered)
        self.assertIn("owner=permanent_vault_write", rendered)
        self.assertNotIn("lowest promotion first", rendered)

    def test_next_fails_closed_when_recovery_program_cannot_load(self):
        output = io.StringIO()
        with patch(
            "portfolio_suites.cli.load_recovery_program",
            side_effect=RecoveryProgramError("broken program"),
        ), redirect_stdout(output):
            code = main(["next"])

        self.assertEqual(code, 1)
        self.assertIn(
            "ERROR recovery program is invalid: broken program",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
