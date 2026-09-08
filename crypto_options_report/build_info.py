"""Observed code identity, independent of analysis and report protocol versions.

An installed wheel uses the identity captured by ``build_py``. A source process
captures its identity on first use, matching the code loaded by that process;
restart after editing source to observe a new runtime identity. Explicit source
inspection is uncached, so packaging always captures the current tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Literal, TypedDict

PACKAGE_NAME = "crypto-options-research-console"
EMBEDDED_FILENAME = "_build_info.json"
_SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".css", ".html", ".json", ".md", ".svg"}
_EXCLUDED_DIRECTORIES = {"__pycache__", "node_modules", "dist", "public-dist", "extension-dist", ".cache"}


class BuildInfoDict(TypedDict):
    package_version: str
    source_digest: str | None
    git_commit: str | None
    git_state: Literal["clean", "dirty", "unknown"]
    source_kind: Literal["working_tree", "embedded", "unknown"]


@dataclass(frozen=True)
class BuildInfo:
    package_version: str
    source_digest: str | None
    git_commit: str | None
    git_state: Literal["clean", "dirty", "unknown"]
    source_kind: Literal["working_tree", "embedded", "unknown"]

    def to_dict(self) -> BuildInfoDict:
        return {
            "package_version": self.package_version,
            "source_digest": self.source_digest,
            "git_commit": self.git_commit,
            "git_state": self.git_state,
            "source_kind": self.source_kind,
        }


def get_build_info(*, project_root: Path | None = None) -> BuildInfo:
    """Return process identity, or freshly inspect an explicitly supplied source tree.

    ``source_digest`` hashes declared application/build source paths and contents,
    with normalized line endings. It excludes Git metadata, credentials, caches,
    test reports and compiled outputs; it is not a hash of the wheel archive.
    Git fields are observations, not a signed attestation of release authority.
    """
    if project_root is not None:
        return _source_build_info(Path(project_root).resolve())
    return _runtime_build_info()


@lru_cache(maxsize=1)
def _runtime_build_info() -> BuildInfo:
    embedded = Path(__file__).with_name(EMBEDDED_FILENAME)
    if embedded.is_file():
        return _read_embedded(embedded)
    root = Path(__file__).resolve().parent.parent
    if (root / "pyproject.toml").is_file():
        return _source_build_info(root)
    try:
        version = metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        version = "unknown"
    return BuildInfo(version, None, None, "unknown", "unknown")


def _read_embedded(path: Path) -> BuildInfo:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format_version") != 1:
            raise ValueError("unsupported format")
        info = BuildInfo(**payload["build_info"])
        if (
            not isinstance(info.package_version, str)
            or not info.package_version
            or not isinstance(info.source_digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", info.source_digest) is None
            or info.git_state not in {"clean", "dirty", "unknown"}
            or info.source_kind != "working_tree"
            or (
                info.git_commit is not None
                and (
                    not isinstance(info.git_commit, str)
                    or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", info.git_commit) is None
                )
            )
            or (info.git_state != "unknown" and info.git_commit is None)
        ):
            raise ValueError("invalid fields")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid embedded build identity") from error
    return replace(info, source_kind="embedded")


def _source_build_info(root: Path) -> BuildInfo:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project.get("name") != PACKAGE_NAME or not isinstance(project.get("version"), str):
        raise ValueError("build identity requires this project's package metadata")
    digest = hashlib.sha256()
    for path in _source_paths(root):
        name = path.relative_to(root).as_posix().encode("utf-8")
        contents = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    commit, state = _git_identity(root)
    return BuildInfo(project["version"], f"sha256:{digest.hexdigest()}", commit, state, "working_tree")


def _source_paths(root: Path) -> list[Path]:
    paths: set[Path] = set()
    # Explicit source roots prevent .env files, local recordings and build output
    # from becoming part of a public identity. Packaged resources are source data.
    for relative, suffixes in (
        ("crypto_options_report", {".py"}),
        ("crypto_options_report/resources", {".json", ".md"}),
        ("web/src", _SOURCE_SUFFIXES),
        ("web/extension", _SOURCE_SUFFIXES),
        ("web/public", _SOURCE_SUFFIXES),
        ("tools", {".py", ".mjs", ".ps1"}),
    ):
        directory = root / relative
        if not directory.exists():
            continue
        _validate_source_path(directory, root)
        for current, directories, filenames in os.walk(directory, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in _EXCLUDED_DIRECTORIES)
            for name in directories:
                _validate_source_path(Path(current) / name, root)
            for name in filenames:
                path = Path(current) / name
                if path.suffix in suffixes and path.name != EMBEDDED_FILENAME:
                    _validate_source_path(path, root)
                    paths.add(path)
    for relative in ("setup.py", "pyproject.toml", "web/package.json", "web/package-lock.json", "web/index.html"):
        path = root / relative
        if path.is_file():
            _validate_source_path(path, root)
            paths.add(path)
    web = root / "web"
    for pattern in ("vite*.ts", "tsconfig*.json"):
        for path in web.glob(pattern):
            _validate_source_path(path, root)
            paths.add(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def _validate_source_path(path: Path, root: Path) -> None:
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if path.is_symlink() or is_junction(path) or not path.resolve().is_relative_to(root):
        raise ValueError("build identity refuses linked or external source paths")


def _git_identity(root: Path) -> tuple[str | None, Literal["clean", "dirty", "unknown"]]:
    # Do not accept CI-provided SHA strings or Git environment redirection as
    # provenance. Local worktree configuration still supports normal worktrees.
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}

    def run(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        ).stdout.strip()

    try:
        if Path(run("rev-parse", "--show-toplevel")).resolve() != root:
            return None, "unknown"
        commit = run("rev-parse", "--verify", "HEAD")
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:
            return None, "unknown"
        dirty = bool(run("status", "--porcelain=v1", "--untracked-files=normal"))
        return commit, "dirty" if dirty else "clean"
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None, "unknown"
