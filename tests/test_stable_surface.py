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

from portfolio_suites import cli, server

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
    routes = sorted(set(re.findall(r'"(/api[^"]*)"', Path(server.__file__).read_text(encoding="utf-8"))))
    return {
        "cli": _describe(_capture_parser()),
        "api_routes": routes,
        # HTTP error classes the server may return; see the error taxonomy in docs/STABLE-SURFACE.md.
        "api_error_statuses": sorted({int(code) for code in re.findall(r"_send_json\((\d{3})", Path(server.__file__).read_text(encoding="utf-8")) if int(code) >= 400}),
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


if __name__ == "__main__":
    unittest.main()
