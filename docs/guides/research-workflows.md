# 研究方法与工作流

[项目首页](../../README.md) · [文档地图](../README.md) · [English](research-workflows.en.md)

以下命令均从仓库根目录运行，并已安装项目包。运维步骤依赖运行手册中明确的服务配置，不是离线演示的前置条件。
首次从输入走到结论，请先读 [完整决策研究流程](decision-workflow.md)。

## 核心概念

读其他文档前，建议先了解这几个词（完整定义见 [术语表](../glossary.md)）：

| 术语 | 含义 |
| --- | --- |
| `research_only` | 输出的固定模式：仅供研究，不构成下单指令。不会被任何配置改变。 |
| mode gate（模式门禁） | 拦截一切越界输出的检查点。交易建议、推荐手数、下单指令都被它挡住。 |
| `AnalysisRecord` | 一次分析的**不可变**完整记录，可信输出的载体。 |
| `EntryAdmissionDecision` | 可信输出的**上限**：“能不能进场考虑”，恒有 `execution_allowed=false`。 |
| evidence class | 证据可信度：`trusted` / `degraded` / `untrusted` / `missing`。 |
| replay（可回放） | 同一构建、全部输入、规则与显式时钟产生可比较的确定性输出；身份差异需要解释。 |

## 能力边界

下表说明源码能力，不是本轮测试或真实市场验证报告；实际检查见 [v0.5.0 交付记录](../product/2026-09-08-open-source-decision-platform.md)。

| 能力 | 状态 |
| --- | --- |
| canonical `strategy_brief.v1` 与三表面一屏投影 | 已实现；实际卡片受证据门禁限制 |
| 本地确定性 / 回放研究工具链 | 已实现；固定输入复核不证明数据可信 |
| 经过发布器校验的静态研究产物 | 已实现；发布与托管需各自通过检查 |
| paper / manual 交易、自动下单、真实账户执行 | **NO-GO** |
| exact-strategy 校准与 promotion/demotion 机制 | 已实现；无成熟真实 cohort 时保持 `UNAVAILABLE` / `SCREENING_ONLY` |
| Bull Put / Iron Condor 历史胜率 | **暂不可用**；等待各自冻结协议后的未来 holdout |
| 交易执行授权 | **NO-GO（永久）** |

WebSocket gap/resync、24 小时 soak 与连续 7 天证据仍属于内部运行/执行就绪度，
不会阻止满足数据质量、可复算性和隐私边界的静态研究发布，也不会被静态发布反向放宽。

## 使用方式

### 找出有 edge 的候选

候选比较回答当前链上结构之间的相对差异，并分别度量两类信息：

- **相对价值** — 该行权价相对自身微笑曲线是贵还是便宜。需要链条通过质量与拟合要求。
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

这条命令不冻结时钟；当前研究应先采集新鲜快照。历史复核可传
`--generated-at <snapshot-captured-at-with-timezone>`，但不会恢复当前资格。

排名用 **Pareto 前沿 + 已发布的字典序**，不做加权求和——给不同量纲的分量配权重，
等于声明一个未经证实的相对重要性。被支配的候选会附带“输给了谁、输在哪几个维度”。
当前沿吞掉几乎全部候选（6 个维度下很常见），`frontier_occupancy` 会如实报告排序实际上
已经退化成第一个维度的字典序。

> **样本量只认独立非重叠窗口。** 重叠窗口共享大部分收益观测，不能用其条数冒充独立样本量。
> 实际计数以历史工具输出为准，它受有效观测数、持有期和 stride 共同影响。

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
- 净 vega 与**按到期日拆分的 vega** 并列——净值隐含“波动率平行移动”这个假设。
- 边际贡献按“把它移出组合”来算，而不是它自己的最坏情况。

### 这个行权价昨天也这么贵吗

每日采集本来是为验证样本攒的，但它同时已经回答了另一个问题。

```powershell
crypto-options-report series-history `
  --snapshot-dir artifacts/snapshots/btc-series --compact
```

`tools/capture-daily.ps1` 每次采集后会自动重建这份产物；把它交给引擎（`--series-artifact`）
就能在“序列历史”页里看到**合约 × 采集日**的标准化残差热力图。

三个刻意的设计：

- **用标准化残差而不是原始 IV。** 合约每天都在临近到期，IV、delta、权利金都会因此移动，
  与错价无关；只有按各到期日自身残差尺度标准化后的值才跨日可比。
- **缺采集不是零。** 采集器从几百个挂牌合约里选约一百个、且随现价漂移，所以缺席很常见。
  空心格是“没采”，实心格才是读数，两者从不互相冒充。
- **排序按向零收缩的均值。** 否则只出现三天的合约会靠三个读数排到最前面——这正是这个
  项目到处在防的样本量错误。收缩常数是发布的。

> **持续为正不等于机会。** 一条始终为正的残差，同样可能说明二次拟合在那个行权价上
> 跟不上真实的翼部。这张图在两种情况下长得一样，所以这句话印在图的**上面**而不是下面。

### 这个排序到底能不能预测什么

当前采集器不回补历史期权链。本验证依赖事先保存的逐合约报价、IV 和采集时刻；
只有标的历史或合约成交 K 线不能替代这组证据。缺失日期保持缺失，持续采集后等待合约到期。

采集、计划任务与样本积累见 [操作者指南](operator-guide.md)。

它用**生产代码路径本身**逐日产出候选，按捕获报价与 `daily_close_proxy` 日收盘结算代理
计算假设到期盈亏，给出分档表与信息系数。它不含真实成交证据，也不能复现交易所结算窗口均价。
两个设计决定了它是否值得信：

- **样本量按到期日 cohort 计**，不按观测数。相邻两天的快照是同一批合约、同一个结算价。
- **相关性先做 moneyness 中性化**。原始相关系数被虚值程度主导——一个等价于“按行权价
  排序”的信号在毫无错价信息的对照组里也能拿到 0.95 的 IC。原始值仍并列展示，好让你
  看见这个混淆有多大。

排序主轴自身也在被度量之列，结果可能是 `no_detectable_edge`。**这正是它存在的意义。**

**本样本只有一个事前登记轴可供后续提升审核。** 2026-07-27（当时 0/8 个 cohort 已结算）登记了
`smile_residual_z`，阈值 `|t| ≥ 2.0`。其余九个信号是探索性的——即使某个得分更高，也只能
用于设计下一次登记，不能从这份样本提升。理由是多重比较：约 7 个不同排序下，在同一份样本上
挑最高分再提升，常规阈值有相当概率从噪声里挑出“赢家”。登记内容随验证产物一起发布
（`pre_registration`），界面上也会标出登记轴与本样本得分最高者的区别。
信号验证产物自身不执行模型提升；通过统计门槛也不能绕过模型协议与其余证据要求。

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

### 路径风险与压力结果的口径

历史路径默认 `unconditioned_uniform`。缺少路径开始前的状态特征时，相似状态条件保持不可用；
不能用该路径之后已经发生的收益反过来选择“相似历史”。

`adverse_excursion` 按实际 credit 腿的 `up`、`down` 或 `both` 风险方向计算标的最大不利变动。
它不是期权持有过程中的市值亏损；无法证明方向的结构返回未知。
`short_strike_cross_probability` 度量样本路径穿越短腿行权价的比例。
旧 `delta_cross_probability` 仍是价格阈值代理，动态 Delta 模型明确标为
`unavailable` / `NO_DYNAMIC_DELTA_PATH_MODEL`，不能解读成模拟了持有期间的 Delta。

压力场景包含双向冲击，`scenario_basis=authored_deterministic_shocks` 表示人工定义的确定性压力。
其权重不是校准后的发生概率（`weights_are_calibrated_probabilities=false`），也没有统计置信度
（`statistical_confidence_available=false`）。用于比较结构对指定冲击的反应，不应用它生成胜率。
