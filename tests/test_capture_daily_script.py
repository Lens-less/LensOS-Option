from __future__ import annotations

import hashlib
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

    @staticmethod
    def _write_capture_stub_tooling(bin_root: Path) -> None:
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
        self.assertIn("CAPTURE_SUCCESS_HEARTBEAT_URL", source)
        self.assertIn("EnableEvidenceRepoSync", source)
        self.assertIn("SuccessHeartbeatUrl", source)

        for stage in (
            "snapshot",
            "underlying_history",
            "dvol_history",
            "series_history",
            "signal_preflight",
            "evidence_repo_preflight",
            "evidence_repo_sync",
            "success_heartbeat",
        ):
            with self.subTest(stage=stage):
                self.assertRegex(source, rf"-Name '{stage}'")

        series_arguments = source[
            source.index("$seriesArgs =") : source.index(
                "Invoke-Stage -Name 'series_history'"
            )
        ]
        self.assertIn(
            "$seriesArgs += @('--generated-at', $analysisTimestamp)",
            series_arguments,
        )

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
            "evidence repo git-common-dir must not match the product repo git-common-dir",
            "evidence repo remote is not configured",
            "evidence repo remote must not match any product repo remote",
            "evidence repo is missing required directories: ",
            "evidence repo required directories must not be reparse points",
            "evidence repo must be clean before sync",
            "evidence sync source must stay inside the product artifacts directory",
            "$requiredDirectories = @('snapshots', 'history', 'logs', 'reports')",
            "$gitAddArguments = @('add', '--')",
            "user.name=LensOS Capture Bot",
            "'commit', '-m', $commitMessage",
            "Invoke-EvidenceRepoPushWithRetry",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_capture_script_declares_unsynced_summary_and_retry_hardening_contracts(self) -> None:
        source = self.SCRIPT.read_text(encoding="utf-8")

        for fragment in (
            "unsynced_local_capture_count",
            "check-ignore --stdin",
            "git fetch",
            "rebase', \"$RemoteName/$Branch\"",
            "retrying evidence repo push after remote update",
            "-UseBasicParsing",
            "delivery_attempts",
            "success_heartbeat",
        ):
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
        self.assertIn("SuccessHeartbeatUrl", help_text)
        self.assertIn("EvidenceRepoRoot", help_text)
        self.assertIn("EnableEvidenceRepoPreflight", help_text)
        self.assertIn("EnableEvidenceRepoSync", help_text)

    def test_successful_capture_posts_a_redacted_success_heartbeat_payload(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        received: queue.Queue[bytes] = queue.Queue()

        class HeartbeatHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                received.put(self.rfile.read(length))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), HeartbeatHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with TemporaryDirectory() as temporary_root_value:
                temporary_root = Path(temporary_root_value)
                product_root = temporary_root / "product"
                bin_root = temporary_root / "bin"
                product_root.mkdir()
                bin_root.mkdir()
                self._write_capture_stub_tooling(bin_root)

                token = "success-secret"
                completed = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-File",
                        str(self.SCRIPT),
                        "-RepoRoot",
                        str(product_root),
                    ],
                    cwd=self.REPO_ROOT,
                    env={
                        **os.environ,
                        "PATH": str(bin_root) + os.pathsep + os.environ.get("PATH", ""),
                        "CAPTURE_DAILY_CAPTURE_DVOL": "true",
                        "CAPTURE_SUCCESS_HEARTBEAT_URL": f"http://127.0.0.1:{server.server_port}/capture-success?token={token}",
                    },
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=30,
                )

                self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
                payload = json.loads(received.get(timeout=5).decode("utf-8-sig"))
                self.assertEqual("capture_daily_success_heartbeat.v1", payload["schema_version"])
                self.assertEqual("ok", payload["status"])
                self.assertNotIn(token, json.dumps(payload))

                summary_path = (
                    product_root
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
                        "delivery_attempts": 1,
                        "error": None,
                    },
                    summary["success_heartbeat"],
                )
                self.assertNotIn(token, summary_text)
                self.assertNotIn("capture-success", summary_text)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_successful_capture_retries_heartbeat_and_fails_closed_on_delivery_error(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        request_count = {"value": 0}

        class HeartbeatHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                request_count["value"] += 1
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), HeartbeatHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with TemporaryDirectory() as temporary_root_value:
                temporary_root = Path(temporary_root_value)
                product_root = temporary_root / "product"
                bin_root = temporary_root / "bin"
                product_root.mkdir()
                bin_root.mkdir()
                self._write_capture_stub_tooling(bin_root)

                completed = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-File",
                        str(self.SCRIPT),
                        "-RepoRoot",
                        str(product_root),
                        "-SuccessHeartbeatUrl",
                        f"http://127.0.0.1:{server.server_port}/capture-success",
                    ],
                    cwd=self.REPO_ROOT,
                    env={
                        **os.environ,
                        "PATH": str(bin_root) + os.pathsep + os.environ.get("PATH", ""),
                        "CAPTURE_DAILY_CAPTURE_DVOL": "true",
                    },
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=30,
                )

                self.assertNotEqual(0, completed.returncode)
                self.assertEqual(3, request_count["value"])
                summary_path = (
                    product_root
                    / "artifacts"
                    / "logs"
                    / "capture-daily-btc.latest.summary.json"
                )
                summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
                self.assertEqual("failed", summary["status"])
                self.assertEqual("success_heartbeat", summary["failed_stage"])
                self.assertEqual(
                    {
                        "configured": True,
                        "attempted": True,
                        "delivered": False,
                        "delivery_attempts": 3,
                        "error": "delivery failed",
                    },
                    summary["success_heartbeat"],
                )
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_successful_capture_without_heartbeat_logs_skipped_stage_truthfully(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        with TemporaryDirectory() as temporary_root_value:
            temporary_root = Path(temporary_root_value)
            product_root = temporary_root / "product"
            bin_root = temporary_root / "bin"
            product_root.mkdir()
            bin_root.mkdir()
            self._write_capture_stub_tooling(bin_root)

            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-File",
                    str(self.SCRIPT),
                    "-RepoRoot",
                    str(product_root),
                ],
                cwd=self.REPO_ROOT,
                env={
                    **os.environ,
                    "PATH": str(bin_root) + os.pathsep + os.environ.get("PATH", ""),
                    "CAPTURE_DAILY_CAPTURE_DVOL": "true",
                },
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )

            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            summary_path = (
                product_root
                / "artifacts"
                / "logs"
                / "capture-daily-btc.latest.summary.json"
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                {
                    "configured": False,
                    "attempted": False,
                    "delivered": None,
                    "delivery_attempts": 0,
                    "error": None,
                },
                summary["success_heartbeat"],
            )
            heartbeat_stage = next(
                stage for stage in summary["stages"] if stage["name"] == "success_heartbeat"
            )
            self.assertEqual("skipped", heartbeat_stage["status"])

            log_text = (
                product_root / "artifacts" / "logs" / "capture-daily.log"
            ).read_text(encoding="utf-8-sig")
            self.assertIn("success_heartbeat skipped (not configured)", log_text)
            self.assertNotIn("success_heartbeat ok", log_text)

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

    def test_invalid_environment_flag_still_writes_failure_summary(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        with TemporaryDirectory() as temporary_root:
            env = os.environ.copy()
            env["CAPTURE_DAILY_EVIDENCE_SYNC"] = "definitely-not-a-bool"
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-File",
                    str(self.SCRIPT),
                    "-RepoRoot",
                    temporary_root,
                ],
                cwd=self.REPO_ROOT,
                env=env,
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
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
            self.assertEqual("failed", summary["status"])
            self.assertIn(
                "environment flag CAPTURE_DAILY_EVIDENCE_SYNC must be one of",
                summary["error"],
            )

    def test_tool_resolution_failure_is_summarized_and_alerted_from_bootstrap(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        received: queue.Queue[bytes] = queue.Queue()

        class WebhookHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                received.put(self.rfile.read(length))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), WebhookHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with TemporaryDirectory() as temporary_root_value:
                temporary_root = Path(temporary_root_value)
                empty_path = temporary_root / "empty-path"
                product_root = temporary_root / "product"
                empty_path.mkdir()
                product_root.mkdir()
                completed = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-File",
                        str(self.SCRIPT),
                        "-RepoRoot",
                        str(product_root),
                        "-FailureWebhookUrl",
                        f"http://127.0.0.1:{server.server_port}/capture-failed",
                    ],
                    cwd=self.REPO_ROOT,
                    env={**os.environ, "PATH": str(empty_path)},
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=30,
                )

                self.assertNotEqual(0, completed.returncode)
                summary_path = (
                    product_root
                    / "artifacts"
                    / "logs"
                    / "capture-daily-btc.latest.summary.json"
                )
                summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
                self.assertEqual("bootstrap", summary["failed_stage"])
                self.assertIn("capture tooling is unavailable", summary["error"])
                payload = json.loads(received.get(timeout=5).decode("utf-8-sig"))
                self.assertEqual("bootstrap", payload["failed_stage"])
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_unsafe_repo_root_failure_still_alerts_without_claiming_a_summary(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        received: queue.Queue[bytes] = queue.Queue()

        class WebhookHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                received.put(self.rfile.read(length))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), WebhookHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with TemporaryDirectory() as temporary_root_value:
                missing_repo = Path(temporary_root_value) / "missing-product-root"
                completed = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-File",
                        str(self.SCRIPT),
                        "-RepoRoot",
                        str(missing_repo),
                        "-FailureWebhookUrl",
                        f"http://127.0.0.1:{server.server_port}/capture-failed",
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
                self.assertEqual("bootstrap", payload["failed_stage"])
                self.assertIsNone(payload["summary_file"])
                self.assertIn(
                    "capture bootstrap failed before a safe summary path was available",
                    " ".join((completed.stderr + completed.stdout).split()),
                )
                self.assertFalse((missing_repo / "artifacts").exists())
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

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
                        "delivery_attempts": 1,
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

    def test_capture_failure_retries_webhook_delivery_before_marking_success(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is not available")

        attempts: queue.Queue[bytes] = queue.Queue()
        request_count = {"value": 0}

        class WebhookHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                attempts.put(self.rfile.read(length))
                request_count["value"] += 1
                status = 500 if request_count["value"] == 1 else 200
                self.send_response(status)
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
                        f"http://127.0.0.1:{server.server_port}/capture-failed",
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
                self.assertEqual(2, request_count["value"])
                first_payload = json.loads(attempts.get(timeout=5).decode("utf-8-sig"))
                second_payload = json.loads(attempts.get(timeout=5).decode("utf-8-sig"))
                self.assertEqual(first_payload, second_payload)

                summary_path = (
                    Path(temporary_root)
                    / "artifacts"
                    / "logs"
                    / "capture-daily-btc.latest.summary.json"
                )
                summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
                self.assertTrue(summary["webhook"]["delivered"])
                self.assertEqual(2, summary["webhook"]["delivery_attempts"])
                self.assertIsNone(summary["webhook"]["error"])
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

            self.assertEqual(0, run(git, "init", "-b", "main", cwd=product_root).returncode)
            self.assertEqual(
                0,
                run(
                    git,
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/Lens-less/LensOS-Option.git",
                    cwd=product_root,
                ).returncode,
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
            self.assertEqual(0, summary["unsynced_local_capture_count"])
            sync_stage = next(stage for stage in summary["stages"] if stage["name"] == "evidence_repo_sync")
            self.assertEqual("ok", sync_stage["status"])
            self.assertEqual("pushed", sync_stage["details"]["mode"])
            self.assertEqual(
                "immutable_pre_sync_receipt.v1",
                summary["evidence_receipt"]["protocol"],
            )
            receipt_path = Path(summary["evidence_receipt"]["path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            self.assertEqual("capture_daily_receipt.v1", receipt["schema_version"])
            self.assertEqual("capture_complete", receipt["status"])
            self.assertEqual("pending", receipt["evidence_repo_sync"]["status"])
            receipt_relative = receipt_path.relative_to(product_root / "artifacts")
            evidence_receipt_path = evidence_root / receipt_relative
            self.assertEqual(receipt_path.read_bytes(), evidence_receipt_path.read_bytes())

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
                "reports/signal-preflight.json",
                receipt_relative.as_posix(),
            ):
                with self.subTest(expected_remote_path=expected):
                    self.assertIn(expected, remote_tree.stdout.splitlines())
            self.assertNotIn(
                "logs/capture-daily-btc.latest.summary.json",
                remote_tree.stdout.splitlines(),
            )
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
            reset_after_junction = run(git, "reset", "--hard", "HEAD", cwd=evidence_root)
            self.assertEqual(0, reset_after_junction.returncode, reset_after_junction.stderr)
            clean_after_junction = run(git, "clean", "-fd", cwd=evidence_root)
            self.assertEqual(0, clean_after_junction.returncode, clean_after_junction.stderr)

            junction_receipt = Path(junction_summary["evidence_receipt"]["path"])
            duplicate_receipt = junction_receipt.with_name(
                "capture-daily-btc-duplicate.receipt.json"
            )
            duplicate_receipt.write_bytes(junction_receipt.read_bytes())

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
            self.assertEqual(2, rejected_summary["unsynced_local_capture_count"])

            pending_receipt = Path(rejected_summary["evidence_receipt"]["path"])
            pending_receipt_relative = pending_receipt.relative_to(
                product_root / "artifacts"
            ).as_posix()
            self.assertEqual(
                0,
                run(
                    git,
                    "remote",
                    "set-url",
                    "origin",
                    str(remote_root),
                    cwd=evidence_root,
                ).returncode,
            )
            reconciled = run(
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
            self.assertEqual(0, reconciled.returncode, reconciled.stderr + reconciled.stdout)
            reconciled_remote_tree = run(
                git,
                f"--git-dir={remote_root}",
                "ls-tree",
                "-r",
                "--name-only",
                "main",
                cwd=temporary_root,
            )
            self.assertEqual(0, reconciled_remote_tree.returncode)
            self.assertIn(
                pending_receipt_relative,
                reconciled_remote_tree.stdout.splitlines(),
            )
            reconciled_summary = json.loads(
                summary_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual(0, reconciled_summary["unsynced_local_capture_count"])

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

    def test_evidence_sync_rejects_matching_product_fetch_or_push_identity(self) -> None:
        if os.name != "nt":
            self.skipTest("capture-daily evidence sync is a Windows PowerShell lane")
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        git = shutil.which("git")
        if not powershell or not git:
            self.skipTest("PowerShell and git are required")

        def run(
            *args: str,
            cwd: Path,
            env: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
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

            self.assertEqual(0, run(git, "init", "-b", "main", cwd=product_root).returncode)
            self.assertEqual(
                0,
                run(
                    git,
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/Lens-less/LensOS-Option.git",
                    cwd=product_root,
                ).returncode,
            )
            self.assertEqual(0, run(git, "init", "-b", "main", cwd=evidence_root).returncode)
            self.assertEqual(
                0,
                run(
                    git,
                    "remote",
                    "add",
                    "origin",
                    "git@github.com:Lens-less/LensOS-Option.git",
                    cwd=evidence_root,
                ).returncode,
            )
            for directory in ("snapshots", "history", "logs", "reports"):
                target = evidence_root / directory
                target.mkdir()
                (target / ".gitkeep").write_text("", encoding="utf-8")
            self.assertEqual(0, run(git, "add", ".", cwd=evidence_root).returncode)
            commit = run(
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
            self.assertEqual(0, commit.returncode, commit.stderr)

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
                "-EnableEvidenceRepoPreflight",
                "-EvidenceRepoRoot",
                str(evidence_root),
                cwd=self.REPO_ROOT,
                env=env,
            )
            self.assertNotEqual(0, completed.returncode)
            summary_path = (
                product_root
                / "artifacts"
                / "logs"
                / "capture-daily-btc.latest.summary.json"
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
            self.assertEqual("evidence_repo_preflight", summary["failed_stage"])
            self.assertIn(
                "evidence repo remote must not match any product repo remote",
                summary["error"],
            )

            self.assertEqual(
                0,
                run(
                    git,
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/Lens-less/LensOS-Option-Evidence.git",
                    cwd=evidence_root,
                ).returncode,
            )
            self.assertEqual(
                0,
                run(
                    git,
                    "remote",
                    "set-url",
                    "--push",
                    "origin",
                    "git@github.com:Lens-less/LensOS-Option.git",
                    cwd=evidence_root,
                ).returncode,
            )
            pushurl_completed = run(
                powershell,
                "-NoProfile",
                "-File",
                str(self.SCRIPT),
                "-RepoRoot",
                str(product_root),
                "-EnableEvidenceRepoPreflight",
                "-EvidenceRepoRoot",
                str(evidence_root),
                cwd=self.REPO_ROOT,
                env=env,
            )
            self.assertNotEqual(0, pushurl_completed.returncode)
            pushurl_summary = json.loads(
                summary_path.read_text(encoding="utf-8-sig")
            )
            self.assertEqual(
                "evidence_repo_preflight", pushurl_summary["failed_stage"]
            )
            self.assertIn(
                "evidence repo remote must not match any product repo remote",
                pushurl_summary["error"],
            )


class PublishWorkflowContractTests(unittest.TestCase):
    REPO_ROOT = Path(__file__).resolve().parents[1]
    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    SECURITY = REPO_ROOT / "SECURITY.md"

    def test_publish_workflow_has_schedule_manual_trigger_and_artifact_upload(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('cron: "10 8 * * *"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("concurrency:", workflow)
        self.assertIn("group: publish-public-evidence", workflow)
        self.assertIn("actions/upload-artifact", workflow)
        self.assertIn("name: dist-site", workflow)
        self.assertIn("path: product/dist/site", workflow)
        self.assertIn("name: captured-evidence", workflow)
        self.assertIn("retention-days: 90", workflow)
        self.assertIn("steps.publish_site.outcome == 'success'", workflow)
        self.assertIn("actions/setup-node", workflow)
        self.assertIn(
            "actions/setup-node@249970729cb0ef3589644e2896645e5dc5ba9c38 # v6",
            workflow,
        )
        self.assertIn("working-directory: product/web", workflow)
        self.assertIn("npm ci", workflow)
        self.assertIn("npm run build:public", workflow)
        self.assertIn("npm run test:public-bundle", workflow)

    def test_publish_workflow_uses_minimal_permissions_and_fail_closed_contracts(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read$")
        self.assertNotIn("pages: write", workflow)
        self.assertNotIn("id-token: write", workflow)
        self.assertIn("Failure webhook is missing or is not a public HTTPS URL", workflow)
        self.assertIn("Success heartbeat is missing or is not a public HTTPS URL", workflow)
        self.assertIn("CAPTURE_SUCCESS_HEARTBEAT_URL", workflow)
        self.assertNotIn("LENSOS_STALE_MONITOR_ENABLED", workflow)
        self.assertIn("LENSOS_STALE_MONITOR_ID", workflow)
        self.assertIn("LENSOS_STALE_MONITOR_ATTESTATION_URL", workflow)
        self.assertIn("LENSOS_STALE_MONITOR_ATTESTATION_TOKEN", workflow)
        self.assertIn("[Uri]::TryCreate", workflow)
        self.assertIn("Test-PublicDnsHost", workflow)
        self.assertIn("Test-IpAddressInPrefix", workflow)
        self.assertIn("'alt'", workflow)
        self.assertIn("'arpa'", workflow)
        self.assertIn("$uri.AbsolutePath -ne '/'", workflow)
        self.assertIn("lensos_stale_monitor_attestation.v1", workflow)
        self.assertIn("failure_delivery_drill_at", workflow)
        self.assertIn("check_interval_seconds", workflow)
        self.assertIn("failure_webhook_sha256", workflow)
        self.assertIn("success_heartbeat_sha256", workflow)
        self.assertIn("-MaximumRedirection 0", workflow)
        self.assertIn("$attestationResponse.StatusCode -ne 200", workflow)
        self.assertIn("application/(?:json|[^;]+\\+json)", workflow)
        self.assertIn("Publish CLI is not available yet", workflow)
        self.assertIn("Publish failed closed", workflow)
        self.assertIn("CAPTURE_DAILY_CAPTURE_DVOL: \"true\"", workflow)
        self.assertIn("'--published-at', $publishedAt", workflow)
        self.assertIn("'--site-origin', $env:SITE_ORIGIN", workflow)
        self.assertIn("'--git-sha', $env:GITHUB_SHA", workflow)
        self.assertIn("'--web-build', 'web/dist-public'", workflow)
        self.assertIn("--web-build web/dist-public", workflow)
        self.assertNotIn("capture_dvol_history:", workflow)
        self.assertNotIn("dvol_history' -and -not", workflow)
        self.assertIn("artifacts/reports/workflow-failure.json", workflow)
        self.assertIn("artifacts/reports/publish-contract.json", workflow)
        self.assertNotIn("dist/site/workflow-failure.json", workflow)
        self.assertNotIn("dist/site/publish-contract.json", workflow)

    def test_publish_workflow_can_explicitly_enable_evidence_repo_sync(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        fragments = (
            "LENSOS_EVIDENCE_REPO_SYNC_ENABLED",
            "LENSOS_EVIDENCE_REPO_SLUG",
            "LENSOS_EVIDENCE_REPO_PUSH_TOKEN",
            "LENSOS_PUBLIC_SITE_ORIGIN",
            "LENSOS_STALE_MONITOR_ID",
            "LENSOS_STALE_MONITOR_ATTESTATION_URL",
            "LENSOS_STALE_MONITOR_ATTESTATION_TOKEN",
            "path: product",
            "path: evidence-repo",
            "working-directory: product",
            "CAPTURE_DAILY_EVIDENCE_SYNC: ${{ steps.config.outputs.evidence_sync_ready }}",
            "CAPTURE_DAILY_EVIDENCE_REPO_ROOT: ${{ github.workspace }}/evidence-repo",
            "product/artifacts/snapshots",
            "EnableEvidenceRepoSync",
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)

    def test_publish_workflow_suspends_deploy_attempts_but_keeps_local_verification(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        fragments = (
            'LENSOS_DEPLOY_DECISION: "SUSPENDED"',
            "LENSOS_DEPLOY_DECISION_ISSUE",
            'LENSOS_DEPLOY_DECISION_ISSUE: "docs/operations/public-deployment-suspension.md"',
            "Build public bundle",
            "Test public bundle boundary",
            "Record suspended deployment decision",
            "Build dist/site and enforce publish contract",
            "DEPLOY_SUSPENDED",
            "status = 'suspended'",
            "decision_issue = $env:DEPLOY_DECISION_ISSUE",
            "expected_owner_inputs = @(",
            "if: always() && env.LENSOS_DEPLOY_DECISION == 'SUSPENDED'",
            "if: always() && env.LENSOS_DEPLOY_DECISION != 'SUSPENDED'",
            "No publication or hosting step was attempted.",
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)

        build_step = workflow[
            workflow.index("      - name: Build public bundle") : workflow.index(
                "      - name: Test public bundle boundary"
            )
        ]
        self.assertIn("if: steps.capture.outcome == 'success'", build_step)
        self.assertNotIn("steps.config.outputs.evidence_sync_ready == 'true'", build_step)

        boundary_step = workflow[
            workflow.index("      - name: Test public bundle boundary") : workflow.index(
                "      - name: Record suspended deployment decision"
            )
        ]
        self.assertIn(
            "if: steps.capture.outcome == 'success' && steps.bundle_build.outcome == 'success'",
            boundary_step,
        )

        suspended_step = workflow[
            workflow.index("      - name: Record suspended deployment decision") : workflow.index(
                "      - name: Build dist/site and enforce publish contract"
            )
        ]
        self.assertIn(
            "if: always() && env.LENSOS_DEPLOY_DECISION == 'SUSPENDED'",
            suspended_step,
        )
        self.assertNotIn("python @publishArgs", suspended_step)

        publish_step = workflow[
            workflow.index("      - name: Build dist/site and enforce publish contract") : workflow.index(
                "      - name: Record durable publication receipt"
            )
        ]
        self.assertIn(
            "if: always() && env.LENSOS_DEPLOY_DECISION != 'SUSPENDED'",
            publish_step,
        )

        receipt_step = workflow[
            workflow.index("      - name: Record durable publication receipt") : workflow.index(
                "      - name: Upload dist/site artifact"
            )
        ]
        self.assertIn("env.LENSOS_DEPLOY_DECISION != 'SUSPENDED'", receipt_step)
        self.assertNotIn(
            "steps.config.outputs.evidence_sync_ready == 'true'",
            boundary_step,
        )

    def test_missing_sync_configuration_fails_only_after_capture(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        preflight_start = workflow.index("      - name: Preflight explicit workflow config")
        checkout_start = workflow.index("      - name: Checkout durable evidence repo")
        capture_start = workflow.index("      - name: Capture evidence")
        final_gate_start = workflow.index(
            "      - name: Fail closed when capture or publish was blocked"
        )
        preflight = workflow[preflight_start:checkout_start]

        self.assertLess(preflight_start, capture_start)
        self.assertLess(capture_start, final_gate_start)
        self.assertIn("id: config", preflight)
        self.assertIn("evidence_sync_ready", preflight)
        self.assertIn("site_origin_ready", preflight)
        self.assertIn("monitoring_ready", preflight)
        self.assertIn("catch {\n              $monitoringReady = $false", preflight)
        self.assertIn(
            "if: steps.config.outputs.evidence_sync_ready == 'true'",
            workflow[checkout_start:capture_start],
        )
        self.assertIn(
            "EVIDENCE_SYNC_READY: ${{ steps.config.outputs.evidence_sync_ready }}",
            workflow[final_gate_start:],
        )

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
            "allow-listed publication receipt",
            "explicitly remains in a collecting state",
            "compare the current time to `publish_edition.stale_after`",
            "Do not rely on a static JSON artifact",
            "durable backup still requires the separately owned evidence repository",
        )
        for fragment in security_fragments:
            with self.subTest(security_fragment=fragment):
                self.assertIn(fragment, security)

    def test_publish_workflow_consumes_and_persists_durable_publication_receipts(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        fragments = (
            "publication-history.json",
            "--publication-history",
            "name: Record durable publication receipt",
            "publications",
            "publication_history.v1",
            "research_publication_status",
            "manifest_sha256",
            "RECEIPT_OUTCOME",
            "Durable evidence sync is disabled",
            "git fetch",
            "git rebase",
            "git push",
            "git check-ignore",
            "git ls-files --error-unmatch",
            "git ls-remote --heads",
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)

    def test_publish_workflow_has_one_fail_closed_admission_contract(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        fragments = (
            "id: bundle_build",
            "id: bundle_boundary",
            "BUNDLE_BUILD_OUTCOME: ${{ steps.bundle_build.outcome }}",
            "BUNDLE_BOUNDARY_OUTCOME: ${{ steps.bundle_boundary.outcome }}",
            "MONITORING_READY: ${{ steps.config.outputs.monitoring_ready }}",
            "SITE_ORIGIN_READY: ${{ steps.config.outputs.site_origin_ready }}",
            "SITE_ORIGIN_NOT_CONFIGURED",
            "PUBLIC_BUNDLE_BUILD_FAILED",
            "PUBLIC_BUNDLE_BOUNDARY_FAILED",
            "MONITORING_NOT_VERIFIED",
            "steps.publication_receipt.outcome == 'success'",
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)

        receipt_start = workflow.index("      - name: Record durable publication receipt")
        upload_start = workflow.index("      - name: Upload dist/site artifact")
        receipt = workflow[receipt_start:upload_start]
        self.assertRegex(
            receipt,
            r"git add -- .*\n\s+if \(\$LASTEXITCODE -ne 0\)",
        )
        upload = workflow[upload_start:]
        self.assertIn("steps.bundle_build.outcome == 'success'", upload)
        self.assertIn("steps.bundle_boundary.outcome == 'success'", upload)
        self.assertIn("steps.config.outputs.evidence_sync_ready == 'true'", upload)
        self.assertIn("steps.config.outputs.monitoring_ready == 'true'", upload)
        self.assertIn("steps.config.outputs.site_origin_ready == 'true'", upload)

    def test_public_endpoint_and_monitor_attestation_guards_fail_under_mutation(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is required to execute the workflow guard contract")

        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        function_start = workflow.index("          function Test-IpAddressInPrefix")
        function_end = workflow.index("\n          $syncRequested", function_start)
        functions = textwrap.dedent(workflow[function_start:function_end])
        probes = r"""
        $now = [DateTimeOffset]::Parse('2026-08-03T10:00:00Z')
        $origin = 'https://research.lensos.dev'
        $failure = 'https://alerts.vendor.dev/failure/secret'
        $heartbeat = 'https://heartbeat.vendor.dev/ping/secret'

        function New-ValidAttestation {
          return [pscustomobject]@{
            schema_version = 'lensos_stale_monitor_attestation.v1'
            monitor_id = 'lens-public-staleness'
            site_origin = $origin
            health_url = "$origin/api/v1/health.json"
            contract = 'compare_current_time_to_stale_after'
            check_interval_seconds = 3600
            status = 'healthy'
            checked_at = '2026-08-03T09:59:00Z'
            failure_delivery_drill_at = '2026-07-15T00:00:00Z'
            failure_webhook_sha256 = Get-Sha256Text -Value $failure
            success_heartbeat_sha256 = Get-Sha256Text -Value $heartbeat
          }
        }

        function Test-ProbePayload {
          param([pscustomobject] $Payload)
          return Test-MonitorAttestationPayload `
            -Attestation $Payload `
            -Now $now `
            -SiteOrigin $origin `
            -MonitorId 'lens-public-staleness' `
            -FailureWebhook $failure `
            -SuccessHeartbeat $heartbeat
        }

        $proofJson = New-MonitorProofProjection -Attestation (New-ValidAttestation) |
          ConvertTo-Json -Compress
        $proofSha256 = Get-Sha256Text -Value $proofJson

        $badSchema = New-ValidAttestation
        $badSchema.schema_version = 'self_attested.v1'
        $wrongMonitor = New-ValidAttestation
        $wrongMonitor.monitor_id = 'other-monitor'
        $staleCheck = New-ValidAttestation
        $staleCheck.checked_at = '2026-08-03T07:59:59Z'
        $futureCheck = New-ValidAttestation
        $futureCheck.checked_at = '2026-08-03T10:05:01Z'
        $offsetCheck = New-ValidAttestation
        $offsetCheck.checked_at = '2026-08-03T09:59:00+00:00'
        $staleDrill = New-ValidAttestation
        $staleDrill.failure_delivery_drill_at = '2026-07-04T09:59:59Z'
        $futureDrill = New-ValidAttestation
        $futureDrill.failure_delivery_drill_at = '2026-08-03T10:05:01Z'
        $fastCheck = New-ValidAttestation
        $fastCheck.check_interval_seconds = 59
        $slowCheck = New-ValidAttestation
        $slowCheck.check_interval_seconds = 3601
        $wrongHealth = New-ValidAttestation
        $wrongHealth.health_url = "$origin/api/v1/summary.json"
        $wrongContract = New-ValidAttestation
        $wrongContract.contract = 'trust_static_is_stale'
        $wrongFailureEndpoint = New-ValidAttestation
        $wrongFailureEndpoint.failure_webhook_sha256 = ('0' * 64)
        $wrongHeartbeatEndpoint = New-ValidAttestation
        $wrongHeartbeatEndpoint.success_heartbeat_sha256 = ('0' * 64)
        $uppercaseFingerprint = New-ValidAttestation
        $uppercaseFingerprint.success_heartbeat_sha256 = $uppercaseFingerprint.success_heartbeat_sha256.ToUpperInvariant()
        $wrongOrigin = New-ValidAttestation
        $wrongOrigin.site_origin = 'https://other.lensos.dev'
        $wrongStatus = New-ValidAttestation
        $wrongStatus.status = 'configured'

        $localhost = Test-PublicDnsHost -HostName 'localhost'
        $loopbackLiteral = Test-PublicDnsHost -HostName '127.0.0.1'
        $reservedPreview = Test-PublicDnsHost -HostName 'preview.invalid'
        $specialArpa = Test-PublicDnsHost -HostName 'service.arpa'
        $exampleDomain = Test-PublicDnsHost -HostName 'research.example.com'
        $trailingRoot = Test-PublicDnsHost -HostName 'research.lensos.dev.'
        $invalidLabel = Test-PublicDnsHost -HostName 'research_.lensos.dev'
        function Test-PublicDnsHost {
          param([string] $HostName)
          return $HostName -eq 'research.lensos.dev'
        }

        [ordered]@{
          public_ip = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('8.8.8.8'))
          public_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('2606:4700:4700::1111'))
          private_ip = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('10.0.0.1'))
          shared_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('100.64.0.1'))
          link_local_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('169.254.0.1'))
          documentation_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('192.0.2.1'))
          as112_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('192.31.196.1'))
          amt_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('192.52.193.1'))
          direct_as112_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('192.175.48.1'))
          benchmark_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('198.18.0.1'))
          multicast_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('224.0.0.1'))
          reserved_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('240.0.0.1'))
          mapped_ipv4 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('::ffff:8.8.8.8'))
          unspecified_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('::'))
          nat64_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('64:ff9b::808:808'))
          local_nat64_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('64:ff9b:1::1'))
          discard_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('100::1'))
          dummy_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('100:0:0:1::1'))
          documentation_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('3fff::1'))
          benchmark_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('2001:2::1'))
          protocol_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('2001:1::1'))
          documentation_v1_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('2001:db8::1'))
          six_to_four_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('2002::1'))
          as112_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('2620:4f:8000::1'))
          segment_routing_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('5f00::1'))
          unique_local_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('fc00::1'))
          link_local_ipv6 = Test-PublicIpAddress -Address ([Net.IPAddress]::Parse('fe80::1'))
          localhost = $localhost
          loopback_literal = $loopbackLiteral
          reserved_preview = $reservedPreview
          special_arpa = $specialArpa
          example_domain = $exampleDomain
          trailing_root = $trailingRoot
          invalid_label = $invalidLabel
          valid_origin = Test-PublicHttpsUrl -Value $origin -OriginOnly
          origin_path = Test-PublicHttpsUrl -Value "$origin/public" -OriginOnly
          origin_query = Test-PublicHttpsUrl -Value "$origin/?preview=true" -OriginOnly
          origin_credentials = Test-PublicHttpsUrl -Value 'https://user:secret@research.lensos.dev' -OriginOnly
          origin_port = Test-PublicHttpsUrl -Value 'https://research.lensos.dev:8443' -OriginOnly
          valid_attestation = Test-ProbePayload -Payload (New-ValidAttestation)
          valid_monitor_id = Test-MonitorId -Value 'lens-public-staleness'
          unicode_monitor_id = Test-MonitorId -Value '监控器'
          proof_json = $proofJson
          proof_sha256 = $proofSha256
          bad_schema = Test-ProbePayload -Payload $badSchema
          wrong_monitor = Test-ProbePayload -Payload $wrongMonitor
          stale_check = Test-ProbePayload -Payload $staleCheck
          future_check = Test-ProbePayload -Payload $futureCheck
          offset_check = Test-ProbePayload -Payload $offsetCheck
          stale_drill = Test-ProbePayload -Payload $staleDrill
          future_drill = Test-ProbePayload -Payload $futureDrill
          fast_check = Test-ProbePayload -Payload $fastCheck
          slow_check = Test-ProbePayload -Payload $slowCheck
          wrong_health = Test-ProbePayload -Payload $wrongHealth
          wrong_contract = Test-ProbePayload -Payload $wrongContract
          wrong_failure_endpoint = Test-ProbePayload -Payload $wrongFailureEndpoint
          wrong_heartbeat_endpoint = Test-ProbePayload -Payload $wrongHeartbeatEndpoint
          uppercase_fingerprint = Test-ProbePayload -Payload $uppercaseFingerprint
          wrong_origin = Test-ProbePayload -Payload $wrongOrigin
          wrong_status = Test-ProbePayload -Payload $wrongStatus
        } | ConvertTo-Json -Compress
        """
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                functions + "\n" + textwrap.dedent(probes),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout.strip())
        self.assertTrue(payload.pop("public_ip"))
        self.assertTrue(payload.pop("public_ipv6"))
        self.assertTrue(payload.pop("valid_origin"))
        self.assertTrue(payload.pop("valid_attestation"))
        self.assertTrue(payload.pop("valid_monitor_id"))
        proof_json = payload.pop("proof_json")
        proof_sha256 = payload.pop("proof_sha256")
        canonical_proof = json.dumps(
            json.loads(proof_json),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.assertEqual(canonical_proof, proof_json)
        self.assertEqual(
            hashlib.sha256(proof_json.encode("utf-8")).hexdigest(),
            proof_sha256,
        )
        for probe, accepted in payload.items():
            with self.subTest(probe=probe):
                self.assertFalse(accepted)

    def test_monitoring_proof_is_persisted_without_secret_urls(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        for fragment in (
            "monitor_proof_json",
            "monitor_proof_sha256",
            "monitoring_admission_evidence.v1",
            "MONITOR_PROOF_JSON",
            "MONITOR_PROOF_SHA256",
            "monitoring_proof = $monitoringProof",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)
        receipt_start = workflow.index("      - name: Record durable publication receipt")
        receipt = workflow[receipt_start:]
        self.assertNotIn("MONITOR_ATTESTATION_TOKEN", receipt)
        self.assertNotIn("MONITOR_ATTESTATION_URL", receipt)

    def test_workflow_is_host_agnostic_until_hosting_is_chosen(self) -> None:
        workflow = self.WORKFLOW.read_text(encoding="utf-8")

        self.assertNotIn("LENSOS_DEPLOY_MODE", workflow)
        self.assertNotIn("deploy-pages", workflow)
        self.assertNotIn("custom-domain", workflow.lower())
        self.assertNotIn("vercel", workflow.lower())

    def test_scheduled_task_docs_set_restart_policy(self) -> None:
        readme = (self.REPO_ROOT / "README.md").read_text(encoding="utf-8")
        readme_en = (self.REPO_ROOT / "README.en.md").read_text(encoding="utf-8")

        for document in (readme, readme_en):
            self.assertIn("-RestartCount 3", document)
            self.assertIn(
                "-RestartInterval (New-TimeSpan -Minutes 20)",
                document,
            )

    def test_archive_docs_point_to_current_product_contract_not_a_second_prd(self) -> None:
        archive_readme = (
            self.REPO_ROOT / "docs" / "archive" / "README.md"
        ).read_text(encoding="utf-8")
        archived_prd = (
            self.REPO_ROOT / "docs" / "archive" / "v1-spec" / "prd-v1.1.md"
        ).read_text(encoding="utf-8")
        archived_spec = (
            self.REPO_ROOT / "docs" / "archive" / "v1-spec" / "spec-v1.1-audit-fixed.md"
        ).read_text(encoding="utf-8")

        for document in (archive_readme, archived_prd, archived_spec):
            self.assertIn("2026-08-02-public-product-spec.md", document)
            self.assertIn(
                "2026-08-12-continuity-and-consistency-spec.md",
                document,
            )
            self.assertIn("研究输入与历史方向", document)
            self.assertNotIn("现行 North Star", document)


if __name__ == "__main__":
    unittest.main()
