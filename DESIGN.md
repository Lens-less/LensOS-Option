# LensOS Option · Decision Desk Design

## 1. Current Product Contract

The default product is a focused BTC / ETH Deribit research desk:
**Discover → Compare / Decide → Observe**. It supports `LINEAR_USDC` options,
keeps precise contract identities and units, and declares its source at every step.
The user guide is [docs/decision-desk.md](docs/decision-desk.md).

`decision_desk.v1` describes observational research candidates, quote coverage,
deterministic criteria, exclusions, and validity. `research_comparison.v1`
binds compared candidates to one snapshot and one set of scenario assumptions.
Neither contract is an entry-admission decision. A comparable research candidate
may exist while legacy evidence gates remain blocked.

`execution_allowed=false` is permanent. No account connection, credentials,
order template, broker control, recommended sizing, or paper/manual execution
is introduced. Existing `strategy_brief.v1` and `EntryAdmissionDecision` remain
fail-closed and at most `WATCH`; the new desk cannot promote their trust, history,
or forecast evidence.

## 2. Three Connected Views

### Discover

Lead with the selected asset, source, quote cutoff, coverage, and actual candidate
results. Provide a small set of criteria: market viewpoint, DTE range, structure
width, and quote-spread tolerance. The user chooses a research question, not an
investment amount or account allocation.

Generate candidates from supported contracts using deterministic rules. Surface
complete legs, expiry, entry cash, entry fees, raw option-payoff loss bound, and
why each candidate is comparable or excluded. Ranking uses moneyness, width,
summary spread, and DTE, with stable tie breaks. It does not estimate returns.
Never claim AI-selected edge, positive EV, or validated probability from rank.

Empty results explain whether criteria matched nothing, data were unavailable,
liquidity failed, or risk/units were unsupported. Filters may change the research
set, but cannot fabricate missing quotes or override any admission gate.

### Compare / Decide

Select 2–3 candidates from one research snapshot and the same expiry. Keep price shift, elapsed time,
IV shift, pricing basis, and fee policy common across the comparison. A changed
assumption recomputes all selected candidates together and updates its identity.

Separate expiry payoff from modeled pre-expiry stress. IV shifts use percentage
points: 50% IV plus 10 points is 60%, not 55%. Identify the model and assumptions
beside hypothetical values. No probability, historical win rate, or expected-value
claim is inferred from a scenario. The current stress model assumes zero rate
and carry, treats the scenario index as forward, freezes current half-spreads,
and includes standard exit fees. Missing IV makes pre-expiry stress unavailable,
not zero. Elapsed time cannot pass the shared expiry.

The decision action is to retain or copy a research observation. It never places
an order, estimates account suitability, or creates a portfolio position.

### Observe

Store observations in this browser only. Retain exact legs, original snapshot and
analysis identities, criteria, assumptions, costs, source, quote times, and recheck
conditions. Browser records and notes are not synchronized across devices. A
manual recheck sends the frozen research structure to the local research service;
local notes are not included.

Recheck the same instruments against newly requested data. Do not substitute
nearby strikes or reset the original observation's identity. A disappeared,
expired, stale, crossed, or incompletely quoted leg produces an explicit recheck
failure. Keep the old observation as historical context without current eligibility.

Observations are research records, not a ledger of orders, fills, positions,
capital, or trading P&L. There are no automatic reminders or background monitoring
promises. Removing browser site data may remove these local observations.

## 3. Source And Coverage

`crypto-options-report start` opens `/index.html` on `127.0.0.1` with a labeled
synthetic offline demo. The user can explicitly switch to public Deribit data
in the desk without restarting; `start --current` opens that mode directly.
`start --snapshot <path>` remains a legacy-report replay using the old input
format, not a new-desk history mode. Current and snapshot flags are mutually
exclusive. Existing ports, manual browser opening, and loopback/origin protections
remain in force.

The synthetic demo uses fictional contracts and quotes. Demo data never become
live provenance, history evidence, calibrated probabilities, or legacy trusted
research. New desk endpoints support demo and live sources. Legacy replay keeps
capture time and current age visible; its refresh rereads historical inputs and
cannot create current data. Live desk refresh may reuse a still-valid analysis
with more than 30 seconds remaining; it retains the original cutoff and identity.
Older analysis requests recollect through the short collector cache rather than
resetting quote time. Comparison rejects expired snapshots.

Scan coverage and deep-quote coverage are different facts. Use the full instrument
registry and chain summary to screen supported contracts, then deepen a bounded
shortlist of at most 48 structures. All eligible OTM-short vertical pairs are
counted; condor wing-pair counts are complete within that filtered policy while
their materialized shortlist is bounded. Display registry count, summary count, supported/inverse exclusions,
scan completeness, and how many instruments received deep quotes. A bounded
shortlist must not be described as every strategy in the market; partial upstream
responses must not be described as a complete scan.

Prefer the existing collection, snapshot, and API seams. Preserve single-flight
requests, finite timeouts, atomic files, cache expiry, retry/backoff, and host/auth
boundaries. Do not introduce a paid provider, account scope, unrestricted polling,
or a second capture service for the same source. Official collection guidance
supports instrument discovery followed by lifecycle tracking and distinguishes
single-leg books from combo books. [Deribit collection guide](https://docs.deribit.com/articles/options-data-collection-best-practices)

## 4. Economic And Model Meaning

Only supported USDC linear contracts may contribute comparable candidates.
Retain contract size, ratio, premium currency, settlement currency, bid/ask,
quote sizes, timestamps, and expiry metadata. `contract_size` and amount increment
are distinct; one normalized research unit is not a recommended size.

Raw option-payoff bounds exclude every trading and delivery fee. `entry_cash`
is gross sell-bid/buy-ask reference credit; `net_entry_cash` deducts entry fees.
Expiry scenario values deduct entry fees and per-leg dynamic delivery fees, with
daily exemption only from explicit registry metadata. Keep entry fees and
mid-to-touch cost separate, with an explicit fee policy and scope. Do not rename
a raw bound “total maximum loss,” nor treat a reserve as a verified fee cap.
The current reference policy uses standard per-leg fees (3 bps of index, capped
at 12.5% of premium), without account or combo discounts. These are dated model
assumptions, not a query of the user's actual fees. Combo discounts require actual
combo/block execution and cannot be assumed for an assembled research structure.
[Deribit Fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees)

USDC linear options and inverse coin-settled options have different premium and
payoff units. Inverse contracts are explicitly excluded, not silently converted
with a frozen exchange rate. Linear altcoin contract multipliers also prevent
assuming every option has size one. [Linear USDC specifications](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options),
[Inverse specifications](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options)

A deterministic rank is a comparison under disclosed criteria. Scenario profit
means profit under that assumption; it does not describe how likely the assumption
is. Deribit's Wizard makes the same probability distinction, while Position
Builder identifies price/time/IV stress as hypothetical model output.
[Option Wizard](https://insights.deribit.com/education/deribit-option-wizard/),
[Position Builder](https://support.deribit.com/hc/en-us/articles/31238900906781-Position-Builder)

## 5. Visible States And Recovery

Never confuse “no match” with unavailable data. Distinguish loading, ready,
partial, expired, unsupported units, malformed response, connection failure,
and clipboard/storage failure. Each state names the next useful action.

Do not silently fall back from live errors to synthetic data. Failed requests
withdraw old current claims. Cached receipts retain age; later UI loads cannot
reset quote time. A successful fetch does not establish complete coverage or
strategy quality. Recheck deadlines require an explicit user refresh.

A copied review includes exact legs, units, quotes, source, snapshot/analysis and
assumption identities, fee policy, raw-bound scope, validity, reasons, and recheck
requirements. It preserves the research-only boundary and cannot become an order
template. Offer selectable text if clipboard access fails.

## 6. Craft And Accessibility

Keep only the three workflow destinations in primary navigation. Market data,
contracts, and comparison occupy the reading path; raw JSON, deeper provenance,
and legacy diagnostics are supporting disclosures. Avoid a dashboard assembled
from every internal module.

Use quiet surfaces, clear typography, aligned numerals, readable full instrument
names, and one primary action per state. On narrow screens, conclusion and next
action come first; comparison tables scroll within their own labeled container.
Keyboard and screen-reader users can filter, select candidates, change scenarios,
copy a review, and recheck observations. Preserve visible focus, semantic headings,
status announcements, and reduced-motion behavior. Errors and exclusions must be
understandable without color alone.

Mole is a quality benchmark for restraint, useful details, and clear outcomes;
ORATS and Deribit's tools inform workflow questions. Do not copy their assets,
code, branding, page layouts, proprietary models, or trading functionality.
[Mole](https://mole.fit/zh/), [ORATS Scanner](https://orats.com/option-scanner)

## 7. Compatibility And Publication

`?view=legacy` retains the previous application; old teaching, reports, CLI,
sidecar, API, extension, and public-edition contracts remain compatibility
surfaces. Their method and evidence requirements are documented in
[architecture.md](docs/architecture.md), the [legacy workflow](docs/guides/decision-workflow.md),
and the [strategy brief specification](docs/product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md).
They do not define the new default information architecture.

The current desk runs locally; this document does not establish a hosted backend
or production URL. A separately configured private backend enables desk live
collection only through `--allow-desk-live-fetch` or
`CRYPTO_OPTIONS_API_ALLOW_DESK_LIVE_FETCH`; host, origin, and bearer protections
still apply. Open-source code permission is separate from data permissions.
Deribit market and derived data are for personal use; other publication or
forwarding requires prior written approval. Public screenshots and demos need
synthetic or independently authorized inputs.
[Exchange Terms §2.10](https://support.deribit.com/hc/en-us/articles/25944532191645-Deribit-Exchange-Membership-Terms-Deribit-FZE)

## 8. Verification

Run `python tools/verify.py` and rebuild packaged static assets for web changes.
Use explicit clocks and synthetic fixtures to check candidate generation,
coverage honesty, unit handling, shared comparison assumptions, exact-leg
recheck, stale data, and failures. Visually inspect desktop and narrow layouts,
including keyboard use. Preserve the legacy browser and evidence checks.

Report actual commands, build, inputs, screenshots, and unverified layers.
Tests, browser interactions, live collection, historical performance, calibration,
cross-platform CI, and released assets are separate evidence. Do not use a passing
UI test to claim market edge. See [CONTRIBUTING.md](CONTRIBUTING.md).
