# Production Hardening Plan

Status: complete (2026-07-12)
Scope: deploy the research console safely without enabling paper, manual, or live trading.

## Invariants

- `research_only`, `NO_TRADE`, and `NO-GO` remain fail-closed.
- No live-order adapter, order template, sizing output, or paper/manual control is added.
- No new runtime dependency is introduced; the service remains Python stdlib based.
- Public HTTP traffic is expected to reach the service through a same-origin reverse proxy. Direct public exposure is unsupported.

## Cleanup before change

1. Keep existing report and dashboard behavior locked through public CLI/HTTP tests.
2. Replace the unbounded `ThreadingHTTPServer` runtime with a bounded server seam instead of adding another server layer.
3. Centralize response security headers and structured logging; delete duplicated header writes.
4. Remove the unsupported cross-origin `api_base` dashboard option and keep same-origin fetches only.
5. Fix duplicate HTML IDs and exclude live local Codex state, generated workflow caches, runtime artifacts, environment files, and private keys from publication. The immutable V1 cutover archive and content-addressed evidence store are the deliberate exception: their exact bytes are required by the recorded SHA-256 migration fence, their coordination tokens are retired non-credentials, and they remain private audit provenance rather than runtime input.

## Vertical slices

1. **Health contract:** add `/livez` and `/readyz`, retain `/health` compatibility, and publish readiness without running a market fetch.
2. **HTTP safety:** bounded workers, socket timeout, overload `503`, no-store and browser security headers, generic server identity, and structured production access/error logs.
3. **Production policy:** HTTP live Deribit fetch is default-off and requires an explicit environment gate; production startup validates host, port, worker, timeout, dashboard asset, and fail-closed mode.
4. **Browser contract:** same-origin dashboard only, unique IDs, refresh path, responsive layout, and no console/network errors.
5. **Delivery:** add container/CI/runbook/LF policy, test on the integrated remote baseline, create a clean branch from `origin/master`, sanitize mutable local-only coordination identifiers, document the immutable content-addressed evidence exception, push, and open a draft PR.

## Verification seams

- `python -m crypto_options_report.api --smoke`
- `GET /health`, `GET /livez`, `GET /readyz`
- `GET /dashboard.html`, `GET /research/report`, invalid route/query, overload response
- CLI compact report and alert evaluation
- complete unit/pytest suite and compile walk
- in-app browser desktop and narrow viewport checks, refresh interaction, console and failed-request inspection
- remote branch/commit/tree readback after push

## Completion criteria

- Local and container-style production startup are documented and deterministic.
- All tests and browser checks pass on the final integrated tree.
- Only publishable project material is committed; machine state and generated caches remain local.
- GitHub contains the clean production-readiness branch and a draft PR against the current default branch.

All completion criteria are satisfied. The implementation evidence and the
remaining deployment boundary are recorded in
`docs/operations/production-verification-report.md`.
