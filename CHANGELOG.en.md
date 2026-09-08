# Changelog — English Release Summary

The canonical detailed changelog is maintained in Chinese in
[CHANGELOG.md](CHANGELOG.md). This file provides the public release summary.

## [0.5.0] - 2026-09-08

This version connects first use, options decision research, evidence inspection,
and reproducible open-source delivery. Publication and verification status are
recorded in the [v0.5.0 delivery record](docs/product/2026-09-08-open-source-decision-platform.md).

- Added an offline learning tour independent of the research API, with fictional
  finite-risk payoff examples and an entry into the real bundled snapshot.
- Added complete-case reproduction with packaged inputs, an explicit clock,
  saved-case comparison, and actual evidence-blocking output.
- Separated typed `AnalysisInputs`, five admission-condition groups, and lazy
  compatibility projection; included build and input identities.
- Added fixed public OpenAPI/schema validation and version consistency across
  Python, Web, extension, tags, and built artifacts.
- Unified verification of source, builds, public boundaries, a clean installed
  wheel, and browser journeys through `tools/verify.py`.
- Required numeric cost budgets and model/configuration identities instead of
  boolean-only fee claims. Net credit deducts entry costs; cards remain `WATCH`
  because a modeled loss budget is not a verified absolute delivery-fee bound.
- Bound forecasts to costs and net credit. Upgrade engine, frontends, and
  extension together and regenerate old reports; v0.4.0 cards and unbound
  calibration artifacts cannot be reused unchanged.
- Removed historical weighting based on a path's own future returns. Missing
  pre-path features now select explicit unconditional uniform sampling.
- Made adverse underlying moves follow actual leg directions, separated short
  strike crossings from price-threshold proxies, and labeled dynamic delta
  unavailable. Bidirectional authored stress weights are not probabilities.
- Included per-leg delivery fees in exact-strategy replay and documented their
  exclusion from the risk denominator, allowing net `R` below `-1`.
- Validated signal/series research markers, schema, timestamps, and recursively
  prohibited execution fields while preserving blocked and exclusion evidence;
  old hand-authored artifacts must be regenerated with the current CLI.
- Unified current freshness and historical evaluation states, prevented stale
  eligibility, and added recovery for invalid data, timeout, and render errors.
- Distinguished missing signal/series artifacts from insufficient samples,
  improved narrow-screen and keyboard navigation, and documented the full
  research workflow in Chinese and English.
- Corrected preflight output, exit-code interpretation, cache expiry, and daily
  close settlement-proxy documentation. Kept private archive ancestry isolated
  from public development.

Research evidence gates remain fail-closed and execution remains disabled.
See the [v0.5.0 release notes](docs/releases/v0.5.0.md).

## [0.4.0] - 2026-08-30

This release integrates the v0.2 one-screen market and strategy brief, v0.3
structure-aligned historical replay, and v0.4 exact-strategy calibration
lifecycle. It does not claim that immature cohorts are validated.

- Added canonical `strategy_brief.v1` validation and deterministic identities
  across Python and TypeScript, projected into internal, public, and Chrome side
  panel surfaces.
- Added zero-to-three exact one-unit finite-risk strategy cards for Bull Put
  Credit Spread, Bear Call Credit Spread, and Iron Condor, including executable
  touch entry, frozen costs, maximum loss, expiry, and cancellation rules.
- Added aligned replay/holdout artifacts and exact-strategy forecast promotion,
  expiry, drift, scope-mismatch, and out-of-sample demotion state machines.
- Bound historical evidence to stable protocol semantics and forecast evidence
  to the exact expiry and legs. Same-family card changes, protocol drift, and
  legacy unbound artifacts now retire evidence and clear probability fields.
- Accepted production `cvar_95_usdc` path-risk rows through the same finite,
  positive-risk gate, and preserved per-leg source quote times on fallback
  candidates instead of replacing missing or stale times with generation time.
- Kept historical rates hidden before `VALIDATED`, forecast intervals hidden
  before `CALIBRATED`, and `execution_allowed=false` under every state.
- Rejects negative post-cost EV, a superior opposite direction, no touch edge,
  unbounded/unknown loss, and incomplete, stale, crossed, asynchronous, or
  unit-inconsistent multi-leg quotes.
- Refreshed the exact Python build/test pins, Web build and type-tool patch
  versions, and the CI-verified Python 3.14 slim container digest.

See the [v0.4.0 delivery notes](docs/releases/v0.4.0.md).

## [0.1.0] - 2026-08-29

The first public release is an auditable research-console tool, not a validated
trading signal. Pre-registered signal validation is still accumulating at 1/8
settled cohorts; this release publishes the tool and methodology without
presenting that progress as a validated trading signal.

### Added

- A wheel-installed `crypto-options-report demo` with redacted packaged data,
  an explicitly labeled read-only UI, and no Node.js, credentials, network, or
  repository-fixture dependency.
- A minimal `v*` GitHub Release workflow that produces the Python wheel, Chrome
  extension ZIP, and `SHA256SUMS` without publishing to a package or app store.
- Deterministic fixture replay across the CLI, HTTP API, Evidence Console, and
  Chrome research companion.
- Fail-closed public publication with explicit privacy allowlists, immutable
  editions, concrete OpenAPI schemas, and Apache-2.0 / CC BY 4.0 licensing.
- Expiry-level quarantine for longitudinal validation, preserving healthy
  cohorts without relaxing full-report quality gates or thresholds.
- Validation-usability fields and two-consecutive-day alerting in daily capture
  summaries, failure webhooks, and dead-man heartbeats.
- A credential-free newcomer path using only repository fixtures, plus public
  contribution and conduct guidance.

### Fixed

- Local HTTP aliases now serve the workbench, Evidence Console, methodology,
  disclaimer, privacy, terms, and status links without navigation 404s.
- Daily capture now normalizes PowerShell 7.6's automatic RFC3339 JSON date
  conversion, preserving the current usability streak even when webhook
  delivery fails closed.
- Alert cooldown timestamps without a timezone are now rejected fail-closed
  instead of being interpreted in the process-local timezone (an 8-hour shift
  on UTC+8 that could suppress or repeat alerts).
- Independent-window counts in realized-vol and path-risk now derive from the
  actual strided sample, so an exact-multiple observation count can no longer
  cross the `MIN_INDEPENDENT_WINDOWS` gate with one window too few.
- Percent formatting no longer guesses units from magnitude: a 1.5%
  strike-distance field rendered as 150% before; unit semantics are now carried
  by the formatter choice per field contract.
- The candidate workbench narrows `edge_components` per entry and all three app
  roots gained an error boundary, so malformed payloads degrade one panel
  instead of white-screening the app.
- Descending sorts keep unavailable rows at the bottom; the payoff curve
  refuses three-leg ids and non-positive spread widths instead of drawing a
  wrong chart; signal/series artifact loading distinguishes HTTP failures from
  an unreachable engine; the internal default artifact URLs are gone from the
  public bundle.

### Changed

- Daily capture refreshes independent underlying and DVOL histories even when
  snapshot collection fails.
- Research-window selection no longer fills its request budget with adverse
  moneyness tails that caused invalid bid-IV exclusions.
- Public DTE conflicts now return only a blocking verdict, uncollected macro
  events are represented as `null` / `not_collected`, and selection fallback is
  visible as a non-blocking advisory reason code.

[0.5.0]: https://github.com/Lens-less/LensOS-Option/releases/tag/v0.5.0
[0.4.0]: https://github.com/Lens-less/LensOS-Option/releases/tag/v0.4.0
[0.1.0]: https://github.com/Lens-less/LensOS-Option/releases/tag/v0.1.0
