# GitHub Option/Deribit Top 100 Research

Generated: 2026-07-08

## Method

- Used official GitHub surfaces: authenticated `gh api search/repositories` for 19 query strings and direct `gh api repos/{owner}/{repo}` metadata for high-signal seed repositories.
- Search cache contained 1,024 unique repositories; the final inventory combines 42 verified high-signal repos with direct Deribit/options search hits to reach 100.
- README/layout enrichment was attempted twice but timed out on repeated GitHub lookups. The inventory below therefore uses official metadata plus verified sidecar summaries for top repositories, and records that limitation.

## Query Strategy

- `deribit options`
- `deribit option`
- `deribit trading options`
- `deribit client options`
- `deribit volatility`
- `crypto options`
- `cryptocurrency options`
- `bitcoin options`
- `option pricing crypto`
- `options pricing`
- `option greeks`
- `options greeks`
- `options analytics`
- `options backtest`
- `option backtesting`
- `volatility surface options`
- `black scholes options`
- `portfolio margin options`
- `optionlab`

## Inclusion Rules

- Include crypto-options, Deribit, option pricing/Greeks, volatility surface, options backtesting, portfolio/risk/margin, execution/paper trading, dashboard/API/reporting, and data validation projects.
- Include strong general options or trading-engine projects when their architecture transfers to this repo.
- Exclude generic software projects where `option` only means command-line or UI options.
- Treat forks/mirrors as duplicates unless they provide materially different ideas.
- Treat GPL/AGPL/NOASSERTION licenses as reference-only until dependency review.

## Inventory Table

| # | Repository | Stars | Language | License | Last pushed | Deribit-specific | Primary value | Suitability | Reason |
| ---: | --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | [ccxt/ccxt](https://github.com/ccxt/ccxt) | 43255 | Python | MIT | 2026-07-07 | false | Deribit connector or exchange adapter | possible adapter pattern | exchange adapter patterns, including Deribit; useful for fail-closed market/account wrapper design |
| 2 | [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | 24505 | Rust | LGPL-3.0 | 2026-07-08 | false | educational/reference only | inspiration only | event-driven architecture, message bus, adapters, and live/backtest parity patterns |
| 3 | [vnpy/vnpy](https://github.com/vnpy/vnpy) | 42753 | Python | MIT | 2026-05-17 | false | educational/reference only | inspiration only | mature trading framework, gateway abstractions, and risk/event-engine patterns |
| 4 | [StockSharp/StockSharp](https://github.com/StockSharp/StockSharp) | 10250 | C# | Apache-2.0 | 2026-06-22 | false | options backtesting | possible test fixture model | multi-asset trading platform with options/risk/execution architecture ideas |
| 5 | [thrasher-corp/gocryptotrader](https://github.com/thrasher-corp/gocryptotrader) | 3447 | Go | MIT | 2026-07-07 | false | execution/paper trading | possible adapter pattern | crypto exchange connector lifecycle and operational config patterns |
| 6 | [knowm/XChange](https://github.com/knowm/XChange) | 4070 | Java | MIT | 2026-07-03 | false | dashboard/API/reporting | possible adapter pattern | typed exchange abstraction and adapter conformance ideas |
| 7 | [crypto-chassis/ccapi](https://github.com/crypto-chassis/ccapi) | 725 | C++ | MIT | 2026-06-24 | false | options backtesting | possible adapter pattern | low-level exchange market data and order API wrapper patterns |
| 8 | [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed) | 2868 | Python | NOASSERTION | 2026-02-01 | false | dashboard/API/reporting | possible adapter pattern | market-data feed normalization and callback routing inspiration |
| 9 | [veighna-global/vnpy_deribit](https://github.com/veighna-global/vnpy_deribit) | 21 | Python | MIT | 2023-06-05 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content |
| 10 | [f0cii/deribit-api](https://github.com/f0cii/deribit-api) | 26 | Go | MIT | 2024-08-20 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content |
| 11 | [askmike/deribit-v2-ws](https://github.com/askmike/deribit-v2-ws) | 22 | JavaScript | MIT | 2024-06-18 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content |
| 12 | [dovahcrow/deribit-rs](https://github.com/dovahcrow/deribit-rs) | 49 | Rust | MIT | 2024-07-04 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content |
| 13 | [schepal/deribit_data_collector](https://github.com/schepal/deribit_data_collector) | 73 | Python | NOASSERTION | 2020-08-29 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; data ingestion or validation ideas |
| 14 | [schepal/delta_hedge](https://github.com/schepal/delta_hedge) | 76 | Python | NOASSERTION | 2022-06-22 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; risk, margin, or portfolio controls |
| 15 | [cryptarbitrage-code/deribit-position-greeks](https://github.com/cryptarbitrage-code/deribit-position-greeks) | 47 | Python | NOASSERTION | 2022-03-22 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; pricing or Greeks logic |
| 16 | [beijingcao/binance-deribit-btc](https://github.com/beijingcao/binance-deribit-btc) | 380 | Python | MIT | 2026-06-22 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content |
| 17 | [pengjin2/Derbit-Volatility-Visulization](https://github.com/pengjin2/Derbit-Volatility-Visulization) | 84 | Python | MIT | 2020-04-05 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |
| 18 | [lballabio/QuantLib](https://github.com/lballabio/QuantLib) | 7324 | C++ | NOASSERTION | 2026-07-06 | false | educational/reference only | possible dependency review | derivatives pricing architecture and term-structure abstractions |
| 19 | [domokane/FinancePy](https://github.com/domokane/FinancePy) | 3035 | Jupyter Notebook | GPL-3.0 | 2026-06-16 | false | option pricing or Greeks | possible dependency review | Python derivatives pricing and risk examples; license requires caution |
| 20 | [vollib/py_vollib](https://github.com/vollib/py_vollib) | 417 | Python | MIT | 2026-05-29 | false | educational/reference only | possible dependency review | Black-Scholes, Greeks, and IV reference calculations |
| 21 | [marcdemers/py_vollib_vectorized](https://github.com/marcdemers/py_vollib_vectorized) | 159 | Python | MIT | 2024-12-02 | false | option pricing or Greeks | possible test fixture model | vectorized Greeks/IV calculation patterns |
| 22 | [rgaveiga/optionlab](https://github.com/rgaveiga/optionlab) | 534 | Python | GPL-3.0 | 2026-06-30 | false | option pricing or Greeks | possible dependency review | options strategy payoff/backtest API ideas; GPL dependency caution |
| 23 | [goldspanlabs/optopsy](https://github.com/goldspanlabs/optopsy) | 1411 | Python | AGPL-3.0 | 2026-06-30 | false | option pricing or Greeks | possible test fixture model | options research/backtesting notebook and fixture ideas; AGPL caution |
| 24 | [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 8208 | Python | NOASSERTION | 2026-07-05 | false | options backtesting | possible test fixture model | vectorized research/backtest architecture |
| 25 | [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | 8654 | Python | AGPL-3.0 | 2025-12-20 | false | options backtesting | possible test fixture model | simple strategy/backtest test harness patterns; AGPL caution |
| 26 | [mementum/backtrader](https://github.com/mementum/backtrader) | 22367 | Python | GPL-3.0 | 2024-08-19 | false | options backtesting | possible test fixture model | event-driven backtest lifecycle and broker abstractions; GPL caution |
| 27 | [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | 20414 | C# | Apache-2.0 | 2026-07-07 | false | educational/reference only | inspiration only | production-grade backtest/live parity, data subscriptions, and brokerage abstractions |
| 28 | [PyPortfolio/PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt) | 5831 | Jupyter Notebook | MIT | 2026-07-07 | false | portfolio/risk/margin | inspiration only | portfolio optimization and allocation constraints |
| 29 | [dcajasn/Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | 4332 | C++ | BSD-3-Clause | 2026-06-22 | false | portfolio/risk/margin | inspiration only | portfolio risk, CVaR, and optimizer examples |
| 30 | [cvxgrp/cvxportfolio](https://github.com/cvxgrp/cvxportfolio) | 1234 | Python | GPL-3.0 | 2026-04-27 | false | portfolio/risk/margin | possible test fixture model | constraint-first portfolio optimization/backtesting ideas; GPL caution |
| 31 | [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | 52155 | Python | GPL-3.0 | 2026-07-07 | false | execution/paper trading | inspiration only | crypto strategy lifecycle, dry-run, and safety-gate patterns; GPL caution |
| 32 | [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | 19091 | Python | Apache-2.0 | 2026-07-08 | false | options backtesting | possible test fixture model | execution connector and paper/live operational state patterns |
| 33 | [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | 6210 | Python | GPL-3.0 | 2026-07-07 | false | options backtesting | possible adapter pattern | crypto bot strategy/execution lifecycle; GPL caution |
| 34 | [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | 8144 | JavaScript | MIT | 2026-07-07 | false | execution/paper trading | inspiration only | crypto backtest/live strategy framework and trade journal ideas |
| 35 | [unionai-oss/pandera](https://github.com/unionai-oss/pandera) | 4399 | Python | MIT | 2026-07-07 | false | data ingestion/schema/validation | possible test fixture model | dataframe schema validation patterns |
| 36 | [pydantic/pydantic](https://github.com/pydantic/pydantic) | 28216 | Python | MIT | 2026-07-06 | false | data ingestion/schema/validation | possible test fixture model | strict model validation and JSON schema generation |
| 37 | [streamlit/streamlit](https://github.com/streamlit/streamlit) | 45166 | Python | Apache-2.0 | 2026-07-07 | false | dashboard/API/reporting | possible test fixture model | rapid research dashboard patterns |
| 38 | [plotly/dash](https://github.com/plotly/dash) | 24297 | Python | MIT | 2026-07-07 | false | dashboard/API/reporting | possible test fixture model | dashboard app structure and callback model |
| 39 | [grafana/grafana](https://github.com/grafana/grafana) | 75343 | TypeScript | AGPL-3.0 | 2026-07-08 | false | dashboard/API/reporting | possible test fixture model | monitoring dashboard and alerting concepts |
| 40 | [microsoft/qlib](https://github.com/microsoft/qlib) | 45931 | Python | MIT | 2026-04-22 | false | data ingestion/schema/validation | possible test fixture model | research pipeline and experiment tracking ideas |
| 41 | [tradingstrategy-ai/trade-executor](https://github.com/tradingstrategy-ai/trade-executor) | 157 | Jupyter Notebook | NOASSERTION | 2026-07-07 | false | options backtesting | inspiration only | strategy execution state, vault/account safety, and runbook ideas |
| 42 | [tfrmma/options-volatility-trading-strats](https://github.com/tfrmma/options-volatility-trading-strats) | 4 | Python | MIT | 2026-06-08 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 43 | [fshahy/dankbit](https://github.com/fshahy/dankbit) | 4 | Python | MIT | 2026-07-07 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 44 | [jothamteo/deribit-options-dashboard](https://github.com/jothamteo/deribit-options-dashboard) | 1 | JavaScript | MIT | 2026-05-24 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 45 | [GSMuller/btc-options-analysis](https://github.com/GSMuller/btc-options-analysis) | 1 |  | NOASSERTION | 2026-01-23 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 46 | [Cieloc/boltCOT](https://github.com/Cieloc/boltCOT) | 0 | TypeScript | NOASSERTION | 2025-12-08 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 47 | [PierreNieto/BTC-Option-Pricing-Hedging-Engine-NIETO-Pierre](https://github.com/PierreNieto/BTC-Option-Pricing-Hedging-Engine-NIETO-Pierre) | 0 |  | NOASSERTION | 2026-02-23 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 48 | [djienne/POLYMARKET_UP_DOWN_DERIBIT_STRATEGY](https://github.com/djienne/POLYMARKET_UP_DOWN_DERIBIT_STRATEGY) | 29 | Python | NOASSERTION | 2026-03-08 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; volatility surface or IV analytics |
| 49 | [davidkim1/pricing-crypto-options-models](https://github.com/davidkim1/pricing-crypto-options-models) | 2 | Jupyter Notebook | NOASSERTION | 2025-04-30 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 50 | [tfrmma/gamma-scalper](https://github.com/tfrmma/gamma-scalper) | 2 | Python | MIT | 2026-06-28 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 51 | [manumanikandan/implied_volatility_bitcoin_options](https://github.com/manumanikandan/implied_volatility_bitcoin_options) | 1 | Python | NOASSERTION | 2025-10-20 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 52 | [tikitaka721/derebit-options-webapp](https://github.com/tikitaka721/derebit-options-webapp) | 1 | Python | NOASSERTION | 2025-01-17 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 53 | [widemangojutsu/owlcord](https://github.com/widemangojutsu/owlcord) | 0 | JavaScript | NOASSERTION | 2025-10-19 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 54 | [pbht/volatility-surface](https://github.com/pbht/volatility-surface) | 0 | Rust | NOASSERTION | 2025-06-22 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; volatility surface or IV analytics |
| 55 | [dwasse/vol-surface-visualizer](https://github.com/dwasse/vol-surface-visualizer) | 63 | Python | NOASSERTION | 2022-12-08 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; volatility surface or IV analytics |
| 56 | [bottama/cryptocurrency-derivatives-pricing-and-delta-neutral-volatility-trading](https://github.com/bottama/cryptocurrency-derivatives-pricing-and-delta-neutral-volatility-trading) | 10 | Python | NOASSERTION | 2021-09-17 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 57 | [ADnocap/taut-arb-backtest](https://github.com/ADnocap/taut-arb-backtest) | 6 | Python | NOASSERTION | 2026-02-19 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; backtesting/replay ideas |
| 58 | [apostleoffinance/Heston-SV-Model-BTC-Call-Option-Calibration](https://github.com/apostleoffinance/Heston-SV-Model-BTC-Call-Option-Calibration) | 4 | Jupyter Notebook | MIT | 2025-12-07 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 59 | [Kirill-Miroshnichenko/deribit-options-collector](https://github.com/Kirill-Miroshnichenko/deribit-options-collector) | 3 | Python | MIT | 2026-02-25 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 60 | [schoeffeljp/deribit-mcp](https://github.com/schoeffeljp/deribit-mcp) | 2 | TypeScript | MIT | 2026-03-23 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 61 | [EVERYTHINGAICO/polymarket-btc-edge](https://github.com/EVERYTHINGAICO/polymarket-btc-edge) | 2 | Python | NOASSERTION | 2026-06-06 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; backtesting/replay ideas |
| 62 | [GuillaumeBld/BTC_Volatility_Smirk_Trading_Bot](https://github.com/GuillaumeBld/BTC_Volatility_Smirk_Trading_Bot) | 1 | Python | MIT | 2025-10-03 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; backtesting/replay ideas |
| 63 | [mariia-botkina/btc-options-vol-surface](https://github.com/mariia-botkina/btc-options-vol-surface) | 1 | Python | MIT | 2026-06-18 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; volatility surface or IV analytics |
| 64 | [matthiasyychan/delta_predict](https://github.com/matthiasyychan/delta_predict) | 0 | Python | NOASSERTION | 2026-02-09 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; volatility surface or IV analytics |
| 65 | [lohith-mahesh/Crypto.Gex](https://github.com/lohith-mahesh/Crypto.Gex) | 0 | Python | NOASSERTION | 2026-04-18 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |
| 66 | [TanvirCCC/options-implied-crypto-signals](https://github.com/TanvirCCC/options-implied-crypto-signals) | 0 | Jupyter Notebook | MIT | 2026-06-15 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; backtesting/replay ideas |
| 67 | [wepoets1107/icefire-options-workbench](https://github.com/wepoets1107/icefire-options-workbench) | 23 | Python | MIT | 2026-06-14 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |
| 68 | [wepoets1107/crypto-options-strategy-assistant](https://github.com/wepoets1107/crypto-options-strategy-assistant) | 7 | Python | MIT | 2026-06-16 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |
| 69 | [dgcar/crypto-options-pricing](https://github.com/dgcar/crypto-options-pricing) | 6 | Python | NOASSERTION | 2025-03-05 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 70 | [ipatpat/deribit-trading-agent](https://github.com/ipatpat/deribit-trading-agent) | 3 | Python | MIT | 2026-05-17 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |
| 71 | [yodablocks/deribit-options-flow](https://github.com/yodablocks/deribit-options-flow) | 0 | Python | NOASSERTION | 2026-06-03 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; data ingestion or validation ideas |
| 72 | [kctejasvi/crypto-trading-bot](https://github.com/kctejasvi/crypto-trading-bot) | 0 | Python | NOASSERTION | 2026-06-10 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; volatility surface or IV analytics |
| 73 | [api-evangelist/deribit](https://github.com/api-evangelist/deribit) | 0 |  | NOASSERTION | 2026-06-27 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; data ingestion or validation ideas |
| 74 | [zelos-alpha/demeter](https://github.com/zelos-alpha/demeter) | 90 | Python | MIT | 2026-06-16 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; backtesting/replay ideas |
| 75 | [BarendPotijk/visualize_crypto_options](https://github.com/BarendPotijk/visualize_crypto_options) | 15 | Python | NOASSERTION | 2023-03-01 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |
| 76 | [chanhyeong28/TradingAlgorithmForDeribit](https://github.com/chanhyeong28/TradingAlgorithmForDeribit) | 3 | Python | MIT | 2025-12-07 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; backtesting/replay ideas |
| 77 | [paulhochenauer/Excel-VBA-Bitcoin-Options-Analysis](https://github.com/paulhochenauer/Excel-VBA-Bitcoin-Options-Analysis) | 1 |  | NOASSERTION | 2025-03-13 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; risk, margin, or portfolio controls |
| 78 | [FinkBig/probability_backtester_v1](https://github.com/FinkBig/probability_backtester_v1) | 0 | Python | MIT | 2025-08-04 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; backtesting/replay ideas |
| 79 | [beetrootblues/btc-options-system](https://github.com/beetrootblues/btc-options-system) | 0 | Python | NOASSERTION | 2026-03-10 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; backtesting/replay ideas |
| 80 | [PinnacleDynamics/TradeTerminal](https://github.com/PinnacleDynamics/TradeTerminal) | 0 |  | NOASSERTION | 2026-05-29 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; risk, margin, or portfolio controls |
| 81 | [shauryachopra03-svg/IV_RV_Mispricing_for_Deribit_Data](https://github.com/shauryachopra03-svg/IV_RV_Mispricing_for_Deribit_Data) | 0 | Jupyter Notebook | NOASSERTION | 2025-11-25 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 82 | [bottama/Deribit-Option-Data](https://github.com/bottama/Deribit-Option-Data) | 35 | Python | NOASSERTION | 2021-03-19 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; data ingestion or validation ideas |
| 83 | [zugzvangg/crypto-calibration](https://github.com/zugzvangg/crypto-calibration) | 13 | Jupyter Notebook | Apache-2.0 | 2024-11-10 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 84 | [ashish1497/black-scholes](https://github.com/ashish1497/black-scholes) | 10 | TypeScript | Apache-2.0 | 2022-05-06 | false | option pricing or Greeks | possible dependency review | options-focused content; pricing or Greeks logic; volatility surface or IV analytics |
| 85 | [mamadrabiie/onchain-options-analysis](https://github.com/mamadrabiie/onchain-options-analysis) | 2 | Jupyter Notebook | NOASSERTION | 2024-09-25 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; volatility surface or IV analytics |
| 86 | [kgeoffrey/AutoHedge.jl](https://github.com/kgeoffrey/AutoHedge.jl) | 81 | Julia | MIT | 2026-04-12 | false | option pricing or Greeks | possible test fixture model | options-focused content; pricing or Greeks logic; backtesting/replay ideas |
| 87 | [teal-finance/rainbow](https://github.com/teal-finance/rainbow) | 65 | Go | MIT | 2026-02-21 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |
| 88 | [jeromeku/cryptocurrency-derivatives-pricing-and-delta-neutral-volatility-trading](https://github.com/jeromeku/cryptocurrency-derivatives-pricing-and-delta-neutral-volatility-trading) | 17 |  | NOASSERTION | 2021-09-17 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; pricing or Greeks logic |
| 89 | [FullStackCraft/floe](https://github.com/FullStackCraft/floe) | 9 | TypeScript | NOASSERTION | 2026-03-19 | false | option pricing or Greeks | possible test fixture model | options-focused content; pricing or Greeks logic; data ingestion or validation ideas |
| 90 | [hoanginc144/volfeed](https://github.com/hoanginc144/volfeed) | 7 | Python | MIT | 2025-04-09 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; data ingestion or validation ideas |
| 91 | [willhammondhimself/adaptive-volatility-arbitrage](https://github.com/willhammondhimself/adaptive-volatility-arbitrage) | 6 | Python | MIT | 2026-05-03 | false | option pricing or Greeks | possible adapter pattern | options-focused content; pricing or Greeks logic; backtesting/replay ideas |
| 92 | [alexagedah/implied-volatility-surface](https://github.com/alexagedah/implied-volatility-surface) | 4 | Python | MIT | 2022-10-11 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |
| 93 | [CameronScarpati/vol-surface-engine](https://github.com/CameronScarpati/vol-surface-engine) | 4 | Python | MIT | 2026-06-30 | false | option pricing or Greeks | possible dependency review | options-focused content; pricing or Greeks logic; volatility surface or IV analytics |
| 94 | [nirajneupane17/Options-Analytics-Volatility-Surface](https://github.com/nirajneupane17/Options-Analytics-Volatility-Surface) | 3 | Python | MIT | 2026-04-18 | false | option pricing or Greeks | possible dependency review | options-focused content; pricing or Greeks logic; volatility surface or IV analytics |
| 95 | [dada63924/deribit-analyzer](https://github.com/dada63924/deribit-analyzer) | 2 | Rust | NOASSERTION | 2026-07-08 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; data ingestion or validation ideas |
| 96 | [Weakpointplacentalmammal373/vol-surface-engine](https://github.com/Weakpointplacentalmammal373/vol-surface-engine) | 2 | Python | MIT | 2026-07-08 | false | option pricing or Greeks | possible test fixture model | options-focused content; pricing or Greeks logic; volatility surface or IV analytics |
| 97 | [FlashAlpha-lab/volatility-surface-python](https://github.com/FlashAlpha-lab/volatility-surface-python) | 2 | Python | MIT | 2026-06-16 | false | option pricing or Greeks | possible adapter pattern | options-focused content; pricing or Greeks logic; volatility surface or IV analytics |
| 98 | [KyleC144/OptionsVolSurface](https://github.com/KyleC144/OptionsVolSurface) | 1 | TypeScript | NOASSERTION | 2026-02-27 | false | option pricing or Greeks | possible dependency review | options-focused content; pricing or Greeks logic; volatility surface or IV analytics |
| 99 | [comersy/RL-4-Quant](https://github.com/comersy/RL-4-Quant) | 1 | Python | NOASSERTION | 2026-06-20 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content; data ingestion or validation ideas |
| 100 | [BluEng9/covered-calls-manager](https://github.com/BluEng9/covered-calls-manager) | 1 | Python | MIT | 2025-10-06 | true | Deribit connector or exchange adapter | possible adapter pattern | Deribit-specific exchange/API content; options-focused content |

## Top 25 Deep-Read Summaries

1. [ccxt/ccxt](https://github.com/ccxt/ccxt): Broad exchange adapter layer with Deribit coverage. Borrow the idea of narrow exchange capability wrappers and explicit unsupported-operation behavior, not the whole dependency.
2. [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader): Event-driven research/live parity, typed data messages, and adapter boundaries. Useful for deciding where a later live collector ends and deterministic replay begins.
3. [vnpy/vnpy](https://github.com/vnpy/vnpy): Gateway/event-engine model for separating adapters, strategy logic, and risk checks. Strong inspiration for future Deribit private-account gateway tests.
4. [StockSharp/StockSharp](https://github.com/StockSharp/StockSharp): Large multi-asset trading stack with options/backtesting/execution surfaces. Useful mostly as architecture reference because the stack is heavy.
5. [thrasher-corp/gocryptotrader](https://github.com/thrasher-corp/gocryptotrader): Crypto exchange operational patterns around configuration, exchange lifecycle, and API failure handling.
6. [knowm/XChange](https://github.com/knowm/XChange): Typed exchange abstraction in Java. The useful lesson is adapter conformance tests across exchanges and clear capability discovery.
7. [crypto-chassis/ccapi](https://github.com/crypto-chassis/ccapi): Low-level exchange API wrapper patterns. Useful for disciplined market-data/order endpoint separation and error propagation.
8. [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed): Market-data feed normalization and callback routing. Treat as reference only because the repo is archived.
9. [veighna-global/vnpy_deribit](https://github.com/veighna-global/vnpy_deribit): Direct Deribit gateway. Useful for endpoint mapping, auth lifecycle, and how a gateway fits a broader trading framework.
10. [f0cii/deribit-api](https://github.com/f0cii/deribit-api): Small Deribit v2 API client. Useful for minimal endpoint coverage and compact request/response tests.
11. [askmike/deribit-v2-ws](https://github.com/askmike/deribit-v2-ws): Deribit WebSocket wrapper. Useful for websocket subscription/reconnect shape, but dated.
12. [dovahcrow/deribit-rs](https://github.com/dovahcrow/deribit-rs): Rust Deribit websocket client. Useful for typed websocket message thinking and adapter isolation.
13. [schepal/deribit_data_collector](https://github.com/schepal/deribit_data_collector): Deribit BTC/ETH option-chain collector. Useful as an idea source for persistent collection cadence and option-chain storage.
14. [schepal/delta_hedge](https://github.com/schepal/delta_hedge): Deribit portfolio delta-hedging reference. Useful for hedge-cost accounting and position Greeks review.
15. [cryptarbitrage-code/deribit-position-greeks](https://github.com/cryptarbitrage-code/deribit-position-greeks): Position Greeks calculator. Useful for account/position reconciliation and exchange-vs-model Greeks checks.
16. [beijingcao/binance-deribit-btc](https://github.com/beijingcao/binance-deribit-btc): Cross-exchange arb plus monitoring. Useful for dashboard/monitoring and exchange-state checks, not strategy logic.
17. [pengjin2/Derbit-Volatility-Visulization](https://github.com/pengjin2/Derbit-Volatility-Visulization): Deribit vol surface visualization. Useful as a cautionary reference for making surface data inspectable.
18. [lballabio/QuantLib](https://github.com/lballabio/QuantLib): Mature derivatives pricing architecture. Borrow abstractions and test ideas, not code, until license/dependency review is complete.
19. [domokane/FinancePy](https://github.com/domokane/FinancePy): Python derivatives pricing and risk examples. GPL license makes it reference-only for this repo unless explicitly approved.
20. [vollib/py_vollib](https://github.com/vollib/py_vollib): Black-Scholes, Greeks, and implied-vol reference calculations. Useful for independent formula cross-check tests.
21. [marcdemers/py_vollib_vectorized](https://github.com/marcdemers/py_vollib_vectorized): Vectorized Greeks/IV on pandas/numpy. Useful for performance and fixture-scale checks.
22. [rgaveiga/optionlab](https://github.com/rgaveiga/optionlab): Options strategy payoff/backtest API. Useful for strategy scenario shape and report ergonomics; GPL license caution.
23. [goldspanlabs/optopsy](https://github.com/goldspanlabs/optopsy): Options research/backtesting notebooks. Useful for fixture design and strategy sweep reporting; AGPL caution.
24. [polakowo/vectorbt](https://github.com/polakowo/vectorbt): Vectorized research/backtest framework. Useful for fast parameter sweeps and artifact-oriented reports.
25. [kernc/backtesting.py](https://github.com/kernc/backtesting.py): Simple backtest API. Useful for small deterministic tests; AGPL license makes direct reuse risky.

## Top 10 Actionable Integration Lessons

1. **Adapter capability contracts**
   - Sources: ccxt, vnpy_deribit, deribit-api
   - Local target: `crypto_options_report/market_data.py`, future account adapter
   - Lesson: Expose endpoint capabilities, supported currencies, auth requirements, rate-limit policy, and fail-closed reasons before a report consumes data.
2. **Snapshot plus streaming ingestion**
   - Sources: cryptofeed, schepal collectors
   - Local target: `market_data.py`, tests/fixtures
   - Lesson: Separate full option-chain snapshot from ticker/order-book refreshes; persist raw responses before normalization for replay.
3. **Schema-first validation**
   - Sources: pandera, pydantic, Great Expectations
   - Local target: `historical.py`, future vendor adapters
   - Lesson: Turn canonical quote/account/path schemas into executable validators with quarantine reports.
4. **Independent pricing oracles**
   - Sources: QuantLib, py_vollib, FinancePy
   - Local target: `pnl.py`, `surface.py`, tests
   - Lesson: Use a small external-oracle test corpus to catch formula, IV, and Greeks drift without importing licensed code.
5. **Surface robustness and no-arb guards**
   - Sources: QuantLib, vol-surface repos
   - Local target: `surface.py`
   - Lesson: Aggregate duplicate strikes, fit bid/ask/mark separately, and treat no-arb math errors as quality failures, not crashes.
6. **Backtest/live parity**
   - Sources: Nautilus Trader, Lean, vnpy
   - Local target: `backtest.py`, `calibration.py`
   - Lesson: Define one event schema for replay and live collection so walk-forward artifacts can be replayed exactly.
7. **Dry-run/paper lifecycle**
   - Sources: freqtrade, hummingbot, Jesse
   - Local target: `paper_ledger.py`, future runbook
   - Lesson: Model paper/manual states as persistent records with idempotent transitions and reconciliation evidence.
8. **Portfolio risk constraints**
   - Sources: Riskfolio-Lib, cvxportfolio, PyPortfolioOpt
   - Local target: `portfolio_risk.py`
   - Lesson: Make size caps explainable constraints and add CVaR/stress optimization tests before any promotion.
9. **Operational dashboards**
   - Sources: Grafana, Dash, Streamlit
   - Local target: `api.py`, `static/dashboard.html`
   - Lesson: Track freshness, rate limits, validation failures, and readiness gates as first-class panels.
10. **Research fixture ergonomics**
   - Sources: optionlab, optopsy, vectorbt
   - Local target: `tests/fixtures`, `docs/research`
   - Lesson: Keep compact scenario fixtures for strategy sweeps, but preserve raw data lineage and exclusion reasons.
