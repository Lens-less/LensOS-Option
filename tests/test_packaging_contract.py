import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CONSTRAINTS = ROOT / "constraints.txt"


def test_wheel_declares_public_legal_pages_and_both_license_files() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    project = config["project"]
    package_data = config["tool"]["setuptools"]["package-data"][
        "crypto_options_report"
    ]

    assert {"LICENSE", "LICENSE-DATA"}.issubset(project["license-files"])
    assert not any(
        classifier.startswith("License ::") for classifier in project["classifiers"]
    )
    assert "static/evidence/en/*.html" in package_data
    assert "static/evidence/*.css" in package_data
    assert "resources/*.json" in package_data
    assert (ROOT / "crypto_options_report/resources/demo-snapshot.json").is_file()
    assert (
        ROOT / "crypto_options_report/resources/demo-underlying-history.json"
    ).is_file()


def test_direct_setup_contract_declares_its_build_backend_as_a_test_tool() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    optional_dependencies = config["project"]["optional-dependencies"]
    assert "setuptools>=77" in optional_dependencies["test"]
    assert "setuptools>=77" in optional_dependencies["dev"]


def test_packaging_metadata_declares_python_3_14_support() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "Programming Language :: Python :: 3.14" in config["project"]["classifiers"]


def test_shared_constraints_pin_the_toolchain_used_by_ci_and_the_wheel_builds() -> None:
    constraints = CONSTRAINTS.read_text(encoding="utf-8")
    ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    for requirement in (
        "pip==25.2",
        "pytest==9.0.3",
        'colorama==0.4.6 ; sys_platform == "win32"',
        "iniconfig==2.3.0",
        "packaging==26.0",
        "pluggy==1.6.0",
        "Pygments==2.20.0",
        "ruff==0.16.0",
        "setuptools==80.10.2",
    ):
        assert requirement in constraints

    assert "PIP_CONSTRAINT: ${{ github.workspace }}/constraints.txt" in ci_workflow
    assert (
        "python -m pip install --upgrade -c constraints.txt pip setuptools"
        in ci_workflow
    )
    assert 'python -m pip install --no-build-isolation -c constraints.txt -e ".[dev]"' in ci_workflow
    assert "python -m pip wheel --no-build-isolation --no-deps . -w dist" in ci_workflow
    assert "wheel-venv/bin/python -m pip install --no-deps -c constraints.txt dist/*.whl" in ci_workflow
    assert "wheel-venv\\Scripts\\python.exe -m pip install --no-deps -c constraints.txt $wheel" in ci_workflow
    assert "pip install" not in dockerfile
    assert "COPY --chown=app:app crypto_options_report ./crypto_options_report" in dockerfile
    assert "COPY --chown=app:app LICENSE LICENSE-DATA ./" in dockerfile


def _run_build_py(build_lib: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "setup.py", "build_py", "--build-lib", str(build_lib)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_wheel_build_removes_stale_hash_assets_from_staging() -> None:
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    source_assets = {
        path.name
        for path in (ROOT / "crypto_options_report/static/evidence/assets").iterdir()
        if path.is_file()
    }

    with TemporaryDirectory(prefix="packaging-contract-", dir=build_root) as temp:
        build_lib = Path(temp)
        staged_assets = build_lib / "crypto_options_report/static/evidence/assets"
        staged_assets.mkdir(parents=True)
        (staged_assets / "index-stale-private.js").write_text(
            "operator_notes = 'must not survive'",
            encoding="utf-8",
        )

        completed = _run_build_py(build_lib)

        assert completed.returncode == 0, completed.stderr
        assert {path.name for path in staged_assets.iterdir()} == source_assets
        assert not (staged_assets / "index-stale-private.js").exists()


def test_wheel_build_refuses_external_or_linked_build_directories() -> None:
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="packaging-external-") as external:
        external_path = Path(external)
        completed = _run_build_py(external_path)
        assert completed.returncode != 0
        assert "outside ./build" in completed.stderr

        with TemporaryDirectory(prefix="packaging-link-parent-", dir=build_root) as parent:
            linked_build = Path(parent) / "linked-build"
            try:
                if os.name == "nt":
                    powershell = shutil.which("pwsh") or shutil.which("powershell")
                    if not powershell:
                        pytest.skip("PowerShell is required to create a Windows junction")
                    link_result = subprocess.run(
                        [
                            powershell,
                            "-NoProfile",
                            "-NonInteractive",
                            "-Command",
                            "New-Item -ItemType Junction -Path $env:PACKAGING_LINK -Target $env:PACKAGING_TARGET | Out-Null",
                        ],
                        env={
                            **os.environ,
                            "PACKAGING_LINK": str(linked_build),
                            "PACKAGING_TARGET": str(external_path),
                        },
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    assert link_result.returncode == 0, link_result.stderr
                else:
                    linked_build.symlink_to(external_path, target_is_directory=True)

                linked_result = _run_build_py(linked_build)
                assert linked_result.returncode != 0
                assert "linked build directory" in linked_result.stderr
            finally:
                if linked_build.is_symlink():
                    linked_build.unlink()
                elif os.name == "nt" and os.path.isjunction(linked_build):
                    linked_build.rmdir()
