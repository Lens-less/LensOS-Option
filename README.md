# Crypto Options Research Console

[English](README.en.md) · 中文

一个**期权入场前的研究工具**：它读取 Deribit 的公开行情，判断「现在有没有一个
值得考虑的卖方机会」，并把结论所依赖的每一份证据都摊开给你看。

它面向的是**自己做决策的期权卖方**——你想要一份可复核、可回放的入场前分析，而
不是一个替你下单的黑盒。

**它不做什么：** 不连接下单接口，不给推荐手数，不做自动或半自动执行。可信输出的
上限是一份 `execution_allowed=false` 的准入结论。这是刻意的设计边界，不是待办事项。

它的两个核心特性：

- **evidence-first**：每个结论都能追溯到具体证据。没有证据支撑的数字不会被编造出来，
  而是显式标记为「缺失」。
- **fail-closed**：证据缺失、过期或校验失败时，一律降级为「阻断」。**没有信号 ≠ 放行。**

## 两种使用形态

| 形态 | 用途 |
| --- | --- |
| **Web 研究工作台** | 筛选、排序、并排对比候选，逐个查看打分依据与收益曲线。挖掘与理解的主场。 |
| **Chrome 研究伴侣** | 在 Deribit 页面上就地回答"我正在看的这张合约有没有 edge、同链有没有更好的"。 |

CLI 与 HTTP API 是驱动这两个界面的**本地引擎接口**，供集成、调度与自动化使用，
不作为独立产品维护。

---

## 快速开始

需要 Python ≥ 3.12。运行时零第三方依赖。

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

用仓库自带的固定快照跑一次完整分析（确定性回放，不联网）：

```powershell
python -m crypto_options_report.cli analysis `
  --snapshot-fixture tests/fixtures/deribit_btc_option_chain_snapshot.json `
  --generated-at 2026-07-07T00:01:30Z --compact
```

启动本地服务并打开证据控制台：

```powershell
python -m crypto_options_report.api --host 127.0.0.1 --port 8000
```

然后访问 <http://127.0.0.1:8000/evidence>。

> **第一次运行会看到大量「不可用 / 缺失」，这是正常的。** 没有配置市场数据源时，
> 产品按设计拒绝编造任何数值。想看到有数据的页面，请用上面的 `--snapshot-fixture`
> 参数，或参考[生产部署](#生产部署)接入实时快照。
>
> 同理，production 模式下 `/readyz` 会稳定返回 `503`：当前没有可提升的模型，
> 就绪门禁按设计保持关闭。**这不代表进程异常**，`/livez` 才表示进程存活。

## 核心概念

读其他文档前，建议先了解这几个词（完整定义见 [术语表](docs/glossary.md)）：

| 术语 | 含义 |
| --- | --- |
| `research_only` | 输出的固定模式：仅供研究，不构成下单指令。不会被任何配置改变。 |
| mode gate（模式门禁） | 拦截一切越界输出的检查点。交易建议、推荐手数、下单指令都被它挡住。 |
| `AnalysisRecord` | 一次分析的**不可变**完整记录，可信输出的载体。 |
| `EntryAdmissionDecision` | 可信输出的**上限**：「能不能进场考虑」，恒有 `execution_allowed=false`。 |
| evidence class | 证据可信度：`trusted` / `degraded` / `untrusted` / `missing`。 |
| replay（可回放） | 同一份快照 + 同一个显式时钟 ⇒ 输出逐字节一致，结论可被独立复核。 |

## 当前状态

| 能力 | 状态 |
| --- | --- |
| 本地确定性 / 回放研究工具链 | **GO** |
| paper / manual 交易、自动下单、真实账户执行 | **NO-GO** |
| 校准与模型提升（model promotion） | 未实现 |
| 对外发布授权 | **NO-GO** |

对外发布门禁要求 WebSocket gap/resync、24 小时 soak 与连续 7 天证据。这些系统观察
条件未满足前，Evidence Console 与 Chrome 侧边栏会持续显示 `NO-GO`。

## 使用方式

### 找出有 edge 的候选

产品的核心问题是"现在这条链上，哪个卖点最划算"。它分两层回答，**不要混淆**：

- **相对价值** — 该行权价相对自身微笑曲线是贵还是便宜。只需当前链条，随时可得。
- **绝对预期价值** — 收信用 − 预期赔付 − 手续费。需要标的的历史收益分布。

先抓一份标的历史（公开数据，无需凭证）：

```powershell
crypto-options-underlying-history --currency BTC --days 1200 `
  --output artifacts/history/btc-daily.json --horizon-days 7 --horizon-days 18
```

它会直接告诉你每个持有期有多少**独立**窗口。窗口不足时对应期限会被阻断，而不是
给出一个样本量不够却看起来很精确的数字。

```powershell
crypto-options-report scan `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

排名用 **Pareto 前沿 + 已发布的字典序**，不做加权求和——给不同量纲的分量配权重，
等于声明一个未经证实的相对重要性。被支配的候选会附带"输给了谁、输在哪几个维度"。
当前沿吞掉几乎全部候选（6 个维度下很常见），`frontier_occupancy` 会如实报告排序实际上
已经退化成第一个维度的字典序。

> **样本量只认独立非重叠窗口。** 从 1200 天日线算 18 天持有期，会得到 1183 个重叠
> 窗口但只有 66 个独立窗口。用前者当样本量会把置信度虚报约 18 倍。

### 候选宇宙

发掘覆盖 call 与 put 两侧，结构由**带符号的腿集合**表达而不是结构名，因此终值盈亏、
最大亏损与仓位希腊值对任意组合都是同一段代码算出来的：

| 结构 | 风险 |
| --- | --- |
| `naked_short_calls` | 无界（`max_loss` 为 `None`，下游比率因此无法成立） |
| `call_credit_spreads` | 有限 |
| `put_credit_spreads` | 有限 |
| `iron_condors` | 有限，双边 |

表名由报告里的 `structure_types` 发布，不需要在消费端硬编码。

### 这几个一起做会怎样

`combination_risk` 把前沿候选当作一个假想组合来看（每个结构一张，**不含任何手数**）：

- **跨到期日不给联合最大亏损**，只给明确标注的上界（各成员最坏情况之和）；只有全部腿
  同一到期日时才算真正的联合 payoff。两个方向相反的价差合起来的最坏情况远小于两者之和。
- 净 vega 与**按到期日拆分的 vega** 并列——净值隐含"波动率平行移动"这个假设。
- 边际贡献按"把它移出组合"来算，而不是它自己的最坏情况。

### 这个排序到底能不能预测什么

**先说数据来源的硬约束：** Deribit 公开 API **不发布历史期权链**。
`get_instruments(expired=true)` 只返回最近一批已到期合约（实测仅当天一个到期日），
逐合约的 TradingView K 线也只对成交过的合约有数据、且不含 IV 与买卖盘。
所以这个验证**无法回溯补数**，只能从今天开始按天采集，等合约自然到期。

每天抓一次，文件按采集时间命名，不会互相覆盖：

```powershell
crypto-options-report pull-snapshot --currency BTC --instrument-limit 64 `
  --output-dir artifacts/snapshots/btc-series --compact
```

`tools/capture-daily.ps1` 把这一步和标的历史刷新打包成一次采集，**历史必须一起刷新**：
它提供每个已结算到期日的结算价，历史过期会让最近结算的 cohort 悄悄掉出样本。注册为
每日计划任务（本地 17:00，即 Deribit 08:00 UTC 结算之后）：

```powershell
$repo = "C:\path\to\Option"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$repo\tools\capture-daily.ps1`"" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At 17:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "LensOS-Option-DailyCapture" `
  -Action $action -Trigger $trigger -Settings $settings -Force
```

采集日志在 `artifacts/logs/capture-daily.log`。同一天跑多次是安全的：验证器按
「日期 × 合约」去重并报告丢弃了多少条，不会让重复行把当日横截面的相关性拉紧。

攒够 8 个已结算的到期日 cohort（BTC 有日到期，按天采集约 2–3 周）后：

```powershell
crypto-options-report validate-signal `
  --snapshot-dir artifacts/snapshots/btc-series `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

样本不足时它会 `blocked` 并写明差多少——**这是正常的，不是故障**。

它一次度量 10 个候选信号（微笑残差的三种量纲、IV 减历史波动率、IV 减 DVOL、期限溢价、
局部偏斜、持仓量占比、深度失衡、报价宽度），并附一份**共线性报告**：数信号不等于数信息。
任何形如「IV 减去一个当日常数」的信号在当日内秩完全相同——拿 DVOL 减和拿历史波动率减
是同一个排序穿了两件衣服。`distinct_signal_estimate` 给出实际有几个不同的排序。

### EV 是负的，到底是哪一种负

一个负的预期价值至少对应三种处境，应对方式相反：样本期恰好包含了卖方被套的那波行情；
edge 真实存在但夹在买卖价之间；或者卖这个形状本来就不划算、有意思的是另一边。

```powershell
crypto-options-report ev-robustness `
  --snapshot-fixture artifacts/snapshots/btc-series/<capture>.json `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

它把三者拆开：**执行敏感度**（在买价/中价/卖价上，买卖两个方向各自的 EV）和
**期间敏感度**（在连续历史切片上重算，看符号是否翻转）。预期赔付与开仓价格无关，所以
四个执行变体不需要任何额外的路径重放，只有切片需要。

`verdict` 只命名数字显示了什么，不给建议：`sign_flips_across_periods`（水平本身没建立起来）、
`no_capturable_edge_at_the_touch`（公允价落在买卖价之间——这是正常市场，不是发现）、
`other_direction_is_positive`（错价在你没筛的那一边）、`negative_across_periods_and_execution`。

它用**生产代码路径本身**逐日产出候选，与到期后的真实盈亏配对，给出分档表与信息系数。
两个设计决定了它是否值得信：

- **样本量按到期日 cohort 计**，不按观测数。相邻两天的快照是同一批合约、同一个结算价。
- **相关性先做 moneyness 中性化**。原始相关系数被虚值程度主导——一个等价于"按行权价
  排序"的信号在毫无错价信息的对照组里也能拿到 0.95 的 IC。原始值仍并列展示，好让你
  看见这个混淆有多大。

排序主轴自身也在被度量之列，结果可能是 `no_detectable_edge`。**这正是它存在的意义。**

### CLI（内部管道）

```powershell
# 抓取一份实时公开快照，供离线分析
python -m crypto_options_report.cli pull-snapshot --instrument-limit 20 `
  --output artifacts/snapshots/btc-chain.json --compact

# 基于快照产出报告；市场数据被阻断时退出码为 10
python -m crypto_options_report.cli report `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --output artifacts/reports/latest.json --fail-on-blocked --compact

# 研究性风险告警（不含任何下单路径）
python -m crypto_options_report.cli alert-eval `
  --snapshot-fixture artifacts/snapshots/btc-chain.json --dry-run --compact
```

调度器可用的退出码：`0` 成功 · `10` 市场数据阻断/缺失 · `11` 触发告警 · `1` 硬错误。
完整示例见 `crypto-options-report --help`。

### HTTP API 与 Evidence Console

Evidence Console 与 API **固定同源**，避免跨源配置和浏览器参数改变生产报告语义。
服务端对同一组输入只生成一次 `AnalysisRecord`，各 GET 投影复用同一份记录，不会重新
拉取数据或重算结论。

主要端点：`/evidence`（控制台）· `/research/report` · `/analysis/result` ·
`/health` · `/livez` · `/readyz`。完整列表、鉴权要求与响应契约见
[API 参考](docs/api-reference.md)。

### Chrome 研究伴侣（个人本地）

面向个人本地使用的 Manifest V3 侧边栏（Chrome 114+）：

```powershell
cd web
npm ci
npm run build:extension
```

在 `chrome://extensions` 打开「开发者模式」→「加载已解压的扩展程序」→ 选择
`web/dist/chrome-extension/`，然后在 Deribit 页面点击工具栏图标。

侧边栏只读取 `http://127.0.0.1:<port>/research/report`，只识别当前 Deribit 合约并
展示研究上下文；**不包含订单、交易、张数或 sizing 控件**。合约上下文按标签页隔离。

## 生产部署

推荐把公共行情、私有只读账户和 Web API 拆成三个进程：凭证只存在于 sidecar 进程，
API 进程只读取脱敏后的 JSON。生产 HTTP 禁止浏览器指定 fixture、账户场景、评估时间
或实时抓取。

服务默认只监听 loopback，必须部署在认证 / TLS 反向代理之后，不能直接暴露到公网。

完整的容器、健康检查、HMAC 密钥管理、密钥轮换、回滚与验证步骤见
**[生产运行手册](docs/operations/production-runbook.md)**；环境变量清单见
[`.env.example`](.env.example)。

## 开发

```powershell
python -m pytest -q
python -m ruff check crypto_options_report tools tests

cd web
npm ci && npm test && npm run lint && npm run build
```

`npm run build` 会更新 `crypto_options_report/static/evidence/`，该产物随 wheel 和
容器一起发布，**必须与源码一起提交**（CI 会校验一致性）。

贡献流程与设计红线见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 项目地图

| 路径 | 职责 |
| --- | --- |
| `crypto_options_report/analysis_run.py` | 不可变的 mandate、证据、策略与准入契约 |
| `crypto_options_report/contract.py` | `research_report.v1` 兼容投影 |
| `crypto_options_report/api.py` | stdlib HTTP API、`/evidence` 与旧 URL 兼容层 |
| `crypto_options_report/market_data.py` | Deribit 接入、快照规范化与质量门禁 |
| `crypto_options_report/structures.py` | 多腿结构：终值 payoff、风险边界、仓位希腊值 |
| `crypto_options_report/signal_validation.py` | 排序信号的预测力度量（分档表与信息系数） |
| `crypto_options_report/combination_risk.py` | 组合聚合与边际风险 |
| `crypto_options_report/_canonical.py` | 全局唯一的规范化 JSON 编码（所有摘要的基础） |
| `web/` | 共享报告边界、Evidence Console、Chrome 侧边栏源码 |
| `tests/` | 契约、API、数据质量、风险与 fail-closed 证据测试 |
| `docs/` | 术语表、API 参考、架构说明、运行手册（见 [文档地图](docs/README.md)） |

## 安全边界

本项目**刻意不包含实盘下单适配器**。可信输出上限是 `execution_allowed=false` 的
`EntryAdmissionDecision`，其中不含可执行张数或下单指令。裸卖 call 只作为「已拒绝的
无界损失对照」出现在可信记录中。

不要以「清理研究控制台」的名义加入订单模板、下单路径、paper/manual 候选控件或
sizing 输出。

漏洞请通过 GitHub Security Advisory 私下报告，详见 [SECURITY.md](SECURITY.md)。

Deribit 接入以官方 [public market-data API](https://docs.deribit.com/api-reference/market-data/public-get_order_book)
和 [OAuth / API key scopes](https://docs.deribit.com/api-reference/authentication/public-auth) 为准。
任何 `account:read_write` 或 `trade:read_write` key 都会被账户 sidecar 拒绝。

## 许可

尚未选定许可证。在选定并加入 `LICENSE` 之前，本仓库默认保留所有权利，不可再分发。
