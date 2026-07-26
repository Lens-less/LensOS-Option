"""A recorded snapshot has to be readable in a browser, and has to say it is one.

Three gates stacked to make the flagship surface unreachable on working data.
Development ignored `--snapshot-fixture` entirely — it was validated at startup
and then never passed to the report — so the console rendered "market source
not configured" against a chain the CLI scored 334 candidates from. The query
parameter that did reach the builder was sandboxed to `tests/fixtures`, so an
operator's own capture was rejected as escaping the allowed roots. And the one
profile that did read the configured fixture evaluated it against a live clock,
where anything older than `market_data_max_age_sec` fails the freshness gate.

The consequence was not a rough edge: the populated state of both surfaces had
never been seen, so it had never been designed.

Replay fixes the third gate by pinning the evaluation clock to the snapshot's
own capture time. That makes stale data read as current everywhere on the page,
which is why it is an operator flag rather than a query parameter, and why the
response states it.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from crypto_options_report.api import (
    RuntimeConfig,
    _replay_clock,
    _report_options_from_query,
    _runtime_context,
)
from crypto_options_report.market_data import load_snapshot_fixture

FIXTURE = Path(__file__).parent / "fixtures" / "deribit_btc_option_chain_snapshot.json"


def _runtime(**overrides) -> RuntimeConfig:
    base = {
        "profile": "development",
        "snapshot_fixture": str(FIXTURE),
    }
    base.update(overrides)
    return RuntimeConfig(**base)


class ConfiguredFixtureReachesTheReportTests(unittest.TestCase):
    def test_development_uses_the_operator_configured_snapshot(self) -> None:
        options = _report_options_from_query("", runtime=_runtime())

        self.assertEqual(options["snapshot_fixture"], str(FIXTURE))

    def test_a_query_parameter_still_overrides_the_configured_one(self) -> None:
        options = _report_options_from_query(
            "snapshot_fixture=tests/fixtures/deribit_btc_option_chain_snapshot.json",
            runtime=_runtime(),
        )

        self.assertEqual(
            options["snapshot_fixture"],
            "tests/fixtures/deribit_btc_option_chain_snapshot.json",
        )

    def test_the_sandbox_applies_to_the_browser_and_not_to_the_operator(self) -> None:
        """The sandbox stops a browser reading arbitrary files, nothing more.

        Applying it to the operator's own command-line choice is what rejected
        every capture living outside `tests/fixtures`.
        """
        configured = _report_options_from_query("", runtime=_runtime())
        self.assertIs(configured["sandbox_fixtures"], False)

        from_query = _report_options_from_query(
            "snapshot_fixture=tests/fixtures/deribit_btc_option_chain_snapshot.json",
            runtime=_runtime(),
        )
        self.assertIs(from_query["sandbox_fixtures"], True)


class ReplayClockTests(unittest.TestCase):
    def test_replay_pins_the_clock_to_the_snapshot_capture_time(self) -> None:
        expected = load_snapshot_fixture(str(FIXTURE))["captured_at"]

        options = _report_options_from_query("", runtime=_runtime(replay=True))

        self.assertEqual(options["generated_at"], expected)

    def test_the_clock_is_read_from_the_file_not_accepted_from_a_caller(self) -> None:
        """An operator cannot pin the clock to a moment the data is not from.

        Accepting an arbitrary instant would revive exactly the staleness the
        freshness gate exists to catch.
        """
        clock = _replay_clock(_runtime(replay=True))

        self.assertEqual(clock, load_snapshot_fixture(str(FIXTURE))["captured_at"])

    def test_live_mode_leaves_the_clock_alone(self) -> None:
        options = _report_options_from_query("", runtime=_runtime())

        self.assertIsNone(options["generated_at"])

    def test_replay_without_a_snapshot_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            RuntimeConfig(profile="development", replay=True).validate(
                check_inputs=False
            )

        self.assertIn("replay requires a snapshot", str(caught.exception))

    def test_replay_and_live_fetch_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            _runtime(replay=True, allow_live_fetch=True).validate(check_inputs=False)


class ReplayIsDeclaredTests(unittest.TestCase):
    """A pinned clock makes every freshness figure read as current.

    Nothing else in the payload can contradict that, so the surfaces are told
    rather than left to infer it.
    """

    def test_a_replayed_response_declares_itself_and_names_the_instant(self) -> None:
        context = _runtime_context(_runtime(replay=True).validate())

        self.assertIs(context["replay"], True)
        self.assertEqual(context["mode"], "replay")
        self.assertEqual(
            context["evaluation_clock"],
            load_snapshot_fixture(str(FIXTURE))["captured_at"],
        )
        self.assertIn("not now", context["notice"])
        self.assertEqual(context["snapshot_fixture"], str(FIXTURE))

    def test_a_live_response_declares_itself_live_and_pins_nothing(self) -> None:
        context = _runtime_context(_runtime().validate())

        self.assertIs(context["replay"], False)
        self.assertEqual(context["mode"], "live")
        self.assertIsNone(context["evaluation_clock"])
        self.assertIsNone(context["notice"])
        # The fixture path is withheld in live mode: it is only meaningful as
        # the provenance of a pinned clock.
        self.assertIsNone(context["snapshot_fixture"])

    def test_the_context_is_json_serializable_for_the_wire(self) -> None:
        context = _runtime_context(_runtime(replay=True).validate())

        self.assertEqual(
            json.loads(json.dumps(context, allow_nan=False))["mode"], "replay"
        )


class ProductionIsUnchangedTests(unittest.TestCase):
    """Replay must not become a way to loosen the production profile."""

    def test_production_still_rejects_browser_supplied_parameters(self) -> None:
        with self.assertRaises(ValueError):
            _report_options_from_query(
                "snapshot_fixture=whatever.json",
                runtime=_runtime(profile="production"),
            )

    def test_production_without_replay_keeps_a_live_clock(self) -> None:
        options = _report_options_from_query(
            "", runtime=_runtime(profile="production")
        )

        self.assertIsNone(options["generated_at"])

    def test_production_live_fetch_remains_unsupported(self) -> None:
        with self.assertRaises(ValueError):
            _runtime(profile="production", allow_live_fetch=True).validate(
                check_inputs=False
            )


if __name__ == "__main__":
    unittest.main()
