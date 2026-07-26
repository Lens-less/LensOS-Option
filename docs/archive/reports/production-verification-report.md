# Production Verification Report

Date: 2026-07-12  
Scope: production-safe deployment of the research console and coordination V2.  
Trading authority: unchanged — `RESEARCH_ONLY`, `NO_TRADE`, and `NO-GO` remain fail-closed.

## Outcome

The production-readiness implementation is complete on
`codex/production-readiness` and is published in draft pull request
[#60](https://github.com/Lens-less/LensOS-Option/pull/60). The verified
implementation commit is `e8af3257732f9b26819a7691751ecebe90a44d05`.

Production mode in this project means a bounded, observable, packageable
research HTTP service. It does not mean paper trading, manual order entry, or
live trading. Direct public exposure remains unsupported: an Internet-facing
deployment must put TLS, authentication, and edge rate limiting in a
same-origin reverse proxy in front of the service.

## Verification evidence

### Local code and contracts

- Full suite: `251 passed, 1 skipped, 137 subtests passed`.
- Coordination/evidence security seam: `35 passed, 1 skipped`.
- `python -m compileall -q crypto_options_report tools`: passed.
- Git whitespace/error scan and duplicate top-level-definition scan: passed.
- Isolated wheel build, install, dependency check, CLI entry point, and API
  smoke: passed.
- V1 cutover archive and evidence-store SHA-256 fences: exact working-tree and
  index readback passed.

### GitHub Actions

Run [29191883478](https://github.com/Lens-less/LensOS-Option/actions/runs/29191883478)
passed all five jobs for the verified implementation commit:

- Ubuntu, Python 3.12: full tests, smoke, wheel build, isolated install.
- Ubuntu, Python 3.13: full tests, smoke, wheel build, isolated install, artifact upload.
- Windows, Python 3.12: full tests, smoke, wheel build, isolated install.
- Windows, Python 3.13: full tests, smoke, wheel build, isolated install.
- Container: non-root production image, read-only root filesystem, tmpfs
  runtime, readiness, health, and dashboard checks.

The Windows matrix also exercises the runner's mixed long and 8.3 path
spellings. Evidence containment accepts aliases for the same repository while
continuing to reject symlink and junction components.

### Runtime and browser

- `/livez`, `/readyz`, `/health`, `/dashboard.html`, and
  `/research/report` returned their documented production contracts.
- Invalid routes, invalid queries, cross-origin/SSRF-style parameters, unsafe
  mode requests, and unsupported methods failed closed.
- Saturation returned deterministic `503` responses with complete security
  headers and structured request IDs, then recovered after capacity returned.
- Desktop dashboard loaded to `complete`, displayed the research-only and
  `NO-GO` boundaries, refreshed successfully, and produced no console errors.
- A malicious `api_base=javascript:...` query was ignored without navigation,
  script execution, a dialog, or a failed refresh.
- A real 375 x 844 browser viewport had no document-level horizontal overflow;
  the navigation region remained locally scrollable and the console remained clean.

## Production safeguards delivered

- Bounded worker pool, socket timeouts, overload rejection, and structured logs.
- Startup preflight before bind and fail-closed runtime readiness.
- Same-origin dashboard with fetch timeout and concurrent-refresh suppression.
- No-store, CSP, frame, referrer, permissions, CORP, request-ID, and generic
  server-identity response policy.
- Crash-safe atomic report writes and environment-sourced webhook secrets.
- Reproducible wheel, non-root container, CI matrix, environment template,
  security policy, and production runbook.
- Coordination V2 planned/running handoff, authoritative task observation,
  immutable Git tree candidates, fresh verifier separation, remote readback,
  local-only gate acceptance, and V1 cutover fences.

## Remaining operator responsibilities

- Review and merge draft PR #60; this verification does not merge into the
  default branch automatically.
- Terminate TLS and enforce authentication/rate limiting at the reverse proxy.
- Provide durable log collection and process supervision in the target hosting
  environment.
- Do not enable trading capabilities without a separate authorization,
  architecture, threat-model, and acceptance cycle.
