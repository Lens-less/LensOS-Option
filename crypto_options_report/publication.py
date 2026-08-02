"""Deterministic static publishing for the public research edition."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from ._canonical import canonical_json_text, canonical_sha256
from .analysis_run import CODE_VERSION, build_analysis_record
from .contract import validate_report_contract
from .full_surface import build_release_gates, validate_full_system_surface_report
from .market_data import load_snapshot_fixture, load_underlying_history_fixture
from .storage import read_json_object_from_regular_file
from .vrp import build_vrp_status, load_dvol_history_fixture

PUBLICATION_MANIFEST_SCHEMA = "public_publication_manifest.v1"
PUBLICATION_SUMMARY_SCHEMA = "public_summary.v1"
PUBLICATION_CANDIDATES_SCHEMA = "public_candidates.v1"
PUBLICATION_SIGNAL_SCHEMA = "public_signal.v1"
PUBLICATION_HEALTH_SCHEMA = "public_health.v1"
PUBLICATION_STATUS_SCHEMA = "public_status.v1"
PUBLISH_CADENCE = "daily"
PUBLISH_INTERVAL = timedelta(days=1)
MIN_VALIDATED_VRP_SAMPLE_COUNT = 1000
PUBLIC_SITE_TITLE = "\u0042\u0054\u0043\u0020\u671f\u6743\u5356\u65b9\u6ea2\u4ef7\u6301\u7eed\u89c2\u5bdf\u53f0"
PUBLIC_SITE_DESCRIPTION = (
    "\u0042\u0054\u0043\u0020\u671f\u6743\u5356\u65b9\u6ea2\u4ef7\u6301\u7eed\u89c2\u5bdf\u53f0\uff1a"
    "\u6bcf\u65e5\u56fa\u5b9a\u53d1\u5e03\u7684\u516c\u5f00\u7814\u7a76\u7248\uff0c"
    "\u805a\u7126\u0044\u0056\u004f\u004c\u3001\u5df2\u5b9e\u73b0\u6ce2\u52a8\u7387\u4e0e"
    "\u4ed3\u4f4d\u65e0\u5173\u7684\u5019\u9009\u7814\u7a76\u8bc1\u636e\u3002"
)
_MANIFEST_PATHS = {
    ".well-known/publish-manifest.json",
    "api/v1/manifest.json",
}
_FORBIDDEN_PUBLICATION_KEYS = {
    "api_key",
    "access_token",
    "account_status",
    "automatic_live_submission_possible",
    "contracts",
    "live_order_adapter",
    "margin_light",
    "margin_snapshot",
    "max_depth_fraction",
    "max_net_delta_nav",
    "max_new_margin_nav",
    "max_single_naked_stress_loss_nav",
    "max_single_spread_loss_nav",
    "nav_relative_metrics_available",
    "order",
    "order_instructions",
    "order_template",
    "orders",
    "paper_manual_trade_candidates",
    "paper_proposal_ledger",
    "portfolio_risk",
    "position_management",
    "positions",
    "projected_margin",
    "quantity",
    "refresh_token",
    "recommended_size",
    "secret",
    "simulation_status",
    "size_contracts",
    "source_endpoint",
    "trade_gate",
    "trade_instruction",
    "trade_instructions",
}
_ABSOLUTE_LOCAL_PATH_RE = re.compile(
    r"(?:file://|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[^\\]"
    r"|/(?:Users|home|root|tmp|var(?:/tmp)?|Volumes|private/(?:tmp|var)"
    r"|workspace|workspaces|github/workspace|mnt|opt)(?:[\\/]|$)"
    r"|(?:^|\s)~[\\/])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PublicationResult:
    out: str
    manifest_sha256: str
    analysis_run_id: str
    captured_at: str
    published_at: str
    research_publication_status: str
    execution_authorization_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "out": self.out,
            "manifest_sha256": self.manifest_sha256,
            "analysis_run_id": self.analysis_run_id,
            "captured_at": self.captured_at,
            "published_at": self.published_at,
            "research_publication_status": self.research_publication_status,
            "execution_authorization_status": self.execution_authorization_status,
        }


def publish_site(
    *,
    snapshot: str,
    underlying_history: str,
    dvol_history: str,
    signal_artifact: str,
    series_artifact: str,
    out: str,
    published_at: str,
    git_sha: str | None = None,
    web_build: str | None = None,
) -> dict[str, Any]:
    """Build one deterministic static publication tree."""
    snapshot_path = _require_file(snapshot, label="snapshot input")
    underlying_path = _require_file(underlying_history, label="underlying history input")
    dvol_path = _require_file(dvol_history, label="DVOL history input")
    signal_path = _require_file(signal_artifact, label="signal artifact input")
    series_path = _require_file(series_artifact, label="series artifact input")
    out_path = _prepare_output_directory(out)
    build_root = _resolve_web_build(web_build)

    snapshot_payload = load_snapshot_fixture(snapshot_path)
    underlying_payload = load_underlying_history_fixture(underlying_path)
    dvol_payload = load_dvol_history_fixture(dvol_path)
    signal_payload = read_json_object_from_regular_file(
        signal_path,
        max_bytes=64 * 1024 * 1024,
        description="signal artifact",
    )
    series_payload = read_json_object_from_regular_file(
        series_path,
        max_bytes=64 * 1024 * 1024,
        description="series artifact",
    )
    _validate_publication_payload(signal_payload, description="signal artifact")
    _validate_publication_payload(series_payload, description="series artifact")

    captured_at = str(snapshot_payload.get("captured_at") or "")
    captured_dt = _parse_timestamp(captured_at, field="snapshot.captured_at")
    underlying_payload = _trim_history_to_capture_date(
        underlying_payload,
        captured_dt=captured_dt,
        label="underlying history",
    )
    dvol_payload = _trim_history_to_capture_date(
        dvol_payload,
        captured_dt=captured_dt,
        label="DVOL history",
    )
    published_dt = _parse_timestamp(published_at, field="published_at")
    if published_dt < captured_dt:
        raise ValueError("published_at must not be earlier than snapshot.captured_at")
    next_expected_dt = captured_dt + PUBLISH_INTERVAL
    stale_after_dt = captured_dt + (PUBLISH_INTERVAL * 2)
    is_stale_at_publish = published_dt >= stale_after_dt

    record = build_analysis_record(
        mode="research_only",
        generated_at=_timestamp(captured_dt),
        market_snapshot=snapshot_payload,
        underlying_history=underlying_payload,
    )
    report = record.project_research_report_v1()
    report_errors = validate_report_contract(report)
    if report_errors:
        raise ValueError("; ".join(report_errors))
    data_status = str((report.get("data_status") or {}).get("status") or "missing")
    if data_status not in {"trusted", "validated"}:
        raise ValueError(f"publication blocked: market data status is {data_status}")

    raw_vrp = build_vrp_status(dvol_payload, underlying_payload, _timestamp(captured_dt))
    vrp_sample_count = int(raw_vrp.get("series_sample_count") or 0)
    if raw_vrp.get("status") != "validated" or vrp_sample_count < MIN_VALIDATED_VRP_SAMPLE_COUNT:
        raise ValueError(
            "publication blocked: VRP status is "
            f"{raw_vrp.get('status') or 'unavailable'}"
        )
    vrp_status = _project_vrp_status(raw_vrp)

    publication_evidence = {
        "data_quality": data_status,
        "publish_manifest": "verified",
        "methodology": "present",
        "disclaimer": "present",
    }
    release_gates = build_release_gates(
        research_publication_ready=True,
        publication_evidence=publication_evidence,
    )
    report["runtime_context"] = {
        "profile": "published",
        "mode": "published",
        "replay": False,
        "evaluation_clock": _timestamp(captured_dt),
        "snapshot_fixture": None,
        "live_fetch_allowed": False,
        "notice": (
            "Published edition evaluated at the capture time; wall-clock age "
            "and publication-stall state are declared separately."
        ),
    }
    report["publish_edition"] = {
        "captured_at": _timestamp(captured_dt),
        "published_at": _timestamp(published_dt),
        "next_expected_at": _timestamp(next_expected_dt),
        "cadence": PUBLISH_CADENCE,
        "stale_after": _timestamp(stale_after_dt),
    }
    report["vrp_status"] = vrp_status
    full_surface = dict(report.get("full_system_surface") or {})
    full_surface["release_gates"] = release_gates
    report["full_system_surface"] = full_surface
    surface_errors = validate_full_system_surface_report(full_surface)
    if surface_errors:
        raise ValueError("; ".join(surface_errors))

    public_report = _build_public_report(report)
    summary = _build_summary(report=public_report, vrp_status=vrp_status)
    thermo = _build_thermo(vrp_status=vrp_status, report=public_report)
    candidates = _build_candidates(report=public_report)
    signal = _build_signal(signal_payload=signal_payload, report=public_report)
    health = _build_health(
        report=public_report,
        is_stale_at_publish=is_stale_at_publish,
    )
    status_payload = _build_status(report=public_report, health=health)

    publication_inputs = {
        "snapshot": canonical_sha256(snapshot_payload),
        "underlying_history": canonical_sha256(underlying_payload),
        "dvol_history": canonical_sha256(dvol_payload),
        "signal_artifact": canonical_sha256(signal_payload),
        "series_artifact": canonical_sha256(series_payload),
        "published_at": _timestamp(published_dt),
        "git_sha": git_sha,
        "engine_version": CODE_VERSION,
    }

    _copy_web_bundle(build_root, out_path)
    _write_json(out_path / "research" / "report", public_report)
    _write_json(out_path / "research" / "signal", signal_payload)
    _write_json(out_path / "research" / "series", series_payload)
    _write_json(out_path / "api" / "v1" / "summary.json", summary)
    _write_json(out_path / "api" / "v1" / "thermo.json", thermo)
    _write_json(out_path / "api" / "v1" / "candidates.json", candidates)
    _write_json(out_path / "api" / "v1" / "signal.json", signal)
    _write_json(out_path / "api" / "v1" / "health.json", health)
    _write_text(out_path / "_headers", _headers_text())
    _write_html(out_path / "methodology.html", _methodology_html(report))
    _write_html(out_path / "disclaimer.html", _disclaimer_html(report))
    _write_html(out_path / "privacy.html", _privacy_html(report))
    _write_html(out_path / "terms.html", _terms_html(report))
    _write_html(out_path / "status.html", _status_html(status_payload))

    _ensure_publication_privacy(out_path)
    manifest = _build_manifest(
        out_path=out_path,
        record=record,
        report=public_report,
        publication_inputs=publication_inputs,
        build_root=build_root,
    )
    manifest_text = canonical_json_text(manifest)
    manifest_sha = sha256(manifest_text.encode("utf-8")).hexdigest()
    _write_json(out_path / ".well-known" / "publish-manifest.json", manifest)
    _write_json(out_path / "api" / "v1" / "manifest.json", manifest)

    research_gate = next(
        gate for gate in release_gates if gate["name"] == "research_publication"
    )
    execution_gate = next(
        gate for gate in release_gates if gate["name"] == "execution_authorization"
    )
    return PublicationResult(
        out=str(out_path),
        manifest_sha256=manifest_sha,
        analysis_run_id=record.analysis_run_id,
        captured_at=_timestamp(captured_dt),
        published_at=_timestamp(published_dt),
        research_publication_status=str(research_gate["status"]),
        execution_authorization_status=str(execution_gate["status"]),
    ).to_dict()


def _build_public_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": report.get("schema_version"),
        "generated_at": report.get("generated_at"),
        "action": report.get("action"),
        "mode": report.get("mode"),
        "effective_mode": report.get("effective_mode"),
        "risk_state": report.get("risk_state"),
        "reason_codes": list(report.get("reason_codes") or []),
        "runtime_context": _project_runtime_context(report.get("runtime_context")),
        "publish_edition": _project_publish_edition(report.get("publish_edition")),
        "vrp_status": _project_public_vrp_status(report.get("vrp_status")),
        "blocked_outputs": list(report.get("blocked_outputs") or []),
        "data_trust": _project_data_trust(report.get("data_trust")),
        "data_status": _project_data_status(report.get("data_status")),
        "calibration_status": _project_status_pair(report.get("calibration_status")),
        "backtest_status": _project_status_pair(report.get("backtest_status")),
        "vol_surface_status": _project_vol_surface_status(report.get("vol_surface_status")),
        "candidate_research": _project_candidate_research(report.get("candidate_research")),
        "strategy_research": _project_strategy_research(
            report.get("strategy_research"),
            published=bool((report.get("runtime_context") or {}).get("mode") == "published"),
        ),
        "ev_candidate_scanner": _project_ev_candidate_scanner(
            report.get("ev_candidate_scanner")
        ),
        "mode_gate": _project_mode_gate(report.get("mode_gate")),
        "full_system_surface": _project_full_system_surface(
            report.get("full_system_surface")
        ),
    }


def _project_runtime_context(value: Any) -> dict[str, Any]:
    context = dict(value or {})
    return {
        "profile": context.get("profile"),
        "mode": context.get("mode"),
        "replay": context.get("replay"),
        "evaluation_clock": context.get("evaluation_clock"),
        "snapshot_fixture": context.get("snapshot_fixture"),
        "live_fetch_allowed": context.get("live_fetch_allowed"),
        "notice": context.get("notice"),
    }


def _project_publish_edition(value: Any) -> dict[str, Any]:
    edition = dict(value or {})
    return {
        "captured_at": edition.get("captured_at"),
        "published_at": edition.get("published_at"),
        "next_expected_at": edition.get("next_expected_at"),
        "cadence": edition.get("cadence"),
        "stale_after": edition.get("stale_after"),
    }


def _project_public_vrp_status(value: Any) -> dict[str, Any]:
    status = dict(value or {})
    projected = {
        "schema_version": status.get("schema_version"),
        "status": status.get("status"),
        "current_vrp_percent_points": status.get("current_vrp_percent_points"),
        "current_dvol_percent": status.get("current_dvol_percent"),
        "current_rv30_percent": status.get("current_rv30_percent"),
        "percentile": status.get("percentile"),
        "band": status.get("band"),
        "evidence_class": status.get("evidence_class"),
        "reason_code": status.get("reason_code"),
        "series": [],
        "missing_dates": list(status.get("missing_dates") or []),
        "sample_count": status.get("sample_count"),
        "minimum_series_sample_count": status.get("minimum_series_sample_count"),
        "window_days": status.get("window_days"),
    }
    for point in status.get("series") or []:
        item = dict(point or {})
        projected["series"].append(
            {
                "observed_at": item.get("observed_at"),
                "vrp_percent_points": item.get("vrp_percent_points"),
                "dvol_percent": item.get("dvol_percent"),
                "rv30_percent": item.get("rv30_percent"),
                "percentile": item.get("percentile"),
                "band": item.get("band"),
                "evidence_class": item.get("evidence_class"),
            }
        )
    return projected


def _project_data_trust(value: Any) -> dict[str, Any]:
    trust = dict(value or {})
    return {
        "verdict": trust.get("verdict"),
        # The public tree is a captured, immutable edition even when the
        # upstream analysis was produced from a validated live collection.
        "source_class": "published_snapshot",
        "reason_codes": list(trust.get("reason_codes") or []),
    }


def _project_data_status(value: Any) -> dict[str, Any]:
    status = dict(value or {})
    collection_scope = dict(status.get("collection_scope") or {})
    quality_gate = dict(status.get("quality_gate") or {})
    thresholds = dict(quality_gate.get("thresholds") or {})
    summary = dict(quality_gate.get("summary") or {})
    return {
        "status": status.get("status"),
        "source": "deribit_published_snapshot",
        "validated": status.get("validated"),
        "reason_code": status.get("reason_code"),
        "market_data_age_sec": status.get("market_data_age_sec"),
        "collection_scope": {
            "selected_instrument_count": collection_scope.get(
                "selected_instrument_count"
            ),
            "upstream_instrument_count": collection_scope.get(
                "upstream_instrument_count"
            ),
            "coverage_ratio": collection_scope.get("coverage_ratio"),
            "scope": collection_scope.get("scope"),
        },
        "quality_gate": {
            "passed": quality_gate.get("passed"),
            "summary": {
                "expiries_evaluated": summary.get("expiries_evaluated"),
                "fetch_errors": summary.get("fetch_errors"),
                "invalid_quotes": summary.get("invalid_quotes"),
                "market_data_age_sec": summary.get("market_data_age_sec"),
                "total_quotes": summary.get("total_quotes"),
                "valid_quotes": summary.get("valid_quotes"),
            },
            "thresholds": {
                "market_data_max_age_sec": thresholds.get("market_data_max_age_sec"),
            },
        },
    }


def _project_status_pair(value: Any) -> dict[str, Any]:
    status = dict(value or {})
    return {
        "status": status.get("status"),
        "model_version": status.get("model_version"),
        "reason_code": status.get("reason_code"),
    }


def _project_vol_surface_status(value: Any) -> dict[str, Any]:
    surface = dict(value or {})
    summary = dict(surface.get("summary") or {})
    expiries = []
    for expiry in surface.get("expiries") or []:
        item = dict(expiry or {})
        points = []
        for point in item.get("surface_points") or []:
            point_item = dict(point or {})
            points.append(
                {
                    "instrument_name": point_item.get("instrument_name"),
                    "strike_price": point_item.get("strike_price"),
                    "market_mark_iv": point_item.get("market_mark_iv"),
                    "surface_fitted_iv": point_item.get("surface_fitted_iv"),
                    "underlying_price": point_item.get("underlying_price"),
                }
            )
        expiries.append(
            {
                "candidate_eligible": item.get("candidate_eligible"),
                "dte_days": item.get("dte_days"),
                "expiry_date": item.get("expiry_date"),
                "fit_quality_pass": item.get("fit_quality_pass"),
                "fit_quality_score": item.get("fit_quality_score"),
                "no_arb_error": item.get("no_arb_error"),
                "no_arb_pass": item.get("no_arb_pass"),
                "quality_passing_quotes": item.get("quality_passing_quotes"),
                "reason_codes": list(item.get("reason_codes") or []),
                "surface_points": points,
            }
        )
    return {
        "status": surface.get("status"),
        "validated": surface.get("validated"),
        "reason_code": surface.get("reason_code"),
        "fit_model": surface.get("fit_model"),
        "summary": {
            "eligible_expiries": summary.get("eligible_expiries"),
            "expiries_evaluated": summary.get("expiries_evaluated"),
            "quality_passing_quotes": summary.get("quality_passing_quotes"),
        },
        "expiries": expiries,
    }


def _project_surface_quality(value: Any) -> dict[str, Any] | None:
    quality = dict(value or {})
    if not quality:
        return None
    return {
        "fit_quality_score": quality.get("fit_quality_score"),
        "no_arb_pass": quality.get("no_arb_pass"),
    }


def _project_call_credit_candidate(value: Any) -> dict[str, Any]:
    candidate = dict(value or {})
    return {
        "candidate_id": candidate.get("candidate_id"),
        "decision": candidate.get("decision"),
        "structure_type": candidate.get("structure_type"),
        "sell_leg_instrument_name": candidate.get("sell_leg_instrument_name"),
        "buy_leg_instrument_name": candidate.get("buy_leg_instrument_name"),
        "sell_leg_strike_price": candidate.get("sell_leg_strike_price"),
        "buy_leg_strike_price": candidate.get("buy_leg_strike_price"),
        "expiry_date": candidate.get("expiry_date"),
        "dte_days": candidate.get("dte_days"),
        "model_delta": candidate.get("model_delta"),
        "net_credit": candidate.get("net_credit"),
        "spread_width": candidate.get("spread_width"),
        "premium_currency": candidate.get("premium_currency"),
        "underlying_price": candidate.get("underlying_price"),
        "surface_quality": _project_surface_quality(candidate.get("surface_quality")),
    }


def _project_naked_candidate(value: Any) -> dict[str, Any]:
    candidate = dict(value or {})
    return {
        "candidate_id": candidate.get("candidate_id"),
        "decision": candidate.get("decision"),
        "structure_type": candidate.get("structure_type"),
        "instrument_name": candidate.get("instrument_name"),
        "expiry_date": candidate.get("expiry_date"),
        "dte_days": candidate.get("dte_days"),
        "model_delta": candidate.get("model_delta"),
        "market_mid": candidate.get("market_mid"),
        "premium_currency": candidate.get("premium_currency"),
        "underlying_price": candidate.get("underlying_price"),
        "surface_quality": _project_surface_quality(candidate.get("surface_quality")),
    }


def _project_candidate_bucket(
    value: Any,
    *,
    row_projector: Any,
) -> dict[str, Any] | None:
    bucket = dict(value or {})
    if not bucket:
        return None
    return {
        "eligible": [row_projector(item) for item in bucket.get("eligible") or []],
        "review": [row_projector(item) for item in bucket.get("review") or []],
        "rejected": [row_projector(item) for item in bucket.get("rejected") or []],
    }


def _project_candidate_research(value: Any) -> dict[str, Any]:
    research = dict(value or {})
    summary = dict(research.get("summary") or {})
    return {
        "status": research.get("status"),
        "reason_code": research.get("reason_code"),
        "summary": {
            "eligible_call_credit_spreads": summary.get("eligible_call_credit_spreads"),
            "eligible_expiries": summary.get("eligible_expiries"),
            "eligible_naked_short_calls": summary.get("eligible_naked_short_calls"),
            "expiries_considered": summary.get("expiries_considered"),
            "rejected_call_credit_spreads": summary.get("rejected_call_credit_spreads"),
            "rejected_naked_short_calls": summary.get("rejected_naked_short_calls"),
            "review_call_credit_spreads": summary.get("review_call_credit_spreads"),
            "review_naked_short_calls": summary.get("review_naked_short_calls"),
        },
        "naked_short_calls": _project_candidate_bucket(
            research.get("naked_short_calls"),
            row_projector=_project_naked_candidate,
        ),
        "call_credit_spreads": _project_candidate_bucket(
            research.get("call_credit_spreads"),
            row_projector=_project_call_credit_candidate,
        ),
    }


def _project_strategy_condition(value: Any) -> dict[str, Any]:
    condition = dict(value or {})
    return {
        "id": condition.get("id"),
        "label": condition.get("label"),
        "observed": condition.get("observed"),
        "requirement": condition.get("requirement"),
        "status": condition.get("status"),
        "blocking": condition.get("blocking"),
        "reason": condition.get("reason"),
    }


def _project_strategy_research(
    value: Any,
    *,
    published: bool = False,
) -> dict[str, Any] | None:
    strategy = dict(value or {})
    if not strategy:
        return None
    decision = dict(strategy.get("decision") or {})
    collection = dict(strategy.get("collection") or {})
    coverage = dict(collection.get("coverage") or {})
    quality = dict(collection.get("quality") or {})
    feed_graph = dict(collection.get("feed_graph") or {})
    analysis = dict(strategy.get("analysis") or {})
    market = dict(analysis.get("market") or {})
    volatility = dict(analysis.get("volatility") or {})
    front_expiry = dict(volatility.get("front_expiry") or {})
    next_expiry = dict(volatility.get("next_expiry") or {})
    selection = dict(strategy.get("strategy_selection") or {})
    review = dict(strategy.get("review") or {})
    monitoring = list(strategy.get("monitoring") or [])
    if published:
        monitoring = [
            item
            for item in monitoring
            if dict(item or {}).get("metric") != "account_age_sec"
        ]
    promotion_conditions = list(review.get("promotion_conditions") or [])
    if published:
        promotion_conditions = [
            item
            for item in promotion_conditions
            if item
            != "Attach a fresh read-only account snapshot before any sizing study."
        ]
    return {
        "schema_version": strategy.get("schema_version"),
        "generated_at": strategy.get("generated_at"),
        "status": strategy.get("status"),
        "advisory_only": strategy.get("advisory_only"),
        "execution_allowed": strategy.get("execution_allowed"),
        "confidence_ceiling": strategy.get("confidence_ceiling"),
        "pipeline": list(strategy.get("pipeline") or []),
        "decision": {
            "stance": decision.get("stance"),
            "primary_structure": decision.get("primary_structure"),
            "entry_readiness": decision.get("entry_readiness"),
            "summary": decision.get("summary"),
            "why_now": list(decision.get("why_now") or []),
            "why_not": list(decision.get("why_not") or []),
            "rejected_structures": list(decision.get("rejected_structures") or []),
        },
        "collection": {
            "status": collection.get("status"),
            "source": "deribit_published_snapshot",
            "captured_at": collection.get("captured_at"),
            "market_data_age_sec": collection.get("market_data_age_sec"),
            "coverage": {
                "scope": coverage.get("scope"),
                "selected_instrument_count": coverage.get("selected_instrument_count"),
                "upstream_instrument_count": coverage.get("upstream_instrument_count"),
                "coverage_ratio": coverage.get("coverage_ratio"),
                "is_research_sample": coverage.get("is_research_sample"),
            },
            "quality": {
                "valid_quotes": quality.get("valid_quotes"),
                "total_quotes": quality.get("total_quotes"),
                "invalid_quotes": quality.get("invalid_quotes"),
                "fetch_errors": quality.get("fetch_errors"),
                "expiries_evaluated": quality.get("expiries_evaluated"),
            },
            "feed_graph": {
                "complete": feed_graph.get("complete"),
                "missing_required_feeds": list(feed_graph.get("missing_required_feeds") or []),
            },
        },
        "analysis": {
            "market": {
                "spot_usd": market.get("spot_usd"),
                "dvol_percent": market.get("dvol_percent"),
                "near_term_atm_iv_percent": market.get("near_term_atm_iv_percent"),
                "dvol_minus_atm_iv_points": market.get("dvol_minus_atm_iv_points"),
                "funding_rate": market.get("funding_rate"),
                "basis_rate": market.get("basis_rate"),
                "event_score": market.get("event_score"),
                "regime_label": market.get("regime_label"),
                "regime_status": market.get("regime_status"),
                "sell_permission": market.get("sell_permission"),
                "spread_permission": market.get("spread_permission"),
                "naked_permission": market.get("naked_permission"),
            },
            "volatility": {
                "surface_status": volatility.get("surface_status"),
                "fit_model": volatility.get("fit_model"),
                "term_slope_iv_points": volatility.get("term_slope_iv_points"),
                "candidate_expiry_atm_iv_percent": volatility.get(
                    "candidate_expiry_atm_iv_percent"
                ),
                "expected_move_usd": volatility.get("expected_move_usd"),
                "expected_move_percent": volatility.get("expected_move_percent"),
                "call_wing_richness_iv_points": volatility.get(
                    "call_wing_richness_iv_points"
                ),
                "front_expiry": {
                    "expiry_date": front_expiry.get("expiry_date"),
                    "dte_days": front_expiry.get("dte_days"),
                    "atm_fitted_iv_percent": front_expiry.get("atm_fitted_iv_percent"),
                    "fit_quality_score": front_expiry.get("fit_quality_score"),
                    "no_arbitrage_pass": front_expiry.get("no_arbitrage_pass"),
                    "candidate_eligible": front_expiry.get("candidate_eligible"),
                },
                "next_expiry": {
                    "expiry_date": next_expiry.get("expiry_date"),
                    "dte_days": next_expiry.get("dte_days"),
                    "atm_fitted_iv_percent": next_expiry.get("atm_fitted_iv_percent"),
                    "fit_quality_score": next_expiry.get("fit_quality_score"),
                    "no_arbitrage_pass": next_expiry.get("no_arbitrage_pass"),
                    "candidate_eligible": next_expiry.get("candidate_eligible"),
                },
            },
            "interpretation_limits": list(analysis.get("interpretation_limits") or []),
        },
        "strategy_selection": {
            "selection_method": selection.get("selection_method"),
            "eligible_spread_count": selection.get("eligible_spread_count"),
            "ranked_candidate_ids": list(selection.get("ranked_candidate_ids") or []),
            "ranking_dimensions": list(selection.get("ranking_dimensions") or []),
        },
        "playbook": _project_playbook(strategy.get("playbook"), published=published),
        "monitoring": monitoring,
        "review": {
            "status": review.get("status"),
            "backtest_status": review.get("backtest_status"),
            "calibration_status": review.get("calibration_status"),
            "path_risk_status": review.get("path_risk_status"),
            "missing_evidence": list(review.get("missing_evidence") or []),
            "promotion_conditions": promotion_conditions,
            "journal_template": list(review.get("journal_template") or []),
        },
        "degradation": list(strategy.get("degradation") or []),
    }


def _project_playbook(value: Any, *, published: bool = False) -> dict[str, Any] | None:
    if value is None:
        return None
    playbook = dict(value or {})
    candidate = dict(playbook.get("candidate") or {})
    economics = dict(playbook.get("economics") or {})
    entry = dict(playbook.get("entry_contract") or {})
    exit_contract = dict(playbook.get("exit_contract") or {})
    time_management = dict(exit_contract.get("time_management") or {})
    conditions = [
        _project_strategy_condition(item) for item in entry.get("conditions") or []
    ]
    if published:
        conditions = [
            item
            for item in conditions
            if item.get("id") != "account_gate"
        ]
    return {
        "structure": playbook.get("structure"),
        "candidate": {
            "candidate_id": candidate.get("candidate_id"),
            "expiry_date": candidate.get("expiry_date"),
            "dte_days": candidate.get("dte_days"),
            "sell_leg": candidate.get("sell_leg"),
            "buy_leg": candidate.get("buy_leg"),
            "sell_strike_usd": candidate.get("sell_strike_usd"),
            "buy_strike_usd": candidate.get("buy_strike_usd"),
            "model_delta": candidate.get("model_delta"),
            "risk_neutral_p_itm": candidate.get("risk_neutral_p_itm"),
            "surface_fit_quality": candidate.get("surface_fit_quality"),
        },
        "economics": {
            "premium_currency": economics.get("premium_currency"),
            "credit_coin": economics.get("credit_coin"),
            "credit_usd_shadow": economics.get("credit_usd_shadow"),
            "spread_width_usd": economics.get("spread_width_usd"),
            "reference_max_loss_usd_shadow": economics.get(
                "reference_max_loss_usd_shadow"
            ),
            "estimated_total_fees_usd_shadow": economics.get(
                "estimated_total_fees_usd_shadow"
            ),
            "breakeven_usd_shadow": economics.get("breakeven_usd_shadow"),
            "sell_strike_distance_usd": economics.get("sell_strike_distance_usd"),
            "sell_strike_distance_percent": economics.get(
                "sell_strike_distance_percent"
            ),
            "sell_strike_expected_move_multiple": economics.get(
                "sell_strike_expected_move_multiple"
            ),
            "credit_to_max_loss_ratio": economics.get("credit_to_max_loss_ratio"),
            "assumption": economics.get("assumption"),
        },
        "entry_contract": {
            "status": entry.get("status"),
            "revalidate_on_refresh": entry.get("revalidate_on_refresh"),
            "price_basis": entry.get("price_basis"),
            "execution_assumption": entry.get("execution_assumption"),
            "conditions": conditions,
        },
        "exit_contract": {
            "policy_status": exit_contract.get("policy_status"),
            "profit_capture": [] if published else list(exit_contract.get("profit_capture") or []),
            "position_states": [] if published else list(exit_contract.get("position_states") or []),
            "time_management": {
                "review_below_dte_days": None
                if published
                else time_management.get("review_below_dte_days"),
                "roll_allowed_states": []
                if published
                else list(time_management.get("roll_allowed_states") or []),
                "roll_delta_band": []
                if published
                else list(time_management.get("roll_delta_band") or []),
                "roll_must_improve": []
                if published
                else list(time_management.get("roll_must_improve") or []),
                "defensive_roll_minimum_stress_reduction": None
                if published
                else time_management.get("defensive_roll_minimum_stress_reduction"),
                "loss_deferral_alone_is_forbidden": None
                if published
                else time_management.get("loss_deferral_alone_is_forbidden"),
            },
            "kill_switches": [] if published else list(exit_contract.get("kill_switches") or []),
        },
    }


def _project_ev_candidate_scanner(value: Any) -> dict[str, Any] | None:
    scanner = dict(value or {})
    if not scanner:
        return None
    ranking_basis = dict(scanner.get("ranking_basis") or {})
    rows = []
    rejected_count = 0
    for row in scanner.get("ranked_candidates") or []:
        item = dict(row or {})
        action = item.get("action")
        if action == "REJECT":
            rejected_count += 1
            continue
        path_risk = dict(item.get("path_risk") or {})
        rows.append(
            {
                "candidate_id": item.get("candidate_id"),
                "structure_type": item.get("structure_type"),
                "action": action,
                "ranking_score": item.get("ranking_score"),
                "ev_after_cost_usdc": item.get("ev_after_cost_usdc"),
                "executable_credit_usdc": item.get("executable_credit_usdc"),
                "path_risk": {
                    "status": path_risk.get("status"),
                    "reason_code": path_risk.get("reason_code"),
                    "p_touch": path_risk.get("p_touch"),
                    "p_itm": path_risk.get("p_itm"),
                    "cvar_95_usdc": path_risk.get("cvar_95_usdc"),
                    "authoritative_sample_size": path_risk.get(
                        "authoritative_sample_size"
                    ),
                    "sample_size_basis": path_risk.get("sample_size_basis"),
                }
                if path_risk
                else None,
                "kill_conditions": list(item.get("kill_conditions") or []),
                "dominated_by": item.get("dominated_by"),
                "losing_axes": list(item.get("losing_axes") or []),
            }
        )
    return {
        "status": scanner.get("status"),
        "score_status": scanner.get("score_status"),
        "reason_code": scanner.get("reason_code"),
        "summary": scanner.get("summary"),
        "ranking_basis": {
            "method": ranking_basis.get("method"),
            "tie_break_order": list(ranking_basis.get("tie_break_order") or []),
            "absolute_ev_available": ranking_basis.get("absolute_ev_available"),
        },
        "ranked_candidates": rows,
        "rejected_count": rejected_count,
    }


def _project_mode_gate(value: Any) -> dict[str, Any]:
    gate = dict(value or {})
    return {
        "trade_recommendation_allowed": gate.get("trade_recommendation_allowed"),
        "recommended_size_allowed": gate.get("recommended_size_allowed"),
        "order_instructions_allowed": gate.get("order_instructions_allowed"),
        "paper_manual_candidates_allowed": gate.get("paper_manual_candidates_allowed"),
        "reason_codes": list(gate.get("reason_codes") or []),
    }


def _project_full_system_surface(value: Any) -> dict[str, Any]:
    surface = dict(value or {})
    readiness = dict(surface.get("release_readiness") or {})
    return {
        "schema_version": surface.get("schema_version"),
        "generated_at": surface.get("generated_at"),
        "status": surface.get("status"),
        "release_readiness": {
            "status": readiness.get("status"),
            "prerequisites": list(readiness.get("prerequisites") or []),
            "missing_prerequisites": list(readiness.get("missing_prerequisites") or []),
            "blocking_prerequisites": list(readiness.get("blocking_prerequisites") or []),
        },
        "release_gates": list(surface.get("release_gates") or []),
    }


def _build_summary(*, report: dict[str, Any], vrp_status: dict[str, Any]) -> dict[str, Any]:
    vrp_evidence_class = vrp_status.get("evidence_class")
    current = {
        "vrp_percent_points": vrp_status.get("current_vrp_percent_points"),
        "dvol_percent": vrp_status.get("current_dvol_percent"),
        "rv30_percent": vrp_status.get("current_rv30_percent"),
        "percentile": vrp_status.get("percentile"),
        "band": vrp_status.get("band"),
        "evidence_class": vrp_evidence_class,
        "field_evidence": {
            "vrp_percent_points": {
                "evidence_class": vrp_evidence_class,
                "unit": "percent_points",
            },
            "dvol_percent": {
                "evidence_class": vrp_evidence_class,
                "unit": "percent",
            },
            "rv30_percent": {
                "evidence_class": vrp_evidence_class,
                "unit": "percent",
            },
            "percentile": {
                "evidence_class": vrp_evidence_class,
                "unit": "fraction_0_1",
            },
        },
    }
    return {
        "schema_version": PUBLICATION_SUMMARY_SCHEMA,
        "captured_at": report["publish_edition"]["captured_at"],
        "published_at": report["publish_edition"]["published_at"],
        "disclaimer_url": "/disclaimer.html",
        "methodology_url": "/methodology.html",
        "cadence": report["publish_edition"]["cadence"],
        "stale_after": report["publish_edition"]["stale_after"],
        "vrp": current,
        "data_status": {
            "status": (report.get("data_status") or {}).get("status"),
            "evidence_class": (report.get("data_trust") or {}).get("verdict"),
        },
        "release_gates": (report.get("full_system_surface") or {}).get("release_gates"),
    }


def _build_thermo(*, vrp_status: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": vrp_status.get("schema_version"),
        "captured_at": report["publish_edition"]["captured_at"],
        "published_at": report["publish_edition"]["published_at"],
        "disclaimer_url": "/disclaimer.html",
        "methodology_url": "/methodology.html",
        "status": vrp_status.get("status"),
        "current_vrp_percent_points": vrp_status.get("current_vrp_percent_points"),
        "current_dvol_percent": vrp_status.get("current_dvol_percent"),
        "current_rv30_percent": vrp_status.get("current_rv30_percent"),
        "percentile": vrp_status.get("percentile"),
        "band": vrp_status.get("band"),
        "evidence_class": vrp_status.get("evidence_class"),
        "series": vrp_status.get("series"),
        "missing_dates": vrp_status.get("missing_dates"),
        "sample_count": vrp_status.get("sample_count"),
        "minimum_series_sample_count": vrp_status.get("minimum_series_sample_count"),
        "window_days": vrp_status.get("window_days"),
    }


def _build_candidates(*, report: dict[str, Any]) -> dict[str, Any]:
    scanner = dict(report.get("ev_candidate_scanner") or {})
    return {
        "schema_version": PUBLICATION_CANDIDATES_SCHEMA,
        "captured_at": report["publish_edition"]["captured_at"],
        "published_at": report["publish_edition"]["published_at"],
        "disclaimer_url": "/disclaimer.html",
        "methodology_url": "/methodology.html",
        "status": scanner.get("status"),
        "reason_code": scanner.get("reason_code"),
        "score_status": scanner.get("score_status"),
        "summary": scanner.get("summary"),
        "ranked_candidates": scanner.get("ranked_candidates") or [],
    }


def _build_signal(*, signal_payload: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PUBLICATION_SIGNAL_SCHEMA,
        "captured_at": report["publish_edition"]["captured_at"],
        "published_at": report["publish_edition"]["published_at"],
        "disclaimer_url": "/disclaimer.html",
        "methodology_url": "/methodology.html",
        "artifact": signal_payload,
    }


def _build_health(*, report: dict[str, Any], is_stale_at_publish: bool) -> dict[str, Any]:
    gates = {
        gate["name"]: gate
        for gate in (report.get("full_system_surface") or {}).get("release_gates") or []
        if isinstance(gate, dict) and isinstance(gate.get("name"), str)
    }
    return {
        "schema_version": PUBLICATION_HEALTH_SCHEMA,
        "captured_at": report["publish_edition"]["captured_at"],
        "published_at": report["publish_edition"]["published_at"],
        "last_published_at": report["publish_edition"]["published_at"],
        "next_expected_at": report["publish_edition"]["next_expected_at"],
        "stale_after": report["publish_edition"]["stale_after"],
        "cadence": report["publish_edition"]["cadence"],
        "runtime_mode": report["runtime_context"]["mode"],
        "data_status": (report.get("data_status") or {}).get("status"),
        "is_stale_at_publish": is_stale_at_publish,
        "research_publication_status": (gates.get("research_publication") or {}).get(
            "status"
        ),
        "execution_authorization_status": (
            gates.get("execution_authorization") or {}
        ).get("status"),
        "disclaimer_url": "/disclaimer.html",
        "status_url": "/status.html",
    }


def _build_status(*, report: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PUBLICATION_STATUS_SCHEMA,
        "captured_at": report["publish_edition"]["captured_at"],
        "published_at": report["publish_edition"]["published_at"],
        "next_expected_at": report["publish_edition"]["next_expected_at"],
        "stale_after": report["publish_edition"]["stale_after"],
        "is_stale_at_publish": health["is_stale_at_publish"],
        "research_publication_status": health["research_publication_status"],
        "execution_authorization_status": health["execution_authorization_status"],
        "disclaimer_url": "/disclaimer.html",
        "privacy_url": "/privacy.html",
        "terms_url": "/terms.html",
    }


def _build_manifest(
    *,
    out_path: Path,
    record: Any,
    report: dict[str, Any],
    publication_inputs: dict[str, Any],
    build_root: Path,
) -> dict[str, Any]:
    artifacts = []
    for relative_path in _relative_file_paths(out_path):
        if relative_path in _MANIFEST_PATHS:
            continue
        path = out_path / relative_path
        artifacts.append(
            {
                "path": relative_path,
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "schema_version": PUBLICATION_MANIFEST_SCHEMA,
        "analysis_run_id": record.analysis_run_id,
        "analysis_record_sha256": record.output_hash,
        "captured_at": report["publish_edition"]["captured_at"],
        "published_at": report["publish_edition"]["published_at"],
        "evaluation_clock": report["runtime_context"]["evaluation_clock"],
        "next_expected_at": report["publish_edition"]["next_expected_at"],
        "stale_after": report["publish_edition"]["stale_after"],
        "cadence": report["publish_edition"]["cadence"],
        "engine_version": CODE_VERSION,
        "git_sha": publication_inputs.get("git_sha"),
        "web_build_source": {
            "root_name": build_root.name,
            "index_name": "index.html",
            "assets_dir": "assets",
        },
        "input_hashes": publication_inputs,
        "artifacts": artifacts,
        "manifest_policy": {
            "canonical_json": True,
            "self_hash_excluded_paths": sorted(_MANIFEST_PATHS),
            "hash_algorithm": "sha256",
            "history_alignment": (
                "Underlying and DVOL observations are trimmed to the snapshot "
                "captured_at UTC date before evaluation and hashing."
            ),
        },
    }


def _project_vrp_status(raw_status: dict[str, Any]) -> dict[str, Any]:
    current = dict(raw_status.get("current") or {})
    series = []
    for point in raw_status.get("time_series") or []:
        series.append(
            {
                "observed_at": _date_to_observed_at(point.get("date")),
                "vrp_percent_points": point.get("vrp_percent_points"),
                "dvol_percent": point.get("dvol_percent_points"),
                "rv30_percent": point.get("rv30_percent_points"),
                "percentile": point.get("percentile"),
                "band": _project_vrp_band(point.get("band"), point.get("percentile")),
                "evidence_class": point.get("evidence_class"),
            }
        )
    return {
        "schema_version": raw_status.get("schema_version"),
        "status": "available" if raw_status.get("status") == "validated" else "unavailable",
        "current_vrp_percent_points": current.get("vrp_percent_points"),
        "current_dvol_percent": current.get("dvol_percent_points"),
        "current_rv30_percent": current.get("rv30_percent_points"),
        "percentile": current.get("percentile"),
        "band": _project_vrp_band(current.get("band"), current.get("percentile")),
        "evidence_class": raw_status.get("evidence_class"),
        "reason_code": ((raw_status.get("reason_codes") or [None])[0]),
        "series": series,
        "missing_dates": raw_status.get("missing_days") or [],
        "sample_count": current.get("percentile_sample_count")
        or raw_status.get("series_sample_count"),
        "minimum_series_sample_count": raw_status.get("minimum_series_sample_count"),
        "window_days": raw_status.get("window_days"),
    }


def _copy_web_bundle(build_root: Path, out_path: Path) -> None:
    index_source = build_root / "index.html"
    assets_source = build_root / "assets"
    if not index_source.is_file():
        raise ValueError("web build is missing index.html")
    if not assets_source.is_dir():
        raise ValueError("web build is missing assets/")
    index_html = index_source.read_text(encoding="utf-8")
    rewritten = _rewrite_index_html(
        index_html.replace('"/evidence/assets/', '"/assets/')
        .replace('"./assets/', '"/assets/')
    )
    _write_html(out_path / "index.html", rewritten)
    assets_out = out_path / "assets"
    assets_out.mkdir(parents=True, exist_ok=True)
    for source in sorted(assets_source.iterdir(), key=lambda item: item.name):
        if source.is_file():
            (assets_out / source.name).write_bytes(source.read_bytes())


def _ensure_publication_privacy(out_path: Path) -> None:
    for relative_path in _relative_file_paths(out_path):
        path = out_path / relative_path
        if relative_path == "_headers":
            continue
        if path.suffix in {".js", ".css"}:
            continue
        if relative_path == "index.html" or path.suffix == ".html":
            content = path.read_text(encoding="utf-8")
            for forbidden in (
                '"api_key"',
                '"secret"',
                '"access_token"',
                '"refresh_token"',
            ):
                if forbidden in content:
                    raise ValueError(f"publication blocked: forbidden token {forbidden}")
            if _contains_absolute_local_path(content):
                raise ValueError(
                    f"publication blocked: absolute local path found in {relative_path}"
                )
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        _validate_publication_payload(payload, description=relative_path)


def _validate_publication_payload(value: Any, *, description: str) -> None:
    if _contains_forbidden_publication_key(value):
        raise ValueError(
            f"publication blocked: forbidden private/execution field in {description}"
        )
    if _contains_absolute_local_path(value):
        raise ValueError(
            f"publication blocked: absolute local path found in {description}"
        )


def _contains_forbidden_publication_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _FORBIDDEN_PUBLICATION_KEYS:
                return True
            if _contains_forbidden_publication_key(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_publication_key(item) for item in value)
    return False


def _contains_absolute_local_path(value: Any) -> bool:
    if isinstance(value, str):
        return _ABSOLUTE_LOCAL_PATH_RE.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_absolute_local_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_absolute_local_path(item) for item in value)
    return False


def _prepare_output_directory(out: str) -> Path:
    out_path = Path(out).expanduser().resolve()
    if out_path.exists():
        if not out_path.is_dir():
            raise ValueError("output path must be a directory")
        if any(out_path.iterdir()):
            raise ValueError("output directory must not already contain files")
    else:
        out_path.mkdir(parents=True, exist_ok=False)
    return out_path


def _resolve_web_build(web_build: str | None) -> Path:
    build_root = (
        Path(web_build).expanduser().resolve()
        if web_build
        else (Path(__file__).resolve().parent / "static" / "evidence")
    )
    if not build_root.is_dir():
        raise ValueError("web build directory not found")
    return build_root


def _require_file(path: str, *, label: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"{label} not found")
    return str(resolved)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json_text(payload), encoding="utf-8")


def _write_html(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _relative_file_paths(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
    )


def _parse_timestamp(value: str, *, field: str) -> datetime:
    if not value:
        raise ValueError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _trim_history_to_capture_date(
    payload: dict[str, Any],
    *,
    captured_dt: datetime,
    label: str,
) -> dict[str, Any]:
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise ValueError(f"{label} observations must be a list")
    cutoff_date = captured_dt.date().isoformat()
    trimmed: list[dict[str, Any]] = []
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError(f"{label} observations must contain only objects")
        observed_at = str(item.get("observed_at") or "")
        if len(observed_at) < 10:
            raise ValueError(f"{label} observation missing observed_at")
        observed_date = observed_at[:10]
        if observed_date > cutoff_date:
            continue
        trimmed.append(item)
    if not trimmed:
        raise ValueError(f"{label} has no observations on or before snapshot capture date")
    trimmed_payload = dict(payload)
    trimmed_payload["observations"] = trimmed
    trimmed_payload["observation_count"] = len(trimmed)
    trimmed_payload["first_observed_at"] = trimmed[0].get("observed_at")
    trimmed_payload["last_observed_at"] = trimmed[-1].get("observed_at")
    coverage = dict(trimmed_payload.get("coverage") or {})
    if coverage:
        missing_days = list(coverage.get("missing_days") or [])
        trimmed_coverage = dict(coverage)
        trimmed_coverage["observed_day_count"] = len(trimmed)
        trimmed_coverage["missing_days"] = [
            day for day in missing_days if isinstance(day, str) and day <= cutoff_date
        ]
        expected_day_count = trimmed_coverage.get("expected_day_count")
        if isinstance(expected_day_count, int):
            trimmed_coverage["expected_day_count"] = min(expected_day_count, len(trimmed))
        missing_day_count = trimmed_coverage.get("missing_day_count")
        if isinstance(missing_day_count, int):
            trimmed_coverage["missing_day_count"] = min(
                missing_day_count,
                len(trimmed_coverage["missing_days"]),
            )
        trimmed_payload["coverage"] = trimmed_coverage
    return trimmed_payload


def _date_to_observed_at(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return f"{value}T08:00:00Z"


def _project_vrp_band(raw_band: Any, percentile: Any) -> str | None:
    if not isinstance(percentile, (int, float)):
        return None
    value = float(percentile)
    if value >= 0.90:
        return "P90+"
    if value >= 0.70:
        return "P70+"
    if value <= 0.10:
        return "P10-"
    if value <= 0.30:
        return "P30-"
    if isinstance(raw_band, str) and raw_band:
        return raw_band
    return "P30-P70"


def _html_shell(*, title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="utf-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"    <title>{title}</title>\n"
        "    <style>\n"
        "      :root { color-scheme: light; }\n"
        "      body { font-family: Georgia, 'Times New Roman', serif; margin: 0; background: #f7f3ea; color: #161616; }\n"
        "      main { max-width: 860px; margin: 0 auto; padding: 48px 24px 72px; }\n"
        "      h1, h2 { line-height: 1.15; }\n"
        "      p, li { line-height: 1.65; }\n"
        "      code { background: rgba(22,22,22,0.08); padding: 0.1rem 0.35rem; }\n"
        "      .eyebrow { text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.78rem; color: #645b52; }\n"
        "      .panel { border: 1px solid rgba(22,22,22,0.14); background: rgba(255,255,255,0.72); padding: 18px 20px; margin: 20px 0; }\n"
        "      ul { padding-left: 1.25rem; }\n"
        "      footer { margin-top: 32px; font-size: 0.95rem; color: #514940; }\n"
        "      a { color: #0b5cab; }\n"
        "    </style>\n"
        "  </head>\n"
        "  <body>\n"
        "    <main>\n"
        f"{body}\n"
        "      <footer>\n"
        "        <p>LensOS Option public research edition. All rights reserved.</p>\n"
        "      </footer>\n"
        "    </main>\n"
        "  </body>\n"
        "</html>\n"
    )


def _headers_text() -> str:
    return (
        "/api/v1/*\n"
        "  Access-Control-Allow-Origin: *\n"
        "  Cache-Control: public, max-age=300\n"
        "\n"
        "/research/*\n"
        "  Cache-Control: public, max-age=300\n"
        "\n"
        "/assets/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n"
    )


def _rewrite_index_html(index_html: str) -> str:
    title = PUBLIC_SITE_TITLE
    description = PUBLIC_SITE_DESCRIPTION
    rewritten = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", index_html, count=1, flags=re.S)
    rewritten = re.sub(
        r'(<meta\s+name="description"\s+content=")(.*?)(".*?>)',
        rf"\1{description}\3",
        rewritten,
        count=1,
        flags=re.S,
    )
    meta_block = (
        f'    <meta property="og:title" content="{title}">\n'
        f'    <meta property="og:description" content="{description}">\n'
        '    <meta property="og:type" content="website">\n'
        '    <meta property="og:locale" content="zh_CN">\n'
        '    <meta name="twitter:card" content="summary">\n'
        f'    <meta name="twitter:title" content="{title}">\n'
        f'    <meta name="twitter:description" content="{description}">\n'
    )
    if 'property="og:title"' not in rewritten:
        rewritten = rewritten.replace("  </head>", f"{meta_block}  </head>", 1)
    return rewritten


def _methodology_html(report: dict[str, Any]) -> str:
    publish = report["publish_edition"]
    body = (
        '<p class="eyebrow">Methodology</p>\n'
        "<h1>Public research methodology</h1>\n"
        "<p>This edition publishes a deterministic snapshot of the research state. "
        "It is evaluated at the capture time and then served read-only.</p>\n"
        '<section class="panel">\n'
        "  <h2>VRP definition</h2>\n"
        "  <p><code>VRP(t) = DVOL(t) - RV_30(t)</code>.</p>\n"
        "  <ul>\n"
        "    <li>DVOL is the Deribit BTC DVOL daily close from the public volatility-index endpoint.</li>\n"
        "    <li>RV30 is the sample standard deviation of the past 30 calendar days of close-to-close log returns, annualized with a 365-day factor.</li>\n"
        "    <li>The percentile is the empirical rank of the current VRP inside a 1095-day rolling window.</li>\n"
        "    <li>Thresholds: P90+ extremely expensive, P70+ expensive, P30-P70 neutral, P30- thin, P10- extremely thin.</li>\n"
        "  </ul>\n"
        "</section>\n"
        '<section class="panel">\n'
        "  <h2>Missing days and boundaries</h2>\n"
        "  <p>Missing DVOL or underlying days are not interpolated. They are marked missing and excluded from the percentile sample instead of being coerced to zero.</p>\n"
        "  <p>Publication never enables execution. Order entry, sizing, and account credentials stay outside the public tree.</p>\n"
        "</section>\n"
        '<section class="panel">\n'
        "  <h2>Publication contract</h2>\n"
        f"  <p>Captured at <code>{publish['captured_at']}</code>, published at <code>{publish['published_at']}</code>, next expected at <code>{publish['next_expected_at']}</code>, stale after <code>{publish['stale_after']}</code>.</p>\n"
        "</section>\n"
    )
    return _html_shell(title="LensOS Option Methodology", body=body)


def _disclaimer_html(report: dict[str, Any]) -> str:
    body = (
        '<p class="eyebrow">Disclaimer</p>\n'
        "<h1>Research only</h1>\n"
        "<p>This site is published for research and information only. It is not investment advice, a solicitation, an offer, or a promise of execution.</p>\n"
        "<ul>\n"
        "  <li>No order entry, position sizing, or execution authority is exposed here.</li>\n"
        "  <li>Data comes from third-party public endpoints and may be incomplete, delayed, or wrong.</li>\n"
        "  <li>Crypto options are high risk. Short-volatility positions can lose more than collected premium.</li>\n"
        "  <li>Users remain responsible for every decision they make.</li>\n"
        "</ul>\n"
        f"<p>Current public edition: <code>{report['publish_edition']['published_at']}</code>.</p>\n"
    )
    return _html_shell(title="LensOS Option Disclaimer", body=body)


def _privacy_html(report: dict[str, Any]) -> str:
    body = (
        '<p class="eyebrow">Privacy</p>\n'
        "<h1>Privacy policy</h1>\n"
        "<p>This static publication does not set cookies, does not accept user accounts, and does not embed third-party analytics tags.</p>\n"
        "<p>Operational logs at the hosting layer may still record normal HTTP metadata such as IP address, user agent, and request time according to the host's own policies.</p>\n"
        f"<p>Published edition timestamp: <code>{report['publish_edition']['published_at']}</code>.</p>\n"
    )
    return _html_shell(title="LensOS Option Privacy", body=body)


def _terms_html(report: dict[str, Any]) -> str:
    body = (
        '<p class="eyebrow">Terms</p>\n'
        "<h1>Terms of use</h1>\n"
        "<p>All rights are reserved unless a separate written grant says otherwise. The public API is provided on a best-effort basis with no service-level guarantee.</p>\n"
        "<ul>\n"
        "  <li>Do not present this material as a live trading signal or execution service.</li>\n"
        "  <li>Attribute the source when quoting the public JSON outputs.</li>\n"
        "  <li>Do not imply official affiliation with Deribit.</li>\n"
        "</ul>\n"
        f"<p>Cadence: <code>{report['publish_edition']['cadence']}</code>.</p>\n"
    )
    return _html_shell(title="LensOS Option Terms", body=body)


def _status_html(status: dict[str, Any]) -> str:
    body = (
        '<p class="eyebrow">Status</p>\n'
        "<h1>Publication status</h1>\n"
        '<section class="panel">\n'
        f"  <p>Published at <code>{status['published_at']}</code>.</p>\n"
        f"  <p>Next expected at <code>{status['next_expected_at']}</code>.</p>\n"
        f"  <p>Stale after <code>{status['stale_after']}</code>.</p>\n"
        f"  <p>Research publication gate: <strong>{status['research_publication_status']}</strong>.</p>\n"
        f"  <p>Execution authorization: <strong>{status['execution_authorization_status']}</strong>.</p>\n"
        f"  <p>Stale at publish: <strong>{'yes' if status['is_stale_at_publish'] else 'no'}</strong>.</p>\n"
        "</section>\n"
    )
    return _html_shell(title="LensOS Option Status", body=body)
