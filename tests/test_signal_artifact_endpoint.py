"""Serving the accumulating validation sample so it can be watched, not re-run.

The sample cannot be backfilled, so it accumulates for weeks before it can be
measured. Reading where it has got to should not require re-running a command
and reading raw JSON, and a console with nothing configured should say so rather
than return a 404 the reader has to interpret.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_options_report.api import (
    SIGNAL_PATH,
    RuntimeConfig,
    _payload_for_path,
)


class SignalArtifactEndpointTests(unittest.TestCase):
    def test_an_unconfigured_console_explains_itself(self) -> None:
        payload = _payload_for_path(SIGNAL_PATH, "", runtime=RuntimeConfig())

        self.assertEqual(payload["status"], "not_configured")
        self.assertEqual(
            payload["reason_code"], "SIGNAL_ARTIFACT_NOT_CONFIGURED"
        )
        self.assertIn("--signal-artifact", payload["detail"])

    def test_a_configured_artifact_is_served_verbatim(self) -> None:
        artifact = {
            "schema_version": "signal_validation_report.v1",
            "status": "projected",
            "cohorts": [{"expiry_date": "2026-08-07"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")

            payload = _payload_for_path(
                SIGNAL_PATH,
                "",
                runtime=RuntimeConfig(signal_artifact=str(path)),
            )

        self.assertEqual(payload, artifact)

    def test_a_missing_artifact_is_rejected_at_startup(self) -> None:
        with self.assertRaises(ValueError) as caught:
            RuntimeConfig(signal_artifact="does-not-exist.json").validate(
                check_inputs=False
            )

        self.assertIn("signal_artifact not found", str(caught.exception))

    def test_an_unreadable_artifact_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{not json", encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                _payload_for_path(
                    SIGNAL_PATH,
                    "",
                    runtime=RuntimeConfig(signal_artifact=str(path)),
                )

        self.assertIn("signal artifact could not be read", str(caught.exception))

    def test_the_endpoint_carries_no_trading_surface(self) -> None:
        payload = _payload_for_path(SIGNAL_PATH, "", runtime=RuntimeConfig())

        rendered = repr(payload)
        for forbidden in ("recommended_size", "order_instruction", "execution_allowed"):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
