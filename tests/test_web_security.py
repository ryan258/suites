import json
import shutil
import subprocess
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


if __name__ == "__main__":
    unittest.main()

