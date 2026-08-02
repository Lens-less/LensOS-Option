# Public Publishing Runbook

## Goal

Build one deterministic static publication tree from a captured snapshot plus precomputed research artifacts. The command fails closed on missing inputs, non-empty output directories, blocked market-data quality, or insufficient VRP history.

## Command

```bash
crypto-options-report publish \
  --snapshot artifacts/snapshots/btc-series/<capture>.json \
  --underlying-history artifacts/history/btc-daily.json \
  --dvol-history artifacts/history/btc-dvol.json \
  --signal-artifact artifacts/reports/signal-preflight.json \
  --series-artifact artifacts/reports/series-history.json \
  --out dist/site \
  --published-at 2026-08-02T08:06:31Z \
  --git-sha <commit>
```

Optional:

```bash
--web-build path/to/prebuilt/crypto_options_report/static/evidence
```

## Inputs

Required:

- Snapshot fixture JSON with a valid `captured_at`
- Underlying daily history JSON
- DVOL daily history JSON
- Signal artifact JSON
- Series artifact JSON
- Explicit `published_at`
- Empty or non-existent output directory

Optional:

- `git_sha`
- Alternate prebuilt web bundle directory

## Output tree

At minimum:

- `index.html`
- `assets/*`
- `_headers`
- `research/report`
- `research/signal`
- `research/series`
- `api/v1/manifest.json`
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

## Fail-closed rules

- Missing input file: abort before writing output.
- Output directory already contains files: abort.
- `published_at` earlier than snapshot `captured_at`: abort.
- Market-data quality not `validated` or `trusted`: abort.
- VRP not `validated` with at least 1000 effective published readings: abort.
- Forbidden private/execution fields detected in the published JSON tree: abort.

## Determinism contract

For identical inputs plus identical `published_at` and `git_sha`, two runs in different output directories must produce byte-identical trees.

The manifest avoids self-hash recursion by excluding the two manifest endpoints from its internal artifact hash list while keeping every other published file hashed and reproducible.

Before analysis and hashing, underlying and DVOL histories are cut off at the snapshot `captured_at` UTC date. Future daily rows are ignored rather than allowed to leak into the published VRP headline.

`research/report` is written from an explicit public whitelist. The published report keeps the research narrative, candidate surfaces, release gates, and published-edition metadata, but excludes account state, portfolio state, paper-ledger state, and sizing/order-cap fields.

## Hosting notes

- `index.html` is rewritten so bundle URLs resolve from `/assets/`.
- `_headers` sets:
  - `/api/v1/*` → CORS `*`, `Cache-Control: public, max-age=300`
  - `/research/*` → `Cache-Control: public, max-age=300`
  - `/assets/*` → `Cache-Control: public, max-age=31536000, immutable`
- `health.json` publishes `stale_after` and `is_stale_at_publish` only. Runtime consumers must compare their current clock to `stale_after`; the static tree does not fabricate a self-updating `is_stale`.
