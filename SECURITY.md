# Security Policy

## Supported surface

The supported production surface is the research-only HTTP console and its
generated static public tree. Paper, manual, testnet, and live order execution
are not supported and remain fail-closed.

The static public tree is read-only and does not expose account, order, or
sizing paths.

Report vulnerabilities privately through the repository's GitHub Security Advisory flow. Do not include credentials, account data, or private market captures in a public issue.

## Deployment boundary

- Keep the Python service on loopback or a private container network.
- Terminate TLS, authentication, public rate limiting, and request-size limits at a reverse proxy.
- Never expose the container port directly to the public Internet.
- Keep `CRYPTO_OPTIONS_API_ALLOW_LIVE_FETCH` disabled. Capture public data with the CLI and mount a reviewed snapshot instead.
- Inject webhook HMAC secrets through environment or a secret manager, never command-line arguments or repository files.
- `tools/capture-daily.ps1` can push to a separate evidence repo only when `EnableEvidenceRepoSync` / `CAPTURE_DAILY_EVIDENCE_SYNC=true` is explicitly enabled. The repo must already exist, be a clean named-branch git top-level with a configured remote, expose real (non-reparse-point) `snapshots/`, `history/`, `logs/`, and `reports/` directories, and remain outside the product workspace boundary. Sync uses a normal push and never force-pushes.
- The scheduled workflow uploads public-market capture artifacts with 90-day retention as an off-device safety copy. This is not a substitute for the separately owned, versioned evidence repository, and durable backup still requires the separately owned evidence repository; Actions artifacts do not back up captures that exist only on the current laptop.
- Any public health monitor must compare the current time to `publish_edition.stale_after`. Do not rely on a static JSON artifact to mutate its own `is_stale` field over time.
- The scheduled publication workflow withholds the distributable site unless a final public HTTPS `LENSOS_PUBLIC_SITE_ORIGIN`, failure delivery, dead-man heartbeat, and an independently operated `stale_after` monitor are all verified. Special-use/local/IP origins and DNS answers in private or IANA special-purpose IPv4/IPv6 ranges are rejected. Monitoring requires a fresh external `lensos_stale_monitor_attestation.v1` response that binds the exact origin, health contract, endpoint fingerprints, hourly-or-faster cadence, and a recent failure-delivery drill; an operator boolean or same-host self-attestation is not accepted. The accepted allow-listed projection and canonical SHA-256 are retained only in the private publication receipt; tokens and secret URLs are never persisted.
- Each scheduled run writes one allow-listed publication receipt under the private evidence repository's `publications/` directory. The next build validates and projects at most 30 days of those receipts; without that durable input, status output explicitly remains in a collecting state.

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
