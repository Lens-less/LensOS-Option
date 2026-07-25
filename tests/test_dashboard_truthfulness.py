import re
import shutil
import subprocess
import unittest
from pathlib import Path

from crypto_options_report.api import (
    dashboard_page_html,
    evidence_page_html,
    validate_evidence_bundle,
)


class DashboardTruthfulnessTests(unittest.TestCase):
    def test_dashboard_compatibility_shell_delegates_to_evidence_console(self):
        self.assertEqual(evidence_page_html(), dashboard_page_html())

    def test_evidence_console_shell_has_single_root_and_packaged_assets(self):
        html = evidence_page_html()

        self.assertIn("<html lang=\"zh-CN\">", html)
        self.assertIn("<title>LensOS Option", html)
        self.assertIn('<div id="root"></div>', html)
        self.assertNotIn("Crypto Options 研究控制台", html)
        self.assertNotIn("/dashboard.html", html)

        asset_urls = re.findall(r'(?:href|src)="(/evidence/assets/[^"]+)"', html)
        self.assertGreaterEqual(len(asset_urls), 2)
        self.assertEqual(len(asset_urls), len(set(asset_urls)))

    def test_evidence_bundle_validation_accepts_packaged_build(self):
        validate_evidence_bundle()

    def test_legacy_dashboard_static_file_is_removed(self):
        self.assertFalse(
            Path("crypto_options_report/static/dashboard.html").exists()
        )

    def test_cdp_verifier_targets_evidence_console_with_legacy_env_fallback(self):
        source = Path(".workflow/verify-dashboard-cdp.mjs").read_text(
            encoding="utf-8"
        )

        self.assertIn("process.env.EVIDENCE_URL", source)
        self.assertIn("process.env.DASHBOARD_URL", source)
        self.assertIn("http://127.0.0.1:8000/evidence", source)
        self.assertNotIn("http://127.0.0.1:8000/dashboard.html", source)

    def test_cdp_verifier_script_is_valid_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is required for verifier syntax verification")

        completed = subprocess.run(
            [node, "--check", ".workflow/verify-dashboard-cdp.mjs"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
