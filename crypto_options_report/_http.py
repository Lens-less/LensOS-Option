"""Shared fail-closed HTTP helpers for bounded public JSON reads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .storage import read_json_object_from_stream


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = build_opener(_RejectRedirects())


def no_redirect_urlopen(request: Request, *, timeout: int):
    """Open one request without following a redirect to a different boundary."""
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


JsonOpener = Callable[..., Any]


def _get_json(
    url: str,
    params: Mapping[str, Any],
    timeout: int,
    *,
    max_bytes: int,
    description: str,
    opener: JsonOpener = no_redirect_urlopen,
) -> dict[str, Any]:
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": "codex-option-research/0.1",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            return read_json_object_from_stream(
                response,
                max_bytes=max_bytes,
                description=description,
            )
    except HTTPError as exc:
        raise ValueError(f"http {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise ValueError(f"network error: {exc.reason}") from exc


def json_getter(
    *,
    max_bytes: int,
    description: str,
    opener: JsonOpener = no_redirect_urlopen,
) -> Callable[[str, Mapping[str, Any], int], dict[str, Any]]:
    """Bind one module's response contract while keeping its patchable seam."""

    def configured_get_json(
        url: str,
        params: Mapping[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        return _get_json(
            url,
            params,
            timeout,
            max_bytes=max_bytes,
            description=description,
            opener=opener,
        )

    return configured_get_json
