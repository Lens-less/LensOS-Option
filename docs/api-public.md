# Public Static API

The public publication tree exposes read-only JSON from static files. All payloads are deterministic for a fixed set of inputs plus `published_at` and optional `git_sha`.

## Paths

`/research/report`
- Canonical published `research_report.v1` public projection.
- Includes `runtime_context.mode = "published"`, `publish_edition`, projected `vrp_status`, and `full_system_surface.release_gates`.
- Sanitized by whitelist before writing: no `account_status`, `portfolio_risk`, `position_management`, `paper_proposal_ledger`, or sizing/order-cap fields such as `risk_budget`.

`/research/signal`
- Canonical signal artifact copied from the CLI input and re-encoded canonically.

`/research/series`
- Canonical series-history artifact copied from the CLI input and re-encoded canonically.

`/api/v1/manifest.json`
- Publication manifest.
- Records `analysis_run_id`, `analysis_record_sha256`, `captured_at`, `published_at`, `evaluation_clock`, `git_sha`, source input hashes, and SHA-256 for every published file except the manifest endpoints themselves.
- Declares that underlying and DVOL histories are trimmed to the snapshot `captured_at` UTC date before evaluation and hashing, so future rows never influence the published VRP state.
- `.well-known/publish-manifest.json` is byte-identical.

`/api/v1/summary.json`
- Headline VRP state for the published edition.
- Fields:
  - `captured_at`
  - `published_at`
  - `cadence`
  - `stale_after`
  - `vrp.vrp_percent_points`
  - `vrp.dvol_percent`
  - `vrp.rv30_percent`
  - `vrp.percentile`
  - `vrp.band`
  - `vrp.evidence_class`
  - `release_gates`

`/api/v1/thermo.json`
- Full projected VRP time series for the public front end.
- Fields:
  - `status`
  - `current_vrp_percent_points`
  - `current_dvol_percent`
  - `current_rv30_percent`
  - `percentile`
  - `band`
  - `series`
  - `missing_dates`
- `sample_count`
- `minimum_series_sample_count`
- `window_days`

`/api/v1/candidates.json`
- Public candidate projection from `ev_candidate_scanner`.
- Includes `status`, `reason_code`, `score_status`, `summary`, and `ranked_candidates`.
- Remains research-only: no order instructions, sizing, or execution state.

`/api/v1/signal.json`
- Wrapper around the signal artifact with publication metadata and legal links.

`/api/v1/health.json`
- Static publication health metadata.
- Fields:
  - `captured_at`
  - `published_at`
  - `last_published_at`
  - `next_expected_at`
  - `stale_after`
  - `cadence`
  - `runtime_mode`
  - `data_status`
  - `is_stale_at_publish`
  - `research_publication_status`
  - `execution_authorization_status`

## Caching and CORS

The publication root emits `_headers` for static hosts that support it:

`/api/v1/*`
- `Access-Control-Allow-Origin: *`
- `Cache-Control: public, max-age=300`

`/research/*`
- `Cache-Control: public, max-age=300`

`/assets/*`
- `Cache-Control: public, max-age=31536000, immutable`

## Notes

- `health.json` does not expose a time-evolving `is_stale`; consumers must compare wall clock time to `stale_after`.
- `published_at` must be greater than or equal to the snapshot `captured_at`.
- Publication is fail-closed. If market-data quality blocks or VRP is not production-valid, `publish` exits without writing a partial site.
