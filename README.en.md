# Crypto Options Research Console

English · [中文](README.md)

A **pre-entry research tool for crypto options**. It reads public Deribit market
data, decides whether there is currently an option-selling opportunity worth
considering, and lays out every piece of evidence that conclusion rests on.

It is built for **option sellers who make their own decisions** — people who want
an auditable, replayable pre-entry analysis rather than a black box that trades
for them.

**What it does not do:** it does not connect to any order endpoint, does not
recommend a position size, and performs no automated or semi-automated
execution. The ceiling on trusted output is an admission decision with
`execution_allowed=false`. This is a deliberate product boundary, not a backlog
item.

Two properties define it:

- **Evidence-first** — every conclusion traces to specific evidence. A number
  with no evidence behind it is never invented; it is explicitly reported as
  missing.
- **Fail-closed** — missing, expired, or unverifiable evidence always degrades to
  "blocked". **No signal is not the same as permission to proceed.**

---

## Two ways to use it

| Surface | Purpose |
| --- | --- |
| **Web research workbench** | Screen, rank, and compare candidates side by side; inspect every score component and payoff curve. Where mining and understanding happen. |
| **Chrome research companion** | Answers, in place on a Deribit page, "does the contract I'm looking at have edge, and is there a better one on this chain?" |

The CLI and HTTP API are the **local engine interfaces** driving those two
surfaces — available for integration, scheduling, and automation, but not
maintained as standalone products.

## Quickstart

Requires Python ≥ 3.12. Zero third-party runtime dependencies.

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

Run a full analysis against the bundled fixture (deterministic replay, no
network):

```bash
python -m crypto_options_report.cli analysis \
  --snapshot-fixture tests/fixtures/deribit_btc_option_chain_snapshot.json \
  --generated-at 2026-07-07T00:01:30Z --compact
```

Start the local service and open the evidence console:

```bash
python -m crypto_options_report.api --host 127.0.0.1 --port 8000
```

Then visit <http://127.0.0.1:8000/evidence>.

> **Seeing mostly "unavailable" and "missing" on a first run is expected.** With
> no market data source configured, the product refuses to fabricate values.
> To see a populated page, use `--snapshot-fixture` as above, or wire up a live
> snapshot per [Production](#production).
>
> Likewise, `/readyz` returns `503` under the production profile: no model has
> been promoted, so the readiness gate stays closed by design. **That does not
> mean the process is unhealthy** — `/livez` reports process liveness.

## Core concepts

Worth knowing before reading anything else (full definitions in the
[glossary](docs/glossary.md), which is written in Chinese):

| Term | Meaning |
| --- | --- |
| `research_only` | The fixed output mode: research only, never an order instruction. No configuration changes it. |
| Mode gate | The checkpoint blocking out-of-bounds output — trade recommendations, sizes, and order instructions. |
| `AnalysisRecord` | The **immutable** record of one analysis; the carrier of trusted output. |
| `EntryAdmissionDecision` | The **ceiling** on trusted output: "may this be considered for entry", always `execution_allowed=false`. |
| Evidence class | Evidence trust level: `trusted` / `degraded` / `untrusted` / `missing`. |
| Replay | Same snapshot + same explicit clock ⇒ byte-identical output, so any conclusion can be independently re-checked. |

## Current status

| Capability | Status |
| --- | --- |
| Local deterministic / replay research toolchain | **GO** |
| Paper / manual trading, order submission, real account execution | **NO-GO** |
| Calibration and model promotion | Not implemented |
| External release authorization | **NO-GO** |

The external release gate additionally requires WebSocket gap/resync handling, a
24-hour soak, and seven consecutive days of evidence. Until those hold, the
Evidence Console and Chrome side panel keep displaying `NO-GO`.

## Usage

### Finding candidates with edge

The product's central question is "which strike on this chain is best priced
right now". It answers in two layers that must not be conflated:

- **Relative value** — is this strike rich or cheap against its own smile.
  Needs only the current chain.
- **Absolute expected value** — credit minus expected payout minus fees. Needs
  the underlying's realized return distribution.

Capture underlying history first (public data, no credentials):

```bash
crypto-options-underlying-history --currency BTC --days 1200 \
  --output artifacts/history/btc-daily.json \
  --horizon-days 7 --horizon-days 18
```

It reports how many **independent** windows each holding period has. Horizons
without enough windows are blocked rather than given a precise-looking number
that the sample cannot support.

```bash
crypto-options-report scan \
  --snapshot-fixture artifacts/snapshots/btc-chain.json \
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

Ranking uses a **Pareto frontier plus a published lexicographic tie-break** — no
weighted sum, because weighting incommensurable components asserts a relative
importance nothing has established. Dominated candidates carry which rival beat
them and on which axes.

> **Sample size means independent, non-overlapping windows.** An 18-day horizon
> over 1200 daily observations yields 1183 overlapping windows but only 66
> independent ones. Using the former overstates confidence by roughly 18x.

### CLI (internal plumbing)

```bash
# Capture a live public snapshot for offline analysis
python -m crypto_options_report.cli pull-snapshot --instrument-limit 20 \
  --output artifacts/snapshots/btc-chain.json --compact

# Produce a report from a snapshot; exit code 10 when market data is blocked
python -m crypto_options_report.cli report \
  --snapshot-fixture artifacts/snapshots/btc-chain.json \
  --output artifacts/reports/latest.json --fail-on-blocked --compact

# Research-only risk alerts (no order path of any kind)
python -m crypto_options_report.cli alert-eval \
  --snapshot-fixture artifacts/snapshots/btc-chain.json --dry-run --compact
```

Scheduler exit codes: `0` success · `10` market data blocked/missing · `11`
alerts fired · `1` hard error. See `crypto-options-report --help` for examples.

### HTTP API and Evidence Console

The console and the API are **same-origin by construction**, so no cross-origin
configuration or browser parameter can change production report semantics. The
server builds one `AnalysisRecord` per input set; every GET projection reuses it
rather than refetching data or recomputing conclusions.

Main endpoints: `/evidence` (console) · `/research/report` · `/analysis/result` ·
`/health` · `/livez` · `/readyz`. Full list, auth requirements, and response
contracts are in the [API reference](docs/api-reference.md).

### Chrome research companion (personal, local)

A Manifest V3 side panel for Chrome 114+, intended for personal local use:

```bash
cd web
npm ci
npm run build:extension
```

In `chrome://extensions`, enable Developer mode → "Load unpacked" → select
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
**[production runbook](docs/operations/production-runbook.md)** (Chinese);
the environment variable reference is [`.env.example`](.env.example).

## Development

```bash
python -m pytest -q
python -m ruff check crypto_options_report tools tests

cd web
npm ci && npm test && npm run lint && npm run build
```

`npm run build` updates `crypto_options_report/static/evidence/`. That build
output ships inside the wheel and the container and **must be committed along
with the source** — CI verifies the two match.

Contribution workflow and design red lines: [CONTRIBUTING.md](CONTRIBUTING.md)
(Chinese).

## Project map

| Path | Responsibility |
| --- | --- |
| `crypto_options_report/analysis_run.py` | Immutable mandate, evidence, strategy, and admission contracts |
| `crypto_options_report/contract.py` | The `research_report.v1` compatibility projection |
| `crypto_options_report/api.py` | Stdlib HTTP API, `/evidence`, and legacy URL aliases |
| `crypto_options_report/market_data.py` | Deribit access, snapshot normalization, quality gates |
| `crypto_options_report/_canonical.py` | The single canonical JSON encoding behind every digest |
| `web/` | Shared report boundary, Evidence Console, Chrome side panel source |
| `tests/` | Contract, API, data-quality, risk, and fail-closed evidence tests |
| `docs/` | Glossary, API reference, architecture, runbook (see [docs map](docs/README.md)) |

## Safety boundary

This project **deliberately ships no live-order adapter**. The trusted output
ceiling is an `EntryAdmissionDecision` with `execution_allowed=false`, containing
no actionable contract count and no order instruction. Naked short calls appear
in the trusted record only as rejected, unbounded-loss comparisons.

Do not add order templates, submission paths, paper/manual candidate controls, or
sizing output under the banner of "cleaning up the research console".

Report vulnerabilities privately via GitHub Security Advisory — see
[SECURITY.md](SECURITY.md).

Deribit integration follows the official
[public market-data API](https://docs.deribit.com/api-reference/market-data/public-get_order_book)
and [OAuth / API key scopes](https://docs.deribit.com/api-reference/authentication/public-auth).
Any `account:read_write` or `trade:read_write` key is rejected by the account
sidecar.

## License

No license has been chosen yet. Until one is selected and added as `LICENSE`,
this repository is all rights reserved and is not redistributable.
