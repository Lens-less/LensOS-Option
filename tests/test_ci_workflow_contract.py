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


def test_web_ci_accepts_the_installed_wheel_after_building_the_final_ui() -> None:
    web_job = _web_job()
    wheel_build = "python -m pip wheel --no-build-isolation --no-deps . -w browser-wheel"
    wheel_install = "browser-venv/bin/python -m pip install --no-index --no-deps browser-wheel/*.whl"
    browser_check = 'node tools/browser-smoke.mjs --python "${{ github.workspace }}/browser-venv/bin/python"'

    assert web_job.index("npm run build:extension") < web_job.index(wheel_build)
    assert web_job.index(wheel_build) < web_job.index(wheel_install) < web_job.index(browser_check)
    assert "continue-on-error" not in web_job
    assert "name: browser-acceptance" in web_job


def test_release_blocks_packaging_and_publish_until_wheel_browser_acceptance() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    build_job, publish_job = workflow.split("\n  publish:\n")
    wheel_build = "python -m pip wheel --no-build-isolation --no-deps . -w release"
    browser_check = 'node tools/browser-smoke.mjs --python "${{ github.workspace }}/wheel-venv/bin/python"'

    assert build_job.index("npm run build:extension") < build_job.index(wheel_build)
    assert build_job.index(wheel_build) < build_job.index(browser_check)
    assert build_job.index(browser_check) < build_job.index("Package Chrome extension and checksums")
    assert "--no-index --no-deps release/*.whl" in build_job
    assert "continue-on-error" not in build_job
    assert "needs: build" in publish_job


def test_python_ci_checks_types_and_reproducible_research() -> None:
    test_job = _test_job()
    assert "python -m mypy --no-incremental" in test_job
    assert "python tools/check_release_versions.py" in test_job
    assert "python tools/reproduce_research.py --check" in test_job


def test_windows_wheel_checks_cannot_mask_an_earlier_native_failure() -> None:
    windows = _test_job().split("name: Verify built wheel on Windows", 1)[1].split("- uses:", 1)[0]
    lines = [line.strip() for line in windows.splitlines()]
    native_commands = [line for line in lines if line.startswith(("python ", "wheel-venv\\Scripts\\python.exe "))]
    assert len(native_commands) == 3
    for command in native_commands:
        assert lines[lines.index(command) + 1] == "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
    assert "python tools/check_installed_wheel.py --python wheel-venv\\Scripts\\python.exe" in windows


def test_release_reuses_full_ci_for_the_selected_tag_before_building() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in _workflow_text()
    assert _workflow_text().count("ref: ${{ inputs.ref || github.ref }}") == 3
    assert "uses: ./.github/workflows/ci.yml" in release
    assert "ref: refs/tags/${{ inputs.tag || github.ref_name }}" in release
    assert "  build:\n    needs: verify\n" in release
    assert "python -m mypy --no-incremental" in release


def test_final_wheel_consumer_checks_precede_browser_acceptance_in_ci_and_release() -> None:
    for workflow, environment in (
        (_web_job(), "browser-venv"),
        ((REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"), "wheel-venv"),
    ):
        consumer = f"python tools/check_installed_wheel.py --python {environment}/bin/python"
        assert workflow.index("--no-index --no-deps") < workflow.index(consumer)
        assert workflow.index(consumer) < workflow.index("node tools/browser-smoke.mjs")
        assert "--public-build-dir web/dist-public --output-dir browser-artifacts" in workflow


def test_release_checks_tag_and_built_wheel_versions_before_browser_acceptance() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    source_check = 'python tools/check_release_versions.py --tag "$RELEASE_TAG"'
    artifact_check = source_check + ' --wheel release/*.whl'
    assert workflow.index(source_check) < workflow.index("Verify and build web release surfaces")
    assert workflow.index("pip wheel") < workflow.index(artifact_check)
    assert workflow.index(artifact_check) < workflow.index("Verify installed release wheel in isolated Chrome")
