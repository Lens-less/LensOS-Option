from __future__ import annotations

import copy
import http.client
import json
import threading
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest

from crypto_options_report.api import (
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
)
from crypto_options_report.decision_desk import DEFAULT_CRITERIA
from crypto_options_report.desk_demo import demo_desk_snapshot
from crypto_options_report.desk_service import DeskRequestError, DeskService


@contextmanager
def desk_http():
    server = ResearchHTTPServer(("127.0.0.1", 0), ResearchReportHandler, runtime=RuntimeConfig())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(server, path, body, *, origin=None, extra_headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    headers = {"Content-Type": "application/json", "Origin": origin or f"http://127.0.0.1:{server.server_port}"}
    headers.update(extra_headers or {})
    try:
        connection.request("POST", path, body=json.dumps(body), headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def discover_request(viewpoint="all"):
    return {"asset": "BTC", "mode": "demo", "criteria": {**DEFAULT_CRITERIA, "viewpoint": viewpoint}}


def compatible(desk):
    expiry = desk["candidates"][0]["expiry_date"]
    return [row for row in desk["candidates"] if row["expiry_date"] == expiry and row["status"] == "comparable"][:3]


def comparison_request(desk):
    return {"snapshot_id": desk["snapshot_id"], "analysis_id": desk["analysis_id"],
            "candidate_ids": [row["candidate_id"] for row in compatible(desk)],
            "scenario": {"price_change_pct": -8, "time_days": 2, "iv_shift_points": 5}}


def test_real_http_demo_discover_compare_and_exact_review_preserve_frozen_identity():
    with desk_http() as server:
        status, desk = post(server, "/desk/discover", discover_request())
        assert status == 200
        assert desk["source"]["mode"] == "demo"
        assert desk["coverage"]["scan_complete"] is True
        assert desk["qualification"]["execution_allowed"] is False
        assert {row["structure"] for row in compatible(desk)} == {"BULL_PUT_CREDIT", "BEAR_CALL_CREDIT", "IRON_CONDOR"}
        original = copy.deepcopy(desk)
        status, comparison = post(server, "/desk/compare", comparison_request(desk))
        assert status == 200
        assert comparison["analysis_id"] == desk["analysis_id"]
        assert comparison["execution_allowed"] is False
        assert len(comparison["members"]) == 3
        assert all(row["stress"] is not None for row in comparison["members"])
        saved = compatible(desk)[0]
        status, review = post(server, "/desk/review", {"original_desk": desk, "candidate_id": saved["candidate_id"]})
        assert status == 200
        assert review["status"] == "current"
        assert review["original_candidate_id"] == saved["candidate_id"]
        current = review["desk"]["candidates"][0]
        assert review["reviewed_candidate_id"] == current["candidate_id"]
        assert [row["instrument_name"] for row in current["legs"]] == [row["instrument_name"] for row in saved["legs"]]
        assert desk == original


def test_http_desk_preserves_origin_source_and_operator_auth_boundaries():
    with desk_http() as server:
        assert post(server, "/desk/discover", discover_request(), origin="https://unrelated.invalid")[0] == 403
        assert post(server, "/desk/discover", {**discover_request(), "base_url": "http://127.0.0.1/private"})[0] == 400
        assert post(server, "/desk/discover", {**discover_request(), "mode": "live"})[0] == 409
        server.expected_bearer_authorization = "Bearer " + "x" * 32
        assert post(server, "/desk/discover", discover_request())[0] == 401
        assert post(server, "/desk/discover", discover_request(), extra_headers={"Authorization": "Bearer " + "x" * 32})[0] == 200


def test_different_filters_on_one_source_snapshot_do_not_overwrite_analysis():
    service = DeskService(allow_live=False)
    snapshot = demo_desk_snapshot("BTC")
    with patch("crypto_options_report.desk_service.demo_desk_snapshot", return_value=snapshot):
        all_desk = service.dispatch("/desk/discover", discover_request())
        bullish = service.dispatch("/desk/discover", discover_request("bullish"))
    assert all_desk["snapshot_id"] == bullish["snapshot_id"]
    assert all_desk["analysis_id"] != bullish["analysis_id"]
    assert service.dispatch("/desk/compare", comparison_request(all_desk))["analysis_id"] == all_desk["analysis_id"]
    altered = comparison_request(all_desk)
    altered["analysis_id"] = bullish["analysis_id"]
    with pytest.raises(ValueError, match="selected candidate"):
        service.dispatch("/desk/compare", altered)


def test_invalid_filters_and_invalid_exact_structure_never_trigger_public_reads():
    collector = Mock()
    service = DeskService(allow_live=True, collector=collector)
    with pytest.raises(ValueError, match="viewpoint"):
        service.dispatch("/desk/discover", {**discover_request("invalid"), "mode": "live"})
    collector.fetch_snapshot.assert_not_called()
    original = DeskService(allow_live=False).dispatch("/desk/discover", discover_request())
    original["source"]["mode"] = "live"
    selected = original["candidates"][0]
    selected["legs"][0]["ratio"] = 0
    with pytest.raises(ValueError, match=r"ratio|metadata"):
        service.dispatch("/desk/review", {"original_desk": original, "candidate_id": selected["candidate_id"]})
    collector.review_exact.assert_not_called()


def test_missing_or_expired_snapshots_cannot_be_compared():
    service = DeskService(allow_live=False)
    desk = service.dispatch("/desk/discover", discover_request())
    service._desks[desk["analysis_id"]]["expires_at"] = "2000-01-01T00:00:00Z"
    with pytest.raises(DeskRequestError) as error:
        service.dispatch("/desk/compare", comparison_request(desk))
    assert error.value.status == 409


def test_expired_exact_review_preserves_identity_and_never_selects_replacements():
    collector = Mock()
    service = DeskService(allow_live=True, collector=collector)
    desk = DeskService(allow_live=False).dispatch("/desk/discover", discover_request())
    saved = desk["candidates"][0]
    saved["expiration_timestamp"] = 1_700_000_000_000
    desk["source"]["mode"] = "live"
    review = service.dispatch("/desk/review", {"original_desk": desk, "candidate_id": saved["candidate_id"]})
    assert review["status"] == "expired"
    assert review["original_candidate_id"] == saved["candidate_id"]
    assert review["desk"] is None
    collector.review_exact.assert_not_called()
