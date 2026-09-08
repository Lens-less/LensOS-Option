"""Regression coverage for authentication revocation and hostile API inputs."""

import hashlib
import http.client
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from crypto_options_report.api import (
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
    _payload_for_path,
)
from crypto_options_report.public_api_contract import validate_public_projection
from crypto_options_report.series_history import build_series_history_report
from crypto_options_report.sidecar_auth import (
    ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV,
    MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV,
    write_sidecar_auth_state,
)
from crypto_options_report.signal_validation import (
    build_signal_preflight_report,
    build_signal_validation_report,
)

RESOURCES = Path(__file__).parents[1] / "crypto_options_report" / "resources"
SNAPSHOT = Path(__file__).with_name("fixtures") / "deribit_btc_option_chain_snapshot.json"


def _account_payload(clock):
    return {
        "schema_version": "deribit_account_snapshot.v1",
        "captured_at": clock,
        "source_endpoints": [
            "private/get_account_summary",
            "private/get_positions",
            "private/get_open_orders_by_currency",
        ],
        "account": {
            "status": "available",
            "source": "deribit_live_private_read_only",
            "source_endpoint": "private/get_account_summary",
            "observed_at": clock,
            "currency": "BTC",
            "equity": 100.0,
            "balance": 100.0,
            "margin_balance": 100.0,
            "available_funds": 90.0,
            "initial_margin": 10.0,
            "maintenance_margin": 5.0,
        },
        "positions": [],
        "open_orders": [],
        "simulation": {
            "status": "available",
            "attempted": True,
            "source_endpoint": "private/simulate_portfolio",
            "projected": {
                "initial_margin": 10.0,
                "maintenance_margin": 5.0,
                "nav_usd": 100.0,
            },
        },
        "replay_metadata": {
            "source": "live_deribit_private_read_only",
            "captured_shape_only": False,
        },
    }


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("revocation", ["delete", "rotate", "domain_alias"])
def test_cached_account_authentication_is_revoked_immediately(
    tmp_path, monkeypatch, replay, revocation
):
    data = tmp_path / "data"
    keys = tmp_path / "keys"
    data.mkdir()
    keys.mkdir()
    key_path = keys / "account.key"
    key_bytes = b"k" * 32
    assert len(key_bytes) == 32
    key_path.write_bytes(key_bytes)
    monkeypatch.setenv(ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV, str(key_path))
    monkeypatch.delenv(MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV, raising=False)
    clock = (
        json.loads(SNAPSHOT.read_text(encoding="utf-8"))["captured_at"]
        if replay
        else datetime.now(UTC).isoformat()
    )
    account = _account_payload(clock)
    account_path = data / "account.json"
    account_path.write_text(json.dumps(account), encoding="utf-8")
    write_sidecar_auth_state(account_path, expected_payload=account)
    runtime = RuntimeConfig(
        snapshot_fixture=str(SNAPSHOT) if replay else None,
        account_snapshot_fixture=str(account_path),
        replay=replay,
    )
    server = ResearchHTTPServer(("127.0.0.1", 0), ResearchReportHandler, runtime=runtime)
    try:
        first = server.analysis_record("")
        assert first.project_research_report_v1()["account_status"]["status"] == "available"
        assert server.analysis_record("") is first
        if revocation == "delete":
            key_path.unlink()
        elif revocation == "rotate":
            before = key_path.stat()
            key_path.write_bytes(b"x" * 32)
            # A key update can preserve both length and timestamps.
            os.utime(key_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        else:
            monkeypatch.setenv(MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV, str(key_path))
        revoked = server.analysis_record("")
        account_status = revoked.project_research_report_v1()["account_status"]
        assert revoked is not first
        assert account_status["status"] == "auth_failed"
        assert account_status["live_snapshot"] is False
        assert account_status["trade_gate"] == "NO_TRADE"
        serialized = json.dumps(revoked.to_dict())
        assert key_bytes.decode() not in serialized
        assert hashlib.sha256(key_bytes).hexdigest() not in serialized
    finally:
        server.server_close()


@pytest.mark.parametrize(
    ("name", "resource"),
    [("signal", "demo-signal-preflight.json"), ("series", "demo-series-history.json")],
)
@pytest.mark.parametrize(
    "mutation", ["unsafe_research", "missing_research", "wrong_schema", "execution", "nested_order"]
)
def test_operator_artifacts_reject_invalid_research_contracts(tmp_path, name, resource, mutation):
    artifact = json.loads((RESOURCES / resource).read_text(encoding="utf-8"))
    if mutation == "unsafe_research":
        artifact["research_only"] = False
    elif mutation == "missing_research":
        artifact.pop("research_only")
    elif mutation == "wrong_schema":
        artifact["schema_version"] = "unrecognized.v1"
    elif mutation == "execution":
        artifact["execution_allowed"] = True
    else:
        artifact["config"]["order_instruction"] = "BUY"
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    runtime = RuntimeConfig(**{f"{name}_artifact": str(path)})
    with pytest.raises(ValueError, match="artifact"):
        _payload_for_path(f"/research/{name}", "", runtime=runtime)


@pytest.mark.parametrize(
    ("name", "resource", "component"),
    [
        ("signal", "demo-signal-preflight.json", "ResearchSignal"),
        ("series", "demo-series-history.json", "ResearchSeries"),
    ],
)
def test_packaged_artifacts_remain_available(name, resource, component):
    runtime = RuntimeConfig(**{f"{name}_artifact": str(RESOURCES / resource)})
    payload = _payload_for_path(f"/research/{name}", "", runtime=runtime)
    assert payload["research_only"] is True
    validate_public_projection(component, payload)


@pytest.mark.parametrize("field", ["execution_allowed", "order_instruction", "recommended_size"])
def test_free_dictionary_cannot_smuggle_execution_fields(tmp_path, field):
    artifact = json.loads((RESOURCES / "demo-signal-preflight.json").read_text(encoding="utf-8"))
    artifact["signal_definitions"][field] = "BUY"
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact"):
        _payload_for_path("/research/signal", "", runtime=RuntimeConfig(signal_artifact=str(path)))


def test_artifact_projection_cannot_coerce_invalid_input_into_valid_output(tmp_path):
    artifact = json.loads((RESOURCES / "demo-signal-preflight.json").read_text(encoding="utf-8"))
    artifact["reason_codes"] = "INVALID_ARRAY"
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact"):
        _payload_for_path("/research/signal", "", runtime=RuntimeConfig(signal_artifact=str(path)))


@pytest.mark.parametrize("producer", ["validation", "preflight", "series"])
def test_empty_producer_artifacts_remain_available(tmp_path, producer):
    common = {"snapshots": [], "generated_at": "2026-09-08T00:00:00Z"}
    if producer == "series":
        artifact = build_series_history_report(**common)
        name = "series"
    else:
        builder = build_signal_preflight_report if producer == "preflight" else build_signal_validation_report
        artifact = builder(**common, underlying_history=None)
        name = "signal"
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    runtime = RuntimeConfig(**{f"{name}_artifact": str(path)})
    payload = _payload_for_path(f"/research/{name}", "", runtime=runtime)
    assert payload["research_only"] is True
    assert payload["status"] == artifact["status"]
    assert payload == artifact


def test_validated_artifact_retains_source_exclusion_evidence(tmp_path):
    artifact = build_signal_validation_report(
        snapshots=[{"captured_at": "bad-clock"}],
        underlying_history={"observations": [{"observed_at": "2026-09-07T00:00:00Z", "close": 100.0}]},
        generated_at="2026-09-08T00:00:00Z",
    )
    assert artifact["sample"]["excluded_snapshots"] == [
        {"captured_at": "bad-clock", "reason_code": "UNPARSEABLE_CAPTURED_AT"}
    ]
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    payload = _payload_for_path("/research/signal", "", runtime=RuntimeConfig(signal_artifact=str(path)))
    assert payload == artifact


@pytest.mark.parametrize(
    ("route", "report"),
    [
        ("/account/risk", {"account_status": []}),
        ("/dashboard", {"full_system_surface": []}),
        ("/dashboard", {"full_system_surface": {"dashboard": []}}),
    ],
)
def test_projection_endpoints_reject_non_object_payloads(route, report):
    record = SimpleNamespace(project_research_report_v1=lambda: report)
    with pytest.raises(ValueError, match="JSON object"):
        _payload_for_path(route, "", analysis_record=record)


@pytest.fixture
def authenticated_server():
    token = "a" * 32
    server = ResearchHTTPServer(("127.0.0.1", 0), ResearchReportHandler, bearer_token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, token
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_non_ascii_bearer_returns_controlled_authentication_error(authenticated_server):
    server, _ = authenticated_server
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/account/risk", headers={"Authorization": "Bearer caf\xe9"})
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 401
        assert payload == {"error": "authentication_required"}
    finally:
        connection.close()


def test_excessively_nested_json_returns_controlled_validation_error(authenticated_server):
    server, token = authenticated_server
    body = '{"schema_version":"backtest_run_request.v1","generated_at":' + "[" * 3000 + "0" + "]" * 3000 + "}"
    assert len(body) < 16 * 1024
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(
            "POST", "/backtest/run", body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Idempotency-Key": "nested-json-regression",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 400
        assert "JSON" in payload["error"]
    finally:
        connection.close()


def test_artifact_corruption_returns_error_instead_of_prior_output(tmp_path, authenticated_server):
    server, token = authenticated_server
    artifact = json.loads((RESOURCES / "demo-signal-preflight.json").read_text(encoding="utf-8"))
    path = tmp_path / "signal.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    server.runtime = RuntimeConfig(signal_artifact=str(path))

    def request():
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/research/signal", headers={"Authorization": f"Bearer {token}"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    status, first = request()
    assert status == 200
    assert first["status"] == "projected"
    artifact["execution_allowed"] = True
    path.write_text(json.dumps(artifact), encoding="utf-8")
    status, rejected = request()
    assert status == 400
    assert set(rejected) == {"error"}
    assert "artifact" in rejected["error"]
