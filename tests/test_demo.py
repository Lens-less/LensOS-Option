from __future__ import annotations

import http.client
import io
import json
import socket
import threading
from unittest import mock

from crypto_options_report import demo
from crypto_options_report.api import ResearchHTTPServer, ResearchReportHandler
from crypto_options_report.cli import build_parser
from crypto_options_report.cli import main as cli_main


def test_cli_parser_exposes_demo_subcommand() -> None:
    args = build_parser().parse_args(["demo", "--port", "8765"])

    assert args.command == "demo"
    assert args.port == 8765
    assert args.open_browser is False


def test_demo_runtime_serves_packaged_snapshot_without_network() -> None:
    with demo.demo_runtime() as runtime:
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=runtime,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report_status, _, report_body = _request(server.server_port, "/research/report")
            signal_status, _, signal_body = _request(server.server_port, "/research/signal")
            series_status, _, series_body = _request(server.server_port, "/research/series")
            page_status, page_headers, page_body = _request(
                server.server_port,
                "/index.html?view=workbench",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    report = json.loads(report_body.decode("utf-8"))
    signal = json.loads(signal_body.decode("utf-8"))
    series = json.loads(series_body.decode("utf-8"))

    assert report_status == 200
    assert report["runtime_context"]["replay"] is True
    assert report["runtime_context"]["demo_mode"] is True
    assert report["runtime_context"]["snapshot_fixture"] == "packaged:demo-snapshot.json"
    assert report["data_status"]["source"].startswith("demo:")
    assert "Bundled demo snapshot" in report["runtime_context"]["notice"]
    assert signal_status == 200
    assert signal["status"] == "projected"
    assert series_status == 200
    assert series["status"] == "blocked"
    assert page_status == 200
    assert page_headers["content-type"] == "text/html; charset=utf-8"
    assert b'<div id="root"></div>' in page_body


def test_cli_demo_delegates_to_demo_module() -> None:
    with mock.patch("crypto_options_report.demo.run_demo", return_value=0) as run_demo:
        exit_code = cli_main(["demo", "--port", "8123"])

    assert exit_code == 0
    run_demo.assert_called_once_with(port=8123, open_browser=False)


def test_demo_reports_port_conflict_clearly() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((demo.DEMO_HOST, 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        exit_code = demo.run_demo(
            port=port,
            open_browser=False,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        listener.close()

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert "already in use" in stderr.getvalue()
    assert "choose another port" in stderr.getvalue()
    assert demo.DEMO_HOST in stderr.getvalue()


def test_demo_server_rejects_a_second_demo_on_the_same_port() -> None:
    with demo.demo_runtime() as runtime:
        server = demo.DemoHTTPServer(
            (demo.DEMO_HOST, 0),
            ResearchReportHandler,
            runtime=runtime,
        )
        duplicate = None
        try:
            try:
                duplicate = demo.DemoHTTPServer(
                    (demo.DEMO_HOST, server.server_port),
                    ResearchReportHandler,
                    runtime=runtime,
                )
            except OSError as exc:
                assert demo._is_address_in_use(exc)
            else:
                raise AssertionError("a second demo unexpectedly reused the occupied port")
        finally:
            if duplicate is not None:
                duplicate.server_close()
            server.server_close()


def test_demo_server_can_restart_on_the_same_port_after_serving_a_request() -> None:
    with demo.demo_runtime() as runtime:
        server = demo.DemoHTTPServer(
            (demo.DEMO_HOST, 0),
            ResearchReportHandler,
            runtime=runtime,
        )
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, _, _ = _request(port, "/status.html")
            assert status == 200
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        restarted = demo.DemoHTTPServer(
            (demo.DEMO_HOST, port),
            ResearchReportHandler,
            runtime=runtime,
        )
        restarted.server_close()


def test_demo_ctrl_c_shuts_down_cleanly() -> None:
    server = mock.Mock(server_port=8000)
    server.serve_forever.side_effect = KeyboardInterrupt
    stdout = io.StringIO()
    stderr = io.StringIO()

    with mock.patch.object(demo, "DemoHTTPServer", return_value=server):
        exit_code = demo.run_demo(
            port=8000,
            open_browser=False,
            stdout=stdout,
            stderr=stderr,
        )

    assert exit_code == 0
    server.server_close.assert_called_once_with()
    assert "Press Ctrl+C to stop" in stdout.getvalue()
    assert "Stopping LensOS Option demo" in stderr.getvalue()


def _request(
    port: int,
    path: str,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        return response.status, headers, response.read()
    finally:
        connection.close()
