# HTTP API 参考

> **定位：内部管道。** 面向用户的产品形态是 **Web 工作台** 与 **Chrome 研究伴侣**。
> 本 API 与 CLI 是驱动它们的本地引擎接口，供集成、调度与自动化使用，不作为独立产品维护。

本服务基于 Python 标准库实现，无 Web 框架依赖。所有端点都只读取或写入本地状态，
**不存在任何下单路径**。

术语见[术语表](glossary.md)；部署与密钥管理见
[生产运行手册](operations/production-runbook.md)。

## 通用约定

**同源** — Evidence Console 与 API 固定同源，避免跨源配置改变生产报告语义。

**单次分析** — 服务端对同一组输入只生成一次 `AnalysisRecord`。所有 GET 投影复用
同一个 `X-Analysis-Run-ID` 与 ETag，不会重新拉取 live 数据或重算准入结论。

**鉴权** — 默认只监听 loopback，此时不要求 Bearer token。若显式绑定到非 loopback
接口（需同时设置 `CRYPTO_OPTIONS_API_ALLOW_REMOTE=1` 与
`CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE`），则除 `/health`、`/livez`、`/readyz` 外的
**所有路径与方法**（含 404、HEAD）都要求：

```
Authorization: Bearer <token>
```

Token 比较使用常数时间比较。鉴权在路由和 404 判定**之前**执行，因此不会通过响应
差异泄露路径是否存在。

> 注：没有注册处理器的 HTTP 动词（如 `TRACE`）由标准库直接返回 `501`，不经过鉴权
> 层。该路径不触及任何路由逻辑或数据。

**Host / Origin** — `Host` 必须匹配 loopback 或 `CRYPTO_OPTIONS_API_ALLOWED_HOSTS`
中显式列出的主机名（防 DNS rebinding）。状态变更请求（POST/DELETE）如携带
`Origin`，其主机必须与 `Host` 一致。响应始终携带
`Cross-Origin-Resource-Policy: same-origin`，且从不返回 `Access-Control-Allow-Origin`。

**生产限制** — production profile 下，浏览器不能通过查询参数指定 fixture、账户场景、
评估时间或触发 live 抓取。

---

## 健康与就绪

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/health` | 否 | 进程健康 |
| GET | `/livez` | 否 | **仅**表示进程存活 |
| GET | `/readyz` | 否 | 业务依赖是否齐备 |

`/readyz` 在 production profile 下只有当服务契约、已绑定的市场信任证据、账户快照、
历史/工件存储、作业队列和已提升模型**全部**可用时才返回 `200`；否则返回 `503` 并
附带原因码：

```json
{
  "runtime_profile": "production",
  "service_ready": true,
  "research_only": true,
  "product_release": "NO-GO",
  "live_order_adapter_available": false,
  "ready": false,
  "reason_codes": ["MARKET_DATA_NOT_READY", "MODEL_NOT_READY", "..."]
}
```

当前没有可提升的模型，因此 production 的 `/readyz` **按设计**保持 `503`。这不是故障。

## 页面

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/evidence` | Evidence Console（推荐入口） |
| GET | `/evidence/assets/*` | 控制台静态资源，文件名经正则校验 |
| GET | `/` · `/dashboard.html` · `/dashboard/page` | 旧书签兼容，返回**同一个** Console |

`/dashboard.html` 只是指向同一 Console 的 URL 兼容层，不是第二套页面。

## 报告投影

以下端点都是同一份 `AnalysisRecord` 的不同投影，不会触发重新计算。

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| GET | `/analysis/result` | 不可变的 `AnalysisRecord`（**可信输出**） |
| GET | `/strategy/brief` | canonical `strategy_brief.v1` 一屏策略简报；0–3 张卡或 `NO_TRADE` |
| GET | `/research/report` · `/report` | `research_report.v1` 兼容投影 |
| GET | `/market/chain` | 报告的 `data_status` |
| GET | `/surface` | `vol_surface_status` |
| GET | `/regime` | `permission_state` |
| GET | `/account/risk` | `account_status` |
| GET | `/portfolio/risk` | `portfolio_risk` |
| GET | `/candidates` | `ev_candidate_scanner` |
| GET | `/recommendation` | 受 mode gate 约束的推荐投影 |
| GET | `/dashboard` | 仪表盘视图模型（JSON，不是页面） |

> **重要：** `research_report.v1` 中残留的退出状态机、持仓与 sizing 叙述**不属于**
> 可信 `AnalysisRecord`，也不能影响入场准入。可信链路严格止于
> `EntryAdmissionDecision`。

`/strategy/brief` 与 `AnalysisRecord.strategy_brief` 是同一份确定性投影。它只允许
Bull Put Credit Spread、Bear Call Credit Spread 与 Iron Condor，且
`execution_allowed=false`。历史胜率只在 `history.status=VALIDATED` 时出现，预测区间只在
`forecast.status=CALIBRATED` 时出现；来源或新鲜度不可证明时返回 `NO_TRADE`，不会冒充 live。

操作者可重复传入 `--strategy-history-artifact <json>`，以及
`--strategy-forecast-runtime-evidence <json>`。后者不是 promotion artifact 的别名：它必须同时
携带独立刷新的当前 input fingerprint、lineage 和 OOS monitor；缺失、漂移或失效会把预测
机械降级为 `RETIRED` 并清空旧区间。浏览器 query 无权指定这些本地路径。

## 回测作业

回测是有界、异步、可幂等的本地作业，在受限子进程中执行（列表参数、非 shell、
默认 60 秒硬超时、环境变量已剔除凭证）。

### `POST /backtest/run`

只接受严格 JSON 与 `Idempotency-Key` 请求头。不接受查询参数。

```bash
curl -sS -X POST http://127.0.0.1:8000/backtest/run \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: baseline-20260713" \
  --data-binary '{"schema_version":"backtest_run_request.v1"}'
```

| 状态码 | 含义 |
| --- | --- |
| `202` | 入队成功，返回 `/backtest/jobs/{job_id}` |
| `400` | 请求体或幂等键不合法 |
| `409` | 相同 key 但请求体不同；或未配置历史 fixture（`MISSING_HISTORICAL_FIXTURE`） |

相同 key + 相同 body 复用同一作业。超时或失败**不会**提升默认结果指针。

### 作业查询

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/backtest/jobs/{job_id}` | 作业状态 |
| GET | `/backtest/jobs/{job_id}/result` | 作业结果 |
| DELETE | `/backtest/jobs/{job_id}` | 取消作业 |
| GET | `/backtest/report/default` | 当前默认回测报告 |
| GET | `/backtest/report/{report_id}` | 指定的不可变回测工件 |

作业与报告 ID 均由服务端生成，并在拼接文件路径**之前**经正则校验
（`^job-[0-9a-f]{64}$` / `^bt-[0-9a-f]{64}$`），因此不存在路径穿越。

这些端点只读取已持久化的状态或不可变工件。

## 候选排名与预期价值

`/candidates` 返回 `ev_candidate_scanner`。它区分两类结论，不要混淆：

| 字段 | 含义 |
| --- | --- |
| `ranking_score` | **相对价值**：该行权价相对自身微笑曲线的偏离（IV 点）。只需当前链条即可得出。 |
| `ev_after_cost_usdc` | **绝对预期价值**：收信用 − 预期赔付 − 手续费。需要已验证的路径证据，否则为 `null`。 |
| `ranking_basis.method` | 恒为 `pareto_frontier_then_lexicographic`。**不做加权求和**——给不同量纲的分量配权重等于声明未经证实的相对重要性。 |
| `ranking_basis.tie_break_order` | 已发布的打破平局顺序。它影响显示排名，因此是契约而非实现细节。 |
| `dominated_explanations` | `{candidate_id, dominated_by, losing_axes}`——"为什么排这里"的答案。 |
| `path_risk.authoritative_sample_size` | **独立非重叠窗口数**。这是唯一可用于判断置信度的样本量。 |

关于样本量的重要提醒：路径抽样内部还报告一个 similarity effective sample size，它衡量权重集中度，**不考虑窗口重叠**，因而通常比真实独立样本大一个数量级。契约中标注了
`effective_sample_size_accounts_for_overlap: false`，请勿据其判断置信度。

`expected_payout_usdc` 是卖方的**预期赔付（成本）**，不是收益。

`action` 的取值只有 `RESEARCH_ONLY` / `REVIEW` / `REJECT`——没有买卖指令。
`score_status` 恒为 `UNCALIBRATED_RESEARCH_ONLY`：可以排名，但分数未经校准。

### 证据分级

| `evidence_class` | 来源 | 不包含 |
| --- | --- | --- |
| `validated_underlying_price_history` | 自采的公开标的日线（`crypto-options-underlying-history`）| 历史期权报价、历史可成交性 |
| `validated_historical_reconciliation` | 经过对账的历史期权报价（需厂商数据）| — |

绝对 EV 目前建立在前者之上。回测真实成交与模型提升仍需后者。

## 错误响应

错误统一为 JSON，且不泄露内部路径或堆栈：

```json
{"error": "not_found"}
```

## 相关文档

- [术语表](glossary.md)
- [架构总览](architecture.md)
- [生产运行手册](operations/production-runbook.md)
- [安全策略](../SECURITY.md)
