# Public Static API

The public site exposes deterministic, read-only JSON. Every payload is built
from explicit allow-list projections; account state, portfolio state, sizing,
orders, operator notes, local paths, and credentials are not part of this API.
The machine-readable OpenAPI 3.1 contract is published at
`/api/openapi.json`.

```powershell
curl.exe -sS http://127.0.0.1:8000/api/v1/summary.json
curl.exe -sS http://127.0.0.1:8000/api/v1/thermo/recent.json
curl.exe -sS http://127.0.0.1:8000/api/v1/health.json
curl.exe -sS http://127.0.0.1:8000/api/openapi.json
```

## Contract rules

- Timestamps are RFC 3339 UTC values.
- `percentile` is a fraction in `0..1`; volatility values are percentages;
  `vrp_percent_points` is `DVOL - RV30` in volatility percentage points.
- A series point whose comparison history is below the minimum publishes
  `percentile: null` and `band: null` rather than a misleading rank.
- `dvol_observed_at`, `underlying_observed_at`, and `evaluation_at` retain the
  real source/evaluation clocks. They are not synthesized from a date label.
- `published_at` is deterministic input. Consumers must compare their wall
  clock with `stale_after`; a static file cannot become stale by mutating itself.
- All endpoint response schemas are concrete OpenAPI `application/json`
  schemas. Object key sets are closed for the values projected in that edition.

## Endpoints

### `/api/v1/summary.json`

Headline edition state:

- `vrp`: current VRP, DVOL, RV30, empirical rank, canonical band, and per-field
  evidence units.
- `change`: change from the previous eligible observation, including VRP and
  percentile deltas plus whether the band changed.
- `alert`: neutral machine-readable display signal; it is not execution advice.
- `publication_history`: a 30-day public projection of durable success/failure
  receipts. Manifest hashes are deliberately removed from this projection.
- `release_gates`: disk-verified research publication and permanent
  execution-authorization gates.

### `/api/v1/thermo.json`

The complete published VRP series. `series[]` carries source timestamps,
`vrp_percent_points`, `dvol_percent`, `rv30_percent`, `percentile`,
`percentile_sample_count`, `band`, and `evidence_class`. Top-level fields also
publish `missing_dates`, `sample_count`, `minimum_series_sample_count`, and the
actual `window_days`.

For smaller reads:

- `/api/v1/thermo/recent.json` — latest 90 observations.
- `/api/v1/thermo/by-year/{year}.json` — one calendar-year shard.
- `recent_series_path` and `year_shards` in `thermo.json` enumerate the
  available routes.

### `/api/v1/candidates.json`

Position-independent research candidates. A row may include
`candidate_id`, `structure_type`, `action`, `expiry_date`, derived `dte_days`,
`ranking_score`, `ev_after_cost_usdc`, `executable_credit_usdc`, `path_risk`,
`kill_conditions`, `dominated_by`, `losing_axes`, and numeric
`field_evidence`.

The ranking value is an uncalibrated research ordering aid, not a return
forecast, recommendation, quantity, or order instruction. Rejected candidates
are summarized rather than exposed as trade-shaped output.

### `/api/v1/signal.json`

Wrapper around the explicitly projected public signal artifact. It includes
evidence annotations and may contain sample, cohort, band, signal-definition,
and pre-registration information. The source artifact is never forwarded
verbatim.

### `/api/v1/health.json`

Static health metadata:

- capture/publication clocks and `stale_after`;
- `is_stale_at_publish` (only the build-time fact);
- disk-verified manifest status and verification details;
- research publication and execution authorization statuses;
- the durable 30-day publication history projection.

An independent monitor must poll this endpoint and compare wall time with
`stale_after`. The success heartbeat and the poller must live outside the
system being monitored.

### `/api/v1/manifest.json` and `/.well-known/publish-manifest.json`

Byte-identical canonical manifests containing provenance, input hashes, the
complete published artifact inventory, artifact SHA-256 values, and manifest
verification policy. The two manifest paths exclude only themselves from the
self-hash set.

### `/research/report`, `/research/signal`, `/research/series`

Extensionless static projections consumed by the public UI. They are also
documented in OpenAPI and receive public CORS/cache headers. Each is built by a
field allow-list:

- `report` keeps the research narrative, evidence, candidates, volatility
  surface, VRP, and release gates.
- `signal` keeps the approved validation/cohort projection.
- `series` keeps the approved longitudinal observation projection.

None of these routes carries margin snapshots, account/portfolio state,
execution authorization details, sizing, orders, operator notes, or source
filesystem paths.

## Evidence classes

| Value | Meaning |
| --- | --- |
| `trusted` | Verified and suitable as a conclusion basis |
| `degraded` | Readable but not strong enough to support a conclusion |
| `untrusted` | Present but validation failed |
| `missing` | Absent |
| `validated_underlying_price_history` | Self-captured underlying history; no historical option fillability claim |
| `validated_historical_reconciliation` | Reconciled historical option quotes backed by vendor data |

## Headers and caching

The generated `_headers` file applies CSP and browser-hardening headers to the
whole site. `/api/v1/*`, `/api/openapi.json`, and `/research/*` allow public
cross-origin reads and use a five-minute cache. Fingerprinted `/assets/*` use an
immutable one-year cache.

Publication fails closed if required market evidence, the public-only web
bundle, legal files, allow-list projection, privacy scan, release gates, or
manifest verification fails.
