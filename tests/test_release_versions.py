import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from tools.check_release_versions import check_versions


def _version_tree(root: Path) -> Path:
    (root / "web/extension").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "crypto-options-research-console"\nversion = "0.4.0"\n', encoding="utf-8"
    )
    for path, value in (
        ("web/package.json", {"version": "0.4.0"}),
        ("web/package-lock.json", {"version": "0.4.0", "packages": {"": {"version": "0.4.0"}}}),
        ("web/extension/manifest.json", {"version": "0.4.0"}),
    ):
        (root / path).write_text(json.dumps(value), encoding="utf-8")
    return root


def _wheel(root: Path, version: str = "0.4.0") -> Path:
    wheel = root / "crypto_options_research_console.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("crypto_options_research_console.dist-info/METADATA", f"Metadata-Version: 2.4\nName: crypto-options-research-console\nVersion: {version}\n")
    return wheel


def test_versions_match_local_source_and_explicit_release_artifact(tmp_path: Path) -> None:
    root = _version_tree(tmp_path)
    assert set(check_versions(root).values()) == {"0.4.0"}
    observed = check_versions(root, release_tag="v0.4.0", wheel_path=_wheel(root))
    assert observed["release_tag"] == "0.4.0"
    assert observed["wheel"] == "0.4.0"


@pytest.mark.parametrize("source", ["package", "lockfile", "lockfile_root", "extension", "tag", "wheel"])
def test_each_version_mismatch_blocks_release(tmp_path: Path, source: str) -> None:
    root = _version_tree(tmp_path)
    wheel = _wheel(root, "0.4.1" if source == "wheel" else "0.4.0")
    if source in {"package", "extension"}:
        path = "web/package.json" if source == "package" else "web/extension/manifest.json"
        (root / path).write_text('{"version":"0.4.1"}', encoding="utf-8")
    if source in {"lockfile", "lockfile_root"}:
        path = root / "web/package-lock.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if source == "lockfile":
            payload["version"] = "0.4.1"
        else:
            payload["packages"][""]["version"] = "0.4.1"
        path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="version mismatch"):
        check_versions(root, release_tag="v0.4.1" if source == "tag" else "v0.4.0", wheel_path=wheel)


def test_missing_lock_root_version_fails_closed(tmp_path: Path) -> None:
    root = _version_tree(tmp_path)
    (root / "web/package-lock.json").write_text('{"version":"0.4.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="lockfile root"):
        check_versions(root)


def test_cli_rejects_mismatched_explicit_tag(tmp_path: Path) -> None:
    root = _version_tree(tmp_path)
    script = Path(__file__).resolve().parents[1] / "tools/check_release_versions.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--tag", "v0.5.0"],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "version mismatch" in completed.stderr


def _extension_artifact(root: Path, kind: str, state: str = "matching") -> Path:
    version = "0.4.1" if state == "mismatch" else "0.4.0"
    manifest = json.dumps({"manifest_version": 3, "version": version})
    contents = {} if state == "missing" else {"manifest.json": manifest}
    if state == "multiple":
        contents["stale/manifest.json"] = manifest
    if state == "invalid":
        contents["manifest.json"] = "[]"
    if kind == "directory":
        directory = root / "dist/chrome-extension"
        directory.mkdir(parents=True)
        for name, payload in contents.items():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
        return directory
    archive_path = root / "extension-release.zip"
    with ZipFile(archive_path, "w") as archive:
        for name, payload in contents.items():
            archive.writestr(name, payload)
    return archive_path


@pytest.mark.parametrize("kind", ["directory", "zip"])
def test_final_extension_artifact_version_is_checked(tmp_path: Path, kind: str) -> None:
    root = _version_tree(tmp_path)
    artifact = _extension_artifact(root, kind)
    arguments = {"extension_dir" if kind == "directory" else "extension_zip": artifact}

    observed = check_versions(root, **arguments)

    assert observed["extension_directory" if kind == "directory" else "extension_zip"] == "0.4.0"


@pytest.mark.parametrize("kind", ["directory", "zip"])
@pytest.mark.parametrize("state", ["mismatch", "missing", "multiple", "invalid"])
def test_invalid_final_extension_artifact_blocks_release(tmp_path: Path, kind: str, state: str) -> None:
    root = _version_tree(tmp_path)
    artifact = _extension_artifact(root, kind, state)
    arguments = {"extension_dir" if kind == "directory" else "extension_zip": artifact}
    expected_error = "version mismatch" if state == "mismatch" else "manifest"

    with pytest.raises(ValueError, match=expected_error):
        check_versions(root, **arguments)


def test_cli_checks_final_extension_directory_and_zip_together(tmp_path: Path) -> None:
    root = _version_tree(tmp_path)
    directory = _extension_artifact(root, "directory")
    archive = _extension_artifact(root, "zip")
    script = Path(__file__).resolve().parents[1] / "tools/check_release_versions.py"
    arguments = [
        sys.executable, str(script), "--root", str(root),
        "--extension-dir", str(directory), "--extension-zip", str(archive),
    ]
    matching = subprocess.run(arguments, capture_output=True, text=True, check=False)
    assert matching.returncode == 0, matching.stderr
    assert "extension_directory=0.4.0" in matching.stdout
    assert "extension_zip=0.4.0" in matching.stdout

    (directory / "manifest.json").write_text('{"version":"0.4.1"}', encoding="utf-8")
    mismatched = subprocess.run(arguments, capture_output=True, text=True, check=False)
    assert mismatched.returncode == 1
    assert "version mismatch" in mismatched.stderr
