"""Deterministic static publishing for the public research edition."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from ._canonical import canonical_json_text, canonical_sha256
from .analysis_run import CODE_VERSION, build_analysis_record
from .contract import validate_report_contract
from .empirical_rank import vrp_band_for_percentile
from .full_surface import build_release_gates, validate_full_system_surface_report
from .market_data import load_snapshot_fixture, load_underlying_history_fixture
from .og_card import render_og_card, validate_og_card_png
from .public_api_contract import build_public_openapi
from .public_bundle_policy import forbidden_bundle_tokens
from .public_origin import validate_public_site_origin
from .public_status_page import render_public_status_html
from .publication_history import build_publication_history
from .storage import read_json_object_from_regular_file
from .vrp import build_vrp_status, load_dvol_history_fixture

PUBLICATION_MANIFEST_SCHEMA = "public_publication_manifest.v1"
PUBLICATION_SUMMARY_SCHEMA = "public_summary.v1"
PUBLICATION_CANDIDATES_SCHEMA = "public_candidates.v1"
PUBLICATION_SIGNAL_SCHEMA = "public_signal.v1"
PUBLICATION_HEALTH_SCHEMA = "public_health.v1"
PUBLICATION_STATUS_SCHEMA = "public_status.v1"
PUBLICATION_THERMO_SCHEMA = "public_thermo.v1"
PUBLISH_CADENCE = "daily"
PUBLISH_INTERVAL = timedelta(days=1)
RECENT_THERMO_WINDOW_DAYS = 90
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
_PUBLIC_LICENSE_FILES = {"LICENSE", "LICENSE-DATA"}
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
_WINDOWS_DRIVE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|[A-Za-z]:\\\\)",
    re.IGNORECASE,
)
_UNC_PATH_RE = re.compile(
    r"\\\\[A-Za-z0-9._$-]+[\\/][^\\/\s]+",
    re.IGNORECASE,
)
_UNIX_ABSOLUTE_PATH_RE = re.compile(
    r"/(?:Users|home|root|tmp|var/tmp|Volumes|private/tmp|private/var|workspace|workspaces|github/workspace|mnt|opt)/[^\s]+",
    re.IGNORECASE,
)
_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
DTE_EVIDENCE_CONFLICT = "DTE_EVIDENCE_CONFLICT"

_SIGNAL_CONFIG_FIELDS = {
    "bucket_count",
    "max_dte_days",
    "min_dte_days",
    "min_independent_cohorts",
    "min_observations",
    "min_observations_per_date",
    "trailing_vol_window_days",
}
_SERIES_CONFIG_FIELDS = {
    "max_instruments",
    "min_capture_dates",
}
_SIGNAL_SAMPLE_FIELDS = {
    "duplicate_observations_dropped",
    "excluded_snapshot_count",
    "excluded_snapshots",
    "expiry_cohorts",
    "independent_expiry_cohorts",
    "observation_count",
    "sample_size_basis",
    "settlement_basis",
    "settlement_note",
    "snapshot_count",
    "snapshot_date_count",
    "validated_snapshot_count",
}
_SIGNAL_SUMMARY_FIELDS = {
    "best_exploratory_signal",
    "pre_registered_axis",
    "pre_registered_axis_verdict",
    "promotion_eligible",
    "promotion_eligibility_basis",
    "signals_measured",
    "signals_with_detectable_ic",
}
_SIGNAL_INFORMATION_COEFFICIENT_FIELDS = {
    "mean",
    "method",
    "neutralization",
    "stdev_across_dates",
    "t_stat",
}
_SIGNAL_RAW_IC_FIELDS = {
    "mean",
    "measured_date_count",
    "method",
    "warning",
}
_SIGNAL_BUCKET_FIELDS = {
    "bucket",
    "expired_itm_rate",
    "independent_expiry_cohorts",
    "mean_pnl_per_vega_iv_points",
    "mean_pnl_usd",
    "median_pnl_per_vega_iv_points",
    "observation_count",
    "signal_max",
    "signal_min",
    "win_rate",
}
_SIGNAL_PER_DATE_FIELDS = {
    "information_coefficient",
    "observation_count",
    "raw_information_coefficient",
    "snapshot_date",
}
_SIGNAL_MEASUREMENT_FIELDS = {
    "buckets",
    "definition",
    "effective_sample_basis",
    "effective_sample_size",
    "evidence_verdict",
    "independent_expiry_cohorts",
    "information_coefficient",
    "measured_date_count",
    "observation_count",
    "per_date",
    "raw_information_coefficient",
    "reason_code",
    "status",
}
_SIGNAL_BAND_FIELDS = {
    "cohorts_required",
    "cohorts_seen",
    "cohorts_short_by",
    "next_pending_expiry",
    "pending_cohorts",
    "pending_observation_count",
    "settled_cohorts",
    "settled_observation_count",
    "would_be_ready_after_expiry",
}
_SIGNAL_COHORT_FIELDS = {
    "band",
    "blocking_reasons",
    "capture_date_count",
    "dte_days_max",
    "dte_days_min",
    "expiry_date",
    "first_capture_date",
    "fitted_capture_count",
    "last_capture_date",
    "name",
    "observation_count",
    "prospective_observation_count",
    "registered_at",
    "settlement_close_available",
    "status",
}
_SIGNAL_EXCLUDED_SNAPSHOT_FIELDS = {"captured_at", "reason_code"}
_SIGNAL_PRE_REGISTRATION_FIELDS = {
    "axis",
    "document",
    "note",
    "registered_at",
    "threshold",
}
_SERIES_INSTRUMENT_FIELDS = {
    "capture_date_count",
    "expiry_date",
    "instrument_name",
    "latest",
    "missing_date_count",
    "option_type",
    "persistence",
    "points",
    "residual_z",
    "strike_price",
}
_SERIES_LATEST_FIELDS = {
    "bid_usdc",
    "date",
    "dte_days",
    "model_delta",
    "residual_z",
}
_SERIES_PERSISTENCE_FIELDS = {
    "basis",
    "coverage",
    "not_a_significance_test",
    "prior_observations",
    "raw_mean",
    "shrinkage_weight",
    "shrunk_mean",
}
_SERIES_SUMMARY_FIELDS = {
    "max",
    "mean",
    "min",
    "observation_count",
    "positive_share",
}
_SERIES_POINT_FIELDS = {
    "bid_usdc",
    "date",
    "dte_days",
    "mark_iv",
    "model_delta",
    "open_interest",
    "present",
    "residual_iv_points",
    "residual_z",
    "underlying_price",
}
_SERIES_EXCLUDED_CAPTURE_FIELDS = {"captured_at", "reason_code"}


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


def _validate_git_sha(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _GIT_SHA_RE.fullmatch(text) is None:
        raise ValueError("git_sha must be a plain SHA")
    return text.lower()


def _build_git_provenance(git_sha: str | None) -> dict[str, Any]:
    if git_sha is None:
        return {
            "status": "unknown",
            "git_sha": None,
            "verification_status": "not_declared",
        }
    return {
        "status": "declared",
        "git_sha": git_sha,
        "verification_status": "declared_unverified",
    }


def _build_publication_inputs(
    *,
    snapshot_payload: dict[str, Any],
    underlying_payload: dict[str, Any],
    dvol_payload: dict[str, Any],
    signal_payload: dict[str, Any],
    series_payload: dict[str, Any],
    publication_history_payload: dict[str, Any],
    published_dt: datetime,
    git_provenance: dict[str, Any],
    site_origin: str,
) -> dict[str, Any]:
    return {
        "snapshot": canonical_sha256(snapshot_payload),
        "underlying_history": canonical_sha256(underlying_payload),
        "dvol_history": canonical_sha256(dvol_payload),
        "signal_artifact": canonical_sha256(signal_payload),
        "series_artifact": canonical_sha256(series_payload),
        "publication_history": canonical_sha256(publication_history_payload),
        "site_origin": site_origin,
        "published_at": _timestamp(published_dt),
        "git_sha": git_provenance.get("git_sha"),
        "git_provenance": git_provenance,
        "engine_version": CODE_VERSION,
    }


def _build_release_gates_from_disk(
    *,
    report: dict[str, Any],
    out_path: Path,
    manifest_verification: dict[str, Any],
) -> list[dict[str, Any]]:
    data_status = str((report.get("data_status") or {}).get("status") or "missing")
    publication_evidence = {
        "data_quality": data_status,
        "publish_manifest": manifest_verification["status"],
        "methodology": "present" if (out_path / "methodology.html").is_file() else "missing",
        "disclaimer": "present" if (out_path / "disclaimer.html").is_file() else "missing",
    }
    research_publication_ready = (
        publication_evidence["publish_manifest"] == "verified"
        and publication_evidence["methodology"] == "present"
        and publication_evidence["disclaimer"] == "present"
        and publication_evidence["data_quality"] in {"trusted", "validated"}
    )
    return build_release_gates(
        research_publication_ready=research_publication_ready,
        publication_evidence=publication_evidence,
    )


def _load_manifest_verification(out_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    for entry in manifest.get("artifacts") or []:
        if not isinstance(entry, dict):
            errors.append("manifest artifact entry must be an object")
            continue
        relative_path = entry.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            errors.append("manifest artifact path must be a non-empty string")
            continue
        path = out_path / relative_path
        if not path.is_file():
            errors.append(f"missing artifact {relative_path}")
            continue
        expected = str(entry.get("sha256") or "")
        actual = sha256(path.read_bytes()).hexdigest()
        if expected != actual:
            errors.append(f"hash mismatch for {relative_path}")
    mirror_path = out_path / ".well-known" / "publish-manifest.json"
    api_path = out_path / "api" / "v1" / "manifest.json"
    if not mirror_path.is_file():
        errors.append("missing .well-known publish manifest")
    if not api_path.is_file():
        errors.append("missing api publish manifest")
    if mirror_path.is_file() and api_path.is_file():
        if mirror_path.read_text(encoding="utf-8") != api_path.read_text(encoding="utf-8"):
            errors.append("manifest mirrors must be byte-identical")
    return {
        "status": "verified" if not errors else "invalid",
        "artifact_count": len(manifest.get("artifacts") or []),
        "errors": errors,
    }


def _infer_numeric_unit(field_name: str) -> str | None:
    if field_name.endswith("_percent") or field_name.endswith("_rate"):
        return "percent"
    if field_name.endswith("_days"):
        return "days"
    if field_name.endswith("_count") or field_name.endswith("_cohorts"):
        return "count"
    if field_name.endswith("_usdc") or field_name.endswith("_usd"):
        return "currency"
    if field_name in {"percentile", "coverage", "coverage_ratio", "win_rate", "positive_share"}:
        return "fraction_0_1"
    if field_name == "threshold":
        return "scalar"
    return None


def _annotate_numeric_field_evidence(value: Any, *, evidence_class: str) -> Any:
    if isinstance(value, list):
        return [
            _annotate_numeric_field_evidence(item, evidence_class=evidence_class)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    annotated: dict[str, Any] = {}
    field_evidence: dict[str, Any] = {}
    for key, nested in value.items():
        annotated_value = _annotate_numeric_field_evidence(
            nested,
            evidence_class=evidence_class,
        )
        annotated[key] = annotated_value
        if isinstance(nested, (int, float)) and not isinstance(nested, bool):
            field_evidence[key] = {
                "evidence_class": evidence_class,
                "unit": _infer_numeric_unit(key),
            }
    if field_evidence:
        annotated["field_evidence"] = field_evidence
    return annotated


def _project_signal_artifact(value: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for field in (
        "schema_version",
        "captured_at",
        "generated_at",
        "research_only",
        "status",
        "headline",
        "note",
        "snapshot_count",
        "t_stat_threshold",
    ):
        if field in value:
            projected[field] = value.get(field)
    if "reason_codes" in value:
        projected["reason_codes"] = list(value.get("reason_codes") or [])
    if "config" in value:
        config = dict(value.get("config") or {})
        unexpected = sorted(set(config) - _SIGNAL_CONFIG_FIELDS)
        if unexpected:
            raise ValueError(
                f"publication blocked: unapproved public field config.{unexpected[0]}"
            )
        projected["config"] = {key: config.get(key) for key in sorted(config)}
    if "summary" in value:
        summary = dict(value.get("summary") or {})
        unexpected = sorted(set(summary) - _SIGNAL_SUMMARY_FIELDS)
        if unexpected:
            raise ValueError(
                f"publication blocked: unapproved public field summary.{unexpected[0]}"
            )
        projected["summary"] = _annotate_numeric_field_evidence(
            {key: summary.get(key) for key in sorted(summary)},
            evidence_class="research_signal_artifact",
        )
    if "pre_registration" in value:
        pre_registration = dict(value.get("pre_registration") or {})
        unexpected = sorted(set(pre_registration) - _SIGNAL_PRE_REGISTRATION_FIELDS)
        if unexpected:
            raise ValueError(
                "publication blocked: unapproved public field "
                f"pre_registration.{unexpected[0]}"
            )
        projected["pre_registration"] = {
            key: pre_registration.get(key) for key in sorted(pre_registration)
        }
    if "signal_definitions" in value:
        definitions = dict(value.get("signal_definitions") or {})
        projected["signal_definitions"] = {
            str(key): str(definitions[key]) for key in sorted(definitions)
        }
    if "excluded_snapshots" in value:
        excluded_snapshots = []
        for item in value.get("excluded_snapshots") or []:
            row = dict(item or {})
            unexpected = sorted(set(row) - _SIGNAL_EXCLUDED_SNAPSHOT_FIELDS)
            if unexpected:
                raise ValueError(
                    "publication blocked: unapproved public field "
                    f"excluded_snapshots.{unexpected[0]}"
                )
            excluded_snapshots.append(
                {key: row.get(key) for key in sorted(row)}
            )
        projected["excluded_snapshots"] = excluded_snapshots
    if "sample" in value:
        sample = dict(value.get("sample") or {})
        unexpected = sorted(set(sample) - _SIGNAL_SAMPLE_FIELDS)
        if unexpected:
            raise ValueError(
                f"publication blocked: unapproved public field sample.{unexpected[0]}"
            )
        projected["sample"] = _annotate_numeric_field_evidence(
            {
                "duplicate_observations_dropped": sample.get("duplicate_observations_dropped"),
                "excluded_snapshot_count": sample.get("excluded_snapshot_count"),
                "excluded_snapshots": projected.get("excluded_snapshots", []),
                "expiry_cohorts": list(sample.get("expiry_cohorts") or []),
                "independent_expiry_cohorts": sample.get("independent_expiry_cohorts"),
                "observation_count": sample.get("observation_count"),
                "sample_size_basis": sample.get("sample_size_basis"),
                "settlement_basis": sample.get("settlement_basis"),
                "settlement_note": sample.get("settlement_note"),
                "snapshot_count": sample.get("snapshot_count"),
                "snapshot_date_count": sample.get("snapshot_date_count"),
                "validated_snapshot_count": sample.get("validated_snapshot_count"),
            },
            evidence_class="research_signal_artifact",
        )
    if "bands" in value:
        projected_bands: dict[str, Any] = {}
        for band_name, band in sorted((value.get("bands") or {}).items()):
            band_row = dict(band or {})
            unexpected = sorted(set(band_row) - _SIGNAL_BAND_FIELDS)
            if unexpected:
                raise ValueError(
                    f"publication blocked: unapproved public field bands.{band_name}.{unexpected[0]}"
                )
            projected_bands[str(band_name)] = _annotate_numeric_field_evidence(
                {key: band_row.get(key) for key in sorted(band_row)},
                evidence_class="research_signal_artifact",
            )
        projected["bands"] = projected_bands
    if "cohorts" in value:
        cohorts = []
        for item in value.get("cohorts") or []:
            row = dict(item or {})
            unexpected = sorted(set(row) - _SIGNAL_COHORT_FIELDS)
            if unexpected:
                raise ValueError(
                    f"publication blocked: unapproved public field cohorts.{unexpected[0]}"
                )
            cohorts.append(
                _annotate_numeric_field_evidence(
                    {
                        key: row.get(key)
                        for key in sorted(row)
                    },
                    evidence_class="research_signal_artifact",
                )
            )
        projected["cohorts"] = cohorts
    if "signals" in value:
        signals: dict[str, Any] = {}
        for signal_name, measurement in sorted((value.get("signals") or {}).items()):
            row = dict(measurement or {})
            unexpected = sorted(set(row) - _SIGNAL_MEASUREMENT_FIELDS)
            if unexpected:
                raise ValueError(
                    f"publication blocked: unapproved public field signals.{signal_name}.{unexpected[0]}"
                )
            projected_row: dict[str, Any] = {
                "status": row.get("status"),
                "reason_code": row.get("reason_code"),
                "definition": row.get("definition"),
                "observation_count": row.get("observation_count"),
                "independent_expiry_cohorts": row.get("independent_expiry_cohorts"),
                "measured_date_count": row.get("measured_date_count"),
                "effective_sample_size": row.get("effective_sample_size"),
                "effective_sample_basis": row.get("effective_sample_basis"),
                "evidence_verdict": row.get("evidence_verdict"),
            }
            if "information_coefficient" in row and isinstance(
                row.get("information_coefficient"), dict
            ):
                ic = dict(row.get("information_coefficient") or {})
                unexpected_ic = sorted(set(ic) - _SIGNAL_INFORMATION_COEFFICIENT_FIELDS)
                if unexpected_ic:
                    raise ValueError(
                        "publication blocked: unapproved public field "
                        f"signals.{signal_name}.information_coefficient.{unexpected_ic[0]}"
                    )
                projected_row["information_coefficient"] = _annotate_numeric_field_evidence(
                    {key: ic.get(key) for key in sorted(ic)},
                    evidence_class="research_signal_artifact",
                )
            if "raw_information_coefficient" in row and isinstance(
                row.get("raw_information_coefficient"), dict
            ):
                raw_ic = dict(row.get("raw_information_coefficient") or {})
                unexpected_raw_ic = sorted(set(raw_ic) - _SIGNAL_RAW_IC_FIELDS)
                if unexpected_raw_ic:
                    raise ValueError(
                        "publication blocked: unapproved public field "
                        f"signals.{signal_name}.raw_information_coefficient.{unexpected_raw_ic[0]}"
                    )
                projected_row["raw_information_coefficient"] = _annotate_numeric_field_evidence(
                    {key: raw_ic.get(key) for key in sorted(raw_ic)},
                    evidence_class="research_signal_artifact",
                )
            if "per_date" in row:
                per_date_rows = []
                for per_date in row.get("per_date") or []:
                    per_date_row = dict(per_date or {})
                    unexpected_per_date = sorted(set(per_date_row) - _SIGNAL_PER_DATE_FIELDS)
                    if unexpected_per_date:
                        raise ValueError(
                            "publication blocked: unapproved public field "
                            f"signals.{signal_name}.per_date.{unexpected_per_date[0]}"
                        )
                    per_date_rows.append(
                        _annotate_numeric_field_evidence(
                            {key: per_date_row.get(key) for key in sorted(per_date_row)},
                            evidence_class="research_signal_artifact",
                        )
                    )
                projected_row["per_date"] = per_date_rows
            if "buckets" in row:
                buckets = []
                for bucket in row.get("buckets") or []:
                    bucket_row = dict(bucket or {})
                    unexpected_bucket = sorted(set(bucket_row) - _SIGNAL_BUCKET_FIELDS)
                    if unexpected_bucket:
                        raise ValueError(
                            "publication blocked: unapproved public field "
                            f"signals.{signal_name}.buckets.{unexpected_bucket[0]}"
                        )
                    buckets.append(
                        _annotate_numeric_field_evidence(
                            {key: bucket_row.get(key) for key in sorted(bucket_row)},
                            evidence_class="research_signal_artifact",
                        )
                    )
                projected_row["buckets"] = buckets
            signals[str(signal_name)] = projected_row
        projected["signals"] = signals
    unexpected_root = sorted(
        set(value)
        - {
            "schema_version",
            "captured_at",
            "generated_at",
            "research_only",
            "status",
            "headline",
            "summary",
            "bands",
            "cohorts",
            "reason_codes",
            "config",
            "sample",
            "signals",
            "note",
            "excluded_snapshots",
            "snapshot_count",
            "pre_registration",
            "signal_definitions",
            "t_stat_threshold",
        }
    )
    if unexpected_root:
        raise ValueError(
            f"publication blocked: unapproved public field {unexpected_root[0]}"
        )
    return projected


def _project_series_artifact(value: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for field in (
        "schema_version",
        "captured_at",
        "generated_at",
        "research_only",
        "status",
        "primary_series",
        "primary_series_reason",
        "instrument_count",
        "capture_count",
        "truncated_instruments",
    ):
        if field in value:
            projected[field] = value.get(field)
    if "reason_codes" in value:
        projected["reason_codes"] = list(value.get("reason_codes") or [])
    if "capture_dates" in value:
        projected["capture_dates"] = list(value.get("capture_dates") or [])
    if "cannot_tell" in value:
        projected["cannot_tell"] = list(value.get("cannot_tell") or [])
    if "config" in value:
        config = dict(value.get("config") or {})
        unexpected = sorted(set(config) - _SERIES_CONFIG_FIELDS)
        if unexpected:
            raise ValueError(
                f"publication blocked: unapproved public field config.{unexpected[0]}"
            )
        projected["config"] = {key: config.get(key) for key in sorted(config)}
    if "excluded_captures" in value:
        excluded = []
        for item in value.get("excluded_captures") or []:
            row = dict(item or {})
            unexpected = sorted(set(row) - _SERIES_EXCLUDED_CAPTURE_FIELDS)
            if unexpected:
                raise ValueError(
                    "publication blocked: unapproved public field "
                    f"excluded_captures.{unexpected[0]}"
                )
            excluded.append({key: row.get(key) for key in sorted(row)})
        projected["excluded_captures"] = excluded
    if "instruments" in value:
        instruments = []
        for item in value.get("instruments") or []:
            row = dict(item or {})
            unexpected = sorted(set(row) - _SERIES_INSTRUMENT_FIELDS)
            if unexpected:
                raise ValueError(
                    f"publication blocked: unapproved public field instruments.{unexpected[0]}"
                )
            instrument = {
                "instrument_name": row.get("instrument_name"),
                "expiry_date": row.get("expiry_date"),
                "option_type": row.get("option_type"),
                "strike_price": row.get("strike_price"),
                "capture_date_count": row.get("capture_date_count"),
                "missing_date_count": row.get("missing_date_count"),
            }
            latest = dict(row.get("latest") or {})
            unexpected_latest = sorted(set(latest) - _SERIES_LATEST_FIELDS)
            if unexpected_latest:
                raise ValueError(
                    "publication blocked: unapproved public field "
                    f"instruments.latest.{unexpected_latest[0]}"
                )
            instrument["latest"] = _annotate_numeric_field_evidence(
                {key: latest.get(key) for key in sorted(latest)},
                evidence_class="research_series_artifact",
            )
            residual = dict(row.get("residual_z") or {})
            unexpected_residual = sorted(set(residual) - _SERIES_SUMMARY_FIELDS)
            if unexpected_residual:
                raise ValueError(
                    "publication blocked: unapproved public field "
                    f"instruments.residual_z.{unexpected_residual[0]}"
                )
            instrument["residual_z"] = _annotate_numeric_field_evidence(
                {key: residual.get(key) for key in sorted(residual)},
                evidence_class="research_series_artifact",
            )
            persistence = dict(row.get("persistence") or {})
            unexpected_persistence = sorted(set(persistence) - _SERIES_PERSISTENCE_FIELDS)
            if unexpected_persistence:
                raise ValueError(
                    "publication blocked: unapproved public field "
                    f"instruments.persistence.{unexpected_persistence[0]}"
                )
            instrument["persistence"] = _annotate_numeric_field_evidence(
                {key: persistence.get(key) for key in sorted(persistence)},
                evidence_class="research_series_artifact",
            )
            points = []
            for point in row.get("points") or []:
                point_row = dict(point or {})
                unexpected_point = sorted(set(point_row) - _SERIES_POINT_FIELDS)
                if unexpected_point:
                    raise ValueError(
                        "publication blocked: unapproved public field "
                        f"instruments.points.{unexpected_point[0]}"
                    )
                points.append(
                    _annotate_numeric_field_evidence(
                        {key: point_row.get(key) for key in sorted(point_row)},
                        evidence_class="research_series_artifact",
                    )
                )
            instrument["points"] = points
            instruments.append(_annotate_numeric_field_evidence(instrument, evidence_class="research_series_artifact"))
        projected["instruments"] = instruments
    if "points" in value:
        points = []
        for item in value.get("points") or []:
            row = dict(item or {})
            unexpected = sorted(set(row) - {"observed_at", "smile_residual_z", "model_delta"})
            if unexpected:
                raise ValueError(
                    f"publication blocked: unapproved public field points.{unexpected[0]}"
                )
            points.append(
                _annotate_numeric_field_evidence(
                    {key: row.get(key) for key in sorted(row)},
                    evidence_class="research_series_artifact",
                )
            )
        projected["points"] = points
    unexpected_root = sorted(
        set(value)
        - {
            "schema_version",
            "captured_at",
            "generated_at",
            "research_only",
            "status",
            "primary_series",
            "primary_series_reason",
            "instrument_count",
            "capture_count",
            "truncated_instruments",
            "reason_codes",
            "capture_dates",
            "cannot_tell",
            "config",
            "excluded_captures",
            "instruments",
            "points",
        }
    )
    if unexpected_root:
        raise ValueError(
            f"publication blocked: unapproved public field {unexpected_root[0]}"
        )
    return projected


def _artifact_date(value: Any, *, field: str) -> date:
    if not isinstance(value, str) or not value:
        raise ValueError(f"publication blocked: {field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"publication blocked: {field} must be an ISO date"
        ) from exc


def _has_artifact_value(value: Any) -> bool:
    return value is not None and value != ""


def _require_artifact_timestamp_at_or_before(
    value: Any,
    *,
    captured_dt: datetime,
    description: str,
    field: str,
) -> None:
    observed_dt = _parse_timestamp(value, field=f"{description}.{field}")
    if observed_dt > captured_dt:
        raise ValueError(
            f"publication blocked: {description}.{field} is after the snapshot cutoff"
        )


def _require_artifact_date_at_or_before(
    value: Any,
    *,
    captured_dt: datetime,
    description: str,
    field: str,
) -> None:
    if _artifact_date(value, field=f"{description}.{field}") > captured_dt.date():
        raise ValueError(
            f"publication blocked: {description}.{field} is after the snapshot cutoff"
        )


def _validate_artifact_capture_alignment(
    payload: dict[str, Any],
    *,
    captured_dt: datetime,
    description: str,
) -> None:
    clock_fields = [
        field
        for field in ("captured_at", "generated_at")
        if _has_artifact_value(payload.get(field))
    ]
    if not clock_fields:
        raise ValueError(
            f"publication blocked: {description} must declare captured_at or generated_at"
        )
    for field in clock_fields:
        artifact_dt = _parse_timestamp(
            payload[field],
            field=f"{description}.{field}",
        )
        if artifact_dt != captured_dt:
            raise ValueError(
                f"publication blocked: {description}.{field} must equal snapshot.captured_at"
            )

    if description == "signal artifact":
        excluded = list(payload.get("excluded_snapshots") or [])
        sample = payload.get("sample")
        if isinstance(sample, dict):
            excluded.extend(sample.get("excluded_snapshots") or [])
        for index, item in enumerate(excluded):
            row = dict(item or {})
            if _has_artifact_value(row.get("captured_at")):
                _require_artifact_timestamp_at_or_before(
                    row["captured_at"],
                    captured_dt=captured_dt,
                    description=description,
                    field=f"excluded_snapshots[{index}].captured_at",
                )
        for index, item in enumerate(payload.get("cohorts") or []):
            row = dict(item or {})
            for field in ("first_capture_date", "last_capture_date"):
                if _has_artifact_value(row.get(field)):
                    _require_artifact_date_at_or_before(
                        row[field],
                        captured_dt=captured_dt,
                        description=description,
                        field=f"cohorts[{index}].{field}",
                    )
        for signal_name, measurement in (payload.get("signals") or {}).items():
            row = dict(measurement or {})
            for index, per_date in enumerate(row.get("per_date") or []):
                per_date_row = dict(per_date or {})
                if _has_artifact_value(per_date_row.get("snapshot_date")):
                    _require_artifact_date_at_or_before(
                        per_date_row["snapshot_date"],
                        captured_dt=captured_dt,
                        description=description,
                        field=(
                            f"signals.{signal_name}.per_date[{index}].snapshot_date"
                        ),
                    )
        return

    for index, value in enumerate(payload.get("capture_dates") or []):
        _require_artifact_date_at_or_before(
            value,
            captured_dt=captured_dt,
            description=description,
            field=f"capture_dates[{index}]",
        )
    for index, item in enumerate(payload.get("excluded_captures") or []):
        row = dict(item or {})
        if _has_artifact_value(row.get("captured_at")):
            _require_artifact_timestamp_at_or_before(
                row["captured_at"],
                captured_dt=captured_dt,
                description=description,
                field=f"excluded_captures[{index}].captured_at",
            )
    for instrument_index, item in enumerate(payload.get("instruments") or []):
        row = dict(item or {})
        latest = dict(row.get("latest") or {})
        if _has_artifact_value(latest.get("date")):
            _require_artifact_date_at_or_before(
                latest["date"],
                captured_dt=captured_dt,
                description=description,
                field=f"instruments[{instrument_index}].latest.date",
            )
        for point_index, point in enumerate(row.get("points") or []):
            point_row = dict(point or {})
            if _has_artifact_value(point_row.get("date")):
                _require_artifact_date_at_or_before(
                    point_row["date"],
                    captured_dt=captured_dt,
                    description=description,
                    field=(
                        f"instruments[{instrument_index}].points[{point_index}].date"
                    ),
                )
    for index, item in enumerate(payload.get("points") or []):
        row = dict(item or {})
        if _has_artifact_value(row.get("observed_at")):
            _require_artifact_timestamp_at_or_before(
                row["observed_at"],
                captured_dt=captured_dt,
                description=description,
                field=f"points[{index}].observed_at",
            )


def _build_change_payload(vrp_status: dict[str, Any]) -> dict[str, Any]:
    series = list(vrp_status.get("series") or [])
    if len(series) < 2:
        return {
            "status": "unavailable",
            "prior_observed_at": None,
            "current_observed_at": series[-1].get("observed_at") if series else None,
            "vrp_percent_points_delta": None,
            "dvol_percent_delta": None,
            "rv30_percent_delta": None,
            "percentile_delta": None,
            "band_changed": None,
        }
    previous = dict(series[-2] or {})
    current = dict(series[-1] or {})
    return {
        "status": "available",
        "prior_observed_at": previous.get("observed_at"),
        "current_observed_at": current.get("observed_at"),
        "vrp_percent_points_delta": _difference(
            current.get("vrp_percent_points"),
            previous.get("vrp_percent_points"),
        ),
        "dvol_percent_delta": _difference(
            current.get("dvol_percent"),
            previous.get("dvol_percent"),
        ),
        "rv30_percent_delta": _difference(
            current.get("rv30_percent"),
            previous.get("rv30_percent"),
        ),
        "percentile_delta": _difference(
            current.get("percentile"),
            previous.get("percentile"),
        ),
        "band_changed": current.get("band") != previous.get("band"),
    }


def _difference(current: Any, previous: Any) -> float | None:
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        return None
    if not isinstance(previous, (int, float)) or isinstance(previous, bool):
        return None
    return round(float(current) - float(previous), 6)


def _build_alert_payload(*, band: Any, is_stale_at_publish: bool) -> dict[str, Any]:
    if is_stale_at_publish:
        return {
            "level": "warning",
            "code": "PUBLISHED_EDITION_STALE",
            "message": "Published edition was already stale at publish time.",
        }
    if band in {"P90+", "P10-"}:
        return {
            "level": "notice",
            "code": str(band),
            "message": f"VRP headline reached the {band} public band.",
        }
    return {
        "level": "info",
        "code": "NO_CHANGE_ALERT",
        "message": "No exceptional public alert condition is active.",
    }


def _split_thermo_series(
    thermo: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    series = list(thermo.get("series") or [])
    recent = dict(thermo)
    recent["series"] = series[-RECENT_THERMO_WINDOW_DAYS:]
    recent["series_window_days"] = RECENT_THERMO_WINDOW_DAYS
    by_year: dict[str, dict[str, Any]] = {}
    for point in series:
        observed_at = str((point or {}).get("observed_at") or "")
        year = observed_at[:4]
        if len(year) != 4 or not year.isdigit():
            continue
        shard = by_year.setdefault(
            year,
            {
                **dict(thermo),
                "series": [],
                "series_window": "calendar_year",
                "series_year": year,
            },
        )
        shard["series"].append(point)
    return recent, by_year


def _thermo_year_shard_paths(series: list[dict[str, Any]]) -> list[str]:
    years = sorted(
        {
            str((point or {}).get("observed_at") or "")[:4]
            for point in series
            if str((point or {}).get("observed_at") or "")[:4].isdigit()
        }
    )
    return [f"/api/v1/thermo/by-year/{year}.json" for year in years]


def _build_robots_txt(*, site_origin: str) -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {site_origin}/sitemap.xml\n"


def _build_sitemap_xml(*, site_origin: str, edition_slug: str) -> str:
    root_url = xml_escape(f"{site_origin}/")
    edition_url = xml_escape(f"{site_origin}/editions/{edition_slug}/")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{root_url}</loc></url>\n"
        f"  <url><loc>{edition_url}</loc></url>\n"
        "</urlset>\n"
    )


def _write_publication_outputs(
    *,
    out_path: Path,
    build_root: Path,
    public_report: dict[str, Any],
    public_signal_artifact: dict[str, Any],
    public_series_artifact: dict[str, Any],
    summary: dict[str, Any],
    thermo: dict[str, Any],
    candidates: dict[str, Any],
    signal: dict[str, Any],
    health: dict[str, Any],
    status_payload: dict[str, Any],
    site_origin: str,
    edition_slug: str,
    copy_bundle: bool,
) -> None:
    if copy_bundle:
        _copy_web_bundle(
            build_root,
            out_path,
            summary=summary,
            site_origin=site_origin,
        )
    _write_json(out_path / "research" / "report", public_report)
    _write_json(out_path / "research" / "signal", public_signal_artifact)
    _write_json(out_path / "research" / "series", public_series_artifact)
    _write_json(out_path / "api" / "v1" / "summary.json", summary)
    _write_json(out_path / "api" / "v1" / "thermo.json", thermo)
    recent_thermo, yearly_thermo = _split_thermo_series(thermo)
    _write_json(out_path / "api" / "v1" / "thermo" / "recent.json", recent_thermo)
    for year, payload in yearly_thermo.items():
        _write_json(out_path / "api" / "v1" / "thermo" / "by-year" / f"{year}.json", payload)
    _write_json(out_path / "api" / "v1" / "candidates.json", candidates)
    _write_json(out_path / "api" / "v1" / "signal.json", signal)
    _write_json(out_path / "api" / "v1" / "health.json", health)
    _write_json(
        out_path / "api" / "openapi.json",
        build_public_openapi(
            summary=summary,
            thermo=thermo,
            thermo_recent=recent_thermo,
            thermo_years=list(yearly_thermo.values())
            or [
                {
                    **thermo,
                    "series": [],
                    "series_window": "calendar_year",
                    "series_year": edition_slug[:4],
                }
            ],
            candidates=candidates,
            signal=signal,
            health=health,
            research_report=public_report,
            research_signal=public_signal_artifact,
            research_series=public_series_artifact,
        ),
    )
    _write_text(out_path / "_headers", _headers_text())
    _write_text(out_path / "robots.txt", _build_robots_txt(site_origin=site_origin))
    _write_text(
        out_path / "sitemap.xml",
        _build_sitemap_xml(site_origin=site_origin, edition_slug=edition_slug),
    )
    _write_status_pages(out_path, status_payload)


def _write_edition_archive(
    out_path: Path,
    *,
    edition_slug: str,
    site_origin: str,
    summary: dict[str, Any],
) -> None:
    edition_root = out_path / "editions" / edition_slug
    if edition_root.exists():
        raise ValueError("publication blocked: edition archive already exists")
    for relative_path in _relative_file_paths(out_path):
        if relative_path.startswith("editions/"):
            continue
        source = out_path / relative_path
        target = edition_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    edition_index = edition_root / "index.html"
    _write_html(
        edition_index,
        _rewrite_index_html(
            edition_index.read_text(encoding="utf-8"),
            summary=summary,
            page_url=f"{site_origin}/editions/{edition_slug}/",
            image_url=f"{site_origin}/editions/{edition_slug}/og-card.png",
        ),
    )


def publish_site(
    *,
    snapshot: str,
    underlying_history: str,
    dvol_history: str,
    signal_artifact: str,
    series_artifact: str,
    publication_history: str,
    out: str,
    published_at: str,
    site_origin: str,
    git_sha: str | None = None,
    web_build: str | None = None,
) -> dict[str, Any]:
    """Build one deterministic static publication tree."""
    site_origin_value = validate_public_site_origin(site_origin)
    snapshot_path = _require_file(snapshot, label="snapshot input")
    underlying_path = _require_file(underlying_history, label="underlying history input")
    dvol_path = _require_file(dvol_history, label="DVOL history input")
    signal_path = _require_file(signal_artifact, label="signal artifact input")
    series_path = _require_file(series_artifact, label="series artifact input")
    publication_history_path = _require_file(
        publication_history,
        label="publication history input",
    )
    build_root = _resolve_web_build(web_build)
    out_path = _prepare_output_directory(out)

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
    publication_history_payload = read_json_object_from_regular_file(
        publication_history_path,
        max_bytes=4 * 1024 * 1024,
        description="publication history",
    )
    _validate_publication_payload(signal_payload, description="signal artifact")
    _validate_publication_payload(series_payload, description="series artifact")
    git_sha_value = _validate_git_sha(git_sha)
    git_provenance = _build_git_provenance(git_sha_value)

    captured_at = str(snapshot_payload.get("captured_at") or "")
    captured_dt = _parse_timestamp(captured_at, field="snapshot.captured_at")
    _validate_artifact_capture_alignment(
        signal_payload,
        captured_dt=captured_dt,
        description="signal artifact",
    )
    _validate_artifact_capture_alignment(
        series_payload,
        captured_dt=captured_dt,
        description="series artifact",
    )
    public_signal_artifact = _project_signal_artifact(signal_payload)
    public_series_artifact = _project_series_artifact(series_payload)
    underlying_payload = _trim_history_to_capture_clock(
        underlying_payload,
        captured_dt=captured_dt,
        label="underlying history",
    )
    dvol_payload = _trim_history_to_capture_clock(
        dvol_payload,
        captured_dt=captured_dt,
        label="DVOL history",
    )
    published_dt = _parse_timestamp(published_at, field="published_at")
    if published_dt < captured_dt:
        raise ValueError("published_at must not be earlier than snapshot.captured_at")
    edition_slug = _timestamp(published_dt)[:10]
    next_expected_dt = captured_dt + PUBLISH_INTERVAL
    stale_after_dt = captured_dt + (PUBLISH_INTERVAL * 2)
    is_stale_at_publish = published_dt >= stale_after_dt
    public_publication_history = build_publication_history(
        publication_history_payload,
        published_at=_timestamp(published_dt),
    )

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
    vrp_minimum_sample_count = int(raw_vrp.get("minimum_series_sample_count") or 0)
    if (
        raw_vrp.get("status") != "validated"
        or vrp_minimum_sample_count <= 0
        or vrp_sample_count < vrp_minimum_sample_count
    ):
        raise ValueError(
            "publication blocked: VRP status is "
            f"{raw_vrp.get('status') or 'unavailable'}"
        )
    vrp_status = _project_vrp_status(raw_vrp)
    release_gates = build_release_gates(
        research_publication_ready=False,
        publication_evidence={"data_quality": data_status},
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
    summary = _build_summary(
        report=public_report,
        vrp_status=vrp_status,
        is_stale_at_publish=is_stale_at_publish,
        publication_history=public_publication_history,
    )
    thermo = _build_thermo(vrp_status=vrp_status, report=public_report)
    candidates = _build_candidates(report=public_report)
    signal = _build_signal(signal_payload=public_signal_artifact, report=public_report)
    health = _build_health(
        report=public_report,
        is_stale_at_publish=is_stale_at_publish,
        manifest_verification={"status": "invalid", "artifact_count": 0, "errors": []},
        publication_history=public_publication_history,
    )
    status_payload = _build_status(report=public_report, health=health)

    publication_inputs = _build_publication_inputs(
        snapshot_payload=snapshot_payload,
        underlying_payload=underlying_payload,
        dvol_payload=dvol_payload,
        signal_payload=signal_payload,
        series_payload=series_payload,
        publication_history_payload=publication_history_payload,
        published_dt=published_dt,
        git_provenance=git_provenance,
        site_origin=site_origin_value,
    )

    _write_publication_outputs(
        out_path=out_path,
        build_root=build_root,
        public_report=public_report,
        public_signal_artifact=public_signal_artifact,
        public_series_artifact=public_series_artifact,
        summary=summary,
        thermo=thermo,
        candidates=candidates,
        signal=signal,
        health=health,
        status_payload=status_payload,
        site_origin=site_origin_value,
        edition_slug=edition_slug,
        copy_bundle=True,
    )
    manifest = _build_manifest(
        out_path=out_path,
        record=record,
        report=public_report,
        publication_inputs=publication_inputs,
        build_root=build_root,
    )
    _write_json(out_path / ".well-known" / "publish-manifest.json", manifest)
    _write_json(out_path / "api" / "v1" / "manifest.json", manifest)
    _ensure_publication_privacy(out_path)
    manifest_verification = _load_manifest_verification(out_path, manifest)

    release_gates = _build_release_gates_from_disk(
        report=report,
        out_path=out_path,
        manifest_verification=manifest_verification,
    )
    full_surface["release_gates"] = release_gates
    report["full_system_surface"] = full_surface
    public_report = _build_public_report(report)
    summary = _build_summary(
        report=public_report,
        vrp_status=vrp_status,
        is_stale_at_publish=is_stale_at_publish,
        publication_history=public_publication_history,
    )
    thermo = _build_thermo(vrp_status=vrp_status, report=public_report)
    candidates = _build_candidates(report=public_report)
    signal = _build_signal(signal_payload=public_signal_artifact, report=public_report)
    health = _build_health(
        report=public_report,
        is_stale_at_publish=is_stale_at_publish,
        manifest_verification=manifest_verification,
        publication_history=public_publication_history,
    )
    status_payload = _build_status(report=public_report, health=health)
    _write_publication_outputs(
        out_path=out_path,
        build_root=build_root,
        public_report=public_report,
        public_signal_artifact=public_signal_artifact,
        public_series_artifact=public_series_artifact,
        summary=summary,
        thermo=thermo,
        candidates=candidates,
        signal=signal,
        health=health,
        status_payload=status_payload,
        site_origin=site_origin_value,
        edition_slug=edition_slug,
        copy_bundle=False,
    )
    manifest = _build_manifest(
        out_path=out_path,
        record=record,
        report=public_report,
        publication_inputs=publication_inputs,
        build_root=build_root,
    )
    _write_json(out_path / ".well-known" / "publish-manifest.json", manifest)
    _write_json(out_path / "api" / "v1" / "manifest.json", manifest)
    _ensure_publication_privacy(out_path)
    manifest_verification = _load_manifest_verification(out_path, manifest)
    if manifest_verification["status"] != "verified":
        raise ValueError(
            "publication blocked: publish manifest could not be verified"
        )
    health = _build_health(
        report=public_report,
        is_stale_at_publish=is_stale_at_publish,
        manifest_verification=manifest_verification,
        publication_history=public_publication_history,
    )
    status_payload = _build_status(report=public_report, health=health)
    _write_json(out_path / "api" / "v1" / "health.json", health)
    _write_status_pages(out_path, status_payload)
    manifest = _build_manifest(
        out_path=out_path,
        record=record,
        report=public_report,
        publication_inputs=publication_inputs,
        build_root=build_root,
    )
    _write_json(out_path / ".well-known" / "publish-manifest.json", manifest)
    _write_json(out_path / "api" / "v1" / "manifest.json", manifest)
    _ensure_publication_privacy(out_path)
    _write_edition_archive(
        out_path,
        edition_slug=edition_slug,
        site_origin=site_origin_value,
        summary=summary,
    )
    manifest = _build_manifest(
        out_path=out_path,
        record=record,
        report=public_report,
        publication_inputs=publication_inputs,
        build_root=build_root,
    )
    _write_json(out_path / ".well-known" / "publish-manifest.json", manifest)
    _write_json(out_path / "api" / "v1" / "manifest.json", manifest)
    _ensure_publication_privacy(out_path)
    manifest_verification = _load_manifest_verification(out_path, manifest)
    if manifest_verification["status"] != "verified":
        raise ValueError(
            "publication blocked: publish manifest could not be verified"
        )
    manifest_text = canonical_json_text(manifest)
    manifest_sha = sha256(manifest_text.encode("utf-8")).hexdigest()

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
    evaluation_clock = str(
        ((report.get("runtime_context") or {}).get("evaluation_clock")) or ""
    )
    publication_reason_codes = list(report.get("reason_codes") or [])
    candidate_research = _project_candidate_research(
        report.get("candidate_research"),
        evaluation_clock=evaluation_clock,
        publication_reason_codes=publication_reason_codes,
    )
    strategy_research = _project_strategy_research(
        report.get("strategy_research"),
        published=bool((report.get("runtime_context") or {}).get("mode") == "published"),
        evaluation_clock=evaluation_clock,
        publication_reason_codes=publication_reason_codes,
    )
    ev_candidate_scanner = _project_ev_candidate_scanner(
        report.get("ev_candidate_scanner"),
        evaluation_clock=evaluation_clock,
        publication_reason_codes=publication_reason_codes,
    )
    return {
        "schema_version": report.get("schema_version"),
        "generated_at": report.get("generated_at"),
        "action": report.get("action"),
        "mode": report.get("mode"),
        "effective_mode": report.get("effective_mode"),
        "risk_state": report.get("risk_state"),
        "reason_codes": publication_reason_codes,
        "event_status": _project_exchange_event_status(report),
        "runtime_context": _project_runtime_context(report.get("runtime_context")),
        "publish_edition": _project_publish_edition(report.get("publish_edition")),
        "vrp_status": _project_public_vrp_status(report.get("vrp_status")),
        "blocked_outputs": list(report.get("blocked_outputs") or []),
        "data_trust": _project_data_trust(report.get("data_trust")),
        "data_status": _project_data_status(report.get("data_status")),
        "calibration_status": _project_status_pair(report.get("calibration_status")),
        "backtest_status": _project_status_pair(report.get("backtest_status")),
        "vol_surface_status": _project_vol_surface_status(report.get("vol_surface_status")),
        "candidate_research": candidate_research,
        "strategy_research": strategy_research,
        "ev_candidate_scanner": ev_candidate_scanner,
        "mode_gate": _project_mode_gate(report.get("mode_gate")),
        "full_system_surface": _project_full_system_surface(
            report.get("full_system_surface")
        ),
    }


def _project_exchange_event_status(report: dict[str, Any]) -> dict[str, Any]:
    data_status = dict(report.get("data_status") or {})
    feed_coverage = dict(data_status.get("feed_coverage") or {})
    feeds = dict(feed_coverage.get("feeds") or {})
    events = dict(feeds.get("events") or {})
    market = dict(
        ((report.get("strategy_research") or {}).get("analysis") or {}).get("market")
        or {}
    )
    source_endpoint = events.get("source_endpoint")
    source = (
        "deribit_public_status" if source_endpoint == "public/status" else None
    )
    source_status_value = events.get("status")
    source_status = source_status_value if isinstance(source_status_value, str) else None
    freshness_status_value = events.get("freshness_status")
    freshness_status = (
        freshness_status_value if isinstance(freshness_status_value, str) else None
    )
    scope_value = events.get("scope")
    scope = scope_value if isinstance(scope_value, str) else None
    source_is_current = (
        source is not None
        and source_status == "available"
        and freshness_status == "fresh"
        and scope == "exchange_native_only"
    )
    raw_score = market.get("event_score")
    event_score = (
        float(raw_score)
        if source_is_current
        and isinstance(raw_score, (int, float))
        and not isinstance(raw_score, bool)
        and isfinite(float(raw_score))
        else None
    )

    if not source_is_current:
        reason_code_value = events.get("reason_code")
        reason_code = (
            reason_code_value
            if isinstance(reason_code_value, str) and reason_code_value
            else None
        )
        if not reason_code:
            if source_status == "missing":
                reason_code = "EVENTS_MISSING"
            elif freshness_status == "stale":
                reason_code = "EVENTS_FEED_STALE"
            else:
                reason_code = "EVENT_SOURCE_UNAVAILABLE"
        exchange_lock_state = "unknown"
        event_score = None
    elif event_score is None:
        exchange_lock_state = "unknown"
        reason_code = "EXCHANGE_LOCK_STATE_UNAVAILABLE"
    elif event_score == 0.0:
        exchange_lock_state = "normal"
        reason_code = "EXCHANGE_NO_ACTIVE_LOCKS"
    elif event_score == 0.8:
        exchange_lock_state = "partial"
        reason_code = "EXCHANGE_PARTIAL_LOCK"
    elif event_score == 1.0:
        exchange_lock_state = "full"
        reason_code = "EXCHANGE_FULL_LOCK"
    else:
        exchange_lock_state = "unknown"
        reason_code = "EVENT_SCORE_NOT_EXCHANGE_LOCK_STATE"

    return {
        "source": source,
        "source_status": source_status,
        "scope": scope,
        "macro_calendar_covered": False,
        "event_score": event_score,
        "exchange_lock_state": exchange_lock_state,
        "reason_code": reason_code,
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


def _append_public_reason_code(reason_codes: list[str] | None, code: str) -> None:
    if reason_codes is None or not code or code in reason_codes:
        return
    reason_codes.append(code)


def _resolve_public_candidate_dte_days(
    candidate: dict[str, Any],
    *,
    evaluation_clock: str,
) -> tuple[float | None, str | None]:
    explicit_value = candidate.get("dte_days")
    if explicit_value is None:
        explicit = None
    elif isinstance(explicit_value, (int, float)) and not isinstance(explicit_value, bool):
        explicit = round(float(explicit_value), 6)
    else:
        return None, DTE_EVIDENCE_CONFLICT
    expiry_date = candidate.get("expiry_date")
    if not isinstance(expiry_date, str) or not expiry_date:
        return None, DTE_EVIDENCE_CONFLICT
    try:
        expiry_dt = datetime.fromisoformat(expiry_date)
        evaluation_dt = _parse_timestamp(evaluation_clock, field="evaluation_clock")
    except ValueError:
        return None, DTE_EVIDENCE_CONFLICT
    derived = float(max((expiry_dt.date() - evaluation_dt.date()).days, 0))
    if explicit is None:
        return derived, None
    if abs(explicit - derived) > 1.0:
        return derived, DTE_EVIDENCE_CONFLICT
    return explicit, None


def _project_public_candidate_dte_days(
    candidate: dict[str, Any],
    *,
    evaluation_clock: str,
    publication_reason_codes: list[str] | None = None,
) -> float | None:
    dte_days, reason_code = _resolve_public_candidate_dte_days(
        candidate,
        evaluation_clock=evaluation_clock,
    )
    _append_public_reason_code(publication_reason_codes, reason_code or "")
    return dte_days


def _project_call_credit_candidate(
    value: Any,
    *,
    evaluation_clock: str,
    publication_reason_codes: list[str] | None = None,
) -> dict[str, Any] | None:
    candidate = dict(value or {})
    dte_days, reason_code = _resolve_public_candidate_dte_days(
        candidate,
        evaluation_clock=evaluation_clock,
    )
    if reason_code:
        _append_public_reason_code(publication_reason_codes, reason_code)
        return None
    return {
        "candidate_id": candidate.get("candidate_id"),
        "decision": candidate.get("decision"),
        "structure_type": candidate.get("structure_type"),
        "sell_leg_instrument_name": candidate.get("sell_leg_instrument_name"),
        "buy_leg_instrument_name": candidate.get("buy_leg_instrument_name"),
        "sell_leg_strike_price": candidate.get("sell_leg_strike_price"),
        "buy_leg_strike_price": candidate.get("buy_leg_strike_price"),
        "expiry_date": candidate.get("expiry_date"),
        "dte_days": dte_days,
        "model_delta": candidate.get("model_delta"),
        "net_credit": candidate.get("net_credit"),
        "spread_width": candidate.get("spread_width"),
        "premium_currency": candidate.get("premium_currency"),
        "underlying_price": candidate.get("underlying_price"),
        "surface_quality": _project_surface_quality(candidate.get("surface_quality")),
    }


def _project_naked_candidate(
    value: Any,
    *,
    evaluation_clock: str,
    publication_reason_codes: list[str] | None = None,
) -> dict[str, Any] | None:
    candidate = dict(value or {})
    dte_days, reason_code = _resolve_public_candidate_dte_days(
        candidate,
        evaluation_clock=evaluation_clock,
    )
    if reason_code:
        _append_public_reason_code(publication_reason_codes, reason_code)
        return None
    return {
        "candidate_id": candidate.get("candidate_id"),
        "decision": candidate.get("decision"),
        "structure_type": candidate.get("structure_type"),
        "instrument_name": candidate.get("instrument_name"),
        "expiry_date": candidate.get("expiry_date"),
        "dte_days": dte_days,
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
    evaluation_clock: str,
    publication_reason_codes: list[str] | None = None,
) -> dict[str, Any] | None:
    bucket = dict(value or {})
    if not bucket:
        return None
    projected_buckets: dict[str, list[dict[str, Any]]] = {}
    for bucket_name in ("eligible", "review", "rejected"):
        rows: list[dict[str, Any]] = []
        for item in bucket.get(bucket_name) or []:
            projected = row_projector(
                item,
                evaluation_clock=evaluation_clock,
                publication_reason_codes=publication_reason_codes,
            )
            if projected is not None:
                rows.append(projected)
        projected_buckets[bucket_name] = rows
    return {
        "eligible": projected_buckets["eligible"],
        "review": projected_buckets["review"],
        "rejected": projected_buckets["rejected"],
    }


def _project_candidate_research(
    value: Any,
    *,
    evaluation_clock: str,
    publication_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    research = dict(value or {})
    summary = dict(research.get("summary") or {})
    naked_short_calls = _project_candidate_bucket(
        research.get("naked_short_calls"),
        row_projector=_project_naked_candidate,
        evaluation_clock=evaluation_clock,
        publication_reason_codes=publication_reason_codes,
    )
    call_credit_spreads = _project_candidate_bucket(
        research.get("call_credit_spreads"),
        row_projector=_project_call_credit_candidate,
        evaluation_clock=evaluation_clock,
        publication_reason_codes=publication_reason_codes,
    )
    all_buckets = [
        bucket
        for bucket in (naked_short_calls, call_credit_spreads)
        if isinstance(bucket, dict)
    ]
    projected_summary = {
        "eligible_call_credit_spreads": len((call_credit_spreads or {}).get("eligible") or []),
        "eligible_expiries": len(
            {
                str(row.get("expiry_date"))
                for bucket in all_buckets
                for row in bucket.get("eligible") or []
                if isinstance(row.get("expiry_date"), str) and row.get("expiry_date")
            }
        ),
        "eligible_naked_short_calls": len((naked_short_calls or {}).get("eligible") or []),
        "expiries_considered": len(
            {
                str(row.get("expiry_date"))
                for bucket in all_buckets
                for bucket_name in ("eligible", "review", "rejected")
                for row in bucket.get(bucket_name) or []
                if isinstance(row.get("expiry_date"), str) and row.get("expiry_date")
            }
        ),
        "rejected_call_credit_spreads": len((call_credit_spreads or {}).get("rejected") or []),
        "rejected_naked_short_calls": len((naked_short_calls or {}).get("rejected") or []),
        "review_call_credit_spreads": len((call_credit_spreads or {}).get("review") or []),
        "review_naked_short_calls": len((naked_short_calls or {}).get("review") or []),
    }
    if summary:
        summary.update(projected_summary)
    else:
        summary = projected_summary
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
        "naked_short_calls": naked_short_calls,
        "call_credit_spreads": call_credit_spreads,
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
    evaluation_clock: str,
    publication_reason_codes: list[str] | None = None,
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
                    "dte_days": _project_public_candidate_dte_days(
                        front_expiry,
                        evaluation_clock=evaluation_clock,
                        publication_reason_codes=publication_reason_codes,
                    ),
                    "atm_fitted_iv_percent": front_expiry.get("atm_fitted_iv_percent"),
                    "fit_quality_score": front_expiry.get("fit_quality_score"),
                    "no_arbitrage_pass": front_expiry.get("no_arbitrage_pass"),
                    "candidate_eligible": front_expiry.get("candidate_eligible"),
                },
                "next_expiry": {
                    "expiry_date": next_expiry.get("expiry_date"),
                    "dte_days": _project_public_candidate_dte_days(
                        next_expiry,
                        evaluation_clock=evaluation_clock,
                        publication_reason_codes=publication_reason_codes,
                    ),
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
        "playbook": _project_playbook(
            strategy.get("playbook"),
            published=published,
            evaluation_clock=evaluation_clock,
            publication_reason_codes=publication_reason_codes,
        ),
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


def _project_playbook(
    value: Any,
    *,
    published: bool = False,
    evaluation_clock: str,
    publication_reason_codes: list[str] | None = None,
) -> dict[str, Any] | None:
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
            "dte_days": _project_public_candidate_dte_days(
                candidate,
                evaluation_clock=evaluation_clock,
                publication_reason_codes=publication_reason_codes,
            ),
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


def _project_ev_candidate_scanner(
    value: Any,
    *,
    evaluation_clock: str,
    publication_reason_codes: list[str] | None = None,
) -> dict[str, Any] | None:
    scanner = dict(value or {})
    if not scanner:
        return None
    ranking_basis = dict(scanner.get("ranking_basis") or {})
    summary = dict(scanner.get("summary") or {})
    rows = []
    rejected_count = 0
    for row in scanner.get("ranked_candidates") or []:
        item = dict(row or {})
        dte_days, reason_code = _resolve_public_candidate_dte_days(
            item,
            evaluation_clock=evaluation_clock,
        )
        if reason_code:
            _append_public_reason_code(publication_reason_codes, reason_code)
            continue
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
                "expiry_date": item.get("expiry_date"),
                "dte_days": dte_days,
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
    if summary:
        summary.update(
            {
                "candidates_scanned": len(rows),
                "review_candidates": sum(row.get("action") == "REVIEW" for row in rows),
                "rejected_candidates": sum(row.get("action") == "REJECT" for row in rows),
            }
        )
    return {
        "status": scanner.get("status"),
        "score_status": scanner.get("score_status"),
        "reason_code": scanner.get("reason_code"),
        "summary": summary or scanner.get("summary"),
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


def _build_summary(
    *,
    report: dict[str, Any],
    vrp_status: dict[str, Any],
    is_stale_at_publish: bool,
    publication_history: dict[str, Any],
) -> dict[str, Any]:
    vrp_evidence_class = vrp_status.get("evidence_class")
    change = _build_change_payload(vrp_status)
    current = {
        "vrp_percent_points": vrp_status.get("current_vrp_percent_points"),
        "dvol_percent": vrp_status.get("current_dvol_percent"),
        "rv30_percent": vrp_status.get("current_rv30_percent"),
        "percentile": vrp_status.get("percentile"),
        "band": vrp_status.get("band"),
        "evaluation_at": vrp_status.get("evaluation_at"),
        "dvol_observed_at": vrp_status.get("dvol_observed_at"),
        "underlying_observed_at": vrp_status.get("underlying_observed_at"),
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
        "change": change,
        "alert": _build_alert_payload(
            band=vrp_status.get("band"),
            is_stale_at_publish=is_stale_at_publish,
        ),
        "data_status": {
            "status": (report.get("data_status") or {}).get("status"),
            "evidence_class": (report.get("data_trust") or {}).get("verdict"),
        },
        "publication_history": publication_history,
        "release_gates": (report.get("full_system_surface") or {}).get("release_gates"),
    }


def _build_thermo(*, vrp_status: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PUBLICATION_THERMO_SCHEMA,
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
        "recent_series_path": "/api/v1/thermo/recent.json",
        "year_shards": _thermo_year_shard_paths(vrp_status.get("series") or []),
    }


def _build_candidates(*, report: dict[str, Any]) -> dict[str, Any]:
    scanner = dict(report.get("ev_candidate_scanner") or {})
    ranked_candidates = [
        _annotate_numeric_field_evidence(
            dict(candidate or {}),
            evidence_class="uncalibrated_research_screen",
        )
        for candidate in (scanner.get("ranked_candidates") or [])
    ]
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
        "evidence_class": "uncalibrated_research_screen",
        "ranked_candidates": ranked_candidates,
    }


def _build_signal(*, signal_payload: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PUBLICATION_SIGNAL_SCHEMA,
        "captured_at": report["publish_edition"]["captured_at"],
        "published_at": report["publish_edition"]["published_at"],
        "disclaimer_url": "/disclaimer.html",
        "methodology_url": "/methodology.html",
        "evidence_class": "research_signal_artifact",
        "artifact": _annotate_numeric_field_evidence(
            signal_payload,
            evidence_class="research_signal_artifact",
        ),
    }


def _build_health(
    *,
    report: dict[str, Any],
    is_stale_at_publish: bool,
    manifest_verification: dict[str, Any],
    publication_history: dict[str, Any],
) -> dict[str, Any]:
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
        "publish_manifest_status": manifest_verification.get("status"),
        "manifest_verification": manifest_verification,
        "research_publication_status": (gates.get("research_publication") or {}).get(
            "status"
        ),
        "execution_authorization_status": (
            gates.get("execution_authorization") or {}
        ).get("status"),
        "publication_history": publication_history,
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
        "publish_manifest_status": health["publish_manifest_status"],
        "research_publication_status": health["research_publication_status"],
        "execution_authorization_status": health["execution_authorization_status"],
        "publication_history": health["publication_history"],
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
        "git_provenance": publication_inputs.get("git_provenance"),
        "web_build_source": {
            "root_name": build_root.name,
            "index_name": "index.html",
            "assets_dir": "assets",
        },
        "input_hashes": publication_inputs,
        "artifacts": artifacts,
        "manifest_verification": {
            "status": "verified",
            "artifact_count": len(artifacts),
            "errors": [],
        },
        "manifest_policy": {
            "canonical_json": True,
            "self_hash_excluded_paths": sorted(_MANIFEST_PATHS),
            "hash_algorithm": "sha256",
            "history_alignment": (
                "Underlying and DVOL observations are trimmed to the snapshot "
                "captured_at clock before 08:00Z settlement-aligned evaluation "
                "and hashing. Signal and series artifact clocks must equal that "
                "snapshot clock, and their observed capture fields may not exceed it."
            ),
        },
    }


def _project_vrp_status(raw_status: dict[str, Any]) -> dict[str, Any]:
    current = dict(raw_status.get("current") or {})
    series = []
    for point in raw_status.get("time_series") or []:
        series.append(
            {
                "observed_at": point.get("evaluation_at"),
                "evaluation_at": point.get("evaluation_at"),
                "dvol_observed_at": point.get("dvol_observed_at"),
                "underlying_observed_at": point.get("underlying_observed_at"),
                "vrp_percent_points": point.get("vrp_percent_points"),
                "dvol_percent": point.get("dvol_percent_points"),
                "rv30_percent": point.get("rv30_percent_points"),
                "percentile": point.get("percentile"),
                "percentile_sample_count": point.get("percentile_sample_count"),
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
        "evaluation_at": current.get("evaluation_at"),
        "dvol_observed_at": current.get("dvol_observed_at"),
        "underlying_observed_at": current.get("underlying_observed_at"),
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


def _copy_web_bundle(
    build_root: Path,
    out_path: Path,
    *,
    summary: dict[str, Any],
    site_origin: str,
) -> None:
    index_source = build_root / "index.html"
    assets_source = build_root / "assets"
    if not index_source.is_file():
        raise ValueError("web build is missing index.html")
    if not assets_source.is_dir():
        raise ValueError("web build is missing assets/")
    for filename in sorted(_PUBLIC_LICENSE_FILES):
        if not (build_root / filename).is_file():
            raise ValueError(f"web build is missing {filename}")
    index_html = index_source.read_text(encoding="utf-8")
    rewritten = _rewrite_index_html(
        index_html.replace('"/evidence/assets/', '"./assets/'),
        summary=summary,
        page_url=f"{site_origin}/",
        image_url=f"{site_origin}/og-card.png",
    )
    for source in sorted(build_root.rglob("*")):
        if not source.is_file() or source == index_source:
            continue
        relative = source.relative_to(build_root)
        target = out_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    _write_html(out_path / "index.html", rewritten)
    vrp = dict(summary.get("vrp") or {})
    og_card = render_og_card(
        vrp_percent_points=vrp.get("vrp_percent_points"),
        percentile=vrp.get("percentile"),
        band=vrp.get("band"),
        publication_date=str(summary.get("published_at") or "")[:10],
    )
    _write_bytes(out_path / "og-card.png", og_card)


def _ensure_publication_privacy(out_path: Path) -> None:
    for relative_path in _relative_file_paths(out_path):
        path = out_path / relative_path
        if path.name == "_headers":
            continue
        if path.name == "og-card.png":
            validate_og_card_png(path.read_bytes())
            continue
        if (
            relative_path == "index.html"
            or path.name in _PUBLIC_LICENSE_FILES
            or path.suffix in {".html", ".js", ".css", ".txt", ".xml"}
        ):
            content = path.read_text(encoding="utf-8")
            lowered = content.lower()
            forbidden_tokens = {
                "api_key",
                "secret",
                "access_token",
                "refresh_token",
            }
            if path.suffix in {".js", ".css"}:
                forbidden_tokens.update(forbidden_bundle_tokens())
            for forbidden in sorted(forbidden_tokens):
                if re.search(
                    rf"(?<![a-z0-9_]){re.escape(forbidden.lower())}(?![a-z0-9_])",
                    lowered,
                ):
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
        return (
            "file://" in value
            or _WINDOWS_DRIVE_PATH_RE.search(value) is not None
            or _UNC_PATH_RE.search(value) is not None
            or _UNIX_ABSOLUTE_PATH_RE.search(value) is not None
            or re.search(r"(?:^|\s)~[\\/][^\s]+", value) is not None
        )
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
    if not web_build:
        raise ValueError("explicit public web build directory is required")
    build_root = Path(web_build).expanduser().resolve()
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


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


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


def _trim_history_to_capture_clock(
    payload: dict[str, Any],
    *,
    captured_dt: datetime,
    label: str,
) -> dict[str, Any]:
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise ValueError(f"{label} observations must be a list")
    trimmed: list[dict[str, Any]] = []
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError(f"{label} observations must contain only objects")
        observed_at = item.get("observed_at")
        observed_dt = _parse_timestamp(
            observed_at,
            field=f"{label} observation observed_at",
        )
        if observed_dt > captured_dt:
            continue
        trimmed.append(item)
    if not trimmed:
        raise ValueError(f"{label} has no observations on or before snapshot capture clock")
    trimmed_payload = dict(payload)
    trimmed_payload["observations"] = trimmed
    trimmed_payload["observation_count"] = len(trimmed)
    trimmed_payload["first_observed_at"] = trimmed[0].get("observed_at")
    trimmed_payload["last_observed_at"] = trimmed[-1].get("observed_at")
    payload_captured_at = trimmed_payload.get("captured_at")
    if isinstance(payload_captured_at, str) and payload_captured_at:
        payload_captured_dt = _parse_timestamp(
            payload_captured_at,
            field=f"{label} captured_at",
        )
        if payload_captured_dt > captured_dt:
            trimmed_payload["captured_at"] = _timestamp(captured_dt)
            requested_days = trimmed_payload.get("requested_days")
            if isinstance(requested_days, int) and not isinstance(requested_days, bool):
                first_date = date.fromisoformat(str(trimmed[0]["observed_at"])[:10])
                capture_date = captured_dt.date()
                available_day_span = max(0, (capture_date - first_date).days)
                if trimmed_payload.get("schema_version") == "dvol_history.v1":
                    trimmed_payload["requested_days"] = max(
                        1,
                        min(requested_days, available_day_span),
                    )
                elif trimmed_payload.get("schema_version") == "underlying_price_history.v1":
                    trimmed_payload["requested_days"] = max(
                        1,
                        min(requested_days, available_day_span + 1),
                    )
    coverage = dict(trimmed_payload.get("coverage") or {})
    if coverage:
        observed_dates = {
            date.fromisoformat(str(item["observed_at"])[:10]) for item in trimmed
        }
        first_date = min(observed_dates)
        last_date = max(observed_dates)
        expected_dates = {
            first_date + timedelta(days=offset)
            for offset in range((last_date - first_date).days + 1)
        }
        missing_dates = sorted(expected_dates - observed_dates)
        expected_day_count = len(expected_dates)
        trimmed_coverage = dict(coverage)
        trimmed_coverage["expected_day_count"] = expected_day_count
        trimmed_coverage["observed_day_count"] = len(observed_dates)
        trimmed_coverage["missing_days"] = [item.isoformat() for item in missing_dates]
        trimmed_coverage["missing_day_count"] = len(missing_dates)
        trimmed_coverage["coverage_ratio"] = (
            len(observed_dates) / expected_day_count
        )
        trimmed_payload["coverage"] = trimmed_coverage
    return trimmed_payload


def _project_vrp_band(raw_band: Any, percentile: Any) -> str | None:
    if not isinstance(percentile, (int, float)):
        return None
    internal_band = (
        str(raw_band)
        if isinstance(raw_band, str) and raw_band
        else vrp_band_for_percentile(float(percentile))
    )
    return {
        "extremely_expensive": "P90+",
        "expensive": "P70+",
        "neutral": "P30-P70",
        "thin": "P30-",
        "extremely_thin": "P10-",
    }.get(internal_band)


def _headers_text() -> str:
    return (
        "/*\n"
        "  Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'\n"
        "  X-Content-Type-Options: nosniff\n"
        "  Referrer-Policy: no-referrer\n"
        "  X-Frame-Options: DENY\n"
        "  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()\n"
        "\n"
        "/api/v1/*\n"
        "  Access-Control-Allow-Origin: *\n"
        "  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: public, max-age=300\n"
        "\n"
        "/research/*\n"
        "  Access-Control-Allow-Origin: *\n"
        "  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: public, max-age=300\n"
        "\n"
        "/robots.txt\n"
        "  Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "/sitemap.xml\n"
        "  Content-Type: application/xml; charset=utf-8\n"
        "\n"
        "/api/openapi.json\n"
        "  Access-Control-Allow-Origin: *\n"
        "  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: public, max-age=300\n"
        "\n"
        "/assets/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n"
    )


def _rewrite_index_html(
    index_html: str,
    *,
    summary: dict[str, Any],
    page_url: str,
    image_url: str,
) -> str:
    title = PUBLIC_SITE_TITLE
    description = PUBLIC_SITE_DESCRIPTION
    vrp = dict(summary.get("vrp") or {})
    og_alt = (
        "BTC volatility risk premium "
        f"{float(vrp['vrp_percent_points']):+.2f} vol points, "
        f"{float(vrp['percentile']) * 100:.1f} percentile, "
        f"{vrp['band']}, research only"
    )
    rewritten = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", index_html, count=1, flags=re.S)
    rewritten = re.sub(
        r'(<meta\s+name="description"\s+content=")(.*?)(".*?>)',
        rf"\1{description}\3",
        rewritten,
        count=1,
        flags=re.S,
    )
    document_meta = ""
    if not re.search(r'<meta\s+name="description"\b', rewritten):
        document_meta += f'    <meta name="description" content="{description}">\n'
    if not re.search(r'<link\s+rel="canonical"\b', rewritten):
        document_meta += f'    <link rel="canonical" href="{page_url}">\n'
    if not re.search(r'<meta\s+name="robots"\b', rewritten):
        document_meta += (
            '    <meta name="robots" '
            'content="index,follow,max-image-preview:large">\n'
        )
    if document_meta:
        rewritten = rewritten.replace("</head>", f"{document_meta}</head>", 1)
    meta_block = (
        f'    <meta property="og:title" content="{title}">\n'
        f'    <meta property="og:description" content="{description}">\n'
        '    <meta property="og:type" content="website">\n'
        '    <meta property="og:locale" content="zh_CN">\n'
        f'    <meta property="og:url" content="{page_url}">\n'
        f'    <meta property="og:image" content="{image_url}">\n'
        f'    <meta property="og:image:alt" content="{og_alt}">\n'
        '    <meta property="og:image:width" content="1200">\n'
        '    <meta property="og:image:height" content="630">\n'
        '    <meta property="og:image:type" content="image/png">\n'
        '    <meta name="twitter:card" content="summary_large_image">\n'
        f'    <meta name="twitter:image" content="{image_url}">\n'
        f'    <meta name="twitter:image:alt" content="{og_alt}">\n'
        f'    <meta name="twitter:title" content="{title}">\n'
        f'    <meta name="twitter:description" content="{description}">\n'
    )
    if 'property="og:title"' not in rewritten:
        rewritten = rewritten.replace("</head>", f"{meta_block}</head>", 1)
    rewritten = re.sub(
        r'(<meta\s+property="og:url"\s+content=")(.*?)(">)',
        rf"\g<1>{page_url}\g<3>",
        rewritten,
        count=1,
    )
    rewritten = re.sub(
        r'(<link\s+rel="canonical"\s+href=")(.*?)(".*?>)',
        rf"\g<1>{page_url}\g<3>",
        rewritten,
        count=1,
    )
    rewritten = re.sub(
        r'(<meta\s+property="og:image"\s+content=")(.*?)(">)',
        rf"\g<1>{image_url}\g<3>",
        rewritten,
        count=1,
    )
    rewritten = re.sub(
        r'(<meta\s+name="twitter:image"\s+content=")(.*?)(">)',
        rf"\g<1>{image_url}\g<3>",
        rewritten,
        count=1,
    )
    return rewritten


def _status_html(status: dict[str, Any], *, language: str) -> str:
    return render_public_status_html(status, language=language)


def _write_status_pages(out_path: Path, status: dict[str, Any]) -> None:
    _write_html(out_path / "status.html", _status_html(status, language="zh-CN"))
    _write_html(out_path / "en" / "status.html", _status_html(status, language="en"))
