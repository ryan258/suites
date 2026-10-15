"""Pins the supported CLI/API surface. A diff here is a compatibility decision, not a test chore.

Regenerate the golden file deliberately: UPDATE_SURFACE=1 PYTHONPATH=src python3 -m unittest tests.test_stable_surface
"""
import argparse
import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio_suites import ai, cli, server

GOLDEN = Path(__file__).parent / "fixtures" / "stable-surface.json"


def _capture_parser() -> argparse.ArgumentParser:
    # ponytail: main() builds its parser inline; capture it instead of refactoring a high-fanout function.
    captured = []

    def grab(self, *args, **kwargs):
        captured.append(self)
        raise SystemExit(0)

    with patch.object(argparse.ArgumentParser, "parse_args", grab):
        try:
            cli.main(["list"])
        except SystemExit:
            pass
    return captured[0]


def _describe(parser: argparse.ArgumentParser) -> dict:
    options, positionals, commands = [], [], {}
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in sorted(action.choices.items()):
                commands[name] = _describe(sub)
        elif action.option_strings:
            options.append(sorted(action.option_strings))
        else:
            positionals.append({"dest": action.dest, "choices": sorted(map(str, action.choices or [])), "nargs": action.nargs})
    return {"options": sorted(options), "positionals": positionals, "commands": commands}


def current_surface() -> dict:
    server_source = Path(server.__file__).read_text(encoding="utf-8")
    ai_source = Path(ai.__file__).read_text(encoding="utf-8")
    routes = sorted(set(re.findall(r'"(/api[^"]*)"', server_source)))
    api_error_statuses = {
        int(code)
        for code in re.findall(r"_send_json\((\d{3})", server_source)
        if int(code) >= 400
    }
    # These paths pass the status through an exception attribute, so literal _send_json
    # extraction alone misses their public response codes.
    api_error_statuses.update(
        int(code) for code in re.findall(r"RequestBodyError\(\s*(\d{3})", server_source)
    )
    api_error_statuses.update(
        int(code) for code in re.findall(r"(?:self\.)?http_status\s*=\s*(\d{3})", ai_source)
    )
    return {
        "cli": _describe(_capture_parser()),
        "api_routes": routes,
        # HTTP error classes the server may return; see the error taxonomy in docs/STABLE-SURFACE.md.
        "api_error_statuses": sorted(api_error_statuses),
        "exit_codes": {"ok": cli.EXIT_OK, "failed": cli.EXIT_FAILED, "incomplete": cli.EXIT_INCOMPLETE},
    }


class StableSurfaceTests(unittest.TestCase):
    def test_surface_matches_frozen_golden(self):
        surface = current_surface()
        if os.environ.get("UPDATE_SURFACE") == "1":
            GOLDEN.write_text(json.dumps(surface, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        frozen = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(surface, frozen, "CLI/API surface changed; see docs/STABLE-SURFACE.md for the compatibility rules")


class ApiErrorShapeTests(unittest.TestCase):
    def test_unknown_endpoint_is_404_with_an_error_key(self):
        import threading
        import urllib.error
        import urllib.request

        httpd = server.create_server(port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/api/no-such-route")
        self.assertEqual(caught.exception.code, 404)
        self.assertIn("error", json.loads(caught.exception.read()))
        caught.exception.close()

    def test_ai_exception_statuses_are_preserved_in_api_responses(self):
        import threading
        import urllib.error
        import urllib.request

        from portfolio_suites.ai import AIConfigurationError, AIInputError, AIProviderError

        cases = (
            (lambda: AIInputError("invalid input"), 400),
            (lambda: AIProviderError("provider failure"), 502),
            (lambda: AIConfigurationError("provider unavailable"), 503),
            (lambda: AIProviderError("rate limited", provider_status=429), 429),
            (lambda: AIProviderError("upstream authentication failed", provider_status=401), 502),
            (lambda: AIProviderError("provider timed out", provider_status=408), 504),
        )

        httpd = server.create_server(port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        url = f"http://127.0.0.1:{httpd.server_address[1]}/api/ai/assist"
        body = json.dumps({"prompt": "Help", "suite_id": "operator-os"}).encode("utf-8")

        for make_error, expected_status in cases:
            request = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.subTest(expected_status=expected_status):
                with patch("portfolio_suites.server.request_assistance", side_effect=make_error()):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, expected_status)
                self.assertIn("error", json.loads(caught.exception.read()))
                caught.exception.close()


if __name__ == "__main__":
    unittest.main()
