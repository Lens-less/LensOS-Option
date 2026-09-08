import copy
import json
import socket
from pathlib import Path

import pytest

from tools.reproduce_research import FIXED_CLOCK, build_case, main


def test_packaged_case_is_repeatable_without_network_or_research_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline research case attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.chdir(tmp_path)
    first = build_case(FIXED_CLOCK)
    second = build_case(FIXED_CLOCK)

    assert first == second
    assert first["evaluation_clock"] == FIXED_CLOCK
    assert first["trust_verdict"] == "untrusted"
    assert "MARKET_EVIDENCE_NOT_TRUSTED" in first["reason_codes"]
    assert first["strategy_brief"]["action"] == "NO_TRADE"
    assert first["strategy_brief"]["strategies"] == []
    assert first["research_only"] is True
    assert first["execution_allowed"] is False
    assert first["decisions"]
    assert all(item["execution_allowed"] is False for item in first["decisions"])
    assert "historical_artifact_hash" in first["missing_evidence"]
    assert list(tmp_path.iterdir()) == []


def test_case_verification_accepts_replay_and_rejects_changed_claim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "case.json"
    assert main(["--output", str(output)]) == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == build_case(FIXED_CLOCK)
    assert main(["--verify", str(output)]) == 0
    assert "matches" in capsys.readouterr().out

    changed = copy.deepcopy(saved)
    changed["trust_verdict"] = "trusted"
    output.write_text(json.dumps(changed), encoding="utf-8")
    assert main(["--verify", str(output)]) == 1
    assert "does not match" in capsys.readouterr().err


def test_explicit_clock_changes_case_and_rejects_naive_time() -> None:
    base = build_case(FIXED_CLOCK)
    stale = build_case("2026-07-08T00:01:30Z")
    assert stale["case_sha256"] != base["case_sha256"]
    assert stale["execution_allowed"] is False
    assert stale["strategy_brief"]["action"] == "NO_TRADE"
    with pytest.raises(ValueError, match="timezone"):
        build_case("2026-07-07T00:01:30")


def test_default_and_check_print_compact_actual_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--check"]) == 0
    output = capsys.readouterr().out
    assert "repeatability=PASS" in output
    assert "trust=untrusted action=NO_TRADE" in output
    assert "execution_allowed=false" in output
    assert "case_sha256=" in output


def test_check_rejects_differing_complete_results(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from tools import reproduce_research

    outcomes = iter([{"case_sha256": "first"}, {"case_sha256": "second"}])
    monkeypatch.setattr(reproduce_research, "build_case", lambda generated_at: next(outcomes))
    assert main(["--check"]) == 1
    assert "Repeatability failed" in capsys.readouterr().err
