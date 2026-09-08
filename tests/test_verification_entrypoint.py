"""The contributor gate must not silently accept a source-only subset."""

import subprocess
import sys
from pathlib import Path

import pytest

from tools import verify


def test_quick_listing_explicitly_identifies_omitted_release_checks(capsys) -> None:
    assert verify.main(["--quick", "--list"]) == 0
    output = capsys.readouterr().out
    assert "QUICK subset" in output
    assert "installed wheel and browser journey are excluded" in output
    assert "Python tests" in output
    assert "Web tests" in output
    assert "Public build" not in output


def test_default_gate_builds_before_verifying_installed_artifacts(monkeypatch) -> None:
    completed = []
    monkeypatch.setattr(verify, "run", lambda label, command, **kwargs: completed.append(label))
    monkeypatch.setattr(verify, "verify_extension", lambda: completed.append("Extension artifact"))
    monkeypatch.setattr(verify, "verify_wheel", lambda **kwargs: completed.append("Installed wheel browser"))

    assert verify.main([]) == 0
    assert completed.index("Public build") < completed.index("Public bundle boundary")
    assert completed.index("Chrome companion build") < completed.index("Extension artifact")
    assert completed[-1] == "Installed wheel browser"


def test_gate_includes_types_version_consistency_and_reproducible_research(capsys) -> None:
    assert verify.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "Python static types" in output
    assert "Source version consistency" in output
    assert "Offline research reproducibility" in output


def test_every_static_gate_ignores_old_mypy_cache() -> None:
    for quick in (False, True):
        commands = {label: command for label, command, _ in verify.source_steps(quick=quick)}
        assert "--no-incremental" in commands["Python static types"]


def test_final_wheel_routes_each_built_surface_to_its_acceptance_tool(monkeypatch, tmp_path: Path) -> None:
    commands = {}

    def run(label, command, **kwargs):
        commands[label] = command
        if label == "Build final wheel":
            output = Path(command[-1])
            output.mkdir()
            (output / "consumer.whl").write_bytes(b"placeholder: no build in this routing test")

    monkeypatch.setattr(verify, "run", run)
    monkeypatch.setattr(verify.venv.EnvBuilder, "create", lambda *args: None)
    verify.verify_wheel(output_dir=tmp_path)

    versions = commands["Final artifact version consistency"]
    assert "--extension-dir" in versions
    assert "--public-build-dir" not in versions
    browser = commands["Installed wheel browser journey"]
    assert browser[browser.index("--public-build-dir") + 1] == str(verify.WEB / "dist-public")
    assert browser[browser.index("--extension-dir") + 1] == str(verify.WEB / "dist" / "chrome-extension")
    assert str(tmp_path.resolve()) in browser


def test_public_boundary_failure_stops_installed_artifact_acceptance(monkeypatch) -> None:
    completed = []

    def run(label, command, **kwargs):
        if label == "Public bundle boundary":
            raise subprocess.CalledProcessError(1, command)
        completed.append(label)

    monkeypatch.setattr(verify, "run", run)
    monkeypatch.setattr(verify, "verify_wheel", lambda **kwargs: completed.append("Installed wheel browser"))

    assert verify.main([]) == 1
    assert "Chrome companion build" not in completed
    assert "Installed wheel browser" not in completed


def test_smoke_success_prints_a_summary_without_the_full_report(capsys) -> None:
    verify.run("API smoke", [sys.executable, "-c", "print('verbose report')", "--smoke"])
    output = capsys.readouterr().out
    assert "Smoke checks passed." in output
    assert "verbose report" not in output


def test_smoke_failure_preserves_output_and_exit_status(capsys) -> None:
    with pytest.raises(subprocess.CalledProcessError) as error:
        verify.run("API smoke", [sys.executable, "-c", "print('failure context'); raise SystemExit(3)", "--smoke"])
    assert error.value.returncode == 3
    assert "failure context" in capsys.readouterr().err
