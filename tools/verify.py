"""One local gate for source checks and the installed release artifact.

Install the existing development dependencies and run ``npm ci`` in web first.
This command never downloads a browser; BROWSER_PATH may select its executable.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def run(label: str, command: list[str], *, cwd: Path = ROOT) -> None:
    print(f"\n[{label}]", flush=True)
    if "--smoke" not in command:
        subprocess.run(command, cwd=cwd, check=True)
        return
    try:
        subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        raise
    print("Smoke checks passed.", flush=True)


def source_steps(*, quick: bool) -> list[tuple[str, list[str], Path]]:
    python = sys.executable
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm"
    steps = [
        ("Python lint", [python, "-m", "ruff", "check", "crypto_options_report", "tools", "tests"], ROOT),
        ("Python syntax", [python, "-m", "compileall", "-q", "crypto_options_report", "tools"], ROOT),
        ("Python static types", [python, "-m", "mypy", "--no-incremental"], ROOT),
        ("Source version consistency", [python, "tools/check_release_versions.py"], ROOT),
        ("Python tests", [python, "-m", "pytest", "-q"], ROOT),
        ("API smoke", [python, "-m", "crypto_options_report.api", "--smoke"], ROOT),
        ("Offline research reproducibility", [python, "tools/reproduce_research.py", "--check"], ROOT),
        ("Web types and unused code", [npm, "run", "lint"], WEB),
        ("Web tests", [npm, "test"], WEB),
    ]
    if not quick:
        steps.extend([
            ("Account sidecar help", [python, "-m", "crypto_options_report.account_snapshot_sidecar", "--help"], ROOT),
            ("Web build", [npm, "run", "build"], WEB),
            ("Public build", [npm, "run", "build:public"], WEB),
            ("Public bundle boundary", [npm, "run", "test:public-bundle"], WEB),
            ("Chrome companion build", [npm, "run", "build:extension"], WEB),
        ])
    return steps


def verify_extension() -> None:
    extension = WEB / "dist" / "chrome-extension"
    for name in ("manifest.json", "sidepanel.html", "assets/service-worker.js", "assets/content-script.js"):
        if not (extension / name).is_file():
            raise RuntimeError(f"Missing built Chrome companion artifact: {name}")
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 3:
        raise RuntimeError("Chrome companion must use Manifest V3")
    print("[Chrome companion artifact] passed", flush=True)


def verify_wheel(*, output_dir: Path | None) -> None:
    # Building after the web checks guarantees the wheel contains the final UI.
    # Running outside ROOT prevents imports from accidentally using the checkout.
    with tempfile.TemporaryDirectory(prefix="option-wheel-check-") as directory:
        temporary = Path(directory)
        wheels = temporary / "wheels"
        run("Build final wheel", [sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", ".", "-w", str(wheels)])
        built = list(wheels.glob("*.whl"))
        if len(built) != 1:
            raise RuntimeError(f"Expected one final wheel, found {len(built)}")
        run("Final artifact version consistency", [
            sys.executable, "tools/check_release_versions.py", "--wheel", str(built[0]),
            "--extension-dir", str(WEB / "dist" / "chrome-extension"),
        ])
        environment = temporary / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run("Install final wheel", [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(built[0])], cwd=temporary)
        run("Installed wheel consumer checks", [
            sys.executable, str(ROOT / "tools" / "check_installed_wheel.py"), "--python", str(python),
        ], cwd=temporary)
        node = shutil.which("node") or "node"
        command = [
            node, str(ROOT / "tools" / "browser-smoke.mjs"), "--python", str(python),
            "--extension-dir", str(WEB / "dist" / "chrome-extension"),
            "--public-build-dir", str(WEB / "dist-public"),
        ]
        if output_dir is not None:
            command.extend(["--output-dir", str(output_dir.resolve())])
        run("Installed wheel browser journey", command, cwd=temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="run source lint/types/tests, versions, API smoke and offline replay; omit builds, artifact and browser checks")
    parser.add_argument("--list", action="store_true", help="list selected checks without running them")
    parser.add_argument("--output-dir", type=Path, help="save browser screenshots and report in this directory (full gate only)")
    args = parser.parse_args(argv)
    steps = source_steps(quick=args.quick)
    if args.quick:
        print("QUICK subset: builds, public bundle, extension artifact, installed wheel and browser journey are excluded.", flush=True)
    if args.list:
        for label, _, _ in steps:
            print(label)
        if not args.quick:
            print("Chrome companion artifact\nBuild and install final wheel\nInstalled wheel consumer checks\nInstalled wheel browser journey")
        return 0
    try:
        for label, command, cwd in steps:
            run(label, command, cwd=cwd)
        if not args.quick:
            verify_extension()
            verify_wheel(output_dir=args.output_dir)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1
    print("\nQuick subset passed." if args.quick else "\nFull verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
