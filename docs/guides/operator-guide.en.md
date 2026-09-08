# Operator Guide

[Project home](../../README.en.md) · [Documentation](../README.md) · [中文](operator-guide.md)

Commands below run from the repository root after installing the package. Operational actions require the configured services described in the runbooks.

## Operator Lane (Windows-only, optional)

This section, plus the daily capture and scheduled-task instructions below,
exists for maintainers of a continuously running public instance. It depends on
PowerShell and optional private evidence storage and hosting; none of it is a
quickstart or contribution prerequisite.

### Static Public Edition and Publishing

The public site does not call Deribit or any credentialed service. The daily
task first freezes the market snapshot, underlying history, DVOL history, and
research artifacts with
[`tools/capture-daily.ps1`](../../tools/capture-daily.ps1), then publishes the
whitelisted report and frontend as a pure static directory:

```powershell
$siteOrigin = $env:LENSOS_PUBLIC_SITE_ORIGIN
if ([string]::IsNullOrWhiteSpace($siteOrigin)) {
  throw 'Set LENSOS_PUBLIC_SITE_ORIGIN to the final owned HTTPS origin.'
}

crypto-options-report publish `
  --snapshot artifacts/snapshots/btc-series/<capture>.json `
  --underlying-history artifacts/history/btc-daily.json `
  --dvol-history artifacts/history/btc-dvol.json `
  --signal-artifact artifacts/reports/signal-preflight.json `
  --series-artifact artifacts/reports/series-history.json `
  --publication-history artifacts/reports/publication-history.json `
  --web-build web/dist-public `
  --site-origin $siteOrigin `
  --out dist/site --published-at <UTC-RFC3339> --git-sha <commit>
```

`--site-origin` must be the final owned HTTPS origin—no path, query,
credentials, or non-default port. It becomes the canonical share URL and the
base for `robots.txt` and `sitemap.xml`. The publisher rejects `example.*`,
`.invalid`, `.alt`, localhost, single-label hosts, and IP literals; the formal
workflow additionally rejects hosts resolving to IANA special-purpose or
non-public addresses. Until the final origin exists, build and test
`web/dist-public` without generating a publication tree carrying false
canonical metadata.

The output tree targets the Cloudflare Pages `_headers` contract. The publisher
fails closed if a quality gate fails, the VRP history is insufficient, or the
report contains account / position / order fields. The browser uses the edition's
`stale_after` deadline; after expiry, it shows "publication halted". See the
[public API](../api-public.md) and
[static publishing runbook](../operations/public-publishing.md) for the full
contract.

The public bundle contains only the public observatory's static pages and JSON.
It does not include the workbench or the Chrome companion.

`research_publication` only answers "can this static research be published";
`execution_authorization` only answers "can the system be used for trading
execution". They do not upgrade each other, and the latter is permanently
`NO-GO`.

#### Operator capture and scheduled task (Windows-only)

The daily capture and Windows scheduled task below are an optional operations
lane, not part of the newcomer quickstart. Capture once per day, with filenames
based on capture time so they do not overwrite each other:

```powershell
crypto-options-report pull-snapshot --currency BTC `
  --output-dir artifacts/snapshots/btc-series --compact
```

`tools/capture-daily.ps1` wraps this step together with the underlying-history
refresh. **The history has to refresh too**: it provides a `daily_close_proxy`
for expired contracts, not the exchange's settlement-window average. Stale
history leaves recent cohorts without that proxy. Register the daily task at
17:00 on an Asia/Shanghai host, after
the 08:00 UTC settlement time used by the research protocol:

```powershell
$repo = "C:\path\to\Option"
$evidenceRepo = "C:\path\to\LensOS-Option-Evidence"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$repo\tools\capture-daily.ps1`" -RepoRoot `"$repo`" -CaptureOrigin local_windows_scheduler -EnableEvidenceRepoSync -EvidenceRepoRoot `"$evidenceRepo`" -EvidenceRepoRemote origin -HistoryDays 1200 -DvolHistoryDays 1095" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At 17:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 45) `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName "LensOS-Option-DailyCapture" `
  -Action $action -Trigger $trigger -Settings $settings -Force
```

Failure delivery and the success dead-man ping read
`CAPTURE_DAILY_FAILURE_WEBHOOK_URL` and
`CAPTURE_DAILY_SUCCESS_HEARTBEAT_URL`. Do not place webhook URLs directly in
scheduled-task arguments that other local users may inspect; inject them into
the dedicated task account instead. An external monitor must also fetch the
published `health.json` and compare `stale_after`; the success ping does not
replace that independent positive check.

The summary and both notification payloads include `usable_for_validation`,
usability reason codes, and consecutive usable/unusable day counts. Two
consecutive capture days that fail to advance validation trigger the failure
webhook even when the process itself exits successfully. If snapshot capture
fails, the independent underlying and DVOL history refreshes still run.

The selected second capture point is the GitHub Actions `08:10 UTC` lane,
identified as `github_actions_0810_utc`. After the private evidence repository
and both notification endpoints are configured, verify three consecutive days
from immutable receipts. `$evidenceRepo` must be the clean top-level of the
private Git repository, with its current named branch fully pushed to `origin`;
the verifier checks every receipt and snapshot blob in that live remote commit.
Exit codes `0/10/11` mean accepted/collecting/invalid:

```powershell
python tools/check-dual-capture-acceptance.py `
  --evidence-root $evidenceRepo `
  --required-origin local_windows_scheduler `
  --required-origin github_actions_0810_utc `
  --days 3
```

Capture logs go to `artifacts/logs/capture-daily.log`. Running more than once in
the same day is safe: the validator deduplicates by "date x contract" and
reports how many duplicates it dropped.

**Count actual qualified, settled cohorts; do not promise completion from run
counts or calendar days.** Expiry distribution, missed captures, bad quotes,
and missing history affect accumulation. Longitudinal series/preflight isolates
failed expiries while retaining healthy cohorts; full reports and publication
retain whole-snapshot gates. Do not lower quality or independent-sample
thresholds to accelerate acceptance.

Use preflight while waiting to see whether the capture is actually producing
observations - **captures cannot be backfilled, so every undetected flaw wastes
time**:

```powershell
crypto-options-report validate-signal --preflight `
  --snapshot-dir artifacts/snapshots/btc-series `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/signal-preflight.json --compact
```

It lists settled / unsettled cohorts, how many observations each can
contribute, and what is blocking them.

You can read the artifact in the Evidence Console instead of rerunning commands
and staring at JSON:

```powershell
python -m crypto_options_report.api --replay `
  --snapshot-fixture <snapshot> --underlying-history-fixture artifacts/history/btc-daily.json `
  --signal-artifact artifacts/reports/signal-preflight.json
```

Once enough cohorts exist:

```powershell
crypto-options-report validate-signal `
  --snapshot-dir artifacts/snapshots/btc-series `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

When samples are still insufficient it returns `blocked` and says how far off
you are - **that is normal, not a failure**.

It measures 10 candidate signals at once (three flavors of smile residual, IV
minus realized vol, IV minus DVOL, term premium, local skew, open-interest
share, depth imbalance, and quote width), and it includes a **collinearity
report**: counting signals is not the same as counting information. Any signal
that looks like "IV minus a same-day constant" has the same within-day rank
ordering - DVOL minus and historical-vol minus are the same sort wearing two
different shirts. `distinct_signal_estimate` tells you how many genuinely
different orderings remain.

## Production

Split public market data, private read-only account access, and the web API into
three processes: credentials live only in the sidecar processes, and the API
process reads redacted JSON. Production HTTP forbids browser-supplied fixtures,
account scenarios, evaluation clocks, and live fetches.

The service binds to loopback by default and must sit behind an authenticating
TLS reverse proxy. Never expose it directly to the internet.

Container setup, health checks, HMAC key management, key rotation, rollback, and
verification steps are in the
**[production runbook](../operations/production-runbook.md)**; the environment
variable reference is [`.env.example`](../../.env.example).
