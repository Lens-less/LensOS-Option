import unittest
from datetime import UTC, datetime, timedelta

from crypto_options_report._canonical import canonical_sha256
from crypto_options_report.publication_history import build_publication_history


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _receipt(day: datetime, *, status: str = "success") -> dict[str, object]:
    published_at = _timestamp(day.replace(hour=9))
    return {
        "date": published_at[:10],
        "captured_at": _timestamp(day.replace(hour=8)),
        "published_at": published_at,
        "status": status,
        "research_publication_status": "GO" if status == "success" else "NO-GO",
        "capture_row_count": 96,
        "quality_gate_blocked_count": 0 if status == "success" else 1,
        "excluded_snapshot_count": 2,
        "manifest_sha256": "a" * 64 if status == "success" else None,
        "reason_code": None if status == "success" else "PUBLISH_FAILED",
        "monitoring_proof": _monitoring_proof(day),
    }


def _monitoring_proof(day: datetime) -> dict[str, object]:
    projection = {
        "attestation_schema_version": "lensos_stale_monitor_attestation.v1",
        "check_interval_seconds": 3600,
        "checked_at": _timestamp(day.replace(hour=8, minute=55)),
        "contract": "compare_current_time_to_stale_after",
        "failure_delivery_drill_at": _timestamp(day - timedelta(days=10)),
        "failure_webhook_sha256": "b" * 64,
        "health_url": "https://research.lensos.dev/api/v1/health.json",
        "monitor_id": "lens-public-staleness",
        "site_origin": "https://research.lensos.dev",
        "status": "healthy",
        "success_heartbeat_sha256": "c" * 64,
    }
    return {
        "schema_version": "monitoring_admission_evidence.v1",
        "projection": projection,
        "projection_sha256": canonical_sha256(projection),
    }


class PublicationHistoryTests(unittest.TestCase):
    def test_projects_latest_30_daily_receipts_in_chronological_order(self) -> None:
        start = datetime(2026, 7, 1, tzinfo=UTC)
        entries = [_receipt(start + timedelta(days=index)) for index in range(35)]
        payload = {
            "schema_version": "publication_history.v1",
            "generated_at": "2026-08-04T10:00:00Z",
            "entries": list(reversed(entries)),
        }

        result = build_publication_history(
            payload,
            published_at="2026-08-04T10:00:00Z",
        )

        self.assertEqual("available", result["status"])
        self.assertEqual(30, result["window_days"])
        self.assertEqual(30, len(result["history"]))
        self.assertEqual("2026-07-06", result["history"][0]["date"])
        self.assertEqual("2026-08-04", result["history"][-1]["date"])
        self.assertNotIn("manifest_sha256", result["history"][-1])
        self.assertNotIn("monitoring_proof", result["history"][-1])

    def test_empty_history_is_explicitly_collecting(self) -> None:
        result = build_publication_history(
            {
                "schema_version": "publication_history.v1",
                "generated_at": "2026-08-04T10:00:00Z",
                "entries": [],
            },
            published_at="2026-08-04T10:00:00Z",
        )

        self.assertEqual("collecting", result["status"])
        self.assertEqual([], result["history"])
        self.assertIn("No durable publication receipts", result["reason"])

    def test_rejects_unapproved_fields_duplicate_days_and_invalid_success(self) -> None:
        baseline = {
            "schema_version": "publication_history.v1",
            "generated_at": "2026-08-04T10:00:00Z",
            "entries": [_receipt(datetime(2026, 8, 3, tzinfo=UTC))],
        }

        for mutation, message in (
            ({**baseline, "operator_notes": "private"}, "unapproved root field"),
            (
                {
                    **baseline,
                    "entries": [{**baseline["entries"][0], "host": "DESKTOP"}],
                },
                "unapproved entry field",
            ),
            (
                {**baseline, "entries": baseline["entries"] * 2},
                "duplicate publication history date",
            ),
            (
                {
                    **baseline,
                    "entries": [
                        {**baseline["entries"][0], "manifest_sha256": None}
                    ],
                },
                "successful publication receipt requires manifest_sha256",
            ),
            (
                {**baseline, "generated_at": "2026-08-04T10:00:01Z"},
                "generated_at exceeds published_at",
            ),
            (
                {
                    **baseline,
                    "entries": [
                        {
                            **baseline["entries"][0],
                            "date": "2026-08-04",
                            "published_at": "2026-08-04T10:00:01Z",
                        }
                    ],
                },
                "receipt published_at exceeds publication",
            ),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError,
                message,
            ):
                build_publication_history(
                    mutation,
                    published_at="2026-08-04T10:00:00Z",
                )

    def test_monitoring_proof_is_exact_private_evidence_and_fails_under_mutation(self) -> None:
        baseline_entry = _receipt(datetime(2026, 8, 3, tzinfo=UTC))
        baseline = {
            "schema_version": "publication_history.v1",
            "generated_at": "2026-08-04T10:00:00Z",
            "entries": [baseline_entry],
        }
        proof = baseline_entry["monitoring_proof"]
        assert isinstance(proof, dict)
        projection = proof["projection"]
        assert isinstance(projection, dict)

        mutations = (
            ({**proof, "operator_notes": "private"}, "unapproved monitoring proof field"),
            ({**proof, "schema_version": "self_attested.v1"}, "schema_version"),
            ({**proof, "projection_sha256": "0" * 64}, "projection_sha256"),
            (
                {**proof, "projection": {**projection, "host": "DESKTOP"}},
                "unapproved monitoring projection field",
            ),
            (
                {
                    **proof,
                    "projection": {
                        key: value
                        for key, value in projection.items()
                        if key != "monitor_id"
                    },
                },
                "missing field monitor_id",
            ),
            (
                {
                    **proof,
                    "projection": {**projection, "check_interval_seconds": 3601},
                },
                "check_interval_seconds",
            ),
            (
                {**proof, "projection": {**projection, "status": "configured"}},
                "status",
            ),
            (
                {
                    **proof,
                    "projection": {
                        **projection,
                        "site_origin": "https://preview.alt",
                        "health_url": "https://preview.alt/api/v1/health.json",
                    },
                },
                "site_origin",
            ),
            (
                {
                    **proof,
                    "projection": {
                        **projection,
                        "checked_at": "2026-08-03T09:05:01Z",
                    },
                },
                "checked_at exceeds receipt published_at",
            ),
        )
        for mutated_proof, message in mutations:
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError,
                message,
            ):
                build_publication_history(
                    {
                        **baseline,
                        "entries": [
                            {**baseline_entry, "monitoring_proof": mutated_proof}
                        ],
                    },
                    published_at="2026-08-04T10:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
