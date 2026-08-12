"""Public DVOL history and VRP temperature-gauge calculations.

VRP is intentionally defined as one directly measured spread:

    VRP(t) = DVOL(t) - RV_30(t)

where both legs are expressed in percentage points. Missing or malformed input
stays unavailable rather than being coerced into zero.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ._http import json_getter
from ._http import no_redirect_urlopen as urlopen
from ._time import utc_timestamp
from .empirical_rank import empirical_percentile, vrp_band_for_percentile
from .market_data import (
    DEFAULT_DERIBIT_BASE_URL,
    MAX_MARKET_SNAPSHOT_BYTES,
    parse_timestamp_ms,
    resolve_snapshot_fixture_path,
    validate_deribit_base_url,
)
from .realized_vol import annualized_volatility
from .storage import read_json_object_from_regular_file

DVOL_HISTORY_SCHEMA_VERSION = "dvol_history.v1"
VRP_STATUS_SCHEMA_VERSION = "vrp_status.v1"
MAX_DVOL_HISTORY_DAYS = 3650
MIN_VRP_SERIES_SAMPLE_COUNT = 1000
_SECONDS_PER_DAY = 86400
_MILLISECONDS_PER_DAY = _SECONDS_PER_DAY * 1000
_VALIDATED_VRP_EVIDENCE = "validated_public_deribit_histories"
_get_json = json_getter(
    max_bytes=MAX_MARKET_SNAPSHOT_BYTES,
    description="Deribit dvol history response",
    opener=lambda request, *, timeout: urlopen(request, timeout=timeout),
)


def load_dvol_history_fixture(
    path: str | Path,
    *,
    allowed_roots: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    """Load a recorded DVOL history fixture for deterministic replay."""
    fixture_path = resolve_snapshot_fixture_path(path, allowed_roots=allowed_roots)
    payload = read_json_object_from_regular_file(
        fixture_path,
        max_bytes=MAX_MARKET_SNAPSHOT_BYTES,
        description="dvol history fixture",
    )
    return _validated_dvol_history(payload)


def fetch_deribit_dvol_history(
    *,
    currency: str = "BTC",
    days: int,
    resolution: str = "1D",
    base_url: str = DEFAULT_DERIBIT_BASE_URL,
    timeout: int,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Fetch public Deribit DVOL history in percent points."""
    safe_base = validate_deribit_base_url(base_url)
    if resolution != "1D":
        raise ValueError("dvol history resolution must be 1D")
    if not isinstance(days, int) or days <= 0 or days > MAX_DVOL_HISTORY_DAYS:
        raise ValueError(
            f"dvol history days must be an int in 1..{MAX_DVOL_HISTORY_DAYS}"
        )
    base_currency = str(currency or "").strip().upper()
    if not base_currency.isalpha():
        raise ValueError("dvol history currency must be alphabetic")

    captured = captured_at or utc_timestamp()
    end_ms = parse_timestamp_ms(captured)
    start_ms = max(0, end_ms - days * _MILLISECONDS_PER_DAY)
    request_start_date = datetime.fromtimestamp(start_ms / 1000, tz=UTC).date()
    request_end_date = datetime.fromtimestamp(end_ms / 1000, tz=UTC).date()

    params: dict[str, Any] = {
        "currency": base_currency,
        "resolution": resolution,
        "start_timestamp": start_ms,
        "end_timestamp": end_ms,
    }
    observed_rows: dict[int, dict[str, Any]] = {}
    previous_page_end_ms = end_ms

    while True:
        payload = _get_json(
            f"{safe_base}/api/v2/public/get_volatility_index_data",
            params,
            timeout=timeout,
        )
        result = _jsonrpc_result(payload, endpoint="get_volatility_index_data")
        data_rows = result.get("data") if isinstance(result, dict) else result
        if not isinstance(data_rows, list) or not data_rows:
            raise ValueError("empty volatility index data")

        for row in data_rows:
            timestamp_ms, close = _parse_dvol_row(row)
            observed_rows[timestamp_ms] = {
                "timestamp_ms": timestamp_ms,
                "observed_at": _timestamp_from_ms(timestamp_ms),
                "close": close,
            }

        continuation = result.get("continuation") if isinstance(result, dict) else None
        observations = sorted(observed_rows.values(), key=lambda item: item["timestamp_ms"])
        trimmed = [
            row
            for row in observations
            if request_start_date <= date.fromisoformat(row["observed_at"][:10]) <= request_end_date
        ]
        if trimmed and date.fromisoformat(trimmed[0]["observed_at"][:10]) <= request_start_date:
            observations = trimmed
            break
        if continuation in (None, ""):
            observations = trimmed
            break
        next_end_ms = _coerce_timestamp_ms(continuation)
        if next_end_ms >= previous_page_end_ms:
            raise ValueError("dvol history continuation must strictly decrease end_timestamp")
        params["end_timestamp"] = next_end_ms
        previous_page_end_ms = next_end_ms

    if not observations:
        raise ValueError("empty volatility index data")
    if (
        date.fromisoformat(observations[0]["observed_at"][:10]) > request_start_date
        or date.fromisoformat(observations[-1]["observed_at"][:10]) < request_end_date
    ):
        raise ValueError("requested dvol history window is not fully covered")

    previous_ms: int | None = None
    observed_dates: set[str] = set()
    for row in observations:
        timestamp_ms = row["timestamp_ms"]
        if previous_ms is not None and timestamp_ms <= previous_ms:
            raise ValueError("dvol history must be strictly increasing in time")
        previous_ms = timestamp_ms
        observed_date = row["observed_at"][:10]
        if observed_date in observed_dates:
            raise ValueError("dvol history must contain one observation per UTC day")
        observed_dates.add(observed_date)

    coverage = _coverage_from_observations(
        observations,
        window_start=request_start_date,
        window_end=request_end_date,
    )
    return {
        "schema_version": DVOL_HISTORY_SCHEMA_VERSION,
        "captured_at": captured,
        "source": f"deribit_live:{safe_base}",
        "source_endpoint": "public/get_volatility_index_data",
        "index_name": f"{base_currency} DVOL",
        "currency": base_currency,
        "resolution": resolution,
        "resolution_seconds": _SECONDS_PER_DAY,
        "requested_days": days,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "value_unit": "percent_points",
        "coverage": coverage,
        "observations": observations,
    }


def build_vrp_status(
    dvol_history: dict[str, Any] | None,
    underlying_history: dict[str, Any] | None,
    generated_at: str,
    *,
    window_days: int = 1095,
    minimum_series_sample_count: int = MIN_VRP_SERIES_SAMPLE_COUNT,
) -> dict[str, Any]:
    """Build the public VRP temperature-gauge status."""
    base = {
        "schema_version": VRP_STATUS_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "unavailable",
        "evidence_class": "unavailable",
        "vrp_unit": "percent_points",
        "dvol_unit": "percent_points",
        "rv_unit": "percent_points",
        "window_days": window_days,
        "minimum_series_sample_count": minimum_series_sample_count,
        "series_sample_count": 0,
        "reason_codes": [],
        "current": _empty_current(),
        "time_series": [],
        "missing_days": [],
        "missing_evidence": [],
        "remediation": _remediation(
            _remediation_command(
                "dvol",
                _currency_from_histories(dvol_history, underlying_history),
                window_days,
            )
        ),
    }
    if (
        not isinstance(window_days, int)
        or window_days <= 0
        or not isinstance(minimum_series_sample_count, int)
        or minimum_series_sample_count <= 0
    ):
        return {
            **base,
            "reason_codes": ["INVALID_WINDOW_DAYS"],
            "remediation": _remediation(
                _remediation_command(
                    "dvol",
                    _currency_from_histories(dvol_history, underlying_history),
                    1095,
                )
            ),
        }
    try:
        evaluation_date = _settlement_evaluation_date(
            parse_timestamp_ms(generated_at) / 1000,
        )
    except (OSError, OverflowError, TypeError, ValueError):
        return {**base, "reason_codes": ["INVALID_EVALUATION_CLOCK"]}

    dvol_validation = _validate_dvol_history_for_vrp(dvol_history)
    underlying_validation = _validate_underlying_history_for_vrp(underlying_history)
    reason_codes: list[str] = []
    remediation_commands: list[str] = []

    if dvol_validation["history"] is None:
        reason_codes.append(dvol_validation["reason_code"])
        remediation_commands.append(
            _remediation_command(
                "dvol",
                dvol_validation["currency"]
                or underlying_validation["currency"]
                or "BTC",
                max(window_days, 1095),
            )
        )
    if underlying_validation["history"] is None:
        reason_codes.append(underlying_validation["reason_code"])
        remediation_commands.append(
            _remediation_command(
                "underlying",
                underlying_validation["currency"]
                or dvol_validation["currency"]
                or "BTC",
                max(window_days, 1095),
            )
        )
    if reason_codes:
        return {
            **base,
            "reason_codes": reason_codes,
            "remediation": _remediation(*remediation_commands),
        }

    dvol_payload = dvol_validation["history"]
    underlying_payload = underlying_validation["history"]
    assert dvol_payload is not None
    assert underlying_payload is not None

    dvol_by_date = _values_by_date(
        dvol_payload["observations"],
        value_key="close",
        through_date=evaluation_date,
    )
    underlying_by_date = _values_by_date(
        underlying_payload["observations"],
        value_key="close",
        through_date=evaluation_date,
    )
    dvol_observed_at_by_date = _observed_at_by_date(
        dvol_payload["observations"],
        through_date=evaluation_date,
    )
    underlying_observed_at_by_date = _observed_at_by_date(
        underlying_payload["observations"],
        through_date=evaluation_date,
    )
    if not dvol_by_date or not underlying_by_date:
        return {**base, "reason_codes": ["NO_HISTORY_AT_EVALUATION_CLOCK"]}
    overlap_start = max(
        date.fromisoformat(min(dvol_by_date.keys())),
        date.fromisoformat(min(underlying_by_date.keys())),
    )
    overlap_end = min(
        date.fromisoformat(max(dvol_by_date.keys())),
        date.fromisoformat(max(underlying_by_date.keys())),
    )
    if overlap_start > overlap_end:
        return {
            **base,
            "reason_codes": ["NO_SHARED_HISTORY_RANGE"],
            "remediation": _remediation(
                _remediation_command(
                    "dvol", dvol_payload["currency"], max(window_days, 1095)
                ),
                _remediation_command(
                    "underlying",
                    underlying_payload["currency"],
                    max(window_days, 1095),
                ),
            ),
        }

    source_missing_days = _combined_missing_days(
        overlap_start,
        overlap_end,
        dvol_by_date,
        underlying_by_date,
        dvol_payload.get("coverage", {}).get("missing_days") or [],
        _coverage_from_observations(underlying_payload["observations"])["missing_days"],
    )

    raw_points: list[dict[str, Any]] = []
    missing_evidence: list[dict[str, Any]] = []
    first_underlying_date = date.fromisoformat(min(underlying_by_date.keys()))
    current_date = max(overlap_start, first_underlying_date + timedelta(days=30))
    while current_date <= evaluation_date:
        current_key = current_date.isoformat()
        dvol_value = dvol_by_date.get(current_key)
        missing_underlying_days = _missing_underlying_rv30_days(
            underlying_by_date,
            current_date,
        )
        missing_reason_codes = []
        if dvol_value is None:
            missing_reason_codes.append("MISSING_DVOL_OBSERVATION")
        if missing_underlying_days:
            missing_reason_codes.append("INCOMPLETE_UNDERLYING_RV30_WINDOW")
        if missing_reason_codes:
            missing_evidence.append(
                {
                    "date": current_key,
                    "reason_code": missing_reason_codes[0],
                    "reason_codes": missing_reason_codes,
                    "missing_underlying_days": missing_underlying_days,
                }
            )
            current_date += timedelta(days=1)
            continue
        rv30 = _realized_vol_30_for_date(underlying_by_date, current_date)
        assert rv30 is not None
        dvol_observed_at = dvol_observed_at_by_date.get(current_key)
        underlying_observed_at = underlying_observed_at_by_date.get(current_key)
        assert dvol_observed_at is not None
        assert underlying_observed_at is not None
        raw_points.append(
            {
                "date": current_key,
                "dvol_observed_at": dvol_observed_at,
                "underlying_observed_at": underlying_observed_at,
                "evaluation_at": underlying_observed_at,
                "dvol_percent_points": round(dvol_value, 6),
                "rv30_percent_points": round(rv30, 6),
                "vrp_percent_points": round(dvol_value - rv30, 6),
                "rv_sample_count": 30,
                "evidence_class": _VALIDATED_VRP_EVIDENCE,
            }
        )
        current_date += timedelta(days=1)

    missing_days = sorted(
        set(source_missing_days)
        | {item["date"] for item in missing_evidence}
    )

    if not raw_points:
        return {
            **base,
            "reason_codes": ["INSUFFICIENT_ALIGNED_HISTORY"],
            "missing_days": missing_days,
            "missing_evidence": missing_evidence,
            "remediation": _remediation(
                _remediation_command(
                    "dvol", dvol_payload["currency"], max(window_days, 1095)
                ),
                _remediation_command(
                    "underlying",
                    underlying_payload["currency"],
                    max(window_days, 1095),
                ),
            ),
        }

    enriched_points: list[dict[str, Any]] = []
    for index, point in enumerate(raw_points):
        point_date = date.fromisoformat(point["date"])
        window_start = point_date - timedelta(days=window_days - 1)
        window_values = [
            item["vrp_percent_points"]
            for item in raw_points[:index]
            if date.fromisoformat(item["date"]) >= window_start
        ]
        percentile_summary = _percentile_band_for_point(
            current=point["vrp_percent_points"],
            history=window_values,
            minimum_sample_count=minimum_series_sample_count,
        )
        enriched_points.append(
            {
                **point,
                "percentile": percentile_summary["percentile"],
                "percentile_sample_count": percentile_summary["sample_count"],
                "band": percentile_summary["band"],
                "window_day_span": window_days,
            }
        )

    if enriched_points[-1]["percentile"] is None:
        return {
            **base,
            "status": "insufficient_history",
            "evidence_class": "insufficient_history",
            "reason_codes": ["INSUFFICIENT_VRP_HISTORY"],
            "time_series": enriched_points,
            "missing_days": missing_days,
            "missing_evidence": missing_evidence,
            "series_sample_count": len(enriched_points),
            "remediation": _remediation(
                _remediation_command(
                    "dvol", dvol_payload["currency"], max(window_days, 1095)
                )
            ),
        }

    if enriched_points[-1]["date"] != evaluation_date.isoformat():
        return {
            **base,
            "reason_codes": ["STALE_VRP_EVALUATION_DATE"],
            "time_series": enriched_points,
            "missing_days": missing_days,
            "missing_evidence": missing_evidence,
            "series_sample_count": len(enriched_points),
            "remediation": _remediation(
                _remediation_command(
                    "dvol", dvol_payload["currency"], max(window_days, 1095)
                ),
                _remediation_command(
                    "underlying",
                    underlying_payload["currency"],
                    max(window_days, 1095),
                ),
            ),
        }

    current = dict(enriched_points[-1])
    return {
        "schema_version": VRP_STATUS_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "validated",
        "evidence_class": _VALIDATED_VRP_EVIDENCE,
        "vrp_unit": "percent_points",
        "dvol_unit": "percent_points",
        "rv_unit": "percent_points",
        "window_days": window_days,
        "minimum_series_sample_count": minimum_series_sample_count,
        "reason_codes": [],
        "current": current,
        "time_series": enriched_points,
        "missing_days": missing_days,
        "missing_evidence": missing_evidence,
        "series_sample_count": len(enriched_points),
        "remediation": _remediation(
            _remediation_command(
                "dvol", dvol_payload["currency"], max(window_days, 1095)
            )
        ),
    }


def _validated_dvol_history(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != DVOL_HISTORY_SCHEMA_VERSION:
        raise ValueError(
            f"dvol history fixture must be {DVOL_HISTORY_SCHEMA_VERSION}"
        )
    if payload.get("resolution") != "1D" or payload.get("resolution_seconds") != 86400:
        raise ValueError("dvol history fixture must use 1D daily resolution")
    if payload.get("value_unit") != "percent_points":
        raise ValueError("dvol history value_unit must be percent_points")
    observations = payload.get("observations")
    if not isinstance(observations, list) or len(observations) < 1:
        raise ValueError("dvol history fixture must contain observations")
    requested_days = payload.get("requested_days")
    if (
        not isinstance(requested_days, int)
        or isinstance(requested_days, bool)
        or requested_days <= 0
        or requested_days > MAX_DVOL_HISTORY_DAYS
    ):
        raise ValueError("dvol history requested_days is invalid")
    try:
        captured_date = datetime.fromtimestamp(
            parse_timestamp_ms(str(payload.get("captured_at") or "")) / 1000,
            tz=UTC,
        ).date()
    except (OSError, OverflowError, TypeError, ValueError) as exc:
        raise ValueError("dvol history captured_at is invalid") from exc
    requested_start = captured_date - timedelta(days=requested_days)

    previous_ms: int | None = None
    observed_dates: set[str] = set()
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("dvol history observations must be objects")
        timestamp_ms = row.get("timestamp_ms")
        close = row.get("close")
        if not isinstance(timestamp_ms, int):
            raise ValueError("dvol history timestamp_ms must be an integer")
        if previous_ms is not None and timestamp_ms <= previous_ms:
            raise ValueError("dvol history must be strictly increasing in time")
        previous_ms = timestamp_ms
        observed_at = row.get("observed_at")
        if observed_at != _timestamp_from_ms(timestamp_ms):
            raise ValueError("dvol history observed_at must match timestamp_ms")
        observed_date = str(observed_at)[:10]
        if observed_date in observed_dates:
            raise ValueError("dvol history must contain one observation per UTC day")
        observed_dates.add(observed_date)
        normalized = _finite_number(close)
        if normalized is None or normalized <= 0:
            raise ValueError("dvol history close must be a positive finite number")

    if (
        requested_start.isoformat() not in observed_dates
        or captured_date.isoformat() not in observed_dates
    ):
        raise ValueError("requested dvol history window is not fully covered")

    payload = dict(payload)
    payload["coverage"] = _coverage_from_observations(
        observations,
        window_start=requested_start,
        window_end=captured_date,
    )
    payload["observation_count"] = len(observations)
    payload["first_observed_at"] = observations[0]["observed_at"]
    payload["last_observed_at"] = observations[-1]["observed_at"]
    return payload


def _validate_dvol_history_for_vrp(history: Any) -> dict[str, Any]:
    currency = ""
    if isinstance(history, dict):
        currency = str(history.get("currency") or "").strip().upper()
    if history is None:
        return {"history": None, "reason_code": "MISSING_DVOL_HISTORY", "currency": currency}
    try:
        return {
            "history": _validated_dvol_history(history),
            "reason_code": None,
            "currency": currency or str(history.get("currency") or "").strip().upper(),
        }
    except (TypeError, ValueError):
        return {"history": None, "reason_code": "INVALID_DVOL_HISTORY", "currency": currency}


def _validate_underlying_history_for_vrp(history: Any) -> dict[str, Any]:
    currency = ""
    if isinstance(history, dict):
        currency = str(history.get("currency") or "").strip().upper()
    if history is None:
        return {
            "history": None,
            "reason_code": "MISSING_UNDERLYING_HISTORY",
            "currency": currency,
        }
    observations = history.get("observations") if isinstance(history, dict) else None
    if not isinstance(history, dict) or history.get("resolution_seconds") != 86400:
        return {
            "history": None,
            "reason_code": "INVALID_UNDERLYING_HISTORY",
            "currency": currency,
        }
    if not isinstance(observations, list) or len(observations) < 31:
        return {
            "history": None,
            "reason_code": "INVALID_UNDERLYING_HISTORY",
            "currency": currency,
        }
    previous_ms: int | None = None
    observed_dates: set[str] = set()
    for row in observations:
        if not isinstance(row, dict):
            return {
                "history": None,
                "reason_code": "INVALID_UNDERLYING_HISTORY",
                "currency": currency,
            }
        close = _finite_number(row.get("close"))
        timestamp_ms = row.get("timestamp_ms")
        if close is None or close <= 0 or not isinstance(timestamp_ms, int):
            return {
                "history": None,
                "reason_code": "INVALID_UNDERLYING_HISTORY",
                "currency": currency,
            }
        if previous_ms is not None and timestamp_ms <= previous_ms:
            return {
                "history": None,
                "reason_code": "INVALID_UNDERLYING_HISTORY",
                "currency": currency,
            }
        observed_at = row.get("observed_at")
        if not isinstance(observed_at, str) or observed_at != _timestamp_from_ms(timestamp_ms):
            return {
                "history": None,
                "reason_code": "INVALID_UNDERLYING_HISTORY",
                "currency": currency,
            }
        observed_date = observed_at[:10]
        if observed_date in observed_dates:
            return {
                "history": None,
                "reason_code": "INVALID_UNDERLYING_HISTORY",
                "currency": currency,
            }
        observed_dates.add(observed_date)
        previous_ms = timestamp_ms
    return {"history": history, "reason_code": None, "currency": currency}


def _values_by_date(
    observations: list[dict[str, Any]],
    *,
    value_key: str,
    through_date: date,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in observations:
        observed_at = str(row.get("observed_at") or "")
        if not observed_at.endswith("Z"):
            continue
        observed_date = date.fromisoformat(observed_at[:10])
        if observed_date <= through_date:
            values[observed_date.isoformat()] = float(row[value_key])
    return values


def _observed_at_by_date(
    observations: list[dict[str, Any]],
    *,
    through_date: date,
) -> dict[str, str]:
    observed_at_by_date: dict[str, str] = {}
    for row in observations:
        observed_at = str(row.get("observed_at") or "")
        if not observed_at.endswith("Z"):
            continue
        observed_date = date.fromisoformat(observed_at[:10])
        if observed_date <= through_date:
            observed_at_by_date[observed_date.isoformat()] = observed_at
    return observed_at_by_date


def _combined_missing_days(
    overlap_start: date,
    overlap_end: date,
    dvol_by_date: dict[str, float],
    underlying_by_date: dict[str, float],
    dvol_coverage_missing: list[str],
    underlying_coverage_missing: list[str],
) -> list[str]:
    missing = {
        item
        for item in set(dvol_coverage_missing) | set(underlying_coverage_missing)
        if overlap_start <= date.fromisoformat(item) <= overlap_end
    }
    current = overlap_start
    while current <= overlap_end:
        key = current.isoformat()
        if key not in dvol_by_date or key not in underlying_by_date:
            missing.add(key)
        current += timedelta(days=1)
    return sorted(missing)


def _missing_underlying_rv30_days(
    underlying_by_date: dict[str, float],
    current_date: date,
) -> list[str]:
    return [
        key
        for offset in range(30, -1, -1)
        if (key := (current_date - timedelta(days=offset)).isoformat())
        not in underlying_by_date
    ]


def _realized_vol_30_for_date(
    underlying_by_date: dict[str, float], current_date: date
) -> float | None:
    if _missing_underlying_rv30_days(underlying_by_date, current_date):
        return None
    closes: list[float] = []
    for offset in range(30, -1, -1):
        key = (current_date - timedelta(days=offset)).isoformat()
        closes.append(underlying_by_date[key])
    returns = [math.log(closes[index + 1] / closes[index]) for index in range(30)]
    volatility = annualized_volatility(returns)
    return volatility * 100.0 if volatility is not None else None


def _percentile_band_for_point(
    *,
    current: float,
    history: list[float],
    minimum_sample_count: int,
) -> dict[str, Any]:
    sample_count = len(history)
    if sample_count < minimum_sample_count:
        return {
            "percentile": None,
            "sample_count": sample_count,
            "band": None,
        }
    percentile = empirical_percentile(current=current, history=history)
    return {
        "percentile": percentile,
        "sample_count": sample_count,
        "band": _band_for_percentile(percentile),
    }


def _band_for_percentile(percentile: float) -> str:
    """Backward-compatible private seam; thresholds live in empirical_rank."""
    return vrp_band_for_percentile(percentile)


def _empty_current() -> dict[str, Any]:
    return {
        "date": None,
        "dvol_observed_at": None,
        "underlying_observed_at": None,
        "evaluation_at": None,
        "dvol_percent_points": None,
        "rv30_percent_points": None,
        "vrp_percent_points": None,
        "percentile": None,
        "percentile_sample_count": None,
        "rv_sample_count": None,
        "band": None,
        "window_day_span": None,
    }


def _currency_from_histories(*histories: Any) -> str:
    for history in histories:
        if isinstance(history, dict):
            currency = str(history.get("currency") or "").strip().upper()
            if currency:
                return currency
    return "BTC"


def _remediation_command(kind: str, currency: str, days: int) -> str:
    if kind == "underlying":
        return (
            "crypto-options-underlying-history "
            f"--currency {currency} --days {days} --resolution 1D "
            f"--output artifacts/history/{currency.lower()}-daily.json"
        )
    return (
        "crypto-options-dvol-history "
        f"--currency {currency} --days {days} --resolution 1D "
        f"--output artifacts/history/{currency.lower()}-dvol.json"
    )


def _remediation(*commands: str) -> dict[str, Any]:
    """Return commands as data plus a newline-safe copy/paste representation."""
    items = [command for command in commands if command]
    return {
        "commands": items,
        "command": "\n".join(items),
    }


def _parse_dvol_row(row: Any) -> tuple[int, float]:
    timestamp_ms: int
    close: float | None
    if isinstance(row, (list, tuple)) and len(row) >= 5:
        if row[0] is None:
            raise ValueError("volatility index row missing timestamp")
        timestamp_ms = _coerce_timestamp_ms(row[0])
        close = _finite_number(row[4])
    elif isinstance(row, dict):
        raw_ts = row.get("timestamp")
        if raw_ts is None:
            raw_ts = row.get("t")
        if raw_ts is None:
            raise ValueError("volatility index dict row missing timestamp")
        timestamp_ms = _coerce_timestamp_ms(raw_ts)
        close = _finite_number(
            row.get("close") or row.get("volatility") or row.get("value")
        )
    else:
        raise ValueError("unrecognized volatility index row shape")
    if close is None or close <= 0:
        raise ValueError("invalid volatility index value")
    return timestamp_ms, close


def _coerce_timestamp_ms(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("volatility index timestamp is not integer-like")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ValueError("volatility index timestamp is not integer-like")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("volatility index timestamp is not integer-like") from exc


def _timestamp_from_ms(value: int) -> str:
    try:
        return (
            datetime.fromtimestamp(value / 1000, tz=UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OSError, OverflowError, ValueError) as exc:
        raise ValueError("volatility index timestamp is out of range") from exc


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _coverage_from_observations(
    observations: list[dict[str, Any]],
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> dict[str, Any]:
    dates = [date.fromisoformat(str(row["observed_at"])[:10]) for row in observations]
    first = window_start or min(dates)
    last = window_end or max(dates)
    expected_day_count = (last - first).days + 1
    observed_keys = {item.isoformat() for item in dates}
    missing_days: list[str] = []
    current = first
    while current <= last:
        key = current.isoformat()
        if key not in observed_keys:
            missing_days.append(key)
        current += timedelta(days=1)
    observed_day_count = sum(first <= item <= last for item in set(dates))
    return {
        "expected_day_count": expected_day_count,
        "observed_day_count": observed_day_count,
        "missing_day_count": len(missing_days),
        "coverage_ratio": observed_day_count / expected_day_count,
        "missing_days": missing_days,
    }


def _settlement_evaluation_date(timestamp_seconds: float) -> date:
    evaluation = datetime.fromtimestamp(timestamp_seconds, tz=UTC)
    if evaluation.hour < 8:
        return evaluation.date() - timedelta(days=1)
    return evaluation.date()


def _jsonrpc_result(payload: Any, *, endpoint: str) -> Any:
    if not isinstance(payload, dict):
        raise ValueError(f"{endpoint}: response is not a JSON object")
    if payload.get("error"):
        error = payload["error"]
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message") or error.get("data") or "rpc error"
            raise ValueError(f"{endpoint}: rpc error {code}: {message}")
        raise ValueError(f"{endpoint}: rpc error {error}")
    if "result" not in payload:
        raise ValueError(f"{endpoint}: missing result field")
    return payload["result"]
