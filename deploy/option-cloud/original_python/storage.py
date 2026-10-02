"""Small crash-safe persistence primitives for operator-owned JSON artifacts."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, BinaryIO

_REPLACE_RETRY_DELAYS_SECONDS = (0.01, 0.02, 0.04)


def read_regular_file_bytes(
    path: str | os.PathLike[str],
    *,
    max_bytes: int,
    description: str,
) -> bytes:
    """Read one bounded regular file without a stat/open race."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    candidate = Path(path).expanduser().resolve()
    with candidate.open("rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError(f"{description} must be a regular file")
        return read_stream_bytes_bounded(
            handle,
            max_bytes=max_bytes,
            description=description,
        )


def read_json_object_from_regular_file(
    path: str | os.PathLike[str],
    *,
    max_bytes: int,
    description: str,
) -> dict[str, Any]:
    raw = read_regular_file_bytes(
        path,
        max_bytes=max_bytes,
        description=description,
    )
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must be a JSON object")
    return payload


def read_json_object_from_stream(
    stream: BinaryIO,
    *,
    max_bytes: int,
    description: str,
) -> dict[str, Any]:
    raw = read_stream_bytes_bounded(
        stream,
        max_bytes=max_bytes,
        description=description,
    )
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must be a JSON object")
    return payload


def read_stream_bytes_bounded(
    stream: BinaryIO,
    *,
    max_bytes: int,
    description: str,
) -> bytes:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    raw = stream.read(max_bytes + 1)
    if not isinstance(raw, bytes):
        raise ValueError(f"{description} did not return bytes")
    if len(raw) > max_bytes:
        raise ValueError(f"{description} exceeds {max_bytes} bytes")
    return raw


def atomic_write_json(
    path: str | os.PathLike[str],
    value: Any,
    *,
    trailing_newline: bool = True,
) -> Path:
    payload = json.dumps(value, indent=2, sort_keys=True)
    if trailing_newline:
        payload += "\n"
    return atomic_write_text(path, payload)


def atomic_write_text(path: str | os.PathLike[str], payload: str) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    else:
        target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(len(_REPLACE_RETRY_DELAYS_SECONDS) + 1):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            transient = isinstance(exc, PermissionError) or (
                os.name == "nt" and winerror in {5, 32, 33}
            )
            if not transient or attempt == len(_REPLACE_RETRY_DELAYS_SECONDS):
                raise
            time.sleep(_REPLACE_RETRY_DELAYS_SECONDS[attempt])
