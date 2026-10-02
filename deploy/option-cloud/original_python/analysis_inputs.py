"""Frozen calculation results shared by analysis and compatibility outputs.

The calculation accepts source observations, never a UI report.  Existing numeric
modules still return JSON objects; JsonDocument validates and detaches those
objects once so they cannot mutate an in-flight analysis.  The three typed
groups keep market observations, account evidence and research results distinct.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict, cast

from ._canonical import canonical_json_text
from .account_risk import build_account_status, load_account_scenario
from .calibration import (
    CALIBRATION_NOT_IMPLEMENTED,
    build_walk_forward_calibration_report,
)
from .ev_scanner import build_ev_candidate_scanner
from .market_data import build_market_data_status, parse_timestamp_ms
from .pnl import build_pnl_evidence_report
from .regime import build_regime_permission_state
from .surface import build_vol_surface_and_candidate_research


class MarketDataStatus(TypedDict, total=False):
    status: str
    validated: bool
    source: str
    reason_code: str
    snapshot_captured_at: str
    quality_gate: dict[str, Any]
    feed_coverage: dict[str, Any]
    trust_evidence: dict[str, Any]


class DataTrustStatus(TypedDict, total=False):
    verdict: str
    source_class: str
    reason_codes: list[str]


class AccountStatus(TypedDict, total=False):
    private_adapter_contract: dict[str, Any]
    status: str
    source: str
    margin_light: str
    trade_gate: str
    reason_code: str


class ResearchStatus(TypedDict, total=False):
    status: str
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class JsonDocument[T: Mapping[str, Any]]:
    """An immutable JSON object with a detached, explicitly typed read view."""

    _json: str

    def __post_init__(self) -> None:
        value = json.loads(self._json)
        if not isinstance(value, dict):
            raise ValueError("analysis section must be a JSON object")
        canonical_json_text(value)  # Reject NaN/Infinity even for direct callers.

    @classmethod
    def freeze(cls, value: Mapping[str, Any]) -> JsonDocument[T]:
        if not isinstance(value, Mapping):
            raise ValueError("analysis section must be an object")
        return cls(canonical_json_text(dict(value)))

    def read(self) -> T:
        # Construction owns the sole JSON-to-type conversion in this module.
        return cast(T, json.loads(self._json))


@dataclass(frozen=True, slots=True)
class MarketInputs:
    data: JsonDocument[MarketDataStatus]
    trust: JsonDocument[DataTrustStatus]
    surface: JsonDocument[ResearchStatus]
    candidates: JsonDocument[dict[str, Any]]
    permission: JsonDocument[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ResearchInputs:
    calibration: JsonDocument[dict[str, Any]]
    backtest: JsonDocument[dict[str, Any]]
    scanner: JsonDocument[dict[str, Any]]
    pnl: JsonDocument[dict[str, Any]]
    walk_forward: JsonDocument[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class AnalysisInputs:
    evaluation_clock: str
    market: MarketInputs
    account: JsonDocument[AccountStatus]
    research: ResearchInputs

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation_clock, str):
            raise ValueError("analysis evaluation clock must be an RFC3339 timestamp")
        clock = datetime.fromisoformat(self.evaluation_clock.replace("Z", "+00:00"))
        if clock.tzinfo is None:
            raise ValueError("analysis evaluation clock must include a timezone")
        for section, name in (
            (self.market.data.read(), "market"),
            (self.account.read(), "account"),
        ):
            if "status" in section and not isinstance(section["status"], str):
                raise ValueError(f"{name} status must be a string")
        trust = self.market.trust.read()
        if trust.get("verdict") not in {
            None,
            "trusted",
            "degraded",
            "untrusted",
            "missing",
        }:
            raise ValueError("market trust verdict is unsupported")
        data: Mapping[str, Any] = self.market.data.read()
        if "validated" in data and not isinstance(data["validated"], bool):
            raise ValueError("market validated flag must be a boolean")
        for key in ("quality_gate", "feed_coverage", "trust_evidence"):
            if key in data and not isinstance(data[key], dict):
                raise ValueError(f"market {key} must be an object")
        scalar_sections: tuple[tuple[Mapping[str, Any], str], ...] = (
            (data, "market"), (self.account.read(), "account")
        )
        for scalar_section, name in scalar_sections:
            for key in ("status", "source", "snapshot_captured_at"):
                if key in scalar_section and scalar_section[key] is not None and not isinstance(scalar_section[key], str):
                    raise ValueError(f"{name} {key} must be a string")
        _validate_string_list(trust, "reason_codes", "market trust")
        candidates = self.market.candidates.read()
        for family in ("call_credit_spreads", "put_credit_spreads", "iron_condors", "naked_short_calls"):
            if family in candidates:
                group = candidates[family]
                if not isinstance(group, dict):
                    raise ValueError(f"candidate family {family} must be an object")
                for bucket in ("eligible", "review", "rejected"):
                    _validate_object_list(group, bucket, family)
        _validate_object_list(self.research.scanner.read(), "ranked_candidates", "scanner")
        _validate_object_list(self.market.surface.read(), "expiries", "surface")

    @classmethod
    def from_legacy_report(cls, report: Mapping[str, Any]) -> AnalysisInputs:
        """Only the compatibility adapter understands research_report field names."""

        def section(key: str) -> dict[str, Any]:
            value = report.get(key, {})
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object")
            return value

        permission = section("permission_state").copy()
        # These two report decorations are projections of the account section,
        # not independent observations that may influence analysis identity.
        permission.pop("account_margin_light", None)
        permission.pop("account_trade_gate", None)
        return cls(
            evaluation_clock=str(report.get("generated_at") or ""),
            market=MarketInputs(
                data=JsonDocument[MarketDataStatus].freeze(section("data_status")),
                trust=JsonDocument[DataTrustStatus].freeze(section("data_trust")),
                surface=JsonDocument[ResearchStatus].freeze(
                    section("vol_surface_status")
                ),
                candidates=JsonDocument.freeze(section("candidate_research")),
                permission=JsonDocument.freeze(permission),
            ),
            account=JsonDocument[AccountStatus].freeze(section("account_status")),
            research=ResearchInputs(
                calibration=JsonDocument.freeze(section("calibration_status")),
                backtest=JsonDocument.freeze(section("backtest_status")),
                scanner=JsonDocument.freeze(section("ev_candidate_scanner")),
                pnl=JsonDocument.freeze(section("pnl_evidence")),
                walk_forward=JsonDocument.freeze(section("walk_forward_calibration")),
            ),
        )

    def identity_payload(self) -> dict[str, Any]:
        """Bind calculated observations, independently of compatibility UI fields."""
        return {
            "schema_version": "analysis_inputs.v1",
            "evaluation_clock": self.evaluation_clock,
            "market": {
                "data": self.market.data.read(),
                "trust": self.market.trust.read(),
                "surface": self.market.surface.read(),
                "candidates": self.market.candidates.read(),
                "permission": self.market.permission.read(),
            },
            "account": self.account.read(),
            "research": {
                "calibration": self.research.calibration.read(),
                "backtest": self.research.backtest.read(),
                "scanner": self.research.scanner.read(),
                "pnl": self.research.pnl.read(),
                "walk_forward": self.research.walk_forward.read(),
            },
        }


@dataclass(frozen=True, slots=True)
class ReportProjectionOptions:
    mode: str = "research_only"
    paper_ledger_path: str | None = None
    manual_approval_runbook_path: str | None = None
    persist_paper_ledger: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"research_only", "paper", "manual_execution"}:
            raise ValueError(f"unsupported mode {self.mode!r}")


def _validate_string_list(section: Mapping[str, Any], key: str, name: str) -> None:
    if key in section and (
        not isinstance(section[key], list) or not all(isinstance(item, str) for item in section[key])
    ):
        raise ValueError(f"{name} {key} must be a list of strings")


def _validate_object_list(section: Mapping[str, Any], key: str, name: str) -> None:
    if key in section and (
        not isinstance(section[key], list) or not all(isinstance(item, dict) for item in section[key])
    ):
        raise ValueError(f"{name} {key} must be a list of objects")


def compute_analysis_inputs(
    *,
    evaluation_clock: str,
    market_snapshot: dict[str, Any] | None = None,
    account_payload: dict[str, Any] | None = None,
    account_scenario: str | None = None,
    backtest_artifact: dict[str, Any] | None = None,
    underlying_history: dict[str, Any] | None = None,
) -> AnalysisInputs:
    """Calculate once from observations without constructing or reading a report."""
    if account_payload is not None and account_scenario is not None:
        raise ValueError("pass account_payload or account_scenario, not both")
    if account_scenario is not None:
        account_payload = load_account_scenario(account_scenario)
    data = (
        build_market_data_status(
            market_snapshot, now_ms=parse_timestamp_ms(evaluation_clock)
        )
        if market_snapshot is not None
        else {
            "status": "missing",
            "validated": False,
            "source": "not_configured",
            "reason_code": "MISSING_VALIDATED_MARKET_DATA",
        }
    )
    account = build_account_status(
        generated_at=evaluation_clock, account_payload=account_payload
    )
    pnl = build_pnl_evidence_report()
    surface, candidates = build_vol_surface_and_candidate_research(
        market_snapshot=market_snapshot,
        generated_at=evaluation_clock,
        data_status=data,
        pnl_evidence=pnl,
    )
    permission = build_regime_permission_state(
        market_snapshot=market_snapshot, data_status=data, vol_surface_status=surface
    )
    walk_forward = build_walk_forward_calibration_report(
        generated_at=evaluation_clock,
        baseline_backtest=(backtest_artifact or {}).get("backtest_report"),
    )
    calibration = _calibration_status_from_walk_forward(walk_forward)
    backtest = _backtest_status_from_artifact(backtest_artifact)
    scanner = build_ev_candidate_scanner(
        generated_at=evaluation_clock,
        data_status=data,
        account_status=account,
        calibration_status=calibration,
        permission_state=permission,
        candidate_research=candidates,
        vol_surface_status=surface,
        underlying_history=underlying_history,
    )
    permission.pop("account_margin_light", None)
    permission.pop("account_trade_gate", None)
    return AnalysisInputs(
        evaluation_clock=evaluation_clock,
        market=MarketInputs(
            data=JsonDocument[MarketDataStatus].freeze(data),
            trust=JsonDocument[DataTrustStatus].freeze(_build_data_trust_summary(data)),
            surface=JsonDocument[ResearchStatus].freeze(surface),
            candidates=JsonDocument.freeze(candidates),
            permission=JsonDocument.freeze(permission),
        ),
        account=JsonDocument[AccountStatus].freeze(account),
        research=ResearchInputs(
            calibration=JsonDocument.freeze(calibration),
            backtest=JsonDocument.freeze(backtest),
            scanner=JsonDocument.freeze(scanner),
            pnl=JsonDocument.freeze(pnl),
            walk_forward=JsonDocument.freeze(walk_forward),
        ),
    )


def _calibration_status_from_walk_forward(
    calibration: dict[str, Any],
) -> dict[str, Any]:
    registry = calibration.get("model_registry") or {}
    model_version = registry.get("model_version")
    promotion_status = registry.get("promotion_status")
    if (
        calibration.get("status") == "not_implemented"
        and registry.get("status") == "unavailable"
    ):
        return {
            "status": "unavailable",
            "calibrated": False,
            "model_version": None,
            "promotion_status": "not_implemented",
            "evidence_class": "unavailable",
            "reason_code": CALIBRATION_NOT_IMPLEMENTED,
        }
    if not model_version or not promotion_status:
        return {
            "status": "missing",
            "calibrated": False,
            "model_version": None,
            "promotion_status": "missing",
            "evidence_class": None,
            "reason_code": "MISSING_CALIBRATION_EVIDENCE",
        }

    promoted = (
        registry.get("promoted_for_sizing") is True and promotion_status == "promoted"
    )
    return {
        "status": "calibrated" if promoted else "research_fixture",
        "calibrated": promoted,
        "model_version": str(model_version),
        "promotion_status": str(promotion_status),
        "evidence_class": calibration.get("evidence_class"),
        "reason_code": None if promoted else "CALIBRATION_PROMOTION_PENDING",
    }


def _backtest_status_from_artifact(
    artifact: dict[str, Any] | None,
) -> dict[str, Any]:
    if not artifact:
        return {
            "status": "not_run",
            "aligned": False,
            "artifact_id": None,
            "reason_code": "BACKTEST_NOT_RUN",
        }
    aligned = artifact.get("aligned") is True
    return {
        "status": "completed",
        "aligned": aligned,
        "artifact_id": artifact.get("report_id"),
        "reason_code": None if aligned else "BACKTEST_ALIGNMENT_FAIL",
    }


def _build_data_trust_summary(data_status: dict[str, Any]) -> dict[str, Any]:
    status = data_status.get("status")
    if status == "missing":
        return {
            "verdict": "untrusted",
            "reason_codes": ["MISSING_VALIDATED_MARKET_DATA"],
            "source_class": "missing",
        }

    source_class = _data_trust_source_class(data_status)
    quality_reasons = list(
        (data_status.get("quality_gate") or {}).get("reason_codes") or []
    )
    if status != "validated":
        return {
            "verdict": "untrusted",
            "reason_codes": _unique_codes(
                quality_reasons
                or [str(data_status.get("reason_code") or "MARKET_DATA_QUALITY_FAIL")]
            ),
            "source_class": source_class,
        }
    if source_class != "live":
        return {
            "verdict": "untrusted",
            "reason_codes": ["DATA_TRUST_PROMOTION_PENDING"],
            "source_class": source_class,
        }

    evidence = data_status.get("trust_evidence") or {}
    evidence_status = str(
        evidence.get("status") or evidence.get("promotion_status") or "collecting"
    ).lower()
    if evidence_status == "reset":
        return {
            "verdict": "untrusted",
            "reason_codes": _unique_codes(
                list(evidence.get("reason_codes") or [])
                or ["DATA_TRUST_EVIDENCE_RESET"]
            ),
            "source_class": "live",
        }
    consecutive_passes = _nonnegative_number(evidence.get("consecutive_passes"))
    supplied_minimum_passes = _positive_number(
        evidence.get(
            "minimum_consecutive_passes",
            evidence.get("required_consecutive_passes"),
        )
    )
    policy_minimum_passes, policy_minimum_observation_seconds = (
        _trust_promotion_thresholds()
    )
    minimum_passes = max(
        policy_minimum_passes,
        supplied_minimum_passes
        if supplied_minimum_passes is not None
        else policy_minimum_passes,
    )
    observation_seconds = _nonnegative_number(
        evidence.get("observation_seconds", evidence.get("observation_sec"))
    )
    supplied_minimum_observation_seconds = _positive_number(
        evidence.get(
            "minimum_observation_seconds", evidence.get("required_observation_sec")
        )
    )
    minimum_observation_seconds = max(
        policy_minimum_observation_seconds,
        supplied_minimum_observation_seconds
        if supplied_minimum_observation_seconds is not None
        else policy_minimum_observation_seconds,
    )
    threshold_evidence_missing = (
        supplied_minimum_passes is None
        or supplied_minimum_observation_seconds is None
        or "TRUST_PROMOTION_MINIMUMS_MISSING"
        in {str(item) for item in evidence.get("reason_codes") or []}
    )
    feed_coverage = data_status.get("feed_coverage") or {}
    response_contract = data_status.get("public_response_contract") or {}
    feeds_complete = bool(feed_coverage) and not feed_coverage.get("missing_feeds")
    response_pass = (
        bool(response_contract) and response_contract.get("overall_status") == "pass"
    )
    promoted = (
        evidence_status in {"promoted", "trusted"}
        and not threshold_evidence_missing
        and consecutive_passes >= minimum_passes
        and observation_seconds >= minimum_observation_seconds
        and feeds_complete
        and evidence.get("feed_graph_complete") is True
        and response_pass
        and not quality_reasons
    )
    if promoted:
        return {
            "verdict": "trusted",
            "reason_codes": [],
            "source_class": "live",
        }

    reasons = list(evidence.get("reason_codes") or [])
    if threshold_evidence_missing:
        reasons.append("DATA_TRUST_THRESHOLD_EVIDENCE_MISSING")
    elif (
        consecutive_passes < minimum_passes
        or observation_seconds < minimum_observation_seconds
    ):
        reasons.append("DATA_TRUST_OBSERVATION_COLLECTING")
    if not feeds_complete:
        reasons.append("PUBLIC_FEED_GRAPH_INCOMPLETE")
    if not response_pass:
        reasons.append("PUBLIC_RESPONSE_CONTRACT_NOT_VERIFIED")
    reasons.extend(quality_reasons)
    if not reasons:
        reasons.append("DATA_TRUST_PROMOTION_PENDING")
    return {
        "verdict": "degraded",
        "reason_codes": _unique_codes(reasons),
        "source_class": "live",
    }


def _nonnegative_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, float(value))


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = _nonnegative_number(value)
    return parsed if parsed > 0 else None


def _trust_promotion_thresholds() -> tuple[float, float]:
    from .analysis_run import PolicyCatalog

    policy = PolicyCatalog()
    return (
        float(policy.trust_minimum_consecutive_passes),
        float(policy.trust_minimum_observation_seconds),
    )


def _data_trust_source_class(data_status: dict[str, Any]) -> str:
    if data_status.get("status") == "missing":
        return "missing"

    source = str(data_status.get("source") or "").lower()
    if "replay" in source:
        return "replay"
    if source.startswith("deribit_live:"):
        return "live"
    return "fixture"


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code and code not in seen:
            unique.append(code)
            seen.add(code)
    return unique
