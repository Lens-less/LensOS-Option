# Dashboard 数据与证据修复报告（2026-07-12）

## 结论

本轮已修复 Dashboard 把“采集器缺数、运行时未接线、证据未配置、功能未实现”混成同一种红灯的问题，并把生产服务接到独立的 Deribit public-only 快照 sidecar。

当前运行边界保持：

- `RESEARCH_ONLY`
- `NO_TRADE`
- 产品发布 `NO-GO`
- 无 live-order adapter
- 无浏览器触发的外部行情抓取

`NO-GO` 不是本轮失败，而是对真实未完成证据的保留：只读账户未配置、历史数据 provenance 未建立、模型未晋级、Backtest 未运行、paper ledger/观察期/manual runbook 未完成。

## 根因与修复

| 根因 | 旧表现 | 修复 |
|---|---|---|
| 成功返回后被无条件清空 | Deribit 有数据但 `rows=0` | 保留成功的 book summaries，并加回归测试 |
| 按字母截前 N 个合约 | 样本集中在近月，不满足 7–35 DTE | 20 个 ticker 安全预算内，按到期日、call、流动性和 moneyness 分层抽样 |
| DVOL 用 1 小时分辨率却要求 60 秒新鲜度 | 健康 DVOL 长期被判 stale | 改取 1 分钟数据；允许 1 分钟 candle rollover 的 90 秒 DVOL 边界 |
| 采集时间记在请求开始，元数据/DVOL 串行 | 网络慢时快照一写入就接近过期 | `captured_at` 改为完整采集完成时间；记录 `collection_started_at`/`collection_duration_ms`；独立请求并行 |
| sidecar 完成后再等待 30 秒 | 60 秒门禁周期性红绿闪烁 | 默认间隔改为 10 秒；生产实测连续采集约 1.0–1.4 秒 |
| 单条坏 quote 无条件阻断整批 | 20 条中 1 条 `bid_iv=0` 即全红 | 坏 quote 单独隔离；按声明阈值执行：有效数少于 8 或坏报价比例超过 25% 才阻断 expiry |
| JSON-RPC `10028` 被判 schema drift | 限流语义错误 | `10028` / `too_many_requests` 归为 retryable rate-limit event |
| 校准/回测展示固定绩效 | 未运行却显示 Calmar 对比 | 删除固定绩效；未运行时 comparison 为空；POST backtest 明确返回 `501 not_implemented` |
| release gate 只有模糊布尔值 | fixture、未配置、观察期混成“缺失” | 拆为 `evidence_state`、`release_state`、`evidence_class`、`reason_codes`，并加双向不变量 |
| Dashboard 用 data trust 代替 freshness | 当前 public data 仍显示 `NOT CURRENT` | freshness/quality 与 shared trust 分开；当前未晋级数据展示 `CURRENT PUBLIC DATA · TRUST PENDING` |
| 离线 fallback 带可信样式假数据 | API 失败仍显示候选/校准/Calmar | fallback 只显示不可用状态，不再携带貌似真实的指标 |
| 局部 `allow_new` 文案像交易授权 | HALT 页面仍出现“允许新交易” | 改为“局部门禁通过”；Regime 数值标注“非交易授权” |

## 生产观测

在 `http://127.0.0.1:8765` 的本机生产进程上观测：

- service readiness：`true`
- runtime profile：`production`
- 上游 BTC options：`870`
- research sample：`20`
- valid quotes：`20/20`（坏值出现时会单独 quarantine）
- fetch errors：`0`
- collection scope：`research_sample`
- DVOL：`available`
- data status：`validated`
- Vol Surface：`validated`
- eligible expiries：`0`
- candidate scanner：`blocked / SURFACE_QUALITY_FAIL`
- candidate count：`0`，这是扫描结果，不再显示成“数据缺失”
- backtest：`not_run`
- calibration：`research_fixture`，未晋级
- product release：`NO-GO`

连续跨分钟采样中，快照年龄保持在 0–10 秒，DVOL 在 59 秒 rollover 仍为 `available`，数据状态持续 `validated`。

## GitHub / 数据项目取舍

完整研究见 [`docs/research/deribit-open-source-project-landscape-2026-07-12.md`](../research/deribit-open-source-project-landscape-2026-07-12.md)。结论：

1. CCXT：最适合未来做 read-only shadow adapter；本轮未引入新依赖。
2. Tardis：最适合真实历史 options chain、trades、L2 与 replay；数据服务需单独采购/授权。
3. NautilusTrader：最值得借鉴 sequence-gap recovery、token bucket、heartbeat、重认证和订阅恢复；不建议把完整交易引擎直接嵌入当前研究控制台。
4. Cryptofeed：采集到存储的实现值得参考，但仓库已归档，只做 reference-only。

## 验证证据

- `python -m pytest -q`：`284 passed, 1 skipped, 160 subtests passed`
- `python -m compileall -q crypto_options_report tools`：通过
- `git diff --check`：通过
- wheel build：通过
- API smoke：通过
- HTTP：Dashboard/report/backtest-report `200`；未知路由 `404`；backtest run `501`；production live-query override `400`
- 浏览器：桌面和约 370px CSS 窄屏无页面横向溢出；刷新按钮成功更新报告时间；Dashboard 自身 console warning/error 为 0

## 仍需外部输入的门禁

以下项目不能用代码伪造完成：

- Deribit read-only account credential 与 secret isolation
- private account deterministic replay evidence
- 有版本、校验和与许可记录的历史数据集
- out-of-sample / walk-forward promotion evidence
- immutable backtest ledger
- 30–60 天 paper reconciliation 观察期
- manual approval runbook

在这些证据完成前，不应将页面升级为 GO，也不应开放 paper/manual/live execution。
