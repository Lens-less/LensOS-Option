"""Authored public API v1 schemas. No values or reports enter this module.

The schema is JSON Schema 2020-12 as used by OpenAPI 3.1. Projection functions
in publication.py are the field allowlists; nullable properties preserve their
explicit unavailable values. Optional properties represent producer variants,
not accidental omissions inferred from a sample. Semantic evidence validation
continues to live in the domain validators.
"""

from __future__ import annotations

from typing import Any

Schema = dict[str, Any]
TEXT: Schema = {"type": "string"}
NUMBER: Schema = {"type": "number"}
COUNT: Schema = {"type": "integer", "minimum": 0}
BOOL: Schema = {"type": "boolean"}
NULL: Schema = {"type": "null"}
DATE: Schema = {"type": "string", "format": "date"}
TIME: Schema = {"type": "string", "format": "date-time"}
HASH: Schema = {"type": "string", "pattern": "^[0-9a-f]{64}$"}


def ref(name: str) -> Schema:
    return {"$ref": f"#/components/schemas/{name}"}


def nullable(schema: Schema) -> Schema:
    return {"anyOf": [schema, NULL]}


def array(schema: Schema, **constraints: Any) -> Schema:
    return {"type": "array", "items": schema, **constraints}


def obj(properties: dict[str, Schema], *, optional: tuple[str, ...] = ()) -> Schema:
    return {
        "type": "object",
        "properties": properties,
        "required": [key for key in properties if key not in optional],
        "additionalProperties": False,
    }


def fields(names: str, schema: Schema) -> dict[str, Schema]:
    return dict.fromkeys(names.split(), schema)


def enum(*values: str) -> Schema:
    return {"type": "string", "enum": list(values)}


N_TEXT = nullable(TEXT)
N_NUMBER = nullable(NUMBER)
N_COUNT = nullable(COUNT)
N_BOOL = nullable(BOOL)
N_DATE = nullable(DATE)
N_TIME = nullable(TIME)
STRINGS = array(TEXT)
FALSE: Schema = {"type": "boolean", "const": False}
TRUE: Schema = {"type": "boolean", "const": True}


def strategy_brief_schema() -> Schema:
    """Keep the one-unit leg schema inline for the public privacy allowlist."""
    action = enum("STRATEGIES_AVAILABLE", "WATCH", "NO_TRADE")
    scope = obj({
        **fields("underlying structure_type direction entry_cost_basis exit_basis", TEXT),
        "dte_band_days": array(NUMBER, minItems=2, maxItems=2),
        "dte_days": NUMBER,
        "expiry_date": DATE,
    })
    strategy = obj({
        **fields("analysis_run_id candidate_id recommendation_id thesis_zh copy_recipe", TEXT),
        "as_of": TIME,
        "valid_until": TIME,
        "expiry_date": DATE,
        "dte_days": NUMBER,
        "rank": {"type": "integer", "minimum": 1},
        "structure_type": enum("BEAR_CALL_CREDIT_SPREAD", "BULL_PUT_CREDIT_SPREAD", "IRON_CONDOR"),
        "recommendation_status": enum("WATCH"),
        "primary_reason_codes": STRINGS,
        "kill_conditions": STRINGS,
        "legs": array(obj({
            "instrument_name": TEXT,
            "side": enum("BUY", "SELL"),
            "option_type": enum("call", "put"),
            "strike": NUMBER,
            "quantity": {"type": "number", "const": 1},
            "bid": NUMBER,
            "ask": NUMBER,
            "observed_at": TIME,
            "expiry_date": DATE,
            "premium_currency": TEXT,
            "premium_unit": enum("quote_currency", "inverse_base_currency"),
        }), minItems=2, maxItems=4),
        "entry": obj({
            "currency": TEXT, "fees_included": BOOL, "slippage_included": BOOL,
            "minimum_net_credit": NUMBER, "price_basis": enum("SHORT_BID_LONG_ASK"),
            "cost_model_id": {"type": "string", "minLength": 1},
            "cost_config_hash": {"type": "string", "minLength": 1},
            "cost_breakdown": obj(fields(
                "entry_fees slippage_reserve legging_reserve settlement_reserve",
                {"type": "number", "minimum": 0},
            )),
        }),
        "economics": obj({
            **fields("absolute_ev_status relative_value_status", TEXT),
            **fields("ev_after_cost net_r", N_NUMBER),
        }),
        "risk": obj({
            "currency": TEXT, "max_loss_per_unit": NUMBER,
            "breakevens": array(NUMBER), "cvar_95": N_NUMBER,
            "path_risk_status": TEXT,
            "max_loss_basis": {"type": "string", "const": "PAYOFF_BOUND_PLUS_FROZEN_COST_BUDGET"},
            "delivery_fee_upper_bound_verified": FALSE,
        }),
        "history": obj({
            "status": enum("INSUFFICIENT", "EXPLORATORY", "VALIDATED", "FAILED"),
            "artifact_id": N_TEXT, "exit_basis": N_TEXT,
            **fields("independent_cohorts observation_count", COUNT),
            **fields("mean_net_r win_rate", N_NUMBER),
            "scope": nullable(scope),
        }),
        "forecast": obj({
            "status": enum("UNAVAILABLE", "SCREENING_ONLY", "CALIBRATED", "RETIRED"),
            "artifact_id": N_TEXT, "confidence": N_TEXT,
            "scope": nullable(scope),
            **fields("win_rate_low win_rate_high", N_NUMBER),
        }),
    })
    return obj({
        "schema_version": enum("strategy_brief.v1"),
        "brief_id": TEXT, "analysis_run_id": TEXT, "generated_at": TIME,
        "research_only": TRUE, "execution_allowed": FALSE, "action": action,
        "market": obj({
            "underlying": TEXT, "as_of": TIME, "expires_at": TIME,
            "summary_zh": TEXT, "action": action,
            "direction": enum("BEARISH", "BULLISH", "RANGE", "UNCLEAR"),
            "volatility": enum("CHEAP", "FAIR", "RICH", "UNKNOWN"),
            "liquidity": enum("EXECUTABLE", "LIMITED", "UNAVAILABLE"),
            "confidence": enum("HIGH", "MEDIUM", "LOW", "UNAVAILABLE"),
        }),
        "strategies": array(strategy),
        "no_trade": obj({
            "active": BOOL, "headline_zh": N_TEXT, "summary_zh": N_TEXT,
            "next_update_at": N_TIME, "primary_reason_codes": STRINGS,
        }),
        "evidence_summary": obj({
            **fields("candidate_count hard_gate_pass_count selected_count recommended_count watch_count", COUNT),
            "as_of": TIME, "valid_until": TIME, "summary_zh": TEXT,
            "default_structure_family": N_TEXT, "primary_reason_codes": STRINGS,
            "rejection_counts": {"type": "object", "additionalProperties": COUNT},
            "surface": obj(fields("freshness_status presented_as source_kind source_label", TEXT)),
            "items": array(obj({
                **fields("label status summary_zh detail_zh", TEXT), "artifact_id": N_TEXT,
            })),
        }),
    })


def report_schemas() -> dict[str, Schema]:
    quality = obj({"fit_quality_score": N_NUMBER, "no_arb_pass": N_BOOL})
    common_candidate = {
        **fields("candidate_id decision structure_type premium_currency", N_TEXT),
        "expiry_date": N_DATE, "dte_days": N_NUMBER, "underlying_price": N_NUMBER,
        "surface_quality": nullable(quality),
    }
    credit = obj({
        **common_candidate,
        **fields("sell_leg_instrument_name buy_leg_instrument_name", N_TEXT),
        **fields("sell_leg_strike_price buy_leg_strike_price model_delta net_credit spread_width", N_NUMBER),
    })
    condor = obj({
        **common_candidate,
        **fields("put_spread_id call_spread_id", N_TEXT),
        **fields("put_short_strike_price put_long_strike_price call_short_strike_price call_long_strike_price net_credit spread_width", N_NUMBER),
    })
    naked = obj({**common_candidate, "instrument_name": N_TEXT, **fields("model_delta market_mid", N_NUMBER)})

    def bucket(candidate: Schema) -> Schema:
        return nullable(obj(fields("eligible review rejected", array(candidate))))

    expiry = obj({
        "expiry_date": N_DATE,
        **fields("dte_days atm_fitted_iv_percent fit_quality_score", N_NUMBER),
        **fields("no_arbitrage_pass candidate_eligible", N_BOOL),
    })
    scanner_summary = obj({
        **fields("candidates_scanned review_candidates rejected_candidates kill_condition_candidates", COUNT),
        **fields("top_candidate_id top_candidate_action", N_TEXT),
    })
    scanner_row = obj({
        **fields("candidate_id structure_type action dominated_by", N_TEXT),
        "expiry_date": N_DATE,
        **fields("dte_days ranking_score ev_after_cost_usdc executable_credit_usdc", N_NUMBER),
        "path_risk": nullable(obj({
            **fields("status reason_code sample_size_basis", N_TEXT),
            **fields("p_touch p_itm cvar_95_usdc", N_NUMBER),
            "authoritative_sample_size": N_COUNT,
            "field_evidence": ref("FieldEvidenceMap"),
        }, optional=("field_evidence",))),
        "kill_conditions": STRINGS, "losing_axes": STRINGS,
        "field_evidence": ref("FieldEvidenceMap"),
    }, optional=("field_evidence",))
    playbook = obj({
        "structure": N_TEXT,
        "candidate": obj({
            **fields("candidate_id sell_leg buy_leg", N_TEXT), "expiry_date": N_DATE,
            **fields("dte_days sell_strike_usd buy_strike_usd model_delta risk_neutral_p_itm surface_fit_quality", N_NUMBER),
        }),
        "economics": obj({
            **fields("premium_currency assumption", N_TEXT),
            **fields("credit_coin credit_usd_shadow spread_width_usd reference_max_loss_usd_shadow estimated_total_fees_usd_shadow breakeven_usd_shadow sell_strike_distance_usd sell_strike_distance_percent sell_strike_expected_move_multiple credit_to_max_loss_ratio", N_NUMBER),
        }),
        "entry_contract": obj({
            **fields("status price_basis execution_assumption", N_TEXT),
            "revalidate_on_refresh": N_BOOL,
            "conditions": array(obj({
                **fields("id label requirement status reason", N_TEXT),
                "observed": {"anyOf": [
                    {"type": ["string", "number", "boolean", "null"]},
                    obj({"buy": N_NUMBER, "sell": N_NUMBER}),
                    obj({"spread_permission": N_BOOL, "status": N_TEXT}),
                ]},
                "blocking": N_BOOL,
            })),
        }),
        # A public edition intentionally clears position-dependent exit advice.
        "exit_contract": obj({
            "policy_status": N_TEXT,
            **fields("profit_capture position_states kill_switches", array(TEXT, maxItems=0)),
            "time_management": obj({
                "review_below_dte_days": NULL,
                "roll_allowed_states": array(TEXT, maxItems=0),
                "roll_delta_band": array(NUMBER, maxItems=0),
                "roll_must_improve": array(TEXT, maxItems=0),
                "defensive_roll_minimum_stress_reduction": NULL,
                "loss_deferral_alone_is_forbidden": NULL,
            }),
        }),
    })
    return {
        "StrategyBrief": strategy_brief_schema(),
        "ScannerSummary": scanner_summary,
        "ScannerCandidate": scanner_row,
        "ResearchReport": obj({
            "schema_version": enum("research_report.v1"), "generated_at": TIME,
            "action": enum("RESEARCH_ONLY", "RESEARCH_ONLY_NO_TRADE", "NO_TRADE"),
            "mode": enum("research_only", "paper", "manual_execution"),
            "effective_mode": enum("research_only"),
            "risk_state": enum("GREEN", "YELLOW", "RED", "HALT"),
            "reason_codes": STRINGS, "blocked_outputs": STRINGS,
            "event_status": obj({
                **fields("source source_status scope", N_TEXT),
                "macro_calendar_covered": FALSE, "event_score": N_NUMBER,
                "exchange_lock_state": enum("unknown", "normal", "partial", "full"),
                "reason_code": TEXT,
            }),
            "runtime_context": obj({
                **fields("profile mode snapshot_fixture notice", N_TEXT),
                "evaluation_clock": N_TIME, **fields("replay live_fetch_allowed", N_BOOL),
            }),
            "publish_edition": obj({
                **fields("captured_at published_at next_expected_at stale_after", N_TIME), "cadence": N_TEXT,
            }),
            "vrp_status": obj({
                **fields("schema_version status band evidence_class reason_code", N_TEXT),
                **fields("current_vrp_percent_points current_dvol_percent current_rv30_percent percentile", N_NUMBER),
                **fields("sample_count minimum_series_sample_count window_days", N_COUNT),
                "series": array(obj({
                    "observed_at": N_TIME,
                    **fields("vrp_percent_points dvol_percent rv30_percent percentile", N_NUMBER),
                    **fields("band evidence_class", N_TEXT),
                })),
                "missing_dates": array(DATE),
            }),
            "data_trust": obj({
                "verdict": N_TEXT, "source_class": enum("published_snapshot"), "reason_codes": STRINGS,
            }),
            "data_status": obj({
                **fields("status reason_code", N_TEXT), "source": enum("deribit_published_snapshot"),
                "validated": N_BOOL, "market_data_age_sec": N_NUMBER,
                "collection_scope": obj({
                    **fields("selected_instrument_count upstream_instrument_count", N_COUNT),
                    "coverage_ratio": N_NUMBER, "scope": N_TEXT,
                }),
                "quality_gate": obj({
                    "passed": N_BOOL, **fields("reason_codes advisory_reason_codes", STRINGS),
                    "summary": obj({
                        **fields("expiries_evaluated fetch_errors invalid_quotes total_quotes valid_quotes", N_COUNT),
                        "market_data_age_sec": N_NUMBER,
                    }),
                    "thresholds": obj({"market_data_max_age_sec": N_NUMBER}),
                }),
            }),
            **fields("calibration_status backtest_status", obj(fields("status model_version reason_code", N_TEXT))),
            "vol_surface_status": obj({
                **fields("status reason_code fit_model", N_TEXT), "validated": N_BOOL,
                "summary": obj(fields("eligible_expiries expiries_evaluated quality_passing_quotes", N_COUNT)),
                "expiries": array(obj({
                    **fields("candidate_eligible fit_quality_pass no_arb_pass", N_BOOL),
                    **fields("dte_days fit_quality_score no_arb_error", N_NUMBER),
                    "expiry_date": N_DATE, "quality_passing_quotes": N_COUNT,
                    "reason_codes": STRINGS,
                    "surface_points": array(obj({
                        "instrument_name": N_TEXT,
                        **fields("strike_price market_mark_iv surface_fitted_iv underlying_price", N_NUMBER),
                    })),
                })),
            }),
            "candidate_research": obj({
                **fields("status reason_code", N_TEXT),
                "summary": obj(fields("eligible_call_credit_spreads eligible_put_credit_spreads eligible_iron_condors eligible_expiries eligible_naked_short_calls expiries_considered rejected_call_credit_spreads rejected_put_credit_spreads rejected_iron_condors rejected_naked_short_calls review_call_credit_spreads review_put_credit_spreads review_iron_condors review_naked_short_calls", COUNT)),
                "naked_short_calls": bucket(naked),
                **fields("call_credit_spreads put_credit_spreads", bucket(credit)),
                "iron_condors": bucket(condor),
            }),
            "strategy_research": nullable(obj({
                **fields("schema_version status confidence_ceiling", N_TEXT),
                "generated_at": N_TIME, "advisory_only": TRUE, "execution_allowed": FALSE,
                "pipeline": array(obj(fields("stage status output", TEXT))),
                "decision": obj({
                    **fields("stance primary_structure entry_readiness summary", N_TEXT),
                    **fields("why_now why_not", STRINGS),
                    "rejected_structures": array(obj({
                        **fields("structure status", TEXT), "reason_codes": STRINGS,
                    })),
                }),
                "collection": obj({
                    "status": N_TEXT, "source": enum("deribit_published_snapshot"),
                    "captured_at": N_TIME, "market_data_age_sec": N_NUMBER,
                    "coverage": obj({
                        "scope": N_TEXT,
                        **fields("selected_instrument_count upstream_instrument_count", N_COUNT),
                        "coverage_ratio": N_NUMBER, "is_research_sample": N_BOOL,
                    }),
                    "quality": obj(fields("valid_quotes total_quotes invalid_quotes fetch_errors expiries_evaluated", N_COUNT)),
                    "feed_graph": obj({"complete": N_BOOL, "missing_required_feeds": STRINGS}),
                }),
                "analysis": obj({
                    "market": obj({
                        **fields("spot_usd dvol_percent near_term_atm_iv_percent dvol_minus_atm_iv_points funding_rate basis_rate event_score", N_NUMBER),
                        **fields("regime_label regime_status", N_TEXT),
                        "sell_permission": N_NUMBER,
                        **fields("spread_permission naked_permission", N_BOOL),
                    }),
                    "volatility": obj({
                        **fields("surface_status fit_model", N_TEXT),
                        **fields("term_slope_iv_points candidate_expiry_atm_iv_percent expected_move_usd expected_move_percent call_wing_richness_iv_points", N_NUMBER),
                        **fields("front_expiry next_expiry", expiry),
                    }),
                    "interpretation_limits": STRINGS,
                }),
                "strategy_selection": obj({
                    "selection_method": N_TEXT, "eligible_spread_count": N_COUNT,
                    **fields("ranked_candidate_ids ranking_dimensions", STRINGS),
                }),
                "playbook": nullable(playbook),
                "monitoring": array(obj({
                    **fields("metric trigger response cadence", TEXT),
                    "current": {"type": ["number", "boolean", "null"]},
                })),
                "review": obj({
                    **fields("status backtest_status calibration_status path_risk_status", N_TEXT),
                    **fields("missing_evidence promotion_conditions journal_template", STRINGS),
                }),
                "degradation": array(obj(fields("condition effect", TEXT))),
            })),
            "ev_candidate_scanner": nullable(obj({
                **fields("status score_status reason_code", N_TEXT),
                "summary": nullable(ref("ScannerSummary")),
                "ranking_basis": obj({"method": N_TEXT, "tie_break_order": STRINGS, "absolute_ev_available": N_BOOL}),
                "ranked_candidates": array(ref("ScannerCandidate")), "rejected_count": COUNT,
            })),
            "mode_gate": obj({
                **fields("trade_recommendation_allowed recommended_size_allowed order_instructions_allowed paper_manual_candidates_allowed", N_BOOL),
                "reason_codes": STRINGS,
            }),
            "full_system_surface": obj({
                **fields("schema_version status", N_TEXT), "generated_at": N_TIME,
                "release_readiness": obj({
                    "status": N_TEXT,
                    **fields("missing_prerequisites blocking_prerequisites", STRINGS),
                    "prerequisites": array(obj({
                        **fields("name evidence_state release_state evidence_class owner action root_cause", TEXT),
                        **fields("satisfied release_blocking", BOOL), "reason_codes": STRINGS,
                    })),
                }),
                "release_gates": array(ref("ReleaseGate")),
            }),
            "strategy_brief": ref("StrategyBrief"),
        }, optional=("strategy_brief",)),
    }


def public_schemas() -> dict[str, Schema]:
    """Construct a fresh copy of the versioned, value-independent contract."""
    public_times = fields("captured_at published_at", TIME)
    links = fields("disclaimer_url methodology_url", TEXT)
    common = {**public_times, **links}
    history = obj({
        "status": enum("available", "collecting"), "window_days": COUNT, "reason": N_TEXT,
        "history": array(obj({
            "date": DATE, "captured_at": N_TIME, "published_at": TIME,
            "status": enum("success", "failed"), "research_publication_status": enum("GO", "NO-GO"),
            **fields("capture_row_count quality_gate_blocked_count excluded_snapshot_count", COUNT),
            "reason_code": N_TEXT,
        })),
    })
    manifest_verification = obj({"status": TEXT, "artifact_count": COUNT, "errors": STRINGS})
    provenance = obj({"status": TEXT, "git_sha": N_TEXT, "verification_status": TEXT})
    field_evidence = {"type": "object", "additionalProperties": obj({"evidence_class": N_TEXT, "unit": N_TEXT})}
    schemas: dict[str, Schema] = {
        "FieldEvidenceMap": field_evidence,
        "ReleaseGate": obj({
            **fields("name status evidence_state evidence_class owner", TEXT),
            "satisfied": BOOL, "execution_allowed": FALSE, "reason_codes": STRINGS,
            "missing_prerequisites": STRINGS, "configurable": FALSE,
            "publication_evidence": obj(fields("data_quality publish_manifest methodology disclaimer", TEXT), optional=("data_quality", "publish_manifest", "methodology", "disclaimer")),
        }, optional=("missing_prerequisites", "configurable", "publication_evidence")),
        "Summary": obj({
            **common, "schema_version": enum("public_summary.v1"), "cadence": TEXT, "stale_after": TIME,
            "vrp": obj({
                **fields("vrp_percent_points dvol_percent rv30_percent percentile", N_NUMBER),
                **fields("band evidence_class", N_TEXT),
                **fields("evaluation_at dvol_observed_at underlying_observed_at", N_TIME),
                "field_evidence": field_evidence,
            }),
            "change": obj({
                "status": enum("available", "unavailable"),
                **fields("prior_observed_at current_observed_at", N_TIME),
                **fields("vrp_percent_points_delta dvol_percent_delta rv30_percent_delta percentile_delta", N_NUMBER),
                "band_changed": N_BOOL,
            }),
            "alert": obj(fields("level code message", TEXT)),
            "data_status": obj(fields("status evidence_class", N_TEXT)),
            "publication_history": history, "release_gates": array(ref("ReleaseGate")),
        }),
        "Thermo": obj({
            **common, "schema_version": enum("public_thermo.v1"),
            **fields("status band evidence_class", N_TEXT),
            **fields("current_vrp_percent_points current_dvol_percent current_rv30_percent percentile", N_NUMBER),
            **fields("sample_count minimum_series_sample_count window_days", N_COUNT),
            "missing_dates": array(DATE), "recent_series_path": TEXT, "year_shards": STRINGS,
            "series": array(obj({
                **fields("observed_at evaluation_at dvol_observed_at underlying_observed_at", N_TIME),
                **fields("vrp_percent_points dvol_percent rv30_percent percentile", N_NUMBER),
                "percentile_sample_count": N_COUNT, **fields("band evidence_class", N_TEXT),
            })),
        }),
        "Candidates": obj({
            **common, "schema_version": enum("public_candidates.v1"),
            **fields("status reason_code score_status", N_TEXT),
            "summary": nullable(ref("ScannerSummary")), "evidence_class": TEXT,
            "ranked_candidates": array(ref("ScannerCandidate")),
        }),
        "Signal": obj({
            **common, "schema_version": enum("public_signal.v1"), "evidence_class": TEXT,
            "artifact": ref("ResearchSignal"),
        }),
        "Health": obj({
            **public_times,
            "schema_version": enum("public_health.v1"),
            **fields("last_published_at next_expected_at stale_after", TIME),
            **fields("cadence runtime_mode publish_manifest_status disclaimer_url status_url", TEXT),
            **fields("data_status research_publication_status execution_authorization_status", N_TEXT),
            "is_stale_at_publish": BOOL, "manifest_verification": manifest_verification,
            "publication_history": history,
        }),
        "Manifest": obj({
            **public_times,
            "schema_version": enum("public_publication_manifest.v1"),
            **fields("analysis_run_id cadence engine_version", TEXT),
            "analysis_record_sha256": HASH,
            **fields("evaluation_clock next_expected_at stale_after", TIME),
            "git_sha": N_TEXT, "git_provenance": provenance,
            "web_build_source": obj(fields("root_name index_name assets_dir", TEXT)),
            "input_hashes": obj({
                **fields("snapshot underlying_history dvol_history signal_artifact series_artifact publication_history", HASH),
                **fields("strategy_history_artifacts strategy_forecast_runtime_evidence", array(HASH)),
                "site_origin": TEXT, "published_at": TIME, "git_sha": N_TEXT,
                "git_provenance": provenance, "engine_version": TEXT,
            }),
            "artifacts": array(obj({"path": TEXT, "sha256": HASH, "bytes": COUNT})),
            "manifest_verification": manifest_verification,
            "manifest_policy": obj({
                "canonical_json": TRUE, "self_hash_excluded_paths": STRINGS,
                "hash_algorithm": enum("sha256"), "history_alignment": TEXT,
            }),
        }),
    }
    thermo_properties = schemas["Thermo"]["properties"]
    schemas["ThermoRecent"] = obj({**thermo_properties, "series_window_days": COUNT})
    schemas["ThermoYear"] = obj({
        **thermo_properties, "series_window": enum("calendar_year"),
        "series_year": {"type": "string", "pattern": "^[0-9]{4}$"},
    })
    schemas.update(report_schemas())
    return schemas
