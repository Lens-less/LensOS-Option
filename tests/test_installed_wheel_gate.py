import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tools import check_installed_wheel as consumer


def test_installed_consumer_covers_every_declared_console_entry_point() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["scripts"] == consumer.ENTRY_POINTS


def test_failed_dependency_check_stops_before_any_later_launcher_can_mask_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    commands = []

    def child(command, **kwargs):
        commands.append(command)
        assert not Path(kwargs["cwd"]).is_relative_to(Path(__file__).resolve().parents[1])
        assert "PYTHONPATH" not in kwargs["env"]
        assert "PYTHONHOME" not in kwargs["env"]
        if command[-2:] == ["pip", "check"]:
            return subprocess.CompletedProcess(command, 7, "broken installed dependency", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setenv("PYTHONPATH", "accidental-source-checkout")
    monkeypatch.setenv("PYTHONHOME", "accidental-interpreter")
    monkeypatch.setattr(consumer.subprocess, "run", child)

    assert consumer.main(["--python", sys.executable]) == 1
    assert len(commands) == 2
    assert all(command[1] == "-I" for command in commands)
    assert "broken installed dependency" in capsys.readouterr().err


def test_missing_installed_interpreter_fails_without_launching_subprocesses(tmp_path: Path) -> None:
    assert consumer.main(["--python", str(tmp_path / "missing-python")]) == 1
