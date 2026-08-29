#!/usr/bin/env python3
"""Rehearse the one-time public history rewrite in an isolated mirror.

The source repository is read-only. The tool creates a private archive, rewrites
an isolated copy, exports only ``refs/heads/main`` to the public bundle, and
never pushes. Existing output directories are rejected and retained on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from email.utils import parseaddr
from pathlib import Path
from typing import Any, NamedTuple

FILTER_REPO_VERSION = "2.47.0"
FILTER_REPO_BUILD_ID = "a40bce548d2c"
PUBLIC_REF = "refs/heads/main"
CUTOVER_TARGETS = ("existing-repository", "new-repository")
STATIC_BUNDLE_PATTERN = re.compile(
    r"^crypto_options_report/static/evidence/assets/index-[^/]+\.(?:css|js)$"
)
BASE_REMOVED_PATHS = (
    ".workflow/",
    "docs/automation/",
    "issues/",
    "tools/options_coordination.py",
    "tools/options_coordination_v2/",
    "tests/test_options_platform_controller_contract.py",
    "tests/test_options_platform_coordination_git_v2.py",
    "tests/test_options_platform_coordination_migration_v2.py",
    "tests/test_options_platform_coordination_v2.py",
    "tests/test_options_platform_cutover_v2.py",
    "tests/test_options_platform_machine_v2.py",
    "tests/test_options_platform_manifest_conversion_v2.py",
    "tests/test_options_platform_projection_v2.py",
    "tests/test_options_platform_remote_cli_v2.py",
)
PRIVATE_ENVIRONMENT_VARIABLES = {
    "private_user_id": "LENSOS_HISTORY_REWRITE_PRIVATE_USER_ID",
    "private_author_id": "LENSOS_HISTORY_REWRITE_PRIVATE_AUTHOR_ID",
    "private_email": "LENSOS_HISTORY_REWRITE_PRIVATE_EMAIL",
    "private_name": "LENSOS_HISTORY_REWRITE_PRIVATE_NAME",
}
PRIVATE_TOKEN_LABELS = tuple(PRIVATE_ENVIRONMENT_VARIABLES)
ALLOWED_BOT_IDENTITIES = {
    "dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>",
    "GitHub <noreply@github.com>",
}


class RewriteError(RuntimeError):
    """Expected fail-closed rehearsal error."""


class PrivateIdentity(NamedTuple):
    private_user_id: str
    private_author_id: str
    private_email: str
    private_name: str

    def items(self) -> tuple[tuple[str, str], ...]:
        return (
            ("private_user_id", self.private_user_id),
            ("private_author_id", self.private_author_id),
            ("private_email", self.private_email),
            ("private_name", self.private_name),
        )

    def token_values(self) -> tuple[str, ...]:
        return tuple(value for _label, value in self.items())


def _private_identity_from_values(
    *, private_user_id: str, private_author_id: str, private_email: str, private_name: str
) -> PrivateIdentity:
    values = {
        "private_user_id": private_user_id.strip(),
        "private_author_id": private_author_id.strip(),
        "private_email": private_email.strip(),
        "private_name": private_name.strip(),
    }
    if any(not value for value in values.values()):
        raise RewriteError("private identity values must be non-empty")
    if any("\n" in value or "\r" in value for value in values.values()):
        raise RewriteError("private identity values must be single-line")
    parsed_name, parsed_email = parseaddr(values["private_email"])
    if parsed_name or parsed_email != values["private_email"] or "@" not in values["private_email"]:
        raise RewriteError("private email must be one bare valid address")
    return PrivateIdentity(**values)


def _load_private_identity(env: dict[str, str] | None = None) -> PrivateIdentity:
    environment = os.environ if env is None else env
    values = {
        label: environment.get(variable, "")
        for label, variable in PRIVATE_ENVIRONMENT_VARIABLES.items()
    }
    present = [label for label, value in values.items() if value.strip()]
    if len(present) != len(values):
        required = ", ".join(PRIVATE_ENVIRONMENT_VARIABLES.values())
        raise RewriteError(
            "private identity environment is incomplete; set all four variables: "
            + required
        )
    return _private_identity_from_values(**values)


def _run(
    arguments: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    accepted: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(argument) for argument in arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode not in accepted:
        command = " ".join(str(argument) for argument in arguments)
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RewriteError(f"command failed ({completed.returncode}): {command}\n{detail}")
    return completed


def _git(source: Path, *arguments: str, accepted: tuple[int, ...] = (0,)) -> str:
    return _run(["git", "-C", source, *arguments], accepted=accepted).stdout.strip()


def _repository_root(source: Path) -> Path:
    source = source.resolve()
    root = Path(_git(source, "rev-parse", "--show-toplevel")).resolve()
    if root != source:
        raise RewriteError(f"--source must be the git top-level: {root}")
    return root


def _validate_identity(
    name: str, email: str, mode: str, private_identity: PrivateIdentity
) -> tuple[str, str]:
    name = name.strip()
    email = email.strip()
    parsed_name, parsed_email = parseaddr(email)
    if parsed_name or parsed_email != email or "@" not in email:
        raise RewriteError("public author email must be one bare valid address")
    if not name or "\n" in name or "\r" in name:
        raise RewriteError("public author name must be non-empty and single-line")
    identity = f"{name}\n{email}".casefold()
    if any(token.casefold() in identity for token in private_identity.token_values()):
        raise RewriteError("public identity must not contain a private identity token")
    domain = email.rsplit("@", 1)[1].casefold()
    placeholder = (
        domain.endswith((".invalid", ".example", ".test"))
        or domain in {"example.com", "example.net", "example.org"}
    )
    if mode == "final" and placeholder:
        raise RewriteError("final identity must not use a placeholder domain")
    if mode == "final" and "rehearsal" in name.casefold():
        raise RewriteError("final identity must not be labelled as a rehearsal")
    return name, email


def _all_historical_paths(source: Path) -> list[str]:
    output = _git(source, "log", "--all", "--name-only", "--pretty=format:")
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


def _tree_manifest(source: Path, revision: str = "HEAD") -> dict[str, str]:
    output = _git(source, "ls-tree", "-r", revision)
    manifest: dict[str, str] = {}
    for line in output.splitlines():
        metadata, path = line.split("\t", 1)
        _mode, object_type, object_id = metadata.split()
        if object_type == "blob":
            manifest[path] = object_id
    return manifest


def _current_static_assets(source: Path) -> dict[str, str]:
    manifest = _tree_manifest(source)
    return {
        path: object_id
        for path, object_id in sorted(manifest.items())
        if STATIC_BUNDLE_PATTERN.fullmatch(path)
    }


def _source_sync_state(source: Path) -> dict[str, Any]:
    head = _git(source, "rev-parse", "HEAD")
    remote = _run(
        ["git", "-C", source, "rev-parse", "--verify", "refs/remotes/origin/main"],
        accepted=(0, 128),
    )
    origin_main = remote.stdout.strip() if remote.returncode == 0 else None
    return {
        "head": head,
        "origin_main": origin_main,
        "head_equals_origin_main": head == origin_main,
    }


def _live_origin_main(source: Path) -> str:
    output = _run(
        ["git", "-C", source, "ls-remote", "--refs", "origin", PUBLIC_REF]
    ).stdout
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RewriteError("live origin/main is missing or ambiguous")
    fields = lines[0].split("\t", 1)
    if len(fields) != 2 or fields[1] != PUBLIC_REF:
        raise RewriteError("live origin/main response is invalid")
    return fields[0]


def _assert_final_source_sync(source: Path) -> str:
    head = _git(source, "rev-parse", "HEAD")
    live_origin_main = _live_origin_main(source)
    if head != live_origin_main:
        raise RewriteError(
            "final rewrite requires HEAD to equal live origin/main, not only the "
            "cached remote-tracking ref"
        )
    return live_origin_main


def build_plan(
    source: Path,
    *,
    name: str,
    email: str,
    mode: str,
    cutover_target: str,
    private_identity: PrivateIdentity,
) -> dict[str, Any]:
    source = _repository_root(source)
    current_assets = _current_static_assets(source)
    if len(current_assets) != 2 or {Path(path).suffix for path in current_assets} != {
        ".css",
        ".js",
    }:
        raise RewriteError("HEAD must contain exactly one hash-named CSS and JS asset")
    head_manifest = _tree_manifest(source)
    index_path = "crypto_options_report/static/evidence/index.html"
    if index_path not in head_manifest:
        raise RewriteError("HEAD is missing the static evidence index")
    index_html = _git(source, "show", f"HEAD:{index_path}")
    missing_references = [
        Path(path).name for path in current_assets if Path(path).name not in index_html
    ]
    if missing_references:
        raise RewriteError(f"static index does not reference current assets: {missing_references}")
    historical_assets = sorted(
        path
        for path in _all_historical_paths(source)
        if STATIC_BUNDLE_PATTERN.fullmatch(path)
    )
    removed_paths = list(BASE_REMOVED_PATHS)
    removed_paths.extend(path for path in historical_assets if path not in current_assets)
    sync = _source_sync_state(source)
    return {
        "schema_version": "public_history_rewrite_plan.v1",
        "status": "planned",
        "source_repository": str(source),
        "source_head": sync["head"],
        "source_ref_count": len(
            _git(source, "for-each-ref", "--format=%(refname)").splitlines()
        ),
        "source_sync": sync,
        "identity_mode": mode,
        "cutover_target": cutover_target,
        "public_author": {"name": name, "email": email},
        "filter_repo_version": FILTER_REPO_VERSION,
        "filter_repo_build_id": FILTER_REPO_BUILD_ID,
        "sensitive_data_removal_mode": True,
        "removed_paths": sorted(set(removed_paths)),
        "retained_static_bundles": sorted(current_assets),
        "retained_static_assets": current_assets,
        "retained_index": {"path": index_path, "oid": head_manifest[index_path]},
        "replacement_marker_categories": list(PRIVATE_TOKEN_LABELS),
        "replacement_marker_count": len(private_identity.token_values()),
        "public_ref_allowlist": [PUBLIC_REF],
        "remote_pr_refs_checked": False,
        "private_archive_required": True,
        "source_mutation_allowed": False,
        "push_allowed": False,
        "signature_preservation_expected": False,
    }


def _write_filter_inputs(
    output_root: Path, *, name: str, email: str, private_identity: PrivateIdentity
) -> tuple[Path, Path]:
    replacements = output_root / "replace-text.txt"
    home_pattern = (
        r"regex:(?i)/?C:[\\/]+Users[\\/]+" + private_identity.private_user_id
        + "==><LOCAL_USER_HOME>"
    )
    replacements.write_text(
        "\n".join(
            (
                home_pattern,
                f"literal:{private_identity.private_email}==>{email}",
                f"literal:{private_identity.private_author_id}==><REDACTED_AUTHOR_ID>",
                f"literal:{private_identity.private_name}==>{name}",
                f"literal:{private_identity.private_user_id}==><LOCAL_USER_ID>",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    mailmap = output_root / "rewrite.mailmap"
    mailmap.write_text(
        f"{name} <{email}> <{private_identity.private_email}>\n", encoding="utf-8"
    )
    return replacements, mailmap


def _verify_filter_repo(executable: Path) -> None:
    if not executable.is_file():
        raise RewriteError(f"git-filter-repo executable does not exist: {executable}")
    build_id = _run([executable, "--version"]).stdout.strip()
    if build_id != FILTER_REPO_BUILD_ID:
        raise RewriteError(
            "git-filter-repo build mismatch: expected "
            f"{FILTER_REPO_VERSION} ({FILTER_REPO_BUILD_ID}), got {build_id or '<empty>'}"
        )


def _path_is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _assert_output_target(source: Path, output_root: Path) -> Path:
    output_root = output_root.resolve()
    if output_root.exists():
        raise RewriteError(f"output root already exists: {output_root}")
    if _path_is_within(output_root, source) or _path_is_within(source, output_root):
        raise RewriteError("output root and source repository must not contain each other")
    if not output_root.parent.is_dir():
        raise RewriteError(f"output parent is not a directory: {output_root.parent}")
    return output_root


def _origin_url(source: Path) -> str:
    url = _git(source, "remote", "get-url", "origin")
    if not url:
        raise RewriteError("origin remote is required for PR-ref inventory")
    return url


def _remote_pr_refs(source: Path) -> dict[str, str]:
    output = _run(
        ["git", "-C", source, "ls-remote", "--refs", "origin", "refs/pull/*/head"]
    )
    return {
        ref: object_id
        for line in output.stdout.splitlines()
        if line.strip()
        for object_id, ref in [line.split("\t", 1)]
    }


def _copy_filter_report(mirror: Path, output_root: Path, name: str) -> str | None:
    candidates = (
        mirror / "filter-repo" / name,
        mirror / ".git" / "filter-repo" / name,
    )
    source = next((candidate for candidate in candidates if candidate.is_file()), None)
    if source is None:
        return None
    destination = output_root / name
    shutil.copyfile(source, destination)
    return str(destination)


def _registered_token_hits(
    payload: bytes, private_identity: PrivateIdentity
) -> list[dict[str, str]]:
    decoded_payloads = {
        "utf-8": (payload.decode("utf-8", errors="ignore").casefold(),),
        "utf-16-le": tuple(
            payload[offset:].decode("utf-16-le", errors="ignore").casefold()
            for offset in (0, 1)
        ),
        "utf-16-be": tuple(
            payload[offset:].decode("utf-16-be", errors="ignore").casefold()
            for offset in (0, 1)
        ),
    }
    hits: list[dict[str, str]] = []
    for category, token in private_identity.items():
        marker = token.casefold()
        for encoding, decoded_views in decoded_payloads.items():
            if any(marker in decoded_view for decoded_view in decoded_views):
                hits.append({"category": category, "encoding": encoding})
    return hits


def _text_token_categories(text: str, private_identity: PrivateIdentity) -> list[str]:
    lowered_text = text.casefold()
    return [
        category
        for category, token in private_identity.items()
        if token.casefold() in lowered_text
    ]


def _reachable_blob_ids(mirror: Path) -> list[str]:
    object_ids = sorted(
        {
            line.split(" ", 1)[0]
            for line in _git(mirror, "rev-list", "--objects", "--all").splitlines()
            if line.strip()
        }
    )
    if not object_ids:
        return []
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(mirror),
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
        ],
        input="\n".join(object_ids) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RewriteError(
            "git cat-file batch-check failed: "
            + (completed.stderr.strip() or "unknown error")
        )
    blobs = []
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == "blob":
            blobs.append(fields[0])
    return blobs


def _scan_reachable_blob_tokens(
    mirror: Path, private_identity: PrivateIdentity
) -> list[dict[str, str]]:
    blob_ids = _reachable_blob_ids(mirror)
    if not blob_ids:
        return []
    completed = subprocess.run(
        ["git", "-C", str(mirror), "cat-file", "--batch"],
        input=("\n".join(blob_ids) + "\n").encode(),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RewriteError(f"git cat-file blob scan failed: {detail or 'unknown error'}")
    output = completed.stdout
    cursor = 0
    findings: list[dict[str, str]] = []
    for expected_oid in blob_ids:
        header_end = output.find(b"\n", cursor)
        if header_end < 0:
            raise RewriteError("git cat-file blob scan returned a truncated header")
        header = output[cursor:header_end].decode("ascii", errors="strict").split()
        if len(header) != 3 or header[0] != expected_oid or header[1] != "blob":
            raise RewriteError("git cat-file blob scan returned an unexpected object")
        size = int(header[2])
        payload_start = header_end + 1
        payload_end = payload_start + size
        if payload_end >= len(output) or output[payload_end : payload_end + 1] != b"\n":
            raise RewriteError("git cat-file blob scan returned truncated content")
        for hit in _registered_token_hits(
            output[payload_start:payload_end], private_identity
        ):
            findings.append({"object_id": expected_oid, **hit})
        cursor = payload_end + 1
    if cursor != len(output):
        raise RewriteError("git cat-file blob scan returned trailing data")
    return findings


def _verify_rewritten_history(
    mirror: Path,
    *,
    plan: dict[str, Any],
    name: str,
    email: str,
    private_identity: PrivateIdentity,
) -> dict[str, Any]:
    historical_paths = set(_all_historical_paths(mirror))
    path_violations = [
        path
        for path in historical_paths
        if any(
            path == removed.rstrip("/") or path.startswith(removed)
            for removed in plan["removed_paths"]
        )
    ]
    if path_violations:
        raise RewriteError(f"removed paths remain in rewritten history: {path_violations[:5]}")
    private_paths = [
        path
        for path in historical_paths
        if _text_token_categories(path, private_identity)
    ]
    if private_paths:
        categories = _text_token_categories(private_paths[0], private_identity)
        raise RewriteError(
            "private token category remains in rewritten pathname: "
            + ",".join(categories)
        )

    rewritten_manifest = _tree_manifest(mirror)
    source_manifest = _tree_manifest(Path(plan["source_repository"]))
    if rewritten_manifest != source_manifest:
        changed = sorted(set(rewritten_manifest) ^ set(source_manifest))
        changed.extend(
            path
            for path in set(rewritten_manifest) & set(source_manifest)
            if rewritten_manifest[path] != source_manifest[path]
        )
        raise RewriteError(f"rewritten HEAD blob manifest changed unexpectedly: {changed[:5]}")
    rewritten_assets = _current_static_assets(mirror)
    if rewritten_assets != plan["retained_static_assets"]:
        raise RewriteError("rewritten HEAD did not preserve static asset paths and OIDs")

    revisions = _git(mirror, "rev-list", "--all").splitlines()
    content_hits = _scan_reachable_blob_tokens(mirror, private_identity)
    if content_hits:
        raise RewriteError(
            "private token category remains in rewritten blob: "
            + json.dumps(content_hits[0], sort_keys=True)
        )

    messages = _git(mirror, "log", "--all", "--format=%B")
    tag_messages = _git(mirror, "for-each-ref", "refs/tags", "--format=%(contents)")
    all_messages = f"{messages}\n{tag_messages}".casefold()
    message_hits = _text_token_categories(all_messages, private_identity)
    if message_hits:
        raise RewriteError(
            "private token categories remain in commit/tag messages: "
            + ",".join(message_hits)
        )

    # Lowercase placeholders are deliberately raw; uppercase variants apply mailmap.
    identity_lines = _git(
        mirror, "log", "--all", "--format=%an <%ae>%n%cn <%ce>"
    ).splitlines()
    tagger_lines = _git(
        mirror, "for-each-ref", "refs/tags", "--format=%(taggername) <%(taggeremail)>"
    ).splitlines()
    identities = sorted(
        {line.strip() for line in identity_lines + tagger_lines if line.strip() != "<>"}
    )
    expected_identity = f"{name} <{email}>"
    unexpected = sorted(set(identities) - ALLOWED_BOT_IDENTITIES - {expected_identity})
    if unexpected:
        raise RewriteError(f"unexpected raw identities remain: {unexpected}")

    _git(mirror, "fsck", "--full", "--no-dangling")
    return {
        "removed_path_count": len(plan["removed_paths"]),
        "rewritten_commit_count": len(revisions),
        "rewritten_raw_identities": identities,
        "private_content_hits": 0,
        "private_path_hits": 0,
        "private_message_hits": 0,
        "head_blob_manifest_unchanged": True,
        "retained_static_assets": rewritten_assets,
        "git_fsck": "passed",
    }


def rehearse(
    plan: dict[str, Any],
    *,
    source: Path,
    output_root: Path,
    filter_repo: Path,
    name: str,
    email: str,
    private_identity: PrivateIdentity,
) -> dict[str, Any]:
    source = _repository_root(source)
    if _git(source, "status", "--porcelain", "--untracked-files=all"):
        raise RewriteError("source repository must be clean before a rewrite rehearsal")
    output_root = _assert_output_target(source, output_root)
    _verify_filter_repo(filter_repo)
    remote_pr_refs = _remote_pr_refs(source)
    live_origin_main = None
    if plan["identity_mode"] == "final":
        live_origin_main = _assert_final_source_sync(source)
        plan["source_sync"]["live_origin_main"] = live_origin_main
        plan["source_sync"]["head_equals_live_origin_main"] = True
    if (
        plan["identity_mode"] == "final"
        and plan["cutover_target"] == "existing-repository"
        and remote_pr_refs
    ):
        raise RewriteError(
            "final rewrite for the existing repository cannot proceed while GitHub "
            "read-only PR refs retain old history; use the new-repository target only "
            "when the old repository will remain permanently private"
        )
    output_root.mkdir()

    (output_root / "source-head-manifest.json").write_text(
        json.dumps(_tree_manifest(source), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "remote-pr-refs.json").write_text(
        json.dumps(remote_pr_refs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    archive_mirror = output_root / "private-original-mirror.git"
    original_bundle = output_root / "private-original.bundle"
    rewritten_mirror = output_root / "rewritten-mirror.git"
    validation_worktree = output_root / "validation-worktree"
    _run(["git", "clone", "--mirror", "--no-hardlinks", source, archive_mirror])
    if remote_pr_refs:
        _git(archive_mirror, "remote", "add", "github-origin", _origin_url(source))
        _git(
            archive_mirror,
            "fetch",
            "--no-tags",
            "github-origin",
            "+refs/pull/*/head:refs/private/github-pull/*/head",
        )
        archived_pr_count = len(
            _git(
                archive_mirror,
                "for-each-ref",
                "refs/private/github-pull",
                "--format=%(refname)",
            ).splitlines()
        )
        if archived_pr_count != len(remote_pr_refs):
            raise RewriteError("private archive did not capture every advertised PR ref")
    archive_historical_assets = {
        path
        for path in _all_historical_paths(archive_mirror)
        if STATIC_BUNDLE_PATTERN.fullmatch(path)
    }
    plan["removed_paths"] = sorted(
        set(plan["removed_paths"])
        | (archive_historical_assets - set(plan["retained_static_assets"]))
    )
    plan["remote_pr_refs_checked"] = True
    plan["remote_pr_ref_count"] = len(remote_pr_refs)
    (output_root / "rewrite-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _run(["git", "-C", archive_mirror, "bundle", "create", original_bundle, "--all"])
    # git-filter-repo's fresh-clone safety check requires a real transport copy.
    # ``--no-hardlinks`` alone still uses Git's local-clone optimization and is
    # therefore rejected before any rewrite can start.
    _run(["git", "clone", "--mirror", "--no-local", archive_mirror, rewritten_mirror])
    _git(rewritten_mirror, "update-ref", "-d", "refs/tags/archive/options-coordination-v2-20260713")
    replacements, mailmap = _write_filter_inputs(
        output_root, name=name, email=email, private_identity=private_identity
    )

    filter_arguments: list[str | Path] = [
        filter_repo,
        "--sensitive-data-removal",
        "--no-fetch",
        "--invert-paths",
    ]
    for removed_path in plan["removed_paths"]:
        filter_arguments.extend(("--path", removed_path))
    filter_arguments.extend(
        (
            "--replace-text",
            replacements,
            "--replace-message",
            replacements,
            "--mailmap",
            mailmap,
            "--replace-refs",
            "delete-no-add",
        )
    )
    filter_result = _run(filter_arguments, cwd=rewritten_mirror)
    checks = _verify_rewritten_history(
        rewritten_mirror,
        plan=plan,
        name=name,
        email=email,
        private_identity=private_identity,
    )

    rewritten_bundle = output_root / "public-rewritten.bundle"
    _run(
        [
            "git",
            "-C",
            rewritten_mirror,
            "bundle",
            "create",
            rewritten_bundle,
            PUBLIC_REF,
        ]
    )
    bundle_heads = _run(["git", "bundle", "list-heads", rewritten_bundle]).stdout
    if bundle_heads.count("refs/heads/main") != 1 or len(bundle_heads.splitlines()) != 1:
        raise RewriteError("public bundle contains refs outside refs/heads/main")
    rewritten_head = _git(rewritten_mirror, "rev-parse", PUBLIC_REF)
    _run(
        [
            "git",
            "clone",
            "--branch",
            "main",
            "--single-branch",
            "--no-local",
            rewritten_bundle,
            validation_worktree,
        ]
    )
    validation_head = _git(validation_worktree, "rev-parse", "HEAD")
    if validation_head != rewritten_head:
        raise RewriteError("validation clone HEAD does not match rewritten main")

    commit_map = _copy_filter_report(rewritten_mirror, output_root, "commit-map")
    changed_refs = _copy_filter_report(rewritten_mirror, output_root, "changed-refs")
    first_changed_commits = _copy_filter_report(
        rewritten_mirror, output_root, "first-changed-commits"
    )
    if commit_map is None:
        raise RewriteError("git-filter-repo did not produce a commit-map")

    existing_repository_blockers = []
    if remote_pr_refs:
        existing_repository_blockers.append(
            "GITHUB_READ_ONLY_PR_REFS_RETAIN_OLD_HISTORY"
        )
    selected_target_blockers = (
        existing_repository_blockers
        if plan["cutover_target"] == "existing-repository"
        else []
    )
    report = {
        "schema_version": "public_history_rewrite_rehearsal.v1",
        "status": (
            "passed_with_remote_blockers" if selected_target_blockers else "passed"
        ),
        "local_rewrite_passed": True,
        "cutover_target": plan["cutover_target"],
        "public_cutover_ready": not selected_target_blockers,
        "remote_blockers": selected_target_blockers,
        "existing_repository_public_cutover_ready": not existing_repository_blockers,
        "existing_repository_blockers": existing_repository_blockers,
        "source_head": plan["source_head"],
        "live_origin_main": live_origin_main,
        "rewritten_head": rewritten_head,
        "identity_mode": plan["identity_mode"],
        "public_author": plan["public_author"],
        "filter_repo_version": FILTER_REPO_VERSION,
        "filter_repo_build_id": FILTER_REPO_BUILD_ID,
        "sensitive_data_removal_mode": True,
        "push_performed": False,
        "source_mutated": False,
        "remote_pr_refs_checked": True,
        "remote_pr_ref_count": len(remote_pr_refs),
        "private_archive": str(original_bundle),
        "private_archive_includes_remote_pr_refs": bool(remote_pr_refs),
        "rewritten_mirror": str(rewritten_mirror),
        "rewritten_bundle": str(rewritten_bundle),
        "public_bundle_refs": [PUBLIC_REF],
        "validation_worktree": str(validation_worktree),
        "validation_head": validation_head,
        "commit_map": commit_map,
        "changed_refs": changed_refs,
        "first_changed_commits": first_changed_commits,
        "signatures_removed_by_history_rewrite": True,
        "checks": checks,
        "filter_stdout": filter_result.stdout.strip(),
    }
    if plan["identity_mode"] == "final":
        report["live_origin_main_after_rehearsal"] = _assert_final_source_sync(source)
    report_path = output_root / "rehearsal-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute an isolated git-filter-repo rehearsal. This tool "
            "never modifies the source repository and never pushes."
        )
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--public-author-name", required=True)
    parser.add_argument("--public-author-email", required=True)
    parser.add_argument(
        "--identity-mode", choices=("rehearsal", "final"), default="rehearsal"
    )
    parser.add_argument(
        "--cutover-target", choices=CUTOVER_TARGETS, default="existing-repository"
    )
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--filter-repo-executable", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        private_identity = _load_private_identity()
        name, email = _validate_identity(
            args.public_author_name,
            args.public_author_email,
            args.identity_mode,
            private_identity,
        )
        source = _repository_root(args.source)
        plan = build_plan(
            source,
            name=name,
            email=email,
            mode=args.identity_mode,
            cutover_target=args.cutover_target,
            private_identity=private_identity,
        )
        if args.plan_only:
            json.dump(plan, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0
        if args.output_root is None:
            raise RewriteError("--output-root is required unless --plan-only is used")
        filter_repo = args.filter_repo_executable
        if filter_repo is None:
            discovered = shutil.which("git-filter-repo")
            if discovered is None:
                raise RewriteError(
                    "--filter-repo-executable is required; use pinned git-filter-repo 2.47.0"
                )
            filter_repo = Path(discovered)
        report = rehearse(
            plan,
            source=source,
            output_root=args.output_root,
            filter_repo=filter_repo.resolve(),
            name=name,
            email=email,
            private_identity=private_identity,
        )
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except (OSError, RewriteError, subprocess.SubprocessError) as exc:
        print(f"history rewrite rehearsal failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
