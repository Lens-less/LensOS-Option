# Security Policy

## Supported surface

The supported production surface is the research-only HTTP console. Paper, manual, testnet, and live order execution are not supported and remain fail-closed.

Report vulnerabilities privately through the repository's GitHub Security Advisory flow. Do not include credentials, account data, or private market captures in a public issue.

## Deployment boundary

- Keep the Python service on loopback or a private container network.
- Terminate TLS, authentication, public rate limiting, and request-size limits at a reverse proxy.
- Never expose the container port directly to the public Internet.
- Keep `CRYPTO_OPTIONS_API_ALLOW_LIVE_FETCH` disabled. Capture public data with the CLI and mount a reviewed snapshot instead.
- Inject webhook HMAC secrets through environment or a secret manager, never command-line arguments or repository files.
- `tools/capture-daily.ps1` can push to a separate evidence repo only when `EnableEvidenceRepoSync` / `CAPTURE_DAILY_EVIDENCE_SYNC=true` is explicitly enabled. The repo must already exist, already have a configured remote, and already be outside the product workspace boundary.
- The scheduled workflow uploads public-market capture artifacts with 90-day retention as an off-device safety copy. This is not a substitute for the separately owned, versioned evidence repository, and durable backup still requires the separately owned evidence repository; Actions artifacts do not back up captures that exist only on the current laptop.
- Any public health monitor must compare the current time to `publish_edition.stale_after`. Do not rely on a static JSON artifact to mutate its own `is_stale` field over time.
- 30-day status history requires persisted evidence artifacts outside a single CI workspace. Without that external evidence input, status output can only describe the current published edition honestly.

The service intentionally emits `research_only=true`, keeps every trading mode gate closed, and contains no live-order adapter.

## Repository hygiene

Internal build-process coordination artifacts (agent handoffs, a content-addressed
evidence store, and controller state) were removed from the working tree on
2026-07-26 and are excluded by `.gitignore`. They contained retired internal
identifiers and historical machine paths — not external credentials — and were
never read by the production service.

Those artifacts remain reachable in git history prior to that cleanup. Before
making this repository public, rewrite history to purge them, or accept that the
retired internal identifiers stay visible in old commits.

Never commit runtime state, active tokens, credentials, logs, or machine
configuration.
