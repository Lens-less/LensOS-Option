# CLI, API, And Local Extension

[Project home](../../README.en.md) · [Documentation](../README.md) · [中文](local-tools.md)

Commands below run from the repository root after installing the package. Operational actions require the configured services described in the runbooks.
New users can follow the [complete decision workflow](decision-workflow.en.md) to connect capture, browser startup, and recovery.

### CLI (internal plumbing)

```powershell
# Capture a live public snapshot for offline analysis
python -m crypto_options_report.cli pull-snapshot `
  --output artifacts/snapshots/btc-chain.json --compact

# Produce a report from a snapshot; exit code 10 when market data is blocked
python -m crypto_options_report.cli report `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --output artifacts/reports/latest.json --fail-on-blocked --compact

# Research-only risk alerts (no order path of any kind)
python -m crypto_options_report.cli alert-eval `
  --snapshot-fixture artifacts/snapshots/btc-chain.json --dry-run --fail-on-alert --compact
```

Exit codes: `0` command success, `1` hard error, `2` usage error.
`report/alert-eval --fail-on-blocked` returns `10` for blocked market quality;
`alert-eval --fail-on-alert` returns `11` when an alert fires. `analysis` has no
`--fail-on-blocked`; inspect its admission decisions. Exit `0` does not establish
evidence, strategy, or execution approval. See each subcommand's `--help`.

`--snapshot-fixture` does not freeze evaluation time. Current research needs new
inputs; historical inspection requires explicit
`--generated-at <snapshot-captured-at-with-timezone>` or API `--replay`. A replay
clock does not restore current eligibility. Omitting `--instrument-limit` uses
the collector's current default; smaller budgets can reduce covered expiries
and valid quotes.

### HTTP API and Evidence Console

The console and the API are **same-origin by construction**, so no cross-origin
configuration or browser parameter can change production report semantics. The
server shares one `AnalysisRecord` across GET projections while that input
version remains valid. File changes and evidence/trust-window expiry rebuild
the record. Refreshing the page does not recapture data; old files remain blocked.

Main endpoints: `/evidence` (console) · `/strategy/brief` · `/research/report` · `/analysis/result`
· `/health` · `/livez` · `/readyz`. Full list, auth requirements, and response
contracts are in the [API reference](../api-reference.md).

Signal/series artifacts require `research_only=true`, supported schemas and valid
timestamps. Execution, order, and sizing fields are rejected at every depth.
Regenerate old hand-authored artifacts with the current CLI. Measured, preflight,
blocked, and demo outputs retain compatibility and `excluded_snapshots` evidence;
see the [v0.5.0 migration](../releases/v0.5.0.md#信号与序列工件升级).

### Chrome research companion (personal, local)

A Manifest V3 side panel for Chrome 114+, intended for personal local use.
Download the Chrome extension ZIP matching your engine version from
[GitHub Releases](https://github.com/Lens-less/LensOS-Option/releases), check
`SHA256SUMS`, and extract it.
Start `crypto-options-report demo`, then enable Developer mode in
`chrome://extensions`, choose "Load unpacked", and select the extracted folder.

To build it from source:

```powershell
cd web
npm ci
npm run build:extension
```

Select `web/dist/chrome-extension/`, then click the toolbar icon on a Deribit
page.

The side panel only reads `http://127.0.0.1:<port>/research/report`. It
identifies the current Deribit contract and shows research context; it contains
**no order, trade, quantity, or sizing controls**. Contract context is isolated
per tab.
For a connection error, use the visible connection settings to match the local
service port and retry. Successful connection does not bypass evidence gates.
