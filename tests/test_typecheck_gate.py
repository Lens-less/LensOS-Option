"""The configured checker must reject broken use of a migrated public interface."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(importlib.util.find_spec("mypy") is None, reason="mypy is in the development extra")
def test_static_gate_accepts_build_identity_and_rejects_a_wrong_consumer_type(tmp_path: Path) -> None:
    consumer = tmp_path / "identity_consumer.py"
    prefix = "from crypto_options_report.build_info import get_build_info\n"

    def check(annotation: str) -> subprocess.CompletedProcess[str]:
        consumer.write_text(prefix + f"version: {annotation} = get_build_info().package_version\n", encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "mypy", "--no-incremental", "--config-file", str(ROOT / "pyproject.toml"), str(consumer)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )

    valid = check("str")
    assert valid.returncode == 0, valid.stdout + valid.stderr
    invalid = check("int")
    assert invalid.returncode != 0
    assert "[assignment]" in invalid.stdout, invalid.stdout + invalid.stderr
