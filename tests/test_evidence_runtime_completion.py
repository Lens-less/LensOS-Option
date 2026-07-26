import hashlib
import http.client
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_options_report.api import (
    ResearchHTTPServer,
    ResearchReportHandler,
    RuntimeConfig,
    build_api_report,
)
from crypto_options_report.contract import _build_data_trust_summary
from crypto_options_report.evidence_store import (
    BACKTEST_JOB_SCHEMA_VERSION,
    BacktestArtifactCorrupt,
    BacktestIdempotencyConflict,
    BacktestJobService,
    BacktestJobStoreCorrupt,
    BacktestJobSubmissionFailed,
    BacktestQueueFull,
    load_backtest_evidence,
    promote_backtest_evidence_default,
    run_backtest_evidence_job,
)
from crypto_options_report.paper_ledger import (
    CONFIGURED_MANUAL_APPROVAL_RUNBOOK_PUBLIC_ID,
    DEFAULT_MANUAL_APPROVAL_RUNBOOK_PUBLIC_ID,
    build_paper_proposal_ledger,
)


class EvidenceRuntimeCompletionTests(unittest.TestCase):
    def test_live_data_trust_collects_before_promotion_and_then_becomes_trusted(self):
        collecting = self._live_data_status(
            {
                "status": "collecting",
                "consecutive_passes": 1,
                "minimum_consecutive_passes": 3,
                "observation_seconds": 0,
                "minimum_observation_seconds": 30,
                "feed_graph_complete": True,
            }
        )
        promoted = self._live_data_status(
            {
                "status": "promoted",
                "consecutive_passes": 3,
                "minimum_consecutive_passes": 3,
                "observation_seconds": 35,
                "minimum_observation_seconds": 30,
                "feed_graph_complete": True,
            }
        )

        self.assertEqual("degraded", _build_data_trust_summary(collecting)["verdict"])
        self.assertIn(
            "DATA_TRUST_OBSERVATION_COLLECTING",
            _build_data_trust_summary(collecting)["reason_codes"],
        )
        self.assertEqual(
            {
                "verdict": "trusted",
                "reason_codes": [],
                "source_class": "live",
            },
            _build_data_trust_summary(promoted),
        )

    def test_fixture_never_promotes_even_if_claimed_promoted(self):
        status = self._live_data_status(
            {
                "status": "promoted",
                "consecutive_passes": 99,
                "minimum_consecutive_passes": 3,
                "observation_seconds": 999,
                "minimum_observation_seconds": 30,
                "feed_graph_complete": True,
            }
        )
        status["source"] = "fixture:untrusted.json"

        trust = _build_data_trust_summary(status)

        self.assertEqual("untrusted", trust["verdict"])
        self.assertIn("DATA_TRUST_PROMOTION_PENDING", trust["reason_codes"])

    def test_live_evidence_reset_is_untrusted(self):
        status = self._live_data_status(
            {
                "status": "reset",
                "reason_codes": ["TRUST_EVIDENCE_CLAIM_INVALID"],
                "feed_graph_complete": True,
            }
        )

        trust = _build_data_trust_summary(status)

        self.assertEqual("untrusted", trust["verdict"])
        self.assertEqual(["TRUST_EVIDENCE_CLAIM_INVALID"], trust["reason_codes"])

    def test_backtest_job_is_content_addressed_and_projected_into_report(self):
        fixture = (
            Path(__file__).with_name("fixtures")
            / "historical_vendor"
            / "baseline_backtest_fixture.json"
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime = RuntimeConfig(
                historical_fixture=str(fixture),
                backtest_artifact_dir=tmp,
            )

            status, payload = self._request(
                "POST",
                "/backtest/run",
                runtime,
                body={
                    "schema_version": "backtest_run_request.v1",
                    "generated_at": "2026-07-07T00:01:30Z",
                },
                headers={"Idempotency-Key": "baseline-runtime-test"},
            )
            job_status, job = self._request("GET", payload["status_url"], runtime)
            lookup_status, lookup = self._request(
                "GET", "/backtest/report/default", runtime
            )
            id_status, by_id = self._request(
                "GET", f"/backtest/report/{lookup['report_id']}", runtime
            )
            report = build_api_report(backtest_artifact_dir=tmp)

            self.assertEqual(202, status)
            self.assertEqual("queued", payload["status"])
            self.assertRegex(payload["job_id"], r"^job-[0-9a-f]{64}$")
            self.assertEqual(200, job_status)
            self.assertEqual("succeeded", job["status"])
            self.assertEqual(200, lookup_status)
            self.assertEqual(job["report_id"], lookup["report_id"])
            self.assertEqual(200, id_status)
            self.assertEqual(lookup, by_id)
            self.assertEqual("completed", report["backtest_status"]["status"])
            self.assertEqual(lookup["report_id"], report["backtest_status"]["artifact_id"])

    def test_backtest_job_without_operator_fixture_is_actionable_conflict(self):
        status, payload = self._request(
            "POST",
            "/backtest/run",
            RuntimeConfig(),
            body={"schema_version": "backtest_run_request.v1"},
            headers={"Idempotency-Key": "missing-history"},
        )

        self.assertEqual(409, status)
        self.assertEqual("historical_data_not_configured", payload["status"])
        self.assertEqual("CONFIGURE_HISTORICAL_FIXTURE", payload["action"])

    def test_backtest_idempotency_reuses_job_and_rejects_changed_body(self):
        fixture = (
            Path(__file__).with_name("fixtures")
            / "historical_vendor"
            / "baseline_backtest_fixture.json"
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime = RuntimeConfig(
                historical_fixture=str(fixture),
                backtest_artifact_dir=tmp,
            )
            request = {
                "schema_version": "backtest_run_request.v1",
                "generated_at": "2026-07-07T00:01:30Z",
            }
            headers = {"Idempotency-Key": "repeatable-baseline"}

            first_status, first = self._request(
                "POST", "/backtest/run", runtime, body=request, headers=headers
            )
            replay_status, replay = self._request(
                "POST", "/backtest/run", runtime, body=request, headers=headers
            )
            conflict_status, conflict = self._request(
                "POST",
                "/backtest/run",
                runtime,
                body={**request, "generated_at": "2026-07-08T00:01:30Z"},
                headers=headers,
            )

            self.assertEqual(202, first_status)
            self.assertEqual(202, replay_status)
            self.assertEqual(first["job_id"], replay["job_id"])
            self.assertTrue(replay["replayed"])
            self.assertEqual(409, conflict_status)
            self.assertEqual(
                "IDEMPOTENCY_KEY_REUSE_CONFLICT",
                conflict["reason_code"],
            )

    def test_backtest_worker_admission_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            started = threading.Event()
            release = threading.Event()

            def blocking_job(**_kwargs):
                started.set()
                self.assertTrue(release.wait(timeout=5))
                return {"report_id": "bt-" + "0" * 64}

            with patch(
                "crypto_options_report.evidence_store.run_backtest_evidence_job",
                side_effect=blocking_job,
            ):
                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=Path(tmp) / "artifacts",
                    max_workers=1,
                    queue_capacity=0,
                    use_subprocess=False,
                )
                try:
                    service.submit(
                        idempotency_key="first",
                        request={"schema_version": "backtest_run_request.v1"},
                    )
                    self.assertTrue(started.wait(timeout=5))
                    with self.assertRaises(BacktestQueueFull):
                        service.submit(
                            idempotency_key="second",
                            request={"schema_version": "backtest_run_request.v1"},
                        )
                finally:
                    release.set()
                    service.close()

    def test_http_backtest_returns_202_while_worker_is_still_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            started = threading.Event()
            release = threading.Event()

            def blocking_job(**_kwargs):
                started.set()
                self.assertTrue(release.wait(timeout=5))
                return {"report_id": "bt-" + "1" * 64}

            with patch(
                "crypto_options_report.evidence_store.run_backtest_evidence_job",
                side_effect=blocking_job,
            ):
                server = ResearchHTTPServer(
                    ("127.0.0.1", 0),
                    ResearchReportHandler,
                    runtime=RuntimeConfig(
                        historical_fixture=str(fixture),
                        backtest_artifact_dir=str(Path(tmp) / "artifacts"),
                    ),
                )
                server.backtest_jobs.close()
                server.backtest_jobs = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=Path(tmp) / "artifacts",
                    max_workers=1,
                    queue_capacity=0,
                    use_subprocess=False,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=5
                )
                try:
                    connection.request(
                        "POST",
                        "/backtest/run",
                        body=json.dumps(
                            {"schema_version": "backtest_run_request.v1"}
                        ).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "Idempotency-Key": "prove-async-response",
                        },
                    )
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(started.wait(timeout=1))
                    self.assertFalse(release.is_set())
                    self.assertEqual(202, response.status)
                    self.assertEqual("queued", payload["status"])
                    connection.close()

                    overloaded = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=5
                    )
                    overloaded.request(
                        "POST",
                        "/backtest/run",
                        body=json.dumps(
                            {"schema_version": "backtest_run_request.v1"}
                        ).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "Idempotency-Key": "queue-must-reject",
                        },
                    )
                    overload_response = overloaded.getresponse()
                    overload_payload = json.loads(
                        overload_response.read().decode("utf-8")
                    )
                    self.assertEqual(503, overload_response.status)
                    self.assertEqual("1", overload_response.getheader("Retry-After"))
                    self.assertEqual("BACKTEST_QUEUE_FULL", overload_payload["reason_code"])
                    overloaded.close()
                finally:
                    release.set()
                    connection.close()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

    def test_backtest_uses_the_exact_bytes_it_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            original = b'{"name":"old","rows":[]}'
            replacement = '{"name":"new","rows":[]}'
            fixture.write_bytes(original)

            from crypto_options_report import evidence_store

            real_builder = evidence_store.build_fixed_baseline_backtest_report

            def replace_before_build(payload, **kwargs):
                fixture.write_text(replacement, encoding="utf-8")
                self.assertEqual("old", payload["name"])
                return real_builder(payload, **kwargs)

            with patch(
                "crypto_options_report.evidence_store.build_fixed_baseline_backtest_report",
                side_effect=replace_before_build,
            ):
                artifact = run_backtest_evidence_job(
                    fixture_path=fixture,
                    artifact_dir=Path(tmp) / "artifacts",
                    generated_at="2026-07-13T00:00:00Z",
                )

            self.assertEqual(
                hashlib.sha256(original).hexdigest(),
                artifact["source_fixture"]["sha256"],
            )
            self.assertEqual(
                "old",
                artifact["backtest_report"]["fixture_window"]["name"],
            )

    def test_executor_submission_failure_does_not_poison_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            service = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=Path(tmp) / "artifacts",
            )
            request = {"schema_version": "backtest_run_request.v1"}
            try:
                with patch.object(
                    service._executor,
                    "submit",
                    side_effect=RuntimeError("executor unavailable"),
                ), self.assertRaises(BacktestJobSubmissionFailed):
                    service.submit(
                        idempotency_key="submission-failure",
                        request=request,
                    )
                with self.assertRaises(BacktestIdempotencyConflict):
                    service.submit(
                        idempotency_key="submission-failure",
                        request={
                            "schema_version": "backtest_run_request.v1",
                            "generated_at": "2026-07-14T00:00:00Z",
                        },
                    )
                replay = service.submit(
                    idempotency_key="submission-failure",
                    request=request,
                )
            finally:
                service.close()

            self.assertFalse(replay["replayed"])
            self.assertEqual("queued", replay["status"])
            self.assertIsNone(replay["reason_code"])

    def test_idempotency_mapping_write_failure_preserves_request_hash_tombstone(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            service = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=Path(tmp) / "artifacts",
                use_subprocess=False,
            )
            request = {"schema_version": "backtest_run_request.v1"}
            from crypto_options_report import evidence_store

            real_atomic_write = evidence_store.atomic_write_json
            mapping_failure_injected = False

            def fail_first_mapping_write(path, value, **kwargs):
                nonlocal mapping_failure_injected
                if (
                    not mapping_failure_injected
                    and Path(path).name.startswith("idempotency-")
                ):
                    mapping_failure_injected = True
                    raise PermissionError("mapping sharing violation")
                return real_atomic_write(path, value, **kwargs)

            try:
                with patch(
                    "crypto_options_report.evidence_store.atomic_write_json",
                    side_effect=fail_first_mapping_write,
                ), self.assertRaises(BacktestJobSubmissionFailed):
                    service.submit(
                        idempotency_key="mapping-write-failure",
                        request=request,
                    )

                service.close()
                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=Path(tmp) / "artifacts",
                    use_subprocess=False,
                )
                with self.assertRaises(BacktestIdempotencyConflict):
                    service.submit(
                        idempotency_key="mapping-write-failure",
                        request={
                            "schema_version": "backtest_run_request.v1",
                            "generated_at": "2026-07-14T00:00:00Z",
                        },
                    )
                retry = service.submit(
                    idempotency_key="mapping-write-failure",
                    request=request,
                )
            finally:
                service.close()

            self.assertTrue(mapping_failure_injected)
            self.assertFalse(retry["replayed"])
            self.assertEqual("queued", retry["status"])

    def test_invalid_job_schema_is_not_ready_or_reflected_by_http(self):
        job_id = "job-" + "e" * 64
        complete_job = {
            "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "status": "queued",
            "submitted_at": "2026-07-14T00:00:00Z",
            "started_at": None,
            "completed_at": None,
            "request_sha256": "1" * 64,
            "fixture_sha256": "2" * 64,
            "idempotency_key_sha256": "3" * 64,
            "status_url": f"/backtest/jobs/{job_id}",
            "result_url": f"/backtest/jobs/{job_id}/result",
            "report_id": None,
            "report_url": None,
            "default_promotion_status": "not_started",
            "reason_code": None,
            "research_only": True,
        }
        invalid_records = {
            "underspecified": {
                "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "status": "succeeded",
            },
            "unknown-field": {
                **complete_job,
                "operator_secret": "must-not-be-reflected",
            },
        }

        for name, record in invalid_records.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                fixture = Path(tmp) / "history.json"
                fixture.write_text('{"rows": []}', encoding="utf-8")
                server = ResearchHTTPServer(
                    ("127.0.0.1", 0),
                    ResearchReportHandler,
                    runtime=RuntimeConfig(
                        historical_fixture=str(fixture),
                        backtest_artifact_dir=str(Path(tmp) / "artifacts"),
                    ),
                )
                (server.backtest_jobs.jobs_dir / f"{job_id}.json").write_text(
                    json.dumps(record),
                    encoding="utf-8",
                )
                store_ready = server.backtest_jobs.readiness_status()["store_ready"]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=5
                )
                try:
                    connection.request("GET", f"/backtest/jobs/{job_id}")
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                finally:
                    connection.close()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

                self.assertFalse(store_ready)
                self.assertEqual(503, response.status)
                self.assertEqual("backtest_job_store_unavailable", payload["error"])
                self.assertNotIn("must-not-be-reflected", json.dumps(payload))

    def test_orphan_idempotency_mapping_is_corruption_not_a_request_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            server = ResearchHTTPServer(
                ("127.0.0.1", 0),
                ResearchReportHandler,
                runtime=RuntimeConfig(
                    historical_fixture=str(fixture),
                    backtest_artifact_dir=str(Path(tmp) / "artifacts"),
                ),
            )
            request_body = b'{"schema_version":"backtest_run_request.v1"}'
            idempotency_key = "orphan-valid-mapping"
            key_sha256 = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()
            orphan_job_id = "job-" + "a" * 64
            mapping = {
                "schema_version": "backtest_idempotency_record.v1",
                "job_id": orphan_job_id,
                "request_sha256": hashlib.sha256(request_body).hexdigest(),
                "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            }
            (
                server.backtest_jobs.jobs_dir
                / f"idempotency-{key_sha256}.json"
            ).write_text(json.dumps(mapping), encoding="utf-8")
            store_ready = server.backtest_jobs.readiness_status()["store_ready"]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            try:
                connection.request(
                    "POST",
                    "/backtest/run",
                    body=request_body,
                    headers={
                        "Content-Type": "application/json",
                        "Idempotency-Key": idempotency_key,
                    },
                )
                response = connection.getresponse()
                retry_after = response.getheader("Retry-After")
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertFalse(store_ready)
            self.assertEqual(503, response.status)
            self.assertEqual("1", retry_after)
            self.assertEqual("backtest_job_store_unavailable", payload["error"])
            self.assertEqual("BACKTEST_JOB_STORE_UNAVAILABLE", payload["reason_code"])

    def test_idempotency_mapping_requires_exact_schema_and_job_hashes(self):
        request = {"schema_version": "backtest_run_request.v1"}
        request_sha256 = hashlib.sha256(
            b'{"schema_version":"backtest_run_request.v1"}'
        ).hexdigest()
        original_key = "strict-mapping"
        original_key_sha256 = hashlib.sha256(
            original_key.encode("ascii")
        ).hexdigest()
        for name in ("unknown-key", "request-cross-mismatch", "filename-mismatch"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                fixture = Path(tmp) / "history.json"
                fixture.write_text('{"rows": []}', encoding="utf-8")
                fixture_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
                job_digest = hashlib.sha256(
                    (
                        f"{original_key_sha256}:{request_sha256}:"
                        f"{fixture_sha256}"
                    ).encode("ascii")
                ).hexdigest()
                job_id = f"job-{job_digest}"
                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=Path(tmp) / "artifacts",
                    use_subprocess=False,
                )
                job = {
                    "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                    "job_id": job_id,
                    "status": "queued",
                    "submitted_at": "2026-07-14T00:00:00Z",
                    "started_at": None,
                    "completed_at": None,
                    "request_sha256": request_sha256,
                    "fixture_sha256": fixture_sha256,
                    "idempotency_key_sha256": original_key_sha256,
                    "status_url": f"/backtest/jobs/{job_id}",
                    "result_url": f"/backtest/jobs/{job_id}/result",
                    "report_id": None,
                    "report_url": None,
                    "default_promotion_status": "not_started",
                    "reason_code": None,
                    "research_only": True,
                }
                (service.jobs_dir / f"{job_id}.json").write_text(
                    json.dumps(job), encoding="utf-8"
                )
                selected_key = original_key
                selected_key_sha256 = original_key_sha256
                mapping = {
                    "schema_version": "backtest_idempotency_record.v1",
                    "job_id": job_id,
                    "request_sha256": request_sha256,
                    "fixture_sha256": fixture_sha256,
                }
                if name == "unknown-key":
                    mapping["operator_secret"] = "must-not-be-trusted"
                elif name == "request-cross-mismatch":
                    mapping["request_sha256"] = "f" * 64
                else:
                    selected_key = "renamed-mapping"
                    selected_key_sha256 = hashlib.sha256(
                        selected_key.encode("ascii")
                    ).hexdigest()
                (service.jobs_dir / f"idempotency-{selected_key_sha256}.json").write_text(
                    json.dumps(mapping), encoding="utf-8"
                )
                try:
                    store_ready = service.readiness_status()["store_ready"]
                    with self.assertRaises(BacktestJobStoreCorrupt):
                        service.submit(
                            idempotency_key=selected_key,
                            request=request,
                        )
                finally:
                    service.close()

                self.assertFalse(store_ready)

    def test_current_job_id_must_match_its_deterministic_hash_tuple(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            service = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                use_subprocess=False,
            )
            request = {"schema_version": "backtest_run_request.v1"}
            request_sha256 = hashlib.sha256(
                b'{"schema_version":"backtest_run_request.v1"}'
            ).hexdigest()
            idempotency_key = "forged-job-id"
            key_sha256 = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()
            fixture_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
            forged_job_id = "job-" + "e" * 64
            job = {
                "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                "job_id": forged_job_id,
                "status": "queued",
                "submitted_at": "2026-07-14T00:00:00Z",
                "started_at": None,
                "completed_at": None,
                "request_sha256": request_sha256,
                "fixture_sha256": fixture_sha256,
                "idempotency_key_sha256": key_sha256,
                "status_url": f"/backtest/jobs/{forged_job_id}",
                "result_url": f"/backtest/jobs/{forged_job_id}/result",
                "report_id": None,
                "report_url": None,
                "default_promotion_status": "not_started",
                "reason_code": None,
                "research_only": True,
            }
            mapping = {
                "schema_version": "backtest_idempotency_record.v1",
                "job_id": forged_job_id,
                "request_sha256": request_sha256,
                "fixture_sha256": fixture_sha256,
            }
            (service.jobs_dir / f"{forged_job_id}.json").write_text(
                json.dumps(job), encoding="utf-8"
            )
            (service.jobs_dir / f"idempotency-{key_sha256}.json").write_text(
                json.dumps(mapping), encoding="utf-8"
            )
            try:
                self.assertFalse(service.readiness_status()["store_ready"])
                with self.assertRaises(BacktestJobStoreCorrupt):
                    service.submit(idempotency_key=idempotency_key, request=request)
            finally:
                service.close()

    def test_succeeded_job_without_immutable_artifact_is_unready_and_returns_503(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            server = ResearchHTTPServer(
                ("127.0.0.1", 0),
                ResearchReportHandler,
                runtime=RuntimeConfig(
                    historical_fixture=str(fixture),
                    backtest_artifact_dir=str(Path(tmp) / "artifacts"),
                ),
            )
            request_body = b'{"schema_version":"backtest_run_request.v1"}'
            request_sha256 = hashlib.sha256(request_body).hexdigest()
            idempotency_key = "missing-succeeded-artifact"
            key_sha256 = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()
            fixture_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
            job_digest = hashlib.sha256(
                f"{key_sha256}:{request_sha256}:{fixture_sha256}".encode("ascii")
            ).hexdigest()
            job_id = f"job-{job_digest}"
            report_id = "bt-" + "f" * 64
            job = {
                "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "status": "succeeded",
                "submitted_at": "2026-07-14T00:00:00Z",
                "started_at": "2026-07-14T00:00:01Z",
                "completed_at": "2026-07-14T00:00:02Z",
                "request_sha256": request_sha256,
                "fixture_sha256": fixture_sha256,
                "idempotency_key_sha256": key_sha256,
                "status_url": f"/backtest/jobs/{job_id}",
                "result_url": f"/backtest/jobs/{job_id}/result",
                "report_id": report_id,
                "report_url": f"/backtest/report/{report_id}",
                "default_promotion_status": "pending",
                "reason_code": None,
                "research_only": True,
            }
            mapping = {
                "schema_version": "backtest_idempotency_record.v1",
                "job_id": job_id,
                "request_sha256": request_sha256,
                "fixture_sha256": fixture_sha256,
            }
            (server.backtest_jobs.jobs_dir / f"{job_id}.json").write_text(
                json.dumps(job), encoding="utf-8"
            )
            (
                server.backtest_jobs.jobs_dir / f"idempotency-{key_sha256}.json"
            ).write_text(json.dumps(mapping), encoding="utf-8")
            store_ready = server.backtest_jobs.readiness_status()["store_ready"]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            try:
                connection.request("GET", f"/backtest/jobs/{job_id}/result")
                response = connection.getresponse()
                retry_after = response.getheader("Retry-After")
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertFalse(store_ready)
            self.assertEqual(503, response.status)
            self.assertEqual("1", retry_after)
            self.assertEqual("backtest_job_store_unavailable", payload["error"])
            self.assertEqual("BACKTEST_JOB_STORE_UNAVAILABLE", payload["reason_code"])

    def test_legacy_succeeded_job_also_requires_its_immutable_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "history.json"
            fixture.write_text('{"rows":[]}', encoding="utf-8")
            service = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=root / "artifacts",
                use_subprocess=False,
            )
            job_id = "job-" + "d" * 64
            self._write_succeeded_job(
                service.jobs_dir,
                job_id=job_id,
                report_id="bt-" + "e" * 64,
                completed_at="2026-07-14T00:00:02Z",
                promotion_status="pending",
            )
            try:
                self.assertFalse(service.readiness_status()["store_ready"])
                with self.assertRaises(BacktestArtifactCorrupt):
                    service.result(job_id)
            finally:
                service.close()

    def test_evidence_artifact_requires_exact_public_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            original = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                update_default_pointer=False,
            )

            invalid_artifacts = {}
            unknown_artifact_field = json.loads(json.dumps(original))
            unknown_artifact_field["operator_secret"] = "must-not-be-reflected"
            invalid_artifacts["unknown-artifact-field"] = unknown_artifact_field

            unknown_report_field = json.loads(json.dumps(original))
            unknown_report_field["backtest_report"]["operator_secret"] = (
                "must-not-be-reflected"
            )
            invalid_artifacts["unknown-report-field"] = unknown_report_field

            unknown_nested_policy_field = json.loads(json.dumps(original))
            unknown_nested_policy_field["backtest_report"]["baseline_policy"][
                "operator_secret"
            ] = "must-not-be-reflected"
            invalid_artifacts["unknown-nested-policy-field"] = (
                unknown_nested_policy_field
            )

            unknown_nested_metric_field = json.loads(json.dumps(original))
            unknown_nested_metric_field["backtest_report"]["metrics"]["cagr"][
                "operator_secret"
            ] = "must-not-be-reflected"
            invalid_artifacts["unknown-nested-metric-field"] = (
                unknown_nested_metric_field
            )

            misplaced_known_object_shape = json.loads(json.dumps(original))
            misplaced_known_object_shape["backtest_report"]["metrics"] = {
                "bid": 123.0
            }
            invalid_artifacts["misplaced-known-object-shape"] = (
                misplaced_known_object_shape
            )

            misplaced_known_metric_leaf = json.loads(json.dumps(original))
            misplaced_known_metric_leaf["backtest_report"]["metrics"]["cagr"] = {
                "bid": 123.0
            }
            invalid_artifacts["misplaced-known-metric-leaf"] = (
                misplaced_known_metric_leaf
            )

            misplaced_known_policy_shape = json.loads(json.dumps(original))
            misplaced_known_policy_shape["backtest_report"]["baseline_policy"][
                "selection"
            ] = {"status": "available", "value": 1.0}
            invalid_artifacts["misplaced-known-policy-shape"] = (
                misplaced_known_policy_shape
            )

            wrong_report_type = json.loads(json.dumps(original))
            wrong_report_type["backtest_report"]["metrics"] = []
            invalid_artifacts["wrong-report-type"] = wrong_report_type

            missing_required_field = json.loads(json.dumps(original))
            del missing_required_field["research_only"]
            invalid_artifacts["missing-required-field"] = missing_required_field

            for name, artifact in invalid_artifacts.items():
                with self.subTest(name=name):
                    core = {
                        key: value
                        for key, value in artifact.items()
                        if key != "report_id"
                    }
                    report_id = "bt-" + hashlib.sha256(
                        json.dumps(
                            core,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                            allow_nan=False,
                        ).encode("utf-8")
                    ).hexdigest()
                    artifact["report_id"] = report_id
                    (artifact_dir / f"{report_id}.json").write_text(
                        json.dumps(artifact),
                        encoding="utf-8",
                    )

                    with self.assertRaises(BacktestArtifactCorrupt):
                        load_backtest_evidence(artifact_dir, report_id)
                    if name == "unknown-artifact-field":
                        server = ResearchHTTPServer(
                            ("127.0.0.1", 0),
                            ResearchReportHandler,
                            runtime=RuntimeConfig(
                                backtest_artifact_dir=str(artifact_dir)
                            ),
                        )
                        thread = threading.Thread(
                            target=server.serve_forever,
                            daemon=True,
                        )
                        thread.start()
                        connection = http.client.HTTPConnection(
                            "127.0.0.1",
                            server.server_port,
                            timeout=5,
                        )
                        try:
                            connection.request(
                                "GET",
                                f"/backtest/report/{report_id}",
                            )
                            response = connection.getresponse()
                            response_payload = json.loads(response.read())
                        finally:
                            connection.close()
                            server.shutdown()
                            server.server_close()
                            thread.join(timeout=5)
                        self.assertEqual(503, response.status)
                        self.assertEqual(
                            "backtest_job_store_unavailable",
                            response_payload["error"],
                        )
                        self.assertNotIn(
                            "must-not-be-reflected",
                            json.dumps(response_payload),
                        )

    def test_current_succeeded_job_must_match_its_result_fixture_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configured_fixture = root / "configured.json"
            configured_fixture.write_text(
                '{"name":"empty","rows":[]}',
                encoding="utf-8",
            )
            other_fixture = root / "other.json"
            other_fixture.write_text(
                '{"name":"empty","rows":[]}\n',
                encoding="utf-8",
            )
            artifact_dir = root / "artifacts"
            other_artifact = run_backtest_evidence_job(
                fixture_path=other_fixture,
                artifact_dir=artifact_dir,
                update_default_pointer=False,
            )
            jobs_dir = artifact_dir / "jobs"
            jobs_dir.mkdir()

            request_body = b'{"schema_version":"backtest_run_request.v1"}'
            request_sha256 = hashlib.sha256(request_body).hexdigest()
            idempotency_key = "cross-fixture-result"
            key_sha256 = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()
            fixture_sha256 = hashlib.sha256(
                configured_fixture.read_bytes()
            ).hexdigest()
            job_id = "job-" + hashlib.sha256(
                f"{key_sha256}:{request_sha256}:{fixture_sha256}".encode("ascii")
            ).hexdigest()
            job = {
                "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "status": "succeeded",
                "submitted_at": "2026-07-14T00:00:00Z",
                "started_at": "2026-07-14T00:00:01Z",
                "completed_at": "2026-07-14T00:00:02Z",
                "request_sha256": request_sha256,
                "fixture_sha256": fixture_sha256,
                "idempotency_key_sha256": key_sha256,
                "status_url": f"/backtest/jobs/{job_id}",
                "result_url": f"/backtest/jobs/{job_id}/result",
                "report_id": other_artifact["report_id"],
                "report_url": f"/backtest/report/{other_artifact['report_id']}",
                "default_promotion_status": "pending",
                "reason_code": None,
                "research_only": True,
            }
            mapping = {
                "schema_version": "backtest_idempotency_record.v1",
                "job_id": job_id,
                "request_sha256": request_sha256,
                "fixture_sha256": fixture_sha256,
            }
            (jobs_dir / f"{job_id}.json").write_text(
                json.dumps(job),
                encoding="utf-8",
            )
            (jobs_dir / f"idempotency-{key_sha256}.json").write_text(
                json.dumps(mapping),
                encoding="utf-8",
            )

            service = BacktestJobService(
                fixture_path=configured_fixture,
                artifact_dir=artifact_dir,
                use_subprocess=False,
            )
            try:
                self.assertFalse(service.readiness_status()["store_ready"])
                with self.assertRaises(BacktestArtifactCorrupt):
                    service.result(job_id)
                (artifact_dir / "default.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "backtest_default_pointer.v2",
                            "report_id": other_artifact["report_id"],
                            "job_id": job_id,
                            "completed_at": job["completed_at"],
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(BacktestArtifactCorrupt):
                    load_backtest_evidence(artifact_dir)
            finally:
                service.close()

    def test_current_job_lifecycle_timestamps_are_monotonic_and_cancel_never_started(self):
        cases = {
            "running-before-submission": {
                "status": "running",
                "started_at": "2026-07-13T23:59:59Z",
                "completed_at": None,
                "reason_code": None,
            },
            "succeeded-before-start": {
                "status": "succeeded",
                "started_at": "2026-07-14T00:00:02Z",
                "completed_at": "2026-07-14T00:00:01Z",
                "reason_code": None,
            },
            "failed-before-submission": {
                "status": "failed",
                "started_at": None,
                "completed_at": "2026-07-13T23:59:59Z",
                "reason_code": "BACKTEST_JOB_SUBMISSION_FAILED",
            },
            "timeout-without-start": {
                "status": "failed",
                "started_at": None,
                "completed_at": "2026-07-14T00:00:02Z",
                "reason_code": "BACKTEST_JOB_TIMEOUT",
            },
            "cancelled-after-start": {
                "status": "cancelled",
                "started_at": "2026-07-14T00:00:01Z",
                "completed_at": "2026-07-14T00:00:02Z",
                "reason_code": "BACKTEST_JOB_CANCELLED",
            },
        }
        for name, state in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixture = root / "history.json"
                fixture.write_text(
                    '{"name":"empty","rows":[]}',
                    encoding="utf-8",
                )
                artifact_dir = root / "artifacts"
                artifact = run_backtest_evidence_job(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    update_default_pointer=False,
                )
                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    use_subprocess=False,
                )
                request_sha256 = hashlib.sha256(
                    b'{"schema_version":"backtest_run_request.v1"}'
                ).hexdigest()
                key_sha256 = hashlib.sha256(name.encode("ascii")).hexdigest()
                fixture_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
                job_id = "job-" + hashlib.sha256(
                    f"{key_sha256}:{request_sha256}:{fixture_sha256}".encode(
                        "ascii"
                    )
                ).hexdigest()
                succeeded = state["status"] == "succeeded"
                job = {
                    "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                    "job_id": job_id,
                    "status": state["status"],
                    "submitted_at": "2026-07-14T00:00:00Z",
                    "started_at": state["started_at"],
                    "completed_at": state["completed_at"],
                    "request_sha256": request_sha256,
                    "fixture_sha256": fixture_sha256,
                    "idempotency_key_sha256": key_sha256,
                    "status_url": f"/backtest/jobs/{job_id}",
                    "result_url": f"/backtest/jobs/{job_id}/result",
                    "report_id": artifact["report_id"] if succeeded else None,
                    "report_url": (
                        f"/backtest/report/{artifact['report_id']}"
                        if succeeded
                        else None
                    ),
                    "default_promotion_status": (
                        "pending" if succeeded else "not_started"
                    ),
                    "reason_code": state["reason_code"],
                    "research_only": True,
                }
                mapping = {
                    "schema_version": "backtest_idempotency_record.v1",
                    "job_id": job_id,
                    "request_sha256": request_sha256,
                    "fixture_sha256": fixture_sha256,
                }
                (service.jobs_dir / f"{job_id}.json").write_text(
                    json.dumps(job),
                    encoding="utf-8",
                )
                (
                    service.jobs_dir / f"idempotency-{key_sha256}.json"
                ).write_text(json.dumps(mapping), encoding="utf-8")
                try:
                    self.assertFalse(service.readiness_status()["store_ready"])
                    with self.assertRaises(BacktestJobStoreCorrupt):
                        service.get(job_id)
                finally:
                    service.close()

    def test_restart_recovery_only_rewrites_coherent_active_lifecycles(self):
        cases = {
            "queued-without-start": {
                "status": "queued",
                "started_at": None,
                "recover": True,
            },
            "running-with-start": {
                "status": "running",
                "started_at": "2026-07-14T00:00:01Z",
                "recover": True,
            },
            "queued-with-start": {
                "status": "queued",
                "started_at": "2026-07-14T00:00:01Z",
                "recover": False,
            },
            "running-without-start": {
                "status": "running",
                "started_at": None,
                "recover": False,
            },
        }
        for name, state in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixture = root / "history.json"
                fixture.write_text(
                    '{"name":"empty","rows":[]}',
                    encoding="utf-8",
                )
                artifact_dir = root / "artifacts"
                jobs_dir = artifact_dir / "jobs"
                jobs_dir.mkdir(parents=True)
                request_sha256 = hashlib.sha256(
                    b'{"schema_version":"backtest_run_request.v1"}'
                ).hexdigest()
                key_sha256 = hashlib.sha256(name.encode("ascii")).hexdigest()
                fixture_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
                job_id = "job-" + hashlib.sha256(
                    f"{key_sha256}:{request_sha256}:{fixture_sha256}".encode(
                        "ascii"
                    )
                ).hexdigest()
                job = {
                    "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                    "job_id": job_id,
                    "status": state["status"],
                    "submitted_at": "2026-07-14T00:00:00Z",
                    "started_at": state["started_at"],
                    "completed_at": None,
                    "request_sha256": request_sha256,
                    "fixture_sha256": fixture_sha256,
                    "idempotency_key_sha256": key_sha256,
                    "status_url": f"/backtest/jobs/{job_id}",
                    "result_url": f"/backtest/jobs/{job_id}/result",
                    "report_id": None,
                    "report_url": None,
                    "default_promotion_status": "not_started",
                    "reason_code": None,
                    "research_only": True,
                }
                job_path = jobs_dir / f"{job_id}.json"
                job_path.write_text(json.dumps(job), encoding="utf-8")

                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    use_subprocess=False,
                )
                try:
                    persisted = json.loads(job_path.read_text(encoding="utf-8"))
                    self.assertEqual(state["started_at"], persisted["started_at"])
                    if state["recover"]:
                        self.assertEqual("failed", persisted["status"])
                        self.assertEqual("JOB_INTERRUPTED", persisted["reason_code"])
                        self.assertTrue(service.readiness_status()["store_ready"])
                        self.assertEqual("failed", service.get(job_id)["status"])
                    else:
                        self.assertEqual(state["status"], persisted["status"])
                        self.assertFalse(service.readiness_status()["store_ready"])
                        with self.assertRaises(BacktestJobStoreCorrupt):
                            service.get(job_id)
                finally:
                    service.close()

    def test_default_pointer_requires_an_exact_versioned_schema(self):
        invalid_pointers = {
            "legacy-unknown-field": {
                "schema_version": "backtest_default_pointer.v1",
                "operator_secret": "must-not-be-trusted",
            },
            "current-unknown-field": {
                "schema_version": "backtest_default_pointer.v2",
                "job_id": "job-" + "a" * 64,
                "completed_at": "2026-07-14T00:00:00Z",
                "operator_secret": "must-not-be-trusted",
            },
            "current-invalid-job-id": {
                "schema_version": "backtest_default_pointer.v2",
                "job_id": "not-a-job",
                "completed_at": "2026-07-14T00:00:00Z",
            },
            "current-naive-completion": {
                "schema_version": "backtest_default_pointer.v2",
                "job_id": "job-" + "b" * 64,
                "completed_at": "2026-07-14T00:00:00",
            },
        }
        for name, pointer_fields in invalid_pointers.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixture = root / "history.json"
                fixture.write_text(
                    '{"name":"empty","rows":[]}',
                    encoding="utf-8",
                )
                artifact_dir = root / "artifacts"
                artifact = run_backtest_evidence_job(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    update_default_pointer=False,
                )
                pointer = {
                    **pointer_fields,
                    "report_id": artifact["report_id"],
                }
                (artifact_dir / "default.json").write_text(
                    json.dumps(pointer),
                    encoding="utf-8",
                )
                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    use_subprocess=False,
                )
                try:
                    self.assertFalse(service.readiness_status()["store_ready"])
                    with self.assertRaises(BacktestArtifactCorrupt):
                        load_backtest_evidence(artifact_dir)
                finally:
                    service.close()

    def test_current_default_pointer_must_cross_link_one_succeeded_job(self):
        cases = ("missing-job", "report-mismatch", "completion-mismatch")
        for name in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixture = root / "history.json"
                fixture.write_text(
                    '{"name":"empty","rows":[]}',
                    encoding="utf-8",
                )
                artifact_dir = root / "artifacts"
                first = run_backtest_evidence_job(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    generated_at="2026-07-14T00:00:00Z",
                    update_default_pointer=False,
                )
                second = run_backtest_evidence_job(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    generated_at="2026-07-14T00:01:00Z",
                    update_default_pointer=False,
                )
                jobs_dir = artifact_dir / "jobs"
                job_id = "job-" + "c" * 64
                completed_at = "2026-07-14T00:00:02Z"
                self._write_succeeded_job(
                    jobs_dir,
                    job_id=job_id,
                    report_id=first["report_id"],
                    completed_at=completed_at,
                    promotion_status="pending",
                )
                pointer = {
                    "schema_version": "backtest_default_pointer.v2",
                    "report_id": first["report_id"],
                    "job_id": job_id,
                    "completed_at": completed_at,
                }
                if name == "missing-job":
                    pointer["job_id"] = "job-" + "d" * 64
                elif name == "report-mismatch":
                    pointer["report_id"] = second["report_id"]
                else:
                    pointer["completed_at"] = "2026-07-14T00:00:03Z"
                (artifact_dir / "default.json").write_text(
                    json.dumps(pointer),
                    encoding="utf-8",
                )

                with self.assertRaises(BacktestArtifactCorrupt):
                    load_backtest_evidence(artifact_dir)

    def test_existing_default_pointer_with_missing_artifact_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            missing_report_id = "bt-" + "f" * 64
            (artifact_dir / "default.json").write_text(
                json.dumps(
                    {
                        "schema_version": "backtest_default_pointer.v1",
                        "report_id": missing_report_id,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(BacktestArtifactCorrupt):
                load_backtest_evidence(artifact_dir)

    def test_failed_status_write_error_does_not_leave_replayed_ghost_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            service = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=Path(tmp) / "artifacts",
                use_subprocess=False,
            )
            request = {"schema_version": "backtest_run_request.v1"}
            from crypto_options_report import evidence_store

            real_atomic_write = evidence_store.atomic_write_json

            def fail_submission_status_write(path, value, **kwargs):
                if (
                    isinstance(value, dict)
                    and value.get("reason_code")
                    == "BACKTEST_JOB_SUBMISSION_FAILED"
                ):
                    raise PermissionError("sharing violation")
                return real_atomic_write(path, value, **kwargs)

            try:
                with (
                    patch.object(
                        service._executor,
                        "submit",
                        side_effect=RuntimeError("executor unavailable"),
                    ),
                    patch(
                        "crypto_options_report.evidence_store.atomic_write_json",
                        side_effect=fail_submission_status_write,
                    ),self.assertRaises(PermissionError)
                ):
                    service.submit(
                        idempotency_key="status-write-failure",
                        request=request,
                    )

                retry = service.submit(
                    idempotency_key="status-write-failure",
                    request=request,
                )
            finally:
                service.close()

            self.assertFalse(retry["replayed"])
            self.assertEqual("queued", retry["status"])

    def test_corrupt_content_addressed_artifacts_return_structured_503(self):
        fixture = (
            Path(__file__).with_name("fixtures")
            / "historical_vendor"
            / "baseline_backtest_fixture.json"
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=tmp,
                generated_at="2026-07-14T00:00:00Z",
            )
            artifact_path = Path(tmp) / f"{artifact['report_id']}.json"
            tampered = json.loads(artifact_path.read_text(encoding="utf-8"))
            tampered["status"] = "tampered"
            artifact_path.write_text(json.dumps(tampered), encoding="utf-8")
            runtime = RuntimeConfig(
                historical_fixture=str(fixture),
                backtest_artifact_dir=tmp,
            )

            status, payload = self._request(
                "GET",
                "/backtest/report/default",
                runtime,
            )

        self.assertEqual(503, status)
        self.assertEqual("backtest_job_store_unavailable", payload["error"])
        self.assertEqual("BACKTEST_JOB_STORE_UNAVAILABLE", payload["reason_code"])

    def test_http_submission_failure_allows_same_key_to_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            server = ResearchHTTPServer(
                ("127.0.0.1", 0),
                ResearchReportHandler,
                runtime=RuntimeConfig(
                    historical_fixture=str(fixture),
                    backtest_artifact_dir=str(Path(tmp) / "artifacts"),
                ),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def submit_once():
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=5
                )
                try:
                    connection.request(
                        "POST",
                        "/backtest/run",
                        body=b'{"schema_version":"backtest_run_request.v1"}',
                        headers={
                            "Content-Type": "application/json",
                            "Idempotency-Key": "executor-failure-http",
                        },
                    )
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                    return response.status, response.getheader("Retry-After"), payload
                finally:
                    connection.close()

            try:
                with patch.object(
                    server.backtest_jobs._executor,
                    "submit",
                    side_effect=RuntimeError("executor unavailable"),
                ):
                    first = submit_once()
                replay = submit_once()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(503, first[0])
            self.assertEqual(202, replay[0])
            self.assertEqual("1", first[1])
            self.assertIsNone(replay[1])
            self.assertEqual(first[2]["job_id"], replay[2]["job_id"])
            self.assertFalse(first[2]["replayed"])
            self.assertFalse(replay[2]["replayed"])
            self.assertEqual("queued", replay[2]["status"])

    def test_success_status_write_failure_finishes_failed_without_default_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            from crypto_options_report import evidence_store

            real_atomic_write = evidence_store.atomic_write_json
            failed_once = False

            def fail_succeeded_job_once(path, value, **kwargs):
                nonlocal failed_once
                if (
                    not failed_once
                    and isinstance(value, dict)
                    and value.get("schema_version") == "backtest_job_status.v1"
                    and value.get("status") == "succeeded"
                ):
                    failed_once = True
                    raise OSError("simulated terminal write failure")
                return real_atomic_write(path, value, **kwargs)

            with patch(
                "crypto_options_report.evidence_store.atomic_write_json",
                side_effect=fail_succeeded_job_once,
            ):
                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    use_subprocess=False,
                )
                submitted = service.submit(
                    idempotency_key="terminal-write-failure",
                    request={
                        "schema_version": "backtest_run_request.v1",
                        "generated_at": "2026-07-13T00:00:00Z",
                    },
                )
                service.close()
                terminal = service.get(submitted["job_id"])

            self.assertTrue(failed_once)
            self.assertEqual("failed", terminal["status"])
            self.assertEqual("BACKTEST_JOB_FAILED", terminal["reason_code"])
            self.assertFalse((artifact_dir / "default.json").exists())

    def test_default_pointer_failure_never_regresses_succeeded_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"

            with patch(
                "crypto_options_report.evidence_store.promote_backtest_evidence_default",
                side_effect=OSError("pointer unavailable"),
            ):
                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=artifact_dir,
                    use_subprocess=False,
                )
                submitted = service.submit(
                    idempotency_key="pointer-failure",
                    request={
                        "schema_version": "backtest_run_request.v1",
                        "generated_at": "2026-07-13T00:00:00Z",
                    },
                )
                service.close()
                terminal = service.get(submitted["job_id"])

            self.assertEqual("succeeded", terminal["status"])
            self.assertEqual("pending", terminal["default_promotion_status"])
            self.assertFalse((artifact_dir / "default.json").exists())

            recovered = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
            )
            self.assertTrue(recovered.readiness_status()["store_ready"])
            recovered.close()
            healed = recovered.get(submitted["job_id"])
            self.assertEqual("succeeded", healed["status"])
            self.assertEqual("promoted", healed["default_promotion_status"])
            self.assertTrue((artifact_dir / "default.json").is_file())

    def test_recovery_never_rolls_default_pointer_back_to_older_pending_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            older = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:00:00Z",
                update_default_pointer=False,
            )
            newer = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:01:00Z",
                update_default_pointer=False,
            )
            jobs_dir = artifact_dir / "jobs"
            jobs_dir.mkdir()
            older_job_id = "job-" + "a" * 64
            newer_job_id = "job-" + "b" * 64
            self._write_succeeded_job(
                jobs_dir,
                job_id=older_job_id,
                report_id=older["report_id"],
                completed_at="2026-07-13T00:00:01Z",
                promotion_status="pending",
            )
            self._write_succeeded_job(
                jobs_dir,
                job_id=newer_job_id,
                report_id=newer["report_id"],
                completed_at="2026-07-13T00:01:01Z",
                promotion_status="promoted",
            )
            promote_backtest_evidence_default(artifact_dir, newer["report_id"])

            recovered = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
            )
            recovered.close()

            selected = load_backtest_evidence(artifact_dir)
            self.assertEqual(newer["report_id"], selected["report_id"])
            self.assertEqual(
                "pending",
                recovered.get(older_job_id)["default_promotion_status"],
            )

    def test_recovery_marks_existing_pending_pointer_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            artifact = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:00:00Z",
                update_default_pointer=False,
            )
            job_id = "job-" + "c" * 64
            self._write_succeeded_job(
                artifact_dir / "jobs",
                job_id=job_id,
                report_id=artifact["report_id"],
                completed_at="2026-07-13T00:00:01Z",
                promotion_status="pending",
            )
            promote_backtest_evidence_default(
                artifact_dir,
                artifact["report_id"],
                job_id=job_id,
                completed_at="2026-07-13T00:00:01Z",
            )
            pointer_path = artifact_dir / "default.json"
            pointer_before = pointer_path.read_bytes()

            recovered = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
            )
            recovered.close()

            self.assertEqual(pointer_before, pointer_path.read_bytes())
            self.assertEqual(
                "promoted",
                recovered.get(job_id)["default_promotion_status"],
            )

    def test_recovery_uses_stable_job_id_tiebreak_for_pending_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            lower = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:00:00Z",
                update_default_pointer=False,
            )
            higher = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:01:00Z",
                update_default_pointer=False,
            )
            lower_job_id = "job-" + "1" * 64
            higher_job_id = "job-" + "f" * 64
            completed_at = "2026-07-13T00:02:00Z"
            self._write_succeeded_job(
                artifact_dir / "jobs",
                job_id=higher_job_id,
                report_id=higher["report_id"],
                completed_at=completed_at,
                promotion_status="pending",
            )
            self._write_succeeded_job(
                artifact_dir / "jobs",
                job_id=lower_job_id,
                report_id=lower["report_id"],
                completed_at=completed_at,
                promotion_status="pending",
            )

            recovered = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
            )
            recovered.close()

            pointer = json.loads((artifact_dir / "default.json").read_text("utf-8"))
            self.assertEqual(higher["report_id"], pointer["report_id"])
            self.assertEqual(higher_job_id, pointer["job_id"])
            self.assertEqual(
                "pending",
                recovered.get(lower_job_id)["default_promotion_status"],
            )

    def test_recovery_preserves_unordered_valid_legacy_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            direct = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:00:00Z",
                update_default_pointer=False,
            )
            pending = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:01:00Z",
                update_default_pointer=False,
            )
            pending_job_id = "job-" + "d" * 64
            self._write_succeeded_job(
                artifact_dir / "jobs",
                job_id=pending_job_id,
                report_id=pending["report_id"],
                completed_at="2026-07-13T00:01:01Z",
                promotion_status="pending",
            )
            promote_backtest_evidence_default(artifact_dir, direct["report_id"])

            recovered = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
            )
            recovered.close()

            self.assertEqual(
                direct["report_id"],
                load_backtest_evidence(artifact_dir)["report_id"],
            )
            self.assertEqual(
                "pending",
                recovered.get(pending_job_id)["default_promotion_status"],
            )

    def test_recovery_repairs_invalid_pointer_with_latest_valid_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            latest = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:01:00Z",
                update_default_pointer=False,
            )
            job_id = "job-" + "e" * 64
            self._write_succeeded_job(
                artifact_dir / "jobs",
                job_id=job_id,
                report_id=latest["report_id"],
                completed_at="2026-07-13T00:01:01Z",
                promotion_status="pending",
            )
            (artifact_dir / "default.json").write_text(
                '{"schema_version":"broken","report_id":"invalid"}',
                encoding="utf-8",
            )

            recovered = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
            )
            legacy_store_ready = recovered.readiness_status()["store_ready"]
            recovered.close()

            self.assertTrue(legacy_store_ready)
            self.assertEqual(
                latest["report_id"],
                load_backtest_evidence(artifact_dir)["report_id"],
            )
            self.assertEqual(
                "promoted",
                recovered.get(job_id)["default_promotion_status"],
            )

    def test_recovery_does_not_promote_malformed_legacy_job_and_store_is_unready(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            current = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:00:00Z",
                update_default_pointer=False,
            )
            unordered = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:01:00Z",
                update_default_pointer=False,
            )
            current_job_id = "job-" + "4" * 64
            unordered_job_id = "job-" + "5" * 64
            self._write_succeeded_job(
                artifact_dir / "jobs",
                job_id=current_job_id,
                report_id=current["report_id"],
                completed_at="2026-07-13T00:00:01Z",
                promotion_status="promoted",
            )
            self._write_succeeded_job(
                artifact_dir / "jobs",
                job_id=unordered_job_id,
                report_id=unordered["report_id"],
                completed_at="not-a-timestamp",
                promotion_status="pending",
            )
            promote_backtest_evidence_default(
                artifact_dir,
                current["report_id"],
                job_id=current_job_id,
                completed_at="2026-07-13T00:00:01Z",
            )

            recovered = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
            )
            store_ready = recovered.readiness_status()["store_ready"]
            recovered.close()

            self.assertEqual(
                current["report_id"],
                load_backtest_evidence(artifact_dir)["report_id"],
            )
            self.assertFalse(store_ready)
            with self.assertRaises(BacktestJobStoreCorrupt):
                recovered.get(unordered_job_id)

    def test_normal_promotion_path_cannot_overwrite_newer_job_with_older_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"name":"empty","rows":[]}', encoding="utf-8")
            artifact_dir = Path(tmp) / "artifacts"
            older = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:00:00Z",
                update_default_pointer=False,
            )
            newer = run_backtest_evidence_job(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
                generated_at="2026-07-13T00:01:00Z",
                update_default_pointer=False,
            )
            service = BacktestJobService(
                fixture_path=fixture,
                artifact_dir=artifact_dir,
            )
            older_job_id = "job-" + "2" * 64
            newer_job_id = "job-" + "3" * 64
            self._write_succeeded_job(
                service.jobs_dir,
                job_id=older_job_id,
                report_id=older["report_id"],
                completed_at="2026-07-13T00:00:01Z",
                promotion_status="pending",
            )
            self._write_succeeded_job(
                service.jobs_dir,
                job_id=newer_job_id,
                report_id=newer["report_id"],
                completed_at="2026-07-13T00:01:01Z",
                promotion_status="pending",
            )

            service._try_promote_default(newer_job_id, artifact=newer)
            service._try_promote_default(older_job_id, artifact=older)
            service.close()

            self.assertEqual(
                newer["report_id"],
                load_backtest_evidence(artifact_dir)["report_id"],
            )

    def test_backtest_timeout_becomes_a_stable_failed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "history.json"
            fixture.write_text('{"rows": []}', encoding="utf-8")
            with patch(
                "crypto_options_report.evidence_store.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="backtest-worker", timeout=60),
            ):
                service = BacktestJobService(
                    fixture_path=fixture,
                    artifact_dir=Path(tmp) / "artifacts",
                )
                try:
                    submitted = service.submit(
                        idempotency_key="timeout",
                        request={"schema_version": "backtest_run_request.v1"},
                    )
                    service.close()
                    completed = service.get(submitted["job_id"])
                finally:
                    if not service._closed:
                        service.close()

            self.assertEqual("failed", completed["status"])
            self.assertEqual("BACKTEST_JOB_TIMEOUT", completed["reason_code"])

    def test_paper_ledger_storage_path_remains_unsupported_and_unwritten(self):
        report = {
            "mode_gate": {"paper_manual_candidates_allowed": False},
            "walk_forward_calibration": {},
            "account_status": {},
            "data_status": {},
            "reason_codes": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            ledger = build_paper_proposal_ledger(
                generated_at="2026-07-13T00:00:00Z",
                report=report,
                storage_path=path,
            )

            self.assertEqual("unsupported", ledger["status"])
            self.assertEqual("NO-GO", ledger["release_state"])
            self.assertEqual("unsupported", ledger["persistence"]["mode"])
            self.assertFalse(ledger["persistence"]["write_allowed"])
            self.assertFalse(path.exists())
            self.assertEqual("not_run", ledger["reconciliation"]["evidence_state"])
            self.assertFalse(ledger["reconciliation"]["ready"])

    def test_existing_paper_file_cannot_self_authorize_reconciliation(self):
        report = {
            "mode_gate": {"paper_manual_candidates_allowed": False},
            "walk_forward_calibration": {},
            "account_status": {},
            "data_status": {},
            "reason_codes": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            path.write_text(
                json.dumps(
                    {
                        "ledger_entries": [
                            {
                                "proposal_id": "proposal-observed",
                                "proposed_at": "2026-06-01T00:00:00Z",
                                "reviewed_at": "2026-06-01T01:00:00Z",
                                "observed_at": "2026-07-02T00:00:00Z",
                                "observed_fill_usdc": None,
                                "terminal_outcome": "rejected",
                                "reconciled": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            before = path.read_bytes()

            ledger = build_paper_proposal_ledger(
                generated_at="2026-07-13T00:00:00Z",
                report=report,
                storage_path=path,
            )

            self.assertEqual(before, path.read_bytes())
            self.assertEqual("unsupported", ledger["status"])
            self.assertEqual("not_authorized", ledger["reconciliation"]["status"])
            self.assertFalse(ledger["reconciliation"]["ready"])
            self.assertEqual([], ledger["ledger_entries"])

    def test_api_get_projection_reads_ledger_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            original = {
                "ledger_entries": [
                    {
                        "proposal_id": "operator-observation",
                        "proposed_at": "2026-06-01T00:00:00Z",
                        "observed_at": "2026-07-02T00:00:00Z",
                        "terminal_outcome": "rejected",
                        "reconciled": True,
                    }
                ]
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            before = path.read_bytes()

            report = build_api_report(paper_ledger_path=str(path))

            self.assertEqual(before, path.read_bytes())
            ledger = report["paper_proposal_ledger"]
            self.assertEqual("unsupported", ledger["status"])
            self.assertFalse(ledger["persistence"]["write_allowed"])
            self.assertIsNone(ledger["persistence"]["storage_path"])
            self.assertEqual([], ledger["ledger_entries"])

    def test_account_not_configured_sidecar_is_normalized_to_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "account.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "deribit_account_snapshot.v1",
                        "account": {"status": "not_configured"},
                        "positions": [],
                        "simulation": {},
                    }
                ),
                encoding="utf-8",
            )

            report = build_api_report(account_snapshot_fixture=str(path))

            self.assertEqual("missing", report["account_status"]["status"])
            self.assertEqual(
                "MISSING_ACCOUNT_API_SNAPSHOT",
                report["account_status"]["reason_code"],
            )

    def test_versioned_manual_runbook_is_verified_local_but_awaits_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            runbook = Path(tmp) / "manual.md"
            runbook.write_text(
                "# Manual approval runbook\n\nVersion: 1.0\n\n"
                "RESEARCH_ONLY. Manual approval is required.\n",
                encoding="utf-8",
            )
            report = build_api_report(manual_approval_runbook_path=str(runbook))
            gates = {
                item["name"]: item
                for item in report["full_system_surface"]["release_readiness"][
                    "prerequisites"
                ]
            }

            gate = gates["external_release_authorization"]
            self.assertFalse(gate["satisfied"])
            self.assertEqual("not_configured", gate["evidence_state"])
            self.assertEqual("awaiting_external", gate["release_state"])
            self.assertEqual("external_operator", gate["owner"])
            self.assertTrue(gate["action"])
            self.assertEqual(
                "EXTERNAL_RELEASE_AUTHORIZATION_REQUIRED", gate["root_cause"]
            )

    def test_packaged_default_manual_runbook_is_available(self):
        report = build_api_report()
        evidence = report["paper_proposal_ledger"]["manual_approval_runbook"]

        self.assertEqual("verified_local", evidence["status"])
        self.assertEqual(DEFAULT_MANUAL_APPROVAL_RUNBOOK_PUBLIC_ID, evidence["path"])
        self.assertRegex(evidence["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(["EXTERNAL_APPROVAL_PENDING"], evidence["reason_codes"])

    def test_api_report_hides_custom_manual_runbook_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            runbook = Path(tmp) / "manual.md"
            runbook.write_text(
                "# Manual approval runbook\n\nVersion: 1.0\n\n"
                "RESEARCH_ONLY. Manual approval is required.\n",
                encoding="utf-8",
            )

            report = build_api_report(manual_approval_runbook_path=str(runbook))

        evidence = report["paper_proposal_ledger"]["manual_approval_runbook"]
        self.assertEqual("verified_local", evidence["status"])
        self.assertEqual(CONFIGURED_MANUAL_APPROVAL_RUNBOOK_PUBLIC_ID, evidence["path"])
        self.assertNotEqual(str(runbook.resolve()), evidence["path"])

    @staticmethod
    def _write_succeeded_job(
        jobs_dir,
        *,
        job_id,
        report_id,
        completed_at,
        promotion_status,
    ):
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{job_id}.json").write_text(
            json.dumps(
                {
                    "schema_version": BACKTEST_JOB_SCHEMA_VERSION,
                    "job_id": job_id,
                    "status": "succeeded",
                    "completed_at": completed_at,
                    "report_id": report_id,
                    "default_promotion_status": promotion_status,
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _live_data_status(trust_evidence):
        return {
            "status": "validated",
            "validated": True,
            "source": "deribit_live:https://www.deribit.com/api/v2",
            "quality_gate": {"status": "pass", "reason_codes": []},
            "feed_coverage": {"missing_feeds": []},
            "public_response_contract": {"overall_status": "pass"},
            "trust_evidence": trust_evidence,
        }

    @staticmethod
    def _request(method, path, runtime, *, body=None, headers=None):
        server = ResearchHTTPServer(
            ("127.0.0.1", 0),
            ResearchReportHandler,
            runtime=runtime,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=5
        )
        try:
            encoded = None if body is None else json.dumps(body).encode("utf-8")
            request_headers = dict(headers or {})
            if encoded is not None:
                request_headers["Content-Type"] = "application/json"
            connection.request(method, path, body=encoded, headers=request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
