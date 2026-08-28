import json
import http.client
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from portfolio_suites.server import create_server
from portfolio_suites.waves import WaveRunResult


class ServerTests(unittest.TestCase):
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

    def _get_json(self, path: str):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path: str):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
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
        self.assertEqual(data["completed_runtime_milestones"], 3)
        self.assertEqual(data["recovery_program"]["discharged"], 2)
        self.assertEqual(data["recovery_program"]["open"], 42)
        self.assertEqual(data["adopted_capabilities"], 1)

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

    def test_document_endpoint_uses_the_explicit_allowlist(self):
        documents = self._get_json("/api/docs")
        self.assertEqual(
            {item["id"] for item in documents},
            {"project-bible", "migration-program", "recovery-standard", "roadmap"},
        )
        bible = self._get_json("/api/docs/project-bible")
        self.assertEqual(bible["name"], "PROJECT-BIBLE.md")
        self.assertIn("# Project Bible", bible["content"])

        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/docs/..%2F.env")
        self.assertEqual(context.exception.code, 404)

    def test_ai_status_endpoint_never_exposes_credentials(self):
        safe_status = {
            "provider": "openrouter",
            "configured": True,
            "credential_source": ".env",
            "free_only": True,
            "roles": {"orchestrator": {"model": "openrouter/free"}},
            "warnings": [],
        }
        with patch("portfolio_suites.server.get_ai_status", return_value=safe_status):
            data = self._get_json("/api/ai/status")
        self.assertTrue(data["configured"])
        self.assertNotIn("api_key", json.dumps(data).lower())

    def test_security_policy_endpoint_is_the_toolbench_redaction_source(self):
        data = self._get_json("/api/security-policy")
        policy = data["argument_redaction"]
        self.assertEqual(policy["flags"], "i")
        self.assertIn("credentials?", policy["pattern"])
        self.assertIn("bearer", policy["pattern"])
        self.assertIn("token", policy["pattern"])
        self.assertIn("REDACTED", policy["redacted_value"])

    def test_ai_assist_endpoint_is_provider_and_review_labelled(self):
        result = {
            "ok": True,
            "mode": "provider_assisted",
            "provider": "openrouter",
            "resolved_model": "vendor/model:free",
            "evidence_type": "model_assisted",
            "human_review_required": True,
            "content": "A safe next move.",
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/ai/assist",
            data=json.dumps({
                "prompt": "Help",
                "suite_id": "operator-os",
                "role": "orchestrator",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with patch("portfolio_suites.server.request_assistance", return_value=result) as assist:
            with urllib.request.urlopen(request) as response:
                data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(data["evidence_type"], "model_assisted")
        self.assertTrue(data["human_review_required"])
        assist.assert_called_once_with(
            "Help",
            suite_id="operator-os",
            role="orchestrator",
            context=None,
            history=None,
        )

    def test_waves_endpoint(self):
        data = self._get_json("/api/waves")
        self.assertEqual(len(data), 43)
        self.assertEqual(sum(1 for row in data if row["execution_kind"] == "verified_analysis"), 40)
        self.assertEqual(sum(1 for row in data if row["execution_kind"] == "verified_runtime_recovery"), 1)
        self.assertEqual(sum(1 for row in data if row["execution_kind"] == "prototype_check"), 0)
        self.assertTrue(all("runner_available" in row for row in data))
        self.assertFalse(any("prototype_passed" in row for row in data))

    def test_wave_post_is_ephemeral_and_classified(self):
        ephemeral = WaveRunResult(
            "model-behavior-lab",
            "M1",
            True,
            "hermetic server dispatch fixture",
            data={"fixture": "server-dispatch"},
            execution_kind="verified_analysis",
            claim_kind="analysis",
            claim_level="source_inspected",
        )
        with patch(
            "portfolio_suites.server.WaveRunner.run_wave",
            return_value=ephemeral,
        ) as run_wave:
            data = self._post_json("/api/waves/model-behavior-lab/M1/run")
            self.assertFalse(data["recorded"])
            self.assertTrue(data["passed"])
            self.assertEqual(data["execution_kind"], "verified_analysis")
            self.assertEqual(data["claim_kind"], "analysis")
            self.assertEqual(data["claim_level"], "source_inspected")
            self.assertIsNone(data["evidence_path"])
            self.assertIsNotNone(data["data"])
            self.assertEqual(data["record_requested"], False)

        run_wave.assert_called_once_with(
            "model-behavior-lab", "M1", write_evidence=False, full=False
        )

    def test_wave_recording_over_http_is_cli_only(self):
        # Recording mutates evidence files, so the web surface refuses it before dispatch
        # even from a trusted loopback client; the CLI `--record` flag is the sole writer.
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/waves/accessibility/A1/run?record=true",
            data=b"",
            method="POST",
        )
        with patch("portfolio_suites.server.WaveRunner.run_wave") as run_wave:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 403)
        self.assertIn("CLI-only", context.exception.read().decode("utf-8"))
        run_wave.assert_not_called()

    def test_unknown_wave_post_returns_not_found(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/waves/missing-suite/X1/run",
            data=b"",
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)

    def test_evidence_endpoint_security_confinement(self):
        # Path escaping outside workspace should return 404
        url = f"http://127.0.0.1:{self.port}/api/evidence?file=../../../../etc/passwd"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 404)

        # Accessing non-evidence root files like .env must return 404
        env_url = f"http://127.0.0.1:{self.port}/api/evidence?file=.env"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(env_url)
        self.assertEqual(ctx.exception.code, 404)

        # Valid relative evidence should return 200
        valid_url = f"http://127.0.0.1:{self.port}/api/evidence?file=accessibility/evidence/A1-WCAG-AUDITOR-PARITY.json"
        data = self._get_json(valid_url[valid_url.find("/api"):])
        self.assertIn("content", data)

    def test_cors_headers_are_not_present(self):
        url = f"http://127.0.0.1:{self.port}/api/summary"
        with urllib.request.urlopen(url) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
            self.assertIsNone(response.headers.get("Access-Control-Allow-Methods"))

    def test_browser_security_headers_cover_api_and_static_assets(self):
        for path in ("/api/summary", "/", "/app.js"):
            with self.subTest(path=path):
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                    self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                    self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                    csp = response.headers["Content-Security-Policy"]
                    self.assertIn("default-src 'self'", csp)
                    self.assertIn("object-src 'none'", csp)
                    self.assertIn("frame-ancestors 'none'", csp)

    def test_validate_post_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/contracts/SourceRecord/validate"
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


class ServerTrustBoundaryTests(unittest.TestCase):
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

    def test_malformed_content_length_is_a_client_error(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.putrequest("POST", "/api/contracts/SourceRecord/validate")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", "not-a-number")
            connection.endheaders()
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
        self.assertEqual(response.status, 400)
        self.assertIn("Content-Length", payload["error"])

    def test_oversized_json_body_is_rejected_before_reading(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.putrequest("POST", "/api/contracts/SourceRecord/validate")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(1_048_577))
            connection.endheaders()
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
        self.assertEqual(response.status, 413)
        self.assertIn("exceeds", payload["error"])

    def test_nonfinite_json_number_is_rejected(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/ai/assist",
            data=b'{"prompt":"Help","suite_id":"operator-os","temperature":NaN}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 400)
        payload = json.loads(context.exception.read().decode("utf-8"))
        self.assertIn("non-finite", payload["error"])

    def test_unhashable_enum_payload_is_a_contract_error(self):
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/api/contracts/ProductionJob/sample"
        ) as response:
            sample = json.loads(response.read().decode("utf-8"))
        sample["status"] = []
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/contracts/ProductionJob/validate",
            data=json.dumps(sample).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 400)
        payload = json.loads(context.exception.read().decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertIn("must be one of", payload["error"])

    def test_cross_origin_donor_scan_reads_are_rejected_before_dispatch(self):
        """Loopback binding does not stop a page the operator merely visits from firing
        these. Each spawns git across every donor checkout; the CORS-blocked response does
        not stop the work from happening."""
        for path, patched in (
            ("/api/drift", "get_live_drift_report"),
            ("/api/validate", "validate_registry"),
        ):
            with self.subTest(path=path):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    headers={
                        "Origin": "https://attacker.example",
                        "Sec-Fetch-Site": "cross-site",
                    },
                )
                with patch(f"portfolio_suites.server.{patched}") as scan:
                    with self.assertRaises(urllib.error.HTTPError) as context:
                        urllib.request.urlopen(request)
                self.assertEqual(context.exception.code, 403)
                scan.assert_not_called()

    def test_manifest_only_reads_stay_open_to_any_origin(self):
        """The refusal is scoped to live donor scans. Reads served from loaded manifests
        cost nothing to run, and gating them would break the dashboard for no benefit."""
        for path in ("/api/summary", "/api/graph", "/api/suites", "/api/validate?fast=true"):
            with self.subTest(path=path):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    headers={
                        "Origin": "https://attacker.example",
                        "Sec-Fetch-Site": "cross-site",
                    },
                )
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 200)

    def test_cross_origin_wave_execution_is_rejected_before_dispatch(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/waves/model-behavior-lab/M1/run",
            data=b"",
            headers={
                "Origin": "https://attacker.example",
                "Sec-Fetch-Site": "cross-site",
            },
            method="POST",
        )
        with patch("portfolio_suites.server.WaveRunner.run_wave") as run_wave:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 403)
        run_wave.assert_not_called()

    def test_cross_origin_engine_execution_is_rejected_before_dispatch(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/engines/operator-os/audit_secrets/run",
            data=json.dumps({"path": "."}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": "https://attacker.example",
                "Sec-Fetch-Site": "cross-site",
            },
            method="POST",
        )
        with patch("portfolio_suites.server.run_action") as run_action:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 403)
        run_action.assert_not_called()

    def test_cross_origin_chain_execution_is_rejected_before_dispatch(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/chains/run",
            data=json.dumps([{"suite": "accessibility", "action": "audit_html_snippet", "arguments": {"html_content": "<p>test</p>"}}]).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": "https://attacker.example",
                "Sec-Fetch-Site": "cross-site",
            },
            method="POST",
        )
        with patch("portfolio_suites.server.run_chain") as run_chain:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 403)
        run_chain.assert_not_called()

    def test_cross_origin_ai_execution_is_rejected_before_dispatch(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/ai/assist",
            data=json.dumps({"prompt": "steal data", "suite_id": "operator-os"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": "https://attacker.example",
                "Sec-Fetch-Site": "cross-site",
            },
            method="POST",
        )
        with patch("portfolio_suites.server.request_assistance") as assist:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 403)
        assist.assert_not_called()

    def test_get_cannot_trigger_live_wave_execution(self):
        with patch("portfolio_suites.server.WaveRunner.run_all") as run_all:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/waves?run=true")
        self.assertEqual(context.exception.code, 405)
        run_all.assert_not_called()

    def test_repeated_route_prefix_is_not_normalized(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/suites//api/suites/accessibility"
            )
        self.assertEqual(context.exception.code, 404)

    def test_non_loopback_host_header_is_refused(self):
        # DNS rebinding: the attacker page resolves its own name to 127.0.0.1, so
        # Sec-Fetch-Site reads same-origin and only the Host header still names the attacker.
        for method, path in (("GET", "/api/summary"), ("POST", "/api/waves/accessibility/A2/run")):
            with self.subTest(method=method):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=b"" if method == "POST" else None,
                    headers={"Host": "evil.example.com"},
                    method=method,
                )
                with patch("portfolio_suites.server.WaveRunner.run_wave") as run_wave:
                    with self.assertRaises(urllib.error.HTTPError) as context:
                        urllib.request.urlopen(request)
                self.assertEqual(context.exception.code, 403)
                run_wave.assert_not_called()


if __name__ == "__main__":
    unittest.main()
