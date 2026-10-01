# Complete An Options Research Decision

[Project home](../../README.en.md) · [中文](decision-workflow.md) · [Research methods](research-workflows.en.md)

One local entry connects learning, public-data research, and a copied review.
The current focus is BTC options using public Deribit data. “Insufficient evidence;
no strategy” is a complete research outcome. `research_only=true` and
`execution_allowed=false` hold under every outcome.

## 1. Open The Platform And Learn A Structure

Install using the [quickstart](../../README.en.md#quickstart), then run:

```powershell
crypto-options-report start
```

The offline learning tour opens automatically. Choose a structure, move the
expiry-price slider, then inspect its evidence. Fictional points describe linear
expiry payoffs, excluding real fills, fees, and changes before expiry. Select
“进入研究简报” (Open research brief) to read the source chosen at startup.
Default offline startup reads the bundled redacted historical snapshot's
evaluation time and blocking reasons. An empty set of reliable strategy cards
is expected; teaching output cannot supply research evidence.

The server binds only to `127.0.0.1`. `Ctrl+C` stops it. Add `--port 8001` if the
port is busy, or `--no-open-browser` to open the printed URL yourself.

## 2. Choose A Declared Data Mode

Stop the demo, choose one input, then open the research brief:

```powershell
# Network required; existing public Deribit source, no account or keys
crypto-options-report start --current

# Historical replay; reads your local input only
crypto-options-report start --snapshot artifacts/snapshots/btc-chain.json
```

Add `--underlying-history artifacts/history/btc-daily.json` for local underlying
history. This supplies historical input; it does not create a historical options
chain or a validated strategy. `--current` and `--snapshot` are mutually exclusive.

| Visible mode | What the update does | Research boundary |
| --- | --- | --- |
| Deribit public data | “更新公开行情” (Update public quotes) requests research; a valid analysis is reused, expired evidence triggers collection | Collection must still pass quality, trust, cost, and model gates |
| Historical snapshot replay | “重新读取快照” (Reread snapshot) reads configured local files and evaluates at capture time | The replay window continues counting from that historical age; a historical pass cannot restore current eligibility |
| Bundled historical snapshot | Rereads the redacted bundled case, without network collection | Explains real blocking, not current market conditions |
| Published research snapshot | “重新载入本版” (Reload edition) reads a precomputed edition | The browser cannot collect quotes; the edition's validity applies |

Check mode, data cutoff, and validity first. Repeated clicks do not guarantee
new quotes or a new analysis identity; a cache hit retains its evaluation time.
Refresh cannot turn missing, stale, unsynchronized, or crossed quotes, or
incomplete costs, into a usable strategy.

## 3. Read The Conclusion, Then Its Evidence

Primary navigation keeps the learning tour and research brief. Candidates,
volatility series, and ranking validation sit under “深入研究” (Deeper research).
The brief explains market conditions, whether a reliable strategy exists, and why.

| Check | Meaning |
| --- | --- |
| Source, capture time, evaluation time, validity | Historical calculation and current availability are separate |
| Strategy cards or rejection reasons | None passing means `NO_TRADE`; cards remain at most `WATCH` |
| Exact legs, expiry, bid/ask, currency and units | Quotes describe that instant; one unit expresses structure ratios, not a recommended position size |
| Minimum net credit, itemized costs, modeled loss budget, cancellation | Missing numeric costs prevent cards; a budget is not an absolute fee-inclusive loss cap |
| `data_status`, `data_trust`, reason codes, history and forecast states | Quality does not authenticate provenance; ranks are not probabilities |
| Analysis and brief identities, clock and source | These support explanation and reproduction, not execution |

`entry.cost_breakdown` lists entry fees, slippage, legging, and settlement reserves
in `entry.currency`. Minimum net credit deducts the first three; the loss budget
also includes settlement reserves. `risk.max_loss_basis=PAYOFF_BOUND_PLUS_FROZEN_COST_BUDGET`
and `delivery_fee_upper_bound_verified=false` explicitly leave the actual delivery
fee upper bound unverified. Boolean “fees included” labels or inserted zeroes do
not establish cost coverage.

Historical rates require `VALIDATED`; forecast intervals require `CALIBRATED`.
Exact-structure historical replay deducts delivery fees from net PnL, while its
risk denominator uses payoff loss plus entry fees.
`delivery_fee_in_risk_denominator=false` makes that exclusion explicit, so net
`R` can fall below `-1`; do not clip it. Check each artifact's settlement basis;
signal validation uses a daily-close proxy.

## 4. Copy A Research Review

For a currently valid strategy card, select “复制研究复核” (Copy research review).
The text includes exact legs, each bid/ask and unit, quote times, source, analysis
and brief identities, evaluation time, contract expiry, minimum net credit,
frozen costs, modeled loss budget, validity, cancellation, and recheck requirements.
If clipboard access fails, selectable text is offered for manual copying.

The copied result always retains `WATCH / execution_allowed=false`. It creates
no order and supplies no position-size recommendation. Do not reuse it after
validity expires. Obtain fresh positive, synchronized two-sided quotes and
reevaluate all costs and evidence before further review. When no cards exist,
select “复制拒绝原因” (Copy rejection reasons) to retain `NO_TRADE`, full reasons,
source, times, and analysis identity. Expired records state that qualification is
paused and contain no old strategy legs or credit instructions. Save the raw JSON
separately for complete reproduction; teaching cards or lowered thresholds cannot replace the result.

For complete reproduction, also retain the original snapshot, underlying history,
UTC evaluation clock, build version, and analysis JSON locally or in an owned
private evidence repository. Public bug reports need a minimal redacted fixture,
reproduction command, and expected/actual behavior, never credentials or a full
runtime directory. No trading journal or account setup is required.

## 5. Recover According To The Reason

| State | Next action | Evidence of recovery |
| --- | --- | --- |
| Connection failure, timeout, invalid response | Check service, port, files, and version; retry after recovery | A newly loaded report passes contract validation; old results are not a fallback |
| Current quotes expired | Select Update public quotes and wait for collection and checks | The new input's cutoff and validity are verifiable |
| Historical snapshot expired | Keep it as historical research, or restart with `start --current` | Mode changes honestly; edited timestamps do not create current eligibility |
| Publication stalled | Wait for the operator to publish a qualified edition | A new edition passes current freshness checks; reloading the old one cannot recover |
| Trust promotion pending, insufficient samples, missing artifact | Accumulate provenance, expiry cohorts, and protocol evidence | Actual requirements pass; refresh, JSON edits, and offline replay do not substitute |
| Expired or mismatched evidence | Check protocol, exact legs, costs, validity, and source; reevaluate | Evidence matching the current strategy passes its own gates |
| No reliable strategy | Retain rejection reasons and wait for changed input or evidence | Subsequent research passes without lowering thresholds |

The report is authoritative for exact reasons. Missing account or model evidence
describes an admission boundary; it does not request a newcomer's credentials.
See the [historical and forecast protocol](../product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md)
for calibration requirements.

## 6. Optional: Manual Capture And Reproducible Artifacts

Existing CLI and HTTP API entry points remain compatible. Use this longer workflow
when you need saved inputs, an explicit clock, or ongoing sample collection. It
is not a first-use prerequisite. Run from the repository root; network access is
needed, no account or keys are needed, and output stays local:

```powershell
python -m crypto_options_report.underlying_history_tool --currency BTC --days 1200 `
  --resolution 1D --output artifacts/history/btc-daily.json

crypto-options-report pull-snapshot --currency BTC `
  --output artifacts/snapshots/btc-chain.json --compact

crypto-options-report report `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/latest.json --quiet --fail-on-blocked

crypto-options-report analysis `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/analysis.json --compact
```

Capture slower history first, then the short-lived quotes. Capture quality is
not trust-promotion evidence. `report --fail-on-blocked` exit `10` means market
quality is blocked; exit `0` still requires inspecting trust, admission, and brief.
`analysis` retains build identity, input hashes, lineage, and evaluated conditions.
Each command defaults to its own clock; pass the same timezone-aware
`--generated-at` for strict comparison.

Inspect these files with `start --snapshot … --underlying-history …`, or retain
the existing API command:

```powershell
python -m crypto_options_report.api --host 127.0.0.1 --port 8000 `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json
```

This file mode only rereads configured files; update inputs to update the market.
Add `--replay` to evaluate at capture time. Ongoing research can append with
`pull-snapshot --output-dir artifacts/snapshots/btc-series`, or use the existing
`python -m crypto_options_report.snapshot_sidecar --output <path>` with `--once`
for one capture or `--interval` for periodic refresh. See the
[operator guide](operator-guide.en.md) for history, signal, and series maintenance.
Do not publicly commit raw captures, logs, or private evidence.

The [fixed offline case](reproducible-case.md) needs no network:

```powershell
python tools/reproduce_research.py --check
```

A matching replay means one build, input set, and clock produce the same output.
It does not establish strategy validity, execution eligibility, or profitability.
