from __future__ import annotations

import http.client
import io
import json
import socket
import threading
from pathlib import Path
from unittest import mock

import pytest

from crypto_options_report import local_app
from crypto_options_report.api import ResearchReportHandler
from crypto_options_report.cli import build_parser
from crypto_options_report.cli import main as cli_main
from crypto_options_report.demo import DEMO_HOST, DemoHTTPServer

SNAPSHOT = Path(__file__).parent / "fixtures" / "deribit_btc_option_chain_snapshot.json"


def test_start_rejects_mixed_current_and_historical_sources() -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["start", "--current", "--snapshot", str(SNAPSHOT)])
    assert exc.value.code == 2
    with pytest.raises(ValueError, match="choose --current or --snapshot"):
        with local_app.local_runtime(current=True, snapshot=str(SNAPSHOT)):
            raise AssertionError("mixed source mode was accepted")


@pytest.mark.parametrize("snapshot", [None, str(SNAPSHOT)])
def test_start_demo_and_history_are_offline_and_declare_their_clocks(
    snapshot: str | None,
) -> None:
    with mock.patch(
        "crypto_options_report.api.fetch_deribit_option_chain_snapshot",
        side_effect=AssertionError("offline mode attempted a public fetch"),
    ) as public_fetch:
        with local_app.local_runtime(snapshot=snapshot) as runtime:
            server = DemoHTTPServer(
                (DEMO_HOST, 0),
                ResearchReportHandler,
                runtime=runtime,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection(DEMO_HOST, server.server_port, timeout=10)
            try:
                connection.request("GET", "/research/report")
                response = connection.getresponse()
                report = json.loads(response.read())
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    assert response.status == 200
    assert report["runtime_context"]["replay"] is True
    assert report["runtime_context"]["demo_mode"] is (snapshot is None)
    assert report["runtime_context"]["evaluation_clock"]
    assert report["runtime_context"]["live_fetch_allowed"] is False
    public_fetch.assert_not_called()


def test_current_start_stays_loopback_and_waits_for_a_browser_request() -> None:
    server = mock.Mock(server_port=8123)
    server.serve_forever.side_effect = KeyboardInterrupt
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        mock.patch.object(local_app, "DemoHTTPServer", return_value=server) as create_server,
        mock.patch("crypto_options_report.api.fetch_deribit_option_chain_snapshot") as public_fetch,
        mock.patch.dict("os.environ", {"CRYPTO_OPTIONS_API_ALLOW_REMOTE": "1"}),
    ):
        result = local_app.run_start(
            port=8123,
            current=True,
            open_browser=False,
            stdout=stdout,
            stderr=stderr,
        )

    assert result == 0
    assert create_server.call_args.args == (("127.0.0.1", 8123), ResearchReportHandler)
    runtime = create_server.call_args.kwargs["runtime"]
    assert runtime.allow_live_fetch is True
    assert runtime.snapshot_fixture is None
    assert runtime.replay is False
    assert runtime.account_snapshot_fixture is None
    assert runtime.paper_ledger_path is None
    public_fetch.assert_not_called()
    server.server_close.assert_called_once_with()
    assert "/index.html?view=desk&mode=live" in stdout.getvalue()
    assert "Deribit public data" in stdout.getvalue()
    assert "execution_allowed=false" in stdout.getvalue()


def test_start_rejects_an_unscoped_underlying_history() -> None:
    with pytest.raises(ValueError, match="requires --current or --snapshot"):
        with local_app.local_runtime(underlying_history="history.json"):
            raise AssertionError("ignored local history was accepted")


def test_cli_start_opens_the_offline_platform_by_default() -> None:
    with mock.patch("crypto_options_report.local_app.run_start", return_value=0) as run_start:
        result = cli_main(["start"])

    assert result == 0
    run_start.assert_called_once_with(
        port=8000,
        open_browser=True,
        current=False,
        snapshot=None,
        underlying_history=None,
    )


def test_start_reports_an_occupied_port_without_launching_a_browser() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((DEMO_HOST, 0))
    listener.listen(1)
    try:
        with mock.patch.object(local_app.webbrowser, "open") as open_browser:
            result = local_app.run_start(
                port=listener.getsockname()[1],
                stdout=stdout,
                stderr=stderr,
            )
    finally:
        listener.close()

    assert result == 1
    assert stdout.getvalue() == ""
    assert "already in use" in stderr.getvalue()
    assert "choose another port with --port" in stderr.getvalue()
    open_browser.assert_not_called()
