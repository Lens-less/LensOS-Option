"""Publish a fixed historical fixture for local public-browser acceptance.

Run this script with the installed wheel's Python and ``-I``. It uses only the
standard library and that package, never imports tests or fetches market data.
The generated site tests publication/UI behavior, not current market evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any

from crypto_options_report.publication import publish_site


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _history_fixtures(captured_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reuse the deterministic daily-price formulas in test_publication.py.

    These synthetic observations only exercise the real publication contract;
    their explicit fixture sources must not be interpreted as measured prices.
    """
    days = 1300
    capture = datetime.fromisoformat(captured_at.replace("Z", "+00:00")).astimezone(UTC)
    first = capture.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    underlying_rows = []
    dvol_rows = []
    for index in range(days):
        observed = first + timedelta(days=index)
        clock = {"timestamp_ms": int(observed.timestamp() * 1000), "observed_at": _timestamp(observed)}
        underlying_rows.append({
            **clock,
            "close": round(28000.0 + index * 21.5 + ((index % 31) - 15) * 37.0 + ((index % 7) - 3) * 11.0, 6),
        })
        dvol_rows.append({**clock, "close": round(42.0 + (index % 19) * 0.45, 6)})
    common = {
        "captured_at": captured_at,
        "currency": "BTC",
        "resolution": "1D",
        "resolution_seconds": 86400,
        "observation_count": days,
        "first_observed_at": underlying_rows[0]["observed_at"],
        "last_observed_at": underlying_rows[-1]["observed_at"],
    }
    underlying = {
        **common,
        "schema_version": "underlying_price_history.v1",
        "source": "fixture:public-browser-underlying-history",
        "instrument_name": "BTC-PERPETUAL",
        "requested_days": days,
        "observations": underlying_rows,
    }
    dvol = {
        **common,
        "schema_version": "dvol_history.v1",
        "source": "fixture:public-browser-dvol-history",
        "source_endpoint": "fixture",
        "index_name": "BTC DVOL",
        "requested_days": 1200,
        "value_unit": "percent_points",
        "coverage": {
            "expected_day_count": days,
            "observed_day_count": days,
            "missing_day_count": 0,
            "coverage_ratio": 1.0,
            "missing_days": [],
        },
        "observations": dvol_rows,
    }
    return underlying, dvol


def prepare_case(*, public_build_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Generate a genuine publication without changing any evidence verdict."""
    resources = files("crypto_options_report").joinpath("resources")
    snapshot = json.loads(resources.joinpath("demo-snapshot.json").read_text(encoding="utf-8"))
    captured_at = snapshot["captured_at"]
    capture = datetime.fromisoformat(captured_at.replace("Z", "+00:00")).astimezone(UTC)
    published_at = _timestamp(capture + timedelta(seconds=30))
    underlying, dvol = _history_fixtures(captured_at)
    output = output_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="option-public-browser-inputs-") as directory:
        inputs = Path(directory)

        def write_input(name: str, value: Any) -> str:
            destination = inputs / name
            destination.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
            return str(destination)

        result = publish_site(
            snapshot=write_input("snapshot.json", snapshot),
            underlying_history=write_input("underlying.json", underlying),
            dvol_history=write_input("dvol.json", dvol),
            signal_artifact=write_input("signal.json", json.loads(
                resources.joinpath("demo-signal-preflight.json").read_text(encoding="utf-8"),
            )),
            series_artifact=write_input("series.json", json.loads(
                resources.joinpath("demo-series-history.json").read_text(encoding="utf-8"),
            )),
            publication_history=write_input("publication-history.json", {
                "schema_version": "publication_history.v1",
                "generated_at": published_at,
                "entries": [],
            }),
            out=str(output),
            published_at=published_at,
            # The same canonical-metadata fixture as test_publication.py.
            # No request, deployment, or ownership claim is made for this host.
            site_origin="https://research.lensos.dev",
            web_build=str(public_build_dir.resolve()),
        )
    health = json.loads((output / "api/v1/health.json").read_text(encoding="utf-8"))
    report = json.loads((output / "research/report").read_text(encoding="utf-8"))
    if report["strategy_brief"]["execution_allowed"] is not False:
        raise ValueError("Public browser fixture must keep execution disabled")
    return {
        "schema_version": "public_browser_case.v1",
        "scope": "fixed_fixture_publication_and_browser_acceptance_only",
        "output_dir": str(output),
        "inputs": {
            "snapshot": "packaged:demo-snapshot.json",
            "snapshot_source": snapshot["source"],
            "signal": "packaged:demo-signal-preflight.json",
            "series": "packaged:demo-series-history.json",
            "underlying_history": underlying["source"],
            "dvol_history": dvol["source"],
            "publication_receipts": "empty",
        },
        "captured_at": captured_at,
        "published_at": published_at,
        "stale_after": health["stale_after"],
        "is_stale_at_publish": health["is_stale_at_publish"],
        "execution_allowed": report["strategy_brief"]["execution_allowed"],
        "publication": result,
        "interpretation": (
            "Historical packaged snapshot and synthetic fixture histories; no live fetch, "
            "account evidence, measured performance, or execution authorization. "
            "Publication GO describes structural publication gates only. "
            "The original capture/publication clocks are historical; current-wall-clock "
            "and explicitly declared historical-clock browser checks test rendering and recovery only."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-build-dir", type=Path, required=True, help="actual npm run build:public output")
    parser.add_argument("--output-dir", type=Path, required=True, help="new or empty local static-site directory")
    args = parser.parse_args(argv)
    try:
        result = prepare_case(public_build_dir=args.public_build_dir, output_dir=args.output_dir)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"Public browser case preparation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
