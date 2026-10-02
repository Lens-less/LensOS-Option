"""HMAC authentication for operator-owned sidecar artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from ._canonical import canonical_json_bytes
from .storage import (
    atomic_write_json,
    read_json_object_from_regular_file,
    read_regular_file_bytes,
)

ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV = (
    "CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_HMAC_KEY_FILE"
)
MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV = (
    "CRYPTO_OPTIONS_MARKET_SNAPSHOT_HMAC_KEY_FILE"
)
ACCOUNT_SIDECAR_AUTH_HMAC_DOMAIN = (
    "crypto_options_report/account_snapshot_auth/v1"
)
MARKET_SNAPSHOT_TRUST_HMAC_DOMAIN = (
    "crypto_options_report/market_snapshot_trust/v1"
)
_ALLOWED_HMAC_DOMAINS = frozenset(
    {
        ACCOUNT_SIDECAR_AUTH_HMAC_DOMAIN,
        MARKET_SNAPSHOT_TRUST_HMAC_DOMAIN,
    }
)
SIDECAR_AUTH_STATE_SCHEMA_VERSION = "sidecar_auth_state.v1"
SIDECAR_AUTH_KEY_BYTES = 32
MAX_SIDECAR_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_SIDECAR_AUTH_STATE_BYTES = 1024 * 1024


class SidecarAuthUnavailable(ValueError):
    """No valid operator-owned HMAC key is configured."""


class _AuthenticatedSidecarPayload(dict[str, Any]):
    def __init__(self, value: dict[str, Any], *, payload_sha256: str) -> None:
        super().__init__(value)
        self.payload_sha256 = payload_sha256


def sidecar_auth_state_path(payload_path: str | Path) -> Path:
    path = Path(payload_path).expanduser().resolve()
    return path.with_name(f"{path.name}.auth.json")


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def sign_mapping(
    payload: dict[str, Any],
    *,
    domain: str,
    key_file: str | Path | None = None,
    key_env: str | None = None,
) -> str:
    return hmac.new(
        _read_key(key_file, key_env=key_env),
        _domain_separated_message(payload, domain=domain),
        hashlib.sha256,
    ).hexdigest()


def verify_mapping(
    payload: dict[str, Any],
    signature: Any,
    *,
    domain: str,
    key_file: str | Path | None = None,
    key_env: str | None = None,
) -> bool:
    if not isinstance(signature, str) or len(signature) != 64:
        return False
    try:
        expected = sign_mapping(
            payload,
            domain=domain,
            key_file=key_file,
            key_env=key_env,
        )
    except (OSError, ValueError):
        return False
    return hmac.compare_digest(expected, signature)


def write_sidecar_auth_state(
    payload_path: str | Path,
    *,
    expected_payload: dict[str, Any],
    key_file: str | Path | None = None,
) -> Path:
    path = Path(payload_path).expanduser().resolve()
    raw = read_json_object_from_regular_file(
        path,
        max_bytes=MAX_SIDECAR_PAYLOAD_BYTES,
        description="sidecar payload",
    )
    payload_sha256 = canonical_payload_sha256(raw)
    if payload_sha256 != canonical_payload_sha256(expected_payload):
        raise ValueError("sidecar payload changed before authentication")
    unsigned = {
        "schema_version": SIDECAR_AUTH_STATE_SCHEMA_VERSION,
        "payload_sha256": payload_sha256,
    }
    separated_key = require_separate_key_file(
        payload_path,
        sidecar_auth_state_path(path),
        key_file=key_file,
        key_env=ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV,
        conflicting_key_env=MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV,
    )
    return atomic_write_json(
        sidecar_auth_state_path(path),
        {
            **unsigned,
            "hmac_sha256": sign_mapping(
                unsigned,
                domain=ACCOUNT_SIDECAR_AUTH_HMAC_DOMAIN,
                key_file=separated_key,
            ),
        },
    )


def authenticate_sidecar_payload(
    payload_path: str | Path,
    payload: dict[str, Any],
    *,
    key_file: str | Path | None = None,
) -> dict[str, Any]:
    try:
        exact_payload = read_json_object_from_regular_file(
            payload_path,
            max_bytes=MAX_SIDECAR_PAYLOAD_BYTES,
            description="sidecar payload",
        )
        if canonical_payload_sha256(exact_payload) != canonical_payload_sha256(
            payload
        ):
            return payload
        state = read_json_object_from_regular_file(
            sidecar_auth_state_path(payload_path),
            max_bytes=MAX_SIDECAR_AUTH_STATE_BYTES,
            description="sidecar authentication state",
        )
        unsigned = {
            "schema_version": state.get("schema_version"),
            "payload_sha256": state.get("payload_sha256"),
        }
        payload_sha256 = canonical_payload_sha256(exact_payload)
        separated_key = require_separate_key_file(
            payload_path,
            sidecar_auth_state_path(payload_path),
            key_file=key_file,
            key_env=ACCOUNT_SIDECAR_AUTH_KEY_FILE_ENV,
            conflicting_key_env=MARKET_SNAPSHOT_HMAC_KEY_FILE_ENV,
        )
        valid = (
            set(state)
            == {"schema_version", "payload_sha256", "hmac_sha256"}
            and unsigned["schema_version"] == SIDECAR_AUTH_STATE_SCHEMA_VERSION
            and unsigned["payload_sha256"] == payload_sha256
            and verify_mapping(
                unsigned,
                state.get("hmac_sha256"),
                domain=ACCOUNT_SIDECAR_AUTH_HMAC_DOMAIN,
                key_file=separated_key,
            )
        )
        if valid:
            return _AuthenticatedSidecarPayload(
                exact_payload,
                payload_sha256=payload_sha256,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return payload


def is_authenticated_sidecar_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, _AuthenticatedSidecarPayload):
        return False
    try:
        return payload.payload_sha256 == canonical_payload_sha256(dict(payload))
    except (TypeError, ValueError):
        return False


def authenticated_projection(
    payload: dict[str, Any],
    *,
    authenticated_source: dict[str, Any],
) -> dict[str, Any]:
    """Preserve a verified boundary marker across an internal normalization."""
    if not is_authenticated_sidecar_payload(authenticated_source):
        return payload
    return _AuthenticatedSidecarPayload(
        payload,
        payload_sha256=canonical_payload_sha256(payload),
    )


def require_separate_key_file(
    *protected_paths: str | Path,
    key_file: str | Path | None = None,
    key_env: str | None = None,
    conflicting_key_env: str | None = None,
) -> Path:
    """Require a domain-distinct key outside every sidecar output directory."""
    key_path = _configured_key_path(key_file, key_env=key_env)
    _reject_domain_key_alias(
        key_path,
        key_env=key_env,
        conflicting_key_env=conflicting_key_env,
    )
    for protected in protected_paths:
        output_directory = Path(protected).expanduser().resolve().parent
        if key_path == Path(protected).expanduser().resolve() or _is_relative_to(
            key_path,
            output_directory,
        ):
            raise SidecarAuthUnavailable(
                "sidecar HMAC key must be outside sidecar output directories"
            )
    return key_path


def _reject_domain_key_alias(
    selected_path: Path,
    *,
    key_env: str | None,
    conflicting_key_env: str | None,
) -> None:
    if not conflicting_key_env:
        return
    conflicting_value = os.environ.get(conflicting_key_env)
    if not conflicting_value:
        return
    conflict_path = Path(conflicting_value).expanduser().resolve()
    configured_value = os.environ.get(key_env) if key_env else None
    configured_path = (
        Path(configured_value).expanduser().resolve() if configured_value else None
    )
    aliases = _same_file(selected_path, conflict_path) or (
        configured_path is not None and _same_file(configured_path, conflict_path)
    )
    if aliases:
        raise SidecarAuthUnavailable(
            "account and market HMAC domains must use distinct key files"
        )


def _same_file(left: Path, right: Path) -> bool:
    if left == right:
        return True
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _read_key(
    key_file: str | Path | None,
    *,
    key_env: str | None = None,
) -> bytes:
    path = _configured_key_path(key_file, key_env=key_env)
    try:
        key = read_regular_file_bytes(
            path,
            max_bytes=SIDECAR_AUTH_KEY_BYTES,
            description="sidecar HMAC key file",
        )
    except OSError as exc:
        raise SidecarAuthUnavailable("sidecar HMAC key file is unavailable") from exc
    except ValueError as exc:
        raise SidecarAuthUnavailable(str(exc)) from exc
    if len(key) != SIDECAR_AUTH_KEY_BYTES:
        raise SidecarAuthUnavailable("sidecar HMAC key must contain exactly 32 bytes")
    return key


def _configured_key_path(
    key_file: str | Path | None,
    *,
    key_env: str | None = None,
) -> Path:
    configured = key_file or (os.environ.get(key_env) if key_env else None)
    if not configured:
        requirement = key_env or "key_file"
        raise SidecarAuthUnavailable(
            f"{requirement} must reference an operator-owned key file"
        )
    return Path(configured).expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return canonical_json_bytes(payload)


def _domain_separated_message(payload: dict[str, Any], *, domain: str) -> bytes:
    if domain not in _ALLOWED_HMAC_DOMAINS:
        raise ValueError("sidecar HMAC domain is not allowed")
    return domain.encode("ascii") + b"\x00" + _canonical_json(payload)
