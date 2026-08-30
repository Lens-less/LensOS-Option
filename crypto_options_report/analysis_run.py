"""Immutable, evidence-first pre-entry analysis seam.

This module deliberately stops at :class:`EntryAdmissionDecision`.  It has no
order, fill, position, exit, settlement, or reconciliation interface.  The
existing ``research_report.v1`` builder is accepted only as a migration
projection and is converted into typed, fail-closed domain records here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from ._canonical import canonical_json_text
from .market_data import snapshot_payload_sha256
from .strategy_brief import build_strategy_brief
from .strategy_forecast import (
    project_strategy_forecast,
    selection_binding_key_from_scope,
    validate_strategy_forecast_runtime_evidence,
)
from .strategy_history import (
    build_strategy_history_artifact,
    project_strategy_history_summary,
    validate_strategy_history_artifact,
)
from .structures import build_structure

ANALYSIS_RECORD_SCHEMA = "analysis_record.v1"
DECISION_MANIFEST_SCHEMA = "decision_manifest.v1"
EVIDENCE_RECORD_SCHEMA = "evidence_record.v1"
DOMAIN_EVENT_SCHEMA = "domain_event.v1"
OPPORTUNITY_SCHEMA = "opportunity_record.v1"
STRATEGY_PLAN_SCHEMA = "strategy_plan.v1"
ENTRY_ADMISSION_SCHEMA = "entry_admission_decision.v1"
POLICY_CATALOG_SCHEMA = "policy_catalog.v1"
POLICY_BUNDLE_SCHEMA = "policy_bundle.v1"
ANALYSIS_MANDATE_SCHEMA = "analysis_mandate.v1"
MODEL_BUNDLE_SCHEMA = "model_bundle_ref.v1"
PRE_ENTRY_RISK_CLAIM_SCHEMA = "pre_entry_risk_claim.v1"
CODE_VERSION = "lensos-option-pre-entry-p0.v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNTRUSTED_SOURCE_TOKENS = ("fixture", "replay", "synthetic", "tracer", "fallback")
_FORBIDDEN_ANALYSIS_KEYS = {
    "recommended_size",
    "suggested_size",
    "contract_count",
    "contract_counts",
    "size_contracts",
    "order",
    "orders",
    "order_instruction",
    "order_instructions",
    "order_template",
    "trade_instruction",
    "trade_instructions",
    "position_management",
    "position_lifecycle",
    "exit_contract",
    "exit_instruction",
    "settlement_reconciliation",
    "reconciliation",
    "post_trade_pnl",
    "paper_trading_allowed",
    "manual_execution_allowed",
    "live_order_adapter",
}


class EvidenceState(str, Enum):
    TRUSTED = "trusted"
    DEGRADED = "degraded"
    UNTRUSTED = "untrusted"
    MISSING = "missing"


class EdgeClass(str, Enum):
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"


class OpportunityStatus(str, Enum):
    DETECTED = "DETECTED"
    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    EVIDENCE_BLOCKED = "EVIDENCE_BLOCKED"
    MODEL_BLOCKED = "MODEL_BLOCKED"
    COST_BLOCKED = "COST_BLOCKED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class EntryAdmissionStatus(str, Enum):
    BLOCKED_BY_EVIDENCE = "BLOCKED_BY_EVIDENCE"
    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    MONITOR_ONLY = "MONITOR_ONLY"
    DEFERRED = "DEFERRED"
    VETOED = "VETOED"
    CONDITIONALLY_ELIGIBLE = "CONDITIONALLY_ELIGIBLE"


class ConditionStatus(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


class PreEntryRiskState(str, Enum):
    CLEAR = "CLEAR"
    VETO = "VETO"
    UNKNOWN = "UNKNOWN"


class ExchangeHealthState(str, Enum):
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    """Canonical JSON text, with analysis-specific error phrasing."""
    try:
        return canonical_json_text(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("analysis inputs must contain finite JSON values") from exc


def _parse_timestamp(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _ensure_hash(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _finite_number(
    value: Any,
    *,
    field: str,
    allow_none: bool = False,
    positive: bool = False,
    nonnegative: bool = False,
) -> float | None:
    if value is None and allow_none:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field} must be finite numeric")
    parsed = float(value)
    if positive and parsed <= 0:
        raise ValueError(f"{field} must be positive")
    if nonnegative and parsed < 0:
        raise ValueError(f"{field} must be nonnegative")
    return parsed


@dataclass(frozen=True, slots=True)
class AnalysisMandate:
    schema_version: str = ANALYSIS_MANDATE_SCHEMA
    effective_mode: str = "research_only"
    instrument_universe: tuple[str, ...] = ("DERIBIT:BTC_OPTIONS",)
    currency: str = "BTC"
    product_types: tuple[str, ...] = ("option",)
    product_styles: tuple[str, ...] = ("inverse", "linear")
    option_types: tuple[str, ...] = ("call", "put")
    expiry_scope: tuple[str, ...] = ("policy_scoped",)
    delta_scope: tuple[float, float] = (-1.0, 1.0)
    moneyness_scope: tuple[float, float] = (0.0, 10.0)
    evidence_class: str = "authenticated_current_or_replay"
    policy_version: str = "pre-entry-policy.v1"
    model_bundle_id: str = "model-bundle:unavailable"
    risk_policy_id: str = "pre-entry-risk.v1"
    evaluation_clock: str | None = None
    output_ceiling: str = "entry_admission_only"

    def __post_init__(self) -> None:
        if self.schema_version != ANALYSIS_MANDATE_SCHEMA:
            raise ValueError(f"schema_version must be {ANALYSIS_MANDATE_SCHEMA}")
        if self.effective_mode != "research_only":
            raise ValueError("AnalysisMandate effective_mode must remain research_only")
        if self.output_ceiling != "entry_admission_only":
            raise ValueError("AnalysisMandate output ceiling must stop at entry admission")
        if self.evaluation_clock is not None:
            _parse_timestamp(self.evaluation_clock, field="evaluation_clock")
        for name, values in (
            ("instrument_universe", self.instrument_universe),
            ("product_types", self.product_types),
            ("product_styles", self.product_styles),
            ("option_types", self.option_types),
            ("expiry_scope", self.expiry_scope),
        ):
            if not values or any(not isinstance(item, str) or not item for item in values):
                raise ValueError(f"{name} must contain non-empty strings")
        for name, scope in (
            ("delta_scope", self.delta_scope),
            ("moneyness_scope", self.moneyness_scope),
        ):
            if len(scope) != 2:
                raise ValueError(f"{name} must contain lower and upper bounds")
            low = _finite_number(scope[0], field=f"{name}.lower")
            high = _finite_number(scope[1], field=f"{name}.upper")
            if low is None or high is None or low > high:
                raise ValueError(f"{name} lower bound must not exceed upper bound")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "effective_mode": self.effective_mode,
            "instrument_universe": list(self.instrument_universe),
            "currency": self.currency,
            "product_types": list(self.product_types),
            "product_styles": list(self.product_styles),
            "option_types": list(self.option_types),
            "expiry_scope": list(self.expiry_scope),
            "delta_scope": list(self.delta_scope),
            "moneyness_scope": list(self.moneyness_scope),
            "evidence_class": self.evidence_class,
            "policy_version": self.policy_version,
            "model_bundle_id": self.model_bundle_id,
            "risk_policy_id": self.risk_policy_id,
            "evaluation_clock": self.evaluation_clock,
            "output_ceiling": self.output_ceiling,
        }


@dataclass(frozen=True, slots=True)
class PolicyCatalog:
    schema_version: str = POLICY_CATALOG_SCHEMA
    policy_version: str = "pre-entry-policy.v1"
    trust_minimum_consecutive_passes: int = 6
    trust_minimum_observation_seconds: int = 60
    market_snapshot_max_age_seconds: float = 60.0
    account_snapshot_max_age_seconds: float = 30.0
    pre_entry_risk_max_age_seconds: float = 30.0
    model_promotion_evidence_max_age_seconds: float = 31_536_000.0
    quote_max_age_seconds: float = 120.0
    leg_sync_window_seconds: float = 2.0
    opportunity_ttl_seconds: int = 600
    cost_coverage_ratio: float = 1.0
    max_spread_ratio: float = 0.25
    minimum_depth: float = 1.0
    minimum_open_interest: float = 10.0
    maximum_event_score: float = 0.75
    model_required_edge_classes: tuple[str, ...] = ("E2", "E3")
    pre_entry_risk_veto_states: tuple[str, ...] = (
        PreEntryRiskState.VETO.value,
    )
    exchange_health_blocking_states: tuple[str, ...] = (
        ExchangeHealthState.BLOCKED.value,
    )
    allowed_detectors: tuple[str, ...] = ("legacy-candidate-screen:v1",)
    settlement_window_utc: tuple[str, str] = ("07:30", "08:00")
    kill_switch: bool = False
    research_output_ceiling: str = "entry_admission_only"

    def __post_init__(self) -> None:
        if self.schema_version != POLICY_CATALOG_SCHEMA:
            raise ValueError(f"schema_version must be {POLICY_CATALOG_SCHEMA}")
        if self.research_output_ceiling != "entry_admission_only":
            raise ValueError("research output ceiling must stop at entry admission")
        for name in (
            "trust_minimum_consecutive_passes",
            "trust_minimum_observation_seconds",
            "opportunity_ttl_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name, options in (
            ("market_snapshot_max_age_seconds", {"positive": True}),
            ("account_snapshot_max_age_seconds", {"positive": True}),
            ("pre_entry_risk_max_age_seconds", {"positive": True}),
            ("model_promotion_evidence_max_age_seconds", {"positive": True}),
            ("quote_max_age_seconds", {"positive": True}),
            ("leg_sync_window_seconds", {"nonnegative": True}),
            ("cost_coverage_ratio", {"positive": True}),
            ("max_spread_ratio", {"positive": True}),
            ("minimum_depth", {"nonnegative": True}),
            ("minimum_open_interest", {"nonnegative": True}),
            ("maximum_event_score", {"nonnegative": True}),
        ):
            _finite_number(getattr(self, name), field=name, **options)
        if self.maximum_event_score > 1.0:
            raise ValueError("maximum_event_score must not exceed 1")
        if len(self.settlement_window_utc) != 2 or any(
            not re.fullmatch(r"\d{2}:\d{2}", value)
            for value in self.settlement_window_utc
        ):
            raise ValueError("settlement_window_utc must contain two HH:MM values")
        if any(item not in {edge.value for edge in EdgeClass} for item in self.model_required_edge_classes):
            raise ValueError("model_required_edge_classes contains an unknown edge class")
        if (
            tuple(self.pre_entry_risk_veto_states)
            != (PreEntryRiskState.VETO.value,)
        ):
            raise ValueError(
                "pre_entry_risk_veto_states must be exactly ('VETO',)"
            )
        if (
            tuple(self.exchange_health_blocking_states)
            != (ExchangeHealthState.BLOCKED.value,)
        ):
            raise ValueError(
                "exchange_health_blocking_states must be exactly ('BLOCKED',)"
            )
        if not self.allowed_detectors:
            raise ValueError("allowed_detectors must not be empty")

    @property
    def catalog_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "trust_minimum_consecutive_passes": self.trust_minimum_consecutive_passes,
            "trust_minimum_observation_seconds": self.trust_minimum_observation_seconds,
            "market_snapshot_max_age_seconds": self.market_snapshot_max_age_seconds,
            "account_snapshot_max_age_seconds": self.account_snapshot_max_age_seconds,
            "pre_entry_risk_max_age_seconds": self.pre_entry_risk_max_age_seconds,
            "model_promotion_evidence_max_age_seconds": (
                self.model_promotion_evidence_max_age_seconds
            ),
            "quote_max_age_seconds": self.quote_max_age_seconds,
            "leg_sync_window_seconds": self.leg_sync_window_seconds,
            "opportunity_ttl_seconds": self.opportunity_ttl_seconds,
            "cost_coverage_ratio": self.cost_coverage_ratio,
            "max_spread_ratio": self.max_spread_ratio,
            "minimum_depth": self.minimum_depth,
            "minimum_open_interest": self.minimum_open_interest,
            "maximum_event_score": self.maximum_event_score,
            "model_required_edge_classes": list(self.model_required_edge_classes),
            "pre_entry_risk_veto_states": list(
                self.pre_entry_risk_veto_states
            ),
            "exchange_health_blocking_states": list(
                self.exchange_health_blocking_states
            ),
            "allowed_detectors": list(self.allowed_detectors),
            "settlement_window_utc": list(self.settlement_window_utc),
            "kill_switch": self.kill_switch,
            "research_output_ceiling": self.research_output_ceiling,
        }


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    schema_version: str
    policy_bundle_id: str
    mandate: AnalysisMandate
    catalog: PolicyCatalog

    @classmethod
    def create(
        cls,
        *,
        mandate: AnalysisMandate,
        catalog: PolicyCatalog,
    ) -> PolicyBundle:
        payload = {
            "schema_version": POLICY_BUNDLE_SCHEMA,
            "mandate": mandate.to_dict(),
            "catalog": catalog.to_dict(),
        }
        return cls(
            schema_version=POLICY_BUNDLE_SCHEMA,
            policy_bundle_id=f"policy:{canonical_sha256(payload)}",
            mandate=mandate,
            catalog=catalog,
        )

    @property
    def bundle_hash(self) -> str:
        return self.policy_bundle_id.removeprefix("policy:")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_bundle_id": self.policy_bundle_id,
            "mandate": self.mandate.to_dict(),
            "catalog": self.catalog.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ModelBundleRef:
    schema_version: str
    model_bundle_id: str
    promotion_status: str
    evidence_class: str
    artifact_hash: str | None
    promotion_evidence_hash: str | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_BUNDLE_SCHEMA:
            raise ValueError(f"schema_version must be {MODEL_BUNDLE_SCHEMA}")
        if self.promotion_status not in {"not_implemented", "research_only", "promoted"}:
            raise ValueError("unknown model promotion status")
        if self.artifact_hash is not None:
            _ensure_hash(self.artifact_hash, field="artifact_hash")
        if self.promotion_evidence_hash is not None:
            _ensure_hash(
                self.promotion_evidence_hash,
                field="promotion_evidence_hash",
            )
        if self.promotion_status == "promoted":
            if self.artifact_hash is None or self.promotion_evidence_hash is None:
                raise ValueError(
                    "promoted model bundle requires model and promotion evidence hashes"
                )
            if self.evidence_class not in {"real_oos", "promoted_oos"}:
                raise ValueError("promoted model bundle requires real OOS evidence")
            lowered = " ".join(
                (self.model_bundle_id, self.evidence_class, *self.reason_codes)
            ).lower()
            if any(token in lowered for token in _UNTRUSTED_SOURCE_TOKENS):
                raise ValueError("fixture/replay/tracer model bundles cannot be promoted")
        elif self.promotion_evidence_hash is not None:
            raise ValueError(
                "non-promoted model bundles cannot carry promotion evidence"
            )

    @classmethod
    def unavailable(cls) -> ModelBundleRef:
        return cls(
            schema_version=MODEL_BUNDLE_SCHEMA,
            model_bundle_id="model-bundle:unavailable",
            promotion_status="not_implemented",
            evidence_class="unavailable",
            artifact_hash=None,
            promotion_evidence_hash=None,
            reason_codes=("CALIBRATION_NOT_IMPLEMENTED",),
        )

    @classmethod
    def research(
        cls,
        *,
        model_bundle_id: str,
        artifact_hash: str,
    ) -> ModelBundleRef:
        return cls(
            schema_version=MODEL_BUNDLE_SCHEMA,
            model_bundle_id=model_bundle_id,
            promotion_status="research_only",
            evidence_class="research_fixture",
            artifact_hash=artifact_hash,
            promotion_evidence_hash=None,
            reason_codes=("MODEL_NOT_PROMOTED",),
        )

    @classmethod
    def promoted(
        cls,
        *,
        model_bundle_id: str,
        artifact_hash: str,
        promotion_evidence_hash: str,
        evidence_class: str,
    ) -> ModelBundleRef:
        return cls(
            schema_version=MODEL_BUNDLE_SCHEMA,
            model_bundle_id=model_bundle_id,
            promotion_status="promoted",
            evidence_class=evidence_class,
            artifact_hash=artifact_hash,
            promotion_evidence_hash=promotion_evidence_hash,
            reason_codes=(),
        )

    @property
    def model_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    @property
    def promoted_for(self) -> bool:
        return self.promotion_status == "promoted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_bundle_id": self.model_bundle_id,
            "promotion_status": self.promotion_status,
            "evidence_class": self.evidence_class,
            "artifact_hash": self.artifact_hash,
            "promotion_evidence_hash": self.promotion_evidence_hash,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    kind: str
    state: EvidenceState
    source: str
    observed_at: str | None
    received_at: str
    expires_at: str | None
    authenticated: bool
    payload_ref: str
    payload_hash: str
    reason_codes: tuple[str, ...]
    trust_consecutive_passes: int | None = None
    trust_observation_seconds: float | None = None
    schema_version: str = EVIDENCE_RECORD_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_RECORD_SCHEMA:
            raise ValueError(f"schema_version must be {EVIDENCE_RECORD_SCHEMA}")
        if not self.evidence_id or not self.kind or not self.source or not self.payload_ref:
            raise ValueError("evidence identity, kind, source, and payload_ref are required")
        _ensure_hash(self.payload_hash, field="payload_hash")
        _parse_timestamp(self.received_at, field="received_at")
        if self.observed_at is not None:
            _parse_timestamp(self.observed_at, field="observed_at")
        if self.expires_at is not None:
            expires = _parse_timestamp(self.expires_at, field="expires_at")
            if self.observed_at is not None and expires < _parse_timestamp(
                self.observed_at,
                field="observed_at",
            ):
                raise ValueError("evidence expires_at must not precede observed_at")
        if self.trust_consecutive_passes is not None and (
            isinstance(self.trust_consecutive_passes, bool)
            or not isinstance(self.trust_consecutive_passes, int)
            or self.trust_consecutive_passes < 0
        ):
            raise ValueError("trust_consecutive_passes must be a nonnegative integer")
        if self.trust_observation_seconds is not None:
            _finite_number(
                self.trust_observation_seconds,
                field="trust_observation_seconds",
                nonnegative=True,
            )
        if self.state is EvidenceState.TRUSTED:
            if not self.authenticated:
                raise ValueError("trusted evidence must be authenticated")
            lowered = f"{self.source} {self.payload_ref}".lower()
            if any(token in lowered for token in _UNTRUSTED_SOURCE_TOKENS):
                raise ValueError("fixture/replay/synthetic/tracer evidence cannot be trusted")
            if self.reason_codes:
                raise ValueError("trusted evidence must not carry blocking reason codes")
            if self.kind == "market_snapshot" and (
                self.trust_consecutive_passes is None
                or self.trust_observation_seconds is None
            ):
                raise ValueError(
                    "trusted market evidence requires explicit trust observations"
                )
        elif not self.reason_codes:
            raise ValueError("non-trusted evidence requires reason codes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "state": self.state.value,
            "source": self.source,
            "observed_at": self.observed_at,
            "received_at": self.received_at,
            "expires_at": self.expires_at,
            "authenticated": self.authenticated,
            "payload_ref": self.payload_ref,
            "payload_hash": self.payload_hash,
            "reason_codes": list(self.reason_codes),
            "trust_consecutive_passes": self.trust_consecutive_passes,
            "trust_observation_seconds": self.trust_observation_seconds,
        }

    def is_current_at(
        self,
        evaluation_clock: str,
        *,
        max_age_seconds: float | None,
        require_expiry: bool = True,
    ) -> bool:
        evaluated_at = _parse_timestamp(
            evaluation_clock,
            field="evidence evaluation_clock",
        )
        if self.observed_at is None:
            return False
        observed_at = _parse_timestamp(
            self.observed_at,
            field="evidence observed_at",
        )
        received_at = _parse_timestamp(
            self.received_at,
            field="evidence received_at",
        )
        if observed_at > evaluated_at or received_at > evaluated_at:
            return False
        if (
            max_age_seconds is not None
            and (evaluated_at - observed_at).total_seconds() > max_age_seconds
        ):
            return False
        if self.expires_at is None:
            return not require_expiry
        return (
            _parse_timestamp(self.expires_at, field="evidence expires_at")
            > evaluated_at
        )


@dataclass(frozen=True, slots=True)
class PreEntryRiskClaim:
    portfolio_state: PreEntryRiskState
    exchange_health_state: ExchangeHealthState
    reason_codes: tuple[str, ...] = ()
    schema_version: str = PRE_ENTRY_RISK_CLAIM_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PRE_ENTRY_RISK_CLAIM_SCHEMA:
            raise ValueError(
                f"schema_version must be {PRE_ENTRY_RISK_CLAIM_SCHEMA}"
            )

    @property
    def payload_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "portfolio_state": self.portfolio_state.value,
            "exchange_health_state": self.exchange_health_state.value,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class EconomicValue:
    amount: float
    currency: str
    kind: str
    product_type: str
    contract_scale: float | None
    as_of: str
    provenance: str

    def __post_init__(self) -> None:
        _finite_number(self.amount, field="economic amount")
        if self.contract_scale is not None:
            _finite_number(
                self.contract_scale,
                field="contract_scale",
                positive=True,
            )
        _parse_timestamp(self.as_of, field="economic value as_of")
        if not all(
            isinstance(value, str) and value
            for value in (
                self.currency,
                self.kind,
                self.product_type,
                self.provenance,
            )
        ):
            raise ValueError("economic value dimensions must be explicit strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "currency": self.currency,
            "kind": self.kind,
            "product_type": self.product_type,
            "contract_scale": self.contract_scale,
            "as_of": self.as_of,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class ProductEconomics:
    product_type: str
    product_style: str
    base_currency: str | None
    quote_currency: str | None
    settlement_currency: str | None
    premium_unit: str | None
    contract_scale: float | None
    provenance: str

    @property
    def units_explicit(self) -> bool:
        return (
            self.product_style in {"inverse", "linear"}
            and bool(self.premium_unit)
            and self.contract_scale is not None
        )

    @property
    def settlement_explicit(self) -> bool:
        return bool(self.settlement_currency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_type": self.product_type,
            "product_style": self.product_style,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "settlement_currency": self.settlement_currency,
            "premium_unit": self.premium_unit,
            "contract_scale": self.contract_scale,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class QuoteEvidence:
    evidence_ref: str
    observed_at: str | None
    quote_age_seconds: float | None
    bid: EconomicValue | None
    ask: EconomicValue | None
    depth: float | None
    open_interest: float | None
    spread_ratio: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_ref": self.evidence_ref,
            "observed_at": self.observed_at,
            "quote_age_seconds": self.quote_age_seconds,
            "bid": self.bid.to_dict() if self.bid else None,
            "ask": self.ask.to_dict() if self.ask else None,
            "depth": self.depth,
            "open_interest": self.open_interest,
            "spread_ratio": self.spread_ratio,
        }


@dataclass(frozen=True, slots=True)
class StrategyLeg:
    side: str
    quantity_ratio: float
    instrument_id: str
    option_type: str
    strike: EconomicValue
    expiry: str
    product_economics: ProductEconomics
    premium_coordinate: EconomicValue | None
    entry_price_policy: str
    source_quote: QuoteEvidence
    liquidity_evidence_ref: str

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("strategy leg side must be BUY or SELL")
        _finite_number(
            self.quantity_ratio,
            field="quantity_ratio",
            positive=True,
        )
        if self.option_type not in {"call", "put"}:
            raise ValueError("strategy leg option_type must be call or put")
        _parse_timestamp(f"{self.expiry}T00:00:00Z", field="expiry")

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "quantity_ratio": self.quantity_ratio,
            "instrument_id": self.instrument_id,
            "option_type": self.option_type,
            "strike": self.strike.to_dict(),
            "expiry": self.expiry,
            "product_economics": self.product_economics.to_dict(),
            "premium_coordinate": (
                self.premium_coordinate.to_dict()
                if self.premium_coordinate
                else None
            ),
            "entry_price_policy": self.entry_price_policy,
            "source_quote": self.source_quote.to_dict(),
            "liquidity_evidence_ref": self.liquidity_evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class OpportunityRecord:
    opportunity_id: str
    edge_class: EdgeClass
    detected_at: str
    valid_until: str
    market_snapshot_id: str
    detector_id: str
    detector_version: str
    model_id: str
    model_status: str
    fair_interval: tuple[EconomicValue, EconomicValue] | None
    observed_market_values: tuple[EconomicValue, ...]
    apparent_edge: EconomicValue | None
    uncertainty: EconomicValue | None
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    status: OpportunityStatus
    confidence_ceiling: str
    source_candidate_id: str
    schema_version: str = OPPORTUNITY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "opportunity_id": self.opportunity_id,
            "edge_class": self.edge_class.value,
            "detected_at": self.detected_at,
            "valid_until": self.valid_until,
            "market_snapshot_id": self.market_snapshot_id,
            "detector_id": self.detector_id,
            "detector_version": self.detector_version,
            "model_id": self.model_id,
            "model_status": self.model_status,
            "fair_interval": (
                [item.to_dict() for item in self.fair_interval]
                if self.fair_interval
                else None
            ),
            "observed_market_values": [
                item.to_dict() for item in self.observed_market_values
            ],
            "apparent_edge": (
                self.apparent_edge.to_dict() if self.apparent_edge else None
            ),
            "uncertainty": (
                self.uncertainty.to_dict() if self.uncertainty else None
            ),
            "evidence_refs": list(self.evidence_refs),
            "reason_codes": list(self.reason_codes),
            "invalidation_conditions": list(self.invalidation_conditions),
            "status": self.status.value,
            "confidence_ceiling": self.confidence_ceiling,
            "source_candidate_id": self.source_candidate_id,
        }


@dataclass(frozen=True, slots=True)
class GreekValue:
    name: str
    amount: float
    unit: str
    as_of: str
    provenance: str

    def __post_init__(self) -> None:
        if self.name not in {"delta", "gamma", "theta", "vega"}:
            raise ValueError("GreekValue name must be delta, gamma, theta, or vega")
        _finite_number(self.amount, field=f"{self.name} amount")
        _parse_timestamp(self.as_of, field=f"{self.name} as_of")
        if not self.unit or not self.provenance:
            raise ValueError("GreekValue unit and provenance are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "amount": self.amount,
            "unit": self.unit,
            "as_of": self.as_of,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class RejectedAlternative:
    structure: str
    reason_codes: tuple[str, ...]
    why: str

    def __post_init__(self) -> None:
        if not self.structure or not self.reason_codes or not self.why:
            raise ValueError(
                "RejectedAlternative requires structure, reason codes, and rationale"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure": self.structure,
            "reason_codes": list(self.reason_codes),
            "why": self.why,
        }


@dataclass(frozen=True, slots=True)
class StrategyPlan:
    strategy_id: str
    opportunity_id: str
    structure: str
    selection_role: str
    legs: tuple[StrategyLeg, ...]
    payoff_status: str
    breakeven: EconomicValue | None
    max_profit: EconomicValue | None
    max_loss: EconomicValue | None
    unbounded_loss: bool
    spread_width: EconomicValue | None
    net_premium: EconomicValue | None
    bid_ask_cost: EconomicValue | None
    fee: EconomicValue | None
    slippage_reserve: EconomicValue | None
    depth_impact: EconomicValue | None
    legging_reserve: EconomicValue | None
    hedge_reserve: EconomicValue | None
    model_uncertainty_reserve: EconomicValue | None
    exit_liquidity_proxy: str
    research_capacity_class: str | None
    conservative_net_edge: EconomicValue | None
    capital_at_risk_proxy: EconomicValue | None
    edge_to_capital_at_risk: float | None
    greeks: tuple[GreekValue, ...]
    why: tuple[str, ...]
    why_now: tuple[str, ...]
    why_this_structure: str
    rejected_alternatives: tuple[RejectedAlternative, ...]
    invalidation_rules: tuple[str, ...]
    observable_next_step: str
    reason_codes: tuple[str, ...]
    schema_version: str = STRATEGY_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("StrategyPlan requires at least one leg")
        if len({leg.expiry for leg in self.legs}) != 1:
            raise ValueError("all StrategyPlan legs must share one expiry")

    def to_dict(self) -> dict[str, Any]:
        def economic(value: EconomicValue | None) -> dict[str, Any] | None:
            return value.to_dict() if value else None

        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "opportunity_id": self.opportunity_id,
            "structure": self.structure,
            "selection_role": self.selection_role,
            "legs": [leg.to_dict() for leg in self.legs],
            "payoff_status": self.payoff_status,
            "breakeven": economic(self.breakeven),
            "max_profit": economic(self.max_profit),
            "max_loss": economic(self.max_loss),
            "unbounded_loss": self.unbounded_loss,
            "spread_width": economic(self.spread_width),
            "net_premium": economic(self.net_premium),
            "bid_ask_cost": economic(self.bid_ask_cost),
            "fee": economic(self.fee),
            "slippage_reserve": economic(self.slippage_reserve),
            "depth_impact": economic(self.depth_impact),
            "legging_reserve": economic(self.legging_reserve),
            "hedge_reserve": economic(self.hedge_reserve),
            "model_uncertainty_reserve": economic(
                self.model_uncertainty_reserve
            ),
            "exit_liquidity_proxy": self.exit_liquidity_proxy,
            "research_capacity_class": self.research_capacity_class,
            "conservative_net_edge": economic(self.conservative_net_edge),
            "capital_at_risk_proxy": economic(self.capital_at_risk_proxy),
            "edge_to_capital_at_risk": self.edge_to_capital_at_risk,
            "greeks": [item.to_dict() for item in self.greeks],
            "why": list(self.why),
            "why_now": list(self.why_now),
            "why_this_structure": self.why_this_structure,
            "rejected_alternatives": [
                item.to_dict() for item in self.rejected_alternatives
            ],
            "invalidation_rules": list(self.invalidation_rules),
            "observable_next_step": self.observable_next_step,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class AdmissionCondition:
    condition_id: str
    observed: str | float | int | bool | None
    requirement: str
    status: ConditionStatus
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "observed": self.observed,
            "requirement": self.requirement,
            "status": self.status.value,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class EntryAdmissionDecision:
    decision_id: str
    analysis_run_id: str
    opportunity_id: str | None
    strategy_id: str | None
    evaluated_at: str
    valid_until: str
    status: EntryAdmissionStatus
    execution_allowed: bool
    conditions: tuple[AdmissionCondition, ...]
    veto_sources: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    policy_bundle_id: str
    model_bundle_id: str
    market_snapshot_id: str
    account_evidence_id: str | None
    confidence_ceiling: str
    next_observable_condition: str | None
    schema_version: str = ENTRY_ADMISSION_SCHEMA

    def __post_init__(self) -> None:
        if self.execution_allowed is not False:
            raise ValueError("EntryAdmissionDecision execution_allowed must be false")

    def to_dict(self) -> dict[str, Any]:
        passed = [
            condition.to_dict()
            for condition in self.conditions
            if condition.status is ConditionStatus.PASS
        ]
        blocked = [
            condition.to_dict()
            for condition in self.conditions
            if condition.status is ConditionStatus.BLOCK
        ]
        unknown = [
            condition.to_dict()
            for condition in self.conditions
            if condition.status is ConditionStatus.UNKNOWN
        ]
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "analysis_run_id": self.analysis_run_id,
            "opportunity_id": self.opportunity_id,
            "strategy_id": self.strategy_id,
            "evaluated_at": self.evaluated_at,
            "valid_until": self.valid_until,
            "status": self.status.value,
            "execution_allowed": False,
            "conditions": [item.to_dict() for item in self.conditions],
            "blocking_conditions": blocked,
            "passed_conditions": passed,
            "unknown_conditions": unknown,
            "veto_sources": list(self.veto_sources),
            "reason_codes": list(self.reason_codes),
            "evidence_refs": list(self.evidence_refs),
            "policy_bundle_id": self.policy_bundle_id,
            "model_bundle_id": self.model_bundle_id,
            "market_snapshot_id": self.market_snapshot_id,
            "account_evidence_id": self.account_evidence_id,
            "confidence_ceiling": self.confidence_ceiling,
            "next_observable_condition": self.next_observable_condition,
        }


@dataclass(frozen=True, slots=True)
class MarketAnalysis:
    market_snapshot_id: str
    status: str
    as_of: str | None
    spot: EconomicValue | None
    dvol_percent: float | None
    surface_status: str
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_snapshot_id": self.market_snapshot_id,
            "status": self.status,
            "as_of": self.as_of,
            "spot": self.spot.to_dict() if self.spot else None,
            "dvol_percent": self.dvol_percent,
            "surface_status": self.surface_status,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: str
    event_type: str
    occurred_at: str
    observed_at: str
    actor: str
    source: str
    correlation_id: str
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    payload_json: str
    schema_version: str = DOMAIN_EVENT_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        occurred_at: str,
        observed_at: str,
        actor: str,
        source: str,
        correlation_id: str,
        evidence_refs: Iterable[str],
        reason_codes: Iterable[str],
        payload: Mapping[str, Any],
    ) -> DomainEvent:
        payload_json = _canonical_json(payload)
        identity = {
            "event_type": event_type,
            "occurred_at": occurred_at,
            "observed_at": observed_at,
            "actor": actor,
            "source": source,
            "correlation_id": correlation_id,
            "evidence_refs": sorted(set(evidence_refs)),
            "reason_codes": sorted(set(reason_codes)),
            "payload": json.loads(payload_json),
        }
        return cls(
            event_id=f"event:{canonical_sha256(identity)}",
            event_type=event_type,
            occurred_at=occurred_at,
            observed_at=observed_at,
            actor=actor,
            source=source,
            correlation_id=correlation_id,
            evidence_refs=tuple(sorted(set(evidence_refs))),
            reason_codes=tuple(sorted(set(reason_codes))),
            payload_json=payload_json,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "observed_at": self.observed_at,
            "actor": self.actor,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "evidence_refs": list(self.evidence_refs),
            "reason_codes": list(self.reason_codes),
            "payload": json.loads(self.payload_json),
        }


@dataclass(frozen=True, slots=True)
class DecisionManifest:
    manifest_id: str
    code_version: str
    configuration_hash: str
    policy_bundle_id: str
    policy_bundle_hash: str
    model_bundle_id: str
    model_bundle_hash: str
    evaluation_clock: str
    market_snapshot_hash: str
    account_evidence_hash: str | None
    historical_artifact_hash: str | None
    pre_entry_risk_evidence_hash: str | None
    detector_versions: tuple[str, ...]
    projection_hash: str
    output_hash: str
    schema_version: str = DECISION_MANIFEST_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "code_version": self.code_version,
            "configuration_hash": self.configuration_hash,
            "policy_bundle_id": self.policy_bundle_id,
            "policy_bundle_hash": self.policy_bundle_hash,
            "model_bundle_id": self.model_bundle_id,
            "model_bundle_hash": self.model_bundle_hash,
            "evaluation_clock": self.evaluation_clock,
            "market_snapshot_hash": self.market_snapshot_hash,
            "account_evidence_hash": self.account_evidence_hash,
            "historical_artifact_hash": self.historical_artifact_hash,
            "pre_entry_risk_evidence_hash": self.pre_entry_risk_evidence_hash,
            "detector_versions": list(self.detector_versions),
            "projection_hash": self.projection_hash,
            "output_hash": self.output_hash,
        }


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    evaluation_clock: str
    policy_bundle: PolicyBundle
    market_evidence: EvidenceRecord
    account_evidence: EvidenceRecord | None
    historical_artifact: EvidenceRecord | None
    pre_entry_risk_claim: PreEntryRiskClaim | None
    pre_entry_risk_evidence: EvidenceRecord | None
    model_bundle: ModelBundleRef
    configuration_hash: str
    report_projection_json: str
    market_snapshot_json: str | None
    strategy_history_artifacts_json: str
    strategy_forecast_runtime_evidence_json: str
    opportunity_detected_at: str
    detector_versions: tuple[str, ...]

    def __post_init__(self) -> None:
        _parse_timestamp(self.evaluation_clock, field="evaluation_clock")
        _parse_timestamp(
            self.opportunity_detected_at,
            field="opportunity_detected_at",
        )
        _ensure_hash(self.configuration_hash, field="configuration_hash")
        if self.policy_bundle.mandate.evaluation_clock != self.evaluation_clock:
            raise ValueError("mandate and request evaluation clocks must match")
        if (
            self.policy_bundle.mandate.model_bundle_id
            != self.model_bundle.model_bundle_id
        ):
            raise ValueError("mandate and request model bundles must match")
        if not self.detector_versions:
            raise ValueError("detector_versions must not be empty")
        projection = json.loads(self.report_projection_json)
        if projection.get("generated_at") != self.evaluation_clock:
            raise ValueError("report projection must use the fixed evaluation clock")
        _strategy_history_artifacts_from_json(self.strategy_history_artifacts_json)
        _strategy_forecast_runtime_evidence_from_json(
            self.strategy_forecast_runtime_evidence_json
        )
        if self.market_evidence.kind != "market_snapshot":
            raise ValueError("market evidence kind must be market_snapshot")
        if self.account_evidence is not None:
            if self.account_evidence.kind != "account_snapshot":
                raise ValueError("account evidence kind must be account_snapshot")
            account_projection = projection.get("account_status") or {}
            if (
                self.account_evidence.payload_hash
                != canonical_sha256(account_projection)
            ):
                raise ValueError(
                    "account evidence hash must match the account projection"
                )
            if (
                self.account_evidence.state is EvidenceState.TRUSTED
                and self.account_evidence.source
                != str(account_projection.get("source") or "")
            ):
                raise ValueError(
                    "trusted account evidence source must match the account projection"
                )
        if (self.pre_entry_risk_claim is None) != (
            self.pre_entry_risk_evidence is None
        ):
            raise ValueError(
                "pre-entry risk claim and evidence must be supplied together"
            )
        if (
            self.pre_entry_risk_claim is not None
            and self.pre_entry_risk_evidence is not None
        ):
            if self.pre_entry_risk_evidence.kind != "pre_entry_risk_veto":
                raise ValueError(
                    "pre-entry risk evidence kind must be pre_entry_risk_veto"
                )
            if (
                self.pre_entry_risk_evidence.payload_hash
                != self.pre_entry_risk_claim.payload_hash
            ):
                raise ValueError(
                    "pre-entry risk evidence hash must match the typed risk claim"
                )
        if self.model_bundle.promoted_for:
            if (
                self.historical_artifact is None
                or self.historical_artifact.kind
                != "historical_oos_promotion_artifact"
                or self.historical_artifact.state is not EvidenceState.TRUSTED
                or self.historical_artifact.payload_hash
                != self.model_bundle.promotion_evidence_hash
                or not self.historical_artifact.is_current_at(
                    self.evaluation_clock,
                    max_age_seconds=(
                        self.policy_bundle.catalog
                        .model_promotion_evidence_max_age_seconds
                    ),
                    require_expiry=False,
                )
            ):
                raise ValueError(
                    "promoted model requires bound, trusted, current historical OOS evidence"
                )
        if self.market_snapshot_json is not None:
            snapshot = json.loads(self.market_snapshot_json)
            digest = snapshot_payload_sha256(snapshot)
            if digest != self.market_evidence.payload_hash:
                raise ValueError("market evidence hash must match the market snapshot")
            if (
                self.market_evidence.state is EvidenceState.TRUSTED
                and str(snapshot.get("source") or "")
                != self.market_evidence.source
            ):
                raise ValueError(
                    "trusted market evidence source must match the snapshot source"
                )

    @classmethod
    def from_projection(
        cls,
        *,
        evaluation_clock: str,
        report_projection: Mapping[str, Any],
        market_snapshot: Mapping[str, Any] | None,
        market_evidence: EvidenceRecord | None = None,
        account_evidence: EvidenceRecord | None = None,
        historical_artifact: EvidenceRecord | None = None,
        pre_entry_risk_claim: PreEntryRiskClaim | None = None,
        pre_entry_risk_evidence: EvidenceRecord | None = None,
        mandate: AnalysisMandate | None = None,
        policy_catalog: PolicyCatalog | None = None,
        model_bundle: ModelBundleRef | None = None,
        configuration: Any | None = None,
        configuration_hash: str | None = None,
        strategy_history_artifacts: Iterable[Mapping[str, Any]] = (),
        strategy_forecast_runtime_evidence: Iterable[Mapping[str, Any]] = (),
        opportunity_detected_at: str | None = None,
        detector_versions: tuple[str, ...] = ("legacy-candidate-screen:v1",),
    ) -> AnalysisRequest:
        _parse_timestamp(evaluation_clock, field="evaluation_clock")
        projection_json = _canonical_json(report_projection)
        projection = json.loads(projection_json)
        if projection.get("generated_at") != evaluation_clock:
            raise ValueError("report projection must use the fixed evaluation clock")

        model = model_bundle or _model_bundle_from_projection(projection)
        catalog = policy_catalog or PolicyCatalog()
        selected_mandate = mandate or AnalysisMandate(
            policy_version=catalog.policy_version,
            model_bundle_id=model.model_bundle_id,
            risk_policy_id=catalog.policy_version,
            evaluation_clock=evaluation_clock,
        )
        if selected_mandate.evaluation_clock is None:
            selected_mandate = replace(
                selected_mandate,
                evaluation_clock=evaluation_clock,
                policy_version=catalog.policy_version,
                model_bundle_id=model.model_bundle_id,
                risk_policy_id=catalog.policy_version,
            )
        bundle = PolicyBundle.create(
            mandate=selected_mandate,
            catalog=catalog,
        )
        if configuration_hash is not None:
            _ensure_hash(configuration_hash, field="configuration_hash")
            config_hash = configuration_hash
        else:
            config_hash = canonical_sha256(
                {} if configuration is None else configuration
            )
        history_artifacts_json = _normalize_strategy_history_artifacts(
            strategy_history_artifacts
        )
        forecast_runtime_evidence_json = (
            _normalize_strategy_forecast_runtime_evidence(
                strategy_forecast_runtime_evidence
            )
        )
        if history_artifacts_json != "[]" or forecast_runtime_evidence_json != "[]":
            config_hash = canonical_sha256(
                {
                    "base_configuration_hash": config_hash,
                    "strategy_history_artifacts_hash": canonical_sha256(
                        json.loads(history_artifacts_json)
                    ),
                    "strategy_forecast_runtime_evidence_hash": canonical_sha256(
                        json.loads(forecast_runtime_evidence_json)
                    ),
                }
            )

        snapshot_json: str | None = None
        if market_snapshot is not None:
            snapshot_copy = dict(market_snapshot)
            snapshot_copy.pop("trust_evidence", None)
            snapshot_copy.pop("_bound_trust_evidence", None)
            snapshot_json = _canonical_json(snapshot_copy)
            snapshot_value = json.loads(snapshot_json)
        else:
            snapshot_value = None
        resolved_market_evidence = market_evidence or _market_evidence_from_projection(
            projection,
            snapshot_value,
            evaluation_clock=evaluation_clock,
            max_age_seconds=catalog.market_snapshot_max_age_seconds,
        )
        if account_evidence is None:
            account_evidence = _account_evidence_from_projection(
                projection,
                evaluation_clock=evaluation_clock,
            )
        return cls(
            evaluation_clock=evaluation_clock,
            policy_bundle=bundle,
            market_evidence=resolved_market_evidence,
            account_evidence=account_evidence,
            historical_artifact=historical_artifact,
            pre_entry_risk_claim=pre_entry_risk_claim,
            pre_entry_risk_evidence=pre_entry_risk_evidence,
            model_bundle=model,
            configuration_hash=config_hash,
            report_projection_json=projection_json,
            market_snapshot_json=snapshot_json,
            strategy_history_artifacts_json=history_artifacts_json,
            strategy_forecast_runtime_evidence_json=forecast_runtime_evidence_json,
            opportunity_detected_at=opportunity_detected_at or evaluation_clock,
            detector_versions=tuple(sorted(set(detector_versions))),
        )

    def projection(self) -> dict[str, Any]:
        return json.loads(self.report_projection_json)

    def market_snapshot(self) -> dict[str, Any] | None:
        return (
            json.loads(self.market_snapshot_json)
            if self.market_snapshot_json is not None
            else None
        )


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    analysis_run_id: str
    manifest: DecisionManifest
    policy_bundle: PolicyBundle
    model_bundle: ModelBundleRef
    trust_verdict: str
    market_analysis: MarketAnalysis
    opportunities: tuple[OpportunityRecord, ...]
    strategy_plans: tuple[StrategyPlan, ...]
    entry_admission_decisions: tuple[EntryAdmissionDecision, ...]
    global_reason_codes: tuple[str, ...]
    evidence_lineage: tuple[EvidenceRecord, ...]
    domain_events: tuple[DomainEvent, ...]
    output_hash: str
    _research_report_projection_json: str
    _strategy_history_artifacts_json: str
    _strategy_forecast_runtime_evidence_json: str
    schema_version: str = ANALYSIS_RECORD_SCHEMA

    def _base_research_report_projection(self) -> dict[str, Any]:
        return json.loads(self._research_report_projection_json)

    def project_strategy_brief_v1(self) -> dict[str, Any]:
        report = self._base_research_report_projection()
        candidates = _strategy_brief_candidates(self, report)
        generated_at = str(report.get("generated_at") or self.manifest.evaluation_clock)
        history_by_candidate = _strategy_brief_history_by_candidate(
            generated_at=generated_at,
            candidates=candidates,
            artifacts=_strategy_history_artifacts_from_json(
                self._strategy_history_artifacts_json
            ),
        )
        forecast_by_candidate = _strategy_brief_forecast_by_candidate(
            generated_at=generated_at,
            candidates=candidates,
            runtime_evidence=_strategy_forecast_runtime_evidence_from_json(
                self._strategy_forecast_runtime_evidence_json
            ),
        )
        return build_strategy_brief(
            analysis_run_id=self.analysis_run_id,
            generated_at=generated_at,
            market=_strategy_brief_market(self, report, candidates=candidates),
            candidates=candidates,
            history_by_candidate=history_by_candidate,
            forecast_by_candidate=forecast_by_candidate,
            policy_ttl_seconds=self.policy_bundle.catalog.market_snapshot_max_age_seconds,
        )

    def project_research_report_v1(self) -> dict[str, Any]:
        """Return a detached compatibility projection."""
        projection = self._base_research_report_projection()
        projection["strategy_brief"] = self.project_strategy_brief_v1()
        return projection

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "analysis_run_id": self.analysis_run_id,
            "manifest": self.manifest.to_dict(),
            "policy_bundle": self.policy_bundle.to_dict(),
            "model_bundle": self.model_bundle.to_dict(),
            "trust_verdict": self.trust_verdict,
            "market_analysis": self.market_analysis.to_dict(),
            "opportunities": [item.to_dict() for item in self.opportunities],
            "strategy_plans": [item.to_dict() for item in self.strategy_plans],
            "entry_admission_decisions": [
                item.to_dict() for item in self.entry_admission_decisions
            ],
            "global_reason_codes": list(self.global_reason_codes),
            "evidence_lineage": [
                item.to_dict() for item in self.evidence_lineage
            ],
            "domain_events": [item.to_dict() for item in self.domain_events],
            "output_hash": self.output_hash,
            "research_only": True,
        }

    def hash_payload(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("output_hash", None)
        payload["manifest"] = dict(payload["manifest"])
        payload["manifest"].pop("output_hash", None)
        return payload


class AnalysisRun:
    """Deep application seam for deterministic pre-entry analysis."""

    def evaluate(self, request: AnalysisRequest) -> AnalysisRecord:
        projection = request.projection()
        snapshot = request.market_snapshot()
        policy = request.policy_bundle.catalog
        evidence = _effective_market_evidence(
            request.market_evidence,
            projection,
            policy=policy,
        )
        market_snapshot_id = f"market:{evidence.payload_hash}"
        manifest_inputs = {
            "schema_version": DECISION_MANIFEST_SCHEMA,
            "code_version": CODE_VERSION,
            "configuration_hash": request.configuration_hash,
            "policy_bundle_id": request.policy_bundle.policy_bundle_id,
            "policy_bundle_hash": request.policy_bundle.bundle_hash,
            "model_bundle_id": request.model_bundle.model_bundle_id,
            "model_bundle_hash": request.model_bundle.model_hash,
            "evaluation_clock": request.evaluation_clock,
            "market_snapshot_hash": evidence.payload_hash,
            "account_evidence_hash": (
                request.account_evidence.payload_hash
                if request.account_evidence
                else None
            ),
            "historical_artifact_hash": (
                request.historical_artifact.payload_hash
                if request.historical_artifact
                else None
            ),
            "pre_entry_risk_evidence_hash": (
                request.pre_entry_risk_evidence.payload_hash
                if request.pre_entry_risk_evidence
                else None
            ),
            "detector_versions": list(request.detector_versions),
            "projection_hash": canonical_sha256(projection),
        }
        manifest_id = f"manifest:{canonical_sha256(manifest_inputs)}"
        analysis_run_id = f"analysis:{canonical_sha256({'manifest': manifest_inputs})}"

        market_analysis = _market_analysis(
            projection,
            snapshot=snapshot,
            market_snapshot_id=market_snapshot_id,
            market_evidence=evidence,
        )
        opportunities: tuple[OpportunityRecord, ...]
        strategies: tuple[StrategyPlan, ...]
        if evidence.state is EvidenceState.TRUSTED:
            opportunities = _opportunities_from_projection(
                projection,
                market_snapshot_id=market_snapshot_id,
                market_evidence=evidence,
                detected_at=request.opportunity_detected_at,
                evaluation_clock=request.evaluation_clock,
                policy=policy,
                model_bundle=request.model_bundle,
            )
            strategies = _strategies_from_opportunities(
                opportunities,
                projection=projection,
                snapshot=snapshot,
                market_evidence=evidence,
                evaluation_clock=request.evaluation_clock,
            )
            opportunities = _classify_opportunity_economics(
                opportunities,
                strategies,
                policy=policy,
            )
        else:
            opportunities = ()
            strategies = ()

        decisions = _entry_admission_decisions(
            analysis_run_id=analysis_run_id,
            projection=projection,
            market_evidence=evidence,
            market_snapshot_id=market_snapshot_id,
            opportunities=opportunities,
            strategies=strategies,
            account_evidence=request.account_evidence,
            historical_artifact=request.historical_artifact,
            pre_entry_risk_claim=request.pre_entry_risk_claim,
            pre_entry_risk_evidence=request.pre_entry_risk_evidence,
            policy_bundle=request.policy_bundle,
            model_bundle=request.model_bundle,
            evaluated_at=request.evaluation_clock,
        )
        lineage = tuple(
            item
            for item in (
                evidence,
                request.account_evidence,
                request.historical_artifact,
                request.pre_entry_risk_evidence,
            )
            if item is not None
        )
        reasons = _unique_codes(
            [
                *evidence.reason_codes,
                *[
                    code
                    for decision in decisions
                    for code in decision.reason_codes
                ],
            ]
        )
        events = _domain_events(
            analysis_run_id=analysis_run_id,
            evaluated_at=request.evaluation_clock,
            evidence_refs=tuple(item.evidence_id for item in lineage),
            opportunities=opportunities,
            decisions=decisions,
            global_reason_codes=reasons,
        )
        manifest = DecisionManifest(
            manifest_id=manifest_id,
            output_hash="",
            **manifest_inputs,
        )
        preliminary = AnalysisRecord(
            analysis_run_id=analysis_run_id,
            manifest=manifest,
            policy_bundle=request.policy_bundle,
            model_bundle=request.model_bundle,
            trust_verdict=evidence.state.value,
            market_analysis=market_analysis,
            opportunities=opportunities,
            strategy_plans=strategies,
            entry_admission_decisions=decisions,
            global_reason_codes=tuple(reasons),
            evidence_lineage=lineage,
            domain_events=events,
            output_hash="",
            _research_report_projection_json=request.report_projection_json,
            _strategy_history_artifacts_json=request.strategy_history_artifacts_json,
            _strategy_forecast_runtime_evidence_json=(
                request.strategy_forecast_runtime_evidence_json
            ),
        )
        output_hash = canonical_sha256(preliminary.hash_payload())
        record = replace(
            preliminary,
            manifest=replace(manifest, output_hash=output_hash),
            output_hash=output_hash,
        )
        errors = validate_analysis_record(record)
        if errors:
            raise ValueError("; ".join(errors))
        return record


def build_analysis_record(
    *,
    mode: str = "research_only",
    generated_at: str | None = None,
    market_snapshot: dict[str, Any] | None = None,
    account_payload: dict[str, Any] | None = None,
    account_scenario: str | None = None,
    backtest_artifact: dict[str, Any] | None = None,
    paper_ledger_path: str | None = None,
    manual_approval_runbook_path: str | None = None,
    persist_paper_ledger: bool = True,
    mandate: AnalysisMandate | None = None,
    policy_catalog: PolicyCatalog | None = None,
    model_bundle: ModelBundleRef | None = None,
    market_evidence: EvidenceRecord | None = None,
    account_evidence: EvidenceRecord | None = None,
    historical_artifact: EvidenceRecord | None = None,
    pre_entry_risk_claim: PreEntryRiskClaim | None = None,
    pre_entry_risk_evidence: EvidenceRecord | None = None,
    configuration: Any | None = None,
    configuration_hash: str | None = None,
    strategy_history_artifacts: Iterable[Mapping[str, Any]] = (),
    strategy_forecast_runtime_evidence: Iterable[Mapping[str, Any]] = (),
    opportunity_detected_at: str | None = None,
    underlying_history: dict[str, Any] | None = None,
) -> AnalysisRecord:
    """Build the legacy projection once, then evaluate one immutable record."""
    from . import contract as contract_module

    evaluation_clock = generated_at or contract_module.utc_timestamp()
    projection = contract_module._build_research_report_v1_projection(
        mode=mode,
        generated_at=evaluation_clock,
        market_snapshot=market_snapshot,
        account_payload=account_payload,
        account_scenario=account_scenario,
        backtest_artifact=backtest_artifact,
        paper_ledger_path=paper_ledger_path,
        manual_approval_runbook_path=manual_approval_runbook_path,
        persist_paper_ledger=persist_paper_ledger,
        underlying_history=underlying_history,
    )
    request = AnalysisRequest.from_projection(
        evaluation_clock=evaluation_clock,
        report_projection=projection,
        market_snapshot=market_snapshot,
        market_evidence=market_evidence,
        account_evidence=account_evidence,
        historical_artifact=historical_artifact,
        pre_entry_risk_claim=pre_entry_risk_claim,
        pre_entry_risk_evidence=pre_entry_risk_evidence,
        mandate=mandate,
        policy_catalog=policy_catalog,
        model_bundle=model_bundle,
        configuration=configuration,
        configuration_hash=configuration_hash,
        strategy_history_artifacts=strategy_history_artifacts,
        strategy_forecast_runtime_evidence=strategy_forecast_runtime_evidence,
        opportunity_detected_at=opportunity_detected_at,
    )
    return AnalysisRun().evaluate(request)


def validate_analysis_record(value: AnalysisRecord | Mapping[str, Any]) -> list[str]:
    payload = value.to_dict() if isinstance(value, AnalysisRecord) else dict(value)
    errors: list[str] = []
    if payload.get("schema_version") != ANALYSIS_RECORD_SCHEMA:
        errors.append(f"schema_version must be {ANALYSIS_RECORD_SCHEMA}")
    if payload.get("research_only") is not True:
        errors.append("analysis record must remain research_only")
    trust = payload.get("trust_verdict")
    opportunities = payload.get("opportunities")
    if trust != EvidenceState.TRUSTED.value and opportunities:
        errors.append("non-trusted evidence must not produce opportunities")
    for decision in payload.get("entry_admission_decisions") or []:
        if decision.get("execution_allowed") is not False:
            errors.append("entry admission execution_allowed must remain false")
        conditions = decision.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            errors.append("entry admission decisions require auditable conditions")
            continue
        for condition in conditions:
            if not isinstance(condition, dict) or set(condition) != {
                "condition_id",
                "observed",
                "requirement",
                "status",
                "reason_code",
            }:
                errors.append("admission conditions must preserve all audit fields")
        if (
            decision.get("status")
            == EntryAdmissionStatus.CONDITIONALLY_ELIGIBLE.value
            and decision.get("unknown_conditions")
        ):
            errors.append("unknown conditions cannot be conditionally eligible")
    forbidden = _find_forbidden_keys(payload)
    if forbidden:
        errors.append(f"analysis record contains forbidden keys: {sorted(forbidden)}")
    try:
        encoded = _canonical_json(payload)
    except ValueError as exc:
        errors.append(str(exc))
        encoded = ""
    if encoded:
        supplied_hash = payload.get("output_hash")
        manifest = payload.get("manifest") or {}
        hash_payload = dict(payload)
        hash_payload.pop("output_hash", None)
        hash_payload["manifest"] = dict(manifest)
        hash_payload["manifest"].pop("output_hash", None)
        expected_hash = canonical_sha256(hash_payload)
        if supplied_hash != expected_hash:
            errors.append("analysis output_hash does not match canonical payload")
        if manifest.get("output_hash") != supplied_hash:
            errors.append("manifest output_hash must match analysis output_hash")
    return errors


def _find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _FORBIDDEN_ANALYSIS_KEYS:
                found.add(str(key))
            if key == "execution_allowed" and nested is not False:
                found.add("execution_allowed=true")
            found.update(_find_forbidden_keys(nested))
    elif isinstance(value, (tuple, list)):
        for nested in value:
            found.update(_find_forbidden_keys(nested))
    return found


def _effective_market_evidence(
    supplied: EvidenceRecord,
    projection: Mapping[str, Any],
    *,
    policy: PolicyCatalog,
) -> EvidenceRecord:
    data_status = projection.get("data_status") or {}
    evaluation_clock = str(projection.get("generated_at") or "")
    clock = _parse_timestamp(evaluation_clock, field="evaluation clock")
    observed_at = (
        _parse_timestamp(supplied.observed_at, field="market evidence observed_at")
        if supplied.observed_at is not None
        else None
    )
    received_at = _parse_timestamp(
        supplied.received_at,
        field="market evidence received_at",
    )
    expired = (
        supplied.expires_at is not None
        and bool(evaluation_clock)
        and _parse_timestamp(supplied.expires_at, field="market evidence expires_at")
        <= clock
    )
    future_observation = observed_at is not None and observed_at > clock
    stale_observation = (
        observed_at is None
        or future_observation
        or (
            observed_at is not None
            and (clock - observed_at).total_seconds()
            > policy.market_snapshot_max_age_seconds
        )
    )
    future_receipt = received_at > clock
    trust_observation_shortfall = (
        supplied.trust_consecutive_passes is None
        or supplied.trust_consecutive_passes
        < policy.trust_minimum_consecutive_passes
        or supplied.trust_observation_seconds is None
        or supplied.trust_observation_seconds
        < policy.trust_minimum_observation_seconds
    )
    if (
        supplied.state is EvidenceState.TRUSTED
        and (
            data_status.get("status") != "validated"
            or expired
            or stale_observation
            or future_receipt
            or trust_observation_shortfall
        )
    ):
        reasons = _unique_codes(
            [
                *list(
                    (data_status.get("quality_gate") or {}).get("reason_codes")
                    or []
                ),
                "MARKET_EVIDENCE_EXPIRED" if expired else None,
                (
                    str(
                        data_status.get("reason_code")
                        or "MARKET_DATA_QUALITY_FAIL"
                    )
                    if data_status.get("status") != "validated"
                    else None
                ),
                (
                    "MARKET_EVIDENCE_OBSERVED_AT_MISSING"
                    if observed_at is None
                    else "MARKET_EVIDENCE_FROM_FUTURE"
                    if future_observation
                    else "MARKET_EVIDENCE_STALE"
                    if stale_observation
                    else None
                ),
                (
                    "MARKET_EVIDENCE_RECEIVED_FROM_FUTURE"
                    if future_receipt
                    else None
                ),
                (
                    "MARKET_TRUST_THRESHOLD_NOT_MET"
                    if trust_observation_shortfall
                    else None
                ),
            ]
        )
        return replace(
            supplied,
            state=EvidenceState.UNTRUSTED,
            authenticated=False,
            reason_codes=tuple(reasons),
        )
    return supplied


def _market_evidence_from_projection(
    projection: Mapping[str, Any],
    snapshot: Mapping[str, Any] | None,
    *,
    evaluation_clock: str,
    max_age_seconds: float,
) -> EvidenceRecord:
    data_status = projection.get("data_status") or {}
    trust = projection.get("data_trust") or {}
    if snapshot is None:
        digest = canonical_sha256({"market_snapshot": None})
    else:
        digest = snapshot_payload_sha256(dict(snapshot))
    verdict = str(trust.get("verdict") or "untrusted")
    state = {
        "trusted": EvidenceState.TRUSTED,
        "degraded": EvidenceState.DEGRADED,
        "untrusted": EvidenceState.UNTRUSTED,
    }.get(verdict, EvidenceState.UNTRUSTED)
    if data_status.get("status") == "missing":
        state = EvidenceState.MISSING
    trust_evidence = data_status.get("trust_evidence") or {}
    raw_passes = trust_evidence.get("consecutive_passes")
    consecutive_passes = (
        raw_passes
        if isinstance(raw_passes, int)
        and not isinstance(raw_passes, bool)
        and raw_passes >= 0
        else None
    )
    observation_seconds = _optional_finite(
        trust_evidence.get("observation_seconds")
    )
    minimum_passes = _optional_positive(
        trust_evidence.get(
            "minimum_consecutive_passes",
            trust_evidence.get("required_consecutive_passes"),
        )
    )
    minimum_observation_seconds = _optional_positive(
        trust_evidence.get(
            "minimum_observation_seconds",
            trust_evidence.get("required_observation_sec"),
        )
    )
    if state is EvidenceState.TRUSTED and (
        consecutive_passes is None
        or observation_seconds is None
        or minimum_passes is None
        or minimum_observation_seconds is None
    ):
        state = EvidenceState.DEGRADED
    observed_at = data_status.get("snapshot_captured_at")
    expires_at = (
        _timestamp(
            _parse_timestamp(str(observed_at), field="snapshot_captured_at")
            + timedelta(seconds=max_age_seconds)
        )
        if observed_at
        else None
    )
    reasons = tuple(
        _unique_codes(
            [str(item) for item in trust.get("reason_codes") or []]
            or [
                (
                    "MARKET_TRUST_THRESHOLD_EVIDENCE_MISSING"
                    if verdict == "trusted"
                    and (
                        minimum_passes is None
                        or minimum_observation_seconds is None
                    )
                    else (
                        "MARKET_TRUST_OBSERVATIONS_MISSING"
                        if verdict == "trusted"
                        else "MISSING_VALIDATED_MARKET_DATA"
                    )
                )
            ]
        )
    )
    return EvidenceRecord(
        evidence_id=f"market:{digest}",
        kind="market_snapshot",
        state=state,
        source=str(data_status.get("source") or "not_configured"),
        observed_at=str(observed_at) if observed_at else None,
        received_at=evaluation_clock,
        expires_at=expires_at,
        authenticated=state is EvidenceState.TRUSTED,
        payload_ref=f"sha256:{digest}",
        payload_hash=digest,
        reason_codes=() if state is EvidenceState.TRUSTED else reasons,
        trust_consecutive_passes=consecutive_passes,
        trust_observation_seconds=observation_seconds,
    )


def _account_evidence_from_projection(
    projection: Mapping[str, Any],
    *,
    evaluation_clock: str,
) -> EvidenceRecord | None:
    account = projection.get("account_status") or {}
    if account.get("status") == "missing":
        return None
    digest = canonical_sha256(account)
    source = str(account.get("source") or "unknown")
    authenticated_live = (
        account.get("status") == "available"
        and "live_private_read_only" in source
        and (account.get("private_adapter_contract") or {}).get("replay_fixture")
        is False
    )
    state = (
        EvidenceState.TRUSTED
        if authenticated_live
        else EvidenceState.UNTRUSTED
    )
    reason = str(account.get("reason_code") or "ACCOUNT_EVIDENCE_NOT_TRUSTED")
    return EvidenceRecord(
        evidence_id=f"account:{digest}",
        kind="account_snapshot",
        state=state,
        source=source,
        observed_at=evaluation_clock,
        received_at=evaluation_clock,
        expires_at=evaluation_clock,
        authenticated=authenticated_live,
        payload_ref=f"sha256:{digest}",
        payload_hash=digest,
        reason_codes=() if authenticated_live else (reason,),
    )


def _model_bundle_from_projection(
    projection: Mapping[str, Any],
) -> ModelBundleRef:
    # P2 owns ModelRegistry promotion. A legacy report claim is never enough
    # to promote a model into the P0 trusted graph.
    del projection
    return ModelBundleRef.unavailable()


def _market_analysis(
    projection: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any] | None,
    market_snapshot_id: str,
    market_evidence: EvidenceRecord,
) -> MarketAnalysis:
    data_status = projection.get("data_status") or {}
    feeds = (snapshot or {}).get("feeds") or {}
    index_spot = feeds.get("index_spot") or {}
    spot_amount = _optional_finite(index_spot.get("index_price"))
    if spot_amount is None:
        spot_amount = next(
            (
                value
                for row in (snapshot or {}).get("rows") or []
                if isinstance(row, Mapping)
                and (
                    value := _optional_finite(
                        ((row.get("summary") or {}).get("underlying_price"))
                    )
                )
                is not None
            ),
            None,
        )
    as_of = data_status.get("snapshot_captured_at")
    trusted = market_evidence.state is EvidenceState.TRUSTED
    spot = (
        EconomicValue(
            amount=spot_amount,
            currency="USD",
            kind="underlying_spot",
            product_type="underlying",
            contract_scale=1.0,
            as_of=str(as_of),
            provenance="market_snapshot:feeds.index_spot.index_price",
        )
        if trusted and spot_amount is not None and as_of
        else None
    )
    dvol = (
        _optional_finite((feeds.get("vol_index") or {}).get("volatility"))
        if trusted
        else None
    )
    reasons = _unique_codes(
        [
            *list((projection.get("data_trust") or {}).get("reason_codes") or []),
            *list(
                (data_status.get("quality_gate") or {}).get("reason_codes") or []
            ),
            *market_evidence.reason_codes,
        ]
    )
    return MarketAnalysis(
        market_snapshot_id=market_snapshot_id,
        status=(
            str(data_status.get("status") or "missing")
            if trusted
            else market_evidence.state.value
        ),
        as_of=str(as_of) if as_of else None,
        spot=spot,
        dvol_percent=dvol,
        surface_status=(
            str(
                (projection.get("vol_surface_status") or {}).get("status")
                or "missing"
            )
            if trusted
            else "not_trusted"
        ),
        reason_codes=tuple(reasons),
    )


def _opportunities_from_projection(
    projection: Mapping[str, Any],
    *,
    market_snapshot_id: str,
    market_evidence: EvidenceRecord,
    detected_at: str,
    evaluation_clock: str,
    policy: PolicyCatalog,
    model_bundle: ModelBundleRef,
) -> tuple[OpportunityRecord, ...]:
    candidates = projection.get("candidate_research") or {}
    rows: list[Mapping[str, Any]] = []
    # Candidate discovery already publishes all three defined-risk families.
    # The typed migration seam used to lift only call spreads, which silently
    # discarded bull-put spreads and iron condors before any hard gate could
    # evaluate them.  Naked rows intentionally remain outside this loop: they
    # are comparison evidence, never a user-card family.
    for section in (
        "call_credit_spreads",
        "put_credit_spreads",
        "iron_condors",
    ):
        group = candidates.get(section) or {}
        eligible = group.get("eligible") or []
        if isinstance(eligible, list):
            rows.extend(item for item in eligible if isinstance(item, Mapping))
    valid_until = _timestamp(
        _parse_timestamp(detected_at, field="opportunity_detected_at")
        + timedelta(seconds=policy.opportunity_ttl_seconds)
    )
    expired = _parse_timestamp(valid_until, field="valid_until") <= _parse_timestamp(
        evaluation_clock,
        field="evaluation_clock",
    )
    opportunities: list[OpportunityRecord] = []
    for candidate in sorted(rows, key=lambda item: str(item.get("candidate_id") or "")):
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        fair_interval = _fair_interval_from_candidate(
            candidate,
            as_of=market_evidence.observed_at or evaluation_clock,
        )
        apparent_edge = _typed_economic_mapping(
            candidate.get("analysis_apparent_edge"),
            default_as_of=market_evidence.observed_at or evaluation_clock,
        )
        uncertainty = _typed_economic_mapping(
            candidate.get("analysis_uncertainty"),
            default_as_of=market_evidence.observed_at or evaluation_clock,
        )
        reason_codes = [
            "E3_RISK_PREMIUM_SCREEN",
        ]
        if fair_interval is None:
            reason_codes.append("FAIR_INTERVAL_UNAVAILABLE")
        if apparent_edge is None:
            reason_codes.append("APPARENT_EDGE_NOT_ESTABLISHED")
        if candidate.get("analysis_invalidation_triggered") is True:
            status = OpportunityStatus.INVALIDATED
            reason_codes.append("OPPORTUNITY_INVALIDATED")
        elif expired:
            status = OpportunityStatus.EXPIRED
            reason_codes.append("OPPORTUNITY_EXPIRED")
        elif not model_bundle.promoted_for:
            status = OpportunityStatus.MODEL_BLOCKED
            reason_codes.append("E3_MODEL_NOT_PROMOTED")
        else:
            status = OpportunityStatus.DETECTED
        values = _candidate_market_values(
            candidate,
            as_of=market_evidence.observed_at or evaluation_clock,
        )
        identity = {
            "edge_class": EdgeClass.E3.value,
            "screening_ref": candidate_id,
            "market_snapshot_id": market_snapshot_id,
            "detector": "legacy-candidate-screen:v1",
            "detected_at": detected_at,
        }
        opportunities.append(
            OpportunityRecord(
                opportunity_id=f"opportunity:{canonical_sha256(identity)}",
                edge_class=EdgeClass.E3,
                detected_at=detected_at,
                valid_until=valid_until,
                market_snapshot_id=market_snapshot_id,
                detector_id="legacy-candidate-screen",
                detector_version="v1",
                model_id=model_bundle.model_bundle_id,
                model_status=model_bundle.promotion_status,
                fair_interval=fair_interval,
                observed_market_values=tuple(values),
                apparent_edge=apparent_edge,
                uncertainty=uncertainty,
                evidence_refs=(market_evidence.evidence_id,),
                reason_codes=tuple(_unique_codes(reason_codes)),
                invalidation_conditions=(
                    "market_snapshot_changes",
                    "candidate_screen_fails",
                    "evidence_expires",
                ),
                status=status,
                confidence_ceiling=(
                    "screening_only"
                    if not model_bundle.promoted_for
                    else "research_anomaly"
                ),
                source_candidate_id=candidate_id,
            )
        )
    return tuple(opportunities)


def _candidate_market_values(
    candidate: Mapping[str, Any],
    *,
    as_of: str,
) -> list[EconomicValue]:
    currency = str(candidate.get("premium_currency") or "UNKNOWN")
    scale = _optional_positive(candidate.get("contract_scale"))
    fields = (
        ("market_bid", "market_bid"),
        ("market_ask", "market_ask"),
        ("net_credit", "net_credit"),
        ("sell_leg_market_bid", "sell_leg_market_bid"),
        ("buy_leg_market_ask", "buy_leg_market_ask"),
    )
    result: list[EconomicValue] = []
    for field, kind in fields:
        amount = _optional_finite(candidate.get(field))
        if amount is None:
            continue
        result.append(
            EconomicValue(
                amount=amount,
                currency=currency,
                kind=kind,
                product_type="option",
                contract_scale=scale,
                as_of=as_of,
                provenance=f"legacy_projection:candidate_research.{field}",
            )
        )
    return result


def _typed_economic_mapping(
    value: Any,
    *,
    default_as_of: str,
) -> EconomicValue | None:
    if not isinstance(value, Mapping):
        return None
    amount = _optional_finite(value.get("amount"))
    dimensions = (
        value.get("currency"),
        value.get("kind"),
        value.get("product_type"),
        value.get("provenance"),
    )
    if amount is None or any(
        not isinstance(item, str) or not item for item in dimensions
    ):
        return None
    return EconomicValue(
        amount=amount,
        currency=str(value["currency"]),
        kind=str(value["kind"]),
        product_type=str(value["product_type"]),
        contract_scale=_optional_positive(value.get("contract_scale")),
        as_of=str(value.get("as_of") or default_as_of),
        provenance=str(value["provenance"]),
    )


def _fair_interval_from_candidate(
    candidate: Mapping[str, Any],
    *,
    as_of: str,
) -> tuple[EconomicValue, EconomicValue] | None:
    raw = candidate.get("analysis_fair_interval")
    if not isinstance(raw, Mapping):
        return None
    lower = _typed_economic_mapping(raw.get("lower"), default_as_of=as_of)
    upper = _typed_economic_mapping(raw.get("upper"), default_as_of=as_of)
    if lower is None or upper is None:
        return None
    if (
        lower.currency != upper.currency
        or lower.product_type != upper.product_type
        or lower.contract_scale != upper.contract_scale
        or lower.amount > upper.amount
    ):
        return None
    return lower, upper


def _strategies_from_opportunities(
    opportunities: tuple[OpportunityRecord, ...],
    *,
    projection: Mapping[str, Any],
    snapshot: Mapping[str, Any] | None,
    market_evidence: EvidenceRecord,
    evaluation_clock: str,
) -> tuple[StrategyPlan, ...]:
    candidate_lookup = _candidate_lookup(projection)
    row_lookup = {
        str(row.get("instrument_name")): row
        for row in (snapshot or {}).get("rows", [])
        if isinstance(row, Mapping)
    }
    plans: list[StrategyPlan] = []
    for opportunity in opportunities:
        candidate = candidate_lookup.get(opportunity.source_candidate_id)
        if not candidate:
            continue
        structure_type = str(candidate.get("structure_type") or "")
        structure = {
            # Preserve the v0.1 typed-domain spelling for compatibility.  The
            # strategy_brief projector maps it to the user contract's explicit
            # bearish direction name.
            "call_credit_spread": "CALL_CREDIT_SPREAD",
            "put_credit_spread": "BULL_PUT_CREDIT_SPREAD",
            "iron_condor": "IRON_CONDOR",
        }.get(structure_type)
        if structure is None:
            # Unknown and uncapped shapes must never be reinterpreted as one of
            # the three supported strategy families.
            continue
        leg_specs = _defined_risk_leg_specs(candidate)
        if not leg_specs:
            continue
        role = "primary_defined_risk_expression"
        unbounded = False
        legs = tuple(
            _strategy_leg(
                side=side,
                instrument_id=instrument,
                strike_value=strike,
                price_policy=price_policy,
                option_type=option_type,
                candidate=candidate,
                row=row_lookup.get(instrument),
                market_evidence=market_evidence,
                evaluation_clock=evaluation_clock,
            )
            for side, instrument, strike, price_policy, option_type in leg_specs
            if instrument and _optional_finite(strike) is not None
        )
        if not legs:
            continue
        net_premium = _economic_from_candidate(
            candidate,
            field=(
                "net_credit"
            ),
            kind="net_credit",
            as_of=market_evidence.observed_at or evaluation_clock,
        )
        spread_width = (
            _economic_from_candidate(
                candidate,
                field="spread_width",
                kind="strike_width",
                as_of=market_evidence.observed_at or evaluation_clock,
                currency="USD",
                contract_scale=1.0,
            )
            if structure in {
                "CALL_CREDIT_SPREAD",
                "BULL_PUT_CREDIT_SPREAD",
                "IRON_CONDOR",
            }
            else None
        )
        bid_ask_cost = _bid_ask_cost(
            legs,
            as_of=market_evidence.observed_at or evaluation_clock,
        )
        costs = _migration_cost_evidence(
            candidate,
            as_of=market_evidence.observed_at or evaluation_clock,
        )
        identity = {
            "opportunity_id": opportunity.opportunity_id,
            "structure": structure,
            "legs": [leg.to_dict() for leg in legs],
        }
        reasons = [
            "LEGACY_SCREEN_CONVERTED_TO_TYPED_STRATEGY",
            "PRODUCT_STYLE_OR_CONTRACT_SCALE_UNKNOWN"
            if any(not leg.product_economics.units_explicit for leg in legs)
            else "PRODUCT_ECONOMICS_EXPLICIT",
        ]
        greek_as_of = market_evidence.observed_at or evaluation_clock
        greek_units = {
            "delta": "model_coordinate_delta",
            "gamma": "model_coordinate_gamma_per_usd",
            "theta": "model_coordinate_quote_units_per_day",
            "vega": "model_coordinate_quote_units_per_vol_point",
        }
        greeks = tuple(
            GreekValue(
                name=name,
                amount=value,
                unit=greek_units[name],
                as_of=greek_as_of,
                provenance=(
                    "legacy_projection:option_surface."
                    f"{opportunity.source_candidate_id}.model_{name}"
                ),
            )
            for name in ("delta", "gamma", "theta", "vega")
            if (value := _optional_finite(candidate.get(f"model_{name}")))
            is not None
        )
        rejected_alternatives = (
            RejectedAlternative(
                structure="NAKED_SHORT_CALL",
                reason_codes=(
                    "UNBOUNDED_TAIL_LOSS",
                    "DEFINED_RISK_STRUCTURE_PREFERRED",
                ),
                why=(
                    "Uncapped short options remain comparison evidence only; "
                    "the purchased wings define the unit loss boundary."
                ),
            ),
        )
        why_this_structure = (
            "Every sold option is paired with a same-expiry protective wing, "
            "so terminal loss is bounded when product units are explicit."
        )
        why_now = (
            "Authenticated market evidence produced an observable E3 screen "
            f"at {market_evidence.observed_at or evaluation_clock}.",
            f"The opportunity remains valid only until {opportunity.valid_until}.",
        )
        (
            payoff_status,
            breakeven,
            max_profit,
            max_loss,
        ) = _aggregate_linear_payoff(
            structure=structure,
            legs=legs,
            net_premium=net_premium,
            spread_width=spread_width,
        )
        conservative_net_edge = costs.get("conservative_net_edge")
        edge_to_capital_at_risk = (
            conservative_net_edge.amount / max_loss.amount
            if conservative_net_edge is not None
            and max_loss is not None
            and max_loss.amount > 0
            and _economic_dimensions_consistent(
                (conservative_net_edge, max_loss)
            )
            else None
        )
        plans.append(
            StrategyPlan(
                strategy_id=f"strategy:{canonical_sha256(identity)}",
                opportunity_id=opportunity.opportunity_id,
                structure=structure,
                selection_role=role,
                legs=legs,
                payoff_status=payoff_status,
                breakeven=breakeven,
                max_profit=max_profit,
                max_loss=max_loss,
                unbounded_loss=unbounded,
                spread_width=spread_width,
                net_premium=net_premium,
                bid_ask_cost=bid_ask_cost,
                fee=costs.get("fee"),
                slippage_reserve=costs.get("slippage_reserve"),
                depth_impact=costs.get("depth_impact"),
                legging_reserve=costs.get("legging_reserve"),
                hedge_reserve=costs.get("hedge_reserve"),
                model_uncertainty_reserve=costs.get(
                    "model_uncertainty_reserve"
                ),
                exit_liquidity_proxy="not_evaluated",
                research_capacity_class=(
                    str(candidate.get("analysis_capacity_class"))
                    if candidate.get("analysis_capacity_class")
                    else None
                ),
                conservative_net_edge=conservative_net_edge,
                capital_at_risk_proxy=max_loss,
                edge_to_capital_at_risk=edge_to_capital_at_risk,
                greeks=greeks,
                why=(
                    "The observable screen produced a typed, defined-risk "
                    "multi-leg candidate.",
                    (
                        "This remains research evidence, not a recommendation or "
                        "execution instruction."
                    ),
                ),
                why_now=why_now,
                why_this_structure=why_this_structure,
                rejected_alternatives=rejected_alternatives,
                invalidation_rules=opportunity.invalidation_conditions,
                observable_next_step=(
                    "Observe whether promoted model evidence and every pre-entry "
                    "condition become simultaneously current before TTL expiry."
                ),
                reason_codes=tuple(reasons),
            )
        )
    return tuple(plans)


def _defined_risk_leg_specs(
    candidate: Mapping[str, Any],
) -> tuple[tuple[str, str, Any, str, str], ...]:
    """Return exact executable leg grammar from the canonical signed legs."""

    raw_legs = candidate.get("structure_legs")
    if not isinstance(raw_legs, list):
        return ()
    specs: list[tuple[str, str, Any, str, str]] = []
    for raw in raw_legs:
        if not isinstance(raw, Mapping):
            return ()
        quantity = _optional_finite(raw.get("quantity"))
        instrument = str(raw.get("instrument_name") or "")
        option_type = str(raw.get("option_type") or "")
        if (
            quantity is None
            or quantity == 0
            or not instrument
            or option_type not in {"call", "put"}
        ):
            return ()
        side = "BUY" if quantity > 0 else "SELL"
        specs.append(
            (
                side,
                instrument,
                raw.get("strike"),
                "buy_ask" if side == "BUY" else "sell_bid",
                option_type,
            )
        )
    if len(specs) not in {2, 4}:
        return ()
    return tuple(specs)


def _aggregate_linear_payoff(
    *,
    structure: str,
    legs: tuple[StrategyLeg, ...],
    net_premium: EconomicValue | None,
    spread_width: EconomicValue | None,
) -> tuple[
    str,
    EconomicValue | None,
    EconomicValue | None,
    EconomicValue | None,
]:
    if (
        net_premium is None
        or net_premium.amount < 0
        or any(
            leg.product_economics.product_style != "linear"
            or not leg.product_economics.units_explicit
            for leg in legs
        )
    ):
        return "unresolved_product_economics", None, None, None
    if any(leg.strike.currency != net_premium.currency for leg in legs):
        return "unresolved_product_economics", None, None, None

    scale = net_premium.contract_scale
    if scale is None:
        return "unresolved_product_economics", None, None, None
    structure_type = {
        "CALL_CREDIT_SPREAD": "call_credit_spread",
        "BULL_PUT_CREDIT_SPREAD": "put_credit_spread",
        "IRON_CONDOR": "iron_condor",
    }.get(structure)
    if structure_type is None:
        return "unresolved_product_economics", None, None, None
    try:
        typed_structure = build_structure(
            structure_type=structure_type,
            contract_size=scale,
            legs=[
                {
                    "option_type": leg.option_type,
                    "strike": leg.strike.amount,
                    "quantity": (
                        leg.quantity_ratio if leg.side == "BUY" else -leg.quantity_ratio
                    ),
                    "expiry_date": leg.expiry,
                    "instrument_name": leg.instrument_id,
                }
                for leg in legs
            ],
        )
        profile = typed_structure.risk_profile(
            entry_cash=net_premium.amount * scale
        )
    except ValueError:
        return "unresolved_product_economics", None, None, None
    if not profile.loss_is_bounded or profile.max_loss is None:
        return "resolved_linear_unbounded", None, None, None

    def derived(amount: float, kind: str) -> EconomicValue:
        return EconomicValue(
            amount=amount,
            currency=net_premium.currency,
            kind=kind,
            product_type=net_premium.product_type,
            contract_scale=net_premium.contract_scale,
            as_of=net_premium.as_of,
            provenance="typed_strategy_legs:linear_payoff_aggregation",
        )

    breakeven = (
        derived(profile.breakevens[0], "breakeven")
        if profile.breakevens
        else None
    )
    max_profit = (
        derived(profile.max_profit, "max_profit")
        if profile.max_profit is not None
        else None
    )
    max_loss = derived(profile.max_loss, "max_loss")
    return "resolved_linear_defined_risk", breakeven, max_profit, max_loss


def _classify_opportunity_economics(
    opportunities: tuple[OpportunityRecord, ...],
    strategies: tuple[StrategyPlan, ...],
    *,
    policy: PolicyCatalog,
) -> tuple[OpportunityRecord, ...]:
    by_opportunity = {plan.opportunity_id: plan for plan in strategies}
    result: list[OpportunityRecord] = []
    for opportunity in opportunities:
        if opportunity.status in {
            OpportunityStatus.EXPIRED,
            OpportunityStatus.INVALIDATED,
            OpportunityStatus.MODEL_BLOCKED,
        }:
            result.append(opportunity)
            continue
        plan = by_opportunity.get(opportunity.opportunity_id)
        if plan is None or opportunity.fair_interval is None:
            result.append(
                replace(
                    opportunity,
                    status=OpportunityStatus.COST_BLOCKED,
                    reason_codes=tuple(
                        _unique_codes(
                            [
                                *opportunity.reason_codes,
                                "EXECUTABLE_COST_EVIDENCE_INCOMPLETE",
                            ]
                        )
                    ),
                )
            )
            continue
        costs = (
            plan.bid_ask_cost,
            plan.fee,
            plan.slippage_reserve,
            plan.depth_impact,
            plan.legging_reserve,
            plan.hedge_reserve,
            plan.model_uncertainty_reserve,
        )
        edge = plan.conservative_net_edge
        dimensions_known = all(
            item is not None and item.contract_scale is not None
            for item in (*costs, edge)
        )
        dimensions_consistent = _economic_dimensions_consistent(
            (*costs, edge)
        )
        costs_nonnegative = all(
            item is not None and item.amount >= 0 for item in costs
        )
        known = (
            all(item is not None for item in costs)
            and edge is not None
            and dimensions_consistent
            and costs_nonnegative
        )
        total_cost = (
            sum(float(item.amount) for item in costs if item is not None)
            if known
            else None
        )
        covered = (
            known
            and edge is not None
            and total_cost is not None
            and edge.amount > 0
            and edge.amount >= total_cost * policy.cost_coverage_ratio
        )
        if covered:
            result.append(
                replace(
                    opportunity,
                    status=OpportunityStatus.DETECTED,
                    reason_codes=tuple(
                        code
                        for code in opportunity.reason_codes
                        if code != "EXECUTABLE_COST_EVIDENCE_INCOMPLETE"
                    )
                    + ("EXECUTABLE_COST_EVIDENCE_PASSED",),
                )
            )
        else:
            result.append(
                replace(
                    opportunity,
                    status=OpportunityStatus.COST_BLOCKED,
                    reason_codes=tuple(
                        _unique_codes(
                            [
                                *opportunity.reason_codes,
                                (
                                    "COST_COVERAGE_FAILED"
                                    if known
                                    else "ECONOMIC_DIMENSIONS_MISMATCH"
                                    if dimensions_known
                                    and not dimensions_consistent
                                    else "ECONOMIC_COST_INVALID"
                                    if dimensions_known
                                    and dimensions_consistent
                                    and not costs_nonnegative
                                    else "EXECUTABLE_COST_EVIDENCE_INCOMPLETE"
                                ),
                            ]
                        )
                    ),
                )
            )
    return tuple(result)


def _economic_dimensions_consistent(
    values: Iterable[EconomicValue | None],
) -> bool:
    items = tuple(values)
    if not items or any(item is None for item in items):
        return False
    typed = tuple(item for item in items if item is not None)
    first = typed[0]
    if first.contract_scale is None:
        return False
    return all(
        item.currency == first.currency
        and item.product_type == first.product_type
        and item.contract_scale == first.contract_scale
        for item in typed[1:]
    )


def _candidate_lookup(
    projection: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    candidates = projection.get("candidate_research") or {}
    for section in (
        "call_credit_spreads",
        "put_credit_spreads",
        "iron_condors",
        "naked_short_calls",
    ):
        group = candidates.get(section) or {}
        for bucket in ("eligible", "review", "rejected"):
            for candidate in group.get(bucket) or []:
                if isinstance(candidate, Mapping) and candidate.get("candidate_id"):
                    result[str(candidate["candidate_id"])] = candidate
    return result


def _strategy_brief_candidates(
    record: AnalysisRecord,
    projection: Mapping[str, Any],
) -> list[dict[str, Any]]:
    ranked = (projection.get("ev_candidate_scanner") or {}).get("ranked_candidates") or []
    supported = {"call_credit_spread", "put_credit_spread", "iron_condor"}
    candidate_lookup = _candidate_lookup(projection)
    opportunities = {
        item.source_candidate_id: item for item in record.opportunities
    }
    plan_by_opportunity = {item.opportunity_id: item for item in record.strategy_plans}
    candidates: list[dict[str, Any]] = []
    for raw in ranked:
        if not isinstance(raw, Mapping):
            continue
        structure_type = str(raw.get("structure_type") or "")
        if structure_type not in supported:
            continue
        candidate_id = str(raw.get("candidate_id") or "")
        base_candidate = candidate_lookup.get(candidate_id) or {}
        candidate = {**dict(base_candidate), **dict(raw)}
        source_candidate = dict(candidate)
        opportunity = opportunities.get(candidate_id)
        plan = (
            plan_by_opportunity.get(opportunity.opportunity_id)
            if opportunity is not None
            else None
        )
        exact_legs = _strategy_brief_exact_legs(plan)
        if exact_legs and _strategy_brief_latest_observed_at(exact_legs) is None:
            exact_legs = []
        if not exact_legs:
            exact_legs = _strategy_brief_candidate_legs(
                candidate=source_candidate,
                candidate_lookup=candidate_lookup,
            )
        observed_at = _strategy_brief_latest_observed_at(exact_legs)
        if exact_legs and observed_at is not None:
            candidate["structure_legs"] = exact_legs
            candidate["observed_at"] = observed_at
        elif _strategy_brief_existing_legs_missing_observed_at(candidate):
            candidate.pop("structure_legs", None)
            candidate.pop("observed_at", None)
        if opportunity is not None:
            candidate["valid_until"] = opportunity.valid_until
            candidate["kill_conditions"] = list(opportunity.invalidation_conditions)
            candidate["primary_reason_codes"] = list(opportunity.reason_codes)[:2]
        candidate.setdefault(
            "settlement_currency",
            _strategy_brief_settlement_currency(candidate, plan),
        )
        candidate.setdefault("currency", candidate.get("settlement_currency"))
        candidate.setdefault(
            "premium_currency",
            _strategy_brief_premium_currency(candidate, plan),
        )
        if candidate.get("ev_after_cost") is None and candidate.get("ev_after_cost_usdc") is not None:
            candidate["ev_after_cost"] = candidate.get("ev_after_cost_usdc")
        candidate.setdefault(
            "cost_components_complete",
            _strategy_brief_cost_components_complete(candidate, plan),
        )
        candidate.setdefault(
            "relative_value_status",
            "AVAILABLE" if candidate.get("ranking_score") is not None else "UNAVAILABLE",
        )
        candidates.append(candidate)
    return candidates


def _strategy_brief_candidate_legs(
    *,
    candidate: Mapping[str, Any],
    candidate_lookup: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    structure_type = str(candidate.get("structure_type") or "")
    if structure_type in {"call_credit_spread", "put_credit_spread"}:
        return _strategy_brief_vertical_legs(candidate)
    if structure_type != "iron_condor":
        return []
    put_spread = candidate_lookup.get(str(candidate.get("put_spread_id") or ""))
    call_spread = candidate_lookup.get(str(candidate.get("call_spread_id") or ""))
    if put_spread is None or call_spread is None:
        return []
    return [
        *_strategy_brief_vertical_legs(put_spread),
        *_strategy_brief_vertical_legs(call_spread),
    ]


def _strategy_brief_vertical_legs(
    candidate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    premium_unit = candidate.get("premium_unit")
    premium_currency = candidate.get("premium_currency")
    expiry_date = str(candidate.get("expiry_date") or "")
    option_type = str(candidate.get("option_type") or "")
    quoted_legs = []
    for side_name, quantity in (("sell", -1.0), ("buy", 1.0)):
        instrument_name = candidate.get(f"{side_name}_leg_instrument_name")
        strike = candidate.get(f"{side_name}_leg_strike_price")
        bid = candidate.get(f"{side_name}_leg_market_bid")
        ask = candidate.get(f"{side_name}_leg_market_ask")
        observed_at = _strategy_brief_leg_observed_at(
            candidate,
            side_name=side_name,
            instrument_name=instrument_name,
        )
        if (
            not instrument_name
            or strike is None
            or bid is None
            or ask is None
            or observed_at is None
        ):
            return []
        quoted_legs.append(
            {
                "instrument_name": instrument_name,
                "option_type": option_type,
                "strike": strike,
                "quantity": quantity,
                "market_bid": bid,
                "market_ask": ask,
                "observed_at": observed_at,
                "expiry_date": expiry_date,
                "premium_unit": premium_unit,
                "premium_currency": premium_currency,
            }
        )
    return quoted_legs


def _strategy_brief_leg_observed_at(
    candidate: Mapping[str, Any],
    *,
    side_name: str,
    instrument_name: Any,
) -> str | None:
    for leg in candidate.get("structure_legs") or ():
        if not isinstance(leg, Mapping):
            continue
        if leg.get("instrument_name") != instrument_name:
            continue
        observed_at = leg.get("observed_at")
        if isinstance(observed_at, str) and observed_at.strip():
            return observed_at
        return None
    observed_at = candidate.get(f"{side_name}_leg_observed_at")
    if isinstance(observed_at, str) and observed_at.strip():
        return observed_at
    return None


def _strategy_brief_latest_observed_at(
    legs: list[Mapping[str, Any]],
) -> str | None:
    if not legs:
        return None
    timestamps: list[datetime] = []
    for leg in legs:
        observed_at = leg.get("observed_at")
        if not isinstance(observed_at, str) or not observed_at.strip():
            return None
        try:
            timestamps.append(
                _parse_timestamp(observed_at, field="strategy brief leg observed_at")
            )
        except ValueError:
            return None
    return _timestamp(max(timestamps))


def _strategy_brief_existing_legs_missing_observed_at(
    candidate: Mapping[str, Any],
) -> bool:
    raw_legs = candidate.get("structure_legs")
    if not isinstance(raw_legs, list) or not raw_legs:
        return False
    return _strategy_brief_latest_observed_at(raw_legs) is None


def _strategy_brief_exact_legs(
    plan: StrategyPlan | None,
) -> list[dict[str, Any]]:
    if plan is None:
        return []
    legs: list[dict[str, Any]] = []
    for leg in plan.legs:
        bid = leg.source_quote.bid
        ask = leg.source_quote.ask
        if bid is None or ask is None:
            return []
        premium_unit = leg.product_economics.premium_unit
        if not isinstance(premium_unit, str) or not premium_unit:
            return []
        legs.append(
            {
                "instrument_name": leg.instrument_id,
                "option_type": leg.option_type,
                "strike": leg.strike.amount,
                "quantity": leg.quantity_ratio if leg.side == "BUY" else -leg.quantity_ratio,
                "market_bid": bid.amount,
                "market_ask": ask.amount,
                "observed_at": leg.source_quote.observed_at,
                "expiry_date": leg.expiry,
                "premium_unit": premium_unit,
                "premium_currency": bid.currency,
            }
        )
    return legs


def _strategy_brief_settlement_currency(
    candidate: Mapping[str, Any],
    plan: StrategyPlan | None,
) -> str | None:
    values = [
        candidate.get("settlement_currency"),
        candidate.get("risk_currency"),
        candidate.get("currency"),
        candidate.get("premium_currency"),
        plan.net_premium.currency if plan and plan.net_premium is not None else None,
        (
            plan.legs[0].source_quote.bid.currency
            if plan and plan.legs and plan.legs[0].source_quote.bid is not None
            else None
        ),
    ]
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def _strategy_brief_premium_currency(
    candidate: Mapping[str, Any],
    plan: StrategyPlan | None,
) -> str | None:
    values = [
        candidate.get("premium_currency"),
        candidate.get("settlement_currency"),
        plan.net_premium.currency if plan and plan.net_premium is not None else None,
        (
            plan.legs[0].source_quote.bid.currency
            if plan and plan.legs and plan.legs[0].source_quote.bid is not None
            else None
        ),
    ]
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def _strategy_brief_cost_components_complete(
    candidate: Mapping[str, Any],
    plan: StrategyPlan | None,
) -> bool:
    if candidate.get("cost_components_complete") is True:
        return True
    if candidate.get("fees_included") is True and candidate.get("slippage_included") is True:
        return bool(
            candidate.get("legging_included") is True
            and candidate.get("settlement_included") is True
        )
    return bool(
        plan is not None
        and plan.bid_ask_cost is not None
        and plan.fee is not None
        and plan.slippage_reserve is not None
        and plan.legging_reserve is not None
    )


def _strategy_brief_market(
    record: AnalysisRecord,
    projection: Mapping[str, Any],
    *,
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    as_of = (
        record.market_analysis.as_of
        or str(projection.get("generated_at") or record.manifest.evaluation_clock)
    )
    as_of_dt = _parse_timestamp(as_of, field="strategy brief market as_of")
    expires_at = _timestamp(
        as_of_dt
        + timedelta(seconds=record.policy_bundle.catalog.market_snapshot_max_age_seconds)
    )
    data_status = projection.get("data_status") or {}
    permission_state = projection.get("permission_state") or {}
    market_trusted = (
        record.trust_verdict == EvidenceState.TRUSTED.value
        and str(data_status.get("status") or "") == "validated"
    )
    return {
        "as_of": as_of,
        "expires_at": expires_at,
        "direction": (
            _strategy_brief_direction(permission_state) if market_trusted else "UNCLEAR"
        ),
        "volatility": (
            _strategy_brief_volatility(permission_state) if market_trusted else "UNKNOWN"
        ),
        "liquidity": _strategy_brief_liquidity(
            record,
            data_status=data_status,
            surface_status=projection.get("vol_surface_status") or {},
        ),
        "confidence": _strategy_brief_confidence(
            record,
            permission_state=permission_state,
            market_trusted=market_trusted,
        ),
    }


def _strategy_brief_direction(permission_state: Mapping[str, Any]) -> str:
    regime = str(
        permission_state.get("primary_regime_label") or ""
    ).strip()
    return {
        "Bear Trend": "BEARISH",
        "Range": "RANGE",
        "Slow Bull": "BULLISH",
        "Fast Bull Breakout": "BULLISH",
    }.get(regime, "UNCLEAR")


def _strategy_brief_volatility(permission_state: Mapping[str, Any]) -> str:
    volatility_inputs = permission_state.get("volatility_inputs") or {}
    dvol_percentile = _optional_finite(volatility_inputs.get("dvol_percentile"))
    atm_percentile = _optional_finite(volatility_inputs.get("atm_iv_percentile"))
    percentile = max(
        value for value in (dvol_percentile, atm_percentile) if value is not None
    ) if any(value is not None for value in (dvol_percentile, atm_percentile)) else None
    if percentile is None:
        return "UNKNOWN"
    if percentile >= 0.70:
        return "RICH"
    if percentile <= 0.30:
        return "CHEAP"
    return "FAIR"


def _strategy_brief_liquidity(
    record: AnalysisRecord,
    *,
    data_status: Mapping[str, Any],
    surface_status: Mapping[str, Any],
) -> str:
    if record.trust_verdict != EvidenceState.TRUSTED.value:
        return "UNAVAILABLE"
    if str(data_status.get("status") or "") != "validated":
        return "UNAVAILABLE"
    if str(surface_status.get("status") or "") == "validated":
        return "EXECUTABLE"
    return "LIMITED"


def _strategy_brief_confidence(
    record: AnalysisRecord,
    *,
    permission_state: Mapping[str, Any],
    market_trusted: bool,
) -> str:
    if not market_trusted:
        return "UNAVAILABLE"
    return (
        "HIGH"
        if str(permission_state.get("status") or "") == "validated"
        else "MEDIUM"
    )


def _normalize_strategy_history_artifacts(
    artifacts: Iterable[Mapping[str, Any]],
) -> str:
    normalized: list[dict[str, Any]] = []
    structures: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping):
            raise ValueError("strategy history artifacts must be mappings")
        artifact = json.loads(_canonical_json(dict(raw)))
        errors = validate_strategy_history_artifact(artifact)
        if errors:
            raise ValueError("invalid strategy history artifact: " + "; ".join(errors))
        structure_type = str(artifact.get("structure_type") or "")
        if structure_type in structures:
            raise ValueError(
                "strategy history artifacts must contain at most one artifact per structure"
            )
        structures.add(structure_type)
        normalized.append(artifact)
    normalized.sort(key=lambda item: str(item.get("artifact_id") or ""))
    return _canonical_json(normalized)


def _strategy_history_artifacts_from_json(value: str) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("strategy history artifact payload must be canonical JSON") from exc
    if not isinstance(payload, list):
        raise ValueError("strategy history artifact payload must be a list")
    normalized = _normalize_strategy_history_artifacts(payload)
    if normalized != value:
        raise ValueError("strategy history artifact payload must use canonical ordering")
    return tuple(json.loads(normalized))


def _normalize_strategy_forecast_runtime_evidence(
    evidence_items: Iterable[Mapping[str, Any]],
) -> str:
    normalized: list[dict[str, Any]] = []
    identities: set[str] = set()
    for raw in evidence_items:
        if not isinstance(raw, Mapping):
            raise ValueError("strategy forecast runtime evidence must be mappings")
        evidence = json.loads(_canonical_json(dict(raw)))
        errors = validate_strategy_forecast_runtime_evidence(evidence)
        if errors:
            raise ValueError(
                "invalid strategy forecast runtime evidence: " + "; ".join(errors)
            )
        artifact = evidence["artifact"]
        selection_binding_key = artifact.get("selection_binding_key")
        if isinstance(selection_binding_key, str) and selection_binding_key:
            identity_key = f"selection:{selection_binding_key}"
        else:
            identity_key = (
                "legacy:"
                + _canonical_json(
                    _strategy_brief_forecast_public_scope_from_scope(artifact.get("scope"))
                )
            )
        if identity_key in identities:
            raise ValueError(
                "strategy forecast runtime evidence must contain at most one artifact per exact selection"
            )
        identities.add(identity_key)
        normalized.append(evidence)
    normalized.sort(
        key=lambda item: str((item.get("artifact") or {}).get("artifact_id") or "")
    )
    return _canonical_json(normalized)


def _strategy_forecast_runtime_evidence_from_json(
    value: str,
) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "strategy forecast runtime evidence payload must be canonical JSON"
        ) from exc
    if not isinstance(payload, list):
        raise ValueError("strategy forecast runtime evidence payload must be a list")
    normalized = _normalize_strategy_forecast_runtime_evidence(payload)
    if normalized != value:
        raise ValueError(
            "strategy forecast runtime evidence payload must use canonical ordering"
        )
    return tuple(json.loads(normalized))


def _strategy_brief_history_by_candidate(
    *,
    generated_at: str,
    candidates: Iterable[Mapping[str, Any]],
    artifacts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    artifacts_by_structure = {
        str(artifact.get("structure_type") or ""): dict(artifact)
        for artifact in artifacts
    }
    summaries_by_structure: dict[str, dict[str, Any]] = {}
    by_candidate: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        structure_type = {
            "call_credit_spread": "BEAR_CALL_CREDIT_SPREAD",
            "put_credit_spread": "BULL_PUT_CREDIT_SPREAD",
            "iron_condor": "IRON_CONDOR",
        }.get(str(candidate.get("structure_type") or ""))
        if not candidate_id or structure_type is None:
            continue
        summary = summaries_by_structure.get(structure_type)
        if summary is None:
            artifact = artifacts_by_structure.get(structure_type)
            if artifact is None:
                artifact = build_strategy_history_artifact(
                    structure_type=structure_type,
                    generated_at=generated_at,
                    cohort_ledger=[],
                    holdout_status="pending",
                )
            summary = project_strategy_history_summary(artifact)
            summary = {
                **summary,
                "underlying": "BTC",
                "structure_type": structure_type,
                "direction": {
                    "BEAR_CALL_CREDIT_SPREAD": "BEARISH",
                    "BULL_PUT_CREDIT_SPREAD": "BULLISH",
                    "IRON_CONDOR": "RANGE",
                }[structure_type],
            }
            summaries_by_structure[structure_type] = summary
        by_candidate[candidate_id] = dict(summary)
    return by_candidate


def _strategy_brief_forecast_by_candidate(
    *,
    generated_at: str,
    candidates: Iterable[Mapping[str, Any]],
    runtime_evidence: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    evidence_by_selection: dict[str, dict[str, Any]] = {}
    evidence_by_public_scope: dict[str, list[dict[str, Any]]] = {}
    for item in runtime_evidence:
        artifact = item.get("artifact") or {}
        public_scope_key = _canonical_json(
            _strategy_brief_forecast_public_scope_from_scope(artifact.get("scope"))
        )
        evidence_by_public_scope.setdefault(public_scope_key, []).append(dict(item))
        selection_binding_key = artifact.get("selection_binding_key")
        if isinstance(selection_binding_key, str) and selection_binding_key:
            evidence_by_selection[selection_binding_key] = dict(item)
            continue
    by_candidate: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        scope = _strategy_brief_forecast_scope(candidate)
        public_scope_key = _canonical_json(
            _strategy_brief_forecast_public_scope(candidate)
        )
        selection_binding_key = selection_binding_key_from_scope(scope)
        evidence = (
            evidence_by_selection.get(selection_binding_key)
            if selection_binding_key is not None
            else None
        )
        if evidence is None:
            scoped_matches = evidence_by_public_scope.get(public_scope_key, [])
            if len(scoped_matches) == 1:
                evidence = scoped_matches[0]
        artifact = evidence.get("artifact") if evidence is not None else None
        projection = project_strategy_forecast(
            as_of=generated_at,
            scope=scope,
            artifact=artifact,
            current_input_fingerprint=(
                evidence.get("current_input_fingerprint")
                if evidence is not None
                else None
            ),
            current_lineage=(
                evidence.get("current_lineage") if evidence is not None else None
            ),
            current_oos_monitor=(
                evidence.get("current_oos_monitor") if evidence is not None else None
            ),
        )
        by_candidate[candidate_id] = {
            "status": projection["status"],
            "win_rate_low": projection["win_rate_low"],
            "win_rate_high": projection["win_rate_high"],
            "confidence": projection["confidence"],
            "scope": projection["scope"] if projection["status"] == "CALIBRATED" else None,
            "artifact_id": projection["artifact_id"],
            "reason_codes": list(projection["reason_codes"]),
            "selection_binding_key": (
                selection_binding_key if projection["status"] == "CALIBRATED" else None
            ),
        }
    return by_candidate


def _strategy_brief_forecast_scope(candidate: Mapping[str, Any]) -> dict[str, Any]:
    structure_type = {
        "call_credit_spread": "BEAR_CALL_CREDIT_SPREAD",
        "put_credit_spread": "BULL_PUT_CREDIT_SPREAD",
        "iron_condor": "IRON_CONDOR",
    }.get(str(candidate.get("structure_type") or ""), "UNKNOWN")
    direction = {
        "BEAR_CALL_CREDIT_SPREAD": "BEARISH",
        "BULL_PUT_CREDIT_SPREAD": "BULLISH",
        "IRON_CONDOR": "RANGE",
    }.get(structure_type, "UNCLEAR")
    scope = {
        "underlying": "BTC",
        "structure": structure_type,
        "direction": direction,
        "dte": {"min": 7, "max": 35},
        "entry_cost_basis": "quoted_bid_ask_plus_adverse_tick_and_fees",
        "exit_basis": "hold_to_expiry_cash_settlement",
    }
    selection = _strategy_brief_forecast_selection(candidate)
    if selection is not None:
        scope["selection"] = selection
    return scope


def _strategy_brief_forecast_public_scope(candidate: Mapping[str, Any]) -> dict[str, Any]:
    scope = _strategy_brief_forecast_scope(candidate)
    scope.pop("selection", None)
    return scope


def _strategy_brief_forecast_public_scope_from_scope(scope: Any) -> dict[str, Any]:
    if not isinstance(scope, Mapping):
        return {}
    return {
        key: value
        for key, value in dict(scope).items()
        if key != "selection"
    }


def _strategy_brief_forecast_selection(
    candidate: Mapping[str, Any],
) -> dict[str, Any] | None:
    legs = candidate.get("structure_legs")
    if not isinstance(legs, list) or not legs:
        return None
    expiry_date = candidate.get("expiry_date")
    if not isinstance(expiry_date, str) or not expiry_date:
        expiry_values = {
            str(leg.get("expiry_date"))
            for leg in legs
            if isinstance(leg, Mapping) and isinstance(leg.get("expiry_date"), str)
        }
        if len(expiry_values) != 1:
            return None
        expiry_date = next(iter(expiry_values))
    normalized_legs: list[dict[str, Any]] = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            return None
        instrument_name = leg.get("instrument_name")
        option_type = leg.get("option_type")
        strike = leg.get("strike")
        quantity = leg.get("quantity")
        if (
            not isinstance(instrument_name, str)
            or not instrument_name
            or not isinstance(option_type, str)
            or not option_type
        ):
            return None
        try:
            normalized_legs.append(
                {
                    "instrument_name": instrument_name,
                    "option_type": option_type.upper(),
                    "strike": float(strike),
                    "quantity": float(quantity),
                }
            )
        except (TypeError, ValueError):
            return None
    return {
        "expiry_date": expiry_date,
        "legs": normalized_legs,
    }


def _strategy_leg(
    *,
    side: str,
    instrument_id: str,
    strike_value: Any,
    price_policy: str,
    option_type: str,
    candidate: Mapping[str, Any],
    row: Mapping[str, Any] | None,
    market_evidence: EvidenceRecord,
    evaluation_clock: str,
) -> StrategyLeg:
    summary = (row or {}).get("summary") or {}
    ticker = (row or {}).get("ticker") or {}
    base = summary.get("base_currency")
    quote = summary.get("quote_currency")
    settlement = candidate.get("settlement_currency") or summary.get(
        "settlement_currency"
    )
    premium_unit = candidate.get("premium_unit")
    product_style = candidate.get("product_style") or summary.get("product_style")
    contract_scale = _optional_positive(
        candidate.get("contract_scale", summary.get("contract_size"))
    )
    economics = ProductEconomics(
        product_type="option",
        product_style=(
            str(product_style).lower()
            if str(product_style).lower() in {"inverse", "linear"}
            else "unknown"
        ),
        base_currency=str(base) if base else None,
        quote_currency=str(quote) if quote else None,
        settlement_currency=str(settlement) if settlement else None,
        premium_unit=str(premium_unit) if premium_unit else None,
        contract_scale=contract_scale,
        provenance="venue_explicit_fields_or_unknown",
    )
    timestamp_ms = ticker.get("timestamp", summary.get("creation_timestamp"))
    observed_at = _timestamp_from_ms(timestamp_ms)
    quote_age = (
        max(
            0.0,
            (
                _parse_timestamp(evaluation_clock, field="evaluation_clock")
                - _parse_timestamp(observed_at, field="quote observed_at")
            ).total_seconds(),
        )
        if observed_at
        else None
    )
    currency = str(candidate.get("premium_currency") or quote or "UNKNOWN")
    bid_amount = _optional_finite(ticker.get("best_bid_price", summary.get("bid_price")))
    ask_amount = _optional_finite(ticker.get("best_ask_price", summary.get("ask_price")))
    value_as_of = observed_at or market_evidence.observed_at or evaluation_clock

    def quote_value(amount: float | None, kind: str) -> EconomicValue | None:
        if amount is None:
            return None
        return EconomicValue(
            amount=amount,
            currency=currency,
            kind=kind,
            product_type="option",
            contract_scale=contract_scale,
            as_of=value_as_of,
            provenance=f"market_snapshot:{instrument_id}",
        )

    bid = quote_value(bid_amount, "bid_premium")
    ask = quote_value(ask_amount, "ask_premium")
    premium = bid if side == "SELL" else ask
    depth = _optional_finite(
        (_optional_finite(ticker.get("best_bid_amount")) or 0.0)
        + (_optional_finite(ticker.get("best_ask_amount")) or 0.0)
    )
    open_interest = _optional_finite(
        ticker.get("open_interest", summary.get("open_interest"))
    )
    spread_ratio = None
    if (
        bid_amount is not None
        and ask_amount is not None
        and ask_amount >= bid_amount
        and bid_amount + ask_amount > 0
    ):
        spread_ratio = (ask_amount - bid_amount) / ((ask_amount + bid_amount) / 2)
    quote_ref = f"{market_evidence.evidence_id}:{instrument_id}"
    return StrategyLeg(
        side=side,
        quantity_ratio=1.0,
        instrument_id=instrument_id,
        option_type=option_type,
        strike=EconomicValue(
            amount=float(strike_value),
            currency=str(quote or "USD"),
            kind="strike_price",
            product_type="option",
            contract_scale=1.0,
            as_of=value_as_of,
            provenance=f"instrument_identity:{instrument_id}",
        ),
        expiry=str(candidate.get("expiry_date")),
        product_economics=economics,
        premium_coordinate=premium,
        entry_price_policy=price_policy,
        source_quote=QuoteEvidence(
            evidence_ref=quote_ref,
            observed_at=observed_at,
            quote_age_seconds=quote_age,
            bid=bid,
            ask=ask,
            depth=depth,
            open_interest=open_interest,
            spread_ratio=spread_ratio,
        ),
        liquidity_evidence_ref=quote_ref,
    )


def _economic_from_candidate(
    candidate: Mapping[str, Any],
    *,
    field: str,
    kind: str,
    as_of: str,
    currency: str | None = None,
    contract_scale: float | None = None,
) -> EconomicValue | None:
    amount = _optional_finite(candidate.get(field))
    if amount is None:
        return None
    return EconomicValue(
        amount=amount,
        currency=currency or str(candidate.get("premium_currency") or "UNKNOWN"),
        kind=kind,
        product_type="option",
        contract_scale=(
            contract_scale
            if contract_scale is not None
            else _optional_positive(candidate.get("contract_scale"))
        ),
        as_of=as_of,
        provenance=f"legacy_projection:candidate_research.{field}",
    )


def _bid_ask_cost(
    legs: tuple[StrategyLeg, ...],
    *,
    as_of: str,
) -> EconomicValue | None:
    spreads: list[float] = []
    currency: str | None = None
    scale: float | None = None
    for leg in legs:
        bid = leg.source_quote.bid
        ask = leg.source_quote.ask
        if bid is None or ask is None or bid.currency != ask.currency:
            return None
        spreads.append(max(0.0, ask.amount - bid.amount))
        currency = bid.currency
        scale = bid.contract_scale
    if not spreads or currency is None:
        return None
    return EconomicValue(
        amount=sum(spreads),
        currency=currency,
        kind="bid_ask_cost",
        product_type="option",
        contract_scale=scale,
        as_of=as_of,
        provenance="typed_strategy_legs:ask_minus_bid",
    )


def _migration_cost_evidence(
    candidate: Mapping[str, Any],
    *,
    as_of: str,
) -> dict[str, EconomicValue | None]:
    raw = candidate.get("analysis_cost_evidence")
    if not isinstance(raw, Mapping):
        return dict.fromkeys(("fee", "slippage_reserve", "depth_impact", "legging_reserve", "hedge_reserve", "model_uncertainty_reserve", "conservative_net_edge"))
    result: dict[str, EconomicValue | None] = {}
    for name in (
        "fee",
        "slippage_reserve",
        "depth_impact",
        "legging_reserve",
        "hedge_reserve",
        "model_uncertainty_reserve",
        "conservative_net_edge",
    ):
        item = raw.get(name)
        if not isinstance(item, Mapping):
            result[name] = None
            continue
        amount = _optional_finite(item.get("amount"))
        currency = item.get("currency")
        kind = item.get("kind")
        product_type = item.get("product_type")
        provenance = item.get("provenance")
        if (
            amount is None
            or not all(
                isinstance(value, str) and value
                for value in (currency, kind, product_type, provenance)
            )
        ):
            result[name] = None
            continue
        result[name] = EconomicValue(
            amount=amount,
            currency=str(currency),
            kind=str(kind),
            product_type=str(product_type),
            contract_scale=_optional_positive(item.get("contract_scale")),
            as_of=str(item.get("as_of") or as_of),
            provenance=str(provenance),
        )
    return result


def _entry_admission_decisions(
    *,
    analysis_run_id: str,
    projection: Mapping[str, Any],
    market_evidence: EvidenceRecord,
    market_snapshot_id: str,
    opportunities: tuple[OpportunityRecord, ...],
    strategies: tuple[StrategyPlan, ...],
    account_evidence: EvidenceRecord | None,
    historical_artifact: EvidenceRecord | None,
    pre_entry_risk_claim: PreEntryRiskClaim | None,
    pre_entry_risk_evidence: EvidenceRecord | None,
    policy_bundle: PolicyBundle,
    model_bundle: ModelBundleRef,
    evaluated_at: str,
) -> tuple[EntryAdmissionDecision, ...]:
    if market_evidence.state is not EvidenceState.TRUSTED:
        condition = AdmissionCondition(
            condition_id="snapshot_trusted",
            observed=market_evidence.state.value,
            requirement="trusted authenticated market evidence",
            status=ConditionStatus.BLOCK,
            reason_code="MARKET_EVIDENCE_NOT_TRUSTED",
        )
        reasons = _unique_codes(
            ["MARKET_EVIDENCE_NOT_TRUSTED", *market_evidence.reason_codes]
        )
        return (
            _decision(
                analysis_run_id=analysis_run_id,
                opportunity=None,
                strategy=None,
                evaluated_at=evaluated_at,
                valid_until=market_evidence.expires_at or evaluated_at,
                status=EntryAdmissionStatus.BLOCKED_BY_EVIDENCE,
                conditions=(condition,),
                veto_sources=("market_evidence",),
                reason_codes=reasons,
                evidence_refs=(market_evidence.evidence_id,),
                policy_bundle=policy_bundle,
                model_bundle=model_bundle,
                market_snapshot_id=market_snapshot_id,
                account_evidence=account_evidence,
                confidence_ceiling="none",
            ),
        )
    if not opportunities:
        conditions = (
            AdmissionCondition(
                condition_id="snapshot_trusted",
                observed="trusted",
                requirement="trusted authenticated market evidence",
                status=ConditionStatus.PASS,
                reason_code="MARKET_EVIDENCE_TRUSTED",
            ),
            AdmissionCondition(
                condition_id="opportunity_scan_complete",
                observed=0,
                requirement="completed detector run with zero or more results",
                status=ConditionStatus.PASS,
                reason_code="NO_OPPORTUNITY_DETECTED",
            ),
        )
        return (
            _decision(
                analysis_run_id=analysis_run_id,
                opportunity=None,
                strategy=None,
                evaluated_at=evaluated_at,
                valid_until=market_evidence.expires_at or evaluated_at,
                status=EntryAdmissionStatus.NO_OPPORTUNITY,
                conditions=conditions,
                veto_sources=(),
                reason_codes=("NO_OPPORTUNITY_DETECTED",),
                evidence_refs=(market_evidence.evidence_id,),
                policy_bundle=policy_bundle,
                model_bundle=model_bundle,
                market_snapshot_id=market_snapshot_id,
                account_evidence=account_evidence,
                confidence_ceiling="trusted_scan_only",
            ),
        )
    by_opportunity = {item.opportunity_id: item for item in strategies}
    decisions: list[EntryAdmissionDecision] = []
    for opportunity in opportunities:
        strategy = by_opportunity.get(opportunity.opportunity_id)
        if strategy is None:
            continue
        conditions, veto_sources = _admission_conditions(
            opportunity=opportunity,
            strategy=strategy,
            projection=projection,
            market_evidence=market_evidence,
            account_evidence=account_evidence,
            pre_entry_risk_claim=pre_entry_risk_claim,
            pre_entry_risk_evidence=pre_entry_risk_evidence,
            policy=policy_bundle.catalog,
            model_bundle=model_bundle,
            evaluated_at=evaluated_at,
        )
        status = _admission_status(
            opportunity=opportunity,
            conditions=conditions,
            veto_sources=veto_sources,
            model_bundle=model_bundle,
        )
        reasons = _unique_codes(
            [
                *opportunity.reason_codes,
                *[
                    condition.reason_code
                    for condition in conditions
                    if condition.status is not ConditionStatus.PASS
                ],
                *veto_sources,
            ]
        )
        decisions.append(
            _decision(
                analysis_run_id=analysis_run_id,
                opportunity=opportunity,
                strategy=strategy,
                evaluated_at=evaluated_at,
                valid_until=opportunity.valid_until,
                status=status,
                conditions=conditions,
                veto_sources=veto_sources,
                reason_codes=reasons,
                evidence_refs=tuple(
                    _unique_codes(
                        [
                            *opportunity.evidence_refs,
                            (
                                account_evidence.evidence_id
                                if account_evidence
                                else None
                            ),
                            (
                                historical_artifact.evidence_id
                                if historical_artifact
                                else None
                            ),
                            (
                                pre_entry_risk_evidence.evidence_id
                                if pre_entry_risk_evidence
                                else None
                            ),
                        ]
                    )
                ),
                policy_bundle=policy_bundle,
                model_bundle=model_bundle,
                market_snapshot_id=market_snapshot_id,
                account_evidence=account_evidence,
                confidence_ceiling=opportunity.confidence_ceiling,
            )
        )
    return tuple(decisions)


def _admission_conditions(
    *,
    opportunity: OpportunityRecord,
    strategy: StrategyPlan,
    projection: Mapping[str, Any],
    market_evidence: EvidenceRecord,
    account_evidence: EvidenceRecord | None,
    pre_entry_risk_claim: PreEntryRiskClaim | None,
    pre_entry_risk_evidence: EvidenceRecord | None,
    policy: PolicyCatalog,
    model_bundle: ModelBundleRef,
    evaluated_at: str,
) -> tuple[tuple[AdmissionCondition, ...], tuple[str, ...]]:
    data_status = projection.get("data_status") or {}
    quality = data_status.get("quality_gate") or {}
    feeds = data_status.get("feed_coverage") or {}
    permission = projection.get("permission_state") or {}
    account = projection.get("account_status") or {}
    leg_times = [
        _parse_timestamp(leg.source_quote.observed_at, field="leg quote observed_at")
        for leg in strategy.legs
        if leg.source_quote.observed_at
    ]
    sync_delta = (
        (max(leg_times) - min(leg_times)).total_seconds()
        if len(leg_times) == len(strategy.legs)
        else None
    )
    quote_ages = [leg.source_quote.quote_age_seconds for leg in strategy.legs]
    max_quote_age = (
        max(float(item) for item in quote_ages if item is not None)
        if all(item is not None for item in quote_ages)
        else None
    )
    units_explicit = all(
        leg.product_economics.units_explicit for leg in strategy.legs
    )
    settlement_explicit = all(
        leg.product_economics.settlement_explicit for leg in strategy.legs
    )
    quotes_valid = all(
        leg.source_quote.bid is not None
        and leg.source_quote.ask is not None
        and leg.source_quote.bid.amount > 0
        and leg.source_quote.ask.amount >= leg.source_quote.bid.amount
        for leg in strategy.legs
    )
    gaps = [
        item
        for item in data_status.get("adapter_events") or []
        if isinstance(item, Mapping)
        and any(
            token in str(item.get("kind") or item.get("reason_code") or "").lower()
            for token in ("gap", "resync")
        )
    ]
    graph_complete = feeds.get("graph_complete")
    no_gap_status = (
        ConditionStatus.PASS
        if graph_complete is True and not gaps
        else ConditionStatus.BLOCK
        if gaps
        else ConditionStatus.UNKNOWN
    )
    model_required = opportunity.edge_class.value in policy.model_required_edge_classes
    model_pass = not model_required or model_bundle.promoted_for
    expired = _parse_timestamp(
        opportunity.valid_until,
        field="opportunity valid_until",
    ) <= _parse_timestamp(evaluated_at, field="evaluated_at")
    invalidated = opportunity.status is OpportunityStatus.INVALIDATED
    costs = (
        strategy.bid_ask_cost,
        strategy.fee,
        strategy.slippage_reserve,
        strategy.depth_impact,
        strategy.legging_reserve,
        strategy.hedge_reserve,
        strategy.model_uncertainty_reserve,
    )
    conservative_edge = strategy.conservative_net_edge
    economic_dimensions_known = all(
        item is not None and item.contract_scale is not None
        for item in (*costs, conservative_edge)
    )
    economic_dimensions_consistent = _economic_dimensions_consistent(
        (*costs, conservative_edge)
    )
    costs_nonnegative = all(
        item is not None and item.amount >= 0 for item in costs
    )
    costs_known = (
        all(item is not None for item in costs)
        and economic_dimensions_consistent
        and costs_nonnegative
    )
    total_cost = (
        sum(float(item.amount) for item in costs if item is not None)
        if costs_known
        else None
    )
    spread_ratios = [
        leg.source_quote.spread_ratio for leg in strategy.legs
    ]
    depths = [leg.source_quote.depth for leg in strategy.legs]
    open_interests = [leg.source_quote.open_interest for leg in strategy.legs]
    event_score = _optional_finite(
        (permission.get("regime_scores") or {}).get("event")
    )
    event_clear = (
        event_score is not None
        and event_score <= policy.maximum_event_score
    )
    account_trusted = (
        account_evidence is not None
        and account_evidence.kind == "account_snapshot"
        and account_evidence.state is EvidenceState.TRUSTED
        and account_evidence.is_current_at(
            evaluated_at,
            max_age_seconds=policy.account_snapshot_max_age_seconds,
        )
    )
    risk_evidence_trusted = (
        pre_entry_risk_evidence is not None
        and pre_entry_risk_evidence.state is EvidenceState.TRUSTED
        and pre_entry_risk_evidence.is_current_at(
            evaluated_at,
            max_age_seconds=policy.pre_entry_risk_max_age_seconds,
        )
    )
    pre_entry_risk_state = (
        pre_entry_risk_claim.portfolio_state
        if risk_evidence_trusted and pre_entry_risk_claim is not None
        else PreEntryRiskState.UNKNOWN
    )
    exchange_health_state = (
        pre_entry_risk_claim.exchange_health_state
        if risk_evidence_trusted and pre_entry_risk_claim is not None
        else ExchangeHealthState.UNKNOWN
    )
    portfolio_veto = (
        pre_entry_risk_state.value in policy.pre_entry_risk_veto_states
    )
    exchange_blocked = (
        exchange_health_state.value in policy.exchange_health_blocking_states
    )
    simulation_available = (
        account_trusted
        and (account.get("simulation_status") or {}).get("status") == "available"
        and (account.get("simulation_status") or {}).get("attempted") is True
    )
    outside_settlement = _outside_settlement_window(evaluated_at, policy)

    conditions = (
        _condition_bool(
            "snapshot_trusted",
            market_evidence.state is EvidenceState.TRUSTED,
            observed=market_evidence.state.value,
            requirement="trusted authenticated market evidence",
            pass_code="MARKET_EVIDENCE_TRUSTED",
            block_code="MARKET_EVIDENCE_NOT_TRUSTED",
        ),
        _condition_bool(
            "coverage_complete",
            quality.get("passed") is True,
            observed=str(data_status.get("status") or "missing"),
            requirement="market quality and declared coverage pass",
            pass_code="MARKET_COVERAGE_PASSED",
            block_code="MARKET_COVERAGE_INCOMPLETE",
        ),
        _condition_numeric_max(
            "legs_synchronized",
            sync_delta,
            policy.leg_sync_window_seconds,
            reason_prefix="LEG_SYNCHRONIZATION",
        ),
        _condition_numeric_max(
            "legs_fresh",
            max_quote_age,
            policy.quote_max_age_seconds,
            reason_prefix="LEG_FRESHNESS",
        ),
        AdmissionCondition(
            condition_id="no_gap_or_resync",
            observed=(
                "gap_or_resync"
                if gaps
                else "complete"
                if graph_complete is True
                else "not_observed"
            ),
            requirement="no gap and no resync pending",
            status=no_gap_status,
            reason_code=(
                "NO_GAP_OR_RESYNC_PENDING"
                if no_gap_status is ConditionStatus.PASS
                else "MARKET_GAP_OR_RESYNC_PENDING"
                if no_gap_status is ConditionStatus.BLOCK
                else "MARKET_GAP_STATE_UNKNOWN"
            ),
        ),
        _condition_bool(
            "explicit_units",
            units_explicit,
            observed="explicit" if units_explicit else "unknown",
            requirement="premium unit, product style, and contract scale explicit",
            pass_code="PRODUCT_UNITS_EXPLICIT",
            block_code="PRODUCT_UNIT_UNKNOWN",
        ),
        _condition_bool(
            "explicit_settlement",
            settlement_explicit,
            observed="explicit" if settlement_explicit else "unknown",
            requirement="venue-explicit settlement currency",
            pass_code="SETTLEMENT_EXPLICIT",
            block_code="SETTLEMENT_UNKNOWN",
        ),
        _condition_bool(
            "quotes_valid",
            quotes_valid,
            observed="valid" if quotes_valid else "crossed_empty_or_missing",
            requirement="positive non-crossed bid and ask for every leg",
            pass_code="LEG_QUOTES_VALID",
            block_code="LEG_QUOTES_INVALID",
        ),
        _condition_bool(
            "detector_allowed",
            f"{opportunity.detector_id}:{opportunity.detector_version}"
            in policy.allowed_detectors,
            observed=f"{opportunity.detector_id}:{opportunity.detector_version}",
            requirement="detector is allowed by the policy catalog",
            pass_code="DETECTOR_ALLOWED",
            block_code="DETECTOR_NOT_ALLOWED",
        ),
        AdmissionCondition(
            condition_id="defined_risk_policy",
            observed=strategy.selection_role,
            requirement="only the primary defined-risk expression may be admitted",
            status=(
                ConditionStatus.PASS
                if strategy.selection_role == "primary_defined_risk_expression"
                else ConditionStatus.BLOCK
            ),
            reason_code=(
                "DEFINED_RISK_POLICY_PASSED"
                if strategy.selection_role == "primary_defined_risk_expression"
                else "NAKED_SHORT_RESTRICTED_COMPARISON"
            ),
        ),
        _condition_bool(
            "pricing_checks",
            all(
                (
                    (projection.get("vol_surface_status") or {}).get("status")
                    == "validated",
                    all(
                        item.get("fit_quality_pass") is True
                        and item.get("no_arb_pass") is True
                        for item in (
                            (projection.get("vol_surface_status") or {}).get(
                                "expiries"
                            )
                            or []
                        )
                    ),
                )
            ),
            observed=str(
                (projection.get("vol_surface_status") or {}).get("status")
                or "missing"
            ),
            requirement="surface fit and no-arbitrage diagnostics pass",
            pass_code="PRICING_CHECKS_PASSED",
            block_code="PRICING_CHECKS_FAILED",
        ),
        _condition_known(
            "fair_interval_available",
            opportunity.fair_interval is not None,
            observed="available" if opportunity.fair_interval else None,
            requirement="typed fair-value interval available",
            pass_code="FAIR_INTERVAL_AVAILABLE",
            unknown_code="FAIR_INTERVAL_UNAVAILABLE",
        ),
        _condition_bool(
            "model_promoted_if_required",
            model_pass,
            observed=model_bundle.promotion_status,
            requirement=(
                "promoted model required for E2/E3"
                if model_required
                else "no promoted model required for E1"
            ),
            pass_code="MODEL_REQUIREMENT_PASSED",
            block_code="E3_MODEL_NOT_PROMOTED",
        ),
        _condition_bool(
            "opportunity_not_expired",
            not expired,
            observed=opportunity.valid_until,
            requirement=f"valid after {evaluated_at}",
            pass_code="OPPORTUNITY_TTL_VALID",
            block_code="OPPORTUNITY_EXPIRED",
        ),
        _condition_bool(
            "invalidation_clear",
            not invalidated,
            observed=opportunity.status.value,
            requirement="no invalidation condition triggered",
            pass_code="OPPORTUNITY_INVALIDATION_CLEAR",
            block_code="OPPORTUNITY_INVALIDATED",
        ),
        _condition_known(
            "net_premium_finite",
            strategy.net_premium is not None,
            observed=(
                strategy.net_premium.amount if strategy.net_premium else None
            ),
            requirement="finite typed net credit or debit",
            pass_code="NET_PREMIUM_FINITE",
            unknown_code="NET_PREMIUM_UNKNOWN",
        ),
        _condition_known(
            "spread_and_fee_known",
            strategy.bid_ask_cost is not None and strategy.fee is not None,
            observed=(
                "known"
                if strategy.bid_ask_cost is not None and strategy.fee is not None
                else None
            ),
            requirement="bid/ask cost and fee explicitly known",
            pass_code="SPREAD_AND_FEE_KNOWN",
            unknown_code="SPREAD_OR_FEE_UNKNOWN",
        ),
        _condition_known(
            "slippage_reserve_known",
            strategy.slippage_reserve is not None,
            observed=(
                strategy.slippage_reserve.amount
                if strategy.slippage_reserve
                else None
            ),
            requirement="slippage reserve explicitly known",
            pass_code="SLIPPAGE_RESERVE_KNOWN",
            unknown_code="SLIPPAGE_RESERVE_UNKNOWN",
        ),
        _condition_known(
            "depth_impact_known",
            strategy.depth_impact is not None,
            observed=(
                strategy.depth_impact.amount if strategy.depth_impact else None
            ),
            requirement="depth impact explicitly known",
            pass_code="DEPTH_IMPACT_KNOWN",
            unknown_code="DEPTH_IMPACT_UNKNOWN",
        ),
        _condition_known(
            "legging_reserve_known",
            strategy.legging_reserve is not None,
            observed=(
                strategy.legging_reserve.amount
                if strategy.legging_reserve
                else None
            ),
            requirement="legging reserve explicitly known",
            pass_code="LEGGING_RESERVE_KNOWN",
            unknown_code="LEGGING_RESERVE_UNKNOWN",
        ),
        _condition_known(
            "hedge_reserve_known",
            strategy.hedge_reserve is not None,
            observed=(
                strategy.hedge_reserve.amount
                if strategy.hedge_reserve
                else None
            ),
            requirement="hedge reserve explicitly known",
            pass_code="HEDGE_RESERVE_KNOWN",
            unknown_code="HEDGE_RESERVE_UNKNOWN",
        ),
        _condition_known(
            "uncertainty_reserve_known",
            strategy.model_uncertainty_reserve is not None,
            observed=(
                strategy.model_uncertainty_reserve.amount
                if strategy.model_uncertainty_reserve
                else None
            ),
            requirement="model uncertainty reserve explicitly known",
            pass_code="UNCERTAINTY_RESERVE_KNOWN",
            unknown_code="UNCERTAINTY_RESERVE_UNKNOWN",
        ),
        AdmissionCondition(
            condition_id="economic_dimensions_consistent",
            observed=(
                "consistent"
                if economic_dimensions_consistent
                else "missing_or_mismatched"
            ),
            requirement=(
                "edge and all cost values share currency, product type, "
                "and contract scale"
            ),
            status=(
                ConditionStatus.UNKNOWN
                if not economic_dimensions_known
                else ConditionStatus.PASS
                if economic_dimensions_consistent and costs_nonnegative
                else ConditionStatus.BLOCK
            ),
            reason_code=(
                "ECONOMIC_DIMENSIONS_UNKNOWN"
                if not economic_dimensions_known
                else "ECONOMIC_DIMENSIONS_CONSISTENT"
                if economic_dimensions_consistent and costs_nonnegative
                else "ECONOMIC_COST_INVALID"
                if economic_dimensions_consistent
                else "ECONOMIC_DIMENSIONS_MISMATCH"
            ),
        ),
        _condition_known_numeric_positive(
            "conservative_net_edge_positive",
            conservative_edge.amount if conservative_edge else None,
            requirement="conservative typed net edge greater than zero",
            pass_code="CONSERVATIVE_NET_EDGE_POSITIVE",
            block_code="CONSERVATIVE_NET_EDGE_NONPOSITIVE",
            unknown_code="CONSERVATIVE_NET_EDGE_UNKNOWN",
        ),
        _condition_known_numeric_positive(
            "capital_at_risk_proxy_positive",
            (
                strategy.capital_at_risk_proxy.amount
                if strategy.capital_at_risk_proxy
                else None
            ),
            requirement="defined-risk capital-at-risk proxy greater than zero",
            pass_code="CAPITAL_AT_RISK_PROXY_POSITIVE",
            block_code="CAPITAL_AT_RISK_PROXY_NONPOSITIVE",
            unknown_code="CAPITAL_AT_RISK_PROXY_UNKNOWN",
        ),
        _condition_known_numeric_positive(
            "edge_to_capital_at_risk_positive",
            strategy.edge_to_capital_at_risk,
            requirement="conservative edge / capital-at-risk proxy greater than zero",
            pass_code="EDGE_TO_CAPITAL_AT_RISK_POSITIVE",
            block_code="EDGE_TO_CAPITAL_AT_RISK_NONPOSITIVE",
            unknown_code="EDGE_TO_CAPITAL_AT_RISK_UNKNOWN",
        ),
        _condition_cost_coverage(
            conservative_edge=conservative_edge,
            total_cost=total_cost,
            costs_known=costs_known,
            required_ratio=policy.cost_coverage_ratio,
        ),
        _condition_collection_max(
            "spread_ratio",
            spread_ratios,
            policy.max_spread_ratio,
            reason_prefix="SPREAD_RATIO",
        ),
        _condition_collection_min(
            "depth",
            depths,
            policy.minimum_depth,
            reason_prefix="DEPTH",
        ),
        _condition_collection_min(
            "open_interest",
            open_interests,
            policy.minimum_open_interest,
            reason_prefix="OPEN_INTEREST",
        ),
        _condition_numeric_max(
            "quote_age",
            max_quote_age,
            policy.quote_max_age_seconds,
            reason_prefix="QUOTE_AGE",
        ),
        AdmissionCondition(
            condition_id="research_capacity",
            observed=strategy.research_capacity_class or "not_evaluated",
            requirement="non-actionable research capacity class available",
            status=(
                ConditionStatus.PASS
                if strategy.research_capacity_class
                else ConditionStatus.UNKNOWN
            ),
            reason_code=(
                "RESEARCH_CAPACITY_CLASS_AVAILABLE"
                if strategy.research_capacity_class
                else "RESEARCH_CAPACITY_NOT_EVALUATED"
            ),
        ),
        _condition_bool(
            "settlement_window",
            outside_settlement,
            observed="outside" if outside_settlement else "inside",
            requirement=(
                "outside "
                f"{policy.settlement_window_utc[0]}-"
                f"{policy.settlement_window_utc[1]} UTC"
            ),
            pass_code="OUTSIDE_SETTLEMENT_WINDOW",
            block_code="SETTLEMENT_WINDOW_ACTIVE",
        ),
        AdmissionCondition(
            condition_id="major_event_gate",
            observed=event_score,
            requirement=(
                "event score observed and <= "
                f"{policy.maximum_event_score:g}"
            ),
            status=(
                ConditionStatus.UNKNOWN
                if event_score is None
                else ConditionStatus.PASS
                if event_clear
                else ConditionStatus.BLOCK
            ),
            reason_code=(
                "MAJOR_EVENT_GATE_UNKNOWN"
                if event_score is None
                else "MAJOR_EVENT_GATE_CLEAR"
                if event_clear
                else "MAJOR_EVENT_GATE_BLOCKED"
            ),
        ),
        AdmissionCondition(
            condition_id="exchange_health",
            observed=exchange_health_state.value,
            requirement="current typed exchange-health evidence is CLEAR",
            status=(
                ConditionStatus.UNKNOWN
                if exchange_health_state is ExchangeHealthState.UNKNOWN
                else ConditionStatus.BLOCK
                if exchange_blocked
                else ConditionStatus.PASS
            ),
            reason_code=(
                "EXCHANGE_HEALTH_UNKNOWN"
                if exchange_health_state is ExchangeHealthState.UNKNOWN
                else "EXCHANGE_HEALTH_BLOCKED"
                if exchange_blocked
                else "EXCHANGE_HEALTH_CLEAR"
            ),
        ),
        _condition_bool(
            "data_source_health",
            market_evidence.state is EvidenceState.TRUSTED,
            observed=market_evidence.state.value,
            requirement="data source remains trusted",
            pass_code="DATA_SOURCE_HEALTH_CLEAR",
            block_code="DATA_SOURCE_DEGRADED",
        ),
        _condition_bool(
            "policy_kill_switch",
            not policy.kill_switch,
            observed=policy.kill_switch,
            requirement="policy kill switch is false",
            pass_code="POLICY_KILL_SWITCH_CLEAR",
            block_code="POLICY_KILL_SWITCH_ACTIVE",
        ),
        _condition_known(
            "account_evidence",
            account_trusted,
            observed=(
                account_evidence.state.value if account_evidence else None
            ),
            requirement="authenticated current read-only account evidence",
            pass_code="ACCOUNT_EVIDENCE_TRUSTED",
            unknown_code="ACCOUNT_EVIDENCE_MISSING_OR_UNTRUSTED",
        ),
        _condition_known(
            "venue_margin_simulation",
            simulation_available,
            observed=(
                (account.get("simulation_status") or {}).get("status")
                if account_trusted
                else None
            ),
            requirement="venue margin simulation attempted and available",
            pass_code="VENUE_MARGIN_SIMULATION_AVAILABLE",
            unknown_code="VENUE_MARGIN_SIMULATION_NOT_EVALUATED",
        ),
        AdmissionCondition(
            condition_id="portfolio_veto",
            observed=pre_entry_risk_state.value,
            requirement="current pre-entry portfolio risk evidence is CLEAR",
            status=(
                ConditionStatus.BLOCK
                if portfolio_veto
                else ConditionStatus.PASS
                if pre_entry_risk_state is PreEntryRiskState.CLEAR
                else ConditionStatus.UNKNOWN
            ),
            reason_code=(
                "PORTFOLIO_VETO_ACTIVE"
                if portfolio_veto
                else "PORTFOLIO_VETO_CLEAR"
                if pre_entry_risk_state is PreEntryRiskState.CLEAR
                else "PORTFOLIO_VETO_EVIDENCE_UNKNOWN"
            ),
        ),
    )
    veto_sources: list[str] = []
    if portfolio_veto:
        veto_sources.append("PORTFOLIO_VETO_ACTIVE")
    if policy.kill_switch:
        veto_sources.append("POLICY_KILL_SWITCH_ACTIVE")
    if not outside_settlement:
        veto_sources.append("SETTLEMENT_WINDOW_ACTIVE")
    if event_score is not None and not event_clear:
        veto_sources.append("MAJOR_EVENT_GATE_BLOCKED")
    if exchange_blocked:
        veto_sources.append("EXCHANGE_HEALTH_BLOCKED")
    if strategy.selection_role == "restricted_comparison_only":
        veto_sources.append("NAKED_SHORT_RESTRICTED_COMPARISON")
    return conditions, tuple(_unique_codes(veto_sources))


def _admission_status(
    *,
    opportunity: OpportunityRecord,
    conditions: tuple[AdmissionCondition, ...],
    veto_sources: tuple[str, ...],
    model_bundle: ModelBundleRef,
) -> EntryAdmissionStatus:
    if opportunity.status is OpportunityStatus.EXPIRED:
        return EntryAdmissionStatus.DEFERRED
    if opportunity.status is OpportunityStatus.INVALIDATED:
        return EntryAdmissionStatus.VETOED
    if veto_sources:
        return EntryAdmissionStatus.VETOED
    if opportunity.edge_class is EdgeClass.E3 and not model_bundle.promoted_for:
        return EntryAdmissionStatus.MONITOR_ONLY
    if any(
        condition.status in {ConditionStatus.BLOCK, ConditionStatus.UNKNOWN}
        for condition in conditions
    ):
        return EntryAdmissionStatus.DEFERRED
    return EntryAdmissionStatus.CONDITIONALLY_ELIGIBLE


def _decision(
    *,
    analysis_run_id: str,
    opportunity: OpportunityRecord | None,
    strategy: StrategyPlan | None,
    evaluated_at: str,
    valid_until: str,
    status: EntryAdmissionStatus,
    conditions: tuple[AdmissionCondition, ...],
    veto_sources: Iterable[str],
    reason_codes: Iterable[str],
    evidence_refs: Iterable[str],
    policy_bundle: PolicyBundle,
    model_bundle: ModelBundleRef,
    market_snapshot_id: str,
    account_evidence: EvidenceRecord | None,
    confidence_ceiling: str,
) -> EntryAdmissionDecision:
    first_unresolved = next(
        (
            condition.condition_id
            for condition in conditions
            if condition.status in {ConditionStatus.BLOCK, ConditionStatus.UNKNOWN}
        ),
        None,
    )
    identity = {
        "analysis_run_id": analysis_run_id,
        "opportunity_id": opportunity.opportunity_id if opportunity else None,
        "strategy_id": strategy.strategy_id if strategy else None,
        "evaluated_at": evaluated_at,
        "status": status.value,
        "conditions": [condition.to_dict() for condition in conditions],
        "policy_bundle_id": policy_bundle.policy_bundle_id,
        "model_bundle_id": model_bundle.model_bundle_id,
    }
    return EntryAdmissionDecision(
        decision_id=f"decision:{canonical_sha256(identity)}",
        analysis_run_id=analysis_run_id,
        opportunity_id=opportunity.opportunity_id if opportunity else None,
        strategy_id=strategy.strategy_id if strategy else None,
        evaluated_at=evaluated_at,
        valid_until=valid_until,
        status=status,
        execution_allowed=False,
        conditions=conditions,
        veto_sources=tuple(_unique_codes(veto_sources)),
        reason_codes=tuple(_unique_codes(reason_codes)),
        evidence_refs=tuple(sorted(set(evidence_refs))),
        policy_bundle_id=policy_bundle.policy_bundle_id,
        model_bundle_id=model_bundle.model_bundle_id,
        market_snapshot_id=market_snapshot_id,
        account_evidence_id=(
            account_evidence.evidence_id if account_evidence else None
        ),
        confidence_ceiling=confidence_ceiling,
        next_observable_condition=first_unresolved,
    )


def _domain_events(
    *,
    analysis_run_id: str,
    evaluated_at: str,
    evidence_refs: tuple[str, ...],
    opportunities: tuple[OpportunityRecord, ...],
    decisions: tuple[EntryAdmissionDecision, ...],
    global_reason_codes: Iterable[str],
) -> tuple[DomainEvent, ...]:
    events: list[DomainEvent] = []
    for opportunity in opportunities:
        events.append(
            DomainEvent.create(
                event_type="opportunity.observed",
                occurred_at=opportunity.detected_at,
                observed_at=evaluated_at,
                actor="AnalysisRun",
                source=opportunity.detector_id,
                correlation_id=analysis_run_id,
                evidence_refs=opportunity.evidence_refs,
                reason_codes=opportunity.reason_codes,
                payload={
                    "opportunity_id": opportunity.opportunity_id,
                    "edge_class": opportunity.edge_class.value,
                    "status": opportunity.status.value,
                    "valid_until": opportunity.valid_until,
                },
            )
        )
    for decision in decisions:
        events.append(
            DomainEvent.create(
                event_type="entry_admission.decided",
                occurred_at=evaluated_at,
                observed_at=evaluated_at,
                actor="PolicyCatalog",
                source="AnalysisRun",
                correlation_id=analysis_run_id,
                evidence_refs=decision.evidence_refs,
                reason_codes=decision.reason_codes,
                payload={
                    "decision_id": decision.decision_id,
                    "status": decision.status.value,
                    "valid_until": decision.valid_until,
                    "next_observable_condition": (
                        decision.next_observable_condition
                    ),
                },
            )
        )
    events.append(
        DomainEvent.create(
            event_type="analysis.completed",
            occurred_at=evaluated_at,
            observed_at=evaluated_at,
            actor="AnalysisRun",
            source="pre_entry_engine",
            correlation_id=analysis_run_id,
            evidence_refs=evidence_refs,
            reason_codes=global_reason_codes,
            payload={
                "analysis_run_id": analysis_run_id,
                "opportunity_count": len(opportunities),
                "decision_count": len(decisions),
                "research_only": True,
            },
        )
    )
    return tuple(sorted(events, key=lambda item: item.event_id))


def _condition_bool(
    condition_id: str,
    passed: bool,
    *,
    observed: str | float | int | bool | None,
    requirement: str,
    pass_code: str,
    block_code: str,
) -> AdmissionCondition:
    return AdmissionCondition(
        condition_id=condition_id,
        observed=observed,
        requirement=requirement,
        status=ConditionStatus.PASS if passed else ConditionStatus.BLOCK,
        reason_code=pass_code if passed else block_code,
    )


def _condition_known(
    condition_id: str,
    passed: bool,
    *,
    observed: str | float | int | bool | None,
    requirement: str,
    pass_code: str,
    unknown_code: str,
) -> AdmissionCondition:
    return AdmissionCondition(
        condition_id=condition_id,
        observed=observed,
        requirement=requirement,
        status=ConditionStatus.PASS if passed else ConditionStatus.UNKNOWN,
        reason_code=pass_code if passed else unknown_code,
    )


def _condition_known_numeric_positive(
    condition_id: str,
    observed: float | None,
    *,
    requirement: str,
    pass_code: str,
    block_code: str,
    unknown_code: str,
) -> AdmissionCondition:
    if observed is None:
        return AdmissionCondition(
            condition_id=condition_id,
            observed=None,
            requirement=requirement,
            status=ConditionStatus.UNKNOWN,
            reason_code=unknown_code,
        )
    passed = observed > 0
    return AdmissionCondition(
        condition_id=condition_id,
        observed=observed,
        requirement=requirement,
        status=ConditionStatus.PASS if passed else ConditionStatus.BLOCK,
        reason_code=pass_code if passed else block_code,
    )


def _condition_cost_coverage(
    *,
    conservative_edge: EconomicValue | None,
    total_cost: float | None,
    costs_known: bool,
    required_ratio: float,
) -> AdmissionCondition:
    if not costs_known or conservative_edge is None or total_cost is None:
        return AdmissionCondition(
            condition_id="cost_coverage",
            observed=None,
            requirement=f"conservative edge / costs >= {required_ratio:g}",
            status=ConditionStatus.UNKNOWN,
            reason_code="COST_COVERAGE_UNKNOWN",
        )
    ratio = (
        conservative_edge.amount / total_cost
        if total_cost > 0
        else math.inf
        if conservative_edge.amount > 0
        else 0.0
    )
    passed = (
        conservative_edge.amount > 0
        and conservative_edge.amount >= total_cost * required_ratio
    )
    return AdmissionCondition(
        condition_id="cost_coverage",
        observed=round(ratio, 9) if math.isfinite(ratio) else "infinite",
        requirement=f"conservative edge / costs >= {required_ratio:g}",
        status=ConditionStatus.PASS if passed else ConditionStatus.BLOCK,
        reason_code=(
            "COST_COVERAGE_PASSED" if passed else "COST_COVERAGE_FAILED"
        ),
    )


def _condition_numeric_max(
    condition_id: str,
    observed: float | None,
    maximum: float,
    *,
    reason_prefix: str,
) -> AdmissionCondition:
    if observed is None:
        return AdmissionCondition(
            condition_id=condition_id,
            observed=None,
            requirement=f"<= {maximum:g}",
            status=ConditionStatus.UNKNOWN,
            reason_code=f"{reason_prefix}_UNKNOWN",
        )
    passed = observed <= maximum
    return AdmissionCondition(
        condition_id=condition_id,
        observed=round(observed, 9),
        requirement=f"<= {maximum:g}",
        status=ConditionStatus.PASS if passed else ConditionStatus.BLOCK,
        reason_code=(
            f"{reason_prefix}_PASSED"
            if passed
            else (
                "LEG_SYNCHRONIZATION_WINDOW_EXCEEDED"
                if reason_prefix == "LEG_SYNCHRONIZATION"
                else f"{reason_prefix}_EXCEEDED"
            )
        ),
    )


def _condition_collection_max(
    condition_id: str,
    values: Iterable[float | None],
    maximum: float,
    *,
    reason_prefix: str,
) -> AdmissionCondition:
    items = list(values)
    observed = (
        max(float(item) for item in items if item is not None)
        if items and all(item is not None for item in items)
        else None
    )
    return _condition_numeric_max(
        condition_id,
        observed,
        maximum,
        reason_prefix=reason_prefix,
    )


def _condition_collection_min(
    condition_id: str,
    values: Iterable[float | None],
    minimum: float,
    *,
    reason_prefix: str,
) -> AdmissionCondition:
    items = list(values)
    if not items or any(item is None for item in items):
        return AdmissionCondition(
            condition_id=condition_id,
            observed=None,
            requirement=f">= {minimum:g}",
            status=ConditionStatus.UNKNOWN,
            reason_code=f"{reason_prefix}_UNKNOWN",
        )
    observed = min(float(item) for item in items if item is not None)
    passed = observed >= minimum
    return AdmissionCondition(
        condition_id=condition_id,
        observed=round(observed, 9),
        requirement=f">= {minimum:g}",
        status=ConditionStatus.PASS if passed else ConditionStatus.BLOCK,
        reason_code=(
            f"{reason_prefix}_PASSED"
            if passed
            else f"{reason_prefix}_BELOW_MINIMUM"
        ),
    )


def _outside_settlement_window(
    evaluated_at: str,
    policy: PolicyCatalog,
) -> bool:
    current = _parse_timestamp(evaluated_at, field="evaluated_at")

    def minutes(value: str) -> int:
        hours, minute = value.split(":")
        return int(hours) * 60 + int(minute)

    current_minutes = current.hour * 60 + current.minute
    start = minutes(policy.settlement_window_utc[0])
    end = minutes(policy.settlement_window_utc[1])
    return not start <= current_minutes < end


def _timestamp_from_ms(value: Any) -> str | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return None
    try:
        return _timestamp(datetime.fromtimestamp(float(value) / 1000, tz=UTC))
    except (OSError, OverflowError, ValueError):
        return None


def _optional_finite(value: Any) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return None
    return float(value)


def _optional_positive(value: Any) -> float | None:
    parsed = _optional_finite(value)
    return parsed if parsed is not None and parsed > 0 else None


def _unique_codes(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
