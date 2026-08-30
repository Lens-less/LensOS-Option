"""Immutable storage for strategy history and forecast artifacts."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, unquote

from ._canonical import canonical_json_bytes
from .storage import atomic_write_text, read_json_object_from_regular_file
from .strategy_forecast import validate_strategy_forecast_artifact
from .strategy_history import validate_strategy_history_artifact

STRATEGY_ARTIFACT_POINTER_SCHEMA_VERSION: Final[str] = "strategy_artifact_pointer.v1"
HISTORY_NAMESPACE: Final[str] = "history"
FORECAST_NAMESPACE: Final[str] = "forecast"
SUPPORTED_NAMESPACES: Final[frozenset[str]] = frozenset(
    {HISTORY_NAMESPACE, FORECAST_NAMESPACE}
)
MAX_STRATEGY_ARTIFACT_BYTES: Final[int] = 64 * 1024 * 1024
MAX_POINTER_BYTES: Final[int] = 4096
_HISTORY_ARTIFACT_ID = re.compile(r"^strategy-history:[0-9a-f]{64}$")
_FORECAST_ARTIFACT_ID = re.compile(r"^strategy_forecast:[0-9a-f]{64}$")
_IMMUTABLE_WRITE_RETRY_DELAYS_SECONDS: Final[tuple[float, ...]] = (
    0.01,
    0.02,
    0.04,
    0.08,
)


class StrategyArtifactStoreCorrupt(ValueError):
    """Persisted strategy artifact state is missing or invalid."""


def store_strategy_history_artifact(
    root: str | Path,
    artifact: Any,
    *,
    update_active_pointer: bool = False,
) -> Path:
    """Persist one validated strategy-history artifact."""

    path = _store_artifact(
        root=root,
        namespace=HISTORY_NAMESPACE,
        artifact=artifact,
    )
    if update_active_pointer:
        set_active_strategy_history_artifact(root, str(artifact["artifact_id"]))
    return path


def store_strategy_forecast_artifact(
    root: str | Path,
    artifact: Any,
    *,
    update_active_pointer: bool = False,
) -> Path:
    """Persist one validated strategy-forecast artifact."""

    path = _store_artifact(
        root=root,
        namespace=FORECAST_NAMESPACE,
        artifact=artifact,
    )
    if update_active_pointer:
        set_active_strategy_forecast_artifact(root, str(artifact["artifact_id"]))
    return path


def load_strategy_history_artifact(
    root: str | Path,
    artifact_id: str,
) -> dict[str, Any]:
    """Load one validated strategy-history artifact by id."""

    return _load_artifact(root=root, namespace=HISTORY_NAMESPACE, artifact_id=artifact_id)


def load_strategy_forecast_artifact(
    root: str | Path,
    artifact_id: str,
) -> dict[str, Any]:
    """Load one validated strategy-forecast artifact by id."""

    return _load_artifact(root=root, namespace=FORECAST_NAMESPACE, artifact_id=artifact_id)


def set_active_strategy_history_artifact(root: str | Path, artifact_id: str) -> Path:
    """Atomically point the history namespace at one already-validated artifact."""

    return _set_active_pointer(root=root, namespace=HISTORY_NAMESPACE, artifact_id=artifact_id)


def set_active_strategy_forecast_artifact(root: str | Path, artifact_id: str) -> Path:
    """Atomically point the forecast namespace at one already-validated artifact."""

    return _set_active_pointer(root=root, namespace=FORECAST_NAMESPACE, artifact_id=artifact_id)


def load_active_strategy_history_artifact(root: str | Path) -> dict[str, Any]:
    """Load the validated history artifact referenced by the active pointer."""

    return _load_active_artifact(root=root, namespace=HISTORY_NAMESPACE)


def load_active_strategy_forecast_artifact(root: str | Path) -> dict[str, Any]:
    """Load the validated forecast artifact referenced by the active pointer."""

    return _load_active_artifact(root=root, namespace=FORECAST_NAMESPACE)


def _store_artifact(
    *,
    root: str | Path,
    namespace: str,
    artifact: Any,
) -> Path:
    directory = _namespace_directory(root, namespace, create=True)
    normalized = _validated_artifact(namespace, artifact)
    artifact_id = str(normalized["artifact_id"])
    target = directory / f"{_encoded_artifact_filename(namespace, artifact_id)}.json"
    _ensure_contained_path(target.parent, directory, label=f"strategy {namespace} artifact")
    payload = canonical_json_bytes(normalized)
    return _write_immutable_artifact(
        target=target,
        payload=payload,
        max_bytes=MAX_STRATEGY_ARTIFACT_BYTES,
        description=f"strategy {namespace} artifact {target.name}",
        artifact_id=artifact_id,
    )


def _load_artifact(
    *,
    root: str | Path,
    namespace: str,
    artifact_id: str,
) -> dict[str, Any]:
    validated_id = _validate_artifact_id(namespace, artifact_id)
    path = _artifact_path(root=root, namespace=namespace, artifact_id=validated_id)
    artifact = _read_json_file(
        path,
        max_bytes=MAX_STRATEGY_ARTIFACT_BYTES,
        description=f"strategy {namespace} artifact {path.name}",
    )
    try:
        validated = _validated_artifact(namespace, artifact)
    except ValueError as exc:
        raise StrategyArtifactStoreCorrupt(
            f"strategy {namespace} artifact {path.name} is invalid"
        ) from exc
    if validated["artifact_id"] != validated_id:
        raise StrategyArtifactStoreCorrupt(
            f"strategy {namespace} artifact id does not match {validated_id}"
        )
    return validated


def _set_active_pointer(
    *,
    root: str | Path,
    namespace: str,
    artifact_id: str,
) -> Path:
    validated_id = _validate_artifact_id(namespace, artifact_id)
    _load_artifact(root=root, namespace=namespace, artifact_id=validated_id)
    pointer = {
        "schema_version": STRATEGY_ARTIFACT_POINTER_SCHEMA_VERSION,
        "namespace": namespace,
        "artifact_id": validated_id,
    }
    path = _pointer_path(root=root, namespace=namespace)
    atomic_write_text(path, canonical_json_bytes(pointer).decode("utf-8"))
    return path


def _load_active_artifact(
    *,
    root: str | Path,
    namespace: str,
) -> dict[str, Any]:
    pointer = _read_pointer(root=root, namespace=namespace)
    return _load_artifact(
        root=root,
        namespace=namespace,
        artifact_id=str(pointer["artifact_id"]),
    )


def _read_pointer(*, root: str | Path, namespace: str) -> dict[str, Any]:
    path = _pointer_path(root=root, namespace=namespace)
    pointer = _read_json_file(
        path,
        max_bytes=MAX_POINTER_BYTES,
        description=f"strategy {namespace} pointer",
    )
    if pointer.get("schema_version") != STRATEGY_ARTIFACT_POINTER_SCHEMA_VERSION:
        raise StrategyArtifactStoreCorrupt("strategy artifact pointer schema is invalid")
    if pointer.get("namespace") != namespace:
        raise StrategyArtifactStoreCorrupt("strategy artifact pointer namespace is invalid")
    artifact_id = pointer.get("artifact_id")
    if not isinstance(artifact_id, str):
        raise StrategyArtifactStoreCorrupt("strategy artifact pointer id is invalid")
    _validate_artifact_id(namespace, artifact_id)
    return pointer


def _validated_artifact(namespace: str, artifact: Any) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        raise ValueError(f"strategy {namespace} artifact must be a dict")
    errors = _artifact_validator(namespace)(artifact)
    if errors:
        raise ValueError("; ".join(errors))
    artifact_id = artifact.get("artifact_id")
    if not isinstance(artifact_id, str):
        raise ValueError(f"strategy {namespace} artifact_id must be present")
    _validate_artifact_id(namespace, artifact_id)
    return artifact


def _artifact_validator(namespace: str):
    if namespace == HISTORY_NAMESPACE:
        return validate_strategy_history_artifact
    if namespace == FORECAST_NAMESPACE:
        return validate_strategy_forecast_artifact
    raise ValueError(f"unsupported strategy artifact namespace: {namespace!r}")


def _artifact_path(
    *,
    root: str | Path,
    namespace: str,
    artifact_id: str,
) -> Path:
    directory = _namespace_directory(root, namespace, create=False)
    return directory / f"{_encoded_artifact_filename(namespace, artifact_id)}.json"


def _pointer_path(*, root: str | Path, namespace: str) -> Path:
    directory = _namespace_directory(root, namespace, create=True)
    return directory / "active.json"


def _namespace_directory(root: str | Path, namespace: str, *, create: bool) -> Path:
    if namespace not in SUPPORTED_NAMESPACES:
        raise ValueError(f"unsupported strategy artifact namespace: {namespace!r}")
    root_path = _absolute_path(root)
    _reject_symlink_path(root_path)
    if create:
        root_path.mkdir(parents=True, exist_ok=True)
    resolved_root = root_path.resolve(strict=False)
    _reject_symlink_path(resolved_root)
    if not resolved_root.is_dir():
        raise FileNotFoundError("strategy artifact root directory not found")
    directory = root_path / namespace
    _reject_symlink_path(directory)
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    resolved_directory = directory.resolve(strict=False)
    _reject_symlink_path(resolved_directory)
    if not resolved_directory.is_dir():
        raise FileNotFoundError(f"strategy artifact namespace directory not found: {namespace}")
    _ensure_contained_path(
        resolved_directory,
        resolved_root,
        label=f"strategy {namespace} namespace",
    )
    return resolved_directory


def _encoded_artifact_filename(namespace: str, artifact_id: str) -> str:
    validated_id = _validate_artifact_id(namespace, artifact_id)
    encoded = quote(validated_id, safe="")
    if unquote(encoded) != validated_id:
        raise ValueError(f"strategy {namespace} artifact id cannot be encoded safely")
    return encoded


def _validate_artifact_id(namespace: str, artifact_id: str) -> str:
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ValueError(f"strategy {namespace} artifact_id must be a non-empty string")
    pattern = (
        _HISTORY_ARTIFACT_ID if namespace == HISTORY_NAMESPACE else _FORECAST_ARTIFACT_ID
    )
    if pattern.fullmatch(artifact_id) is None:
        raise ValueError(f"strategy {namespace} artifact_id is invalid")
    return artifact_id


def _read_json_file(
    path: Path,
    *,
    max_bytes: int,
    description: str,
) -> dict[str, Any]:
    _reject_symlink_path(path)
    try:
        return read_json_object_from_regular_file(
            path,
            max_bytes=max_bytes,
            description=description,
        )
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise StrategyArtifactStoreCorrupt(f"{description} is invalid") from exc
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise StrategyArtifactStoreCorrupt(f"{description} is invalid") from exc


def _read_regular_bytes(
    path: Path,
    *,
    max_bytes: int,
    description: str,
) -> bytes:
    _reject_symlink_path(path)
    candidate = path.expanduser().resolve()
    try:
        with candidate.open("rb") as handle:
            mode = os.fstat(handle.fileno()).st_mode
            if not stat.S_ISREG(mode):
                raise StrategyArtifactStoreCorrupt(
                    f"{description} must be a regular file"
                )
            payload = handle.read(max_bytes + 1)
    except OSError as exc:
        raise StrategyArtifactStoreCorrupt(f"{description} is invalid") from exc
    if len(payload) > max_bytes:
        raise StrategyArtifactStoreCorrupt(f"{description} exceeds {max_bytes} bytes")
    return payload


def _reject_symlink_path(path: Path) -> None:
    try:
        if path.is_symlink():
            raise StrategyArtifactStoreCorrupt(f"{path.name or path} must not be a symlink")
    except OSError as exc:
        raise StrategyArtifactStoreCorrupt(f"{path.name or path} is inaccessible") from exc


def _absolute_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate


def _ensure_contained_path(path: Path, root: Path, *, label: str) -> None:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise StrategyArtifactStoreCorrupt(f"{label} escapes its namespace root") from exc


def _write_immutable_artifact(
    *,
    target: Path,
    payload: bytes,
    max_bytes: int,
    description: str,
    artifact_id: str,
) -> Path:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor: int | None = None
    try:
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return target
    except FileExistsError:
        return _await_existing_immutable_artifact(
            target=target,
            payload=payload,
            max_bytes=max_bytes,
            description=description,
            artifact_id=artifact_id,
        )
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(OSError):
            target.unlink(missing_ok=True)
        raise StrategyArtifactStoreCorrupt(f"{description} is invalid") from exc
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(OSError):
            target.unlink(missing_ok=True)
        raise


def _await_existing_immutable_artifact(
    *,
    target: Path,
    payload: bytes,
    max_bytes: int,
    description: str,
    artifact_id: str,
) -> Path:
    for attempt, delay in enumerate((*_IMMUTABLE_WRITE_RETRY_DELAYS_SECONDS, 0.0)):
        try:
            existing = _read_regular_bytes(
                target,
                max_bytes=max_bytes,
                description=description,
            )
        except (FileNotFoundError, StrategyArtifactStoreCorrupt):
            if attempt == len(_IMMUTABLE_WRITE_RETRY_DELAYS_SECONDS):
                raise
        else:
            if existing == payload:
                return target
            if attempt == len(_IMMUTABLE_WRITE_RETRY_DELAYS_SECONDS):
                raise StrategyArtifactStoreCorrupt(
                    f"strategy artifact content does not match {artifact_id}"
                )
        if delay > 0.0:
            time.sleep(delay)
    raise StrategyArtifactStoreCorrupt(
        f"strategy artifact content does not match {artifact_id}"
    )
