# Public release cutover checklist

This is the one-time OS-6 checklist. It intentionally separates repository
publication from hosted-site publication; the repository may become public
while `LENSOS_DEPLOY_DECISION=SUSPENDED` remains in force.

No destructive or externally visible step below is automated. Record the
operator, UTC timestamp, before/after refs, and evidence location for every
checked item.

## 1. Freeze and inventory

- [ ] Pause write-producing workflows, Dependabot updates, merges, and local
  commits.
- [ ] Confirm the working tree is clean and `HEAD == origin/main`.
- [ ] Confirm there are no open PRs and record all branch, tag, and remote PR
  ref tips.
- [ ] Create and verify an immutable private mirror/bundle outside the product
  repository.
- [ ] Confirm the owner-selected public author name and GitHub-verified noreply
  email (D-1).

## 2. Resolve GitHub retained-history risk

- [ ] Ask GitHub Support to remove affected read-only PR refs and cached views,
  following GitHub's
  [sensitive-data removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
- [ ] Re-run `git ls-remote --refs origin 'refs/pull/*/head'` and retain the
  response/evidence.
- [ ] If Support cannot confirm removal, select the safe fallback: create a new
  public repository and keep this original repository permanently private.

## 3. Rehearse and validate the rewritten repository

- [ ] Run the pinned OS-1 rehearsal in
  [`public-history-rewrite.md`](public-history-rewrite.md).
- [ ] Verify the content/path/message/author/tagger scans are zero-hit, HEAD blob
  manifest is unchanged, current CSS/JS OIDs are retained, `git fsck` passes,
  and the public bundle exposes only `refs/heads/main`.
- [ ] In `validation-worktree`, run Python tests and Ruff plus web lint, tests,
  build, and public-bundle boundary checks.
- [ ] Run the README newcomer path from a clean clone.
- [ ] Record that historical signatures are intentionally removed and retain
  the private `commit-map`.

## 4. Remove public-read risks unrelated to git objects

- [ ] Inventory all existing `publish.yml` workflow runs and artifacts.
- [ ] Remove or privately archive raw `captured-evidence` artifacts and old
  logs before any visibility change.
- [ ] Verify the raw capture upload's `repository.private == true`
  condition on the destination; the private evidence repository remains the
  durable system of record.
- [ ] Verify GitHub Actions fork-approval policy, least-privilege permissions,
  secret availability boundaries, and default-branch protection.
- [ ] Verify Security Advisories are enabled and `SECURITY.md` is visible.

## 5. Publish exactly one clean history

- [ ] For the existing-repository route, owner reviews the exact force-push
  targets and pushes only the rewritten `main`; internal branches, archive tags,
  and old clones must never be merged back.
- [ ] For the recommended fallback route, owner creates a new empty public repo
  and pushes only `refs/heads/main` from `public-rewritten.bundle`.
- [ ] Fresh-mirror clone the public destination and repeat every history scan,
  ref allowlist check, and full test matrix.
- [ ] Enable/reapply branch protection after the rewritten `main` exists.

## 6. Public metadata and release

- [ ] Set repository description, website (only if live), and topics.
- [ ] Confirm Apache-2.0 code licensing and CC BY 4.0 data/publication licensing.
- [ ] Confirm `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, and bilingual issue/PR
  guidance render correctly.
- [ ] Create and sign `v0.1.0` only from the rewritten public history; verify
  changelog, package version, tag, and release notes agree.
- [ ] Change visibility only after all preceding checks are recorded green.

## 7. Keep site deployment independent

- [ ] Leave `LENSOS_DEPLOY_DECISION=SUSPENDED` until DNS, deployment identity,
  notification endpoints, and independent monitor evidence are ready.
- [ ] Configure the selected Actions capture lane separately and require the
  three-day immutable-receipt acceptance in
  [`public-deployment-suspension.md`](public-deployment-suspension.md).
- [ ] Do not describe the strategy as validated before eight settled cohorts;
  open-source release is a tool/methodology release, not a signal conclusion.
