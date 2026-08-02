from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class CaptureDailyContractTests(unittest.TestCase):
    REPO_ROOT = Path(__file__).resolve().parents[1]
    SCRIPT = REPO_ROOT / "tools" / "capture-daily.ps1"
    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    SECURITY = REPO_ROOT / "SECURITY.md"

    def test_capture_script_declares_hardened_stages_and_summary_contract(self) -> None:
        source = self.SCRIPT.read_text(encoding="utf-8")

        self.assertIn("capture_daily_summary.v1", source)
        self.assertIn("last_successful_snapshot", source)
        self.assertIn("summary_latest_path", source)
        self.assertIn("CAPTURE_DAILY_FAILURE_WEBHOOK_URL", source)
        self.assertIn("CAPTURE_DAILY_CAPTURE_DVOL", source)
        self.assertIn("Get-EnvFlag -Name 'CAPTURE_DAILY_CAPTURE_DVOL' -Default $true", source)
        self.assertIn("CAPTURE_DAILY_EVIDENCE_PREFLIGHT", source)
        self.assertIn("CAPTURE_DAILY_EVIDENCE_SYNC", source)
        self.assertIn("EnableEvidenceRepoSync", source)

        for stage in (
            "snapshot",
            "underlying_history",
            "dvol_history",
            "series_history",
            "signal_preflight",
            "evidence_repo_preflight",
            "evidence_repo_sync",
        ):
            with self.subTest(stage=stage):
                self.assertRegex(source, rf"-Name '{stage}'")

    def test_capture_script_creates_required_directories_and_redacts_webhook(self) -> None:
        source = self.SCRIPT.read_text(encoding="utf-8")

        for segment in (
            "artifacts",
            "artifacts\\logs",
            "artifacts\\history",
            "artifacts\\snapshots",
            "artifacts\\reports",
        ):
            with self.subTest(segment=segment):
                normalized = segment.replace("\\", "/")
                self.assertIn(normalized.split("/")[-1], source)

        self.assertIn("url = 'redacted'", source)
        self.assertIn("git", source)
        self.assertIn("commit", source)
        self.assertIn("push", source)

    def test_capture_script_sync_contract_requires_independent_git_repo(self) -> None:
        source = self.SCRIPT.read_text(encoding="utf-8")

        expected_fragments = (
            "evidence repo root must not be the product repo root",
            "evidence repo root must live outside the product repo tree",
            "product repo root must not live inside the evidence repo tree",
            "evidence repo is not a git worktree",
            "evidence repo remote is not configured",
            "evidence repo is missing required directories: ",
            "$requiredDirectories = @('snapshots', 'history', 'logs', 'reports')",
            "Arguments @('add', '--')",
            "Arguments @('commit', '-m', $commitMessage)",
            "Arguments @('push', $RemoteName, \"HEAD:$branch\")",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_capture_script_contains_no_hardcoded_secret_like_literals(self) -> None:
        source = self.SCRIPT.read_text(encoding="utf-8")
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        combined = source + "\n" + workflow

        suspicious_literals = (
            "hooks.slack.com",
            "discord.com/api/webhooks",
            "api.telegram.org",
            "ghp_",
            "github_pat_",
            "xoxb-",
            "AKIA",
        )
        for literal in suspicious_literals:
            with self.subTest(literal=literal):
                self.assertNotIn(literal, combined)

    def test_capture_script_help_mentions_new_parameters(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                f"Get-Help '{self.SCRIPT}' -Full",
            ],
            cwd=self.REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        help_text = completed.stdout + completed.stderr
        self.assertIn("CaptureDvolHistory", help_text)
        self.assertIn("FailureWebhookUrl", help_text)
        self.assertIn("EvidenceRepoRoot", help_text)
        self.assertIn("EnableEvidenceRepoPreflight", help_text)
        self.assertIn("EnableEvidenceRepoSync", help_text)

    def test_capture_failure_writes_a_machine_readable_summary(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        with TemporaryDirectory() as temporary_root:
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-File",
                    str(self.SCRIPT),
                    "-RepoRoot",
                    temporary_root,
                    "-InstrumentLimit",
                    "0",
                ],
                cwd=self.REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )

            self.assertNotEqual(0, completed.returncode)
            summary_path = (
                Path(temporary_root)
                / "artifacts"
                / "logs"
                / "capture-daily-btc.latest.summary.json"
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
            self.assertEqual("failed", summary["status"])
            self.assertEqual("snapshot", summary["failed_stage"])
            self.assertFalse(summary["webhook"]["configured"])
            self.assertEqual("failed", summary["stages"][0]["status"])


class PublishWorkflowContractTests(unittest.TestCase):
    REPO_ROOT = Path(__file__).resolve().parents[1]
    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    SECURITY = REPO_ROOT / "SECURITY.md"

    def test_publish_workflow_has_schedule_manual_trigger_and_artifact_upload(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('cron: "10 8 * * *"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("actions/upload-artifact", workflow)
        self.assertIn("name: dist-site", workflow)
        self.assertIn("path: dist/site", workflow)
        self.assertIn("name: captured-evidence", workflow)
        self.assertIn("retention-days: 90", workflow)
        self.assertIn("if: always()", workflow)

    def test_publish_workflow_uses_minimal_permissions_and_fail_closed_contracts(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read$")
        self.assertNotIn("pages: write", workflow)
        self.assertNotIn("id-token: write", workflow)
        self.assertIn("CAPTURE_FAILURE_WEBHOOK_URL secret is required", workflow)
        self.assertIn("Publish CLI is not available yet", workflow)
        self.assertIn("Publish failed closed", workflow)
        self.assertIn("CAPTURE_DAILY_CAPTURE_DVOL: \"true\"", workflow)
        self.assertIn("'--published-at', $publishedAt", workflow)
        self.assertIn("'--git-sha', $env:GITHUB_SHA", workflow)
        self.assertNotIn("capture_dvol_history:", workflow)
        self.assertNotIn("dvol_history' -and -not", workflow)

    def test_publish_workflow_can_explicitly_enable_evidence_repo_sync(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        fragments = (
            "LENSOS_EVIDENCE_REPO_SYNC_ENABLED",
            "LENSOS_EVIDENCE_REPO_SLUG",
            "LENSOS_EVIDENCE_REPO_PUSH_TOKEN",
            "path: evidence-repo",
            "CAPTURE_DAILY_EVIDENCE_SYNC: ${{ env.LENSOS_EVIDENCE_REPO_SYNC_ENABLED }}",
            "CAPTURE_DAILY_EVIDENCE_REPO_ROOT: ${{ github.workspace }}/evidence-repo",
            "EnableEvidenceRepoSync",
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)

    def test_publish_workflow_documents_status_history_and_stale_after_contracts(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        security = self.SECURITY.read_text(encoding="utf-8")

        workflow_fragments = (
            "30-day status history requires persisted evidence artifacts",
            "compare the current time to publish_edition.stale_after",
            "Do not rely on a static JSON artifact",
        )
        for fragment in workflow_fragments:
            with self.subTest(workflow_fragment=fragment):
                self.assertIn(fragment, workflow)

        security_fragments = (
            "30-day status history requires persisted evidence artifacts",
            "compare the current time to `publish_edition.stale_after`",
            "Do not rely on a static JSON artifact",
            "durable backup still requires the separately owned evidence repository",
        )
        for fragment in security_fragments:
            with self.subTest(security_fragment=fragment):
                self.assertIn(fragment, security)

    def test_workflow_is_host_agnostic_until_hosting_is_chosen(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        self.assertNotIn("LENSOS_DEPLOY_MODE", workflow)
        self.assertNotIn("deploy-pages", workflow)
        self.assertNotIn("custom-domain", workflow.lower())
        self.assertNotIn("vercel", workflow.lower())


if __name__ == "__main__":
    unittest.main()
