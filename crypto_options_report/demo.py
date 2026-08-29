"""Offline packaged demo for the research-only console."""

from __future__ import annotations

import argparse
import errno
import socket
import sys
import webbrowser
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager, suppress
from importlib.resources import as_file, files
from pathlib import Path

from .api import ResearchHTTPServer, ResearchReportHandler, RuntimeConfig

DEMO_HOST = "127.0.0.1"
DEMO_URL_PATH = "/index.html?view=workbench"
DEMO_SNAPSHOT_RESOURCE = "demo-snapshot.json"
DEMO_UNDERLYING_RESOURCE = "demo-underlying-history.json"
DEMO_SIGNAL_RESOURCE = "demo-signal-preflight.json"
DEMO_SERIES_RESOURCE = "demo-series-history.json"


class DemoHTTPServer(ResearchHTTPServer):
    """Loopback server that reserves its demo port for one process."""

    _exclusive_address_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    allow_reuse_address = _exclusive_address_use is None

    def server_bind(self) -> None:
        if self._exclusive_address_use is not None:
            self.socket.setsockopt(
                socket.SOL_SOCKET,
                self._exclusive_address_use,
                1,
            )
        super().server_bind()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto-options-report demo",
        description=(
            "Start the packaged read-only demo from bundled snapshot data. "
            "The UI stays in RESEARCH_ONLY / NO_TRADE mode and does not call the network."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="loopback port for the local demo server (default 8000)",
    )
    parser.add_argument(
        "--open-browser",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="open the demo URL in the default browser after startup",
    )
    return parser


@contextmanager
def demo_runtime() -> Iterator[RuntimeConfig]:
    with ExitStack() as stack:
        snapshot = _resource_path(stack, DEMO_SNAPSHOT_RESOURCE)
        underlying = _resource_path(stack, DEMO_UNDERLYING_RESOURCE)
        signal = _resource_path(stack, DEMO_SIGNAL_RESOURCE)
        series = _resource_path(stack, DEMO_SERIES_RESOURCE)
        yield RuntimeConfig(
            profile="development",
            snapshot_fixture=str(snapshot),
            underlying_history_fixture=str(underlying),
            signal_artifact=str(signal),
            series_artifact=str(series),
            allow_live_fetch=False,
            replay=True,
            demo_mode=True,
            access_log=False,
        ).validate()


def run_demo(
    *,
    port: int,
    open_browser: bool = False,
    stdout: object | None = None,
    stderr: object | None = None,
) -> int:
    if port < 1 or port > 65535:
        raise ValueError("demo port must be between 1 and 65535")
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    with demo_runtime() as runtime:
        try:
            server = DemoHTTPServer(
                (DEMO_HOST, port),
                ResearchReportHandler,
                runtime=runtime,
            )
        except OSError as exc:
            if _is_address_in_use(exc):
                print(
                    f"demo could not bind {DEMO_HOST}:{port} because it is already in use; "
                    "choose another port with --port",
                    file=stderr,
                )
                return 1
            raise

        url = f"http://{DEMO_HOST}:{server.server_port}{DEMO_URL_PATH}"
        print(f"LensOS Option demo ready at {url}", file=stdout)
        print(
            "Demo / snapshot data only. Read-only interface. RESEARCH_ONLY / NO_TRADE. "
            "Press Ctrl+C to stop.",
            file=stdout,
        )
        if open_browser:
            with suppress(Exception):
                webbrowser.open(url, new=2)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Stopping LensOS Option demo.", file=stderr)
        finally:
            server.server_close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_demo(port=args.port, open_browser=args.open_browser)


def _resource_path(stack: ExitStack, resource_name: str) -> Path:
    return stack.enter_context(
        as_file(files("crypto_options_report").joinpath("resources", resource_name))
    )


def _is_address_in_use(exc: OSError) -> bool:
    return (
        exc.errno == errno.EADDRINUSE
        or getattr(exc, "winerror", None) in {10048, 10013}
    )


if __name__ == "__main__":
    raise SystemExit(main())
