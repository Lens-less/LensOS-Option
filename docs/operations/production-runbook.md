# Production Runbook

## Supported production posture

This deployment serves a **research-only console**. Service readiness does not authorize trading: every report must continue to show `research_only`, `NO_TRADE`, and product release `NO-GO`. There is no live-order adapter.

The Python process must run on loopback or a private container network behind an authenticated TLS reverse proxy. Direct public exposure is unsupported.

## Native startup

```powershell
$env:CRYPTO_OPTIONS_RUNTIME_PROFILE = "production"
python -m crypto_options_report.api `
  --runtime-profile production `
  --host 127.0.0.1 `
  --port 8000 `
  --max-workers 8 `
  --request-timeout 15
```

Only one instance should own a host/port. Use the service manager's singleton and restart policy; do not run cron-launched duplicate API processes.

The API rejects untrusted `Host` headers by default. Loopback names and addresses are allowed automatically. If a same-origin reverse proxy preserves an external hostname, set a comma-separated exact allowlist such as `$env:CRYPTO_OPTIONS_API_ALLOWED_HOSTS = "research.example.internal"`; do not use wildcards. Mutating requests that carry `Origin` must match the request `Host` authority, including an explicit port. Direct requests accept only the `http` scheme. A TLS reverse proxy must also list each exact external origin, including scheme and port when non-default, for example `$env:CRYPTO_OPTIONS_API_TRUSTED_ORIGINS = "https://research.example.internal"`. This setting has no wildcard or suffix semantics; an invalid entry is ignored.

Non-loopback binds are fail-closed. They require both `CRYPTO_OPTIONS_API_ALLOW_REMOTE=1` and `CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE`, where the configured path is a readable, non-symlink regular file containing exactly one printable ASCII token, no whitespace/control characters, and length `32..256`. On POSIX, use an owner-only or read-only service-group mode (`0400`, `0440`, `0600`, or `0640`). Only `GET /health`, `GET /livez`, and `GET /readyz` remain unauthenticated for probes. Every other path and method, including `404`, `HEAD`, `GET`, `POST`, `DELETE`, and unsupported verbs, requires exactly one `Authorization: Bearer <token>` header before route logic or request-body parsing runs. Duplicate `Host`, `Origin`, or `Authorization` headers are rejected.

If the reverse proxy preserves the caller's bearer header, forward it explicitly:

```nginx
location / {
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_pass http://127.0.0.1:8000;
}
```

If the proxy injects the API bearer itself, source that value from the platform secret store or mounted file rather than checking it into config, command history, or logs.

## Container startup

```powershell
docker build -t crypto-options-research-console:local .
$apiTokenPath = "C:\service-config\crypto-options\api-bearer.token"
New-Item -ItemType Directory -Force -Path (Split-Path $apiTokenPath) | Out-Null
if (-not (Test-Path -LiteralPath $apiTokenPath)) {
  throw "Provision a 32-256 character ASCII bearer token file before remote startup"
}
docker run --rm --name crypto-options-research-console `
  --env CRYPTO_OPTIONS_API_ALLOW_REMOTE=1 `
  --env CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE=/run/secrets/api-bearer.token `
  --mount type=bind,source=$apiTokenPath,target=/run/secrets/api-bearer.token,readonly `
  --publish 127.0.0.1:8000:8000 `
  --read-only `
  --tmpfs /tmp:rw,noexec,nosuid,size=16m `
  crypto-options-research-console:local `
  python -m crypto_options_report.api --runtime-profile production `
    --host 0.0.0.0 --port 8000
```

The image itself defaults to loopback and does not bake in `CRYPTO_OPTIONS_API_ALLOW_REMOTE`. Container bridge publishing therefore requires explicit remote opt-in, a mounted `CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE`, and an explicit `0.0.0.0` command override, as shown above. Publishing the host port on `127.0.0.1` remains intentional. Put a same-origin reverse proxy in front of it for TLS, authentication, public rate limiting, body-size limits, and HSTS. Keep the token file outside the image, mount it read-only, and never print the token in startup logs.

## Data source policy

Production HTTP requests cannot select a fixture, account scenario, evaluation time, instrument limit, or live source. The safe default is a fail-closed no-market report.

For refreshed data, run the public-market sidecar as a separate process. The web process still never performs a live fetch. Prime the operator-owned file once before starting the production API:

```powershell
$sidecarOutput = "C:\service-data\crypto-options\snapshot.json"
New-Item -ItemType Directory -Force -Path (Split-Path $sidecarOutput) | Out-Null
$marketKeyPath = "C:\service-config\crypto-options\market-snapshot-hmac.key"
New-Item -ItemType Directory -Force -Path (Split-Path $marketKeyPath) | Out-Null
if (-not (Test-Path -LiteralPath $marketKeyPath)) {
  $marketKey = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Fill($marketKey)
  [IO.File]::WriteAllBytes($marketKeyPath, $marketKey)
}
$env:CRYPTO_OPTIONS_MARKET_SNAPSHOT_HMAC_KEY_FILE = $marketKeyPath
python -m crypto_options_report.snapshot_sidecar `
  --once `
  --output $sidecarOutput `
  --instrument-limit 20 `
  --currency BTC `
  --complete-feed-graph
```

Point the web process at that exact file, then start it normally:

```powershell
$env:CRYPTO_OPTIONS_API_SNAPSHOT_FIXTURE = $sidecarOutput
python -m crypto_options_report.api `
  --runtime-profile production `
  --host 127.0.0.1 `
  --port 8000
```

Run the continuous sidecar under a separate singleton service-manager unit:

```powershell
$marketKeyPath = "C:\service-config\crypto-options\market-snapshot-hmac.key"
if (-not (Test-Path -LiteralPath $marketKeyPath)) {
  throw "Generate the market key during the prime step before starting the sidecar"
}
$env:CRYPTO_OPTIONS_MARKET_SNAPSHOT_HMAC_KEY_FILE = $marketKeyPath

python -m crypto_options_report.snapshot_sidecar `
  --output "C:\service-data\crypto-options\snapshot.json" `
  --interval 10 `
  --instrument-limit 20 `
  --currency BTC `
  --base-url https://www.deribit.com `
  --complete-feed-graph
```

The interval is measured from one completed refresh attempt to the next attempt. The default is 10 seconds so a healthy completed snapshot remains inside the report's 60-second freshness threshold even when collection itself takes time. Keep `--instrument-limit 20`; it is the public ticker request budget, not a request to collect the full venue universe.

Installed wheels also expose the equivalent `crypto-options-snapshot-sidecar` command. The package module form above works consistently in source checkouts, wheels, and the production container.

Each successful or fail-closed public collector result is written with a same-directory temporary file plus atomic replace. `collection_started_at` records when network collection began, `captured_at` records when the complete snapshot became available, and `collection_duration_ms` exposes the elapsed collection cost. `--complete-feed-graph` also captures bounded order-book, index, funding/basis, DVOL, and exchange-health evidence, then persists consecutive trust observations and up to 288 real rolling samples in `<snapshot>.trust.json`. That separate record binds the exact snapshot digest and is authenticated with HMAC-SHA256 using the market-domain key file. Embedded snapshot claims, unsigned/forged state, stale state, or any post-load snapshot change are ignored. Keep the exactly 32-byte key file outside the snapshot writer's output directory and grant it only to the market sidecar and API service identity. Without the key, snapshots remain readable for research but cannot promote trust or readiness. Instrument metadata and DVOL requests run concurrently with the bounded ticker pool to avoid serial network latency. An unexpected collection/write exception leaves the previous file intact, emits a redacted structured JSON failure event, waits for the next interval, and retries. `Ctrl-C` emits a clean stop event and exits zero. Logs contain public operational metadata only; the public sidecar has no private-account or order path.

The short REST observation window promotes authenticated research-snapshot trust only. WebSocket gap/resync, soak, and calendar evidence remain future external release work; the current runtime does not synthesize those observations or expose a second pseudo production gate. Product release is governed only by the explicit external authorization state and remains `NO-GO`.

Private account evidence uses a separate read-only sidecar. The key must grant exactly `account:read` and `trade:read`; any `read_write` scope is rejected before private collection. Keep the credentials in the sidecar service environment only:

```powershell
$env:DERIBIT_CLIENT_ID = "<local-secret>"
$env:DERIBIT_CLIENT_SECRET = "<local-secret>"
$accountKeyPath = "C:\service-config\crypto-options\account-snapshot-hmac.key"
New-Item -ItemType Directory -Force -Path (Split-Path $accountKeyPath) | Out-Null
if (-not (Test-Path -LiteralPath $accountKeyPath)) {
  $accountKey = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Fill($accountKey)
  [IO.File]::WriteAllBytes($accountKeyPath, $accountKey)
}
$env:CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_HMAC_KEY_FILE = $accountKeyPath
python -m crypto_options_report.account_snapshot_sidecar `
  --output "C:\service-data\crypto-options\account.json" `
  --interval 15 `
  --currency BTC
```

The sidecar sends `public/auth` as a JSON-RPC POST whose credentials are in the request body, never the URL. Private calls carry the access token only as `Authorization: Bearer <token>`. The transport refuses every redirect so credentials and bearer tokens cannot cross origins. The sanitized account JSON omits credentials, access tokens, raw account identifiers, order ids, and labels.

The account sidecar also writes `<account>.auth.json`, which authenticates the exact sanitized payload with the separate account-domain, exactly 32-byte HMAC key. Never reuse the market key for the account domain. Keep the account key outside the account output directory and grant it only to the account sidecar and API service identity. A hand-written JSON document that merely claims `deribit_live_private_read_only` provenance is accepted as research input only; it never contributes to production readiness. Configure the API with `CRYPTO_OPTIONS_ACCOUNT_SNAPSHOT_FIXTURE`; never pass Deribit credentials into the Web process. Configure `CRYPTO_OPTIONS_BACKTEST_ARTIFACT_DIR` and add `CRYPTO_OPTIONS_HISTORICAL_FIXTURE` only after an authorized historical source is validated. Calibration/model promotion and paper/manual workflow remain unimplemented/unsupported; do not configure or claim persistence for them.

The API rereads the configured snapshot path for reports, so atomic sidecar updates become visible without browser-triggered fetches. Do not run multiple sidecars for the same output file. HTTP-triggered live fetch remains unsupported in production.

## Health and readiness

- `GET /livez`: process liveness only.
- `GET /readyz`: service contract plus provider, authenticated research-trusted snapshot, authenticated account, store, queue, and model dependency readiness. Production returns `503` until every dependency is usable; this remains distinct from liveness.
- `GET /health`: compatibility liveness endpoint.

Expected readiness fields:

```json
{
  "ready": false,
  "service_ready": true,
  "dependencies_ready": false,
  "market_provider_ready": false,
  "last_trusted_snapshot_ready": false,
  "market_data_ready": false,
  "account_data_ready": false,
  "store_ready": false,
  "queue_ready": false,
  "model_ready": false,
  "reason_codes": [
    "MARKET_PROVIDER_NOT_READY",
    "MARKET_DATA_NOT_READY",
    "ACCOUNT_DATA_NOT_READY",
    "BACKTEST_STORE_NOT_READY",
    "BACKTEST_QUEUE_NOT_READY",
    "MODEL_NOT_READY"
  ],
  "research_only": true,
  "product_release": "NO-GO",
  "live_order_adapter_available": false,
  "runtime_profile": "production"
}
```

`service_ready` says the application can still render a safe fail-closed report. `ready` is the production traffic gate: a blocked, stale, unsigned, unbound, or absent evidence dependency keeps it false and the endpoint returns `503`. The current calibration/model implementation is explicitly unavailable, so `model_ready` remains false and production readiness remains `503`; this is an honest release blocker, not a service crash. Use `/livez`, not `/readyz`, for process-health restarts.

## Operations

- Logs are structured JSON on stderr in production. Collect them with the service manager; rotate outside the process.
- Full capacity returns `503` with `Retry-After: 1`; clients should back off.
- Responses are `no-store`, same-origin, frame-denied, and do not expose the Python version.
- Dashboard requests are same-origin only. Do not add broad CORS or client-selectable API origins.
- Alert webhook secrets come from `ALERT_WEBHOOK_SECRET`; webhook URLs must be HTTPS and the client refuses every redirect. Signed requests include `X-Webhook-Timestamp`, `X-Webhook-Delivery-Id`, and `X-Signature-SHA256`. The signature is HMAC-SHA256 over `timestamp.delivery_id.body` using the exact transmitted body bytes. Receivers must enforce a short timestamp-skew window and reject a repeated delivery id within that window.
- Snapshot and alert-state writes use same-directory temporary files plus atomic replace. Run one scheduler writer per state file.
- Report, dashboard, and readiness GET requests are read-only. The current paper/manual status is unsupported and performs no ledger write.
- Backtest submission requires strict JSON and `Idempotency-Key`, returns `202`, and executes in a bounded worker queue plus a hard-timeout subprocess. Poll `/backtest/jobs/{job_id}`; failed or timed-out work cannot promote the default result, and result reads never recompute the replay.

## Verification

```powershell
python -m compileall -q crypto_options_report tools
python -m pytest -q tests/test_market_snapshot_sidecar.py tests/test_public_feed_graph_runtime.py tests/test_account_snapshot_sidecar.py
python -m pytest -q
python -m crypto_options_report.api --runtime-profile development --smoke
python -m pip wheel --no-deps . -w dist
curl.exe -sS http://127.0.0.1:8000/livez
curl.exe -sS http://127.0.0.1:8000/readyz
curl.exe -sS -D - -o NUL http://127.0.0.1:8000/research/report
```

The final browser pass must cover desktop and mobile widths, report refresh, JSON endpoints, `404`, production query rejection, console errors, and failed network requests.

## Rollback

Stop the new process, restore the previous immutable image or Git commit, and restart it on the same private port. Do not roll back by enabling live fetch or relaxing mode gates. Confirm `/readyz` and the dashboard both still report the research-only `NO-GO` posture.
