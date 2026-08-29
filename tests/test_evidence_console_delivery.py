import http.client
import re
import threading
import unittest

from crypto_options_report.api import (
    EVIDENCE_PAGE_PATH,
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
)


class EvidenceConsoleDeliveryTests(unittest.TestCase):
    def test_public_navigation_aliases_serve_every_clickable_page_without_404(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="development"),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            html_paths = {
                "/": '<div id="root"></div>',
                "/index.html": '<div id="root"></div>',
                "/index.html?view=workbench": '<div id="root"></div>',
                EVIDENCE_PAGE_PATH: '<div id="root"></div>',
                f"{EVIDENCE_PAGE_PATH}/": '<div id="root"></div>',
                f"{EVIDENCE_PAGE_PATH}/index.html?view=signal": '<div id="root"></div>',
                "/methodology.html": "LensOS Option",
                f"{EVIDENCE_PAGE_PATH}/methodology.html": "LensOS Option",
                "/disclaimer.html": "LensOS Option / research only",
                f"{EVIDENCE_PAGE_PATH}/disclaimer.html": "LensOS Option / research only",
                "/privacy.html": "loopback",
                f"{EVIDENCE_PAGE_PATH}/privacy.html": "loopback",
                "/terms.html": "LensOS Option",
                f"{EVIDENCE_PAGE_PATH}/terms.html": "LensOS Option",
                "/status.html": "LOCAL_PREVIEW",
                f"{EVIDENCE_PAGE_PATH}/status.html": "LOCAL_PREVIEW",
                "/en/methodology.html": "Methodology",
                f"{EVIDENCE_PAGE_PATH}/en/methodology.html": "Methodology",
                "/en/disclaimer.html": "Disclaimer",
                f"{EVIDENCE_PAGE_PATH}/en/disclaimer.html": "Disclaimer",
                "/en/privacy.html": "Privacy",
                f"{EVIDENCE_PAGE_PATH}/en/privacy.html": "Privacy",
                "/en/terms.html": "Terms",
                f"{EVIDENCE_PAGE_PATH}/en/terms.html": "Terms",
                "/en/status.html": "LOCAL_PREVIEW",
                f"{EVIDENCE_PAGE_PATH}/en/status.html": "LOCAL_PREVIEW",
            }
            for path, expected in html_paths.items():
                with self.subTest(path=path):
                    status, headers, body = self._request(server.server_port, path)
                    self.assertEqual(200, status)
                    self.assertEqual(
                        "text/html; charset=utf-8",
                        headers["content-type"],
                    )
                    self.assertIn(expected, body.decode("utf-8"))

            for path in (
                "/static-page.css",
                f"{EVIDENCE_PAGE_PATH}/static-page.css",
                f"{EVIDENCE_PAGE_PATH}/en/static-page.css",
            ):
                with self.subTest(path=path):
                    status, headers, body = self._request(server.server_port, path)
                    self.assertEqual(200, status)
                    self.assertEqual("text/css; charset=utf-8", headers["content-type"])
                    self.assertIn(b".page-shell", body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_evidence_page_and_built_assets_are_served_from_the_same_origin(self):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="development"),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            page_status, page_headers, page_body = self._request(
                server.server_port,
                EVIDENCE_PAGE_PATH,
            )
            asset_paths = re.findall(
                rb'(?:href|src)="(/evidence/assets/[^"]+)"',
                page_body,
            )

            self.assertEqual(200, page_status)
            self.assertEqual(
                "text/html; charset=utf-8",
                page_headers["content-type"],
            )
            self.assertIn(b'<div id="root"></div>', page_body)
            self.assertEqual(2, len(asset_paths))
            self.assertIn("script-src 'self'", page_headers["content-security-policy"])
            self.assertNotIn(
                "'unsafe-inline'",
                page_headers["content-security-policy"],
            )

            for raw_path in asset_paths:
                status, headers, body = self._request(
                    server.server_port,
                    raw_path.decode("ascii"),
                )
                self.assertEqual(200, status)
                self.assertTrue(body)
                self.assertEqual("nosniff", headers["x-content-type-options"])
                if raw_path.endswith(b".js"):
                    self.assertEqual(
                        "text/javascript; charset=utf-8",
                        headers["content-type"],
                    )
                    self.assertIn(b"/research/report", body)
                else:
                    self.assertEqual(
                        "text/css; charset=utf-8",
                        headers["content-type"],
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_evidence_routes_inherit_authentication_and_reject_unknown_assets(self):
        token = "T" * 32
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=RuntimeConfig(profile="development"),
            bearer_token=token,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            unauthorized_status, _, _ = self._request(
                server.server_port,
                EVIDENCE_PAGE_PATH,
            )
            missing_status, _, missing_body = self._request(
                server.server_port,
                "/evidence/assets/%2e%2e%2findex.html",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(401, unauthorized_status)
        self.assertEqual(404, missing_status)
        self.assertEqual(b'{"error": "not_found"}', missing_body)

    @staticmethod
    def _request(
        port: int,
        path: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            headers = {name.lower(): value for name, value in response.getheaders()}
            return response.status, headers, response.read()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
