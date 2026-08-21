import json
import threading
import unittest
import urllib.error
import urllib.request

from portfolio_suites.server import create_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(port=8399)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get_json(self, path: str):
        url = f"http://127.0.0.1:8399{path}"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path: str):
        req = urllib.request.Request(
            f"http://127.0.0.1:8399{path}",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def test_summary_endpoint(self):
        data = self._get_json("/api/summary")
        self.assertEqual(data["total_projects"], 70)
        self.assertEqual(len(data["suites"]), 8)
        self.assertEqual(data["recovery_target_score"], 9.0)
        self.assertEqual(data["recovered_runtime_behaviors"], 1)

    def test_suites_endpoint(self):
        data = self._get_json("/api/suites")
        self.assertEqual(len(data), 8)

    def test_projects_endpoint(self):
        data = self._get_json("/api/projects")
        self.assertEqual(len(data), 70)

    def test_contracts_endpoint(self):
        data = self._get_json("/api/contracts")
        self.assertIn("A11yFinding", data)
        self.assertIn("SourceRecord", data)

    def test_contract_sample_endpoint(self):
        data = self._get_json("/api/contracts/A11yFinding/sample")
        self.assertEqual(data["schema_version"], "1.0.0")

    def test_waves_endpoint(self):
        data = self._get_json("/api/waves")
        self.assertEqual(len(data), 43)
        self.assertEqual(sum(1 for row in data if row["execution_kind"] == "verified_analysis"), 16)
        self.assertEqual(sum(1 for row in data if row["execution_kind"] == "verified_runtime_recovery"), 1)
        self.assertEqual(sum(1 for row in data if row["execution_kind"] == "prototype_check"), 26)
        self.assertTrue(all("prototype_passed" in row for row in data))

    def test_wave_post_is_ephemeral_and_classified(self):
        data = self._post_json("/api/waves/production-house/P1/run")
        self.assertFalse(data["recorded"])
        self.assertFalse(data["passed"])
        self.assertTrue(data["prototype_passed"])
        self.assertEqual(data["execution_kind"], "prototype_check")
        self.assertIsNone(data["evidence_path"])
        self.assertIsNotNone(data["data"])

    def test_unknown_wave_post_returns_not_found(self):
        req = urllib.request.Request(
            "http://127.0.0.1:8399/api/waves/missing-suite/X1/run",
            data=b"",
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)

    def test_evidence_endpoint_security_confinement(self):
        # Path escaping outside workspace should return 404
        url = "http://127.0.0.1:8399/api/evidence?file=../../../../etc/passwd"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 404)

        # Accessing non-evidence root files like .env must return 404
        env_url = "http://127.0.0.1:8399/api/evidence?file=.env"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(env_url)
        self.assertEqual(ctx.exception.code, 404)

        # Valid relative evidence should return 200
        valid_url = "http://127.0.0.1:8399/api/evidence?file=accessibility/evidence/A1-WCAG-AUDITOR-PARITY.md"
        data = self._get_json(valid_url[valid_url.find("/api"):])
        self.assertIn("content", data)

    def test_cors_headers_are_not_present(self):
        url = "http://127.0.0.1:8399/api/summary"
        with urllib.request.urlopen(url) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
            self.assertIsNone(response.headers.get("Access-Control-Allow-Methods"))

    def test_validate_post_endpoint(self):
        url = "http://127.0.0.1:8399/api/contracts/SourceRecord/validate"
        sample = self._get_json("/api/contracts/SourceRecord/sample")
        req = urllib.request.Request(
            url,
            data=json.dumps(sample).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            res = json.loads(response.read().decode("utf-8"))
            self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()
