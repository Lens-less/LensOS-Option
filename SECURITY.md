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

The service intentionally emits `research_only=true`, keeps every trading mode gate closed, and contains no live-order adapter.

## Immutable audit provenance

`docs/automation/archive/options-platform-v1/` and `docs/automation/evidence-store/` preserve exact cutover evidence whose SHA-256 identities are part of the V2 migration fence. They may contain retired internal coordination identifiers and historical machine paths. Those values are not external credentials, are not read by the production service, and must never be reused as authorization.

Keep this repository private while those byte-for-byte audit artifacts are retained. New runtime state, active tokens, credentials, logs, or machine configuration must never be added to either directory. Do not redact an existing content-addressed artifact in place; create a new version and update its digest references through the migration tooling.
