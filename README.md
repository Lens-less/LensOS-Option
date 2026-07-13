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
- `http://127.0.0.1:8000/livez`
- `http://127.0.0.1:8000/readyz`

Dashboard 与 API 固定同源，避免跨源配置和浏览器参数改变生产报告语义。

## Production Runtime

生产运行配置与业务 `mode` 分离；即使 HTTP runtime 使用 production profile，报告仍严格保持 `research_only`：

```powershell
$env:CRYPTO_OPTIONS_RUNTIME_PROFILE = "production"
python -m crypto_options_report.api --runtime-profile production --host 127.0.0.1 --port 8000 --max-workers 8 --request-timeout 15
```

生产 HTTP 禁止浏览器指定 fixture、账户场景、评估时间或 live Deribit 抓取。服务应放在认证/TLS 反向代理之后，不能直接暴露到公网。完整容器、健康检查、日志、回滚与验证说明见 [Production Runbook](docs/operations/production-runbook.md)。

推荐把公共市场、私有只读账户和 Web API 分成三个进程。公共 sidecar 必须显式收集完整 feed 图；账户 sidecar 未配置凭证时会写出安全的 `missing/not_configured` 快照，不会伪造账户状态：

```powershell
$runtime = "artifacts/runtime"
python -m tools.refresh_market_snapshot --output "$runtime/deribit-btc-current.json" --interval 10 --instrument-limit 20 --currency BTC --complete-feed-graph

# 仅这个 sidecar 进程读取 DERIBIT_CLIENT_ID / DERIBIT_CLIENT_SECRET；
# API 进程只读取脱敏后的 JSON。API key 必须严格为 account:read + trade:read。
python -m tools.refresh_account_snapshot --output "$runtime/deribit-account-current.json" --interval 15 --currency BTC

python -m crypto_options_report.api --runtime-profile production --host 127.0.0.1 --port 8000 `
  --snapshot-fixture "$runtime/deribit-btc-current.json" `
  --account-snapshot-fixture "$runtime/deribit-account-current.json" `
  --backtest-artifact-dir "$runtime/backtests" `
  --paper-ledger-path "$runtime/paper-ledger.json" `
  --manual-approval-runbook "crypto_options_report/resources/manual-approval-runbook.md"
```

`POST /backtest/run` 已实现为有界、异步、可幂等的本地作业。它只接受严格 JSON 与 `Idempotency-Key`，成功入队返回 HTTP `202` 和 `/backtest/jobs/{job_id}`；相同 key + body 复用同一作业，不同 body 返回 `409`。实际回测在受限子进程中执行，默认 60 秒硬超时；超时或失败不会提升默认结果指针。没有 operator-owned 历史 fixture 时返回可操作的 HTTP `409`；配置 `--historical-fixture` 后才执行。`GET /backtest/jobs/{job_id}`、`GET /backtest/jobs/{job_id}/result`、`GET /backtest/report/default` 和 `GET /backtest/report/{id}` 都只读取已持久化状态或不可变工件。

```powershell
$body = '{"schema_version":"backtest_run_request.v1"}'
curl.exe -sS -X POST http://127.0.0.1:8000/backtest/run `
  -H "Content-Type: application/json" `
  -H "Idempotency-Key: baseline-20260713" `
  --data-binary $body
```

当前 REST 连续快照达到短观察阈值后，只能标记为“研究证据可信”。生产发布门禁另外要求 WebSocket gap/resync、24 小时 soak 和连续 7 天证据；这些系统观察条件未满足前，Dashboard 必须继续显示产品 `NO-GO`。

## Common Checks

```powershell
python -m unittest tests.test_full_system_surfaces
python -m pytest -q
python -m crypto_options_report.cli ingestion-status --live-deribit --instrument-limit 5 --compact
python -m crypto_options_report.cli ingestion-status --live-deribit --instrument-limit 20 --compact
```

## Analysis Ops And Alerts

Capture a live snapshot for offline analysis:

```powershell
python -m crypto_options_report.cli pull-snapshot --instrument-limit 20 --output artifacts/snapshots/btc-chain.json --compact
python -m crypto_options_report.cli report --snapshot-fixture artifacts/snapshots/btc-chain.json --output artifacts/reports/latest.json --fail-on-blocked --compact
```

Evaluate research-only risk alerts (no order paths; opportunity alerts default off):

```powershell
# Preview only (no state write, no webhook delivery):
python -m crypto_options_report.cli alert-eval --snapshot-fixture artifacts/snapshots/btc-chain.json --dry-run --compact

# Scheduler / ops path: persist cooldown state (do not combine with --dry-run):
python -m crypto_options_report.cli alert-eval --snapshot-fixture artifacts/snapshots/btc-chain.json --state-file artifacts/alerts/state.json --fail-on-alert --compact
# optional webhook (HMAC). Failed delivery does NOT advance cooldown state:
#   --webhook-url https://example/hooks/alerts --webhook-secret-env ALERT_WEBHOOK_SECRET
```

Exit codes for schedulers:

- `0` success
- `10` market data blocked/missing (`--fail-on-blocked`)
- `11` one or more alerts fired (`--fail-on-alert`)
- `1` hard error (including webhook delivery failure)

Trading spine (paper/manual/live orders) remains **NO-GO** until external Definition of Done evidence exists. Alerts are risk-degradation first; candidate opportunity alerts stay gated by path-risk and calibration evidence.

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

Deribit 接入以官方 [public market-data API](https://docs.deribit.com/api-reference/market-data/public-get_order_book) 和 [OAuth / API key scopes](https://docs.deribit.com/api-reference/authentication/public-auth) 为准。任何 `account:read_write` 或 `trade:read_write` key 都会被账户 sidecar 拒绝。
