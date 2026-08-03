"""Small setuptools hook that prevents stale build-tree files entering wheels."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

PROJECT_ROOT = Path(__file__).resolve().parent
EXPECTED_BUILD_ROOT = Path(os.path.abspath(PROJECT_ROOT / "build"))
PACKAGE_DIRECTORY = "crypto_options_report"


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    return path.is_symlink() or bool(is_junction(path))


def _validated_staged_package(build_lib: str) -> Path:
    build_directory = Path(os.path.abspath(build_lib))
    if not build_directory.is_relative_to(EXPECTED_BUILD_ROOT):
        raise RuntimeError("refusing to clean a build directory outside ./build")

    cursor = build_directory
    while True:
        if cursor.exists() and _is_link_or_junction(cursor):
            raise RuntimeError("refusing to traverse a linked build directory")
        if cursor == EXPECTED_BUILD_ROOT:
            break
        if cursor.parent == cursor:
            raise RuntimeError("build directory escaped the expected root")
        cursor = cursor.parent

    staged_package = build_directory / PACKAGE_DIRECTORY
    if staged_package.exists():
        if not staged_package.is_dir() or _is_link_or_junction(staged_package):
            raise RuntimeError("staged package is not a regular build directory")
        if not staged_package.resolve().is_relative_to(build_directory.resolve()):
            raise RuntimeError("staged package resolves outside the build directory")
    return staged_package


class CleanBuildPy(build_py):
    """Recreate the staged package so removed/hash-named assets cannot linger."""

    def run(self) -> None:
        staged_package = _validated_staged_package(self.build_lib)
        if staged_package.exists():
            shutil.rmtree(staged_package)
        super().run()


setup(cmdclass={"build_py": CleanBuildPy})
