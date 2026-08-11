from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _web_job() -> str:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
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
