"""Canonical, fail-closed validation for formal public-site origins."""

from __future__ import annotations

import re
from ipaddress import ip_address
from urllib.parse import urlsplit

_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SPECIAL_USE_SUFFIXES = (
    "alt",
    "arpa",
    "example",
    "internal",
    "invalid",
    "local",
    "localhost",
    "onion",
    "test",
)
_EXAMPLE_DOMAINS = ("example.com", "example.net", "example.org")


def validate_public_site_origin(value: str) -> str:
    """Return a normalized HTTPS origin or reject non-final host metadata."""
    text = str(value).strip()
    if not text:
        raise ValueError("site_origin is required")
    parsed = urlsplit(text)
    if parsed.scheme.lower() != "https" or parsed.hostname is None:
        raise ValueError("site_origin must be an absolute HTTPS origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("site_origin must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("site_origin must not contain a path, query, or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("site_origin contains an invalid port") from exc
    if port not in {None, 443}:
        raise ValueError("site_origin must use the default HTTPS port")
    raw_host = parsed.hostname
    if raw_host.endswith("."):
        raise ValueError("site_origin must not use a trailing DNS root label")
    try:
        host = raw_host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("site_origin contains an invalid DNS host") from exc
    if _is_reserved_or_non_public_host(host):
        raise ValueError("site_origin must name a final public DNS host")
    return f"https://{host}"


def _is_reserved_or_non_public_host(host: str) -> bool:
    if "." not in host or len(host) > 253:
        return True
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        return True
    labels = host.split(".")
    if any(_DNS_LABEL_RE.fullmatch(label) is None for label in labels):
        return True
    top_level = labels[-1]
    if not top_level.startswith("xn--") and (
        len(top_level) < 2 or not top_level.isalpha()
    ):
        return True
    if any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _SPECIAL_USE_SUFFIXES
    ):
        return True
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in _EXAMPLE_DOMAINS
    )
