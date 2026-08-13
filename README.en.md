# Crypto Options Research Console

English · [中文](README.md)

[![CI](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml/badge.svg)](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
![Python >=3.12](https://img.shields.io/badge/Python-%3E%3D3.12-3776AB?logo=python&logoColor=white)

A **pre-entry research tool for crypto options**. It reads public Deribit
market data, decides whether there is currently an option-selling opportunity
worth considering, and lays out every piece of evidence that conclusion rests
on.

It is built for **option sellers who make their own decisions** - people who
want an auditable, replayable pre-entry analysis rather than a black box that
trades for them.

**What it does not do:** it does not connect to any order endpoint, does not
recommend a position size, and performs no automated or semi-automated
execution. The ceiling on trusted output is an admission decision with
`execution_allowed=false`. This is a deliberate product boundary, not a backlog
item.

Two properties define it:

- **Evidence-first** - every conclusion traces to specific evidence. A number
  with no evidence behind it is never invented; it is explicitly reported as
  missing.
- **Fail-closed** - missing, expired, or unverifiable evidence always degrades
  to "blocked". **No signal is not the same as permission to proceed.**

## Two Ways To Use It

| Surface | Purpose |
| --- | --- |
| **Web research workbench** | Screen, rank, and compare candidates side by side; inspect every score component and payoff curve. Where mining and understanding happen. |
| **Chrome research companion** | Answers, in place on a Deribit page, "does the contract I am looking at have edge, and is there a better one on this chain?" |

The CLI and HTTP API are the **local engine interfaces** driving those two
surfaces. They are not standalone products.

The public static bundle contains only the evidence site and legal pages. The
workbench and Chrome companion remain internal / local surfaces and are not
part of the public bundle.

## Public Release

- Code is licensed under `Apache-2.0`; see [`LICENSE`](LICENSE).
- Public data artifacts and generated public research content are licensed
  under `CC BY 4.0`; see [`LICENSE-DATA`](LICENSE-DATA).
- The public static pages are Chinese-first; English mirrors, if published, live
  under `/en/`.
- Public headlines are published from already-closed daily data and are
  intentionally one day behind capture day.
- The eight-stage workflow is kept as secondary disclosure on the methodology
  page, not as the homepage narrative.
- This repository does not claim that a public domain, external heartbeat, or
  separate evidence repository is already configured; those are deployment
  contracts described in the runbooks.

## Quickstart

Requires Git and Python 3.12 or newer. There are no third-party runtime
dependencies, and this path needs no credentials, locally captured output, or
owner infrastructure.

```powershell
git clone https://github.com/Lens-less/LensOS-Option.git
Set-Location LensOS-Option
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade -c constraints.txt pip setuptools
python -m pip install --no-build-isolation -c constraints.txt -e ".[test]"
python -m pytest -q
```

Run one deterministic analysis against the bundled fixture:

```powershell
python -m crypto_options_report.cli analysis `
  --snapshot-fixture tests/fixtures/deribit_btc_option_chain_snapshot.json `
  --generated-at 2026-07-07T00:01:30Z --compact
```

Start the local service and open the evidence console. To read a recorded
snapshot in a browser, you must add `--replay`:

```powershell
python -m crypto_options_report.api --host 127.0.0.1 --port 8000 --replay `
  --snapshot-fixture tests/fixtures/deribit_btc_option_chain_snapshot.json
```

Then visit <http://127.0.0.1:8000/evidence>.

`--replay` pins the evaluation clock to the snapshot's own capture time. Without
it, any recorded file older than 60 seconds is blocked by freshness checks - the
CLI has always done this via `--generated-at` defaulting to `captured_at`, but
the HTTP side used to have no equivalent. **Replay makes every freshness number
on the page look like "now"**, so it is a startup parameter, not a browser
parameter, and every surface shows an unclosable replay banner with the pinned
time.

Without `--replay`, the service runs in real-time mode and expired snapshots are
blocked as-is.

> **Seeing lots of "unavailable" and "missing" on a first run is expected.**
> With no market data source configured, the product refuses to fabricate
> values. Empty states list what is missing and the exact command needed to
> fill it.
>
> Likewise, `/readyz` returns `503` under the production profile: no model has
> been promoted, so the readiness gate stays closed by design. **That does not
> mean the process is unhealthy** - `/livez` reports process liveness.

## Operator Lane (Windows-only, optional)

This section, plus the daily capture and scheduled-task instructions below,
exists for maintainers of a continuously running public instance. It depends on
PowerShell and optional private evidence storage and hosting; none of it is a
quickstart or contribution prerequisite.

### Static Public Edition and Publishing

The public site does not call Deribit or any credentialed service. The daily
task first freezes the market snapshot, underlying history, DVOL history, and
research artifacts with
[`tools/capture-daily.ps1`](tools/capture-daily.ps1), then publishes the
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
report contains account / position / order fields; once browser-visible data is
older than 48 hours, the site enters a "publication halted" state. See the
[public API](docs/api-public.md) and
[static publishing runbook](docs/operations/public-publishing.md) for the full
contract.

The public bundle contains only the public observatory's static pages and JSON.
It does not include the workbench or the Chrome companion.

`research_publication` only answers "can this static research be published";
`execution_authorization` only answers "can the system be used for trading
execution". They do not upgrade each other, and the latter is permanently
`NO-GO`.

## Core Concepts

Read these first (full definitions live in the [glossary](docs/glossary.md),
which is written in Chinese):

| Term | Meaning |
| --- | --- |
| `research_only` | The fixed output mode: research only, never an order instruction. No configuration changes it. |
| Mode gate | The checkpoint blocking out-of-bounds output - trade recommendations, sizes, and order instructions. |
| `AnalysisRecord` | The **immutable** record of one analysis; the carrier of trusted output. |
| `EntryAdmissionDecision` | The **ceiling** on trusted output: "may this be considered for entry", always `execution_allowed=false`. |
| Evidence class | Evidence trust level: `trusted` / `degraded` / `untrusted` / `missing`. |
| Replay | Same snapshot + same explicit clock => byte-identical output, so any conclusion can be independently re-checked. |

## Current Status

| Capability | Status |
| --- | --- |
| Local deterministic / replay research toolchain | **GO** |
| Publisher-verified static research artifacts | **GO** |
| Paper / manual trading, order submission, real account execution | **NO-GO** |
| Calibration and model promotion | Not implemented; the spec is final and the axis was pre-registered (see [model-promotion.md](docs/model-promotion.md)) |
| Trading execution authorization | **NO-GO (permanent)** |

WebSocket gap/resync, 24-hour soak, and seven consecutive days of evidence are
still internal run / execution readiness requirements. They do not block static
research publication that satisfies data-quality, reproducibility, and privacy
boundaries, and the static release does not relax them.

## Usage

### Finding candidates with edge

The product's central question is "which strike on this chain is best priced
right now". It answers in two layers that must not be conflated:

- **Relative value** - is this strike rich or cheap against its own smile.
  Needs only the current chain.
- **Absolute expected value** - credit minus expected payout minus fees. Needs
  the underlying's realized-return distribution.

Capture underlying history first (public data, no credentials):

```powershell
crypto-options-underlying-history --currency BTC --days 1200 `
  --output artifacts/history/btc-daily.json --horizon-days 7 --horizon-days 18
```

It reports how many **independent** windows each holding period has. Horizons
without enough windows are blocked rather than given a precise-looking number
that the sample cannot support.

```powershell
crypto-options-report scan `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

Ranking uses a **Pareto frontier plus a published lexicographic tie-break** - no
weighted sum, because weighting incommensurable components asserts a relative
importance nothing has established. Dominated candidates carry which rival beat
them and on which axes. When the frontier swallows nearly everything, the
`frontier_occupancy` field says so honestly.

> **Sample size means independent, non-overlapping windows.** An 18-day horizon
> over 1200 daily observations yields 1183 overlapping windows but only 66
> independent ones. Using the former overstates confidence by roughly 18x.

### Candidate Universe

The universe covers both calls and puts. Structures are expressed as a **signed
set of legs**, not as a structure name, so terminal payoff, max loss, and
position greeks are computed by the same code for every combination:

| Structure | Risk |
| --- | --- |
| `naked_short_calls` | Unbounded (`max_loss` is `None`, so downstream ratios cannot be formed) |
| `call_credit_spreads` | Finite |
| `put_credit_spreads` | Finite |
| `iron_condors` | Finite, both sides |

The table names are published by `structure_types` in the report. Consumers do
not need to hard-code them.

### What happens if you combine these?

`combination_risk` treats the frontier candidates as a hypothetical book, one
structure each, **without any notion of size**:

- **No joint max loss across expiries** - it only publishes a labeled upper
  bound, the sum of each member's worst case. Only when all legs share the same
  expiry does it compute a true joint payoff.
- Net vega appears alongside **vega split by expiry** because the net number
  implicitly assumes a parallel volatility shift.
- Marginal contribution is computed by "remove this member" rather than by the
  member's own worst case.

### Is this strike still that expensive yesterday?

Daily capture started as a way to accumulate validation samples, but it also
answers a different question.

```powershell
crypto-options-report series-history `
  --snapshot-dir artifacts/snapshots/btc-series --compact
```

`tools/capture-daily.ps1` rebuilds that artifact after every capture. Feeding it
to the engine via `--series-artifact` shows a **contract x capture day**
heatmap of standardized residuals.

Three deliberate choices:

- **Standardized residuals instead of raw IV.** Every day a contract gets closer
  to expiry, IV, delta, and premium move for reasons unrelated to mispricing.
  Only values normalized by each expiry's residual scale are comparable across
  days.
- **A missing capture is not zero.** The collector samples about one hundred
  contracts from a few hundred listed ones, and the set drifts with spot.
  Empty cells mean "not captured", filled cells mean observed; they never
  impersonate each other.
- **Ranking by shrinkage toward zero.** Otherwise contracts that appear on only
  three days would float to the top on the back of three reads - exactly the
  sample-size error this project tries to avoid. The shrinkage constant is
  published.

> **Persistently positive does not automatically mean opportunity.** A residual
> that stays positive can also mean the secondary fit cannot keep up with the
> true wing at that strike. Both situations look the same on the chart, so the
> sentence sits **above** the chart.

### What can this ranking predict?

**First, the hard data constraint:** Deribit's public API **does not publish
historical option chains**. `get_instruments(expired=true)` only returns a
recent batch of expired contracts (in practice, one expiry day for the capture
in this repo), and per-contract TradingView candles only exist for contracts
that traded, with no IV or bid/ask book. So this validation **cannot backfill**.
It has to start today, capture every day, and wait for contracts to expire
naturally.

#### Operator capture and scheduled task (Windows-only)

The daily capture and Windows scheduled task below are an optional operations
lane, not part of the newcomer quickstart. Capture once per day, with filenames
based on capture time so they do not overwrite each other:

```powershell
crypto-options-report pull-snapshot --currency BTC --instrument-limit 64 `
  --output-dir artifacts/snapshots/btc-series --compact
```

`tools/capture-daily.ps1` wraps this step together with the underlying-history
refresh. **The history has to refresh too**: it provides settlement prices for
each expired expiry, and stale history will silently drop the most recently
settled cohort. Register it as a daily scheduled task (local 17:00, after
Deribit's 08:00 UTC settlement):

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
from immutable receipts. Exit codes `0/10/11` mean accepted/collecting/invalid:

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

**Expect about 2 months, not a few weeks, to reach 8 cohorts.** The 7-35 day
window carries only three expiries at a time, and new weekly expiries arrive one
per week. Deribit does have 1-5 day daily expiries, but in this repo's captured
data they fail the quality gate (`INVALID_BID_IV` /
`INSUFFICIENT_VALID_QUOTES`). Longitudinal series/preflight consumers now
quarantine only the failed expiry while retaining healthy cohorts; full-chain
reports and public publishing still block on the whole-snapshot verdict, and no
threshold was relaxed. The capture window therefore remains 7-35 days instead
of trading data quality for validation speed.

Use preflight while waiting to see whether the capture is actually producing
observations - **captures cannot be backfilled, so every undetected flaw wastes
time**:

```powershell
crypto-options-report validate-signal --preflight `
  --snapshot-dir artifacts/snapshots/btc-series `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
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

### EV is negative - which kind of negative?

A negative expected value can mean three different things, and they call for
different responses: the sample period happened to include a bad regime for
sellers; edge exists but sits inside the spread; or the shape is simply bad and
the other direction is the interesting one.

```powershell
crypto-options-report ev-robustness `
  --snapshot-fixture artifacts/snapshots/btc-series/<capture>.json `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

It splits the problem into **execution sensitivity** (buy / sell, bid / mid /
ask) and **period sensitivity** (recompute on continuous historical slices and
see whether the sign flips). Expected payout does not depend on entry price, so
the four execution variants are arithmetic on the same path replay; only the
slices need extra work.

`verdict` only names what the numbers show: `sign_flips_across_periods`,
`no_capturable_edge_at_the_touch` (fair value between bid and ask - normal
market, not a discovery), `other_direction_is_positive`, and
`negative_across_periods_and_execution`.

It uses the **production code path itself** to generate daily candidates and
match them with realized post-expiry PnL, then publishes bin tables and an
information coefficient. Two choices determine whether it is worth trusting:

- **Sample size is counted by expiry cohort, not by observation count.**
  Consecutive snapshots are the same contracts and the same settlement price.
- **Correlation is moneyness-neutralized first.** The raw correlation is
  dominated by moneyness - a signal equivalent to "sort by strike" can score
  0.95 IC in a control group with no mispricing information. The raw value is
  still shown alongside the neutralized one so you can see how large the
  confound is.

The ranking axis itself is also measured, and the outcome can be
`no_detectable_edge`. **That is the point.**

**Only one axis can be promoted from this sample.** On 2026-07-27, when 0/8
cohorts had settled, `smile_residual_z` was pre-registered with a threshold of
`|t| >= 2.0`. The other nine signals are exploratory - even if one has a better
score, it can only inform the next registration, not be promoted from this
sample. The reason is multiple comparison risk: with roughly 7 distinct orderings
in the same sample, picking the top one and promoting it gives noise a real
chance to win. The registration is published with the validation artifact
(`pre_registration`), and the UI marks the registered axis separately from the
highest-scoring exploratory axis in this sample.

### CLI (internal plumbing)

```powershell
# Capture a live public snapshot for offline analysis
python -m crypto_options_report.cli pull-snapshot --instrument-limit 20 `
  --output artifacts/snapshots/btc-chain.json --compact

# Produce a report from a snapshot; exit code 10 when market data is blocked
python -m crypto_options_report.cli report `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --output artifacts/reports/latest.json --fail-on-blocked --compact

# Research-only risk alerts (no order path of any kind)
python -m crypto_options_report.cli alert-eval `
  --snapshot-fixture artifacts/snapshots/btc-chain.json --dry-run --compact
```

Scheduler exit codes: `0` success · `10` market data blocked / missing · `11`
alerts fired · `1` hard error. See `crypto-options-report --help` for examples.

### HTTP API and Evidence Console

The console and the API are **same-origin by construction**, so no cross-origin
configuration or browser parameter can change production report semantics. The
server builds one `AnalysisRecord` per input set; every GET projection reuses
it rather than refetching data or recomputing conclusions.

Main endpoints: `/evidence` (console) · `/research/report` · `/analysis/result`
· `/health` · `/livez` · `/readyz`. Full list, auth requirements, and response
contracts are in the [API reference](docs/api-reference.md).

### Chrome research companion (personal, local)

A Manifest V3 side panel for Chrome 114+, intended for personal local use:

```powershell
cd web
npm ci
npm run build:extension
```

In `chrome://extensions`, enable Developer mode -> "Load unpacked" -> select
`web/dist/chrome-extension/`, then click the toolbar icon on a Deribit page.

The side panel only reads `http://127.0.0.1:<port>/research/report`. It
identifies the current Deribit contract and shows research context; it contains
**no order, trade, quantity, or sizing controls**. Contract context is isolated
per tab.

## Production

Split public market data, private read-only account access, and the web API into
three processes: credentials live only in the sidecar processes, and the API
process reads redacted JSON. Production HTTP forbids browser-supplied fixtures,
account scenarios, evaluation clocks, and live fetches.

The service binds to loopback by default and must sit behind an authenticating
TLS reverse proxy. Never expose it directly to the internet.

Container setup, health checks, HMAC key management, key rotation, rollback, and
verification steps are in the
**[production runbook](docs/operations/production-runbook.md)**; the environment
variable reference is [`.env.example`](.env.example).

## Development

```powershell
python -m pytest -q
python -m ruff check crypto_options_report tools tests

cd web
npm ci && npm test && npm run lint && npm run build
```

`npm run build` updates `crypto_options_report/static/evidence/`. That build
output ships inside the wheel and the container and **must be committed along
with the source** - CI verifies the two match.

Contribution workflow and design red lines: [CONTRIBUTING.md](CONTRIBUTING.md).

## Project Map

| Path | Responsibility |
| --- | --- |
| `crypto_options_report/analysis_run.py` | Immutable mandate, evidence, strategy, and admission contracts |
| `crypto_options_report/contract.py` | The `research_report.v1` compatibility projection |
| `crypto_options_report/api.py` | Stdlib HTTP API, `/evidence`, and legacy URL aliases |
| `crypto_options_report/market_data.py` | Deribit access, snapshot normalization, quality gates |
| `crypto_options_report/structures.py` | Multi-leg structures: terminal payoff, risk bounds, position greeks |
| `crypto_options_report/signal_validation.py` | Predictiveness metrics for ranking signals (bin tables and IC) |
| `crypto_options_report/combination_risk.py` | Portfolio aggregation and marginal risk |
| `crypto_options_report/_canonical.py` | The single canonical JSON encoding behind every digest |
| `web/` | Shared report boundary, Evidence Console, Chrome side panel source |
| `tests/` | Contract, API, data-quality, risk, and fail-closed evidence tests |
| `docs/` | Glossary, API reference, architecture, runbook (see [docs map](docs/README.md)) |

## Safety Boundary

This project **deliberately ships no live-order adapter**. The trusted output
ceiling is an `EntryAdmissionDecision` with `execution_allowed=false`, containing
no actionable contract count and no order instruction. Naked short calls appear
in the trusted record only as rejected, unbounded-loss comparisons.

Do not add order templates, submission paths, paper/manual candidate controls, or
sizing output under the banner of "cleaning up the research console".

Report vulnerabilities privately via GitHub Security Advisory - see
[SECURITY.md](SECURITY.md).

Deribit integration follows the official
[public market-data API](https://docs.deribit.com/api-reference/market-data/public-get_order_book)
and [OAuth / API key scopes](https://docs.deribit.com/api-reference/authentication/public-auth).
Any `account:read_write` or `trade:read_write` key is rejected by the account
sidecar.

## License

Code is licensed under [Apache-2.0](LICENSE). Public data artifacts and
generated public research content are licensed under
[CC BY 4.0](LICENSE-DATA).
