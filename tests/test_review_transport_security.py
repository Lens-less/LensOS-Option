import hashlib
import hmac
import json
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
                account_snapshot_sidecar.urlopen(request, timeout=2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

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
                market_data.urlopen(request, timeout=2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

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
                alerts.urlopen(request, timeout=2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

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
        self.assertIn("--host 0.0.0.0", workflow)

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
        self.assertIn("--host 0.0.0.0", runbook)
        self.assertIn("--publish 127.0.0.1:8000:8000", runbook)
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
