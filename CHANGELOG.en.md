# Changelog — English Release Summary

The canonical detailed changelog is maintained in Chinese in
[CHANGELOG.md](CHANGELOG.md). This file provides the public release summary.

## [0.1.0] - Unreleased

The first public release is an auditable research-console tool, not a validated
trading signal. Pre-registered signal validation is still accumulating at 1/8
settled cohorts. The tag must wait for the one-time history sanitization and the
owner's public-author identity decision.

### Added

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

### Changed

- Daily capture refreshes independent underlying and DVOL histories even when
  snapshot collection fails.
- Research-window selection no longer fills its request budget with adverse
  moneyness tails that caused invalid bid-IV exclusions.
- Public DTE conflicts now return only a blocking verdict, uncollected macro
  events are represented as `null` / `not_collected`, and selection fallback is
  visible as a non-blocking advisory reason code.
