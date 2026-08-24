"""Free-only OpenRouter configuration, transport, and evidence-boundary tests."""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from portfolio_suites.ai import (
    AIConfigurationError,
    AIInputError,
    AIProviderError,
    OPENROUTER_FREE_MODEL,
    _NoRedirectHandler,
    OpenRouterClient,
    OpenRouterConfig,
)
from portfolio_suites.cli import EXIT_INCOMPLETE, EXIT_OK, main


class OpenRouterConfigurationTests(unittest.TestCase):
    def test_legacy_auto_models_are_safely_overridden_by_free_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "OPENROUTER_API_KEY=local-secret\n"
                "OPENROUTER_DEFAULT_MODEL=openrouter/auto\n"
                "OPENROUTER_ROLE_REVIEWER_MODEL=paid/example\n",
                encoding="utf-8",
            )
            config = OpenRouterConfig.from_environment(root=root, environ={})

        self.assertTrue(config.configured)
        self.assertTrue(config.free_only)
        self.assertEqual(config.roles["reviewer"].model, OPENROUTER_FREE_MODEL)
        self.assertTrue(config.warnings)
        status = config.public_status()
        self.assertNotIn("local-secret", json.dumps(status))
        self.assertNotIn("local-secret", repr(config))

    def test_environment_wins_and_explicit_free_variant_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("OPENROUTER_API_KEY=file-key\n", encoding="utf-8")
            config = OpenRouterConfig.from_environment(
                root=root,
                environ={
                    "OPENROUTER_API_KEY": "process-key",
                    "OPENROUTER_DEFAULT_MODEL": "vendor/model:free",
                },
            )
        self.assertEqual(config.credential_source, "environment")
        self.assertEqual(config.roles["analyst"].model, "vendor/model:free")

    def test_empty_environment_value_falls_back_to_dotenv_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("OPENROUTER_API_KEY=file-key\n", encoding="utf-8")
            for empty_value in ("", "   "):
                with self.subTest(empty_value=empty_value):
                    config = OpenRouterConfig.from_environment(
                        root=root,
                        environ={"OPENROUTER_API_KEY": empty_value},
                    )
                    self.assertTrue(config.configured)
                    self.assertEqual(config.api_key, "file-key")
                    self.assertEqual(config.credential_source, ".env")

    def test_quoted_dotenv_values_preserve_unicode_and_literal_backslashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = (
                ("Café Studio — Ryan", "Café Studio — Ryan"),
                (r"a\xZZ", r"a\xZZ"),
            )
            for configured, expected in cases:
                with self.subTest(configured=configured):
                    (root / ".env").write_text(
                        "OPENROUTER_API_KEY=file-key\n"
                        f'OPENROUTER_APP_TITLE="{configured}"\n',
                        encoding="utf-8",
                    )
                    config = OpenRouterConfig.from_environment(root=root, environ={})
                    self.assertEqual(config.app_title, expected)

    def test_env_file_is_data_not_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "must-not-exist"
            (root / ".env").write_text(
                f"OPENROUTER_API_KEY=$(touch {marker})\n",
                encoding="utf-8",
            )
            config = OpenRouterConfig.from_environment(root=root, environ={})
            self.assertTrue(config.configured)
            self.assertFalse(marker.exists())

    def test_invalid_remote_http_base_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AIConfigurationError):
                OpenRouterConfig.from_environment(
                    root=Path(tmp),
                    environ={"OPENROUTER_BASE_URL": "http://provider.example/api/v1"},
                )

    def test_exported_key_cannot_be_redirected_by_a_checkout_local_base_url(self):
        """The confirmed exfiltration path: process-owned key, checkout-owned destination."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "OPENROUTER_BASE_URL=https://attacker.example/api/v1\n",
                encoding="utf-8",
            )
            with self.assertRaises(AIConfigurationError) as context:
                OpenRouterConfig.from_environment(
                    root=root,
                    environ={"OPENROUTER_API_KEY": "operator-exported-secret"},
                )
            self.assertIn("attacker.example", str(context.exception))

    def test_custom_endpoint_opt_in_uses_its_own_credential_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = {
                "OPENROUTER_API_KEY": "operator-exported-secret",
                "OPENROUTER_BASE_URL": "https://compatible.example/api/v1",
                "OPENROUTER_ALLOW_CUSTOM_ENDPOINT": "true",
            }
            # Opted in, but with no separately named credential the OpenRouter key still
            # does not travel: absence is "not configured", never a fallback.
            config = OpenRouterConfig.from_environment(root=Path(tmp), environ=environ)
            self.assertFalse(config.configured)
            self.assertNotEqual(config.api_key, "operator-exported-secret")

            environ["OPENROUTER_CUSTOM_ENDPOINT_API_KEY"] = "endpoint-owned-secret"
            config = OpenRouterConfig.from_environment(root=Path(tmp), environ=environ)
            self.assertEqual(config.api_key, "endpoint-owned-secret")
            self.assertTrue(
                any("compatible.example" in w for w in config.warnings),
                f"a nonstandard credential destination must be visible: {config.warnings}",
            )

    def test_exported_custom_credential_cannot_be_aimed_by_a_checkout(self):
        """One generic custom credential just moves the redirectable secret.

        The destination, the opt-in, and the credential are each resolved independently, so
        an exported `OPENROUTER_CUSTOM_ENDPOINT_API_KEY` meant for one endpoint was still
        sent wherever a checkout-local `.env` pointed. A process-sourced credential now
        requires a process-sourced destination and opt-in.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "OPENROUTER_BASE_URL=https://attacker.example/api/v1\n"
                "OPENROUTER_ALLOW_CUSTOM_ENDPOINT=true\n",
                encoding="utf-8",
            )
            with self.assertRaises(AIConfigurationError) as context:
                OpenRouterConfig.from_environment(
                    root=root,
                    environ={"OPENROUTER_CUSTOM_ENDPOINT_API_KEY": "endpoint-owned-secret"},
                )
            self.assertIn("attacker.example", str(context.exception))

            # A checkout that supplies all three is still free to use its own credential.
            (root / ".env").write_text(
                "OPENROUTER_BASE_URL=https://compatible.example/api/v1\n"
                "OPENROUTER_ALLOW_CUSTOM_ENDPOINT=true\n"
                "OPENROUTER_CUSTOM_ENDPOINT_API_KEY=checkout-owned-secret\n",
                encoding="utf-8",
            )
            config = OpenRouterConfig.from_environment(root=root, environ={})
            self.assertEqual(config.api_key, "checkout-owned-secret")

    def test_status_names_the_host_that_actually_receives_the_request(self):
        """The consent surface has to agree with the credential pin.

        `provider` was the constant "openrouter" no matter where the request went, so an
        operator could opt a custom endpoint in and send sensitive context to it while every
        status line, receipt, and browser label still named OpenRouter.
        """
        with tempfile.TemporaryDirectory() as tmp:
            official = OpenRouterConfig.from_environment(
                root=Path(tmp), environ={"OPENROUTER_API_KEY": "official-secret"}
            ).public_status()
            self.assertEqual(official["provider"], "openrouter")
            self.assertTrue(official["provider_is_openrouter"])
            self.assertEqual(official["destination_host"], "openrouter.ai")

            custom = OpenRouterConfig.from_environment(
                root=Path(tmp),
                environ={
                    "OPENROUTER_BASE_URL": "https://compatible.example/api/v1",
                    "OPENROUTER_ALLOW_CUSTOM_ENDPOINT": "true",
                    "OPENROUTER_CUSTOM_ENDPOINT_API_KEY": "endpoint-owned-secret",
                },
            ).public_status()
            self.assertEqual(custom["provider"], "custom:compatible.example")
            self.assertFalse(custom["provider_is_openrouter"])
            self.assertEqual(custom["destination_host"], "compatible.example")
            self.assertNotIn("endpoint-owned-secret", json.dumps(custom))

    def test_app_url_cannot_embed_credentials_or_tracking_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in (
                "https://user:password@example.test",
                "https://example.test/?token=secret",
                "https://example.test/#fragment",
            ):
                with self.subTest(value=value), self.assertRaises(AIConfigurationError):
                    OpenRouterConfig.from_environment(
                        root=Path(tmp),
                        environ={"OPENROUTER_APP_URL": value},
                    )

    def test_request_header_configuration_rejects_control_characters(self):
        cases = (
            {"OPENROUTER_API_KEY": "key\nInjected: yes"},
            {"OPENROUTER_APP_TITLE": "title\r\nX-Injected: yes"},
            {"OPENROUTER_APP_URL": "https://example.test/\nX-Injected: yes"},
            {"OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1\nX-Injected: yes"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            for environment in cases:
                with self.subTest(environment=environment), self.assertRaises(AIConfigurationError):
                    OpenRouterConfig.from_environment(root=Path(tmp), environ=environment)

    def test_default_transport_refuses_redirects(self):
        handler = _NoRedirectHandler()
        self.assertIsNone(
            handler.redirect_request(
                None,
                None,
                302,
                "Found",
                {},
                "https://attacker.example/collect",
            )
        )


class OpenRouterClientTests(unittest.TestCase):
    def _config(self, **environment: str) -> OpenRouterConfig:
        defaults = {
            # A loopback test transport is a custom endpoint like any other, so it carries the
            # opt-in and its own credential name rather than borrowing OPENROUTER_API_KEY.
            "OPENROUTER_CUSTOM_ENDPOINT_API_KEY": "test-secret",
            "OPENROUTER_ALLOW_CUSTOM_ENDPOINT": "true",
            "OPENROUTER_BASE_URL": "http://127.0.0.1:9999/api/v1",
            "OPENROUTER_DEFAULT_MODEL": OPENROUTER_FREE_MODEL,
        }
        defaults.update(environment)
        with tempfile.TemporaryDirectory() as tmp:
            return OpenRouterConfig.from_environment(root=Path(tmp), environ=defaults)

    def test_request_and_response_are_free_labelled_and_review_bound(self):
        captured = {}

        def transport(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return 200, {"X-Request-Id": "edge-1"}, json.dumps({
                "id": "gen-1",
                "model": "vendor/resolved:free",
                "choices": [{
                    "message": {"role": "assistant", "content": "A bounded next move."},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14, "secret": 1},
            }).encode("utf-8")

        result = OpenRouterClient(self._config(), transport=transport).complete(
            "What should I do next?",
            suite_id="operator-os",
            role="orchestrator",
            context={"bandwidth": "reduced"},
        )

        self.assertEqual(captured["url"], "http://127.0.0.1:9999/api/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], OPENROUTER_FREE_MODEL)
        self.assertEqual(captured["payload"]["stream"], False)
        self.assertIn("Bearer test-secret", captured["headers"].values())
        self.assertIn("untrusted data", captured["payload"]["messages"][-2]["content"])
        self.assertEqual(result["resolved_model"], "vendor/resolved:free")
        self.assertEqual(result["content"], "A bounded next move.")
        self.assertEqual(result["evidence_type"], "model_assisted")
        self.assertTrue(result["human_review_required"])
        self.assertNotIn("secret", result["usage"])
        # Routing policy and observed cost are different facts and travel separately.
        self.assertTrue(result["free_only_requested"])
        self.assertEqual(
            result["zero_cost_confirmed"], "unknown",
            "no provider cost was reported, so zero cost must not be claimed",
        )

    def test_a_paid_completion_is_rejected_under_free_only_policy(self):
        """Ryan's probe: the provider resolves a paid model and reports a positive cost,
        while the client kept claiming `free_only: true`. Under the strict policy that
        response is refused instead of being presented as free-route output."""

        def transport(request, timeout):
            return 200, {}, json.dumps({
                "model": "provider/paid-model",
                "choices": [{
                    "message": {"role": "assistant", "content": "billed output"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14, "cost": 1.25},
            }).encode("utf-8")

        with self.assertRaises(AIProviderError) as context:
            OpenRouterClient(self._config(), transport=transport).complete(
                "Help",
                suite_id="operator-os",
            )
        self.assertEqual(context.exception.code, "paid_model_on_free_route")
        self.assertFalse(context.exception.retryable)

    def test_zero_reported_cost_is_confirmed_and_positive_cost_flagged(self):
        def make_transport(cost):
            usage = {"cost": cost} if cost is not None else {}
            return lambda request, timeout: (
                200,
                {},
                json.dumps({
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": usage,
                }).encode("utf-8"),
            )

        result_free = OpenRouterClient(self._config(), transport=make_transport(0)).complete(
            "Help", suite_id="operator-os"
        )
        self.assertTrue(result_free["zero_cost_confirmed"])
        with self.assertRaises(AIProviderError):
            OpenRouterClient(self._config(), transport=make_transport(0.01)).complete(
                "Help", suite_id="operator-os"
            )

    def test_structured_text_parts_are_joined(self):
        def transport(request, timeout):
            return 200, {}, json.dumps({
                "choices": [{"message": {"content": [
                    {"type": "text", "text": "First"},
                    {"type": "text", "text": "Second"},
                ]}}],
            }).encode("utf-8")

        result = OpenRouterClient(self._config(), transport=transport).complete(
            "Draft",
            suite_id="brand-publishing",
            role="creative",
        )
        self.assertEqual(result["content"], "First\nSecond")

    def test_missing_key_fails_without_fabricating_output(self):
        config = self._config(OPENROUTER_CUSTOM_ENDPOINT_API_KEY="")
        with self.assertRaises(AIConfigurationError) as context:
            OpenRouterClient(config).complete("Help", suite_id="accessibility")
        self.assertEqual(context.exception.code, "not_configured")

    def test_unknown_suite_role_and_oversized_prompt_are_rejected(self):
        client = OpenRouterClient(self._config(), transport=lambda *_: self.fail("transport called"))
        for kwargs in (
            {"suite_id": "missing"},
            {"suite_id": "accessibility", "role": "wizard"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(AIInputError):
                client.complete("Help", **kwargs)
        with self.assertRaises(AIInputError):
            client.complete("x" * 50_001, suite_id="accessibility")
        with self.assertRaises(AIInputError):
            client.complete(
                "Review",
                suite_id="accessibility",
                context={"score": float("nan")},
            )

    def test_likely_credentials_are_refused_before_transport(self):
        client = OpenRouterClient(self._config(), transport=lambda *_: self.fail("transport called"))
        cases = (
            {"prompt": "OPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnopqrstuvwxyz", "context": None},
            {"prompt": "Review this", "context": "-----BEGIN OPENSSH PRIVATE KEY-----"},
            {"prompt": "Review this", "context": "ghp_abcdefghijklmnopqrstuvwxyz1234567890"},
            # `_` is a word character, so `\bAPI_KEY` never matched inside the newly
            # documented variable: a user could paste the exact `.env` line and send it.
            {"prompt": "OPENROUTER_CUSTOM_ENDPOINT_API_KEY=endpoint-owned-secret", "context": None},
            {
                "prompt": "Review this",
                "context": "OPENROUTER_CUSTOM_ENDPOINT_API_KEY=endpoint-owned-secret",
            },
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(AIInputError):
                client.complete(
                    case["prompt"],
                    suite_id="operator-os",
                    context=case["context"],
                )
        with self.assertRaises(AIInputError):
            client.complete(
                "Review this",
                suite_id="operator-os",
                history=[
                    {
                        "role": "user",
                        "content": "OPENROUTER_CUSTOM_ENDPOINT_API_KEY=endpoint-owned-secret",
                    }
                ],
            )

    def test_http_rate_limit_is_classified_and_key_is_not_leaked(self):
        secret = "very-secret-key"

        def transport(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {},
                _BytesReader(json.dumps({"error": {"message": f"limit for Bearer {secret}"}}).encode()),
            )

        client = OpenRouterClient(
            self._config(OPENROUTER_CUSTOM_ENDPOINT_API_KEY=secret),
            transport=transport,
        )
        with self.assertRaises(AIProviderError) as context:
            client.complete("Help", suite_id="agent-reliability")
        self.assertEqual(context.exception.code, "rate_limited")
        self.assertTrue(context.exception.retryable)
        self.assertNotIn(secret, str(context.exception))

    def test_provider_error_cannot_echo_raw_configured_key(self):
        secret = "raw-secret-key-value"

        def transport(request, timeout):
            return 400, {}, json.dumps({
                "error": {"code": "bad_request", "message": f"invalid key {secret}"},
            }).encode("utf-8")

        client = OpenRouterClient(
            self._config(OPENROUTER_CUSTOM_ENDPOINT_API_KEY=secret),
            transport=transport,
        )
        with self.assertRaises(AIProviderError) as context:
            client.complete("Help", suite_id="operator-os")
        self.assertNotIn(secret, str(context.exception))

    def test_embedded_error_in_http_200_is_not_a_completion(self):
        def transport(request, timeout):
            return 200, {}, json.dumps({
                "error": {"code": "rate_limit_exceeded", "message": "Slow down"},
            }).encode("utf-8")

        with self.assertRaises(AIProviderError) as context:
            OpenRouterClient(self._config(), transport=transport).complete(
                "Help",
                suite_id="model-behavior-lab",
            )
        self.assertEqual(context.exception.code, "rate_limited")


class OpenRouterCLITests(unittest.TestCase):
    def test_status_is_credential_free(self):
        status = {
            "provider": "openrouter",
            "configured": True,
            "credential_source": ".env",
            "free_only": True,
            "roles": {"orchestrator": {"model": OPENROUTER_FREE_MODEL, "temperature": 0.2, "max_tokens": 50}},
            "warnings": [],
            "evidence_boundary": "Model-assisted only.",
        }
        output = StringIO()
        with patch("portfolio_suites.cli.get_ai_status", return_value=status), redirect_stdout(output):
            code = main(["ai", "--status"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn(OPENROUTER_FREE_MODEL, output.getvalue())
        self.assertNotIn("Authorization", output.getvalue())

    def test_prompt_routes_to_named_suite_and_role(self):
        result = {
            "content": "Review result",
            "resolved_model": "vendor/model:free",
            "suite_id": "accessibility",
            "role": "reviewer",
        }
        output = StringIO()
        with patch("portfolio_suites.cli.request_assistance", return_value=result) as request, redirect_stdout(output):
            code = main(["ai", "--suite", "accessibility", "--role", "reviewer", "Review", "this"])
        self.assertEqual(code, EXIT_OK)
        request.assert_called_once_with(
            "Review this",
            suite_id="accessibility",
            role="reviewer",
            context=None,
        )
        self.assertIn("human review required", output.getvalue())

    def test_missing_prompt_is_incomplete(self):
        error = StringIO()
        with redirect_stderr(error):
            code = main(["ai"])
        self.assertEqual(code, EXIT_INCOMPLETE)
        self.assertIn("provide a prompt", error.getvalue())

    def test_sensitive_context_is_refused_before_provider_call(self):
        error = StringIO()
        with patch("portfolio_suites.cli.request_assistance") as request, redirect_stderr(error):
            code = main(["ai", "--context", ".env", "Summarize"])
        self.assertEqual(code, EXIT_INCOMPLETE)
        self.assertIn("sensitive", error.getvalue())
        request.assert_not_called()

    def test_oversized_context_is_refused_before_provider_call(self):
        with tempfile.TemporaryDirectory(dir="/Users/ryanjohnson/Projects") as tmp:
            context_file = Path(tmp) / "large.txt"
            context_file.write_text("x" * 75_001, encoding="utf-8")
            error = StringIO()
            with patch("portfolio_suites.cli.request_assistance") as request, redirect_stderr(error):
                code = main(["ai", "--context", str(context_file), "Summarize"])
        self.assertEqual(code, EXIT_INCOMPLETE)
        self.assertIn("character limit", error.getvalue())
        request.assert_not_called()


class _BytesReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.data) - self.offset
        result = self.data[self.offset:self.offset + size]
        self.offset += len(result)
        return result

    def close(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
