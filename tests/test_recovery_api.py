import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from portfolio_suites.recovery_program import RecoveryProgramError
from portfolio_suites.server import create_server


class RecoveryAPIIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/recovery"

    def test_recovery_endpoint_exposes_validated_dependency_state(self):
        with urllib.request.urlopen(self._url()) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))

        self.assertTrue(data["ok"])
        self.assertEqual(data["program_id"], "portfolio-runtime-recovery-v2")
        self.assertEqual(data["summary"]["obligations"], 44)
        self.assertEqual(data["summary"]["wave_runtime_followups"], 42)
        self.assertEqual(data["summary"]["lifecycle_obligations"], 2)
        self.assertEqual(data["summary"]["states"], {
            "ready": 18,
            "blocked_dependency": 24,
            "discharged": 2,
        })
        obligations = {item["id"]: item for item in data["obligations"]}
        self.assertEqual(
            obligations["accessibility/A2-adoption"]["effective_state"],
            "discharged",
        )
        self.assertEqual(
            obligations["brand-publishing/B3"]["effective_state"],
            "blocked_dependency",
        )
        self.assertEqual(
            obligations["operator-os/O1"]["effective_state"],
            "discharged",
        )
        self.assertEqual(
            obligations["operator-os/O1-adoption"]["owner_gate"],
            "permanent_vault_write",
        )
        self.assertNotIn("api_key", json.dumps(data).lower())

    def test_recovery_endpoint_fails_closed_for_invalid_program(self):
        with patch(
            "portfolio_suites.server.load_recovery_program",
            side_effect=RecoveryProgramError("broken program"),
        ):
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(self._url())

        self.assertEqual(context.exception.code, 500)
        data = json.loads(context.exception.read().decode("utf-8"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "recovery_program_invalid")
        self.assertEqual(data["message"], "broken program")


if __name__ == "__main__":
    unittest.main()
