# Crypto Options Research Console

本仓库是一个加密货币期权卖 Call 研究工具链。当前状态是：

- **GO**：本地 deterministic/replay research toolchain。
- **NO-GO**：paper/manual trading、自动下单、真实账户执行。
- 默认输出保持 `research_only`，所有 trade recommendation、recommended size、order instruction、paper/manual candidate 都必须被 mode gate 阻断，直到外部数据、账户、校准和纸面交易对账证据满足 Definition of Done。

## Quickstart

```powershell
python -m pytest -q
python -m crypto_options_report.api --smoke
python -m crypto_options_report.api --host 127.0.0.1 --port 8000
```

启动 API 后可访问：

- `http://127.0.0.1:8000/dashboard.html`
- `http://127.0.0.1:8000/dashboard`
- `http://127.0.0.1:8000/research/report`
- `http://127.0.0.1:8000/health`

静态 dashboard 也支持显式 API 地址：

```text
http://127.0.0.1:8000/dashboard.html?api_base=http://127.0.0.1:8000
```

## Common Checks

```powershell
python -m unittest tests.test_full_system_surfaces
python -m pytest -q
python -m crypto_options_report.cli ingestion-status --live-deribit --instrument-limit 5 --compact
python -m crypto_options_report.cli ingestion-status --live-deribit --instrument-limit 40 --compact
```

Dashboard visual smoke:

```powershell
$env:DASHBOARD_URL = "http://127.0.0.1:8000/dashboard.html"
node .workflow/verify-dashboard-cdp.mjs
```

Optional environment overrides:

- `DASHBOARD_URL`
- `CHROME_PATH`
- `CDP_PORT`

## Project Map

- `crypto_options_report/contract.py` builds the shared `research_report.v1`.
- `crypto_options_report/api.py` serves the stdlib HTTP API and static dashboard page.
- `crypto_options_report/full_surface.py` declares CLI/API/dashboard surface descriptors.
- `crypto_options_report/static/dashboard.html` is the dependency-free research console.
- `tests/` contains contract, API, data-quality, risk, calibration, and paper-ledger checks.
- `issues/README.md` indexes core `ISSUE-001..015` and DQR remediation issues.
- `docs/automation/goal-board.md` is the canonical acceptance board.
- `docs/automation/project-acceptance-report.md` records current project acceptance.
- `docs/research/` contains data-quality audits, remediation backlog, and integration research.
- `DESIGN.md` anchors the dashboard visual/product style.

## Safety Boundary

This project intentionally has no live-order adapter. Paper/manual readiness remains `NO-GO` unless all release prerequisites are satisfied by external evidence, including real account adapter validation, promoted calibration, persistent paper ledger, and 30-60 day reconciliation.

Do not add order templates, live submission paths, paper/manual candidate controls, or sizing outputs as part of research-console cleanup.
