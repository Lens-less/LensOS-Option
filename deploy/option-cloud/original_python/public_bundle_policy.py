"""Single fail-closed policy source for public bundle privacy scanners."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Any

_SCHEMA_VERSION = "public_bundle_forbidden_tokens.v1"
_TOKEN_RE = re.compile(r"^[a-z0-9_+=-]+$")


@lru_cache(maxsize=1)
def forbidden_bundle_tokens() -> frozenset[str]:
    """Load and validate the shared public-bundle deny vocabulary."""
    resource = files("crypto_options_report").joinpath(
        "resources/public_bundle_forbidden_tokens.json"
    )
    try:
        payload: Any = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("public bundle privacy policy could not be loaded") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "tokens"}:
        raise RuntimeError("public bundle privacy policy has an invalid root contract")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise RuntimeError("public bundle privacy policy schema is unsupported")
    tokens = payload.get("tokens")
    if not isinstance(tokens, list) or not tokens:
        raise RuntimeError("public bundle privacy policy tokens must be a non-empty list")
    if any(
        not isinstance(token, str)
        or _TOKEN_RE.fullmatch(token) is None
        or token != token.lower()
        for token in tokens
    ):
        raise RuntimeError("public bundle privacy policy contains an invalid token")
    if tokens != sorted(set(tokens)):
        raise RuntimeError("public bundle privacy policy tokens must be sorted and unique")
    return frozenset(tokens)
