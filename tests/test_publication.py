import hashlib
import json
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
from crypto_options_report.publication import publish_site

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_FIXTURE = ROOT / "tests" / "fixtures" / "deribit_btc_option_chain_snapshot.json"
PUBLIC_REPLAY_FIXTURE = ROOT / "tests" / "fixtures" / "public_deribit_replay.json"
PUBLIC_TITLE = "\u0042\u0054\u0043\u0020\u671f\u6743\u5356\u65b9\u6ea2\u4ef7\u6301\u7eed\u89c2\u5bdf\u53f0"


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
        "status": "validated",
        "headline": "Published public research signal artifact",
        "cohorts": [
            {
                "name": "smile_residual_z",
                "registered_at": "2026-07-27T00:00:00Z",
                "status": "collecting",
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


class PublicationTests(unittest.TestCase):
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
        published_at: str | None = None,
        out_name: str = "site",
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
            _build_series_artifact(snapshot["captured_at"]),
        )
        published_value = published_at or snapshot["captured_at"]
        output_dir = tempdir / out_name
        result = publish_site(
            snapshot=str(snapshot_path),
            underlying_history=str(underlying_path),
            dvol_history=str(dvol_path),
            signal_artifact=str(signal_path),
            series_artifact=str(series_path),
            out=str(output_dir),
            published_at=published_value,
            git_sha="abc123def456",
        )
        return output_dir, result

    def test_publish_is_deterministic_and_rewrites_bundle_paths(self) -> None:
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            published_at = _timestamp(
                _parse_timestamp(snapshot["captured_at"]) + timedelta(hours=25)
            )
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

            asset_paths = {
                f"assets/{path.name}"
                for path in (ROOT / "crypto_options_report" / "static" / "evidence" / "assets").iterdir()
                if path.is_file()
            }
            expected_paths = {
                ".well-known/publish-manifest.json",
                "_headers",
                "api/v1/candidates.json",
                "api/v1/health.json",
                "api/v1/manifest.json",
                "api/v1/signal.json",
                "api/v1/summary.json",
                "api/v1/thermo.json",
                "disclaimer.html",
                "index.html",
                "methodology.html",
                "privacy.html",
                "research/report",
                "research/series",
                "research/signal",
                "status.html",
                "terms.html",
            }
            expected_paths.update(asset_paths)

            self.assertTrue(expected_paths.issubset(set(_tree_listing(first_dir))))
            self.assertEqual(_tree_listing(first_dir), _tree_listing(second_dir))
            self.assertEqual(_tree_hashes(first_dir), _tree_hashes(second_dir))

            index_html = (first_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn(f"<title>{PUBLIC_TITLE}</title>", index_html)
            self.assertIn(
                f'<meta property="og:title" content="{PUBLIC_TITLE}">',
                index_html,
            )
            self.assertIn('src="/assets/', index_html)
            self.assertIn('href="/assets/', index_html)
            self.assertNotIn("/evidence/assets/", index_html)
            headers = (first_dir / "_headers").read_text(encoding="utf-8")
            self.assertIn("/api/v1/*", headers)
            self.assertIn("Access-Control-Allow-Origin: *", headers)
            self.assertIn("Cache-Control: public, max-age=300", headers)

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

            with self.assertRaisesRegex(ValueError, "snapshot input not found"):
                publish_site(
                    snapshot=str(tempdir / "missing-snapshot.json"),
                    underlying_history=str(underlying_path),
                    dvol_history=str(dvol_path),
                    signal_artifact=str(signal_path),
                    series_artifact=str(series_path),
                    out=str(tempdir / "other-site"),
                    published_at="2026-08-01T09:00:14Z",
                )

            with self.assertRaisesRegex(ValueError, "output directory must not already contain files"):
                publish_site(
                    snapshot=str(SNAPSHOT_FIXTURE),
                    underlying_history=str(underlying_path),
                    dvol_history=str(dvol_path),
                    signal_artifact=str(signal_path),
                    series_artifact=str(series_path),
                    out=str(out_dir),
                    published_at="2026-08-01T09:00:14Z",
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
                    out=str(tempdir / "too-early"),
                    published_at=_timestamp(
                        _parse_timestamp(snapshot["captured_at"]) - timedelta(seconds=1)
                    ),
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
                if relative == "_headers" or path.suffix in {".html", ".js", ".css"}:
                    continue
                with self.subTest(relative=relative):
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    self.assertFalse(_contains_forbidden_key(payload, forbidden))

    def test_publish_preflights_forwarded_artifact_privacy_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tempdir = Path(tmp)
            snapshot = load_snapshot_fixture(str(SNAPSHOT_FIXTURE))
            cases = {
                "private-field": {"account_status": {"status": "missing"}},
                "absolute-path": {
                    "diagnostic_path": r"C:\Users\operator\private\signal.json"
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
                "trimmed to the snapshot captured_at UTC date",
                manifest["manifest_policy"]["history_alignment"],
            )

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
                    "/.well-known/publish-manifest.json",
                    "/methodology.html",
                    "/disclaimer.html",
                    "/privacy.html",
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
