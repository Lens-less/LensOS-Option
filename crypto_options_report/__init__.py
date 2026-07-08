"""Research-only report contract for the crypto options short-call system."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "FORBIDDEN_RESEARCH_ONLY_KEYS": (".contract", "FORBIDDEN_RESEARCH_ONLY_KEYS"),
    "REQUIRED_REPORT_KEYS": (".contract", "REQUIRED_REPORT_KEYS"),
    "generate_research_report": (".contract", "generate_research_report"),
    "report_shape": (".contract", "report_shape"),
    "validate_report_contract": (".contract", "validate_report_contract"),
    "build_fixed_baseline_backtest_report": (".backtest", "build_fixed_baseline_backtest_report"),
    "build_path_risk_distribution_report": (
        ".path_risk",
        "build_path_risk_distribution_report",
    ),
    "build_path_risk_report_from_fixture": (
        ".path_risk",
        "build_path_risk_report_from_fixture",
    ),
    "build_path_risk_report_from_historical_report": (
        ".path_risk",
        "build_path_risk_report_from_historical_report",
    ),
    "build_pnl_evidence_report": (".pnl", "build_pnl_evidence_report"),
    "inverse_long_call_settlement_coin": (".pnl", "inverse_long_call_settlement_coin"),
    "build_regime_permission_state": (".regime", "build_regime_permission_state"),
    "build_vol_surface_and_candidate_research": (
        ".surface",
        "build_vol_surface_and_candidate_research",
    ),
    "build_market_data_status": (".market_data", "build_market_data_status"),
    "fetch_deribit_option_chain_snapshot": (".market_data", "fetch_deribit_option_chain_snapshot"),
    "load_public_replay_fixture": (".market_data", "load_public_replay_fixture"),
    "load_snapshot_fixture": (".market_data", "load_snapshot_fixture"),
    "normalize_market_snapshot": (".market_data", "normalize_market_snapshot"),
    "load_private_replay_fixture": (".account_risk", "load_private_replay_fixture"),
}

_OPTIONAL_EXPORTS = {
    "build_market_data_status",
    "fetch_deribit_option_chain_snapshot",
    "load_public_replay_fixture",
    "load_snapshot_fixture",
    "normalize_market_snapshot",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    try:
        module = import_module(module_name, __name__)
    except ImportError:
        if name in _OPTIONAL_EXPORTS:
            value = None
            globals()[name] = value
            return value
        raise

    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
