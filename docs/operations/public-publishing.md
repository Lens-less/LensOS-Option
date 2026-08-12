# Public Publishing Runbook

## Goal

Build one deterministic static publication tree from a captured snapshot plus
precomputed research artifacts. The command fails closed on missing inputs,
non-empty output directories, blocked market-data quality, or insufficient VRP
history.

## Publishing contract

- The target host contract is Cloudflare Pages. The `_headers` file in the
  output tree is written in Cloudflare Pages format.
- The public edition is Chinese-first. English copies may be published under
  `/en/` as a static mirror when the owner chooses to ship them.
- The public headline is intentionally lagged by one day. The edition should be
  built from already-closed daily data so same-day re-runs do not produce two
  different headlines.
- Treat publication as a bounded operator task, not a background daemon. The
  operational slot is 45 minutes; if the slot is exceeded, stop and recover
  rather than improvise a partial publish.
- The public release and the evidence repository are separate contracts. A
  static tree can be generated without claiming that the external heartbeat or
  the evidence repository are already configured.

## Command

```powershell
Push-Location web
npm ci
npm run build:public
npm run test:public-bundle
Pop-Location

$siteOrigin = $env:LENSOS_PUBLIC_SITE_ORIGIN
if ([string]::IsNullOrWhiteSpace($siteOrigin)) {
  throw 'Set LENSOS_PUBLIC_SITE_ORIGIN to the final owned HTTPS origin.'
}

crypto-options-report publish `
  --snapshot artifacts/snapshots/btc-series/<capture>.json `
  --underlying-history artifacts/history/btc-daily.json `
  --dvol-history artifacts/history/btc-dvol.json `
  --signal-artifact artifacts/reports/signal-preflight.json `
  --series-artifact artifacts/reports/series-history.json `
  --publication-history artifacts/reports/publication-history.json `
  --out dist/site `
  --published-at 2026-08-02T08:06:31Z `
  --site-origin $siteOrigin `
  --git-sha <commit> `
  --web-build web/dist-public
```

## Inputs

Required:

- Snapshot fixture JSON with a valid `captured_at`
- Underlying daily history JSON
- DVOL daily history JSON
- Signal artifact JSON
- Series artifact JSON
- Durable `publication_history.v1` receipt collection assembled from the
  private evidence repository
- Explicit public-only web bundle built by `npm run build:public`
- Explicit `published_at`
- Final absolute HTTPS `site_origin`, containing no credentials, path, query,
  or fragment
- Empty or non-existent output directory

Optional:

- `git_sha`

## Output tree

At minimum:

- `index.html`
- `og-card.png`
- `assets/*`
- `_headers`
- `research/report`
- `research/signal`
- `research/series`
- `api/v1/manifest.json`
- `api/openapi.json`
- `api/v1/summary.json`
- `api/v1/thermo.json`
- `api/v1/candidates.json`
- `api/v1/signal.json`
- `api/v1/health.json`
- `.well-known/publish-manifest.json`
- `methodology.html`
- `disclaimer.html`
- `privacy.html`
- `terms.html`
- `status.html`
- `robots.txt`
- `sitemap.xml`
- `en/{methodology,disclaimer,privacy,terms,status}.html`
- `static-page.css`
- `editions/<date>/...` immutable edition copy

## Fail-closed rules

- Missing input file: abort before writing output.
- Missing, malformed, future-dated, duplicated, or privately extended
  publication receipt history: abort before writing output.
- Output directory already contains files: abort.
- Missing or non-HTTPS `--site-origin`; a special-use (`.alt`, `example.*`,
  `.invalid`, localhost, and related names), local/single-label or IP host; a
  non-default port; or an origin containing credentials, path, query, or
  fragment: abort before creating the output directory. The formal workflow
  also resolves every address and rejects private, documentation, benchmark,
  translation, and other IANA special-purpose IPv4/IPv6 ranges.
- `published_at` earlier than snapshot `captured_at`: abort.
- Market-data quality not `validated` or `trusted`: abort.
- VRP not `validated` with at least 1000 effective published readings: abort.
- Forbidden private/execution fields or local absolute paths in forwarded
  artifacts: abort before any site file is written.
- Any private/execution vocabulary embedded in JavaScript or CSS: abort. The
  public bundle must also pass `npm run test:public-bundle`; the publisher
  repeats the content scan instead of trusting that earlier check.
- Missing `--web-build`: abort. The internal Evidence Console bundle is never a
  publication fallback.

## Determinism contract

For identical inputs plus identical `published_at`, `site_origin`, and
`git_sha`, two runs in different output directories must produce byte-identical
trees.

The manifest avoids self-hash recursion by excluding the two manifest endpoints
from its internal artifact hash list while keeping every other published file
hashed and reproducible.

Before analysis and hashing, underlying and DVOL histories are cut off at the
exact snapshot `captured_at` clock. Future rows—even later on the same UTC
date—are ignored rather than allowed to leak into the published VRP headline.

`research/report` is written from an explicit public whitelist. The published
report keeps the research narrative, candidate surfaces, release gates, and
published-edition metadata, but excludes account state, portfolio state,
paper-ledger state, and sizing/order-cap fields.

## Monitoring and recovery

- A public monitor should compare the current wall clock to
  `publish_edition.stale_after`. The static tree does not update `is_stale`
  itself.
- `capture-daily.ps1` can send a success-only dead-man ping through
  `-SuccessHeartbeatUrl` / `CAPTURE_DAILY_SUCCESS_HEARTBEAT_URL`, after capture
  and durable evidence sync have both succeeded. Delivery failure is fatal and
  is recorded without persisting the URL.
- The success ping is not an external health check. A separately owned hourly
  monitor must fetch `/api/v1/health.json` and compare its own clock to
  `stale_after`. Domain ownership and that third-party monitor remain explicit
  deployment prerequisites; this repository does not pretend they are set.
- If the evidence repository is unavailable, do not invent a fallback or claim
  that sync succeeded. Keep the static publication separate from the recovery
  path and retry the evidence sync only after the repository constraint is
  satisfied.
- After every attempted publish, the scheduled workflow commits one narrow,
  allow-listed `publications/YYYY-MM-DD.json` receipt to the private evidence
  repository. A successful run is not accepted until that push succeeds. The
  next publication validates these receipts and renders the prior 30 days;
  manifest hashes are validated privately but never copied to the public status
  projection.

## Scheduled workflow admission

The scheduled workflow always captures first, even when deployment settings are
missing. The current repository decision also keeps deployment
**explicitly suspended** until owner-owned DNS/hosting identity exist. The
workflow therefore still captures and verifies the public bundle, uploads that
capture as a temporary recovery artifact, and records `DEPLOY_SUSPENDED`
instead of attempting publication. It only admits a distributable `dist/site`
after that suspension is intentionally cleared and every independent contract
below is satisfied. The durable decision and owner handoff are recorded in
[`public-deployment-suspension.md`](public-deployment-suspension.md):

- Repository variables:
  - `LENSOS_EVIDENCE_REPO_SYNC_ENABLED=true`
  - `LENSOS_EVIDENCE_REPO_SLUG=<owner/private-evidence-repo>`
  - `LENSOS_EVIDENCE_REPO_BRANCH=<named-branch>`
  - `LENSOS_PUBLIC_SITE_ORIGIN=https://<final-public-host>`
  - `LENSOS_STALE_MONITOR_ID=<external-provider-monitor-id>`
- Repository secrets:
  - `LENSOS_EVIDENCE_REPO_PUSH_TOKEN`
  - `CAPTURE_FAILURE_WEBHOOK_URL`
  - `CAPTURE_SUCCESS_HEARTBEAT_URL`
  - `LENSOS_STALE_MONITOR_ATTESTATION_URL`
  - `LENSOS_STALE_MONITOR_ATTESTATION_TOKEN`

Missing configuration produces a failed, durable publication receipt and no
distributable site artifact. The workflow does not accept an operator boolean
as proof that monitoring exists. It fetches a fresh JSON attestation over
public HTTPS from a host distinct from the site origin, rejects redirects, and
binds the proof to the exact origin, health endpoint, notification endpoints,
poll interval, and latest failure-delivery drill.

The external service must return `Content-Type: application/json` (or a
`+json` media type) and this contract:

```json
{
  "schema_version": "lensos_stale_monitor_attestation.v1",
  "monitor_id": "<same as LENSOS_STALE_MONITOR_ID>",
  "site_origin": "https://<final-public-host>",
  "health_url": "https://<final-public-host>/api/v1/health.json",
  "contract": "compare_current_time_to_stale_after",
  "check_interval_seconds": 3600,
  "status": "healthy",
  "checked_at": "2026-08-03T09:59:00Z",
  "failure_delivery_drill_at": "2026-07-15T00:00:00Z",
  "failure_webhook_sha256": "<lowercase SHA-256 of the exact failure URL>",
  "success_heartbeat_sha256": "<lowercase SHA-256 of the exact heartbeat URL>"
}
```

`checked_at` must be no older than 2 hours, the failure drill no older than 30
days, and `check_interval_seconds` must be between 60 and 3600. `armed` is also
accepted during first-deployment bootstrap. Fingerprints bind secret endpoint
URLs without writing those URLs into logs or receipts. A proof older than its
window, a changed endpoint, a placeholder/private host, or an unreachable
attestation service turns the publication gate red while capture still runs.

When the proof is accepted, the private daily publication receipt stores an
exact allow-listed projection plus the SHA-256 of its canonical JSON. It keeps
the monitor ID, normalized site/health contract, cadence, check and drill
timestamps, status, and endpoint fingerprints. It never stores the bearer
token, attestation URL, or secret notification URLs. The public 30-day status
projection deliberately removes this private proof, while the evidence repo
retains enough information to replay why admission was green on that run.

## Hosting notes

- `index.html` keeps relative `./assets/` URLs so both the current root and a
  dated `/editions/<date>/` archive load their own immutable assets and JSON.
- Durable backup is a separate contract from static hosting:
  `tools/capture-daily.ps1 -EnableEvidenceRepoSync` reconciles the complete
  managed `snapshots/`, `history/`, `logs/`, and `reports/` set against an
  already-provisioned evidence git repo. A prior failed push is therefore
  backfilled by a later run. The GitHub Actions 90-day artifact is only a
  temporary safety copy. Preflight rejects product-repository worktrees,
  matching remotes, ignored managed paths, detached branches, and dirty
  evidence repos before an ordinary (never forced) push.
- In Actions, the product checkout lives at
  `${{ github.workspace }}/product` and the evidence checkout at
  `${{ github.workspace }}/evidence-repo`. They are siblings by design;
  placing the evidence checkout under the product repo fails preflight.
- The canonical HTTPS origin is embedded in Open Graph/Twitter metadata,
  `robots.txt`, and `sitemap.xml`; changing hosts therefore requires a fresh
  deterministic build, not a byte-for-byte copy of an old tree.
- `_headers` uses the Cloudflare Pages contract and sets:
  - `/*` -> self-only CSP, `nosniff`, no-referrer, frame denial, and restrictive
    browser permissions
  - `/api/v1/*` -> CORS `*`, `Cache-Control: public, max-age=300`
  - `/research/*` -> CORS `*`, `Cache-Control: public, max-age=300`
  - `/assets/*` -> `Cache-Control: public, max-age=31536000, immutable`
- `health.json` publishes `stale_after` and `is_stale_at_publish` only. Runtime
  consumers must compare their current clock to `stale_after`; the static tree
  does not fabricate a self-updating `is_stale`.
