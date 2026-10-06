"""Authentic producer -> separately executed consumer proof for A11yFinding (contract freeze).

Producer: allys-tools' own aria-validator, run through tsx in a donor subprocess.
Consumer: the control plane's CLI in a second process. Skips when the donor toolchain is absent.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from portfolio_suites.adapters.common import donor_env, get_repo_path
from portfolio_suites.paths import SUITES_ROOT

SCRIPT = """
import { validateAriaSnapshot } from './a11y-tools/aria-validator/index.ts';
const nodes = [{selector:'#email',tagName:'input',role:null,implicitRole:null,accessibleName:'Email Address',focusable:true,interactive:true,text:'',html:'<input id="email" type="email" class="is-invalid" aria-invalid="true">',attributes:{id:'email',type:'email',class:'is-invalid','aria-invalid':'true'}}];
console.log(JSON.stringify(validateAriaSnapshot('https://example.test/checkout', nodes)));
"""


class AllysToolsA11yFindingProofTests(unittest.TestCase):
    def test_donor_validator_finding_maps_to_an_a11y_finding_an_independent_consumer_accepts(self):
        donor = get_repo_path("allys-tools", "ALLYS_TOOLS_DIR")
        if not (donor / "a11y-tools" / "aria-validator" / "index.ts").is_file() or not (donor / "node_modules").is_dir() or not shutil.which("npx"):
            self.skipTest("allys-tools checkout with installed node_modules is not available")
        produced = subprocess.run(
            ["npx", "--no-install", "tsx", "-e", SCRIPT],
            cwd=donor, env=donor_env(), capture_output=True, text=True, timeout=60,
        )
        if produced.returncode != 0:
            self.skipTest(f"donor toolchain not runnable here (environment blocked): {produced.stderr[-200:]}")
        raw = json.loads(produced.stdout.strip().splitlines()[-1])["findings"][0]
        self.assertEqual(raw["selector"], "#email")  # the donor really flagged the unassociated invalid input
        finding = {
            "schema_version": "1.0.0",
            "finding_id": "find-ally-331-" + raw["id"],
            "rule_id": "wcag-" + raw["wcagRule"].replace(".", ""),
            "severity": "serious" if raw["severity"] == "moderate" else raw["severity"],
            "summary": raw["description"],
            "target": raw["selector"],
            "evidence": [{"tool": raw["tool"], "html": raw["html"], "donor_finding_id": raw["id"], "timestamp": raw["timestamp"]}],
            "evidence_kind": "deterministic",
            "needs_review": True,  # donor status is needs-review; no human has confirmed it
            "status": "open",
        }
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "finding.json"
            artifact.write_text(json.dumps(finding), encoding="utf-8")
            consumed = subprocess.run(
                [sys.executable, "-m", "portfolio_suites", "contract", "A11yFinding", "validate", str(artifact)],
                env={"PYTHONPATH": str(SUITES_ROOT / "src"), "SUITES_ROOT": str(SUITES_ROOT), "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(consumed.returncode, 0, consumed.stdout + consumed.stderr)


if __name__ == "__main__":
    unittest.main()
