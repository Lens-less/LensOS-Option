# Public history rewrite rehearsal

## Purpose and boundary

This is the mandatory OS-1 rehearsal for removing historical machine paths,
private author metadata, internal coordination files, and obsolete generated
bundles before open-source release. It never runs against the working
repository and never pushes.

The repository tool follows the official
[`git-filter-repo` sensitive-data-removal guidance](https://github.com/newren/git-filter-repo/blob/master/Documentation/git-filter-repo.txt)
and pins version `2.47.0` / build `a40bce548d2c`. Installation guidance is in
the project's [official install document](https://github.com/newren/git-filter-repo/blob/main/INSTALL.md).

## Current remote blocker

The 2026-08-13 audit found 12 GitHub read-only `refs/pull/*/head` refs. A normal
force-push cannot update them. GitHub also warns that pull-request refs and
cached views can retain sensitive objects after a rewrite. Follow GitHub's
[sensitive-data removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

Therefore:

- local rehearsal success is necessary but does not make the existing GitHub
  repository safe to publish;
- request GitHub Support removal of affected PR refs and cached views; and
- if Support cannot confirm removal, create a new private repository from the
  rewritten `main` bundle, validate it, then make only that new repository
  public while keeping the old repository permanently private.

## Install the pinned tool outside project dependencies

Use a disposable virtual environment. Do not add `git-filter-repo` to runtime
dependencies.

```powershell
python -m venv .wheel-verify\git-filter-repo-2.47.0
.\.wheel-verify\git-filter-repo-2.47.0\Scripts\python.exe -m pip install git-filter-repo==2.47.0
.\.wheel-verify\git-filter-repo-2.47.0\Scripts\git-filter-repo.exe --version
```

Expected build ID: `a40bce548d2c`.

## Load the private identity from local environment variables

The rehearsal tool no longer stores any private identity token in tracked
source. Before running it, set all four task-specific variables in the current
shell with local-only placeholder names:

```powershell
$env:LENSOS_HISTORY_REWRITE_PRIVATE_USER_ID = "<PRIVATE_LOCAL_USER_ID>"
$env:LENSOS_HISTORY_REWRITE_PRIVATE_AUTHOR_ID = "<PRIVATE_AUTHOR_ID>"
$env:LENSOS_HISTORY_REWRITE_PRIVATE_EMAIL = "<PRIVATE_EMAIL>"
$env:LENSOS_HISTORY_REWRITE_PRIVATE_NAME = "<PRIVATE_DISPLAY_NAME>"
```

All four are required every time. Missing or partially populated variables fail
closed. Do not commit these values, paste them into issues, or save them in
tracked repo files.

## Inspect the plan

The public identity below is intentionally a rehearsal placeholder:

```powershell
python tools/rehearse-public-history-rewrite.py `
  --source . `
  --public-author-name "LensOS Public Rehearsal" `
  --public-author-email "history-rewrite@example.invalid" `
  --identity-mode rehearsal `
  --plan-only
```

The plan must say `push_allowed=false`, retain exactly the current hash-named
CSS and JS blobs, remove all historical internal paths, and allow only
`refs/heads/main` in the public bundle. Public plan and report JSON only expose
replacement marker categories and counts, never the private token values.

## Run an isolated rehearsal

The output must be a new directory outside this repository. The command rejects
a dirty source or an existing output path.

```powershell
python tools/rehearse-public-history-rewrite.py `
  --source . `
  --public-author-name "LensOS Public Rehearsal" `
  --public-author-email "history-rewrite@example.invalid" `
  --identity-mode rehearsal `
  --output-root C:\path\outside\LensOS-history-rehearsal-20260813 `
  --filter-repo-executable .\.wheel-verify\git-filter-repo-2.47.0\Scripts\git-filter-repo.exe
```

Outputs include:

- `private-original.bundle`: private archive of all local refs plus fetched PR
  ref tips; it contains the data being removed and must never be published;
- `public-rewritten.bundle`: only rewritten `refs/heads/main`;
- `commit-map`, `changed-refs`, and `first-changed-commits` when emitted by the
  pinned tool;
- `validation-worktree`: clean clone used for the complete test matrix; and
- `rehearsal-report.json`: local checks plus remote-cutover blockers.

`passed_with_remote_blockers` is expected while GitHub PR refs remain. It is
not public-cutover approval.

The content audit scans every reachable blob as bytes, including UTF-8,
UTF-16LE, and UTF-16BE token encodings. Binary-classified blobs are not skipped.

History rewrite removes existing commit/tag signatures. This is expected; do
not claim that old Verified badges survive. Sign the post-rewrite `v0.1.0`
release afresh if release policy requires it.

## Final identity and destination gate

`--identity-mode final` rejects placeholder identities, a dirty source,
and `HEAD !=` the freshly queried live `origin/main` (a cached tracking ref is
not sufficient). With the default
`--cutover-target existing-repository`, it also rejects any remaining GitHub
PR refs. The owner must first confirm the exact public display name and a
GitHub-verified noreply address. Never infer or hard-code that address from an
account ID.

If GitHub Support cannot remove the pull-request refs and cached views, use
`--cutover-target new-repository` for the final local rewrite. This permits a
clean `main` bundle for a newly created private repository. Validate that
destination completely before changing its visibility; the old repository
remains permanently private. This does not make the old repository safe to
publish.

The final rewrite is still produced locally with no push. Any force-push,
repository creation, deletion of old refs/runs, or visibility change is a
separate owner-executed step in
[`public-release-cutover.md`](public-release-cutover.md).
