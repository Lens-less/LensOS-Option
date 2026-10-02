"""Bounded, immutable research snapshots for the three decision workspaces."""
# ruff: noqa: RUF001

from __future__ import annotations

import copy
import json
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from ._time import utc_timestamp
from .decision_desk import (
    build_desk,
    compare_candidates,
    enumerate_provisional,
    evaluate_exact,
    validate_criteria,
    validate_exact_candidate,
)
from .desk_demo import demo_desk_snapshot
from .desk_market import DeskMarketCollector

MAX_DEEP_LEGS = 24
MAX_DESK_CACHE = 32


class DeskRequestError(ValueError):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def _current(value: dict[str, Any]) -> bool:
    try:
        expiry = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
        return datetime.now(UTC) < expiry
    except (ValueError, KeyError, TypeError):
        return False


def _object(value: Any, *, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise DeskRequestError(HTTPStatus.BAD_REQUEST, "invalid research request fields")
    return value


class DeskService:
    """One collection per canonical input set; no user records or disk writes."""

    def __init__(self, *, allow_live: bool, collector: DeskMarketCollector | None = None) -> None:
        self.allow_live = allow_live
        self.collector = collector or DeskMarketCollector()
        self._lock = threading.RLock()
        self._desks: dict[str, dict[str, Any]] = {}
        self._requests: dict[str, str] = {}

    def dispatch(self, path: str, request: Any) -> dict[str, Any]:
        if not self._lock.acquire(timeout=65):
            raise DeskRequestError(HTTPStatus.SERVICE_UNAVAILABLE, "public collection is busy; retry shortly")
        try:
            if path == "/desk/discover":
                return self._discover(request)
            if path == "/desk/compare":
                return self._compare(request)
            if path == "/desk/review":
                return self._review(request)
            raise DeskRequestError(HTTPStatus.NOT_FOUND, "unknown research route")
        finally:
            self._lock.release()

    def _remember(self, desk: dict[str, Any], cache_key: str | None = None) -> dict[str, Any]:
        for identity in tuple(self._desks):
            if not _current(self._desks[identity]):
                self._desks.pop(identity)
        while len(self._desks) >= MAX_DESK_CACHE:
            self._desks.pop(next(iter(self._desks)))
        self._desks[desk["analysis_id"]] = copy.deepcopy(desk)
        self._requests = {key: identity for key, identity in self._requests.items() if identity in self._desks}
        if cache_key:
            self._requests[cache_key] = desk["analysis_id"]
        return copy.deepcopy(desk)

    def _discover(self, request: Any) -> dict[str, Any]:
        request = _object(request, allowed={"asset", "criteria", "mode"}, required={"asset", "criteria", "mode"})
        asset, mode, criteria = request["asset"], request["mode"], request["criteria"]
        if asset not in {"BTC", "ETH"} or mode not in {"demo", "live"}:
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "asset must be BTC/ETH; mode must be demo/live")
        _object(criteria, allowed={"viewpoint", "dte_min", "dte_max", "max_width_pct", "max_spread_ratio"}, required=set())
        criteria = validate_criteria(criteria)
        if mode == "live" and not self.allow_live:
            raise DeskRequestError(HTTPStatus.CONFLICT, "live source is not enabled by this server operator")
        key = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
        cached = self._desks.get(self._requests.get(key, ""))
        # Keep a useful review window. A user refresh never receives a snapshot
        # about to expire merely because its canonical filters are unchanged.
        if cached and _current(cached):
            remaining = datetime.fromisoformat(cached["expires_at"].replace("Z", "+00:00")) - datetime.now(UTC)
            if remaining.total_seconds() > 30:
                return copy.deepcopy(cached)
        snapshot = demo_desk_snapshot(asset) if mode == "demo" else self.collector.fetch_snapshot(asset)
        provisional = enumerate_provisional(snapshot, criteria)
        names: list[str] = []
        complete_count = 0
        for candidate in provisional["candidates"]:
            candidate_names = [leg["instrument_name"] for leg in candidate["legs"]]
            missing = [name for name in candidate_names if name not in names]
            if len(names) + len(missing) <= MAX_DEEP_LEGS:
                names.extend(missing)
                complete_count += 1
        if mode == "live" and names:
            snapshot = self.collector.deepen(snapshot, names)
        snapshot["coverage"]["deep_leg_limit"] = MAX_DEEP_LEGS
        snapshot["coverage"]["selected_complete_candidate_count"] = complete_count
        desk = build_desk(snapshot, criteria, evaluation_clock=utc_timestamp())
        return self._remember(desk, key)

    def _compare(self, request: Any) -> dict[str, Any]:
        request = _object(request, allowed={"snapshot_id", "analysis_id", "candidate_ids", "scenario"}, required={"snapshot_id", "analysis_id", "candidate_ids", "scenario"})
        if not isinstance(request["snapshot_id"], str):
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "snapshot identity must be a string")
        if not isinstance(request["analysis_id"], str):
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "analysis identity must be a string")
        desk = self._desks.get(request["analysis_id"])
        if desk is None or desk["snapshot_id"] != request["snapshot_id"] or not _current(desk):
            raise DeskRequestError(HTTPStatus.CONFLICT, "research snapshot has expired; fetch current quotes again")
        ids = request["candidate_ids"]
        if not isinstance(ids, list) or not 2 <= len(ids) <= 3 or any(not isinstance(item, str) for item in ids):
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "compare two or three compatible candidates")
        selected = [item for item in desk["candidates"] if item["candidate_id"] in ids]
        if any(not _current({"expires_at": item["recheck_at"]}) for item in selected):
            raise DeskRequestError(HTTPStatus.CONFLICT, "exact candidate quotes expired; fetch current quotes again")
        return compare_candidates(desk, ids, request["scenario"], evaluation_clock=utc_timestamp())

    def _review(self, request: Any) -> dict[str, Any]:
        request = _object(request, allowed={"original_desk", "candidate_id"}, required={"original_desk", "candidate_id"})
        original = request["original_desk"]
        if not isinstance(original, dict) or original.get("schema_version") != "decision_desk.v1" or original.get("qualification", {}).get("execution_allowed") is not False:
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "original observed research is invalid")
        asset = original.get("asset")
        if asset not in {"BTC", "ETH"} or original.get("contract_family") != "LINEAR_USDC":
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "original asset or contract family is unsupported")
        candidate = next((row for row in original.get("candidates", []) if isinstance(row, dict) and row.get("candidate_id") == request["candidate_id"]), None)
        if candidate is None:
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "original exact candidate is missing")
        validate_exact_candidate(candidate)
        criteria = validate_criteria(original.get("criteria"))
        result: dict[str, Any] = {
            "schema_version": "desk_review.v1", "reviewed_at": utc_timestamp(),
            "original_snapshot_id": original.get("snapshot_id"), "original_candidate_id": candidate["candidate_id"],
            "reviewed_candidate_id": None, "status": "unavailable", "desk": None, "reasons": [],
        }
        expiry = candidate.get("expiration_timestamp")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "original expiry is invalid")
        if expiry <= datetime.now(UTC).timestamp() * 1000:
            result.update(status="expired", reasons=[{"code": "EXPIRED_EXACT_LEGS", "detail": "原选腿已到期，保留原记录；不会替换成其他合约。"}])
            return result
        mode = original.get("source", {}).get("mode")
        if mode == "live" and not self.allow_live:
            result["reasons"] = [{"code": "LIVE_SOURCE_DISABLED", "detail": "当前服务未启用实时来源，原记录保持不变。"}]
            return result
        raw_names = [leg.get("instrument_name") for leg in candidate.get("legs", []) if isinstance(leg, dict)]
        if not 2 <= len(raw_names) <= 4 or any(not isinstance(name, str) for name in raw_names):
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "original exact legs are invalid")
        names = [name for name in raw_names if isinstance(name, str)]
        if mode == "demo":
            snapshot = demo_desk_snapshot(asset, expiry_dates=[candidate["expiry_date"]])
        elif mode == "live":
            snapshot = self.collector.review_exact(asset, names)
        else:
            raise DeskRequestError(HTTPStatus.BAD_REQUEST, "original source mode is unsupported")
        desk = evaluate_exact(snapshot, candidate, criteria, evaluation_clock=utc_timestamp())
        result.update(reviewed_at=desk["generated_at"], desk=desk)
        assessed = desk["candidates"][0] if desk["candidates"] else None
        result["reviewed_candidate_id"] = assessed["candidate_id"] if assessed else None
        if assessed and assessed["status"] == "comparable":
            result["status"] = "current"
        else:
            result["reasons"] = assessed["reasons"] if assessed else [{"code": "EXACT_LEGS_UNAVAILABLE", "detail": "无法复核原选腿，原记录保持不变。"}]
        self._remember(desk)
        return result
