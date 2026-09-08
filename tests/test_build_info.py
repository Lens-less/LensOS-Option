import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from crypto_options_report.build_info import get_build_info


def _source_tree(root: Path) -> Path:
    (root / "crypto_options_report").mkdir()
    (root / "crypto_options_report/example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "crypto-options-research-console"\nversion = "0.4.0"\n',
        encoding="utf-8",
    )
    (root / "web/src").mkdir(parents=True)
    (root / "web/src/App.tsx").write_text("export const value = 1;\n", encoding="utf-8")
    return root


def test_source_identity_is_deterministic_and_excludes_local_artifacts_and_secrets(tmp_path: Path) -> None:
    root = _source_tree(tmp_path)
    before = get_build_info(project_root=root)
    (root / "build").mkdir()
    (root / "build/output.py").write_text("BUILD_TIMESTAMP = 123\n", encoding="utf-8")
    (root / ".env").write_text("API_KEY=do-not-include\n", encoding="utf-8")
    (root / "crypto_options_report/local-secret.pem").write_text("do-not-include", encoding="utf-8")

    after = get_build_info(project_root=root)

    assert before == after
    assert before.package_version == "0.4.0"
    assert before.source_digest.startswith("sha256:")
    assert before.git_commit is None
    assert before.git_state == "unknown"
    assert "do-not-include" not in json.dumps(before.to_dict())
    (root / "crypto_options_report/example.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert get_build_info(project_root=root).source_digest != before.source_digest


def test_frontend_source_changes_are_part_of_the_build_identity(tmp_path: Path) -> None:
    root = _source_tree(tmp_path)
    before = get_build_info(project_root=root)
    (root / "web/src/App.tsx").write_text("export const value = 2;\n", encoding="utf-8")
    assert get_build_info(project_root=root).source_digest != before.source_digest


def test_git_identity_is_observed_and_dirty_state_is_not_a_self_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is needed for observed repository identity")
    root = _source_tree(tmp_path)
    for arguments in (
        ["init", "--quiet"],
        ["add", "."],
        ["-c", "user.name=Build Contract", "-c", "user.email=build@example.invalid", "commit", "--quiet", "-m", "Fixture"],
    ):
        subprocess.run([git, *arguments], cwd=root, check=True, capture_output=True)
    expected = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=root, text=True).strip()
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.setenv("GIT_DIR", str(root / "does-not-exist"))
    monkeypatch.setenv("SOURCE_VERSION", "untrusted")

    clean = get_build_info(project_root=root)
    assert clean.git_commit == expected
    assert clean.git_state == "clean"
    (root / "crypto_options_report/example.py").write_text("VALUE = 3\n", encoding="utf-8")
    dirty = get_build_info(project_root=root)
    assert dirty.git_commit == expected
    assert dirty.git_state == "dirty"
    assert dirty.source_digest != clean.source_digest


def test_runtime_identity_is_bounded_and_serializable() -> None:
    first = get_build_info()
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert get_build_info() is first
    assert json.loads(json.dumps(first.to_dict()))["package_version"] == project["version"]
    assert "timestamp" not in first.to_dict()


def test_source_digest_does_not_follow_links_outside_the_source_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    root = _source_tree(source)
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = 'not-source'\n", encoding="utf-8")
    linked = root / "crypto_options_report/linked.py"
    try:
        linked.symlink_to(outside)
    except OSError:
        if os.name == "nt":
            pytest.skip("Windows symlink permission is not available")
        raise
    with pytest.raises(ValueError, match="linked"):
        get_build_info(project_root=root)
