# 术语表

本项目自造词较多，且很多词在金融语境下另有含义。这里给出本仓库内的确切定义。
枚举值均取自 `crypto_options_report/analysis_run.py`。

## 核心理念

**evidence-first（证据优先）**
每一个结论都必须能追溯到一份具体的、带来源和时间戳的证据。没有证据支撑的数值
不会被输出为结论，而是显式标记为「缺失」。产品宁可少说，不可编造。

**fail-closed（失败即阻断）**
当证据缺失、过期或校验失败时，系统一律降级为「阻断」，而不是沿用旧值或给出乐观
默认值。这是本项目最核心的安全属性：**没有信号 ≠ 放行**。

**research_only（仅研究）**
产品输出的固定模式。它意味着输出仅供研究参考，不构成下单指令，也不含可执行的
手数。这个标记不会因为配置、环境变量或浏览器参数而改变。

**mode gate（模式门禁）**
拦截一切「越界输出」的检查点。任何交易建议、推荐手数、下单指令、paper/manual
候选都必须被它拦下，直到外部数据、账户、校准与纸面对账证据全部满足 Definition
of Done。当前这些条件未满足，因此门禁保持关闭。

**replay（可回放）**
给定同一份输入快照和同一个显式的 `--generated-at` 时钟，输出必须逐字节一致。
这让任何一次结论都可以被独立复核。

## 核心数据契约

**`AnalysisRecord`**
一次分析的**不可变**完整记录，是可信输出的载体。服务端对同一组输入只生成一次，
各个 GET 投影复用同一份记录，不会重新拉取数据或重算结论。

**`research_report.v1`**
`AnalysisRecord` 的**兼容投影**，供 `/evidence`、Chrome 伴侣和旧客户端读取。
注意：其中残留的退出状态机、持仓与 sizing 叙述**不属于**可信记录，也不能影响
入场准入。

**`EntryAdmissionDecision`**
可信输出的**上限**。它描述「这个机会现在能不能进场考虑」，恒有
`execution_allowed=false`，且不含可执行手数或下单指令。

**`PreEntryRiskClaim`**
组合/交易所层面的否决输入。只接受哈希绑定的类型化声明；兼容字段里的
`final_action` 字符串**不是**决策输入。

## 状态枚举

**`EvidenceState`** — 一份证据的可信程度：

| 值 | 含义 |
| --- | --- |
| `trusted` | 已验证，可作为结论依据 |
| `degraded` | 可读但不足以支撑结论 |
| `untrusted` | 存在但校验失败 |
| `missing` | 不存在 |

**`EdgeClass`** — 机会所依赖的证据强度等级，`E1` 最强、`E3` 最弱。`E3` 类机会
需要绑定已提升（promoted）的模型工件才能通过准入。

**`OpportunityStatus`** — `DETECTED`、`NO_OPPORTUNITY`、`EVIDENCE_BLOCKED`、
`MODEL_BLOCKED`、`COST_BLOCKED`、`EXPIRED`、`INVALIDATED`。后五者说明「为什么
没有机会」，这比单纯的「无」更有信息量。

**`EntryAdmissionStatus`** — 准入结论：

| 值 | 含义 |
| --- | --- |
| `BLOCKED_BY_EVIDENCE` | 证据不足，无法评估 |
| `NO_OPPORTUNITY` | 证据充分，但当前无机会 |
| `MONITOR_ONLY` | 值得关注，尚不满足进场条件 |
| `DEFERRED` | 需要等待外部条件 |
| `VETOED` | 被组合/交易所风险否决 |
| `CONDITIONALLY_ELIGIBLE` | 满足全部已实现的检查项。**这不是下单指令** |

**`ConditionStatus`** — 单个准入检查项的结果：`PASS` / `BLOCK` / `UNKNOWN`。
`UNKNOWN` 与 `BLOCK` 一样不会放行，这正是 fail-closed 的体现。

**`PreEntryRiskState`** / **`ExchangeHealthState`** — `CLEAR` / `VETO`（或
`BLOCKED`）/ `UNKNOWN`。

## edge 与预期价值

**相对价值（relative value）**
"这个行权价相对**自身微笑曲线**是贵还是便宜"。只需当前链条即可得出，不需要历史。
它**不能**告诉你卖波动率是否赚钱——那是绝对预期价值的问题。

**绝对预期价值（absolute EV）**
`收信用 − 预期赔付 − 手续费`。需要标的的实现收益分布，因此需要历史证据。

**预期赔付（expected payout）**
契约字段 `expected_payout_usdc`。它是卖方**要付出去的成本**，不是收益。把它当成
收益会让每个结论正负颠倒。

**Pareto 前沿**
排名方法。若某候选在所有可比维度上都不优于另一个，则它被"支配"。前沿内部再按
**已发布的**字典序打破平局。项目刻意**不做加权求和**：给不同量纲的分量配权重，
等于声明一个未经证实的相对重要性。

**支配关系（dominated_by / losing_axes）**
"为什么它排在这里"的答案：它被哪个候选支配、输在哪几个维度上。

**独立窗口（independent window）**
样本量的唯一正确口径。从 N 天日线计算 T 天持有期收益，会得到 N−T 个**重叠**窗口，
但独立样本只有约 N/T 个。重叠窗口共享绝大部分观测，用它当样本量会把置信度
虚报约 T 倍。契约中的 `authoritative_sample_size` 即独立窗口数。

> 注意：路径抽样内部还有一个 similarity effective sample size，它衡量权重集中度，
> **不考虑窗口重叠**。契约用 `effective_sample_size_accounts_for_overlap: false`
> 标注了这一点，不要据其判断置信度。

**证据分级（evidence class）**
`validated_underlying_price_history` 来自自采的公开标的日线，足以刻画收益分布，但
**不含**历史期权报价与可成交性。`validated_historical_reconciliation` 来自经过对账
的历史期权报价，需要厂商数据。前者不会借用后者的名号。

## 运行时概念

**runtime profile（运行配置）**
`local` 与 `production` 两种进程运行配置，与业务 `mode` **相互独立**。即使跑在
production profile 下，业务模式依然是 `research_only`。

**sidecar（边车进程）**
独立于 Web API 的取数进程，分为公共行情与私有只读账户两类。凭证只存在于 sidecar
进程中，API 进程只读取脱敏后的 JSON。二者使用不同的环境变量和不同的 HMAC 密钥。

**trust evidence（信任证据）**
以 SHA-256 绑定快照的旁路文件（`<snapshot>.trust.json`）。快照 JSON 内部自带的
`trust_evidence` 字段**不会**被接受，避免数据源自证可信。

**readiness（就绪）**
`/livez` 只表示进程存活；`/readyz` 表示业务依赖是否齐备。当前没有可提升的模型，
因此 production 的 `/readyz` 按设计保持 `503` 并给出原因码——**这不代表进程异常**。

**Definition of Done**
解除某个门禁所需的外部证据清单。它要求的是真实世界的证据（外部数据、账户、校准、
纸面对账），而不是代码里的开关。

## 相关文档

- [`architecture.md`](architecture.md) — 这些概念如何串成一条信任链路
- [`api-reference.md`](api-reference.md) — 各端点返回哪些契约
- [`../SECURITY.md`](../SECURITY.md) — 安全边界
