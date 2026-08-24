import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

from portfolio_suites.engine_actions import (
    argument_redaction_policy,
    redact_sensitive_arguments,
)
from portfolio_suites.server import _is_loopback_host_header


WEB_DIR = Path(__file__).resolve().parents[1] / "src" / "portfolio_suites" / "web"
SERVER_SOURCE = WEB_DIR.parent / "server.py"


class _FormTopologyParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.label_targets: set[str] = set()
        self.controls: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag == "label" and attributes.get("for"):
            self.label_targets.add(attributes["for"])
        if tag in {"input", "select", "textarea"}:
            self.controls.append((tag, attributes.get("id")))


class WebSecurityTests(unittest.TestCase):
    def test_host_header_validator_accepts_only_loopback_authorities(self):
        accepted = ("localhost", "localhost:8383", "127.0.0.1:8383", "[::1]:8383")
        refused = (
            None,
            "",
            "evil.example",
            "evil.example@127.0.0.1",
            "127.0.0.1:99999",
            "127.0.0.1:not-a-port",
            "127.0.0.1/path",
            "127.0.0.1\r\nX-Forwarded-Host: evil.example",
            " localhost",
        )
        for value in accepted:
            with self.subTest(value=value):
                self.assertTrue(_is_loopback_host_header(value))
        for value in refused:
            with self.subTest(value=value):
                self.assertFalse(_is_loopback_host_header(value))

    def test_manifest_rendering_uses_data_actions_not_inline_javascript(self):
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        index_source = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("onclick=", app_source)
        self.assertNotIn("onclick=", index_source)
        self.assertIn('data-app-action="run-wave"', app_source)
        self.assertIn("event.target.closest('[data-app-action]')", app_source)

    def test_drift_dashboard_never_renders_incomplete_fingerprint_as_in_sync(self):
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("untracked_incomplete", app_source)
        self.assertIn("untracked_incomplete_reasons", app_source)
        self.assertIn("FINGERPRINT INCOMPLETE", app_source)

    def test_browser_never_counts_a_prototype_as_a_verified_analysis(self):
        """The CLI keys prototype_count off prototype_passed; the browser must agree."""
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("if (res.passed || res.prototype_passed) {", app_source)
        self.assertIn("if (res.prototype_passed) {", app_source)
        self.assertIn("counts.set('prototype_check'", app_source)
        self.assertIn(
            "PASSED_LABELS[res.prototype_passed ? 'prototype_check' : res.execution_kind]",
            app_source,
        )

    def test_escape_html_behavior_neutralizes_hostile_xss_payloads(self):
        """Execute escapeHtml directly in Node to test behavioral neutralization of injection vectors."""
        if not shutil.which("node"):
            self.skipTest("node runtime unavailable for behavioral web security test")

        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # Extract escapeHtml function definition
        func_body = app_source.split("class SuitesApp")[0]

        test_cases = [
            ('<script>alert("XSS")</script>', "&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;"),
            ('"><img src=x onerror=prompt(1)>', "&quot;&gt;&lt;img src=x onerror=prompt(1)&gt;"),
            ("test 'payload' & <tag>", "test &#039;payload&#039; &amp; &lt;tag&gt;"),
            (None, ""),
            ("", ""),
            (12345, "12345"),
            ("<a href=\"javascript:alert('xss')\">link</a>", "&lt;a href=&quot;javascript:alert(&#039;xss&#039;)&quot;&gt;link&lt;/a&gt;"),
        ]

        js_script = f"""
{func_body}
const cases = {json.dumps([c[0] for c in test_cases])};
const results = cases.map(c => escapeHtml(c));
console.log(JSON.stringify(results));
"""
        proc = subprocess.run(
            ["node", "-e", js_script],
            capture_output=True,
            text=True,
            check=True,
        )
        outputs = json.loads(proc.stdout)
        self.assertEqual(len(outputs), len(test_cases))
        for (input_val, expected), actual in zip(test_cases, outputs):
            with self.subTest(input=input_val):
                self.assertEqual(actual, expected)
                if input_val is not None and "<" in str(input_val):
                    self.assertNotIn("<", actual)
                    self.assertNotIn(">", actual)

    def test_launchpad_has_no_remote_asset_dependency(self):
        index_source = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("fonts.googleapis.com", index_source)
        self.assertNotIn("fonts.gstatic.com", index_source)
        self.assertNotRegex(index_source, r'<(?:script|link)[^>]+(?:src|href)=["\']https?://')

    def test_toolbench_replays_only_transitive_dependencies_and_redacts_secrets(self):
        if not shutil.which("node"):
            self.skipTest("node runtime unavailable for behavioral Toolbench test")

        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        helpers = app_source.split("class SuitesApp")[0]
        policy = argument_redaction_policy()
        redaction_input = {
            "operator_approval_token": "opa1.secret",
            "nested": {
                "api_key": "provider-secret",
                "credential": "credential-value",
                "bearer": "bearer-value",
                "token": "bare-token-value",
                "client_secret": "client-secret-value",
                "clientSecret": "camel-secret-value",
                "dbPassword": "db-password-value",
                "token_budget": 4096,
                "ordinary": "keep-me",
            },
        }
        js_script = f"""
{helpers}
const sensitiveKeyPattern = new RegExp({json.dumps(policy["pattern"])}, {json.dumps(policy["flags"])});
const redactedArgumentValue = {json.dumps(policy["redacted_value"])};
const tray = [
  {{args: {{unrelated: true}}}},
  {{args: {{seed: 1}}}},
  {{args: {{also_unrelated: true}}}},
  {{args: {{source: {{$from: 1, path: 'value'}}}}}}
];
const pending = {{input: {{$from: 3}}}};
const dependencies = collectChainDependencies(pending, tray);
const indexMap = new Map(dependencies.map((original, rebased) => [original, rebased]));
const rebasedDependency = rebaseChainReferences(tray[3].args, indexMap);
const rebasedPending = rebaseChainReferences(pending, indexMap);
const redacted = redactSensitiveArguments(
  {json.dumps(redaction_input)},
  sensitiveKeyPattern,
  redactedArgumentValue
);
let invalidRefused = false;
try {{ collectChainDependencies({{input: {{$from: 99}}}}, tray); }} catch {{ invalidRefused = true; }}
console.log(JSON.stringify({{
  dependencies,
  rebasedDependency,
  rebasedPending,
  redacted,
  invalidRefused,
  containsRedacted: containsRedactedArgument(redacted, redactedArgumentValue)
}}));
"""
        proc = subprocess.run(
            ["node", "-e", js_script],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["dependencies"], [1, 3])
        self.assertEqual(result["rebasedDependency"], {"source": {"$from": 0, "path": "value"}})
        self.assertEqual(result["rebasedPending"], {"input": {"$from": 1}})
        self.assertEqual(result["redacted"], redact_sensitive_arguments(redaction_input))
        self.assertEqual(result["redacted"]["nested"]["ordinary"], "keep-me")
        self.assertEqual(result["redacted"]["nested"]["token_budget"], 4096)
        for secret in (
            "opa1.secret",
            "provider-secret",
            "credential-value",
            "bearer-value",
            "bare-token-value",
            "client-secret-value",
            "camel-secret-value",
            "db-password-value",
        ):
            self.assertNotIn(secret, json.dumps(result))
        self.assertTrue(result["invalidRefused"])
        self.assertTrue(result["containsRedacted"])
        self.assertNotIn("const SENSITIVE_ARGUMENT_KEY", app_source)
        self.assertNotIn("const REDACTED_ARGUMENT", app_source)
        self.assertIn("fetch('/api/security-policy')", app_source)

    def test_every_text_entry_and_selector_has_an_explicit_label(self):
        parser = _FormTopologyParser()
        parser.feed((WEB_DIR / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(parser.controls)
        for tag, control_id in parser.controls:
            with self.subTest(tag=tag, control_id=control_id):
                self.assertIsNotNone(control_id)
                self.assertIn(control_id, parser.ids)
                self.assertIn(control_id, parser.label_targets)

    def test_evidence_viewer_is_a_keyboard_managed_modal(self):
        index_source = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('role="dialog"', index_source)
        self.assertIn('aria-modal="true"', index_source)
        self.assertIn('aria-labelledby="evidence-modal-title"', index_source)
        self.assertIn("event.key === 'Escape'", app_source)
        self.assertIn("this.modalLastFocus", app_source)
        self.assertIn("focusable", app_source)

    def test_ai_output_is_text_only_and_review_labelled(self):
        index_source = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("Free OpenRouter Assistant", index_source)
        self.assertIn("human review", index_source.lower())
        self.assertIn("answer.textContent = result.content", app_source)
        self.assertNotIn("answer.innerHTML = result.content", app_source)
        self.assertIn("credential stays server-side", index_source)

    def test_wave_ui_is_ephemeral_and_uses_current_manifest_count(self):
        index_source = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("all 43 deterministic checks", index_source)
        self.assertNotIn("all 24 waves", index_source)
        self.assertNotIn("Run & Record All Waves", index_source)
        self.assertIn("No evidence was recorded", app_source)
        self.assertIn("const totalChecks = this.state.waves.length", app_source)
        self.assertIn("environmentBlockedCount", app_source)

    def test_loopback_server_declares_browser_security_headers_and_doc_allowlist(self):
        server_source = SERVER_SOURCE.read_text(encoding="utf-8")
        for header in (
            "Content-Security-Policy",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Permissions-Policy",
            "Referrer-Policy",
        ):
            self.assertIn(header, server_source)
        self.assertIn('"project-bible": SUITES_ROOT / "docs" / "PROJECT-BIBLE.md"', server_source)
        self.assertIn('path.startswith("/api/docs/")', server_source)
        self.assertIn('path == "/api/security-policy"', server_source)
        self.assertIn("argument_redaction_policy()", server_source)
        self.assertIn('"arguments": redact_sensitive_arguments(arguments)', server_source)

    def test_toolbench_reports_the_chain_error_step_index(self):
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("body.step_index ?? body.step", app_source)


if __name__ == "__main__":
    unittest.main()
