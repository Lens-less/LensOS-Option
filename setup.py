"""Small setuptools hook that prevents stale build-tree files entering wheels."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

PROJECT_ROOT = Path(__file__).resolve().parent
EXPECTED_BUILD_ROOT = Path(os.path.abspath(PROJECT_ROOT / "build"))
PACKAGE_DIRECTORY = "crypto_options_report"


def _load_build_info():
    # PEP 517 metadata hooks run before the package is installed and need not
    # place the source root on sys.path. Load the stdlib-only helper by its
    # exact path, so an older installed distribution cannot supply build code.
    name = "_lensos_option_build_info"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / PACKAGE_DIRECTORY / "build_info.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the source build identity helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_build_info = _load_build_info()
EMBEDDED_FILENAME = _build_info.EMBEDDED_FILENAME
get_build_info = _build_info.get_build_info


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
        if self.editable_mode:
            # PEP 660 uses a temporary build directory and maps back to source.
            # Its runtime identity must remain the source identity; wheel-only
            # cleanup and embedded outputs do not belong to this build mode.
            super().run()
            return
        staged_package = _validated_staged_package(self.build_lib)
        if staged_package.exists():
            shutil.rmtree(staged_package)
        super().run()
        # Only write to the validated build tree. Source checkouts and sdists do
        # not acquire stale generated identity files after a local wheel build.
        identity = get_build_info(project_root=PROJECT_ROOT)
        (staged_package / EMBEDDED_FILENAME).write_text(
            json.dumps(
                {"format_version": 1, "build_info": identity.to_dict()},
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n",
            encoding="utf-8",
        )

    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = super().get_outputs(include_bytecode)
        if self.editable_mode:
            return outputs
        return outputs + [
            str(Path(self.build_lib) / PACKAGE_DIRECTORY / EMBEDDED_FILENAME)
        ]


setup(cmdclass={"build_py": CleanBuildPy})
