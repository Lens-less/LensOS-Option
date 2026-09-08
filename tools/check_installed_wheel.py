"""Accept an installed wheel outside the source tree, using only offline checks.

The supplied interpreter must belong to the virtual environment containing the
wheel. All subprocess failures propagate on Windows as well as POSIX hosts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ENTRY_POINTS = {
    "crypto-options-report": "crypto_options_report.cli:main",
    "crypto-options-report-api": "crypto_options_report.api:main",
    "crypto-options-snapshot-sidecar": "crypto_options_report.snapshot_sidecar:main",
    "crypto-options-account-snapshot-sidecar": "crypto_options_report.account_snapshot_sidecar:main",
    "crypto-options-dvol-history": "crypto_options_report.dvol_history_tool:main",
    "crypto-options-underlying-history": "crypto_options_report.underlying_history_tool:main",
}

INSTALLED_IDENTITY_CHECK = """
import importlib.metadata
import json
import sys
from pathlib import Path
import crypto_options_report
from crypto_options_report.build_info import get_build_info

package = Path(crypto_options_report.__file__).resolve()
assert sys.prefix != sys.base_prefix, "Consumer checks require an isolated virtual environment"
assert package.is_relative_to(Path(sys.prefix).resolve()), "Imported source checkout instead of installed wheel"
distribution = importlib.metadata.distribution("crypto-options-research-console")
expected = json.loads(sys.argv[1])
actual = {entry.name: entry.value for entry in distribution.entry_points if entry.group == "console_scripts"}
assert actual == expected, f"Installed console entry points differ: {actual!r}"
for entry in distribution.entry_points:
    if entry.group == "console_scripts":
        assert callable(entry.load()), f"Entry point is not callable: {entry.name}"
build = get_build_info()
assert build.package_version == distribution.version, "Embedded build version differs from installed metadata"
assert (package.parent / "_build_info.json").is_file(), "Missing embedded wheel build identity"
for relative in ("resources/demo-snapshot.json", "resources/demo-underlying-history.json", "resources/public-openapi-v1.json", "static/evidence/index.html", "py.typed"):
    assert (package.parent / relative).is_file(), f"Missing installed resource: {relative}"
print(f"Installed wheel identity passed: {distribution.version}")
"""


def check_installed_wheel(python: Path) -> None:
    python = python.absolute()
    if not python.is_file():
        raise ValueError(f"Installed-wheel interpreter does not exist: {python}")
    # Console launchers cannot accept Python's -I flag. Remove Python startup
    # overrides as well as using a fresh cwd, so those checks cannot import ROOT.
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    with tempfile.TemporaryDirectory(prefix="option-installed-consumer-") as directory:
        def run(command: list[str], *, quiet: bool = False) -> None:
            completed = subprocess.run(
                command, cwd=directory, env=environment, check=False,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
            )
            if completed.returncode:
                if completed.stdout:
                    print(completed.stdout, file=sys.stderr)
                if completed.stderr:
                    print(completed.stderr, file=sys.stderr)
                completed.check_returncode()
            if not quiet and completed.stdout:
                print(completed.stdout.strip())

        run([str(python), "-I", "-c", INSTALLED_IDENTITY_CHECK, json.dumps(ENTRY_POINTS)])
        run([str(python), "-I", "-m", "pip", "check"])
        for name in ENTRY_POINTS:
            launcher = python.parent / (f"{name}.exe" if os.name == "nt" else name)
            run([str(launcher), "--help"], quiet=True)
        run([str(python), "-I", "-m", "crypto_options_report.api", "--smoke"], quiet=True)
    print("Installed wheel consumer checks passed: 6 console launchers, packaged resources, dependencies and API smoke.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True, help="Interpreter in the installed-wheel virtual environment")
    args = parser.parse_args(argv)
    try:
        check_installed_wheel(args.python)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Installed wheel verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
