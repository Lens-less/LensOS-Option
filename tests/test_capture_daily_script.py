from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
            "evidence repo required directories must not be reparse points",
            "evidence repo must be clean before sync",
            "evidence sync source must stay inside the product artifacts directory",
            "$requiredDirectories = @('snapshots', 'history', 'logs', 'reports')",
            "$gitAddArguments = @('add', '--')",
            "user.name=LensOS Capture Bot",
            "'commit', '-m', $commitMessage",
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

    def test_capture_failure_posts_a_redacted_webhook_payload(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        received: queue.Queue[bytes] = queue.Queue()

        class WebhookHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                received.put(self.rfile.read(length))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), WebhookHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with TemporaryDirectory() as temporary_root:
                token = "local-test-secret"
                webhook_url = (
                    f"http://127.0.0.1:{server.server_port}/capture-failed?token={token}"
                )
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
                        "-FailureWebhookUrl",
                        webhook_url,
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
                payload = json.loads(received.get(timeout=5).decode("utf-8-sig"))
                self.assertEqual("capture_daily_failure_webhook.v1", payload["schema_version"])
                self.assertEqual("failed", payload["status"])
                self.assertEqual("snapshot", payload["failed_stage"])
                self.assertNotIn(token, json.dumps(payload))

                summary_path = (
                    Path(temporary_root)
                    / "artifacts"
                    / "logs"
                    / "capture-daily-btc.latest.summary.json"
                )
                summary_text = summary_path.read_text(encoding="utf-8-sig")
                summary = json.loads(summary_text)
                self.assertEqual(
                    {
                        "configured": True,
                        "attempted": True,
                        "delivered": True,
                        "url": "redacted",
                        "error": None,
                    },
                    summary["webhook"],
                )
                self.assertNotIn(token, summary_text)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_evidence_sync_pushes_versioned_artifacts_to_local_bare_remote(
        self,
    ) -> None:
        if os.name != "nt":
            self.skipTest("capture-daily evidence sync is a Windows PowerShell lane")
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        git = shutil.which("git")
        if not powershell or not git:
            self.skipTest("PowerShell and git are required")

        def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                list(args),
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )

        with TemporaryDirectory() as temporary_root_value:
            temporary_root = Path(temporary_root_value)
            product_root = temporary_root / "product"
            evidence_root = temporary_root / "evidence-repo"
            remote_root = temporary_root / "evidence-remote.git"
            bin_root = temporary_root / "bin"
            product_root.mkdir()
            evidence_root.mkdir()
            bin_root.mkdir()

            stub = bin_root / "capture_stub.py"
            stub.write_text(
                textwrap.dedent(
                    """
                    from __future__ import annotations

                    import json
                    import sys
                    from pathlib import Path


                    tool = sys.argv[1]
                    args = sys.argv[2:]


                    def value(flag: str) -> str:
                        return args[args.index(flag) + 1]


                    def write_json(path: Path, payload: dict[str, object]) -> None:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(payload), encoding="utf-8")


                    if tool == "snapshot":
                        command = args[0]
                        if command == "pull-snapshot":
                            output_dir = Path(value("--output-dir"))
                            output = output_dir / "btc-chain-20260802T090014.json"
                            write_json(output, {"schema_version": "stub_snapshot.v1"})
                            payload = {
                                "path": str(output.resolve()),
                                "captured_at": "2026-08-02T09:00:14Z",
                                "row_count": 1,
                                "fetch_errors": [],
                            }
                        elif command == "series-history":
                            output = Path(value("--output"))
                            write_json(output, {"schema_version": "stub_series.v1"})
                            payload = {
                                "generated_at": "2026-08-02T09:00:14Z",
                                "instrument_count": 1,
                                "capture_count": 1,
                            }
                        elif command == "validate-signal":
                            output = Path(value("--output"))
                            write_json(output, {"schema_version": "stub_signal.v1"})
                            payload = {
                                "status": "collecting",
                                "generated_at": "2026-08-02T09:00:14Z",
                                "reason_code": "INSUFFICIENT_SETTLED_COHORTS",
                            }
                        else:
                            raise SystemExit(f"unexpected snapshot command: {command}")
                    elif tool == "underlying":
                        output = Path(value("--output"))
                        write_json(output, {"schema_version": "stub_underlying.v1"})
                        payload = {
                            "observation_count": 1200,
                            "first_observed_at": "2023-04-21T00:00:00Z",
                            "last_observed_at": "2026-08-02T00:00:00Z",
                        }
                    elif tool == "dvol":
                        output = Path(value("--output"))
                        write_json(output, {"schema_version": "stub_dvol.v1"})
                        payload = {
                            "observation_count": 1095,
                            "first_observed_at": "2023-08-04T00:00:00Z",
                            "last_observed_at": "2026-08-02T00:00:00Z",
                            "missing_day_count": 0,
                        }
                    else:
                        raise SystemExit(f"unexpected tool: {tool}")

                    print(json.dumps(payload))
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            commands = {
                "crypto-options-report.cmd": "snapshot",
                "crypto-options-underlying-history.cmd": "underlying",
                "crypto-options-dvol-history.cmd": "dvol",
            }
            for command_name, tool_name in commands.items():
                (bin_root / command_name).write_text(
                    f'@echo off\r\n"{sys.executable}" "%~dp0capture_stub.py" {tool_name} %*\r\n',
                    encoding="utf-8",
                )

            self.assertEqual(0, run(git, "init", "--bare", str(remote_root), cwd=temporary_root).returncode)
            self.assertEqual(0, run(git, "init", "-b", "main", cwd=evidence_root).returncode)
            for directory in ("snapshots", "history", "logs", "reports"):
                target = evidence_root / directory
                target.mkdir()
                (target / ".gitkeep").write_text("", encoding="utf-8")
            self.assertEqual(0, run(git, "add", ".", cwd=evidence_root).returncode)
            initial_commit = run(
                git,
                "-c",
                "user.name=Test Operator",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-m",
                "Provision durable evidence roots",
                cwd=evidence_root,
            )
            self.assertEqual(0, initial_commit.returncode, initial_commit.stderr)
            self.assertEqual(0, run(git, "remote", "add", "origin", str(remote_root), cwd=evidence_root).returncode)
            initial_push = run(git, "push", "-u", "origin", "main", cwd=evidence_root)
            self.assertEqual(0, initial_push.returncode, initial_push.stderr)

            env = os.environ.copy()
            env["PATH"] = str(bin_root) + os.pathsep + env.get("PATH", "")
            env["CAPTURE_DAILY_CAPTURE_DVOL"] = "true"
            completed = run(
                powershell,
                "-NoProfile",
                "-File",
                str(self.SCRIPT),
                "-RepoRoot",
                str(product_root),
                "-EnableEvidenceRepoSync",
                "-EvidenceRepoRoot",
                str(evidence_root),
                cwd=self.REPO_ROOT,
                env=env,
            )
            summary_path = (
                product_root
                / "artifacts"
                / "logs"
                / "capture-daily-btc.latest.summary.json"
            )
            failure_detail = completed.stderr + completed.stdout
            if summary_path.exists():
                failure_detail += summary_path.read_text(encoding="utf-8-sig")
            self.assertEqual(0, completed.returncode, failure_detail)

            summary = json.loads(
                summary_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual("ok", summary["status"])
            sync_stage = next(stage for stage in summary["stages"] if stage["name"] == "evidence_repo_sync")
            self.assertEqual("ok", sync_stage["status"])
            self.assertEqual("pushed", sync_stage["details"]["mode"])

            remote_tree = run(
                git,
                f"--git-dir={remote_root}",
                "ls-tree",
                "-r",
                "--name-only",
                "main",
                cwd=temporary_root,
            )
            self.assertEqual(0, remote_tree.returncode, remote_tree.stderr)
            for expected in (
                "snapshots/btc-series/btc-chain-20260802T090014.json",
                "history/btc-daily.json",
                "history/btc-dvol.json",
                "reports/series-history.json",
                "reports/signal-preflight.json",
                "logs/capture-daily.log",
                "logs/capture-daily-btc.latest.summary.json",
            ):
                with self.subTest(expected_remote_path=expected):
                    self.assertIn(expected, remote_tree.stdout.splitlines())
            self.assertNotIn("artifacts/", remote_tree.stdout)

            remote_log = run(
                git,
                f"--git-dir={remote_root}",
                "log",
                "--format=%s",
                "main",
                cwd=temporary_root,
            )
            self.assertEqual(0, remote_log.returncode, remote_log.stderr)
            self.assertEqual(
                "Preserve daily market evidence outside the product workspace",
                remote_log.stdout.splitlines()[0],
            )

            captured_relative = Path(
                "snapshots/btc-series/btc-chain-20260802T090014.json"
            )
            removed_capture = run(
                git,
                "rm",
                "--",
                captured_relative.as_posix(),
                cwd=evidence_root,
            )
            self.assertEqual(0, removed_capture.returncode, removed_capture.stderr)
            remove_commit = run(
                git,
                "-c",
                "user.name=Test Operator",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-m",
                "Prepare nested reparse-point regression",
                cwd=evidence_root,
            )
            self.assertEqual(0, remove_commit.returncode, remove_commit.stderr)
            remove_push = run(git, "push", "origin", "main", cwd=evidence_root)
            self.assertEqual(0, remove_push.returncode, remove_push.stderr)

            outside_target = temporary_root / "outside-evidence-root"
            outside_target.mkdir()
            junction_path = evidence_root / "snapshots" / "btc-series"

            def quote(value: Path) -> str:
                return str(value).replace("'", "''")

            create_junction = run(
                powershell,
                "-NoProfile",
                "-Command",
                (
                    "New-Item -ItemType Junction "
                    f"-Path '{quote(junction_path)}' "
                    f"-Target '{quote(outside_target)}' | Out-Null"
                ),
                cwd=evidence_root,
            )
            self.assertEqual(0, create_junction.returncode, create_junction.stderr)
            clean_with_empty_junction = run(
                git,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                cwd=evidence_root,
            )
            self.assertEqual("", clean_with_empty_junction.stdout.strip())

            junction_run = run(
                powershell,
                "-NoProfile",
                "-File",
                str(self.SCRIPT),
                "-RepoRoot",
                str(product_root),
                "-EnableEvidenceRepoSync",
                "-EvidenceRepoRoot",
                str(evidence_root),
                cwd=self.REPO_ROOT,
                env=env,
            )
            self.assertNotEqual(0, junction_run.returncode)
            junction_summary = json.loads(
                summary_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual("evidence_repo_sync", junction_summary["failed_stage"])
            self.assertIn(
                "reparse points are not allowed in evidence sync paths",
                junction_summary["error"],
            )
            self.assertEqual([], list(outside_target.iterdir()))
            junction_path.rmdir()

            missing_remote = temporary_root / "missing-evidence-remote.git"
            self.assertEqual(
                0,
                run(
                    git,
                    "remote",
                    "set-url",
                    "origin",
                    str(missing_remote),
                    cwd=evidence_root,
                ).returncode,
            )
            rejected_push = run(
                powershell,
                "-NoProfile",
                "-File",
                str(self.SCRIPT),
                "-RepoRoot",
                str(product_root),
                "-EnableEvidenceRepoSync",
                "-EvidenceRepoRoot",
                str(evidence_root),
                cwd=self.REPO_ROOT,
                env=env,
            )
            self.assertNotEqual(0, rejected_push.returncode)
            rejected_summary = json.loads(
                summary_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual("failed", rejected_summary["status"])
            self.assertEqual("evidence_repo_sync", rejected_summary["failed_stage"])
            self.assertIn("git push failed with exit code", rejected_summary["error"])

            (evidence_root / "operator-note.txt").write_text("do not absorb me", encoding="utf-8")
            dirty_run = run(
                powershell,
                "-NoProfile",
                "-File",
                str(self.SCRIPT),
                "-RepoRoot",
                str(product_root),
                "-EnableEvidenceRepoSync",
                "-EvidenceRepoRoot",
                str(evidence_root),
                cwd=self.REPO_ROOT,
                env=env,
            )
            self.assertNotEqual(0, dirty_run.returncode)
            dirty_summary = json.loads(
                (product_root / "artifacts" / "logs" / "capture-daily-btc.latest.summary.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            self.assertEqual("failed", dirty_summary["status"])
            self.assertEqual("evidence_repo_preflight", dirty_summary["failed_stage"])
            self.assertIn("must be clean before sync", dirty_summary["error"])


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
        self.assertIn("path: product/dist/site", workflow)
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
            "path: product",
            "path: evidence-repo",
            "working-directory: product",
            "CAPTURE_DAILY_EVIDENCE_SYNC: ${{ env.LENSOS_EVIDENCE_REPO_SYNC_ENABLED }}",
            "CAPTURE_DAILY_EVIDENCE_REPO_ROOT: ${{ github.workspace }}/evidence-repo",
            "product/artifacts/snapshots",
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
