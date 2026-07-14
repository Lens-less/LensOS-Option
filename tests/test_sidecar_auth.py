import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from crypto_options_report.sidecar_auth import (
    ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV,
    MARKET_SNAPSHOT_TRUST_HMAC_DOMAIN,
    MAX_SIDECAR_AUTH_STATE_BYTES,
    MAX_SIDECAR_PAYLOAD_BYTES,
    SidecarAuthUnavailable,
    authenticate_sidecar_payload,
    canonical_payload_sha256,
    is_authenticated_sidecar_payload,
    sign_mapping,
    sidecar_auth_state_path,
    verify_mapping,
    write_sidecar_auth_state,
)


class SidecarAuthenticationTests(unittest.TestCase):
    def test_market_domain_signature_cannot_authenticate_account_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            key_file = key_dir / "shared.key"
            key_file.write_bytes(b"s" * 32)
            payload_path = data_dir / "account.json"
            payload = {"captured_at": "2026-07-14T00:00:00Z", "rows": []}
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            state_path = write_sidecar_auth_state(
                payload_path,
                expected_payload=payload,
                key_file=key_file,
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            unsigned = {
                "schema_version": state["schema_version"],
                "payload_sha256": state["payload_sha256"],
            }
            state["hmac_sha256"] = sign_mapping(
                unsigned,
                key_file=key_file,
                domain=MARKET_SNAPSHOT_TRUST_HMAC_DOMAIN,
            )
            state_path.write_text(json.dumps(state), encoding="utf-8")

            forged = authenticate_sidecar_payload(
                payload_path,
                dict(payload),
                key_file=key_file,
            )

        self.assertFalse(is_authenticated_sidecar_payload(forged))

    def test_same_key_signature_cannot_cross_account_and_market_domains(self):
        payload = {"schema_version": "shared-shape.v1", "digest": "a" * 64}
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "shared.key"
            key_file.write_bytes(b"s" * 32)

            account_signature = sign_mapping(
                payload,
                key_file=key_file,
                domain="crypto_options_report/account_snapshot_auth/v1",
            )
            market_signature = sign_mapping(
                payload,
                key_file=key_file,
                domain="crypto_options_report/market_snapshot_trust/v1",
            )
            self.assertNotEqual(account_signature, market_signature)
            self.assertTrue(
                verify_mapping(
                    payload,
                    account_signature,
                    key_file=key_file,
                    domain="crypto_options_report/account_snapshot_auth/v1",
                )
            )
            self.assertTrue(
                verify_mapping(
                    payload,
                    market_signature,
                    key_file=key_file,
                    domain="crypto_options_report/market_snapshot_trust/v1",
                )
            )
            self.assertFalse(
                verify_mapping(
                    payload,
                    account_signature,
                    key_file=key_file,
                    domain="crypto_options_report/market_snapshot_trust/v1",
                )
            )
            self.assertFalse(
                verify_mapping(
                    payload,
                    market_signature,
                    key_file=key_file,
                    domain="crypto_options_report/account_snapshot_auth/v1",
                )
            )

    def test_account_key_environment_rejects_market_key_path_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            key_file = key_dir / "shared.key"
            key_file.write_bytes(b"s" * 32)
            payload_path = data_dir / "account.json"
            payload = {"captured_at": "2026-07-14T00:00:00Z", "rows": []}
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            relative_alias = os.path.relpath(key_file, Path.cwd())

            with mock.patch.dict(
                os.environ,
                {
                    ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV: str(key_file),
                    "CRYPTO_OPTIONS_MARKET_SNAPSHOT_HMAC_KEY_FILE": relative_alias,
                },
                clear=True,
            ):
                with self.assertRaisesRegex(
                    SidecarAuthUnavailable,
                    "distinct key files",
                ):
                    write_sidecar_auth_state(
                        payload_path,
                        expected_payload=payload,
                    )

    def test_account_runtime_uses_only_its_domain_specific_key_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            key_file = key_dir / "account.key"
            key_file.write_bytes(b"a" * 32)
            payload_path = data_dir / "account.json"
            payload = {"captured_at": "2026-07-14T00:00:00Z", "rows": []}
            payload_path.write_text(json.dumps(payload), encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"CRYPTO_OPTIONS_MARKET_SNAPSHOT_HMAC_KEY_FILE": str(key_file)},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    SidecarAuthUnavailable,
                    ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV,
                ):
                    write_sidecar_auth_state(
                        payload_path,
                        expected_payload=payload,
                    )

            with mock.patch.dict(
                os.environ,
                {ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV: str(key_file)},
                clear=True,
            ):
                write_sidecar_auth_state(payload_path, expected_payload=payload)
                authenticated = authenticate_sidecar_payload(payload_path, payload)
            self.assertTrue(is_authenticated_sidecar_payload(authenticated))

    def test_key_must_be_a_regular_file_with_exactly_32_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            payload_path = data_dir / "account.json"
            payload = {"captured_at": "2026-07-14T00:00:00Z"}
            payload_path.write_text(json.dumps(payload), encoding="utf-8")

            invalid_keys = []
            for length in (31, 33):
                candidate = key_dir / f"key-{length}.bin"
                candidate.write_bytes(b"k" * length)
                invalid_keys.append(candidate)
            invalid_keys.append(key_dir)

            for candidate in invalid_keys:
                with self.subTest(key=candidate):
                    with self.assertRaises(SidecarAuthUnavailable):
                        write_sidecar_auth_state(
                            payload_path,
                            expected_payload=payload,
                            key_file=candidate,
                        )

    def test_oversized_auth_state_is_rejected_before_hmac_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            key_file = key_dir / "account.key"
            key_file.write_bytes(b"a" * 32)
            payload_path = data_dir / "account.json"
            payload = {"captured_at": "2026-07-14T00:00:00Z"}
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            sidecar_auth_state_path(payload_path).write_bytes(
                b"{" + b" " * MAX_SIDECAR_AUTH_STATE_BYTES + b"}"
            )

            authenticated = authenticate_sidecar_payload(
                payload_path,
                payload,
                key_file=key_file,
            )

            self.assertFalse(is_authenticated_sidecar_payload(authenticated))

    def test_oversized_account_payload_is_rejected_before_authentication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            key_file = key_dir / "account.key"
            key_file.write_bytes(b"a" * 32)
            payload_path = data_dir / "account.json"
            payload_path.write_bytes(
                b"{" + b" " * MAX_SIDECAR_PAYLOAD_BYTES + b"}"
            )

            with self.assertRaisesRegex(ValueError, "exceeds"):
                write_sidecar_auth_state(
                    payload_path,
                    expected_payload={},
                    key_file=key_file,
                )

    def test_only_keyed_exact_payload_is_authenticated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            key_file = key_dir / "operator.key"
            key_file.write_bytes(b"k" * 32)
            payload_path = data_dir / "account.json"
            payload = {"captured_at": "2026-07-14T00:00:00Z", "rows": []}
            payload_path.write_text(json.dumps(payload), encoding="utf-8")

            unsigned = authenticate_sidecar_payload(
                payload_path,
                dict(payload),
                key_file=key_file,
            )
            self.assertFalse(is_authenticated_sidecar_payload(unsigned))

            write_sidecar_auth_state(
                payload_path,
                expected_payload=payload,
                key_file=key_file,
            )
            authenticated = authenticate_sidecar_payload(
                payload_path,
                dict(payload),
                key_file=key_file,
            )
            self.assertTrue(is_authenticated_sidecar_payload(authenticated))

            authenticated["rows"].append({"forged": True})
            self.assertFalse(is_authenticated_sidecar_payload(authenticated))

    def test_public_digest_without_operator_key_cannot_forge_authentication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            key_dir = root / "keys"
            data_dir.mkdir()
            key_dir.mkdir()
            key_file = key_dir / "operator.key"
            key_file.write_bytes(b"k" * 32)
            payload_path = data_dir / "account.json"
            payload = {"captured_at": "2026-07-14T00:00:00Z", "rows": []}
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            sidecar_auth_state_path(payload_path).write_text(
                json.dumps(
                    {
                        "schema_version": "sidecar_auth_state.v1",
                        "payload_sha256": canonical_payload_sha256(payload),
                        "hmac_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

            forged = authenticate_sidecar_payload(
                payload_path,
                dict(payload),
                key_file=key_file,
            )
            self.assertFalse(is_authenticated_sidecar_payload(forged))
            with self.assertRaises(SidecarAuthUnavailable):
                write_sidecar_auth_state(
                    payload_path,
                    expected_payload=payload,
                    key_file=key_dir / "missing.key",
                )

    def test_payload_or_output_directory_cannot_be_used_as_the_hmac_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            payload_path = data_dir / "account.json"
            payload = {
                "schema_version": "deribit_account_snapshot.v1",
                "captured_at": "2026-07-14T00:00:00Z",
                "padding": "x" * 64,
            }
            payload_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                SidecarAuthUnavailable,
                "outside sidecar output directories",
            ):
                write_sidecar_auth_state(
                    payload_path,
                    expected_payload=payload,
                    key_file=payload_path,
                )

            same_directory_key = data_dir / "operator.key"
            same_directory_key.write_bytes(b"k" * 32)
            with self.assertRaisesRegex(
                SidecarAuthUnavailable,
                "outside sidecar output directories",
            ):
                write_sidecar_auth_state(
                    payload_path,
                    expected_payload=payload,
                    key_file=same_directory_key,
                )


if __name__ == "__main__":
    unittest.main()
