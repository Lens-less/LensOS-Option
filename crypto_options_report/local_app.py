"""One loopback-only entry point for demo, recorded, and current research."""

from __future__ import annotations

import sys
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TextIO

from .api import ResearchReportHandler, RuntimeConfig
from .demo import DEMO_HOST, DemoHTTPServer, _is_address_in_use, demo_runtime

RESEARCH_URL_PATH = "/index.html?view=evidence"
DEMO_URL_PATH = "/index.html?view=demo"


@contextmanager
def local_runtime(
    *,
    current: bool = False,
    snapshot: str | None = None,
    underlying_history: str | None = None,
) -> Iterator[RuntimeConfig]:
    """Choose a declared source without weakening the existing HTTP policy."""
    if current and snapshot:
        raise ValueError("choose --current or --snapshot, not both")
    if underlying_history and not (current or snapshot):
        raise ValueError("--underlying-history requires --current or --snapshot")
    if not current and not snapshot:
        with demo_runtime() as runtime:
            yield runtime
        return

    yield RuntimeConfig(
        profile="development",
        snapshot_fixture=_local_input_path(snapshot),
        underlying_history_fixture=_local_input_path(underlying_history),
        allow_live_fetch=current,
        replay=bool(snapshot),
        access_log=False,
    ).validate()


def run_start(
    *,
    port: int = 8000,
    open_browser: bool = True,
    current: bool = False,
    snapshot: str | None = None,
    underlying_history: str | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Serve the packaged UI through the existing bounded research server."""
    if not 1 <= port <= 65535:
        raise ValueError("local port must be between 1 and 65535; choose --port")
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    with local_runtime(
        current=current,
        snapshot=snapshot,
        underlying_history=underlying_history,
    ) as runtime:
        try:
            server = DemoHTTPServer(
                (DEMO_HOST, port),
                ResearchReportHandler,
                runtime=runtime,
            )
        except OSError as exc:
            if not _is_address_in_use(exc):
                raise
            print(
                f"could not start LensOS Option at {DEMO_HOST}:{port}: port is already "
                "in use; choose another port with --port",
                file=stderr,
            )
            return 1

        path = DEMO_URL_PATH if runtime.demo_mode else RESEARCH_URL_PATH
        url = f"http://{DEMO_HOST}:{server.server_port}{path}"
        print(f"LensOS Option ready at {url}", file=stdout, flush=True)
        print(_source_notice(runtime), file=stdout, flush=True)
        print(
            "Research only. WATCH / execution_allowed=false. Press Ctrl+C to stop.",
            file=stdout,
            flush=True,
        )
        if open_browser:
            with suppress(Exception):
                webbrowser.open(url, new=2)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Stopping LensOS Option.", file=stderr)
        finally:
            server.server_close()
    return 0


def _source_notice(runtime: RuntimeConfig) -> str:
    if runtime.demo_mode:
        return (
            "Mode: offline demo. Bundled teaching and snapshot data; no network. "
            "Use --snapshot <path> for recorded research or --current for public market data."
        )
    if runtime.replay:
        return (
            "Mode: historical snapshot. Evaluation is pinned to the capture time. "
            "Refresh only rereads the configured local input; it does not collect new market data."
        )
    return (
        "Mode: current public market data. Opening the research view collects Deribit "
        "public data through the existing approved source. Refresh may reuse a still-current "
        "analysis; expired evidence is collected again. No account or credentials are used."
    )


def _local_input_path(path: str | None) -> str | None:
    return str(Path(path).expanduser().resolve()) if path else None
