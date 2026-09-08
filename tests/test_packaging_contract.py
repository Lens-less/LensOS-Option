import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

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

    pins = {}
    for line in constraints.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        requirement = Requirement(line)
        specifiers = list(requirement.specifier)
        assert len(specifiers) == 1 and specifiers[0].operator == "==", f"Not an exact pin: {line}"
        version = Version(specifiers[0].version)  # Reject wildcard and invalid versions.
        name = canonicalize_name(requirement.name)
        assert name not in pins, f"Ambiguous duplicate pin: {name}"
        pins[name] = version

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = ["pip", *config["build-system"]["requires"]]
    for requirements in config["project"]["optional-dependencies"].values():
        declared.extend(requirements)
    for text in declared:
        requirement = Requirement(text)
        name = canonicalize_name(requirement.name)
        assert name in pins, f"Development/build dependency has no exact constraint: {name}"
        assert pins[name] in requirement.specifier, f"Constraint violates project requirement: {text}"

    pre_commit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    ruff_hook = pre_commit.split("repo: https://github.com/astral-sh/ruff-pre-commit", 1)[1].split("  - repo:", 1)[0]
    assert f"rev: v{pins['ruff']}" in ruff_hook

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
        embedded_path = build_lib / "crypto_options_report/_build_info.json"
        embedded = json.loads(embedded_path.read_text(encoding="utf-8"))["build_info"]
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        assert embedded["package_version"] == project["version"]
        assert embedded["source_digest"].startswith("sha256:")
        assert not (ROOT / "crypto_options_report/_build_info.json").exists()
        with TemporaryDirectory(prefix="isolated-build-identity-") as isolated:
            installed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import json,sys; sys.path.insert(0,sys.argv[1]); "
                    "from crypto_options_report.build_info import get_build_info; "
                    "print(json.dumps(get_build_info().to_dict()))",
                    str(build_lib),
                ],
                cwd=isolated,
                env={**os.environ, "GITHUB_SHA": "f" * 40},
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        observed = json.loads(installed.stdout)
        assert observed == {**embedded, "source_kind": "embedded"}


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
