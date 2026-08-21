import unittest
from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1] / "src" / "portfolio_suites" / "web"


class WebSecurityTests(unittest.TestCase):
    def test_manifest_rendering_uses_data_actions_not_inline_javascript(self):
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        index_source = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("onclick=", app_source)
        self.assertNotIn("onclick=", index_source)
        self.assertIn('data-app-action="run-wave"', app_source)
        self.assertIn("event.target.closest('[data-app-action]')", app_source)

    def test_previously_raw_manifest_and_contract_fields_are_escaped(self):
        app_source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        for expression in (
            "escapeHtml(s.name)",
            "escapeHtml(s.promise)",
            "escapeHtml(m.project)",
            "escapeHtml(w.objective)",
            "escapeHtml(w.acceptance)",
            "escapeHtml(spec.name)",
            "escapeHtml(spec.description)",
        ):
            with self.subTest(expression=expression):
                self.assertIn(expression, app_source)


if __name__ == "__main__":
    unittest.main()
