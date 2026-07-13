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

## Container startup

```powershell
docker build -t crypto-options-research-console:local .
docker run --rm --name crypto-options-research-console `
  --publish 127.0.0.1:8000:8000 `
  --read-only `
  --tmpfs /tmp:rw,noexec,nosuid,size=16m `
  crypto-options-research-console:local
```

Publishing on `127.0.0.1` is intentional. Put a same-origin reverse proxy in front of it for TLS, authentication, public rate limiting, body-size limits, and HSTS.

## Data source policy

Production HTTP requests cannot select a fixture, account scenario, evaluation time, instrument limit, or live source. The safe default is a fail-closed no-market report.

For refreshed data, run the public-market sidecar as a separate process. The web process still never performs a live fetch. Prime the operator-owned file once before starting the production API:

```powershell
$sidecarOutput = "C:\service-data\crypto-options\snapshot.json"
New-Item -ItemType Directory -Force -Path (Split-Path $sidecarOutput) | Out-Null
python -m crypto_options_report.snapshot_sidecar `
  --once `
  --output $sidecarOutput `
  --instrument-limit 20 `
  --currency BTC
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
python -m crypto_options_report.snapshot_sidecar `
  --output "C:\service-data\crypto-options\snapshot.json" `
  --interval 10 `
  --instrument-limit 20 `
  --currency BTC `
  --base-url https://www.deribit.com
```

The interval is measured from one completed refresh attempt to the next attempt. The default is 10 seconds so a healthy completed snapshot remains inside the report's 60-second freshness threshold even when collection itself takes time. Keep `--instrument-limit 20`; it is the public ticker request budget, not a request to collect the full venue universe.

Installed wheels also expose the equivalent `crypto-options-snapshot-sidecar` command. The package module form above works consistently in source checkouts, wheels, and the production container.

Each successful or fail-closed public collector result is written with a same-directory temporary file plus atomic replace. `collection_started_at` records when network collection began, `captured_at` records when the complete snapshot became available, and `collection_duration_ms` exposes the elapsed collection cost. Instrument metadata and DVOL requests run concurrently with the bounded ticker pool to avoid serial network latency. An unexpected collection/write exception leaves the previous file intact, emits a redacted structured JSON failure event, waits for the next interval, and retries. `Ctrl-C` emits a clean stop event and exits zero. Logs contain public operational metadata only; the sidecar has no private-account or order path.

The API rereads the configured snapshot path for reports, so atomic sidecar updates become visible without browser-triggered fetches. Do not run multiple sidecars for the same output file. HTTP-triggered live fetch remains unsupported in production.

## Health and readiness

- `GET /livez`: process liveness only.
- `GET /readyz`: configuration, dashboard asset, report schema, and fail-closed mode readiness.
- `GET /health`: compatibility liveness endpoint.

Expected readiness fields:

```json
{
  "service_ready": true,
  "research_only": true,
  "product_release": "NO-GO",
  "live_order_adapter_available": false,
  "runtime_profile": "production"
}
```

A blocked or absent market is still a service-ready, fail-closed report. It must not be mistaken for process failure.

## Operations

- Logs are structured JSON on stderr in production. Collect them with the service manager; rotate outside the process.
- Full capacity returns `503` with `Retry-After: 1`; clients should back off.
- Responses are `no-store`, same-origin, frame-denied, and do not expose the Python version.
- Dashboard requests are same-origin only. Do not add broad CORS or client-selectable API origins.
- Alert webhook secrets come from `ALERT_WEBHOOK_SECRET`; webhook URLs must be HTTPS.
- Snapshot, alert state, and paper-ledger writes use same-directory temporary files plus atomic replace. Run one scheduler writer per state file.

## Verification

```powershell
python -m compileall -q crypto_options_report tools
python -m pytest -q tests/test_market_snapshot_sidecar.py
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
