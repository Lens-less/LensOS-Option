import json
import shutil
import socket
from pathlib import Path

import pytest

from tools.prepare_public_browser_case import main, prepare_case

ROOT = Path(__file__).resolve().parents[1]


def _public_build(tmp_path: Path) -> Path:
    """Minimal source bundle for publisher tests; browser acceptance uses Vite output."""
    build = tmp_path / "public-build"
    shutil.copytree(ROOT / "web/public", build)
    for filename in ("LICENSE", "LICENSE-DATA"):
        shutil.copy2(ROOT / filename, build / filename)
    (build / "assets").mkdir(exist_ok=True)
    (build / "index.html").write_text(
        '<!doctype html><html><head><title>Public fixture</title></head>'
        '<body><div id="root"></div><script type="module" src="./assets/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (build / "assets/app.js").write_text('document.title = "Public fixture";', encoding="utf-8")
    return build


def test_public_case_uses_real_publisher_offline_and_preserves_historical_execution_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Public browser fixture attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    build = _public_build(tmp_path)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "site"
    case = prepare_case(public_build_dir=build, output_dir=output)
    health = json.loads((output / "api/v1/health.json").read_text(encoding="utf-8"))
    report = json.loads((output / "research/report").read_text(encoding="utf-8"))
    assert case["captured_at"] == "2026-07-07T00:01:00Z"
    assert case["published_at"] == "2026-07-07T00:01:30Z"
    assert case["stale_after"] == "2026-07-09T00:01:00Z"
    assert case["is_stale_at_publish"] is False
    assert case["execution_allowed"] is False
    assert case["inputs"]["snapshot_source"] == "demo:bundled-option-chain"
    assert case["inputs"]["underlying_history"].startswith("fixture:")
    assert case["inputs"]["dvol_history"].startswith("fixture:")
    assert health["is_stale_at_publish"] is False
    assert report["runtime_context"]["live_fetch_allowed"] is False
    assert report["strategy_brief"]["execution_allowed"] is False
    assert report["strategy_brief"]["action"] == "NO_TRADE"
    assert (output / "api/v1/manifest.json").read_bytes() == (
        output / ".well-known/publish-manifest.json"
    ).read_bytes()
    assert (output / "assets/app.js").read_bytes() == (build / "assets/app.js").read_bytes()


def test_public_case_refuses_to_overwrite_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    build = _public_build(tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    existing = output / "keep.txt"
    existing.write_text("existing content", encoding="utf-8")
    assert main(["--public-build-dir", str(build), "--output-dir", str(output)]) == 1
    assert "output directory must not already contain files" in capsys.readouterr().err
    assert existing.read_text(encoding="utf-8") == "existing content"
    assert list(output.iterdir()) == [existing]
