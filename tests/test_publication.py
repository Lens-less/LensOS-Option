import hashlib
import json
import shutil
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime, timedelta
from functools import partial
from http.client import HTTPConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from crypto_options_report._canonical import canonical_json_text
from crypto_options_report.market_data import (
    load_public_replay_fixture,
    load_snapshot_fixture,
)
from crypto_options_report.publication import (
    _build_public_report,
    _build_release_gates_from_disk,
    _load_manifest_verification,
    _trim_history_to_capture_clock,
    publish_site,
)
from crypto_options_report.vrp import build_vrp_status

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_FIXTURE = ROOT / "tests" / "fixtures" / "deribit_btc_option_chain_snapshot.json"
PUBLIC_REPLAY_FIXTURE = ROOT / "tests" / "fixtures" / "public_deribit_replay.json"
PUBLIC_TITLE = "\u0042\u0054\u0043\u0020\u671f\u6743\u5356\u65b9\u6ea2\u4ef7\u6301\u7eed\u89c2\u5bdf\u53f0"
SITE_ORIGIN = "https://research.lensos.dev"


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_listing(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        relative: _file_sha256(root / relative)
        for relative in _tree_listing(root)
    }


def _contains_forbidden_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in forbidden or _contains_forbidden_key(nested, forbidden):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_key(item, forbidden) for item in value)
    return False


def _assert_schema_accepts(value: object, schema: dict, *, path: str = "$") -> None:
    if "anyOf" in schema:
        failures = []
        for candidate in schema["anyOf"]:
            try:
                _assert_schema_accepts(value, candidate, path=path)
                return
            except AssertionError as exc:
                failures.append(str(exc))
        raise AssertionError(f"{path} matched no anyOf branch: {failures}")

    expected_type = schema.get("type")
    if expected_type == "null":
        assert value is None, path
    elif expected_type == "boolean":
        assert isinstance(value, bool), path
    elif expected_type == "integer":
        assert isinstance(value, int) and not isinstance(value, bool), path
    elif expected_type == "number":
        assert isinstance(value, (int, float)) and not isinstance(value, bool), path
    elif expected_type == "string":
        assert isinstance(value, str), path
    elif expected_type == "array":
        assert isinstance(value, list), path
        for index, item in enumerate(value):
            _assert_schema_accepts(item, schema.get("items", {}), path=f"{path}[{index}]")
    elif expected_type == "object":
        assert isinstance(value, dict), path
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        assert not missing, f"{path} missing {sorted(missing)}"
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            assert not extra, f"{path} has additional properties {sorted(extra)}"
        for key, item in value.items():
            if key in properties:
                _assert_schema_accepts(item, properties[key], path=f"{path}.{key}")


def _build_underlying_history_fixture(
    captured_at: str,
    *,
    day_count: int = 1300,
) -> dict[str, object]:
    capture_dt = _parse_timestamp(captured_at).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    start_dt = capture_dt - timedelta(days=day_count - 1)
    observations = []
    for index in range(day_count):
        observed_dt = start_dt + timedelta(days=index)
        close = round(
            28000.0
            + (index * 21.5)
            + ((index % 31) - 15) * 37.0
            + ((index % 7) - 3) * 11.0,
            6,
        )
        observations.append(
            {
                "timestamp_ms": int(observed_dt.timestamp() * 1000),
                "observed_at": _timestamp(observed_dt),
                "close": close,
            }
        )
    return {
        "schema_version": "underlying_price_history.v1",
        "captured_at": captured_at,
        "source": "fixture:test_underlying_history",
        "instrument_name": "BTC-PERPETUAL",
        "currency": "BTC",
        "resolution": "1D",
        "resolution_seconds": 86400,
        "requested_days": day_count,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "observations": observations,
    }


def _build_dvol_history_fixture(
    underlying_payload: dict[str, object],
) -> dict[str, object]:
    underlying = underlying_payload
    observations = []
    for index, row in enumerate(underlying["observations"]):
        observations.append(
            {
                "timestamp_ms": row["timestamp_ms"],
                "observed_at": row["observed_at"],
                "close": round(42.0 + ((index % 19) * 0.45), 6),
            }
        )
    first_date = observations[0]["observed_at"][:10]
    last_date = observations[-1]["observed_at"][:10]
    expected_day_count = (
        date.fromisoformat(last_date) - date.fromisoformat(first_date)
    ).days + 1
    return {
        "schema_version": "dvol_history.v1",
        "captured_at": underlying["captured_at"],
        "source": "fixture:test_dvol_history",
        "source_endpoint": "fixture",
        "index_name": "BTC DVOL",
        "currency": "BTC",
        "resolution": "1D",
        "resolution_seconds": 86400,
        "requested_days": 1200,
        "observation_count": len(observations),
        "first_observed_at": observations[0]["observed_at"],
        "last_observed_at": observations[-1]["observed_at"],
        "value_unit": "percent_points",
        "coverage": {
            "expected_day_count": expected_day_count,
            "observed_day_count": len(observations),
            "missing_day_count": 0,
            "coverage_ratio": 1.0,
            "missing_days": [],
        },
        "observations": observations,
    }


def _deep_copy(payload: dict[str, object]) -> dict[str, object]:
    return json.loads(canonical_json_text(payload))


def _append_future_daily_observation(
    payload: dict[str, object],
    *,
    close: float,
) -> dict[str, object]:
    mutated = _deep_copy(payload)
    observations = mutated["observations"]
    last = observations[-1]
    next_dt = _parse_timestamp(last["observed_at"]) + timedelta(days=1)
    observations.append(
        {
            "timestamp_ms": int(next_dt.timestamp() * 1000),
            "observed_at": _timestamp(next_dt),
            "close": close,
        }
    )
    mutated["observation_count"] = len(observations)
    mutated["first_observed_at"] = observations[0]["observed_at"]
    mutated["last_observed_at"] = observations[-1]["observed_at"]
    coverage = mutated.get("coverage")
    if isinstance(coverage, dict):
        first_date = observations[0]["observed_at"][:10]
        last_date = observations[-1]["observed_at"][:10]
        expected_day_count = (
            date.fromisoformat(last_date) - date.fromisoformat(first_date)
        ).days + 1
        coverage["expected_day_count"] = expected_day_count
        coverage["observed_day_count"] = len(observations)
        coverage["missing_day_count"] = 0
        coverage["coverage_ratio"] = 1.0
        coverage["missing_days"] = []
    return mutated


def _build_signal_artifact(captured_at: str) -> dict[str, object]:
    return {
        "schema_version": "signal_preflight.v1",
        "captured_at": captured_at,
        "generated_at": captured_at,
        "research_only": True,
        "status": "projected",
        "headline": "Published public research signal artifact",
        "summary": {
            "signals_measured": 1,
            "signals_with_detectable_ic": 0,
        },
        "bands": {
            "research_window": {
                "cohorts_required": 8,
                "cohorts_seen": 3,
                "cohorts_short_by": 5,
                "pending_cohorts": 1,
                "settled_cohorts": 2,
            }
        },
        "cohorts": [
            {
                "name": "smile_residual_z",
                "registered_at": "2026-07-27T00:00:00Z",
                "status": "collecting",
                "observation_count": 3,
            }
        ],
    }


def _build_series_artifact(
    captured_at: str,
) -> dict[str, object]:
    capture_dt = _parse_timestamp(captured_at).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return {
        "schema_version": "series_history.v1",
        "captured_at": captured_at,
        "points": [
            {
                "observed_at": _timestamp(capture_dt - timedelta(days=2)),
                "smile_residual_z": 0.18,
                "model_delta": 0.09,
            },
            {
                "observed_at": _timestamp(capture_dt - timedelta(days=1)),
                "smile_residual_z": -0.07,
                "model_delta": 0.11,
            },
            {
                "observed_at": _timestamp(capture_dt),
                "smile_residual_z": 0.04,
                "model_delta": 0.08,
            },
        ],
    }


def _build_publication_history_fixture(published_at: str) -> dict[str, object]:
    published_dt = _parse_timestamp(published_at) - timedelta(days=1)
    prior_published_at = _timestamp(published_dt)
    return {
        "schema_version": "publication_history.v1",
        "generated_at": published_at,
        "entries": [
            {
                "date": prior_published_at[:10],
                "captured_at": _timestamp(published_dt - timedelta(hours=1)),
                "published_at": prior_published_at,
                "status": "success",
                "research_publication_status": "GO",
                "capture_row_count": 96,
                "quality_gate_blocked_count": 0,
                "excluded_snapshot_count": 1,
                "manifest_sha256": "a" * 64,
                "reason_code": None,
            }
        ],
    }


class PublicationTests(unittest.TestCase):
    def test_public_report_projects_fail_closed_exchange_event_evidence(self) -> None:
        base_report = {
            "schema_version": "research_report.v1",
            "runtime_context": {"evaluation_clock": "2026-08-03T00:00:00Z"},
            "data_status": {
                "feed_coverage": {
                    "feeds": {
                        "events": {
                            "freshness_status": "fresh",
                            "reason_code": None,
                            "scope": "exchange_native_only",
                            "source_endpoint": "public/status",
                            "status": "available",
                        }
                    }
                }
            },
        }
        cases = (
            (None, "unknown", "EXCHANGE_LOCK_STATE_UNAVAILABLE"),
            (0.0, "normal", "EXCHANGE_NO_ACTIVE_LOCKS"),
            (0.8, "partial", "EXCHANGE_PARTIAL_LOCK"),
            (1.0, "full", "EXCHANGE_FULL_LOCK"),
        )

        for event_score, expected_state, expected_reason in cases:
            with self.subTest(event_score=event_score):
                report = _deep_copy(base_report)
                report["strategy_research"] = {
                    "analysis": {"market": {"event_score": event_score}}
                }

                public_report = _build_public_report(report)

                self.assertEqual(
                    {
                        "event_score": event_score,
                        "exchange_lock_state": expected_state,
                        "macro_calendar_covered": False,
                        "reason_code": expected_reason,
                        "scope": "exchange_native_only",
                        "source": "deribit_public_status",
                        "source_status": "available",
                    },
                    public_report["event_status"],
                )

        missing_report = _deep_copy(base_report)
        missing_report["data_status"]["feed_coverage"]["feeds"]["events"] = {
            "freshness_status": "unknown",
            "reason_code": "EVENTS_MISSING",
            "scope": None,
            "source_endpoint": None,
            "status": "missing",
        }
        missing_report["strategy_research"] = {
            "analysis": {"market": {"event_score": 0.0}}
        }

        missing = _build_public_report(missing_report)["event_status"]

        self.assertEqual("unknown", missing["exchange_lock_state"])
        self.assertEqual("EVENTS_MISSING", missing["reason_code"])
        self.assertIsNone(missing["event_score"])
        self.assertIsNone(missing["source"])

        malformed_report = _deep_copy(base_report)
        malformed_report["data_status"]["feed_coverage"]["feeds"]["events"] = {
            "freshness_status": {"internal": "fresh"},
            "reason_code": {"internal": "EVENTS_MISSING"},
            "scope": {"internal": "exchange_native_only"},
            "source_endpoint": "public/status",
            "status": {"internal": "available"},
        }

        malformed = _build_public_report(malformed_report)["event_status"]

        self.assertIsNone(malformed["source_status"])
        self.assertIsNone(malformed["scope"])
        self.assertEqual("EVENT_SOURCE_UNAVAILABLE", malformed["reason_code"])

    def test_public_report_blocks_candidate_rows_with_conflicting_or_malformed_dte_evidence(
        self,
    ) -> None:
        valid_candidate = {
            "candidate_id": "valid-spread",
            "decision": "RESEARCH_ONLY",
            "structure_type": "call_credit_spread",
            "sell_leg_instrument_name": "BTC-29AUG26-120000-C",
            "buy_leg_instrument_name": "BTC-29AUG26-125000-C",
            "sell_leg_strike_price": 120000.0,
            "buy_leg_strike_price": 125000.0,
            "expiry_date": "2026-08-29",
            "dte_days": 26.0,
            "model_delta": 0.18,
            "net_credit": 0.012,
            "spread_width": 5000.0,
            "premium_currency": "BTC",
            "underlying_price": 115000.0,
        }
        conflict_candidate = {
            **valid_candidate,
            "candidate_id": "conflict-spread",
            "dte_days": 8.0,
        }
        malformed_candidate = {
            "candidate_id": "bad-naked",
            "decision": "REJECT",
            "structure_type": "naked_short_call",
            "instrument_name": "BTC-29AUG26-140000-C",
            "expiry_date": "not-a-date",
            "dte_days": 26.0,
            "model_delta": 0.09,
            "market_mid": 0.004,
            "premium_currency": "BTC",
            "underlying_price": 115000.0,
        }
        valid_rejected_candidate = {
            **malformed_candidate,
            "candidate_id": "valid-rejected-naked",
            "expiry_date": "2026-09-05",
            "dte_days": 33.0,
        }
        source_report = {
            "schema_version": "research_report.v1",
            "reason_codes": ["KEEP_EXISTING_REASON"],
            "runtime_context": {"evaluation_clock": "2026-08-03T00:00:00Z"},
            "candidate_research": {
                "status": "validated",
                "reason_code": None,
                "summary": {
                    "eligible_call_credit_spreads": 1,
                    "eligible_expiries": 1,
                    "eligible_naked_short_calls": 0,
                    "expiries_considered": 1,
                    "rejected_call_credit_spreads": 0,
                    "rejected_naked_short_calls": 1,
                    "review_call_credit_spreads": 1,
                    "review_naked_short_calls": 0,
                },
                "naked_short_calls": {
                    "eligible": [],
                    "review": [],
                    "rejected": [valid_rejected_candidate, malformed_candidate],
                },
                "call_credit_spreads": {
                    "eligible": [valid_candidate],
                    "review": [conflict_candidate],
                    "rejected": [],
                },
            },
            "ev_candidate_scanner": {
                "status": "validated",
                "score_status": "UNCALIBRATED_RESEARCH_ONLY",
                "reason_code": None,
                "summary": {
                    "candidates_scanned": 2,
                    "review_candidates": 1,
                    "rejected_candidates": 1,
                },
                "ranking_basis": {
                    "method": "screening_rank_no_path_risk",
                    "tie_break_order": ["ranking_score"],
                    "absolute_ev_available": False,
                },
                "ranked_candidates": [
                    {
                        "candidate_id": "valid-review",
                        "structure_type": "call_credit_spread",
                        "action": "REVIEW",
                        "expiry_date": "2026-08-29",
                        "dte_days": 26.0,
                        "ranking_score": 0.61,
                        "ev_after_cost_usdc": 42.0,
                        "executable_credit_usdc": 73.0,
                        "path_risk": {
                            "status": "available",
                            "reason_code": None,
                            "p_touch": 0.12,
                            "p_itm": 0.08,
                            "cvar_95_usdc": 80.0,
                            "authoritative_sample_size": 512,
                            "sample_size_basis": "validated",
                        },
                        "kill_conditions": [],
                        "dominated_by": None,
                        "losing_axes": [],
                    },
                    {
                        "candidate_id": "scanner-conflict",
                        "structure_type": "call_credit_spread",
                        "action": "REJECT",
                        "expiry_date": "2026-08-29",
                        "dte_days": 2.0,
                        "ranking_score": 0.12,
                        "ev_after_cost_usdc": -5.0,
                        "executable_credit_usdc": 9.0,
                        "path_risk": {
                            "status": "available",
                            "reason_code": None,
                            "p_touch": 0.41,
                            "p_itm": 0.27,
                            "cvar_95_usdc": 180.0,
                            "authoritative_sample_size": 512,
                            "sample_size_basis": "validated",
                        },
                        "kill_conditions": ["BAD_EDGE"],
                        "dominated_by": "valid-review",
                        "losing_axes": ["edge"],
                    },
                ],
            },
        }

        public_report = _build_public_report(source_report)

        self.assertEqual(
            ["KEEP_EXISTING_REASON", "DTE_EVIDENCE_CONFLICT"],
            public_report["reason_codes"],
        )
        self.assertEqual(
            ["valid-spread"],
            [
                row["candidate_id"]
                for row in public_report["candidate_research"]["call_credit_spreads"][
                    "eligible"
                ]
            ],
        )
        self.assertEqual(
            [],
            public_report["candidate_research"]["call_credit_spreads"]["review"],
        )
        self.assertEqual(
            ["valid-rejected-naked"],
            [
                row["candidate_id"]
                for row in public_report["candidate_research"]["naked_short_calls"][
                    "rejected"
                ]
            ],
        )
        self.assertEqual(
            {
                "eligible_call_credit_spreads": 1,
                "eligible_expiries": 1,
                "eligible_naked_short_calls": 0,
                "expiries_considered": 2,
                "rejected_call_credit_spreads": 0,
                "rejected_naked_short_calls": 1,
                "review_call_credit_spreads": 0,
                "review_naked_short_calls": 0,
            },
            public_report["candidate_research"]["summary"],
        )
        self.assertEqual(
            ["valid-review"],
            [
                row["candidate_id"]
                for row in public_report["ev_candidate_scanner"]["ranked_candidates"]
            ],
        )
        self.assertEqual(
            {
                "candidates_scanned": 1,
                "review_candidates": 1,
                "rejected_candidates": 0,
            },
            public_report["ev_candidate_scanner"]["summary"],
        )
        self.assertEqual(0, public_report["ev_candidate_scanner"]["rejected_count"])

    def test_public_report_blocks_playbook_candidate_when_dte_evidence_conflicts(
        self,
    ) -> None:
        source_report = {
            "schema_version": "research_report.v1",
            "reason_codes": ["KEEP_EXISTING_REASON"],
            "runtime_context": {"evaluation_clock": "2026-08-03T00:00:00Z"},
            "strategy_research": {
                "playbook": {
                    "structure": "CALL_CREDIT_SPREAD",
                    "candidate": {
                        "candidate_id": "playbook-conflict",
                        "expiry_date": "2026-08-29",
                        "dte_days": 8.0,
                        "sell_leg": "BTC-29AUG26-120000-C",
                        "buy_leg": "BTC-29AUG26-125000-C",
                    },
                    "economics": {
                        "premium_currency": "BTC",
                        "credit_usd_shadow": 420.0,
                    },
                    "entry_contract": {
                        "status": "ready",
                        "conditions": [],
                    },
                    "exit_contract": {
                        "policy_status": "defined",
                        "time_management": {},
                    },
                }
            },
        }

        public_report = _build_public_report(source_report)

        self.assertEqual(
            ["KEEP_EXISTING_REASON", "DTE_EVIDENCE_CONFLICT"],
            public_report["reason_codes"],
        )
        self.assertIsNone(public_report["strategy_research"]["playbook"])

    def test_public_report_treats_missing_expiry_metadata_as_unavailable_not_conflict(
        self,
    ) -> None:
        source_report = {
            "schema_version": "research_report.v1",
            "reason_codes": ["KEEP_EXISTING_REASON"],
            "runtime_context": {"evaluation_clock": "2026-08-03T00:00:00Z"},
            "strategy_research": {
                "analysis": {
                    "volatility": {
                        "front_expiry": {},
                        "next_expiry": {
                            "atm_fitted_iv_percent": 54.2,
                            "candidate_eligible": False,
                        },
                    }
                }
            },
        }

        public_report = _build_public_report(source_report)
        volatility = public_report["strategy_research"]["analysis"]["volatility"]

        self.assertEqual(["KEEP_EXISTING_REASON"], public_report["reason_codes"])
        self.assertIsNone(volatility["front_expiry"]["dte_days"])
        self.assertIsNone(volatility["next_expiry"]["dte_days"])

    def test_public_report_does_not_treat_malformed_expiry_metadata_as_missing(
        self,
    ) -> None:
        source_report = {
            "schema_version": "research_report.v1",
            "reason_codes": [],
            "runtime_context": {"evaluation_clock": "2026-08-03T00:00:00Z"},
            "strategy_research": {
                "analysis": {
                    "volatility": {
                        "front_expiry": {"expiry_date": 0},
                        "next_expiry": {},
                    }
                }
            },
        }

        public_report = _build_public_report(source_report)

        self.assertEqual(["DTE_EVIDENCE_CONFLICT"], public_report["reason_codes"])
        self.assertIsNone(
            public_report["strategy_research"]["analysis"]["volatility"][
                "front_expiry"
            ]["dte_days"]
        )

    def test_public_report_does_not_publish_conflicting_expiry_summary_dte(
        self,
    ) -> None:
        source_report = {
            "schema_version": "research_report.v1",
            "reason_codes": [],
            "runtime_context": {"evaluation_clock": "2026-08-03T00:00:00Z"},
            "strategy_research": {
                "analysis": {
                    "volatility": {
                        "front_expiry": {
                            "expiry_date": "2026-08-29",
                            "dte_days": 8.0,
                        },
                        "next_expiry": {},
                    }
                }
            },
        }

        public_report = _build_public_report(source_report)

        self.assertEqual(["DTE_EVIDENCE_CONFLICT"], public_report["reason_codes"])
        self.assertIsNone(
            public_report["strategy_research"]["analysis"]["volatility"][
                "front_expiry"
            ]["dte_days"]
        )

    def test_history_cutoff_uses_exact_capture_clock_and_recomputes_coverage(self) -> None:
        payload = {
            "coverage": {
                "expected_day_count": 4,
                "observed_day_count": 3,
                "missing_day_count": 1,
                "coverage_ratio": 0.75,
                "missing_days": ["2026-08-02"],
            },
            "observations": [
                {"observed_at": "2026-08-01T00:00:00Z", "close": 30.0},
                {"observed_at": "2026-08-03T00:00:00Z", "close": 31.0},
                {"observed_at": "2026-08-03T00:02:00Z", "close": 99.0},
            ],
        }

        trimmed = _trim_history_to_capture_clock(
            payload,
            captured_dt=_parse_timestamp("2026-08-03T00:01:00Z"),
            label="DVOL history",
        )

        self.assertEqual(2, trimmed["observation_count"])
        self.assertEqual("2026-08-03T00:00:00Z", trimmed["last_observed_at"])
        self.assertEqual(
            {
                "expected_day_count": 3,
                "observed_day_count": 2,
                "missing_day_count": 1,
                "coverage_ratio": 2 / 3,
                "missing_days": ["2026-08-02"],
            },
            trimmed["coverage"],
        )

    def test_history_cutoff_rebases_later_capture_metadata_for_vrp(self) -> None:
        snapshot_captured_at = "2026-07-07T00:01:00Z"
        history_captured_at = _timestamp(
            _parse_timestamp(snapshot_captured_at) + timedelta(days=5)
        )
        underlying = _build_underlying_history_fixture(
            history_captured_at,
            day_count=1201,
        )
        dvol = _build_dvol_history_fixture(underlying)
        captured_dt = _parse_timestamp(snapshot_captured_at)

        trimmed_underlying = _trim_history_to_capture_clock(
            underlying,
            captured_dt=captured_dt,
            label="underlying history",
        )
        trimmed_dvol = _trim_history_to_capture_clock(
            dvol,
            captured_dt=captured_dt,
            label="DVOL history",
        )
        status = build_vrp_status(
            trimmed_dvol,
            trimmed_underlying,
            snapshot_captured_at,
        )

        self.assertEqual(snapshot_captured_at, trimmed_underlying["captured_at"])
        self.assertEqual(snapshot_captured_at, trimmed_dvol["captured_at"])
        self.assertEqual(1195, trimmed_dvol["requested_days"])
        self.assertEqual("validated", status["status"])
        self.assertEqual("2026-07-06", status["current"]["date"])

    def _write_json(self, path: Path, payload: object) -> Path:
        path.write_text(canonical_json_text(payload), encoding="utf-8")
        return path

    def _publish(
        self,
        tempdir: Path,
        *,
        snapshot_payload: dict | None = None,
        underlying_payload: dict | None = None,
        dvol_payload: dict | None = None,
        signal_payload: dict | None = None,
        series_payload: dict | None = None,
        publication_history_payload: dict | None = None,
        published_at: str | None = None,
        out_name: str = "site",
        git_sha: str | None = "abc123def456",
        web_build: Path | None = None,
        site_origin: str = SITE_ORIGIN,
    ) -> tuple[Path, dict]:
        snapshot = snapshot_payload or load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
        snapshot_path = self._write_json(tempdir / "snapshot.json", snapshot)
        underlying = underlying_payload or _build_underlying_history_fixture(
            snapshot["captured_at"]
        )
        underlying_path = self._write_json(tempdir / "underlying.json", underlying)
        dvol_path = self._write_json(
            tempdir / "btc-dvol.json",
            dvol_payload or _build_dvol_history_fixture(underlying),
        )
        signal_path = self._write_json(
            tempdir / "signal.json",
            signal_payload or _build_signal_artifact(snapshot["captured_at"]),
        )
        series_path = self._write_json(
            tempdir / "series.json",
            series_payload or _build_series_artifact(snapshot["captured_at"]),
        )
        published_value = published_at or snapshot["captured_at"]
        publication_history_path = self._write_json(
            tempdir / "publication-history.json",
            publication_history_payload
            or _build_publication_history_fixture(published_value),
        )
        output_dir = tempdir / out_name
        resolved_web_build = web_build or self._build_custom_web_build(tempdir)
        result = publish_site(
            snapshot=str(snapshot_path),
            underlying_history=str(underlying_path),
            dvol_history=str(dvol_path),
            signal_artifact=str(signal_path),
            series_artifact=str(series_path),
            publication_history=str(publication_history_path),
            out=str(output_dir),
            published_at=published_value,
            git_sha=git_sha,
            web_build=str(resolved_web_build),
            site_origin=site_origin,
        )
        return output_dir, result

    def _build_custom_web_build(
        self,
        tempdir: Path,
        *,
        js_append: str = "",
        css_append: str = "",
    ) -> Path:
        destination = tempdir / "custom-web-build"
        if destination.exists():
            shutil.rmtree(destination)
        (destination / "assets").mkdir(parents=True)
        (destination / "index.html").write_text(
            "<!doctype html><html lang=\"zh-CN\"><head>"
            "<meta charset=\"UTF-8\">"
            "<title>Public</title><link rel=\"stylesheet\" href=\"./assets/app.css\">"
            "</head><body><div id=\"root\"></div>"
            "<script type=\"module\" src=\"./assets/app.js\"></script></body></html>\n",
            encoding="utf-8",
        )
        (destination / "assets" / "app.js").write_text(
            'document.querySelector("#root")?.setAttribute("data-public", "true");\n',
            encoding="utf-8",
        )
        (destination / "assets" / "app.css").write_text(
            ":root { color-scheme: light; }\n",
            encoding="utf-8",
        )
        public_pages = ROOT / "web" / "public"
        for source in sorted(public_pages.rglob("*")):
            if not source.is_file():
                continue
            target = destination / source.relative_to(public_pages)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for filename in ("LICENSE", "LICENSE-DATA"):
            shutil.copy2(ROOT / filename, destination / filename)
        if js_append:
            target = next(
                path for path in sorted((destination / "assets").iterdir()) if path.suffix == ".js"
            )
            target.write_text(
                target.read_text(encoding="utf-8") + js_append,
                encoding="utf-8",
            )
        if css_append:
            target = next(
                path for path in sorted((destination / "assets").iterdir()) if path.suffix == ".css"
            )
            target.write_text(
                target.read_text(encoding="utf-8") + css_append,
                encoding="utf-8",
            )
        return destination

    def test_publish_is_deterministic_and_rewrites_bundle_paths(self) -> None:
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            published_at = _timestamp(
                _parse_timestamp(snapshot["captured_at"]) + timedelta(hours=25)
            )
            edition_date = published_at[:10]
            first_dir, first_result = self._publish(
                Path(first_tmp),
                published_at=published_at,
                out_name="first",
            )
            second_dir, second_result = self._publish(
                Path(second_tmp),
                published_at=published_at,
                out_name="second",
            )

            asset_paths = {"assets/app.css", "assets/app.js"}
            expected_paths = {
                ".well-known/publish-manifest.json",
                "_headers",
                "LICENSE",
                "LICENSE-DATA",
                "api/openapi.json",
                "api/v1/candidates.json",
                "api/v1/health.json",
                "api/v1/manifest.json",
                "api/v1/signal.json",
                "api/v1/summary.json",
                "api/v1/thermo.json",
                "api/v1/thermo/recent.json",
                "disclaimer.html",
                "en/disclaimer.html",
                "en/methodology.html",
                "en/privacy.html",
                "en/status.html",
                "en/terms.html",
                "index.html",
                "methodology.html",
                "og-card.png",
                "privacy.html",
                "research/report",
                "research/series",
                "research/signal",
                "robots.txt",
                "sitemap.xml",
                "status.html",
                "static-page.css",
                "terms.html",
            }
            expected_paths.update(asset_paths)
            expected_paths.update(
                {
                    f"api/v1/thermo/by-year/{year}.json"
                    for year in ("2023", "2024", "2025", "2026")
                }
            )
            expected_paths.update(
                {
                    f"editions/{edition_date}/{relative}"
                    for relative in asset_paths
                }
            )
            expected_paths.update(
                {
                    f"editions/{edition_date}/.well-known/publish-manifest.json",
                    f"editions/{edition_date}/_headers",
                    f"editions/{edition_date}/LICENSE",
                    f"editions/{edition_date}/LICENSE-DATA",
                    f"editions/{edition_date}/api/openapi.json",
                    f"editions/{edition_date}/api/v1/candidates.json",
                    f"editions/{edition_date}/api/v1/health.json",
                    f"editions/{edition_date}/api/v1/manifest.json",
                    f"editions/{edition_date}/api/v1/signal.json",
                    f"editions/{edition_date}/api/v1/summary.json",
                    f"editions/{edition_date}/api/v1/thermo.json",
                    f"editions/{edition_date}/api/v1/thermo/recent.json",
                    f"editions/{edition_date}/disclaimer.html",
                    f"editions/{edition_date}/en/disclaimer.html",
                    f"editions/{edition_date}/en/methodology.html",
                    f"editions/{edition_date}/en/privacy.html",
                    f"editions/{edition_date}/en/status.html",
                    f"editions/{edition_date}/en/terms.html",
                    f"editions/{edition_date}/index.html",
                    f"editions/{edition_date}/methodology.html",
                    f"editions/{edition_date}/og-card.png",
                    f"editions/{edition_date}/privacy.html",
                    f"editions/{edition_date}/research/report",
                    f"editions/{edition_date}/research/series",
                    f"editions/{edition_date}/research/signal",
                    f"editions/{edition_date}/robots.txt",
                    f"editions/{edition_date}/sitemap.xml",
                    f"editions/{edition_date}/status.html",
                    f"editions/{edition_date}/static-page.css",
                    f"editions/{edition_date}/terms.html",
                }
            )
            expected_paths.update(
                {
                    f"editions/{edition_date}/api/v1/thermo/by-year/{year}.json"
                    for year in ("2023", "2024", "2025", "2026")
                }
            )

            self.assertTrue(expected_paths.issubset(set(_tree_listing(first_dir))))
            self.assertEqual(
                (ROOT / "LICENSE").read_bytes(),
                (first_dir / "LICENSE").read_bytes(),
            )
            self.assertEqual(
                (ROOT / "LICENSE-DATA").read_bytes(),
                (first_dir / "LICENSE-DATA").read_bytes(),
            )
            self.assertEqual(_tree_listing(first_dir), _tree_listing(second_dir))
            self.assertEqual(_tree_hashes(first_dir), _tree_hashes(second_dir))

            index_html = (first_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn(f"<title>{PUBLIC_TITLE}</title>", index_html)
            self.assertIn(
                f'<meta property="og:title" content="{PUBLIC_TITLE}">',
                index_html,
            )
            self.assertIn(
                f'<meta property="og:url" content="{SITE_ORIGIN}/">',
                index_html,
            )
            self.assertIn('<meta name="description" content="', index_html)
            self.assertIn(
                f'<link rel="canonical" href="{SITE_ORIGIN}/">',
                index_html,
            )
            self.assertIn(
                '<meta name="robots" content="index,follow,max-image-preview:large">',
                index_html,
            )
            self.assertIn(
                f'<meta property="og:image" content="{SITE_ORIGIN}/og-card.png">',
                index_html,
            )
            self.assertIn(
                '<meta name="twitter:card" content="summary_large_image">',
                index_html,
            )
            self.assertIn(
                f'<meta name="twitter:image" content="{SITE_ORIGIN}/og-card.png">',
                index_html,
            )
            self.assertEqual(
                f"User-agent: *\nAllow: /\nSitemap: {SITE_ORIGIN}/sitemap.xml\n",
                (first_dir / "robots.txt").read_text(encoding="utf-8"),
            )
            sitemap = (first_dir / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn(f"<loc>{SITE_ORIGIN}/</loc>", sitemap)
            self.assertIn(
                f"<loc>{SITE_ORIGIN}/editions/{edition_date}/</loc>", sitemap
            )
            edition_index = (
                first_dir / "editions" / edition_date / "index.html"
            ).read_text(encoding="utf-8")
            self.assertIn(
                f'<meta property="og:url" content="{SITE_ORIGIN}/editions/{edition_date}/">',
                edition_index,
            )
            self.assertIn(
                f'<link rel="canonical" href="{SITE_ORIGIN}/editions/{edition_date}/">',
                edition_index,
            )
            self.assertTrue(
                (first_dir / "og-card.png").read_bytes().startswith(
                    b"\x89PNG\r\n\x1a\n"
                )
            )
            self.assertIn('src="./assets/', index_html)
            self.assertIn('href="./assets/', index_html)
            self.assertNotIn("/evidence/assets/", index_html)
            archived_index = (
                first_dir / "editions" / edition_date / "index.html"
            ).read_text(encoding="utf-8")
            self.assertIn('src="./assets/', archived_index)
            self.assertIn('href="./assets/', archived_index)
            self.assertIn('lang="zh-CN"', (first_dir / "status.html").read_text(encoding="utf-8"))
            self.assertIn(
                'href="./LICENSE"',
                (first_dir / "terms.html").read_text(encoding="utf-8"),
            )
            self.assertIn(
                'href="../LICENSE"',
                (first_dir / "en" / "terms.html").read_text(encoding="utf-8"),
            )
            self.assertIn(
                'href="./LICENSE-DATA"',
                (first_dir / "editions" / edition_date / "terms.html").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertIn(
                'href="../LICENSE-DATA"',
                (
                    first_dir
                    / "editions"
                    / edition_date
                    / "en"
                    / "terms.html"
                ).read_text(encoding="utf-8"),
            )
            self.assertIn('lang="en"', (first_dir / "en" / "status.html").read_text(encoding="utf-8"))
            self.assertIn("静态状态页不会自行判定", (first_dir / "status.html").read_text(encoding="utf-8"))
            self.assertIn("公开头条默认滞后一日", (first_dir / "methodology.html").read_text(encoding="utf-8"))
            headers = (first_dir / "_headers").read_text(encoding="utf-8")
            self.assertTrue(headers.startswith("/*\n"))
            self.assertIn("/api/v1/*", headers)
            self.assertIn("Access-Control-Allow-Origin: *", headers)
            self.assertIn("Cache-Control: public, max-age=300", headers)
            self.assertIn("/research/*", headers)
            self.assertIn("Content-Type: application/json; charset=utf-8", headers)
            self.assertIn("Content-Security-Policy: default-src 'self';", headers)
            self.assertIn("X-Content-Type-Options: nosniff", headers)
            self.assertIn("Referrer-Policy: no-referrer", headers)
            self.assertIn("X-Frame-Options: DENY", headers)
            self.assertNotIn("'unsafe-inline'", headers)

            manifest = json.loads(
                (first_dir / "api" / "v1" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            publish_manifest = json.loads(
                (first_dir / ".well-known" / "publish-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest, publish_manifest)
            self.assertEqual(first_result["manifest_sha256"], second_result["manifest_sha256"])
            self.assertEqual("verified", manifest["manifest_verification"]["status"])
            for artifact in manifest["artifacts"]:
                path = first_dir / artifact["path"]
                self.assertTrue(path.is_file(), artifact["path"])
                self.assertEqual(artifact["sha256"], _file_sha256(path))

    def test_publish_sets_published_runtime_and_release_gates_for_25_hours(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            captured_at = snapshot["captured_at"]
            published_at = _timestamp(_parse_timestamp(captured_at) + timedelta(hours=25))
            output_dir, _ = self._publish(Path(tmp), published_at=published_at)

            report = json.loads(
                (output_dir / "research" / "report").read_text(encoding="utf-8")
            )
            health = json.loads(
                (output_dir / "api" / "v1" / "health.json").read_text(encoding="utf-8")
            )
            summary = json.loads(
                (output_dir / "api" / "v1" / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            gates = {
                gate["name"]: gate
                for gate in report["full_system_surface"]["release_gates"]
            }

            self.assertEqual("published", report["runtime_context"]["mode"])
            self.assertFalse(report["runtime_context"]["replay"])
            self.assertEqual(
                "deribit_published_snapshot", report["data_status"]["source"]
            )
            self.assertEqual(
                "published_snapshot", report["data_trust"]["source_class"]
            )
            self.assertEqual(
                "deribit_published_snapshot",
                report["strategy_research"]["collection"]["source"],
            )
            self.assertEqual(captured_at, report["runtime_context"]["evaluation_clock"])
            self.assertEqual(captured_at, report["publish_edition"]["captured_at"])
            self.assertEqual(published_at, report["publish_edition"]["published_at"])
            self.assertEqual(
                _timestamp(_parse_timestamp(captured_at) + timedelta(days=2)),
                report["publish_edition"]["stale_after"],
            )
            self.assertEqual("GO", gates["research_publication"]["status"])
            self.assertEqual("NO-GO", gates["execution_authorization"]["status"])
            self.assertNotIn(
                "account_age_sec",
                [item["metric"] for item in report["strategy_research"]["monitoring"]],
            )
            self.assertNotIn(
                "account_gate",
                [
                    item["id"]
                    for item in report["strategy_research"]["playbook"]["entry_contract"][
                        "conditions"
                    ]
                ],
            )
            self.assertEqual(
                [],
                report["strategy_research"]["playbook"]["exit_contract"][
                    "position_states"
                ],
            )
            self.assertNotIn(
                "Attach a fresh read-only account snapshot before any sizing study.",
                report["strategy_research"]["review"]["promotion_conditions"],
            )
            self.assertEqual(
                report["data_trust"]["verdict"],
                summary["data_status"]["evidence_class"],
            )
            self.assertNotEqual(
                summary["vrp"]["evidence_class"],
                summary["data_status"]["evidence_class"],
            )
            field_evidence = summary["vrp"]["field_evidence"]
            self.assertEqual(
                {
                    "dvol_percent",
                    "percentile",
                    "rv30_percent",
                    "vrp_percent_points",
                },
                set(field_evidence),
            )
            for field in field_evidence.values():
                self.assertEqual(
                    summary["vrp"]["evidence_class"], field["evidence_class"]
                )
            self.assertFalse(health["is_stale_at_publish"])
            self.assertEqual("verified", health["publish_manifest_status"])
            self.assertEqual("available", health["publication_history"]["status"])
            self.assertEqual(1, len(health["publication_history"]["history"]))
            self.assertNotIn(
                "manifest_sha256",
                health["publication_history"]["history"][0],
            )
            self.assertIn("change", summary)
            self.assertIn("alert", summary)
            self.assertIn("publication_history", summary)

    def test_publish_marks_a_50_hour_old_edition_as_stale_at_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            captured_at = snapshot["captured_at"]
            published_at = _timestamp(_parse_timestamp(captured_at) + timedelta(hours=50))
            output_dir, _ = self._publish(Path(tmp), published_at=published_at)

            health = json.loads(
                (output_dir / "api" / "v1" / "health.json").read_text(encoding="utf-8")
            )
            self.assertTrue(health["is_stale_at_publish"])
            self.assertEqual(
                _timestamp(_parse_timestamp(captured_at) + timedelta(days=2)),
                health["stale_after"],
            )

    def test_publish_stays_fail_closed_when_quality_gates_block_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocked_snapshot = load_public_replay_fixture(
                str(PUBLIC_REPLAY_FIXTURE),
                scenario="empty_dvol_data",
            )
            with self.assertRaisesRegex(ValueError, "publication blocked"):
                self._publish(Path(tmp), snapshot_payload=blocked_snapshot)

    def test_publish_rejects_missing_inputs_and_non_empty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tempdir = Path(tmp)
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            underlying = _build_underlying_history_fixture(snapshot["captured_at"])
            out_dir = tempdir / "site"
            out_dir.mkdir()
            (out_dir / "sentinel.txt").write_text("occupied", encoding="utf-8")

            underlying_path = self._write_json(tempdir / "underlying.json", underlying)
            dvol_path = self._write_json(
                tempdir / "btc-dvol.json",
                _build_dvol_history_fixture(underlying),
            )
            signal_path = self._write_json(
                tempdir / "signal.json",
                _build_signal_artifact(snapshot["captured_at"]),
            )
            series_path = self._write_json(
                tempdir / "series.json",
                _build_series_artifact(snapshot["captured_at"]),
            )
            publication_history_path = self._write_json(
                tempdir / "publication-history.json",
                _build_publication_history_fixture("2026-08-01T09:00:14Z"),
            )
            web_build = self._build_custom_web_build(tempdir)

            with self.assertRaisesRegex(ValueError, "snapshot input not found"):
                publish_site(
                    snapshot=str(tempdir / "missing-snapshot.json"),
                    underlying_history=str(underlying_path),
                    dvol_history=str(dvol_path),
                    signal_artifact=str(signal_path),
                    series_artifact=str(series_path),
                    publication_history=str(publication_history_path),
                    out=str(tempdir / "other-site"),
                    published_at="2026-08-01T09:00:14Z",
                    site_origin=SITE_ORIGIN,
                )

            with self.assertRaisesRegex(ValueError, "output directory must not already contain files"):
                publish_site(
                    snapshot=str(SNAPSHOT_FIXTURE),
                    underlying_history=str(underlying_path),
                    dvol_history=str(dvol_path),
                    signal_artifact=str(signal_path),
                    series_artifact=str(series_path),
                    publication_history=str(publication_history_path),
                    out=str(out_dir),
                    published_at="2026-08-01T09:00:14Z",
                    web_build=str(web_build),
                    site_origin=SITE_ORIGIN,
                )

            with self.assertRaisesRegex(
                ValueError,
                "published_at must not be earlier than snapshot.captured_at",
            ):
                publish_site(
                    snapshot=str(SNAPSHOT_FIXTURE),
                    underlying_history=str(underlying_path),
                    dvol_history=str(dvol_path),
                    signal_artifact=str(signal_path),
                    series_artifact=str(series_path),
                    publication_history=str(publication_history_path),
                    out=str(tempdir / "too-early"),
                    published_at=_timestamp(
                        _parse_timestamp(snapshot["captured_at"]) - timedelta(seconds=1)
                    ),
                    web_build=str(web_build),
                    site_origin=SITE_ORIGIN,
                )

    def test_publish_rejects_non_https_or_non_origin_site_urls_before_writing(self) -> None:
        invalid_origins = (
            "",
            "http://research.example.com",
            "https://user:password@research.example.com",
            "https://research.example.com/public",
            "https://research.example.com/?preview=true",
            "https://research.example.com/#latest",
            "https://localhost",
            "https://127.0.0.1",
            "https://[::1]",
            "https://intranet",
            "https://preview.invalid",
            "https://preview.alt",
            "https://service.arpa",
            "https://research.example.com",
            "https://research.lensos.dev:8443",
            "https://research.lensos.dev.",
            "https://-research.lensos.dev",
            "https://research_.lensos.dev",
            "https://research..lensos.dev",
            "https://research.lensos.123",
            f"https://{'a' * 64}.lensos.dev",
        )
        for index, site_origin in enumerate(invalid_origins):
            with self.subTest(site_origin=site_origin), tempfile.TemporaryDirectory() as tmp:
                tempdir = Path(tmp)
                output_dir = tempdir / f"invalid-origin-{index}"
                with self.assertRaisesRegex(ValueError, "site_origin"):
                    self._publish(
                        tempdir,
                        out_name=output_dir.name,
                        site_origin=site_origin,
                    )
                self.assertFalse(output_dir.exists())

    def test_publish_rejects_public_build_without_license_files(self) -> None:
        for filename in ("LICENSE", "LICENSE-DATA"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                tempdir = Path(tmp)
                web_build = self._build_custom_web_build(tempdir)
                (web_build / filename).unlink()

                with self.assertRaisesRegex(
                    ValueError,
                    rf"web build is missing {filename}",
                ):
                    self._publish(
                        tempdir,
                        out_name=f"site-without-{filename.lower()}",
                        web_build=web_build,
                    )

    def test_publish_report_is_explicitly_sanitized_and_tree_excludes_private_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, _ = self._publish(Path(tmp))
            report = json.loads(
                (output_dir / "research" / "report").read_text(encoding="utf-8")
            )
            self.assertEqual(
                {
                    "action",
                    "backtest_status",
                    "blocked_outputs",
                    "calibration_status",
                    "candidate_research",
                    "data_status",
                    "data_trust",
                    "effective_mode",
                    "event_status",
                    "ev_candidate_scanner",
                    "full_system_surface",
                    "generated_at",
                    "mode",
                    "mode_gate",
                    "publish_edition",
                    "reason_codes",
                    "risk_state",
                    "runtime_context",
                    "schema_version",
                    "strategy_research",
                    "vol_surface_status",
                    "vrp_status",
                },
                set(report),
            )
            self.assertEqual(
                {
                    "event_score",
                    "exchange_lock_state",
                    "macro_calendar_covered",
                    "reason_code",
                    "scope",
                    "source",
                    "source_status",
                },
                set(report["event_status"]),
            )
            self.assertNotIn("source_endpoint", report["event_status"])
            self.assertFalse(report["event_status"]["macro_calendar_covered"])
            for key in (
                "account_status",
                "combination_risk",
                "confidence",
                "paper_proposal_ledger",
                "permission_state",
                "pnl_evidence",
                "portfolio_risk",
                "position_management",
                "walk_forward_calibration",
            ):
                self.assertNotIn(key, report)
            self.assertNotIn(
                "risk_budget",
                (report.get("strategy_research") or {}).get("playbook") or {},
            )
            self.assertEqual(
                {
                    "generated_at",
                    "release_gates",
                    "release_readiness",
                    "schema_version",
                    "status",
                },
                set(report["full_system_surface"]),
            )
            scanner_rows = (
                (report.get("ev_candidate_scanner") or {}).get("ranked_candidates") or []
            )
            if scanner_rows:
                self.assertFalse(
                    {
                        "absolute_ev",
                        "edge_components",
                        "fair_value_usdc",
                        "margin_snapshot",
                        "premium_usdc",
                        "reason_codes",
                        "structure_legs",
                    }
                    & set(scanner_rows[0])
                )
            forbidden = {
                "api_key",
                "secret",
                "access_token",
                "refresh_token",
                "account_status",
                "contracts",
                "margin_snapshot",
                "max_depth_fraction",
                "max_new_margin_nav",
                "max_single_naked_stress_loss_nav",
                "max_single_spread_loss_nav",
                "paper_manual_trade_candidates",
                "paper_proposal_ledger",
                "portfolio_risk",
                "position_management",
                "positions",
                "projected_margin",
                "quantity",
                "recommended_size",
                "size_contracts",
                "trade_instruction",
            }
            for relative in _tree_listing(output_dir):
                path = output_dir / relative
                if path.name in {"_headers", "LICENSE", "LICENSE-DATA"} or path.suffix in {
                    ".html",
                    ".js",
                    ".css",
                    ".png",
                    ".txt",
                    ".xml",
                }:
                    continue
                with self.subTest(relative=relative):
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    self.assertFalse(_contains_forbidden_key(payload, forbidden))

    def test_publish_accepts_the_blocked_signal_summary_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tempdir = Path(tmp)
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            signal = _build_signal_artifact(snapshot["captured_at"])
            signal["status"] = "blocked"
            signal["reason_codes"] = ["INSUFFICIENT_SIGNAL_OBSERVATIONS"]
            signal["summary"] = {
                "signals_measured": 0,
                "signals_with_detectable_ic": 0,
                "best_exploratory_signal": None,
                "pre_registered_axis": "smile_residual_z",
                "pre_registered_axis_verdict": None,
                "promotion_eligible": False,
                "promotion_eligibility_basis": (
                    "pre_registered_axis_only; see docs/model-promotion.md"
                ),
            }

            output_dir, _ = self._publish(
                tempdir,
                signal_payload=signal,
                out_name="blocked-signal-contract",
            )

            published = json.loads(
                (output_dir / "research" / "signal").read_text(encoding="utf-8")
            )
            summary = published["summary"]
            self.assertNotIn("best_signal", summary)
            self.assertIsNone(summary["best_exploratory_signal"])
            self.assertIs(summary["promotion_eligible"], False)

    def test_publish_blocks_uncataloged_reason_code_in_public_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tempdir = Path(tmp)
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            signal = _build_signal_artifact(snapshot["captured_at"])
            signal["status"] = "blocked"
            signal["reason_codes"] = ["SYNTHETIC_REASON_UNREGISTERED"]

            with self.assertRaisesRegex(
                ValueError,
                "SYNTHETIC_REASON_UNREGISTERED",
            ):
                self._publish(
                    tempdir,
                    signal_payload=signal,
                    out_name="uncataloged-reason-code",
                )

    def test_publish_preflights_forwarded_artifact_privacy_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tempdir = Path(tmp)
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            cases = {
                "private-field": {"account_status": {"status": "missing"}},
                "absolute-path": {
                    "diagnostic_path": r"C:\Users\operator\private\signal.json"
                },
                "unexpected-public-field": {
                    "operator_notes": {"desk_name": "research-a", "equity_usd": 123456.78}
                },
            }
            for out_name, injected in cases.items():
                with self.subTest(out_name=out_name):
                    signal = _build_signal_artifact(snapshot["captured_at"])
                    signal.update(injected)
                    with self.assertRaisesRegex(ValueError, "publication blocked"):
                        self._publish(
                            tempdir,
                            signal_payload=signal,
                            out_name=out_name,
                        )
                    output_dir = tempdir / out_name
                    self.assertTrue(output_dir.is_dir())
                    self.assertEqual([], list(output_dir.rglob("*")))

    def test_publish_rejects_unlisted_series_fields_even_when_not_blacklisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tempdir = Path(tmp)
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            series = _build_series_artifact(snapshot["captured_at"])
            series["points"][0]["desk_comment"] = "private review note"
            with self.assertRaisesRegex(ValueError, "publication blocked"):
                self._publish(
                    tempdir,
                    series_payload=series,
                    out_name="series-unexpected-field",
                )
            output_dir = tempdir / "series-unexpected-field"
            self.assertTrue(output_dir.is_dir())
            self.assertEqual([], list(output_dir.rglob("*")))

    def test_publish_rejects_signal_or_series_data_after_the_snapshot_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tempdir = Path(tmp)
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            captured_dt = _parse_timestamp(snapshot["captured_at"])

            future_signal = _build_signal_artifact(snapshot["captured_at"])
            future_signal["generated_at"] = _timestamp(
                captured_dt + timedelta(seconds=1)
            )
            with self.assertRaisesRegex(ValueError, "signal artifact.*snapshot.captured_at"):
                self._publish(
                    tempdir,
                    signal_payload=future_signal,
                    out_name="future-signal",
                )

            future_signal_row = _build_signal_artifact(snapshot["captured_at"])
            future_signal_row["signals"] = {
                "smile_residual_z": {
                    "per_date": [
                        {
                            "snapshot_date": (
                                captured_dt + timedelta(days=1)
                            ).date().isoformat()
                        }
                    ]
                }
            }
            with self.assertRaisesRegex(ValueError, "signal artifact.*snapshot cutoff"):
                self._publish(
                    tempdir,
                    signal_payload=future_signal_row,
                    out_name="future-signal-row",
                )

            future_series = _build_series_artifact(snapshot["captured_at"])
            future_series["points"][-1]["observed_at"] = _timestamp(
                captured_dt + timedelta(days=1)
            )
            with self.assertRaisesRegex(ValueError, "series artifact.*snapshot cutoff"):
                self._publish(
                    tempdir,
                    series_payload=future_series,
                    out_name="future-series",
                )

    def test_publish_rejects_bundle_tokens_and_non_sha_git_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tempdir = Path(tmp)
            web_build = self._build_custom_web_build(
                tempdir,
                js_append='\nwindow.__leak = "api_key";\n',
                css_append='\n.leak { content: "dk_live_7f3"; }\n',
            )
            with self.assertRaisesRegex(ValueError, "publication blocked"):
                self._publish(
                    tempdir,
                    out_name="bundle-leak",
                    web_build=web_build,
                )
            shape_leak_build = self._build_custom_web_build(
                tempdir,
                js_append='\nwindow.__shape = "portfolio_risk";\n',
            )
            with self.assertRaisesRegex(ValueError, "publication blocked"):
                self._publish(
                    tempdir,
                    out_name="bundle-shape-leak",
                    web_build=shape_leak_build,
                )
            with self.assertRaisesRegex(ValueError, "git_sha must be a plain SHA"):
                self._publish(
                    tempdir,
                    out_name="bad-git-sha",
                    git_sha=r"built from C:\Users\example-user\secret-build",
                )

    def test_release_gate_is_recomputed_from_disk_and_manifest_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, _ = self._publish(Path(tmp))
            report = json.loads(
                (output_dir / "research" / "report").read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (output_dir / "api" / "v1" / "manifest.json").read_text(encoding="utf-8")
            )

            verification = _load_manifest_verification(output_dir, manifest)
            gates = {
                gate["name"]: gate
                for gate in _build_release_gates_from_disk(
                    report=report,
                    out_path=output_dir,
                    manifest_verification=verification,
                )
            }
            self.assertEqual("GO", gates["research_publication"]["status"])
            self.assertEqual("verified", gates["research_publication"]["publication_evidence"]["publish_manifest"])

            (output_dir / "methodology.html").unlink()
            gates = {
                gate["name"]: gate
                for gate in _build_release_gates_from_disk(
                    report=report,
                    out_path=output_dir,
                    manifest_verification=verification,
                )
            }
            self.assertEqual("NO-GO", gates["research_publication"]["status"])
            self.assertIn("methodology", gates["research_publication"]["missing_prerequisites"])

    def test_publish_trims_future_history_rows_to_snapshot_date(self) -> None:
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            baseline_underlying = _build_underlying_history_fixture(
                snapshot["captured_at"]
            )
            baseline_dvol = _build_dvol_history_fixture(baseline_underlying)
            future_underlying = _append_future_daily_observation(
                baseline_underlying,
                close=float(baseline_underlying["observations"][-1]["close"]) * 1.05,
            )
            future_dvol = _append_future_daily_observation(
                baseline_dvol,
                close=88.0,
            )
            published_at = _timestamp(
                _parse_timestamp(snapshot["captured_at"]) + timedelta(hours=25)
            )
            baseline_dir, _ = self._publish(
                Path(first_tmp),
                snapshot_payload=snapshot,
                underlying_payload=baseline_underlying,
                dvol_payload=baseline_dvol,
                published_at=published_at,
                out_name="baseline",
            )
            skewed_dir, _ = self._publish(
                Path(second_tmp),
                snapshot_payload=snapshot,
                underlying_payload=future_underlying,
                dvol_payload=future_dvol,
                published_at=published_at,
                out_name="skewed",
            )

            self.assertEqual(_tree_hashes(baseline_dir), _tree_hashes(skewed_dir))
            thermo = json.loads(
                (skewed_dir / "api" / "v1" / "thermo.json").read_text(encoding="utf-8")
            )
            self.assertTrue(thermo["series"])
            self.assertLessEqual(
                max(point["observed_at"][:10] for point in thermo["series"]),
                snapshot["captured_at"][:10],
            )
            manifest = json.loads(
                (skewed_dir / "api" / "v1" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                "trimmed to the snapshot captured_at clock",
                manifest["manifest_policy"]["history_alignment"],
            )

    def test_publish_exposes_numeric_field_evidence_and_thermo_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, _ = self._publish(Path(tmp))
            candidates = json.loads(
                (output_dir / "api" / "v1" / "candidates.json").read_text(encoding="utf-8")
            )
            signal = json.loads(
                (output_dir / "api" / "v1" / "signal.json").read_text(encoding="utf-8")
            )
            thermo = json.loads(
                (output_dir / "api" / "v1" / "thermo.json").read_text(encoding="utf-8")
            )
            recent = json.loads(
                (output_dir / "api" / "v1" / "thermo" / "recent.json").read_text(encoding="utf-8")
            )
            by_year = json.loads(
                (output_dir / "api" / "v1" / "thermo" / "by-year" / "2026.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("public_thermo.v1", thermo["schema_version"])
            self.assertIn("year_shards", thermo)
            self.assertIn("recent_series_path", thermo)
            self.assertLessEqual(len(recent["series"]), len(thermo["series"]))
            self.assertTrue(by_year["series"])
            gated_point = next(
                point for point in thermo["series"] if point["percentile"] is None
            )
            self.assertIsNone(gated_point["band"])
            self.assertLess(
                gated_point["percentile_sample_count"],
                thermo["minimum_series_sample_count"],
            )
            if candidates["ranked_candidates"]:
                row = candidates["ranked_candidates"][0]
                self.assertIn("field_evidence", row)
                self.assertIn("ranking_score", row["field_evidence"])
            self.assertIn("field_evidence", signal["artifact"]["bands"]["research_window"])
            self.assertIn(
                "cohorts_seen",
                signal["artifact"]["bands"]["research_window"]["field_evidence"],
            )

            openapi = json.loads(
                (output_dir / "api" / "openapi.json").read_text(encoding="utf-8")
            )
            self.assertEqual("3.1.0", openapi["openapi"])
            for path, operation in openapi["paths"].items():
                with self.subTest(path=path):
                    response = operation["get"]["responses"]["200"]
                    schema = response["content"]["application/json"]["schema"]
                    self.assertRegex(schema["$ref"], r"^#/components/schemas/")
            summary_schema = openapi["components"]["schemas"]["Summary"]
            self.assertFalse(summary_schema["additionalProperties"])
            public_summary = json.loads(
                (output_dir / "api" / "v1" / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                set(public_summary),
                set(summary_schema["required"]),
            )
            endpoint_files = {
                "/api/v1/summary.json": "api/v1/summary.json",
                "/api/v1/thermo.json": "api/v1/thermo.json",
                "/api/v1/thermo/recent.json": "api/v1/thermo/recent.json",
                "/api/v1/thermo/by-year/{year}.json": "api/v1/thermo/by-year/2026.json",
                "/api/v1/candidates.json": "api/v1/candidates.json",
                "/api/v1/signal.json": "api/v1/signal.json",
                "/api/v1/health.json": "api/v1/health.json",
                "/api/v1/manifest.json": "api/v1/manifest.json",
                "/research/report": "research/report",
                "/research/signal": "research/signal",
                "/research/series": "research/series",
            }
            for route, relative_path in endpoint_files.items():
                with self.subTest(response_schema=route):
                    response_schema = openapi["paths"][route]["get"]["responses"][
                        "200"
                    ]["content"]["application/json"]["schema"]
                    component = response_schema["$ref"].rsplit("/", 1)[-1]
                    payload = json.loads(
                        (output_dir / relative_path).read_text(encoding="utf-8")
                    )
                    _assert_schema_accepts(
                        payload,
                        openapi["components"]["schemas"][component],
                    )
            openapi_text = canonical_json_text(openapi).lower()
            for private_term in ("margin_snapshot", "account_status", "api_key"):
                self.assertNotIn(private_term, openapi_text)

    def test_published_site_serves_index_assets_and_extensionless_json_without_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, _ = self._publish(Path(tmp))
            asset_paths = sorted(
                f"/assets/{path.name}"
                for path in (output_dir / "assets").iterdir()
                if path.is_file()
            )
            handler = partial(SimpleHTTPRequestHandler, directory=str(output_dir))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                for path in (
                    "/",
                    "/research/report",
                    "/research/signal",
                    "/research/series",
                    "/api/v1/manifest.json",
                    "/api/v1/summary.json",
                    "/api/v1/thermo.json",
                    "/api/v1/candidates.json",
                    "/api/v1/signal.json",
                    "/api/v1/health.json",
                    "/api/openapi.json",
                    "/.well-known/publish-manifest.json",
                    "/methodology.html",
                    "/disclaimer.html",
                    "/privacy.html",
                    "/robots.txt",
                    "/sitemap.xml",
                    "/terms.html",
                    "/status.html",
                    "/_headers",
                ):
                    with self.subTest(path=path):
                        connection.request("GET", path)
                        response = connection.getresponse()
                        body = response.read()
                        self.assertEqual(200, response.status)
                        self.assertTrue(body)
                for path in asset_paths:
                    with self.subTest(path=path):
                        connection.request("GET", path)
                        response = connection.getresponse()
                        body = response.read()
                        self.assertEqual(200, response.status)
                        self.assertTrue(body)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
