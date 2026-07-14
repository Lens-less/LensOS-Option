"""Research-only alert evaluation and delivery (no order paths).

Priority: analysis risk-degradation notifications first.
Trading opportunity alerts are intentionally blocked while path risk is
placeholder and score models remain unpromoted.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .storage import atomic_write_json

ALERT_EVENT_SCHEMA = "alert_event.v1"
ALERT_EVAL_SCHEMA = "alert_evaluation.v1"
ALERT_STATE_SCHEMA = "alert_state.v1"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = build_opener(_RejectRedirects())


def urlopen(request: Request, *, timeout: int):
    """Open one webhook request without following redirects."""
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


# Risk-degradation rules only for default product policy.
DEFAULT_RULE_IDS = (
    "data_quality.blocked",
    "regime.kill",
    "portfolio.severity_upgrade",
    "account.margin_degraded",
    "release_readiness.nogo",
)

SEVERITY_RANK = {
    "info": 0,
    "warning": 1,
    "critical": 2,
}

PORTFOLIO_SEVERITY_RANK = {
    "allow_new": 0,
    "reduce_size": 1,
    "spread_only": 2,
    "no_new_trades": 3,
    "reduce_existing": 4,
    "close_batch": 5,
    "close_all_and_pause": 6,
    "halt_system": 7,
}

FORBIDDEN_ALERT_PAYLOAD_KEYS = {
    "recommended_size",
    "size_contracts",
    "order_instructions",
    "order_template",
    "trade_instruction",
    "trade_instructions",
    "entry_rule",
    "exit_rule",
    "limit_price",
}


def evaluate_alerts(
    report: dict[str, Any],
    *,
    previous_state: dict[str, Any] | None = None,
    cooldown_sec: int = 1800,
    now: str | None = None,
    allow_opportunity_alerts: bool = False,
) -> dict[str, Any]:
    """Evaluate research-only alerts from a shared report.

    Opportunity-style candidate alerts stay disabled unless
    ``allow_opportunity_alerts`` is True **and** evidence gates pass
    (non-placeholder path risk, promoted model). Default is False.
    """
    generated_at = now or report.get("generated_at") or _utc_now()
    previous_state = previous_state or empty_alert_state()
    candidates = _collect_candidate_events(report, allow_opportunity_alerts=allow_opportunity_alerts)
    fired: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    last_fired = dict(previous_state.get("last_fired") or {})
    now_ms = _parse_ms(generated_at)

    for event in candidates:
        fingerprint = event["fingerprint"]
        prior_ms = last_fired.get(fingerprint)
        if prior_ms is not None and now_ms - int(prior_ms) < cooldown_sec * 1000:
            suppressed.append(
                {
                    "fingerprint": fingerprint,
                    "rule_id": event["rule_id"],
                    "reason": "cooldown",
                    "cooldown_sec": cooldown_sec,
                }
            )
            continue
        fired.append(event)
        last_fired[fingerprint] = now_ms

    next_state = {
        "schema_version": ALERT_STATE_SCHEMA,
        "updated_at": generated_at,
        "last_fired": last_fired,
        "last_report_action": report.get("action"),
        "last_risk_state": report.get("risk_state"),
        "last_portfolio_action": (report.get("portfolio_risk") or {}).get("final_action"),
    }
    return {
        "schema_version": ALERT_EVAL_SCHEMA,
        "generated_at": generated_at,
        "research_only": True,
        "trade_actions_allowed": False,
        "opportunity_alerts_allowed": False
        if not allow_opportunity_alerts
        else _opportunity_evidence_ok(report),
        "cooldown_sec": cooldown_sec,
        "events": fired,
        "suppressed": suppressed,
        "summary": {
            "candidate_events": len(candidates),
            "fired": len(fired),
            "suppressed": len(suppressed),
            "highest_severity": _highest_severity(fired),
        },
        "state": next_state,
        "delivery": {
            "automatic_live_submission_possible": False,
            "order_adapter": "not_implemented",
        },
    }


def empty_alert_state() -> dict[str, Any]:
    return {
        "schema_version": ALERT_STATE_SCHEMA,
        "updated_at": None,
        "last_fired": {},
        "last_report_action": None,
        "last_risk_state": None,
        "last_portfolio_action": None,
    }


def load_alert_state(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return empty_alert_state()
    state_path = Path(path)
    if not state_path.exists():
        return empty_alert_state()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return empty_alert_state()
    payload.setdefault("schema_version", ALERT_STATE_SCHEMA)
    payload.setdefault("last_fired", {})
    return payload


def save_alert_state(path: str | Path, state: dict[str, Any]) -> Path:
    return atomic_write_json(path, state)


def deliver_webhook(
    evaluation: dict[str, Any],
    *,
    url: str,
    secret: str | None = None,
    timeout: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """POST alert evaluation JSON to a webhook. Never includes order templates."""
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ValueError("webhook URL must use https")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise ValueError("webhook URL must not include userinfo")
    if timeout <= 0:
        raise ValueError("webhook timeout must be positive")
    payload = {
        "schema_version": "alert_webhook_payload.v1",
        "research_only": True,
        "trade_actions_allowed": False,
        "generated_at": evaluation.get("generated_at"),
        "summary": evaluation.get("summary"),
        "events": evaluation.get("events") or [],
    }
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    if dry_run:
        return {
            "status": "dry_run",
            # Webhook providers commonly encode the credential in the path.
            # Dry-run output exposes only the destination origin.
            "url": f"{parsed_url.scheme}://{parsed_url.netloc}",
            "bytes": len(body),
            "event_count": len(payload["events"]),
        }
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "crypto-options-report-alerts/0.1",
        "X-Research-Only": "1",
    }
    delivery_timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    delivery_id = str(uuid4())
    headers["X-Webhook-Timestamp"] = delivery_timestamp
    headers["X-Webhook-Delivery-Id"] = delivery_id
    if secret:
        signed_message = (
            delivery_timestamp.encode("ascii")
            + b"."
            + delivery_id.encode("ascii")
            + b"."
            + body
        )
        digest = hmac.new(
            secret.encode("utf-8"),
            signed_message,
            hashlib.sha256,
        ).hexdigest()
        headers["X-Signature-SHA256"] = digest
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            return {
                "status": "delivered",
                "http_status": int(status),
                "event_count": len(payload["events"]),
            }
    except HTTPError as exc:
        return {
            "status": "failed",
            "http_status": int(exc.code),
            "error": str(exc.reason),
            "event_count": len(payload["events"]),
        }
    except URLError as exc:
        return {
            "status": "failed",
            "http_status": None,
            "error": str(exc.reason),
            "event_count": len(payload["events"]),
        }


def validate_alert_evaluation(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["alert evaluation must be a dict"]
    if payload.get("schema_version") != ALERT_EVAL_SCHEMA:
        errors.append("alert evaluation schema_version must be alert_evaluation.v1")
    if payload.get("research_only") is not True:
        errors.append("alert evaluation must set research_only true")
    if payload.get("trade_actions_allowed") is not False:
        errors.append("alert evaluation must set trade_actions_allowed false")
    if payload.get("delivery", {}).get("automatic_live_submission_possible") is not False:
        errors.append("alert delivery must keep automatic_live_submission_possible false")
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            errors.append("alert event must be a dict")
            continue
        if event.get("schema_version") != ALERT_EVENT_SCHEMA:
            errors.append("alert event schema_version must be alert_event.v1")
        if event.get("category") == "opportunity" and not event.get("evidence_ok"):
            errors.append("opportunity alert requires evidence_ok true")
        blob = json.dumps(event, sort_keys=True)
        for key in FORBIDDEN_ALERT_PAYLOAD_KEYS:
            if f'"{key}"' in blob:
                errors.append(f"alert event forbids key {key}")
    return errors


def _collect_candidate_events(
    report: dict[str, Any],
    *,
    allow_opportunity_alerts: bool,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    generated_at = report.get("generated_at")
    data_status = report.get("data_status") or {}
    permission = report.get("permission_state") or {}
    portfolio = report.get("portfolio_risk") or {}
    account = report.get("account_status") or {}
    readiness = (report.get("full_system_surface") or {}).get("release_readiness") or {}

    if data_status.get("status") == "blocked":
        events.append(
            _event(
                rule_id="data_quality.blocked",
                severity="warning",
                category="risk_degradation",
                title="Market data quality blocked",
                reason_codes=[data_status.get("reason_code") or "MARKET_DATA_QUALITY_FAIL"],
                context={
                    "data_status": data_status.get("status"),
                    "source": data_status.get("source"),
                },
                generated_at=generated_at,
            )
        )
    elif data_status.get("status") == "missing":
        events.append(
            _event(
                rule_id="data_quality.blocked",
                severity="warning",
                category="risk_degradation",
                title="Market data missing",
                reason_codes=["MISSING_VALIDATED_MARKET_DATA"],
                context={"data_status": "missing"},
                generated_at=generated_at,
            )
        )

    regime_codes = [
        code
        for code in (permission.get("reason_codes") or [])
        if any(token in str(code) for token in ("KILL", "CAP_0", "BLOCK"))
        or str(code) in {"BREAKOUT_KILL", "EVENT_KILL", "DATA_QUALITY_KILL"}
    ]
    if permission.get("sell_permission") == 0.0 or regime_codes:
        events.append(
            _event(
                rule_id="regime.kill",
                severity="critical" if permission.get("sell_permission") == 0.0 else "warning",
                category="risk_degradation",
                title="Regime permission constrained",
                reason_codes=regime_codes or list(permission.get("reason_codes") or [])[:5],
                context={
                    "sell_permission": permission.get("sell_permission"),
                    "limiting_dimension": permission.get("limiting_dimension"),
                    "input_provenance": permission.get("input_provenance"),
                },
                generated_at=generated_at,
            )
        )

    final_action = portfolio.get("final_action")
    previous_action = None
    # Edge trigger uses report-local signal only; state cooldown handles repeats.
    if final_action in {
        "no_new_trades",
        "reduce_existing",
        "close_batch",
        "close_all_and_pause",
        "halt_system",
    }:
        events.append(
            _event(
                rule_id="portfolio.severity_upgrade",
                severity="critical"
                if PORTFOLIO_SEVERITY_RANK.get(str(final_action), 0) >= 6
                else "warning",
                category="risk_degradation",
                title=f"Portfolio severity {final_action}",
                reason_codes=list((portfolio.get("summary") or {}).get("reason_codes") or [])[:8],
                context={
                    "final_action": final_action,
                    "previous_action": previous_action,
                },
                generated_at=generated_at,
            )
        )

    margin_light = account.get("margin_light")
    if margin_light in {"YELLOW", "RED", "HALT"}:
        events.append(
            _event(
                rule_id="account.margin_degraded",
                severity="critical" if margin_light in {"RED", "HALT"} else "warning",
                category="risk_degradation",
                title=f"Account margin light {margin_light}",
                reason_codes=[account.get("reason_code") or "ACCOUNT_MARGIN_DEGRADED"],
                context={
                    "margin_light": margin_light,
                    "trade_gate": account.get("trade_gate"),
                    "status": account.get("status"),
                },
                generated_at=generated_at,
            )
        )

    if readiness.get("status") == "NO-GO":
        events.append(
            _event(
                rule_id="release_readiness.nogo",
                severity="info",
                category="risk_degradation",
                title="Release readiness remains NO-GO",
                reason_codes=list(readiness.get("missing_prerequisites") or [])[:12],
                context={
                    "paper_mode_allowed": readiness.get("paper_mode_allowed"),
                    "manual_execution_allowed": readiness.get("manual_execution_allowed"),
                },
                generated_at=generated_at,
            )
        )

    if allow_opportunity_alerts and _opportunity_evidence_ok(report):
        scanner = report.get("ev_candidate_scanner") or {}
        for candidate in (scanner.get("ranked_candidates") or [])[:3]:
            if candidate.get("action") not in {"RESEARCH_ONLY", "REVIEW"}:
                continue
            kills = set(candidate.get("kill_conditions") or [])
            if "PLACEHOLDER_PATH_RISK" in kills or "UNCALIBRATED_SCORE_MODEL" in kills:
                continue
            events.append(
                _event(
                    rule_id="ev.candidate_watch",
                    severity="info",
                    category="opportunity",
                    title="Research candidate watch",
                    reason_codes=list(kills)[:8],
                    context={
                        "candidate_id": candidate.get("candidate_id"),
                        "action": candidate.get("action"),
                        "ranking_score": candidate.get("ranking_score"),
                    },
                    generated_at=generated_at,
                    evidence_ok=True,
                )
            )

    return events


def _opportunity_evidence_ok(report: dict[str, Any]) -> bool:
    scanner = report.get("ev_candidate_scanner") or {}
    path_evidence = scanner.get("path_risk_evidence") or {}
    calibration = report.get("walk_forward_calibration") or {}
    registry = calibration.get("model_registry") or {}
    if path_evidence.get("placeholder_data") is not False:
        return False
    if path_evidence.get("status") == "research_placeholder":
        return False
    if registry.get("promoted_for_sizing") is not True:
        return False
    if calibration.get("status") == "research_fixture":
        return False
    return True


def _event(
    *,
    rule_id: str,
    severity: str,
    category: str,
    title: str,
    reason_codes: list[Any],
    context: dict[str, Any],
    generated_at: Any,
    evidence_ok: bool = True,
) -> dict[str, Any]:
    codes = [str(code) for code in reason_codes if code is not None]
    fingerprint_src = f"{rule_id}|{severity}|{'/'.join(codes[:5])}|{context.get('final_action') or context.get('margin_light') or context.get('data_status') or ''}"
    fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": ALERT_EVENT_SCHEMA,
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "title": title,
        "reason_codes": codes,
        "context": context,
        "fingerprint": fingerprint,
        "generated_at": generated_at,
        "research_only": True,
        "evidence_ok": evidence_ok,
        "trade_action": None,
    }


def _highest_severity(events: list[dict[str, Any]]) -> str | None:
    if not events:
        return None
    return max(events, key=lambda item: SEVERITY_RANK.get(item.get("severity"), 0)).get(
        "severity"
    )


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_ms(value: str | None) -> int:
    if not value:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
