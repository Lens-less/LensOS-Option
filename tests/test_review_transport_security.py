import hashlib
import hmac
import http.client
import json
import os
import re
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request

from crypto_options_report import account_snapshot_sidecar, alerts, api, market_data


class _JsonResponse:
    def __init__(self, payload: dict, *, status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


class ReviewTransportSecurityTests(unittest.TestCase):
    REPO_ROOT = Path(__file__).resolve().parents[1]
    FULL_GITHUB_ACTION_SHA = re.compile(
        r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?@[0-9a-f]{40}$"
    )
    FULL_IMAGE_DIGEST = re.compile(
        r"^[^@\s]+@sha256:[0-9a-f]{64}$"
    )

    def test_remote_bearer_token_file_requires_one_regular_ascii_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "api-token.txt"
            valid_token = "A" * 32
            token_path.write_text(valid_token, encoding="ascii")
            token_path.chmod(0o600)
            self.assertEqual(valid_token, api._load_remote_bearer_token(token_path))

            invalid_tokens = {
                "too_short": "A" * 31,
                "too_long": "A" * 257,
                "contains_space": "A" * 16 + " " + "B" * 15,
                "contains_newline": "A" * 32 + "\n",
                "contains_control": "A" * 31 + "\x7f",
                "non_ascii": "A" * 31 + "é",
            }
            for label, value in invalid_tokens.items():
                with self.subTest(case=label):
                    token_path.write_text(value, encoding="utf-8")
                    with self.assertRaisesRegex(
                        ValueError,
                        "CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE",
                    ):
                        api._load_remote_bearer_token(token_path)

            token_dir = Path(tmp) / "token-dir"
            token_dir.mkdir()
            with self.assertRaisesRegex(
                ValueError,
                "CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE",
            ):
                api._load_remote_bearer_token(token_dir)

            symlink_path = Path(tmp) / "api-token-link.txt"
            try:
                symlink_path.symlink_to(token_path)
            except OSError:
                pass
            else:
                with self.assertRaisesRegex(
                    ValueError,
                    "CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE",
                ):
                    api._load_remote_bearer_token(symlink_path)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not authoritative on Windows")
    def test_remote_bearer_token_file_rejects_broad_posix_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "api-token.txt"
            token_path.write_text("A" * 32, encoding="ascii")
            token_path.chmod(0o644)

            with self.assertRaisesRegex(
                ValueError,
                "CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE",
            ):
                api._load_remote_bearer_token(token_path)

    def test_remote_bind_refuses_missing_bearer_token_file_before_binding(self):
        with (
            mock.patch.dict(
                api.os.environ,
                {"CRYPTO_OPTIONS_API_ALLOW_REMOTE": "1"},
                clear=False,
            ),
            mock.patch.object(api, "ResearchHTTPServer") as server_class,
            self.assertRaisesRegex(SystemExit, "CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE"),
        ):
            api.serve("0.0.0.0", 8000, runtime=api.RuntimeConfig())

        server_class.assert_not_called()

    def test_loopback_bind_keeps_default_ux_without_remote_token_file(self):
        fake_server = mock.Mock()
        fake_server.server_port = 8000
        with (
            mock.patch.dict(
                api.os.environ,
                {
                    "CRYPTO_OPTIONS_API_ALLOW_REMOTE": "",
                    "CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE": "",
                },
                clear=False,
            ),
            mock.patch.object(api, "ResearchHTTPServer", return_value=fake_server) as server_class,
            mock.patch.object(api, "_log_json"),
        ):
            api.serve("127.0.0.1", 8000, runtime=api.RuntimeConfig())

        self.assertIsNone(server_class.call_args.kwargs["bearer_token"])
        fake_server.serve_forever.assert_called_once_with()
        fake_server.server_close.assert_called()

    def test_remote_bind_refuses_invalid_bearer_token_without_leaking_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "api-token.txt"
            leaked_token = "bad token with spaces"
            token_path.write_text(leaked_token, encoding="utf-8")
            with self.assertRaisesRegex(
                SystemExit,
                "CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE",
            ) as raised, mock.patch.dict(
                api.os.environ,
                {
                    "CRYPTO_OPTIONS_API_ALLOW_REMOTE": "1",
                    "CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE": str(token_path),
                },
                clear=False,
            ), mock.patch.object(api, "ResearchHTTPServer") as server_class:
                api.serve("0.0.0.0", 8000, runtime=api.RuntimeConfig())

            server_class.assert_not_called()
            self.assertNotIn(leaked_token, str(raised.exception))

    def test_remote_bearer_auth_exempts_only_health_and_readiness_probes(self):
        token = "R" * 32
        server = api.ResearchHTTPServer(
            ("127.0.0.1", 0),
            api.ResearchReportHandler,
            runtime=api.RuntimeConfig(),
            bearer_token=token,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/health")
            health = connection.getresponse()
            health_payload = json.loads(health.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/livez")
            live = connection.getresponse()
            live_payload = json.loads(live.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/readyz")
            ready = connection.getresponse()
            ready_payload = json.loads(ready.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/dashboard.html")
            protected = connection.getresponse()
            protected_payload = json.loads(protected.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("POST", "/livez")
            non_get_probe = connection.getresponse()
            non_get_probe_payload = json.loads(non_get_probe.read().decode("utf-8"))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(200, health.status)
        self.assertEqual({"status": "ok"}, health_payload)
        self.assertEqual(200, live.status)
        self.assertEqual({"status": "alive"}, live_payload)
        self.assertEqual(200, ready.status)
        self.assertTrue(ready_payload["service_ready"])
        self.assertEqual(401, protected.status)
        self.assertEqual("Bearer", protected.getheader("WWW-Authenticate"))
        self.assertEqual("authentication_required", protected_payload["error"])
        self.assertEqual(401, non_get_probe.status)
        self.assertEqual("Bearer", non_get_probe.getheader("WWW-Authenticate"))
        self.assertEqual("authentication_required", non_get_probe_payload["error"])

    def test_remote_bearer_auth_rejects_ambiguous_security_headers(self):
        token = "V" * 32
        server = api.ResearchHTTPServer(
            ("127.0.0.1", 0),
            api.ResearchReportHandler,
            runtime=api.RuntimeConfig(),
            bearer_token=token,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.putrequest("GET", "/research/report", skip_host=True)
            connection.putheader("Host", f"127.0.0.1:{server.server_port}")
            connection.putheader("Host", "evil.example")
            connection.putheader("Authorization", f"Bearer {token}")
            connection.endheaders()
            duplicate_host = connection.getresponse()
            duplicate_host_payload = json.loads(
                duplicate_host.read().decode("utf-8")
            )
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.putrequest("GET", "/research/report")
            connection.putheader("Authorization", f"Bearer {token}")
            connection.putheader("Authorization", "Bearer attacker-controlled")
            connection.endheaders()
            duplicate_authorization = connection.getresponse()
            duplicate_authorization_payload = json.loads(
                duplicate_authorization.read().decode("utf-8")
            )
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.putrequest("POST", "/backtest/run")
            connection.putheader("Authorization", f"Bearer {token}")
            connection.putheader("Origin", "http://127.0.0.1")
            connection.putheader("Origin", "https://evil.example")
            connection.putheader("Content-Length", "0")
            connection.endheaders()
            duplicate_origin = connection.getresponse()
            duplicate_origin_payload = json.loads(
                duplicate_origin.read().decode("utf-8")
            )
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(400, duplicate_host.status)
        self.assertEqual("invalid_host_header", duplicate_host_payload["error"])
        self.assertEqual(400, duplicate_authorization.status)
        self.assertEqual(
            "invalid_authorization_header",
            duplicate_authorization_payload["error"],
        )
        self.assertEqual(400, duplicate_origin.status)
        self.assertEqual("invalid_origin_header", duplicate_origin_payload["error"])

    def test_unsupported_methods_pass_through_remote_auth_gate(self):
        token = "W" * 32
        server = api.ResearchHTTPServer(
            ("127.0.0.1", 0),
            api.ResearchReportHandler,
            runtime=api.RuntimeConfig(),
            bearer_token=token,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("TRACE", "/research/report")
            unauthorized = connection.getresponse()
            unauthorized_payload = json.loads(unauthorized.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request(
                "TRACE",
                "/research/report",
                headers={"Authorization": f"Bearer {token}"},
            )
            authorized = connection.getresponse()
            authorized_payload = json.loads(authorized.read().decode("utf-8"))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(401, unauthorized.status)
        self.assertEqual("Bearer", unauthorized.getheader("WWW-Authenticate"))
        self.assertEqual("authentication_required", unauthorized_payload["error"])
        self.assertEqual(405, authorized.status)
        self.assertEqual("method_not_allowed", authorized_payload["error"])

    def test_server_constructor_cannot_bypass_remote_bearer_invariant(self):
        with self.assertRaisesRegex(ValueError, "require a bearer token"):
            api.ResearchHTTPServer(
                ("0.0.0.0", 0),
                api.ResearchReportHandler,
                runtime=api.RuntimeConfig(),
            )

    def test_remote_bearer_auth_rejects_missing_or_invalid_credentials_before_body_work(self):
        token = "S" * 32
        server = api.ResearchHTTPServer(
            ("127.0.0.1", 0),
            api.ResearchReportHandler,
            runtime=api.RuntimeConfig(),
            bearer_token=token,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/research/report")
            report = connection.getresponse()
            report_payload = json.loads(report.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/dashboard", headers={"Authorization": "Bearer wrong"})
            dashboard = connection.getresponse()
            dashboard_payload = json.loads(dashboard.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/backtest/jobs/job-" + "a" * 64)
            job = connection.getresponse()
            job_payload = json.loads(job.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/not-a-route")
            unknown = connection.getresponse()
            unknown_payload = json.loads(unknown.read().decode("utf-8"))
            connection.close()

            with mock.patch.object(
                api.ResearchReportHandler,
                "_read_backtest_request",
                side_effect=AssertionError("request body should not be read before auth"),
            ):
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=5
                )
                connection.request(
                    "POST",
                    "/backtest/run",
                    body=b"not-json",
                    headers={"Content-Type": "text/plain"},
                )
                post = connection.getresponse()
                post_payload = json.loads(post.read().decode("utf-8"))
                connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("HEAD", "/research/report")
            head = connection.getresponse()
            head.read()
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("DELETE", "/backtest/jobs/job-" + "a" * 64)
            delete = connection.getresponse()
            delete_payload = json.loads(delete.read().decode("utf-8"))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        for response, payload in (
            (report, report_payload),
            (dashboard, dashboard_payload),
            (job, job_payload),
            (unknown, unknown_payload),
            (post, post_payload),
            (delete, delete_payload),
        ):
            self.assertEqual(401, response.status)
            self.assertEqual("Bearer", response.getheader("WWW-Authenticate"))
            self.assertEqual("authentication_required", payload["error"])
        self.assertEqual(401, head.status)
        self.assertEqual("Bearer", head.getheader("WWW-Authenticate"))


    def test_remote_bearer_auth_accepts_valid_credentials_for_protected_routes(self):
        token = "T" * 32
        server = api.ResearchHTTPServer(
            ("127.0.0.1", 0),
            api.ResearchReportHandler,
            runtime=api.RuntimeConfig(),
            bearer_token=token,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/research/report", headers=headers)
            report = connection.getresponse()
            report_payload = json.loads(report.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request("GET", "/dashboard.html", headers=headers)
            dashboard_page = connection.getresponse()
            dashboard_body = dashboard_page.read().decode("utf-8")
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request(
                "POST",
                "/backtest/run",
                body=b'{"schema_version":"backtest_run_request.v1"}',
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "Idempotency-Key": "authorized-request",
                },
            )
            post = connection.getresponse()
            post_payload = json.loads(post.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request(
                "GET",
                "/backtest/jobs/job-" + "a" * 64,
                headers=headers,
            )
            job = connection.getresponse()
            job_payload = json.loads(job.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request(
                "GET",
                "/not-a-route",
                headers=headers,
            )
            unknown = connection.getresponse()
            unknown_payload = json.loads(unknown.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request(
                "DELETE",
                "/backtest/jobs/job-" + "a" * 64,
                headers=headers,
            )
            delete = connection.getresponse()
            delete_payload = json.loads(delete.read().decode("utf-8"))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(200, report.status)
        self.assertEqual("research_report.v1", report_payload["schema_version"])
        self.assertEqual(200, dashboard_page.status)
        self.assertIn("LensOS Option", dashboard_body)
        self.assertIn("/evidence/assets/", dashboard_body)
        self.assertEqual(409, post.status)
        self.assertEqual("historical_data_not_configured", post_payload["status"])
        self.assertEqual(404, job.status)
        self.assertEqual("backtest_job_not_found", job_payload["error"])
        self.assertEqual(404, unknown.status)
        self.assertEqual("not_found", unknown_payload["error"])
        self.assertEqual(404, delete.status)
        self.assertEqual("backtest_job_not_found", delete_payload["error"])

    def test_loopback_extension_origin_can_read_reports_but_cannot_mutate(self):
        server = api.ResearchHTTPServer(
            ("127.0.0.1", 0),
            api.ResearchReportHandler,
            runtime=api.RuntimeConfig(),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        extension_headers = {"Origin": "chrome-extension://local-research-client"}
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request(
                "GET",
                "/research/report",
                headers=extension_headers,
            )
            report = connection.getresponse()
            report_payload = json.loads(report.read().decode("utf-8"))
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request(
                "POST",
                "/backtest/run",
                body=b'{"schema_version":"backtest_run_request.v1"}',
                headers={
                    **extension_headers,
                    "Content-Type": "application/json",
                    "Idempotency-Key": "extension-must-remain-read-only",
                },
            )
            mutation = connection.getresponse()
            mutation_payload = json.loads(mutation.read().decode("utf-8"))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(200, report.status)
        self.assertEqual("research_report.v1", report_payload["schema_version"])
        self.assertEqual(403, mutation.status)
        self.assertEqual(
            "cross_origin_request_rejected",
            mutation_payload["error"],
        )

    def test_remote_bearer_auth_does_not_leak_tokens_in_responses_or_logs(self):
        token = "U" * 32
        supplied_secret = "client-supplied-secret"
        server = api.ResearchHTTPServer(
            ("127.0.0.1", 0),
            api.ResearchReportHandler,
            runtime=api.RuntimeConfig(access_log=True),
            bearer_token=token,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(api, "_log_json") as log_json:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=5
                )
                connection.request(
                    "GET",
                    "/research/report",
                    headers={"Authorization": f"Bearer {supplied_secret}"},
                )
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                headers = dict(response.getheaders())
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(401, response.status)
        serialized = json.dumps(
            {
                "body": body,
                "headers": headers,
                "logs": [
                    {
                        "args": call.args,
                        "kwargs": call.kwargs,
                    }
                    for call in log_json.call_args_list
                ],
            },
            sort_keys=True,
            default=str,
        )
        self.assertNotIn(token, serialized)
        self.assertNotIn(supplied_secret, serialized)

    def test_arbitrary_dns_name_cannot_self_certify_as_a_loopback_bind(self):
        loopback_answer = [
            (
                api.socket.AF_INET,
                api.socket.SOCK_STREAM,
                api.socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", 0),
            )
        ]
        with mock.patch.object(
            api.socket,
            "getaddrinfo",
            return_value=loopback_answer,
        ) as resolver:
            self.assertFalse(api._is_loopback_host("controlled.example"))

        resolver.assert_not_called()

    def test_mutating_request_origin_must_match_the_host_port(self):
        self.assertTrue(
            api._origin_matches_host(
                "http://localhost:8000",
                "localhost:8000",
            )
        )
        self.assertFalse(
            api._origin_matches_host(
                "http://localhost:9999",
                "localhost:8000",
            )
        )
        self.assertFalse(
            api._origin_matches_host(
                "http://localhost",
                "localhost:8000",
            )
        )

    def test_direct_http_origin_rejects_cross_scheme_authority_by_default(self):
        with mock.patch.dict(
            api.os.environ,
            {"CRYPTO_OPTIONS_API_TRUSTED_ORIGINS": ""},
            clear=False,
        ):
            self.assertFalse(
                api._origin_matches_host(
                    "https://localhost:8000",
                    "localhost:8000",
                )
            )

    def test_non_http_origin_requires_an_exact_trusted_origin(self):
        with mock.patch.dict(
            api.os.environ,
            {
                "CRYPTO_OPTIONS_API_TRUSTED_ORIGINS": (
                    "https://localhost:8000,app://localhost:8000"
                )
            },
            clear=False,
        ):
            self.assertTrue(
                api._origin_matches_host(
                    "https://localhost:8000",
                    "localhost:8000",
                )
            )
            self.assertTrue(
                api._origin_matches_host(
                    "app://localhost:8000",
                    "localhost:8000",
                )
            )
            self.assertFalse(
                api._origin_matches_host(
                    "https://localhost:8001",
                    "localhost:8000",
                )
            )
            self.assertFalse(
                api._origin_matches_host(
                    "https://127.0.0.1:8000",
                    "localhost:8000",
                )
            )

    def test_https_only_external_origin_rejects_http_while_loopback_http_remains(self):
        with mock.patch.dict(
            api.os.environ,
            {
                "CRYPTO_OPTIONS_API_TRUSTED_ORIGINS": (
                    "https://research.internal:8443,"
                    "http://research.internal:8443"
                )
            },
            clear=False,
        ):
            self.assertTrue(
                api._origin_matches_host(
                    "https://research.internal:8443",
                    "research.internal:8443",
                )
            )
            self.assertFalse(
                api._origin_matches_host(
                    "http://research.internal:8443",
                    "research.internal:8443",
                )
            )
            self.assertTrue(
                api._origin_matches_host(
                    "http://localhost:8000",
                    "localhost:8000",
                )
            )

    def test_deribit_credentials_never_appear_in_request_urls(self):
        responses = iter(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "access_token": "access-token-never-in-url",
                        "scope": "account:read trade:read",
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "currency": "BTC",
                        "portfolio_margining_enabled": False,
                        "equity": 1.0,
                        "balance": 1.0,
                        "margin_balance": 1.0,
                        "available_funds": 0.8,
                        "initial_margin": 0.1,
                        "maintenance_margin": 0.05,
                    },
                },
                {"jsonrpc": "2.0", "id": 1, "result": []},
                {"jsonrpc": "2.0", "id": 1, "result": []},
            ]
        )
        requests = []

        def open_request(request, *, timeout):
            self.assertEqual(20, timeout)
            requests.append(request)
            return _JsonResponse(next(responses))

        with mock.patch.object(
            account_snapshot_sidecar,
            "urlopen",
            side_effect=open_request,
        ):
            account_snapshot_sidecar.fetch_deribit_account_snapshot(
                client_id="client-id-never-in-url",
                client_secret="client-secret-never-in-url",
            )

        self.assertEqual(4, len(requests))
        self.assertTrue(all(request.get_method() == "POST" for request in requests))
        self.assertTrue(
            all(
                request.full_url == "https://www.deribit.com/api/v2"
                for request in requests
            )
        )

        auth_payload = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual("public/auth", auth_payload["method"])
        self.assertEqual(
            "client-secret-never-in-url",
            auth_payload["params"]["client_secret"],
        )
        self.assertIsNone(requests[0].get_header("Authorization"))

        for request in requests[1:]:
            private_payload = json.loads(request.data.decode("utf-8"))
            self.assertTrue(private_payload["method"].startswith("private/"))
            self.assertNotIn("access_token", private_payload["params"])
            self.assertEqual(
                "Bearer access-token-never-in-url",
                request.get_header("Authorization"),
            )

        request_urls = "\n".join(request.full_url for request in requests)
        self.assertNotIn("client-id-never-in-url", request_urls)
        self.assertNotIn("client-secret-never-in-url", request_urls)
        self.assertNotIn("access-token-never-in-url", request_urls)

    def test_deribit_transport_rejects_redirects_before_following_them(self):
        class RedirectHandler(BaseHTTPRequestHandler):
            target_hits = 0

            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()

            def do_GET(self):
                type(self).target_hits += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/start",
                data=b"{}",
                method="POST",
            )
            with self.assertRaises(HTTPError):
                account_snapshot_sidecar.urlopen(request, timeout=5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(0, RedirectHandler.target_hits)

    def test_public_market_transport_rejects_redirects_before_following_them(self):
        class RedirectHandler(BaseHTTPRequestHandler):
            target_hits = 0

            def do_GET(self):
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/redirect-target")
                    self.end_headers()
                    return
                type(self).target_hits += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"result":{"source":"internal"}}')

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}/start")
            with self.assertRaises(HTTPError):
                market_data.urlopen(request, timeout=5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(0, RedirectHandler.target_hits)

    def test_webhook_signature_binds_delivery_timestamp_id_and_body(self):
        requests = []

        def open_request(request, *, timeout):
            self.assertEqual(10, timeout)
            requests.append(request)
            return _JsonResponse({})

        with mock.patch.object(alerts, "urlopen", side_effect=open_request):
            result = alerts.deliver_webhook(
                {
                    "generated_at": "2026-07-14T00:00:00Z",
                    "summary": {"critical": 1},
                    "events": [{"rule_id": "data_quality.blocked"}],
                },
                url="https://alerts.example.invalid/hooks/research",
                secret="webhook-signing-secret",
            )

        self.assertEqual("delivered", result["status"])
        self.assertEqual(1, len(requests))
        request = requests[0]
        headers = {name.lower(): value for name, value in request.header_items()}
        delivery_timestamp = headers.get("x-webhook-timestamp")
        delivery_id = headers.get("x-webhook-delivery-id")
        self.assertIsNotNone(delivery_timestamp)
        self.assertIsNotNone(delivery_id)
        self.assertTrue(delivery_timestamp.isdecimal())
        uuid.UUID(delivery_id)

        signed_message = (
            delivery_timestamp.encode("ascii")
            + b"."
            + delivery_id.encode("ascii")
            + b"."
            + request.data
        )
        expected_signature = hmac.new(
            b"webhook-signing-secret",
            signed_message,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(
            expected_signature,
            headers.get("x-signature-sha256"),
        )
        body_only_signature = hmac.new(
            b"webhook-signing-secret",
            request.data,
            hashlib.sha256,
        ).hexdigest()
        self.assertNotEqual(
            body_only_signature,
            headers.get("x-signature-sha256"),
        )

    def test_webhook_rejects_userinfo_and_redacts_dry_run_url_secrets(self):
        evaluation = {
            "generated_at": "2026-07-14T00:00:00Z",
            "summary": {"critical": 0},
            "events": [],
        }

        with self.assertRaisesRegex(ValueError, "userinfo"):
            alerts.deliver_webhook(
                evaluation,
                url="https://operator:secret@alerts.example.invalid/hook",
                dry_run=True,
            )

        result = alerts.deliver_webhook(
            evaluation,
            url="https://alerts.example.invalid/hooks/research?token=secret#fragment",
            dry_run=True,
        )

        self.assertEqual(
            "https://alerts.example.invalid",
            result["url"],
        )
        self.assertNotIn("hooks", json.dumps(result, sort_keys=True))
        self.assertNotIn("secret", json.dumps(result, sort_keys=True))

    def test_webhook_transport_rejects_redirects_before_following_them(self):
        class RedirectHandler(BaseHTTPRequestHandler):
            target_hits = 0

            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()

            def do_GET(self):
                type(self).target_hits += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/start",
                data=b"{}",
                method="POST",
            )
            with self.assertRaises(HTTPError):
                alerts.urlopen(request, timeout=5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(0, RedirectHandler.target_hits)

    def test_container_image_defaults_to_loopback_without_remote_opt_in(self):
        dockerfile = (self.REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertNotIn("CRYPTO_OPTIONS_API_ALLOW_REMOTE", dockerfile)
        self.assertIn('"--host", "127.0.0.1"', dockerfile)
        self.assertNotIn('"--host", "0.0.0.0"', dockerfile)

    def test_container_ci_makes_remote_bind_an_explicit_opt_in(self):
        workflow = (self.REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("--env CRYPTO_OPTIONS_API_ALLOW_REMOTE=1", workflow)
        self.assertIn("CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE", workflow)
        self.assertIn("--mount type=bind", workflow)
        self.assertIn("--host 0.0.0.0", workflow)

    def test_ci_and_container_inputs_use_immutable_identities(self):
        workflow_dir = self.REPO_ROOT / ".github" / "workflows"
        workflow_violations = []
        workflow_paths = sorted(workflow_dir.glob("*.yml")) + sorted(
            workflow_dir.glob("*.yaml")
        )
        for workflow_path in workflow_paths:
            for line_number, line in enumerate(
                workflow_path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                match = re.match(r"^\s*-\s+uses:\s+([^#\s]+)", line)
                if not match:
                    continue
                reference = match.group(1)
                if reference.startswith("./"):
                    continue
                if not self.FULL_GITHUB_ACTION_SHA.fullmatch(reference):
                    workflow_violations.append(
                        f"{workflow_path.relative_to(self.REPO_ROOT)}:{line_number}:{reference}"
                    )

        self.assertEqual([], workflow_violations)

        docker_violations = []
        for dockerfile_path in sorted(self.REPO_ROOT.glob("Dockerfile*")):
            stage_aliases = set()
            for line_number, line in enumerate(
                dockerfile_path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                match = re.match(
                    r"^\s*FROM\s+([^\s]+)(?:\s+AS\s+([A-Za-z0-9_.-]+))?\s*$",
                    line,
                    flags=re.IGNORECASE,
                )
                if not match:
                    continue
                base_ref, stage_alias = match.groups()
                if base_ref != "scratch" and base_ref not in stage_aliases:
                    if not self.FULL_IMAGE_DIGEST.fullmatch(base_ref):
                        docker_violations.append(
                            f"{dockerfile_path.relative_to(self.REPO_ROOT)}:{line_number}:{base_ref}"
                        )
                if stage_alias:
                    stage_aliases.add(stage_alias)

        self.assertEqual([], docker_violations)

    def test_operator_docs_expose_transport_security_contracts(self):
        readme = (self.REPO_ROOT / "README.md").read_text(encoding="utf-8")
        runbook = (
            self.REPO_ROOT / "docs" / "operations" / "production-runbook.md"
        ).read_text(encoding="utf-8")
        operator_docs = readme + "\n" + runbook

        self.assertIn("JSON-RPC POST", operator_docs)
        self.assertIn("Authorization: Bearer", operator_docs)
        self.assertIn("X-Webhook-Timestamp", operator_docs)
        self.assertIn("X-Webhook-Delivery-Id", operator_docs)
        self.assertIn("timestamp.delivery_id.body", operator_docs)
        self.assertIn("--env CRYPTO_OPTIONS_API_ALLOW_REMOTE=1", runbook)
        self.assertIn("CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE", operator_docs)
        self.assertIn("--host 0.0.0.0", runbook)
        self.assertIn("--publish 127.0.0.1:8000:8000", runbook)
        self.assertIn("Authorization", runbook)
        self.assertIn("proxy_set_header Authorization", runbook)
        self.assertIn("CRYPTO_OPTIONS_API_ALLOWED_HOSTS", operator_docs)
        self.assertIn("CRYPTO_OPTIONS_API_TRUSTED_ORIGINS", operator_docs)
        self.assertIn("https://research.example.internal", runbook)
        self.assertIn(
            "New-Item -ItemType Directory -Force -Path (Split-Path $marketKeyPath)",
            runbook,
        )
        self.assertIn(
            "New-Item -ItemType Directory -Force -Path (Split-Path $accountKeyPath)",
            runbook,
        )


if __name__ == "__main__":
    unittest.main()
