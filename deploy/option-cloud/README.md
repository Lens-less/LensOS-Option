# Option private quote research workbench

This Site is a browser-local research workflow using user-supplied quote chains. It does not fetch or redistribute exchange quotes, connect accounts, place orders, predict prices, calculate win rates or provide automated trading recommendations.

## Working flow

1. Select a local CSV (max 5 MB / 5000 rows), map columns, and explicitly confirm contract units and definitions. Standard headers, common Chinese/English aliases, field mapping, an empty template and optional clearly synthetic A/B/bad-data examples are available.
2. Choose direction, underlying, currency, expiry range, multiplier, quantities, cash-flow constraints, fixed fees and quote-quality windows. The browser actually enumerates protected 1:1 put-credit or call-credit spreads. Each structure has identical asset, settlement currency, expiry, exercise/settlement convention and multiplier. Full chains can contain multiple groups. Enumeration is capped at 100,000 pairs and explicitly reports partial coverage.
3. Compare up to three candidates in the same direction and units. Different expiries are plotted separately. Exact expiry intrinsic payoff, configured fee-adjusted bounds and break-even levels are calculated; there is no pre-expiry theoretical pricing model. Sell bid / buy ask are reference cash flows, not simultaneous-execution guarantees.
4. Freeze exact legs, quotes, timestamps, file SHA-256, assumptions and a reason as a research plan. Local storage and JSON export/import retain originals. A later CSV must match exact contracts and provide newer quotes. Rechecks append versions; missing legs and unsupported definitions block. Opposite-side close capacity is checked independently; liquidation references are not account or realized P&L.

## Supported definitions and limits

- BTC / ETH, denominated and settled separately in USD / USDC / USDT
- European, cash-linear payoff only; no inverse, American or physical-delivery support
- Explicit per-underlying-unit or per-contract premiums; explicit contract multiplier
- Fees are user-entered fixed cash per contract, separately for entry, expiry and hypothetical close. Dynamic delivery/liquidation fees, margin needs, slippage and lifecycle risks are outside the conditional expiry bound
- Historical quotes remain historical. No source is labeled live or independently verified. A file hash identifies bytes, not authenticity
- Incomplete/invalid/duplicate/off-tick rows are identified and excluded rather than silently repaired. Missing quote sizes remain unknown
- Browser-only storage, max 50 plans / 100 events each / 3,000,000 serialized characters; failed writes preserve prior records and offer direct JSON export

## Verification and reproducibility

- `npm ci && npm run fixtures && npm run oracle && npm run lint && npm test && npm run build`
- `scripts/generate-payoff-oracle.py` calls the retained original Python `structures.py` to generate 60 structure/cost/multiplier cases and 480 payoff points. TypeScript tests check results and additional unbounded/zero-range cases
- Integration tests cover the full local-file workflow, actual quote/risk filtering, different-expiry charts, JSON reconstruction, exact rechecks, cancellation races, duplicate contract identity collisions and storage failures
- Independent read-only review additionally checked 240 arithmetic cases and identified four defects now covered by regressions: close-side depth, forged baseline constraints, delimiter collisions, and write/read storage-limit mismatch
- Cloud-browser localhost navigation returned `ERR_BLOCKED_BY_CLIENT`. The dedicated GitHub Actions workflow instead runs one real isolated Chromium journey against the production build: CSV A import, comparison, frozen JSON download, CSV B recheck, 390px overflow and no outbound/body-bearing requests. It uploads two screenshots and a machine-readable report; inspect the exact commit run before acceptance.

The original Python runtime under `original_python/` is unmodified from upstream `30102e5d99994346a48d99e97972fd4266cf106b`; upstream `15f3f4e792f060d788326e5d52188a26c7e24301` differs only in a transport test. The original Python product and main branch are unchanged. This deployment is mirrored under `deploy/option-cloud/` on GitHub branch `deploy/option-cloud-acceptance`; generated JSON fixtures are reproducible with the commands above. The Site repository is the canonical publication source.

The former fixed 32-comparison synthetic replay is retained only at `?legacy=1` and lazy-loaded. It is not the default workbench. No recurring work or wider sharing is enabled.
