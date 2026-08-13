from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "rehearse-public-history-rewrite.py"


def _plan(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(ROOT),
            "--public-author-name",
            "LensOS Public Rehearsal",
            "--public-author-email",
            "history-rewrite@example.invalid",
            "--identity-mode",
            "rehearsal",
            "--plan-only",
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )


def test_plan_preserves_only_the_current_static_bundle_and_never_pushes() -> None:
    completed = _plan()

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    current_assets = subprocess.run(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            "HEAD",
            "--",
            "crypto_options_report/static/evidence/assets",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.splitlines()
    current_bundles = sorted(
        path
        for path in current_assets
        if path.endswith((".css", ".js")) and "/index-" in path
    )
    historical_paths = subprocess.run(
        ["git", "log", "--all", "--name-only", "--pretty=format:"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.splitlines()
    historical_bundles = {
        path
        for path in historical_paths
        if path.startswith("crypto_options_report/static/evidence/assets/index-")
        and path.endswith((".css", ".js"))
    }
    expected_obsolete_bundles = historical_bundles - set(current_bundles)

    assert plan["schema_version"] == "public_history_rewrite_plan.v1"
    assert plan["status"] == "planned"
    assert plan["identity_mode"] == "rehearsal"
    assert plan["cutover_target"] == "existing-repository"
    assert plan["source_head"] == subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    assert plan["retained_static_bundles"] == current_bundles
    assert set(plan["retained_static_assets"]) == set(current_bundles)
    assert all(bundle not in plan["removed_paths"] for bundle in current_bundles)
    assert "docs/automation/" in plan["removed_paths"]
    assert "issues/" in plan["removed_paths"]
    assert ".workflow/" in plan["removed_paths"]
    assert "tools/options_coordination_v2/" in plan["removed_paths"]
    assert {
        "tests/test_options_platform_controller_contract.py",
        "tests/test_options_platform_coordination_git_v2.py",
        "tests/test_options_platform_coordination_migration_v2.py",
        "tests/test_options_platform_coordination_v2.py",
        "tests/test_options_platform_cutover_v2.py",
        "tests/test_options_platform_machine_v2.py",
        "tests/test_options_platform_manifest_conversion_v2.py",
        "tests/test_options_platform_projection_v2.py",
        "tests/test_options_platform_remote_cli_v2.py",
    }.issubset(plan["removed_paths"])
    assert expected_obsolete_bundles.issubset(plan["removed_paths"])
    assert plan["source_mutation_allowed"] is False
    assert plan["push_allowed"] is False
    assert plan["private_archive_required"] is True
    assert plan["filter_repo_version"] == "2.47.0"
    assert plan["sensitive_data_removal_mode"] is True
    assert plan["public_ref_allowlist"] == ["refs/heads/main"]
    assert plan["remote_pr_refs_checked"] is False


def test_final_mode_rejects_a_placeholder_public_identity() -> None:
    completed = _plan("--identity-mode", "final")

    assert completed.returncode != 0
    assert "final identity must not use a placeholder domain" in completed.stderr


def test_plan_can_select_a_new_repository_cutover() -> None:
    completed = _plan("--cutover-target", "new-repository")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["cutover_target"] == "new-repository"


def test_rewrite_mirror_disables_local_clone_optimization() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert '["git", "clone", "--mirror", "--no-local"' in script
    assert '["git", "clone", "--mirror", "--no-hardlinks", archive_mirror' not in script


def test_validation_clone_explicitly_checks_out_rewritten_main() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert '"--branch",\n            "main",\n            "--single-branch"' in script
    assert 'if validation_head != rewritten_head:' in script


def test_current_tracked_tree_contains_no_registered_private_identity_tokens() -> None:
    private_user_id = "28" + "340"
    private_author_id = private_user_id + "0448"
    tokens = (
        private_user_id,
        private_author_id,
        f"{private_author_id}@qq.com",
        "LENS\\" + private_user_id,
    )

    for token in tokens:
        completed = subprocess.run(
            ["git", "grep", "-I", "-F", "-n", "-e", token, "--", "."],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        assert completed.returncode == 1, completed.stdout


def test_public_cutover_docs_keep_history_and_raw_artifacts_fail_closed() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    history = (ROOT / "docs/operations/public-history-rewrite.md").read_text(
        encoding="utf-8"
    )
    cutover = (ROOT / "docs/operations/public-release-cutover.md").read_text(
        encoding="utf-8"
    )
    docs_map = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")

    assert "mandatory precondition" in security
    assert "read-only pull-request" in security
    assert "passed_with_remote_blockers" in history
    assert "refs/heads/main" in history
    assert "new public repository" in history
    assert "Inventory all existing" in cutover
    assert "public-history-rewrite.md" in docs_map
    assert "public-release-cutover.md" in docs_map
    assert "github.event.repository.private == true" in workflow
