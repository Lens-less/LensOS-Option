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
- In a private operator repository, the scheduled workflow can upload public-market capture artifacts with 90-day retention as an off-device recovery copy. The step requires GitHub to report `repository.private == true`; it is not an upload path for the public source repository. Before changing any private repository's visibility, inventory and remove or privately archive its historical workflow artifacts/runs. Raw capture is not implicitly a public CC BY release; durable backup still requires the separately owned evidence repository.
- Any public health monitor must compare the current time to `publish_edition.stale_after`. Do not rely on a static JSON artifact to mutate its own `is_stale` field over time.
- The scheduled publication workflow withholds the distributable site unless a final public HTTPS `LENSOS_PUBLIC_SITE_ORIGIN`, failure delivery, dead-man heartbeat, and an independently operated `stale_after` monitor are all verified. Special-use/local/IP origins and DNS answers in private or IANA special-purpose IPv4/IPv6 ranges are rejected. Monitoring requires a fresh external `lensos_stale_monitor_attestation.v1` response that binds the exact origin, health contract, endpoint fingerprints, hourly-or-faster cadence, and a recent failure-delivery drill; an operator boolean or same-host self-attestation is not accepted. The accepted allow-listed projection and canonical SHA-256 are retained only in the private publication receipt; tokens and secret URLs are never persisted.
- Each scheduled run writes one allow-listed publication receipt under the private evidence repository's `publications/` directory. The next build validates and projects at most 30 days of those receipts; without that durable input, status output explicitly remains in a collecting state.

The service intentionally emits `research_only=true`, keeps every trading mode gate closed, and contains no live-order adapter.

## Repository hygiene

The public development repository is
[`Lens-less/LensOS-Option`](https://github.com/Lens-less/LensOS-Option). The earlier
private archive has a separate history. The
[one-time cutover checklist](docs/operations/public-release-cutover.md) documents
that boundary and the fallback of publishing clean history into a separate
repository; it is not a requirement to repeat a history rewrite for every release.

Internal coordination artifacts, machine paths, and retired operational records
belong to the private archive and are not supported product inputs. Keep archive
branches, tags, pull-request refs, and old clone history isolated. Never merge
them into the public history. When transferring needed changes from an old
workspace, review the file changes and apply them on the public baseline without
importing archive ancestry. Check the actual remote URL before any push; a local
remote named `origin` is not evidence that it is the public destination.

Any newly discovered sensitive material must be assessed in all affected refs,
workflow artifacts, and cached views. Follow GitHub's removal process, including
Support where necessary; deleting a file in a new commit does not erase history.

Never commit runtime state, active tokens, credentials, logs, or machine
configuration.
