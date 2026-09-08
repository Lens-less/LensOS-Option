# Complete An Options Research Decision

[Project home](../../README.en.md) · [中文](decision-workflow.md) · [Research methods](research-workflows.en.md)

This guide connects first use, public-data analysis, evidence inspection, and a
reproducible record. The current focus is BTC options using public Deribit data.
“Insufficient evidence; no strategy” is a valid research outcome.
`research_only=true` and `execution_allowed=false` hold under every outcome.

## 1. Learn With The Offline Tour

Install using the [quickstart](../../README.en.md#quickstart), run
`crypto-options-report demo`, and open the printed `/index.html?view=demo` URL.
Choose a structure, move the expiry-price slider, and compare profit and loss.
These fictional points describe linear expiry payoffs; they do not model real
fills, fees, or changes before expiry.

Select “查看真实快照” (View real snapshot) to inspect the bundled redacted
research snapshot. Check its evaluation time, evidence state, and blocking
reasons. An empty set of reliable strategy cards is expected here. From the
source repository, inspect the corresponding machine-readable case with:

```powershell
python tools/reproduce_research.py --check
```

This compares complete outputs for one build, input set, and explicit clock.
See the [offline case](reproducible-case.md) for fields and saved-case comparison.

## 2. Capture Public Market Inputs

These commands need network access, but no Deribit account or API key. Run them
from the repository root; output stays under local `artifacts/`. Do not commit
raw captures, runtime logs, or any later account data to the public repository.

```powershell
python -m crypto_options_report.underlying_history_tool --currency BTC --days 1200 `
  --resolution 1D --output artifacts/history/btc-daily.json

crypto-options-report pull-snapshot --currency BTC `
  --output artifacts/snapshots/btc-chain.json --compact
```

Refresh slower history first, then capture the short-lived market snapshot.
The capture summary includes `quality_gate_passed`, `quality_reason_codes`,
`validation_eligible_expiry_count`, and the output path. Saving a snapshot does
not establish full-chain quality or promoted data trust. Index history supplies
underlying observations; it does not create a historical options chain or a
validated strategy.

After a network or sampling failure, retain the reason and capture again when
the source recovers. For ongoing work, append snapshots with
`pull-snapshot --output-dir artifacts/snapshots/btc-series` and maintain history,
signal, and series artifacts using the [operator guide](operator-guide.en.md).

## 3. Generate And Inspect The Analysis

```powershell
crypto-options-report report `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/latest.json --quiet --fail-on-blocked

crypto-options-report analysis `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/analysis.json --compact
```

For `report --fail-on-blocked`, exit `10` means market quality is blocked. Exit
`0` only establishes command success and that check; inspect `data_trust`,
admission decisions, and `strategy_brief` separately. `analysis` saves the
immutable record, including build identity, input hashes, evidence lineage,
and conditions actually evaluated. Each command defaults to its own execution
clock; pass the same timezone-aware `--generated-at` for strict comparison.

Start a read-only local server in another terminal. Stop a demo using port 8000
with `Ctrl+C` first, or select port 8001 below:

```powershell
python -m crypto_options_report.api --host 127.0.0.1 --port 8000 `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json
```

Open the [research brief](http://127.0.0.1:8000/evidence). Read the data time and
overall result before candidates and supporting evidence. Browser refresh reads
configured files; it does not capture market data. Update inputs before refreshing.

Add `--replay` to inspect an old snapshot at its capture-time evaluation clock.
The interface still reports age against the reader's current time. A historical
pass does not restore present eligibility; changing timestamps cannot cure staleness.

## 4. Read In Evidence Order

| Check | Meaning |
| --- | --- |
| Source, capture time, evaluation time, freshness | Historical calculations and current availability are separate |
| `data_status`, `data_trust`, reason codes | Complete, valid fields do not authenticate their source |
| Relative value, post-cost EV, risk, ranking basis | A rank is a comparison, not a probability |
| `strategy_brief.action`, exact legs, expiry, itemized costs, loss basis, cancellation | Cards remain at most `WATCH`; none passing means `NO_TRADE` |
| History and forecast states, scope, protocol and selection identities | Historical rates require `VALIDATED`; forecast intervals require `CALIBRATED` |
| Manifest, conditions, lineage and hashes | These support explanation and reproduction, not execution |

`entry.cost_breakdown` lists entry fees, slippage, legging, and settlement
reserves in `entry.currency`. Minimum net credit deducts the first three;
the loss budget also includes the settlement reserve.
`risk.max_loss_basis=PAYOFF_BOUND_PLUS_FROZEN_COST_BUDGET` and
`delivery_fee_upper_bound_verified=false` explicitly distinguish a modeled
budget from an absolute fee-inclusive loss cap. Missing numeric costs prevent
cards; boolean “fees included” labels or inserted zeroes do not establish coverage.

Exact-structure historical replay deducts delivery fees calculated under its
fee rules from net PnL, while the risk denominator uses payoff loss plus entry
fees. `delivery_fee_in_risk_denominator=false` makes that exclusion explicit,
so net `R` can fall below `-1`. Do not clip this result. Also check each historical
artifact's settlement basis; signal validation uses a daily-close proxy.

## 5. Recover From Blocking States

| State | Next action | Evidence of recovery |
| --- | --- | --- |
| Connection failure, timeout, HTTP error | Check the local service, port and paths; retry after it recovers | A newly loaded report passes contract validation |
| Non-JSON or invalid contract | Check service version and response; repair the input or service | A valid report replaces the error; old output is not used as a fallback |
| Stale data or suspended publication | Recapture local inputs; operators regenerate and publish a qualified edition | A verifiable new cutoff passes current freshness checks |
| Trust promotion pending | Accumulate authenticated observations and provenance through the runbook | Actual trust requirements pass; refreshes and JSON edits do not substitute |
| Missing artifact or insufficient sample | Continue capture, retain expiry cohorts, generate and configure the artifact | The UI distinguishes unconfigured, collecting, and statistical outcomes |
| Expired or mismatched historical/forecast evidence | Check protocol, exact legs, validity and lineage; reevaluate under the model protocol | Current evidence matches the strategy and passes its own gates |
| No reliable strategy | Read rejection reasons, save the observation, and wait for changed inputs/evidence | A subsequent analysis passes without lowering thresholds |

The report is authoritative for exact reason codes. Missing account or model
evidence describes an admission boundary; it is not a request for a newcomer's
credentials. Offline replay cannot create calibration. See the
[historical and forecast specification](../product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md).

## 6. Keep A Reproducible Record

Retain snapshots, underlying history, UTC evaluation clock, build version, and
analysis JSON. Record the observation, blocking reasons, and evidence needed
next. Keep these locally or in an owned private evidence repository. A public
bug report should contain a minimal redacted fixture, reproduction command,
and expected/actual behavior, never credentials or a full runtime directory.

Completion means that inputs, conclusions, and limits are reviewable. It does
not require a strategy card or demonstrate profitability.
