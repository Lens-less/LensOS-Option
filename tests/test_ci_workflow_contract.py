from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def _test_job() -> str:
    workflow = _workflow_text()
    test_start = workflow.index("  test:\n")
    web_start = workflow.index("\n  web:\n", test_start)
    return workflow[test_start:web_start]


def _web_job() -> str:
    workflow = _workflow_text()
    web_start = workflow.index("  web:\n")
    container_start = workflow.index("\n  container:\n", web_start)
    return workflow[web_start:container_start]


def _web_run_step(command: str) -> str:
    return f"        run: {command}\n        working-directory: web"


def test_web_ci_audits_dependencies_against_the_official_registry() -> None:
    web_job = _web_job()

    assert (
        _web_run_step(
            "npm audit --omit=dev --registry=https://registry.npmjs.org "
            "--audit-level=high"
        )
        in web_job
    )


def test_web_ci_builds_and_scans_the_static_public_bundle() -> None:
    web_job = _web_job()
    public_build = "npm run build:public"
    boundary_scan = "npm run test:public-bundle"

    assert _web_run_step(public_build) in web_job
    assert _web_run_step(boundary_scan) in web_job
    assert web_job.index(public_build) < web_job.index(boundary_scan)


def test_python_ci_runs_the_full_matrix_on_python_3_14() -> None:
    test_job = _test_job()

    assert 'python-version: ["3.12", "3.13", "3.14"]' in test_job
    assert "python -m pytest -q" in test_job
    assert "matrix.python-version == '3.14'" in test_job


def test_python_ci_uses_shared_constraints_for_dev_and_wheel_installs() -> None:
    test_job = _test_job()

    assert "PIP_CONSTRAINT: ${{ github.workspace }}/constraints.txt" in test_job
    assert (
        "python -m pip install --upgrade -c constraints.txt pip setuptools" in test_job
    )
    assert 'python -m pip install --no-build-isolation -c constraints.txt -e ".[dev]"' in test_job
    assert "python -m pip wheel --no-build-isolation --no-deps . -w dist" in test_job
    assert "wheel-venv/bin/python -m pip install --no-deps -c constraints.txt dist/*.whl" in test_job
    assert "wheel-venv\\Scripts\\python.exe -m pip install --no-deps -c constraints.txt $wheel" in test_job


def test_web_ci_pins_node_to_the_jsdom_30_supported_patch_release() -> None:
    web_job = _web_job()

    assert 'node-version: "22.22.2"' in web_job
