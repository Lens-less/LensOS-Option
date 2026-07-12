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

For refreshed data, capture a snapshot outside the web process:

```powershell
python -m crypto_options_report.cli pull-snapshot `
  --instrument-limit 40 `
  --output artifacts/snapshots/btc-chain.json `
  --compact
```

Then restart the service with an operator-controlled snapshot:

```powershell
$env:CRYPTO_OPTIONS_API_SNAPSHOT_FIXTURE = "C:\service-data\btc-chain.json"
```

HTTP-triggered live fetch remains unsupported in the production profile. This prevents browser requests from creating unbounded external workload or altering report semantics.

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
