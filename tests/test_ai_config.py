import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from portfolio_suites.ai_config import AIConfigError, load_openrouter_config, read_env_file
from portfolio_suites.cli import main


class AIConfigTests(unittest.TestCase):
    def test_empty_local_key_is_safe_for_non_network_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "OPENROUTER_API_KEY=\nOPENROUTER_DEFAULT_MODEL=openrouter/auto\n",
                encoding="utf-8",
            )
            config = load_openrouter_config(env_path=env_path, environ={})

        self.assertFalse(config.api_key_configured)
        self.assertEqual(config.role("reviewer").model, "openrouter/auto")
        self.assertNotIn("api_key", config.safe_summary())

    def test_require_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("OPENROUTER_API_KEY=\n", encoding="utf-8")
            with self.assertRaises(AIConfigError):
                load_openrouter_config(env_path=env_path, environ={}, require_api_key=True)

    def test_role_overrides_and_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "OPENROUTER_API_KEY=local-file-key",
                        "OPENROUTER_APP_URL=https://example.test/suites",
                        "OPENROUTER_APP_TITLE=Suites Test",
                        "OPENROUTER_ROLE_REVIEWER_MODEL=author/reviewer-v1",
                        "OPENROUTER_ROLE_REVIEWER_TEMPERATURE=0.25",
                        "OPENROUTER_ROLE_REVIEWER_MAX_TOKENS=2048",
                    ]
                ),
                encoding="utf-8",
            )
            config = load_openrouter_config(
                env_path=env_path,
                environ={"OPENROUTER_API_KEY": "process-key"},
                require_api_key=True,
            )

        reviewer = config.role("reviewer")
        headers = config.request_headers()
        self.assertEqual(reviewer.model, "author/reviewer-v1")
        self.assertEqual(reviewer.temperature, 0.25)
        self.assertEqual(reviewer.max_tokens, 2048)
        self.assertEqual(headers["Authorization"], "Bearer process-key")
        self.assertEqual(headers["HTTP-Referer"], "https://example.test/suites")
        self.assertEqual(headers["X-OpenRouter-Title"], "Suites Test")
        self.assertNotIn("process-key", str(config.safe_summary()))
        self.assertNotIn("process-key", repr(config))

    def test_invalid_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "OPENROUTER_ROLE_CREATIVE_TEMPERATURE=2.5\n",
                encoding="utf-8",
            )
            with self.assertRaises(AIConfigError):
                load_openrouter_config(env_path=env_path, environ={})

    def test_dotenv_parser_does_not_expand_shell_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "export OPENROUTER_API_KEY='literal-$(whoami)'\n",
                encoding="utf-8",
            )
            values = read_env_file(env_path)

        self.assertEqual(values["OPENROUTER_API_KEY"], "literal-$(whoami)")

    def test_cli_summary_is_redacted(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["ai-config", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(payload["ok"])
        self.assertIn("api_key_configured", payload)
        self.assertNotIn("api_key", payload)


if __name__ == "__main__":
    unittest.main()
