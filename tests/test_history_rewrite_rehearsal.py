from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "rehearse-public-history-rewrite.py"


def _private_env() -> dict[str, str]:
    return {
        "LENSOS_HISTORY_REWRITE_PRIVATE_USER_ID": "local-" + "user-123",
        "LENSOS_HISTORY_REWRITE_PRIVATE_AUTHOR_ID": "author-" + "456",
        "LENSOS_HISTORY_REWRITE_PRIVATE_EMAIL": "maintainer-" + "private@example.invalid",
        "LENSOS_HISTORY_REWRITE_PRIVATE_NAME": "Local " + "Maintainer",
    }


def _load_tool():
    spec = importlib.util.spec_from_file_location("history_rewrite_tool", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def _plan(*extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    for variable in _private_env():
        process_env.pop(variable, None)
    if env is not None:
        process_env.update(env)
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
        env=process_env,
        timeout=30,
    )


def _private_identity(tool):
    return tool._load_private_identity(_private_env())


def test_plan_preserves_only_the_current_static_bundle_and_never_pushes() -> None:
    private_env = _private_env()
    completed = _plan(env=private_env)

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
    assert plan["replacement_marker_categories"] == [
        "private_user_id",
        "private_author_id",
        "private_email",
        "private_name",
    ]
    assert plan["replacement_marker_count"] == 4
    for value in private_env.values():
        assert value not in completed.stdout


def test_final_mode_rejects_a_placeholder_public_identity() -> None:
    completed = _plan("--identity-mode", "final", env=_private_env())

    assert completed.returncode != 0
    assert "final identity must not use a placeholder domain" in completed.stderr


def test_plan_can_select_a_new_repository_cutover() -> None:
    completed = _plan("--cutover-target", "new-repository", env=_private_env())

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["cutover_target"] == "new-repository"


def test_plan_fails_closed_without_private_identity_environment() -> None:
    completed = _plan()

    assert completed.returncode != 0
    assert "set all four variables" in completed.stderr


def test_plan_fails_closed_with_partial_private_identity_environment() -> None:
    completed = _plan(
        env={
            key: value
            for key, value in _private_env().items()
            if key != "LENSOS_HISTORY_REWRITE_PRIVATE_NAME"
        }
    )

    assert completed.returncode != 0
    assert "set all four variables" in completed.stderr


def test_rewrite_mirror_disables_local_clone_optimization() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert '["git", "clone", "--mirror", "--no-local"' in script
    assert '["git", "clone", "--mirror", "--no-hardlinks", archive_mirror' not in script


def test_validation_clone_explicitly_checks_out_rewritten_main() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert '"--branch",\n            "main",\n            "--single-branch"' in script
    assert 'if validation_head != rewritten_head:' in script


def test_registered_identity_scan_detects_utf16_binary_blob() -> None:
    tool = _load_tool()
    private_identity = _private_identity(tool)
    private_name = private_identity.private_name
    payload = b"\x00binary\x00" + private_name.swapcase().encode("utf-16-le") + b"\x00"

    hits = tool._registered_token_hits(payload, private_identity)

    assert any(hit["category"] == "private_name" for hit in hits)
    assert any(hit["encoding"] == "utf-16-le" for hit in hits)


@pytest.mark.parametrize("encoding", ("utf-8", "utf-16-le", "utf-16-be"))
def test_registered_identity_scan_casefolds_unicode_binary_tokens(
    encoding: str,
) -> None:
    tool = _load_tool()
    private_identity = tool._private_identity_from_values(
        private_user_id="local-" + "user-123",
        private_author_id="author-" + "456",
        private_email="maintainer-" + "private@example.invalid",
        private_name="Éclair " + "Maintainer",
    )
    payload = b"\xff" + "ÉCLAIR MAINTAINER".encode(encoding) + b"\xff"

    hits = tool._registered_token_hits(payload, private_identity)

    assert {"category": "private_name", "encoding": encoding} in hits


def test_reachable_blob_scan_detects_registered_identity_in_binary_git_blob() -> None:
    tool = _load_tool()
    private_identity = _private_identity(tool)
    with TemporaryDirectory() as temporary_root:
        repository = Path(temporary_root) / "repository"
        repository.mkdir()
        _git("init", "-b", "main", cwd=repository)
        private_name = private_identity.private_name
        (repository / "opaque.bin").write_bytes(
            b"\x00binary\xff" + private_name.swapcase().encode("utf-16-be") + b"\x00"
        )
        _git("add", ".", cwd=repository)
        _git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "Add binary fixture",
            cwd=repository,
        )

        hits = tool._scan_reachable_blob_tokens(repository, private_identity)

    assert any(hit["category"] == "private_name" for hit in hits)
    assert any(hit["encoding"] == "utf-16-be" for hit in hits)


def test_final_sync_uses_live_origin_instead_of_cached_tracking_ref() -> None:
    tool = _load_tool()
    with TemporaryDirectory() as temporary_root:
        root = Path(temporary_root)
        remote = root / "remote.git"
        source = root / "source"
        peer = root / "peer"
        source.mkdir()
        _git("init", "--bare", str(remote), cwd=root)
        _git("init", "-b", "main", cwd=source)
        (source / "README.md").write_text("initial\n", encoding="utf-8")
        _git("add", ".", cwd=source)
        _git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "Initial",
            cwd=source,
        )
        _git("remote", "add", "origin", str(remote), cwd=source)
        _git("push", "-u", "origin", "main", cwd=source)
        assert tool._source_sync_state(source)["head_equals_origin_main"] is True

        _git("clone", "--branch", "main", str(remote), str(peer), cwd=root)
        (peer / "README.md").write_text("advanced remotely\n", encoding="utf-8")
        _git("add", ".", cwd=peer)
        _git(
            "-c",
            "user.name=Peer",
            "-c",
            "user.email=peer@example.invalid",
            "commit",
            "-m",
            "Advance remote",
            cwd=peer,
        )
        _git("push", "origin", "main", cwd=peer)

        assert tool._source_sync_state(source)["head_equals_origin_main"] is True
        with pytest.raises(tool.RewriteError, match="live origin/main"):
            tool._assert_final_source_sync(source)


def test_current_tracked_tree_contains_no_registered_private_identity_tokens() -> None:
    tokens = tuple(_private_env().values())

    for token in tokens:
        completed = subprocess.run(
            ["git", "grep", "-a", "-F", "-n", "-e", token, "--", "."],
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
    assert "new private repository" in history
    assert "LENSOS_HISTORY_REWRITE_PRIVATE_EMAIL" in history
    assert "replacement marker categories and counts" in history
    assert "new empty private repository" in cutover
    assert "Inventory all existing" in cutover
    assert "public-history-rewrite.md" in docs_map
    assert "public-release-cutover.md" in docs_map
    assert "github.event.repository.private == true" in workflow
