"""Small crash-safe persistence primitives for operator-owned JSON artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


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
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
