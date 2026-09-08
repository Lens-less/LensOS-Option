"""Fresh PEP 517/660 metadata must not import an installed application package."""

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("hook", ["prepare_metadata_for_build_wheel", "prepare_metadata_for_build_editable"])
def test_metadata_can_be_prepared_without_the_application_on_sys_path(tmp_path: Path, hook: str) -> None:
    source = tmp_path / "source"
    package = source / "crypto_options_report"
    package.mkdir(parents=True)
    for name in ("setup.py", "pyproject.toml", "README.md", "LICENSE", "LICENSE-DATA"):
        shutil.copyfile(ROOT / name, source / name)
    shutil.copyfile(ROOT / "crypto_options_report/build_info.py", package / "build_info.py")
    # Importing the application at build time must remain unnecessary, even
    # when an unrelated/old installation exists in the build interpreter.
    (package / "__init__.py").write_text("raise RuntimeError('application imported during build')\n", encoding="utf-8")
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    code = """
import json, os, sys
from setuptools import build_meta
os.chdir(sys.argv[1])
sys.modules['crypto_options_report'] = None
result = getattr(build_meta, sys.argv[2])(sys.argv[3])
print(json.dumps({'metadata': result}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(source), hook, str(metadata)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout.strip().splitlines()[-1])
    contents = (metadata / output["metadata"] / "METADATA").read_text(encoding="utf-8")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert f"Version: {version}\n" in contents


@pytest.mark.parametrize("mode", ["lenient", "strict"])
def test_editable_build_does_not_claim_or_embed_wheel_only_identity(tmp_path: Path, mode: str) -> None:
    source = tmp_path / "source"
    package = source / "crypto_options_report"
    package.mkdir(parents=True)
    for name in ("setup.py", "pyproject.toml", "README.md", "LICENSE", "LICENSE-DATA"):
        shutil.copyfile(ROOT / name, source / name)
    shutil.copyfile(ROOT / "crypto_options_report/build_info.py", package / "build_info.py")
    (package / "__init__.py").write_text("", encoding="utf-8")
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    code = """
import json, os, sys
from setuptools import build_meta
os.chdir(sys.argv[1])
sys.modules['crypto_options_report'] = None
settings = {'editable_mode': 'strict'} if sys.argv[3] == 'strict' else {}
result = build_meta.build_editable(sys.argv[2], settings)
print(json.dumps({'wheel': result}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(source), str(wheels), mode],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Customization incompatible with editable install" not in result.stdout + result.stderr
    output = json.loads(result.stdout.strip().splitlines()[-1])
    with ZipFile(wheels / output["wheel"]) as archive:
        assert any(name.endswith(".pth") for name in archive.namelist())
        assert not any(name.endswith("_build_info.json") for name in archive.namelist())
    assert not (package / "_build_info.json").exists()
