# Open-Source Integration Opportunities

## Principles

- Borrow concepts, schemas, tests, and architecture. Do not copy third-party code into this repo.
- Prefer no new dependency until a license, maintenance, and adapter-surface review is complete.
- GPL/AGPL/NOASSERTION projects are reference-only for this Goal.

## Deribit and exchange adapters

- **Adapter capability contracts**: Expose endpoint capabilities, supported currencies, auth requirements, rate-limit policy, and fail-closed reasons before a report consumes data.
  - Sources: ccxt, vnpy_deribit, deribit-api
  - Local targets: `crypto_options_report/market_data.py`, future account adapter
- **Snapshot plus streaming ingestion**: Separate full option-chain snapshot from ticker/order-book refreshes; persist raw responses before normalization for replay.
  - Sources: cryptofeed, schepal collectors
  - Local targets: `market_data.py`, tests/fixtures
- **Schema-first validation**: Turn canonical quote/account/path schemas into executable validators with quarantine reports.
  - Sources: pandera, pydantic, Great Expectations
  - Local targets: `historical.py`, future vendor adapters

## Pricing, Greeks, and volatility surface

- **Independent pricing oracles**: Use a small external-oracle test corpus to catch formula, IV, and Greeks drift without importing licensed code.
  - Sources: QuantLib, py_vollib, FinancePy
  - Local targets: `pnl.py`, `surface.py`, tests
- **Surface robustness and no-arb guards**: Aggregate duplicate strikes, fit bid/ask/mark separately, and treat no-arb math errors as quality failures, not crashes.
  - Sources: QuantLib, vol-surface repos
  - Local targets: `surface.py`

## Backtesting, calibration, and path risk

- **Backtest/live parity**: Define one event schema for replay and live collection so walk-forward artifacts can be replayed exactly.
  - Sources: Nautilus Trader, Lean, vnpy
  - Local targets: `backtest.py`, `calibration.py`
- **Dry-run/paper lifecycle**: Model paper/manual states as persistent records with idempotent transitions and reconciliation evidence.
  - Sources: freqtrade, hummingbot, Jesse
  - Local targets: `paper_ledger.py`, future runbook

## Portfolio risk and paper workflow

- **Portfolio risk constraints**: Make size caps explainable constraints and add CVaR/stress optimization tests before any promotion.
  - Sources: Riskfolio-Lib, cvxportfolio, PyPortfolioOpt
  - Local targets: `portfolio_risk.py`
- **Operational dashboards**: Track freshness, rate limits, validation failures, and readiness gates as first-class panels.
  - Sources: Grafana, Dash, Streamlit
  - Local targets: `api.py`, `web/src/App.tsx`, `web/src/public/`

## Research fixtures and reporting

- **Research fixture ergonomics**: Keep compact scenario fixtures for strategy sweeps, but preserve raw data lineage and exclusion reasons.
  - Sources: optionlab, optopsy, vectorbt
  - Local targets: `tests/fixtures`, `docs/research`

## What Not To Borrow

- Do not import trading-bot execution stacks just to get paper mode; this repo's safety gates must remain explicit and narrower.
- Do not adopt GPL/AGPL pricing/backtesting code without an explicit dependency decision.
- Do not replace conservative bid/ask assumptions with mid/mark fills copied from educational notebooks.
- Do not use broad ML/research frameworks to bypass the PRD requirement for walk-forward calibration, leakage checks, and fail-closed release gates.

## License Cautions

- Reference-only until reviewed: QuantLib/NOASSERTION, vectorbt/NOASSERTION, cryptofeed/NOASSERTION, FinancePy/GPL-3.0, optionlab/GPL-3.0, optopsy/AGPL-3.0, backtesting.py/AGPL-3.0, backtrader/GPL-3.0, cvxportfolio/GPL-3.0, freqtrade/GPL-3.0, OctoBot/GPL-3.0, Grafana/AGPL-3.0.
- Dependency-review candidates with permissive licenses: ccxt, vnpy, py_vollib, py_vollib_vectorized, pydantic, pandera, Dash, Streamlit, PyPortfolioOpt, Riskfolio-Lib, Lean, hummingbot.
