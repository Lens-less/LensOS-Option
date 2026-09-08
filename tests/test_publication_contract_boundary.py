"""Publication rejects invalid public artifacts before making an output tree."""

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from crypto_options_report.market_data import load_snapshot_fixture
from crypto_options_report.public_api_contract import validate_public_projection
from crypto_options_report.signal_validation import build_signal_validation_report
from tests import test_publication as fixtures
from tests import test_signal_validation as signal_fixtures


def _measured_signal_at_publication_clock() -> dict:
    cutoff = load_snapshot_fixture(fixtures.SNAPSHOT_FIXTURE)["captured_at"]
    snapshots, history = signal_fixtures._build_series(richness_reaches_quote=True)
    snapshots = [item for item in snapshots if item["captured_at"] <= cutoff]
    history["observations"] = [
        item for item in history["observations"] if item["observed_at"] <= cutoff
    ]
    history["observation_count"] = len(history["observations"])
    history["last_observed_at"] = history["observations"][-1]["observed_at"]
    return build_signal_validation_report(
        snapshots=snapshots, underlying_history=history, generated_at=cutoff,
    )


class PublicationContractBoundaryTests(unittest.TestCase):
    def test_invalid_timezone_offset_is_rejected_before_publication(self) -> None:
        captured_at = load_snapshot_fixture(fixtures.SNAPSHOT_FIXTURE)["captured_at"]
        source = fixtures._build_signal_artifact(captured_at)
        # Python normalizes +00:60 to +01:00. The represented instant is within
        # the publication window, but the source text is not an RFC3339 clock.
        clock = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        invalid_clock = (clock + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:60")
        source["captured_at"] = invalid_clock
        source["generated_at"] = invalid_clock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "valid date-time"):
                fixtures.PublicationTests()._publish(root, signal_payload=source)
            self.assertFalse(any(path.is_file() for path in (root / "site").rglob("*")))

    def test_measured_signal_publishes_explanatory_limits_and_collinearity(self) -> None:
        source = _measured_signal_at_publication_clock()
        self.assertEqual("measured", source["status"])
        with tempfile.TemporaryDirectory() as tmp:
            output, result = fixtures.PublicationTests()._publish(
                Path(tmp), signal_payload=source,
            )
            projected = json.loads((output / "research/signal").read_text(encoding="utf-8"))
            wrapper = json.loads((output / "api/v1/signal.json").read_text(encoding="utf-8"))
            validate_public_projection("ResearchSignal", projected)
            validate_public_projection("Signal", wrapper)
            self.assertEqual(source["cannot_tell"], projected["cannot_tell"])
            self.assertEqual(source["collinearity"]["method"], projected["collinearity"]["method"])
            for field, expected in source["collinearity"]["pairs"][0].items():
                self.assertEqual(expected, projected["collinearity"]["pairs"][0][field])
            self.assertIn("field_evidence", projected["collinearity"]["pairs"][0])
            self.assertTrue(projected["research_only"])
            self.assertEqual("NO-GO", result["execution_authorization_status"])

    def test_measured_signal_rejects_unapproved_explanation_fields_before_output(self) -> None:
        measured = _measured_signal_at_publication_clock()
        for path, value in (
            (("cannot_tell",), "not-an-array"),
            (("collinearity", "private_notes"), "unapproved"),
            (("collinearity", "pairs", 0, "private_notes"), "unapproved"),
            (("collinearity", "equivalence_threshold"), "0.99"),
        ):
            with self.subTest(path=path):
                source = deepcopy(measured)
                row = source
                for key in path[:-1]:
                    row = row[key]
                row[path[-1]] = value
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with self.assertRaisesRegex(ValueError, path[-1]):
                        fixtures.PublicationTests()._publish(root, signal_payload=source)
                    self.assertFalse(any(path.is_file() for path in (root / "site").rglob("*")))

    def test_malformed_artifacts_leave_no_public_json_or_bundle_behind(self) -> None:
        captured_at = load_snapshot_fixture(fixtures.SNAPSHOT_FIXTURE)["captured_at"]
        for artifact, field, value in (
            ("signal", "signals_measured", "invalid-count"),
            ("signal", "signals_measured", True),
            ("series", "model_delta", [0.08]),
        ):
            with self.subTest(artifact=artifact, value=value):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    signal = fixtures._build_signal_artifact(captured_at)
                    series = fixtures._build_series_artifact(captured_at)
                    if artifact == "signal":
                        signal["summary"][field] = value
                    else:
                        series["points"][0][field] = value

                    with self.assertRaisesRegex(ValueError, field):
                        fixtures.PublicationTests()._publish(
                            root,
                            signal_payload=signal,
                            series_payload=series,
                        )

                    public_files = [
                        str(path.relative_to(root / "site"))
                        for path in (root / "site").rglob("*")
                        if path.is_file()
                    ]
                    self.assertEqual([], public_files)

    def test_completed_publication_and_archive_obey_fixed_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output, result = fixtures.PublicationTests()._publish(Path(tmp))
            components = {
                "research/report": "ResearchReport",
                "research/signal": "ResearchSignal",
                "research/series": "ResearchSeries",
                "api/v1/summary.json": "Summary",
                "api/v1/thermo.json": "Thermo",
                "api/v1/thermo/recent.json": "ThermoRecent",
                "api/v1/candidates.json": "Candidates",
                "api/v1/signal.json": "Signal",
                "api/v1/health.json": "Health",
                "api/v1/manifest.json": "Manifest",
                ".well-known/publish-manifest.json": "Manifest",
            }
            archive = output / "editions" / result["published_at"][:10]
            for edition in (output, archive):
                for relative, component in components.items():
                    with self.subTest(edition=edition.name, component=component):
                        validate_public_projection(
                            component,
                            json.loads((edition / relative).read_text(encoding="utf-8")),
                        )
                for shard in (edition / "api/v1/thermo/by-year").glob("*.json"):
                    validate_public_projection(
                        "ThermoYear", json.loads(shard.read_text(encoding="utf-8")),
                    )
            self.assertEqual("GO", result["research_publication_status"])
            self.assertEqual("NO-GO", result["execution_authorization_status"])
