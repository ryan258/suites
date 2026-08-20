import unittest

from portfolio_suites.waves import WaveRunner


class WaveTests(unittest.TestCase):
    def test_run_all_waves(self):
        results = WaveRunner.run_all(write_evidence=False)
        self.assertEqual(len(results), 24)
        for r in results:
            self.assertTrue(r.passed, f"Wave {r.suite_id}/{r.wave_id} failed: {r.message}")

    def test_run_individual_waves(self):
        a2 = WaveRunner.run_wave("accessibility", "A2", write_evidence=False)
        self.assertTrue(a2.passed)

        o1 = WaveRunner.run_wave("operator-os", "O1", write_evidence=False)
        self.assertTrue(o1.passed)

        b1 = WaveRunner.run_wave("brand-publishing", "B1", write_evidence=False)
        self.assertTrue(b1.passed)

        p1 = WaveRunner.run_wave("production-house", "P1", write_evidence=False)
        self.assertTrue(p1.passed)

        m1 = WaveRunner.run_wave("model-behavior-lab", "M1", write_evidence=False)
        self.assertTrue(m1.passed)

        d2 = WaveRunner.run_wave("discovery-decision", "D2", write_evidence=False)
        self.assertTrue(d2.passed)

        r1 = WaveRunner.run_wave("agent-reliability", "R1", write_evidence=False)
        self.assertTrue(r1.passed)

        g1 = WaveRunner.run_wave("game-design", "G1", write_evidence=False)
        self.assertTrue(g1.passed)


if __name__ == "__main__":
    unittest.main()
