"""Check source, release-tag, wheel and extension versions without dependencies."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

PACKAGE_NAME = "crypto-options-research-console"


def _version(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"missing or invalid {label} version")
    return value


def _extension_manifest_version(contents: str | bytes, label: str) -> str:
    try:
        manifest = json.loads(contents)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"invalid {label} manifest.json") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"invalid {label} manifest.json")
    return _version(manifest.get("version"), f"{label} manifest.json")


def check_versions(
    project_root: Path,
    *,
    release_tag: str | None = None,
    wheel_path: Path | None = None,
    extension_dir: Path | None = None,
    extension_zip: Path | None = None,
) -> dict[str, str]:
    """Return matching observed versions; raise for missing or conflicting data."""
    root = Path(project_root)
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project.get("name") != PACKAGE_NAME:
        raise ValueError("unexpected Python distribution name")

    def read_json(relative: str) -> dict[str, object]:
        value = json.loads((root / relative).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"invalid version metadata: {relative}")
        return value

    package = read_json("web/package.json")
    lockfile = read_json("web/package-lock.json")
    extension = read_json("web/extension/manifest.json")
    lock_packages = lockfile.get("packages")
    lock_root = lock_packages.get("") if isinstance(lock_packages, dict) else None
    if not isinstance(lock_root, dict):
        raise ValueError("missing or invalid lockfile root version")
    observed = {
        "python": _version(project.get("version"), "Python"),
        "web": _version(package.get("version"), "Web"),
        "lockfile": _version(lockfile.get("version"), "lockfile"),
        "lockfile_root": _version(lock_root.get("version"), "lockfile root"),
        "extension": _version(extension.get("version"), "extension"),
    }
    if release_tag is not None:
        tag = _version(release_tag, "release tag")
        observed["release_tag"] = tag.removeprefix("v")
    if wheel_path is not None:
        with ZipFile(wheel_path) as archive:
            metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_paths) != 1:
                raise ValueError("wheel must contain exactly one distribution METADATA")
            metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
        if str(metadata.get("Name", "")).replace("_", "-") != PACKAGE_NAME:
            raise ValueError("wheel has an unexpected distribution name")
        observed["wheel"] = _version(metadata.get("Version"), "wheel")
    if extension_dir is not None:
        directory = Path(extension_dir)
        manifests = list(directory.rglob("manifest.json")) if directory.is_dir() else []
        if len(manifests) != 1 or not manifests[0].is_file():
            raise ValueError("extension directory must contain exactly one manifest.json")
        observed["extension_directory"] = _extension_manifest_version(
            manifests[0].read_bytes(), "extension directory",
        )
    if extension_zip is not None:
        with ZipFile(extension_zip) as archive:
            zip_manifests = [
                entry for entry in archive.infolist()
                if PurePosixPath(entry.filename).name == "manifest.json" and not entry.is_dir()
            ]
            if len(zip_manifests) != 1:
                raise ValueError("extension ZIP must contain exactly one manifest.json")
            observed["extension_zip"] = _extension_manifest_version(
                archive.read(zip_manifests[0]), "extension ZIP",
            )
    expected = observed["python"]
    conflicts = [f"{label}={value}" for label, value in observed.items() if value != expected]
    if conflicts:
        raise ValueError(f"version mismatch: Python={expected}; " + "; ".join(conflicts))
    return observed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tag", help="Explicit release tag (v prefix accepted); omitted for local checks")
    parser.add_argument("--wheel", type=Path, help="Final wheel whose distribution metadata must match")
    parser.add_argument("--extension-dir", type=Path, help="Final extension build directory whose manifest must match")
    parser.add_argument("--extension-zip", type=Path, help="Final extension release ZIP whose manifest must match")
    arguments = parser.parse_args(argv)
    try:
        observed = check_versions(
            arguments.root,
            release_tag=arguments.tag,
            wheel_path=arguments.wheel,
            extension_dir=arguments.extension_dir,
            extension_zip=arguments.extension_zip,
        )
    except (OSError, KeyError, TypeError, ValueError, BadZipFile) as error:
        print(f"Release version check failed: {error}", file=sys.stderr)
        return 1
    print("Release versions match: " + ", ".join(f"{label}={version}" for label, version in observed.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
