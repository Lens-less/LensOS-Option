# LensOS Option v0.2–v0.4 · 极简策略简报产品规格

> 状态：Released — v0.4.0
> 起草日：2026-08-30
> 产品边界：`RESEARCH_ONLY / NO_AUTO_EXECUTION / NO_PERSONALIZED_SIZING`
> 目标版本：v0.2「市场与策略简报」→ v0.3「可信历史表现」→ v0.4「校准预测胜率」
> 核心原则：**把复杂留给系统，把市场结论、策略、合约和风险用一屏交给用户。**

---

## 0. 文档权威与关系

本文定义 v0.2–v0.4 的统一产品形态、用户可见语义、数据契约、策略准入、历史表现、
预测胜率和验收标准。

本文：

- 取代旧文档中以“证据台 / 工作台 / 序列 / 信号”为首页主叙事的产品信息架构；
- 不降低 `data-trustworthiness-prd.md`、现有 market-data gate 与 fail-closed 约束；
- 不修改 `docs/automation/strategy-eval-spec.md` 已冻结的 holdout、成本、比较基准和
  `RESEARCH_ONLY` 约束；
- 不修改 `docs/model-promotion.md` 已登记的排名信号、样本外确认、过期和降级规则；
- 不授权自动下单、账户级仓位建议、实盘执行或任何凭证暴露；
- 允许输出精确的一单位策略组合，供用户人工复核和手工录入。

若本文的极简展示与底层证据约束发生冲突，证据约束优先；产品必须简化表达，不能简化真值。

实施前还必须确认工作树基于真实发布版本。2026-08-30 审计时，本地 `main` 落后于远端，
且并非实际公开 `v0.1.0` 的发布树。不得在未核对基线、未保护用户现有未跟踪文件的情况下
直接开始大规模实现。

---

## 1. 一句话产品定义

> 用户在 30 秒内知道：当前市场是什么状态、今天有没有值得研究的策略、具体买卖哪些
> 合约、历史表现或预测胜率是否可信、最多亏多少，以及什么情况下不要做。

LensOS Option 不再把研究模块本身当作产品首页。首页是每天更新的一份“一屏式策略简报”；
残差、曲面、IC、cohort、校准、数据 lineage 和所有 gate 仍然存在，但默认收在“查看依据”中。

---

## 2. 为什么要做

当前产品能够产生丰富研究证据，但用户还需要自己完成四次翻译：

1. 把曲面和波动率信息翻译成市场状态；
2. 把候选排序翻译成策略；
3. 把策略翻译成具体合约腿；
4. 判断排序分数、历史表现或模型结果究竟能不能信。

当前存档研究产物还暴露了三个必须先消除的误导风险：

- `scan.json` 的顶部候选可以同时具有负的成本后 EV、无上限亏损和不可用保证金；
- `robustness.json` 中已测试的四个候选全部为 `other_direction_is_positive`；
- 截至 2026-08-30，真实 `signal-preflight.json` 只有 4/8 个已结算 research-window
  cohort，尚不能生成可信预测胜率。

这些产物不是当前实时交易建议，但证明“候选排得高”与“策略值得做”不能共用一个用户语义。

---

## 3. North Star 与成功标准

### 3.1 North Star

**有效策略简报率**：在数据和证据允许时，系统能生成 0–3 张完整、可复核、未过期、
有限风险的策略卡；证据不允许时，系统能明确输出 `NO_TRADE`，且不泄露伪精确绩效。

### 3.2 用户成功标准

用户无需理解内部模型，也能在一屏回答：

- 市场偏多、震荡、偏空，还是无法判断？
- 隐含波动率偏贵、正常、偏便宜，还是无法判断？
- 今天是有策略、仅观察，还是不交易？
- 推荐的结构是什么？
- 每条腿买还是卖、合约代码是什么、数量是多少？
- 最低可接受净权利金、最大亏损和有效时间是什么？
- 历史表现是否已经验证？
- 当前预测胜率是否已经校准？
- 哪个条件触发后应取消这张策略卡？

### 3.3 产品级硬指标

- 首页默认最多展示 3 张策略卡；0 张是完全合法的结果。
- 100% 的策略卡包含精确合约腿、方向、数量、入场口径、最大亏损和 `valid_until`。
- 0 张 `RECOMMENDED` 卡允许 `ev_after_cost <= 0`。
- 0 张 `RECOMMENDED` 卡允许无上限亏损、未知最大亏损或未知路径风险。
- 0 个预测胜率数字允许在 `forecast.status != CALIBRATED` 时展示。
- 0 个历史胜率允许把重叠 observation 数量冒充独立样本数。
- 0 张已过期或多腿不同步的卡继续显示为有效策略。
- 没有候选时，首页必须给出清晰的 `NO_TRADE` 原因，而不是空表格。
- 目标用户在首次使用测试中，30 秒内正确复述市场状态、首选策略和最大亏损。

---

## 4. 范围与非目标

### 4.1 本期范围

- BTC Deribit 期权；
- 7–35 天到期研究窗口；
- 三种有限风险卖方结构：
  - `BULL_PUT_CREDIT_SPREAD`；
  - `BEAR_CALL_CREDIT_SPREAD`；
  - `IRON_CONDOR`；
- 每张卡使用一单位标准组合；
- 当前市场状态、执行合约、成本后经济性、最大亏损、历史表现和预测胜率；
- 内部实时版、公开静态版和 Chrome 侧栏共用同一简报语义；
- 复制组合文本，供人工在交易所界面复核和录入。

### 4.2 明确非目标

- 自动下单、半自动下单或 API 交易；
- 根据真实账户 NAV 推荐合约数量；
- 裸卖 Call、裸卖 Put 或其他无上限亏损结构；
- 在本期加入 debit spread、calendar、butterfly、straddle 等新策略族；
- 多交易所、多标的或跨交易所套利；
- 用一个综合分隐藏相对价值、绝对 EV、流动性和风险差异；
- 为了“每天有推荐”而放松门禁；
- 在证据不足时生成预测胜率；
- 用 mark/mid 价格冒充可执行入场价格；
- 用 Delta、到期价外概率或排名 IC 冒充策略胜率；
- 大规模视觉换皮、微服务拆分或与本产品结果无关的工程重构。

---

## 5. 一个最终产品，三个证据阶段

v0.2–v0.4 不是三套界面，也不是三份不兼容合同。v0.2 起即采用最终的一屏式简报和
`strategy_brief.v1` 合同；后续版本只让已有字段从“不可用”晋级为“可信可用”。

| 版本 | 用户得到什么 | 尚不能声称什么 |
| --- | --- | --- |
| v0.2 | 市场一句话判断、0–3 张精确策略卡、具体合约腿、可执行入场口径、最大亏损、有效期和取消条件 | 不能把探索性回测称为可信历史胜率；不能显示预测胜率 |
| v0.3 | 与推荐策略完全同口径、通过独立 holdout 的历史胜率、平均净 `R`、最差表现和样本范围 | 历史胜率不是当前市场预测胜率 |
| v0.4 | 对精确策略结果校准后的预测胜率区间、可信度、适用范围、promotion/demotion 状态 | 不授权自动交易或个性化仓位 |

版本演进必须保持 schema 向后兼容：

- v0.2 的 `history.status = INSUFFICIENT | EXPLORATORY`；
- v0.2 的 `forecast.status = UNAVAILABLE | SCREENING_ONLY`；
- v0.3 可将 `history.status` 晋级为 `VALIDATED` 或定论为 `FAILED`；
- v0.4 可将 `forecast.status` 晋级为 `CALIBRATED`，或保持不可用；
- 任何晋级都可以在证据失效后退回非晋级状态。

---

## 6. 用户体验与页面信息架构

### 6.1 首页固定结构

首页只包含四个主区域：

1. 市场一句话；
2. 今日行动；
3. 最多三张策略卡；
4. 默认折叠的“查看依据”。

示意：

```text
BTC：震荡偏多｜隐含波动率偏贵｜流动性可执行
今日行动：有 2 个有限风险策略值得观察
更新于 14:30:05｜有效至 14:35:05

① Bull Put Spread       ② Iron Condor
   观察                    观察
   精确合约腿               精确合约腿
   最低净权利金             最低净权利金
   最大亏损                 最大亏损
   历史：样本不足           历史：样本不足
   预测：暂不可用           预测：暂不可用

[查看依据]
```

示意中的状态和时间只是布局占位，不是市场结论。

### 6.2 信息优先级

首屏必须优先显示：

- 市场状态；
- 今日行动；
- 策略名称；
- 合约腿；
- 入场条件；
- 最大亏损；
- 历史 / 预测是否可信；
- 有效时间。

以下信息默认折叠：

- 曲面拟合和残差；
- IC、t-stat、cohort 进度；
- 费用明细、路径风险分布和 bootstrap；
- 数据来源、hash、模型版本和证据 lineage；
- 所有内部 reason codes。

折叠不等于删除。每个用户结论必须能从“查看依据”回溯到完整证据。

### 6.3 空状态

没有策略时不展示空表格，改为完整的 `NO_TRADE` 卡：

```text
今日暂无可靠策略

主要原因：
1. 当前隐含波动率没有提供足够的成本后溢价；
2. 可用结构的报价或风险证据不足。

下次更新：14:35
```

用户可展开查看所有阻断原因，但首页最多显示两个最重要原因。

---

## 7. 市场状态规格

### 7.1 用户可见字段

| 字段 | 类型 | 用户含义 |
| --- | --- | --- |
| `underlying` | string | 当前仅 `BTC` |
| `as_of` | timestamp | 市场数据截止时间 |
| `expires_at` | timestamp | 本次市场判断失效时间 |
| `direction` | enum | `BULLISH / RANGE / BEARISH / UNCLEAR` |
| `volatility` | enum | `CHEAP / FAIR / RICH / UNKNOWN` |
| `liquidity` | enum | `EXECUTABLE / LIMITED / UNAVAILABLE` |
| `confidence` | enum | `HIGH / MEDIUM / LOW / UNAVAILABLE` |
| `action` | enum | `STRATEGIES_AVAILABLE / WATCH / NO_TRADE` |
| `summary_zh` | string | 一句自然语言结论 |

### 7.2 市场状态到策略族的默认映射

| 方向 | 波动率 | 默认研究结构 |
| --- | --- | --- |
| `BULLISH` | `RICH` | Bull Put Credit Spread |
| `RANGE` | `RICH` | Iron Condor |
| `BEARISH` | `RICH` | Bear Call Credit Spread |
| 任意 | `CHEAP / FAIR / UNKNOWN` | 默认 `NO_TRADE`；除非未来另有已验证 edge class |
| `UNCLEAR` | 任意 | 默认 `NO_TRADE` |

该表只决定“生成哪些结构进行研究”，不直接产生推荐。所有结构仍需通过执行、经济性、风险和
证据门禁。

### 7.3 时效与同步

- 市场 headline 使用当前分析时钟，不得用发布时钟冒充行情时间；
- 每条腿必须满足现有 quote freshness gate；
- 多腿 `observed_at` 最大偏差不得超过 2 秒；
- live 策略 TTL 不再无条件继承固定 600 秒，应取以下最小值：
  - 当前 policy 上限；
  - 任一腿报价剩余有效期；
  - 市场状态剩余有效期；
  - 模型或账户风险证据剩余有效期；
- 价差、深度或波动状态快速恶化时允许进一步缩短 TTL；
- public static 版继续使用独立 publication cadence 和 `stale_after`，不得把每日发布伪装成
  秒级实时建议。

---

## 8. 策略卡规格

### 8.1 用户可见字段

每张策略卡必须展示：

| 区域 | 字段 |
| --- | --- |
| 身份 | 排名、策略名称、`recommendation_status`、一句话逻辑 |
| 合约 | 每条腿 `BUY/SELL`、instrument name、quantity |
| 入场 | `price_basis`、最低可接受净权利金、币种 / 单位 |
| 风险 | 每一单位组合最大亏损、盈亏平衡点、到期日 |
| 历史 | 状态；验证后显示胜率、平均净 `R`、独立样本范围 |
| 预测 | 状态；校准后显示胜率区间和可信度 |
| 生命周期 | `as_of`、`valid_until`、最多两个取消条件 |

### 8.2 状态语义

用户只看到三类状态：

- `RECOMMENDED` / 推荐：当前经济性和风险通过，且至少有可信历史支持或校准预测支持；
- `WATCH` / 观察：市场和结构值得关注，但历史或预测证据尚未达到推荐门槛；
- `NO_TRADE` / 不交易：没有任何结构通过硬门禁。

被硬门禁拒绝的单个候选不会作为第四种卡混入 Top 3；它只出现在折叠的“未采用方案”中。

页面级 `action` 与卡片状态的映射必须是确定性的：

| `strategies` 内容 | 页面 `action` |
| --- | --- |
| 至少一张 `RECOMMENDED` | `STRATEGIES_AVAILABLE` |
| 没有 `RECOMMENDED`，但至少一张 `WATCH` | `WATCH` |
| 空数组 | `NO_TRADE` |

`strategies` 数组中不放置 `NO_TRADE` 占位卡。`NO_TRADE` 只通过页面 action 和顶层
`no_trade` 对象表达。不同 UI surface 不得自行推导另一套映射。

### 8.3 标准一单位组合

- 每个策略默认展示 `1 × strategy unit`；
- Vertical 的一单位为卖出腿 1 张 + 保护腿 1 张；
- Iron Condor 的一单位为四条腿各 1 张，方向按结构定义；
- 卡片必须展示该一单位的最大亏损和权利金单位；
- 不根据用户 NAV 自动放大 quantity；
- 若无法得到真实账户保证金或最大亏损，状态不得为 `RECOMMENDED`。

### 8.4 复制组合

每张卡提供“复制组合”按钮，输出稳定文本：

```text
STRATEGY: <strategy name>
SELL 1 <instrument>
BUY  1 <instrument>
MIN NET CREDIT: <amount> <unit>
MAX LOSS PER UNIT: <amount> <unit>
VALID UNTIL: <timestamp>
CANCEL IF: <condition>
RESEARCH_ONLY / MANUAL REVIEW REQUIRED
```

Iron Condor 按四条腿输出。按钮只复制文本，不打开或提交交易票据。

---

## 9. 策略生成、过滤与排序

### 9.1 处理顺序

后台必须遵循：

```text
Market State
  → Eligible Strategy Families
  → Exact Contract Combinations
  → Executable Quote Construction
  → Cost and Absolute-EV Gate
  → Defined-Risk and Path-Risk Gate
  → Historical / Forecast Evidence Gate
  → Rank Within One Defined-Risk Bucket
  → 0–3 User Cards
```

排名永远发生在硬门禁之后。高排名不能覆盖任何数据、执行、成本或风险否决。

### 9.2 Top 3 硬门禁

任一候选满足以下任一条件，均不得成为 `RECOMMENDED`：

- market data 非可信或已过期；
- 任一腿缺少正的双边报价；
- 多腿时间差超过 2 秒；
- 使用 mid / mark 作为默认可执行价格；
- executable net credit 非正；
- `ev_after_cost <= 0`；
- robustness verdict 为 `other_direction_is_positive`；
- robustness verdict 为 `no_capturable_edge_at_the_touch`；
- `UNBOUNDED_LOSS_STRUCTURE`；
- 最大亏损、保证金或路径风险未知；
- path-risk evidence 未达到允许的状态；
- 费用、滑点、legging 或 settlement 单位未知；
- premium、payoff、settlement currency 或 inverse/linear 单位不一致；
- 策略已过期或命中 kill condition；
- 预测胜率被请求展示，但 forecast 尚未校准。

其中经济性、执行和风险已通过，但历史 / 预测证据仍在积累的候选，可以成为 `WATCH`，不能
成为 `RECOMMENDED`。

### 9.3 相对价值与绝对 EV 分离

- `relative_value` 只回答“相对同链或拟合曲面是否更贵”；
- `absolute_ev` 只回答“按可执行价格、成本和结果分布，净期望是否为正”；
- relative-value 异常可以进入研究详情；
- 只有 absolute-EV 和风险门禁通过的结构才能进入策略卡；
- 不允许用一个 blended score 合并两种 claim。

### 9.4 排序规则

通过门禁后，按以下顺序选择 Top 3：

1. `RECOMMENDED` 优先于 `WATCH`；
2. 保守净 `R` 下界更高者优先；
3. 最大亏损和 CVaR 更低者优先；
4. executable liquidity 更好者优先；
5. 合约到期、行权价和 instrument name 作为确定性 tie-break；
6. 同一策略族默认只保留一张主卡，避免三个近似 spread 占满首页。

用户不看到综合分，只看到排序后的策略和关键理由。

---

## 10. v0.2 · 市场与策略简报

### 10.1 交付范围

- 新增 `strategy_brief.v1` canonical artifact / API projection；
- 生成市场一句话、行动状态和 0–3 张策略卡；
- 为每张卡输出精确合约腿、可执行入场口径、最大亏损、到期日、TTL 和 kill conditions；
- 将候选榜拆为“相对异常研究”和“策略简报”，不再共用一个 Top Candidate 语义；
- 首页、Chrome 侧栏和 public 版使用同一 selector / status semantics；
- 历史和预测字段存在但默认显示证据状态，不生成伪数字。

### 10.2 v0.2 用户语义

v0.2 允许：

- “当前市场震荡偏多、隐含波动率偏贵”；
- “这个 Bull Put Spread 的报价、成本后 EV 和最大亏损值得观察”；
- “精确组合是卖出 X、买入 Y，最低净权利金为 Z”；
- “历史表现样本不足”；
- “预测胜率暂不可用”。

v0.2 不允许：

- “胜率 70%”，如果没有与精确策略同口径的历史验证；
- “模型预测胜率 70%”，如果 forecast 未校准；
- 把相对残差较高称为“卖方有 edge”；
- 把负 EV 或反方向更优的结构放进策略卡；
- 根据用户账户推荐做几组。

### 10.3 v0.2 Definition of Done

- `strategy_brief.v1` 有 Python validator、TypeScript contract 和运行时 validator；
- live、replay、public artifact 对相同 AnalysisRecord 产生相同策略语义；
- 负 EV、反方向更优、无上限亏损、过期和多腿不同步 fixture 均产生 0 张推荐卡；
- eligible defined-risk fixture 产生精确、确定性的卡片和复制文本；
- UI 在 320–1440px 宽度下首屏都先显示 headline、action、cards；
- 无历史 / 预测证据时不渲染任何 plausible percentage；
- `execution_allowed` 始终为 `false`；
- Python、Web、public、extension 的相关 lint、typecheck、tests、build 全部通过。

---

## 11. v0.3 · 可信历史表现

### 11.1 历史表现的唯一合法定义

“历史胜率”定义为：

> 在同一结构、同一方向、同一 DTE band、同一选腿规则、同一入场价格、同一持有 / 退出规则、
> 同一费用和 settlement 口径下，成本后净 PnL 大于零的独立策略结果占比。

以下均不属于该策略历史胜率：

- Delta 或到期价外概率；
- smile residual 的命中方向；
- 排名 IC；
- 使用不同结构的 naked-call baseline；
- 使用 mark/mid 入场的回测；
- 使用不同退出规则或不同 DTE band 的结果；
- observation count 未按到期 cohort 聚类的百分比。

### 11.2 固定回放协议

每个结构族在读取最终 holdout 之前必须冻结：

- 结构和方向；
- 到期窗口；
- 选腿和 tie-break；
- 入场价格：short at bid、long at ask，并按冻结协议加入不利 tick / slippage；
- 费用和 settlement；
- 第一版统一 hold to expiry；
- 样本排除规则；
- purge、35 天 embargo 和 walk-forward split；
- no-trade 与同结构简单 comparator；
- 成本压力情景；
- 代码、配置和数据 manifest hash。

任何 early-exit 规则都需要新的冻结协议和独立历史结果，不能复用 hold-to-expiry 胜率。

### 11.3 历史状态

| 状态 | 用户展示 | 后台含义 |
| --- | --- | --- |
| `INSUFFICIENT` | 历史：样本不足 | 独立 cohort、观测、连续性或 regime 覆盖不足 |
| `EXPLORATORY` | 历史：探索中 | 开发样本可计算，但没有封存的策略级 holdout 结论 |
| `VALIDATED` | 历史胜率、平均净 R、独立样本数 | 所有冻结的性能、比较、成本压力、稳定性和风险门禁通过 |
| `FAILED` | 历史：未通过 | 样本充分，但任一冻结门禁失败 |

`INSUFFICIENT` 和 `EXPLORATORY` 不在首页显示百分比。原始探索性数字可以进入开发者证据页，
不得出现在普通用户策略卡。

### 11.4 `VALIDATED` 最低门槛

沿用并扩展 `docs/automation/strategy-eval-spec.md`：

- aligned replay 冻结后，至少 8 个进一步的独立已结算 expiry cohorts；
- 至少 100 个有效策略观测；
- 至少覆盖两个 volatility / trend / liquidity regimes；
- 任一 regime 不得贡献超过 60% 的最终 cohorts；
- 95% cohort-bootstrap 下，平均净 `R` 下界大于 0；
- 相对同结构简单 comparator 的配对差值大于 0；
- 1.5× 成本压力后仍为正；
- 最大回撤、CVaR、单 cohort / 单月贡献和风险预算满足冻结协议；
- 无上限亏损、未知最大亏损、未知 margin 或未知单位自动失败。

Bull Put Spread 和 Iron Condor 当前没有与现行 Call Credit Spread 完全等价的冻结策略级协议；
在各自协议完成并获得未来 holdout 前，它们的历史状态必须保持 `INSUFFICIENT` 或
`EXPLORATORY`。

现有冻结的可晋级策略边界只覆盖 `CALL_CREDIT_SPREAD`，对应本 spec 的
`BEAR_CALL_CREDIT_SPREAD` 方向。v0.3 实现不得把这个结果横向借给 Bull Put Spread 或
Iron Condor；只有具备本策略族自身 aligned replay、冻结协议和未来 holdout 的结构，才允许
进入 `VALIDATED`。

### 11.5 首页最小展示

历史验证后，策略卡只显示：

```text
历史胜率：68%
平均净收益：+0.21R
独立样本：12 个到期 cohort
```

数字仅为布局示例，不是本项目当前结果。最大回撤、CVaR、置信区间、成本压力和 regime
分解进入折叠详情。

### 11.6 v0.3 Definition of Done

- 三种结构均有独立、冻结、可重放的评估协议，或诚实保持非验证状态；
- live 和 replay 共用同一结构、费用、单位和 payoff 语义；
- 每个历史结果可回溯到 immutable ledger / artifact；
- 同一输入与配置产生相同结果 hash；
- lookahead、重叠窗口、重复 observation 和 settlement proxy 回归测试通过；
- 只有 `VALIDATED` 在普通用户卡片展示历史胜率；
- `FAILED` 不会被 UI 换词包装成“低置信度推荐”；
- v0.2 的简报合同不发生破坏性变更。

---

## 12. v0.4 · 校准预测胜率

### 12.1 预测对象

预测胜率必须回答：

> 对这张策略卡中的精确结构、方向、DTE band、入场 / 成本和 hold-to-expiry 规则，当前进入后
> 最终成本后净 PnL 大于 0 的概率是多少？

它不是：

- 标的上涨概率；
- 期权到期价外概率；
- risk-neutral `P(ITM)`；
- Delta；
- smile residual 排名；
- 排名信号的 IC；
- 没有与当前结构对齐的历史 hit rate。

### 12.2 预测状态

| 状态 | 用户展示 | 允许的产品行为 |
| --- | --- | --- |
| `UNAVAILABLE` | 预测：暂不可用 | 不显示任何胜率数字 |
| `SCREENING_ONLY` | 预测：仅用于排序 | 可帮助后台排序，不显示胜率数字 |
| `CALIBRATED` | 预计胜率区间 + 可信度 | 可参与 `RECOMMENDED` 判定 |
| `RETIRED` | 预测：已失效 | 立即隐藏旧胜率并降级策略状态 |

### 12.3 排名 promotion 与胜率 calibration 分离

现有 `smile_residual_z` 预登记、8 个独立 cohort 和至少 4 个后续 OOS cohort，只能支持
限定范围内的“排序 claim”。即使排名 promotion 成功，也不能直接输出策略胜率。

策略胜率模型必须另行冻结目标、特征、训练 / 验证 split、概率校准方法、基准模型、
适用范围和 demotion 规则，并使用与策略卡完全一致的 outcome。

### 12.4 `CALIBRATED` 最低门槛

- 模型和校准器在读取最终 holdout 前预登记并冻结；
- 使用 purged / embargoed walk-forward，按 expiry cohort 保持独立性；
- 满足 v0.3 的策略级最小 holdout、观测和 regime 覆盖；
- sealed OOS 上的 Brier score 优于无条件 base-rate 模型；
- 概率可靠性没有系统性反向或严重失真；
- 当前卡片的 95% 概率区间可计算，且宽到无法决策时必须 suppress；
- 相应策略的成本后平均净 `R` 及风险门禁仍然通过；
- 每次预测记录 model ID、calibrator ID、dataset hash、scope、as-of、expires-at；
- promotion 生成一个 content-addressed artifact，报告只引用该 artifact；
- 不同 underlying、结构族、方向或 DTE band 不得借用未覆盖范围的胜率。

具体模型和校准阈值必须在首次查看最终胜率 holdout 之前写入冻结 successor protocol；不得在
看到结果后为通过而调阈值。

### 12.5 用户展示

只有 `CALIBRATED` 显示：

```text
预计胜率：64%–70%
可信度：中等
适用：BTC · Bull Put Spread · 7–35 DTE · hold to expiry
```

区间只是展示格式示例，不是当前结果。首页不显示 Brier、reliability curve、fold 和 IC；这些
进入“查看依据”。

### 12.6 Promotion、过期与降级

预测能力不是永久资产。至少发生以下任一情况时，状态必须从 `CALIBRATED` 退回
`RETIRED` 或 `UNAVAILABLE`：

- promotion artifact 超过 90 天未续证；
- surface、residual、filters、结构选腿、fill、fee 或 settlement 定义变化；
- 输入 schema 或单位语义变化；
- 连续数据中断超过冻结门槛；
- 连续 3 个新 OOS cohorts 出现方向反转或相对基准预测质量失效；
- 当前市场超出已登记 scope；
- artifact、模型或数据 lineage 无法验证。

降级后旧胜率必须立即从普通用户页面消失，不能以“低置信度”继续展示。

### 12.7 v0.4 Definition of Done

- 排名 claim、策略 PnL claim 和预测胜率 claim 有三个独立 artifact / status；
- `status != CALIBRATED` 时 schema、selector 和 UI 三层均禁止输出胜率数字；
- promoted 模型可从单一 artifact 追溯训练、校准、scope 和 OOS 证据；
- 过期、输入漂移、scope 越界和 OOS 反证会自动降级；
- 降级后缓存、public artifact 和 Chrome 侧栏都不会保留旧概率；
- no-trade、历史基准和当前预测在同一张卡里含义清晰、不互相替代；
- v0.2 / v0.3 合同保持兼容，相关完整测试通过。

---

## 13. `strategy_brief.v1` 合同

### 13.1 顶层字段

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `schema_version` | 是 | 固定为 `strategy_brief.v1` |
| `brief_id` | 是 | 内容寻址或稳定不可变 ID |
| `analysis_run_id` | 是 | 来源 AnalysisRecord |
| `generated_at` | 是 | 简报生成时间 |
| `research_only` | 是 | 固定 `true` |
| `execution_allowed` | 是 | 固定 `false` |
| `market` | 是 | §7 市场状态 |
| `action` | 是 | `STRATEGIES_AVAILABLE / WATCH / NO_TRADE` |
| `strategies` | 是 | 0–3 张策略卡 |
| `no_trade` | 是 | 无策略或全局阻断解释 |
| `evidence_summary` | 是 | 折叠依据入口和状态 |

### 13.2 策略卡字段

```text
strategy
  recommendation_id
  rank
  recommendation_status
  structure_type
  thesis_zh
  as_of
  valid_until
  legs[]
    instrument_name
    side
    quantity
    observed_at
    bid
    ask
    premium_unit
  entry
    price_basis
    minimum_net_credit
    currency
    fees_included
    slippage_included
  risk
    max_loss_per_unit
    currency
    breakevens[]
    path_risk_status
    cvar_95
  economics
    relative_value_status
    absolute_ev_status
    ev_after_cost
    net_r
  history
    status
    win_rate
    mean_net_r
    independent_cohorts
    observation_count
    exit_basis
    artifact_id
  forecast
    status
    win_rate_low
    win_rate_high
    confidence
    scope
    artifact_id
  kill_conditions[]
  primary_reason_codes[]
```

### 13.3 Null 与缺失规则

- `history.status != VALIDATED` 时，普通用户 projection 的 `win_rate` 和 `mean_net_r`
  必须为 `null`；
- `forecast.status != CALIBRATED` 时，`win_rate_low` 和 `win_rate_high` 必须为 `null`；
- `null` 必须伴随 status / reason code，不能由 UI 补 0、`--` 后再渲染为可用；
- 所有金额同时带 currency / premium unit；
- 所有时间带明确 UTC offset；
- 所有 artifact IDs 必须可从内部版追溯；public projection 可以隐藏私有路径，但不能伪造 ID。

### 13.4 合同不变量

- `strategies.length <= 3`；
- `execution_allowed == false`；
- `RECOMMENDED` 不能包含 unbounded-loss 结构；
- `RECOMMENDED` 必须有正的成本后 EV、可用最大亏损和未过期 quotes；
- `RECOMMENDED` 必须有 `history.status == VALIDATED` 或
  `forecast.status == CALIBRATED`；
- `action == NO_TRADE` 时 `strategies` 为空；
- `strategies` 至少含一张 `RECOMMENDED` 时 `action == STRATEGIES_AVAILABLE`；
- `strategies` 非空且全部为 `WATCH` 时 `action == WATCH`；
- `strategies` 数组不包含 `NO_TRADE` 占位卡；
- `forecast.status != CALIBRATED` 时所有预测概率为 null；
- `history.status != VALIDATED` 时首页历史绩效为 null；
- 相同 AnalysisRecord、policy 和 clock 产生相同 canonical payload hash。

---

## 14. Reason codes 与用户文案

内部保留完整 reason tape，首页只将最重要的 1–2 个原因翻译为普通语言。

| 内部原因 | 用户文案 |
| --- | --- |
| `NO_CAPTURABLE_EDGE_AT_TOUCH` | 当前可成交价格下没有足够收益空间 |
| `OTHER_DIRECTION_IS_POSITIVE` | 当前数据更支持反方向，不建议该卖方结构 |
| `NEGATIVE_EV_AFTER_COST` | 扣除成本后期望收益为负 |
| `UNBOUNDED_LOSS_STRUCTURE` | 亏损上限不明确，本版本不推荐 |
| `MISSING_VALIDATED_PATH_RISK` | 风险历史证据不足，暂不推荐 |
| `STALE_MARKET_DATA` | 行情已过期，等待刷新 |
| `LEGS_NOT_SYNCHRONIZED` | 多腿报价不同步，无法确认组合价格 |
| `HISTORICAL_EVIDENCE_INSUFFICIENT` | 历史样本不足，仅供观察 |
| `FORECAST_NOT_CALIBRATED` | 预测胜率尚未完成校准 |
| `PROMOTION_EXPIRED` | 预测证据已过期，等待重新验证 |

用户文案不能淡化失败语义。例如 `FAILED` 不能翻译为“低置信度机会”。

---

## 15. 关键用户流程

### Flow A · 有两张观察卡

1. 用户打开首页；
2. 看到一句话市场状态和“有 2 个策略值得观察”；
3. 查看每张卡的合约腿、最低净权利金和最大亏损；
4. 历史显示“样本不足”，预测显示“暂不可用”；
5. 用户可复制组合或展开依据；
6. 产品不替用户提交订单或决定数量。

### Flow B · 有一张已验证推荐卡

1. 所有执行、经济性和风险门禁通过；
2. aligned historical replay 已 `VALIDATED`，或 forecast 已 `CALIBRATED`；
3. 首页显示一张 `RECOMMENDED` 卡；
4. 用户看到历史胜率或预测区间、最大亏损和取消条件；
5. 到达 `valid_until` 后卡片自动失效并从推荐区移除。

### Flow C · 没有机会

1. 所有候选被负 EV、成本、风险、数据或证据门禁拒绝；
2. 首页显示 `今日暂无可靠策略`；
3. 给出最多两个主因和下次更新时间；
4. 不显示“最不差的三个候选”。

### Flow D · 模型被降级

1. 已晋级模型过期、输入变化或 OOS 反证；
2. forecast 立即改为 `RETIRED`；
3. 旧胜率从所有用户表面消失；
4. 若历史验证仍有效，卡片可按历史证据重新裁决；
5. 否则从 `RECOMMENDED` 降为 `WATCH` 或全局 `NO_TRADE`。

---

## 16. 验收场景

### 16.1 市场与卡片

1. **Given** 市场为 `RANGE + RICH`，存在 eligible condor，**When** 构建简报，
   **Then** headline 为震荡 / 波动率偏贵，卡片包含四条精确腿。
2. **Given** 市场为 `UNCLEAR`，**When** 构建简报，**Then** action 为 `NO_TRADE`，
   strategies 为空。
3. **Given** 4 个 eligible 结构，**When** 排序，**Then** 最多输出 3 张，且默认每个策略族
   最多一张。
4. **Given** 同一 snapshot、policy 和 clock，**When** 重建两次，**Then** payload hash 相同。

### 16.2 金融真值

5. **Given** `ev_after_cost < 0`，**When** 构建简报，**Then** 候选不得 `RECOMMENDED`。
6. **Given** robustness 为 `other_direction_is_positive`，**Then** 候选不得进入 Top 3。
7. **Given** naked short，**Then** 候选被硬拒绝。
8. **Given** short leg 只能按 bid、long leg 只能按 ask 成交，**Then** entry 使用二者构造，
   不得使用 mid / mark。
9. **Given** premium unit 与 payoff currency 不一致，**Then** fail closed。
10. **Given** 任一腿 stale 或两腿时间差超过 2 秒，**Then** 卡片不再有效。

### 16.3 历史表现

11. **Given** 只有重叠 observations 而独立 cohorts 不足，**Then** history 为
    `INSUFFICIENT`，无胜率数字。
12. **Given** 开发样本表现良好但 final holdout 不存在，**Then** history 为
    `EXPLORATORY`，首页无胜率数字。
13. **Given** exact-strategy holdout 所有门禁通过，**Then** history 可为 `VALIDATED`，
    并展示胜率和平均净 `R`。
14. **Given** 使用不同 exit rule 的历史结果，**Then** 不得挂到当前卡片。

### 16.4 预测胜率

15. **Given** 只有正 IC，**Then** forecast 至多为 `SCREENING_ONLY`，不得显示胜率。
16. **Given** sample fixture 标记 promotion eligible，但 live artifact 未晋级，**Then** live 卡片不得
    读取 sample 的概率。
17. **Given** calibrated artifact 通过且 scope 匹配，**Then** 展示概率区间，不展示伪精确单点。
18. **Given** artifact 过期或输入 hash 改变，**Then** forecast 降级，旧概率立即消失。

### 16.5 产品边界

19. 所有 payload 的 `execution_allowed` 为 `false`。
20. 复制组合不触发网络交易请求。
21. 未提供账户 NAV 时不推荐数量，只展示一单位组合。
22. public / demo / fallback 数据必须显式标识，不能被读取成 live 推荐。

---

## 17. 实施工作流与依赖

### WS-0 · 基线与合同冻结

- 核对真实 `v0.1.0` 发布树、当前远端和本地用户修改；
- 冻结 `strategy_brief.v1`、状态机和 reason-code 映射；
- 为现有 `research_report.v1` 保留兼容 projector；
- 建立 contract tests 和 golden fixtures。

### WS-1 · Market Headline

- 把现有 regime、VRP、surface、liquidity 和 trust 结果投影为 §7 的极简状态；
- 同一来源生成 headline、action 和 TTL；
- 加入 `UNCLEAR / UNKNOWN / NO_TRADE` 路径。

### WS-2 · Strategy Brief v0.2

- 统一三种 defined-risk strategy grammar；
- 生成 exact legs、executable credit、max loss、breakeven 和 kill conditions；
- 执行 hard gates、Top 3 选择和 copy recipe；
- 完成 internal / public / sidepanel 的一屏式 UI。

### WS-3 · Aligned Historical Replay v0.3

- 为每种结构冻结可比较协议；
- live / replay 共用结构、payoff、fees、settlement 和 units；
- 完成 cohort ledger、purge / embargo、comparator、bootstrap、cost stress；
- 只从 immutable validated artifact 填充 history。

### WS-4 · Calibrated Forecast v0.4

- 冻结 exact-strategy probability target；
- 完成 walk-forward forecast、calibration、scope 和 baseline；
- 建立 promotion artifact、90-day expiry、input-drift 与 OOS demotion；
- 只从 calibrated artifact 填充 forecast。

### WS-5 · 端到端验证与发布

- Python lint、compile、tests、API smoke；
- Web lint、typecheck、tests、internal / public / extension build；
- contract、financial invariants、responsive 和 accessibility 验收；
- demo、replay、live、public 四种表面语义一致性；
- 发布说明明确当前哪些字段仍为 insufficient / unavailable。

依赖顺序：

```text
WS-0 → WS-1 → WS-2 → v0.2
                 ↓
                WS-3 → v0.3
                         ↓
                        WS-4 → v0.4
WS-5 贯穿每个版本并在各版本发布前收口
```

---

## 18. 版本发布门槛

### v0.2 Release Gate

- 一屏简报和 `strategy_brief.v1` 完成；
- Top 3 hard gates 和 no-trade 路径通过；
- exact legs / entry / max loss / TTL 完整；
- 历史和预测不可用时没有伪数字；
- 所有执行授权仍关闭；
- 相关完整测试通过。

### v0.3 Release Gate

- 至少一个结构有真实 `VALIDATED` artifact，或产品明确以“历史证据仍在积累”发布；
- 所有显示的历史结果与卡片四同一：结构、方向、DTE、exit / fill / fee；
- 独立 holdout、comparator、成本压力和风险门禁可审计；
- 未验证结构不借用其他结构的胜率。

### v0.4 Release Gate

- 至少一个 exact-strategy forecast 产生有效 `CALIBRATED` artifact，或保持不显示预测胜率；
- 排名 promotion 不能替代胜率 calibration；
- promotion、expiry、scope、drift 和 demotion 全链验证；
- 旧概率不会在缓存、public 或 extension 表面残留；
- 没有证据时发布“暂不可用”被视为正确结果，不构成发布失败。

外部证据时间不服从开发排期。截至 2026-08-30，排名 preflight 只有 4/8 个已结算 cohort，
最早预计 2026-09-25 才可能具备首轮 ranking measurement 条件；策略级历史与预测还需要各自
冻结后的未来 holdout。不得为了版本日期提前打开或重复使用 holdout。

---

## 19. 风险与缓解

| 风险 | 后果 | 缓解 |
| --- | --- | --- |
| 精确合约腿让研究卡看起来像交易指令 | 用户忽略证据成熟度 | 明确状态、最大亏损、TTL；复制但不提交；执行授权固定关闭 |
| 胜率成为唯一决策依据 | 高胜率低赔率策略被误选 | 同屏保留平均净 R 和最大亏损；推荐仍需 EV / risk gate |
| 排名策略与回测策略不一致 | 历史数字不可用于当前卡片 | 强制四同一与 artifact scope；不一致即 suppress |
| exploratory winner 被事后挑选 | 过拟合与伪预测 | 预登记、多重比较控制、sealed holdout |
| live 与 sample artifact 混用 | demo 结果冒充当前能力 | provenance、artifact class 和 projection 隔离测试 |
| 多腿纸面价格不可成交 | 推荐虚假正 EV | bid/ask、同步、深度、slippage、legging gate |
| 静态日报被当成实时建议 | 用户使用过期卡片 | public `stale_after`、隐藏过期策略、明显 as-of |
| 用户自行放大一单位组合 | 风险超过账户承受能力 | 不提供账户 sizing；每单位最大亏损显著展示 |
| 模型曾经有效后永久保留 | 漂移导致旧胜率误导 | 90 天过期、连续 OOS 检查、输入变化机械降级 |

---

## 20. 最终验收定义

本方案完成时，LensOS Option 应满足：

1. 用户打开首页，先读到市场结论，不先读到工程状态；
2. 用户看到最多三张、结构不同、有限风险的策略卡；
3. 每张卡明确写出买卖合约、数量、最低净权利金、最大亏损和有效期；
4. 系统不会把相对异常、负 EV 或反方向机会包装成卖方推荐；
5. 历史胜率只来自与当前卡片完全对齐并通过 holdout 的策略；
6. 预测胜率只在 exact-strategy probability model 完成校准后显示；
7. 证据不足时页面清楚写“样本不足 / 暂不可用”；
8. 没有机会时页面清楚写“今日暂无可靠策略”；
9. 所有复杂证据仍可展开审计，但不会阻碍用户理解；
10. 自动交易、个性化仓位和执行授权始终不在本 spec 范围内。

最终产品承诺不是“每天给三个答案”，而是：

> **有可靠策略时，告诉用户市场、策略、合约、表现和风险；没有可靠策略时，明确告诉用户
> 今天不要做。**

---

## 21. 新会话 Goal 提示词

将下面整段复制到新的 Codex 会话：

```text
你正在 LensOS Option 仓库中工作。

Goal：按照
docs/product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md
完整设计、实现并验证 LensOS Option v0.2–v0.4 的一体化“极简策略简报”。不要停留在建议、
原型或局部改动；在当前可获得证据允许的范围内持续推进到可交付状态。

产品目标：用户在一屏内、30 秒内看懂当前 BTC 期权市场状态、今天是否有可靠策略、最多三种
策略、每种策略的精确买卖合约腿、最低可接受净权利金、每一单位最大亏损、历史表现是否可信、
预测胜率是否已校准、有效期和取消条件。复杂模型和证据默认折叠，但所有结论必须可审计。

开始前必须：
1. 完整阅读仓库 AGENTS.md、上述主 spec、docs/automation/strategy-eval-spec.md、
   docs/model-promotion.md，以及与 research_report、AnalysisRun、surface、EV、path risk、
   strategy research、calibration、public、sidepanel 相关的现有实现和测试。
2. 先检查 git status、远端和真实 v0.1.0 发布基线。当前本地 main 曾被确认落后且不是实际发布树；
   不得覆盖用户修改或未跟踪文件，不得用破坏性 git 操作解决基线问题。
3. 建立可执行计划，把相互独立的代码审计、schema/UI、历史回放、预测治理和验证任务交给
   Codex 原生子代理并行处理；主代理负责集成、金融语义和最终验证。

实施顺序固定为：先完成 canonical schema、validators、状态映射和 hard gates；再完成与每个
策略族对齐的 historical replay 与 artifact；随后完成 forecast calibration / lifecycle；最后将
已验证语义统一接入首页、public 和 sidepanel 并做端到端收口。UI 可以先用明确的 unavailable
fixture 验证布局，但不得先于金融语义定稿而固化另一套状态逻辑。

必须交付：

A. v0.2 市场与策略简报
- 建立 canonical strategy_brief.v1 schema、Python/TypeScript/runtime validators、projector、
  API 或静态 artifact 投影和兼容边界。
- 首页、公开版和 Chrome 侧栏统一改为：市场一句话 + 今日行动 + 0–3 张策略卡 + 折叠依据。
- 初始策略仅包含 defined-risk 的 Bull Put Credit Spread、Bear Call Credit Spread、Iron Condor。
- 每张卡包含精确 BUY/SELL legs、quantity、executable entry basis、最低净权利金、premium unit、
  max loss、breakeven、expiry、as-of、valid-until 和 kill conditions。
- 排名必须发生在 hard gates 后。负成本后 EV、反方向更优、touch 无 edge、无上限亏损、未知
  max loss/margin/path risk、stale quote、不同步多腿、单位不一致的候选不得成为推荐。
- 没有候选时明确显示“今日暂无可靠策略”，不得展示“最不差”的候选。
- 提供只复制、不提交订单的一单位组合文本；execution_allowed 永远为 false。

B. v0.3 可信历史表现
- 为每个策略族建立和当前卡片完全对齐的冻结回放协议：同结构、同方向、同 DTE、同选腿、
  同 bid/ask fill、同 fee/slippage、同 hold-to-expiry/settlement 规则。
- live 与 replay 共用结构、payoff、费用、单位和 settlement 语义；不允许用 naked-call baseline
  证明 spread/condor。
- 实现独立 expiry-cohort ledger、purge、35 天 embargo、walk-forward、no-trade 和同结构 comparator、
  cohort bootstrap、1.5x cost stress、regime/risk gates、immutable artifact 与 result hash。
- history 状态只允许 INSUFFICIENT / EXPLORATORY / VALIDATED / FAILED。
- 只有 VALIDATED 才在普通用户策略卡显示历史胜率和平均净 R；其余状态不显示 plausible percentage。
- 不得读取或重用已经看过的样本冒充 future holdout。
- 当前 frozen strategy-eval 的可晋级边界只覆盖 CALL_CREDIT_SPREAD / Bear Call Credit Spread；
  Bull Put Spread 和 Iron Condor 必须分别拥有 aligned replay、冻结协议和未来 holdout，才能进入
  VALIDATED，不能借用 Call Credit Spread 的历史结果。

C. v0.4 校准预测胜率
- 排名 claim、策略 PnL claim、exact-strategy win-probability claim 必须分开建模和晋级。
- 预测目标固定为当前卡片精确规则下“成本后净 PnL > 0”的概率；不得用 Delta、P(OTM)、
  risk-neutral P(ITM)、排名 IC 或探索性 hit rate冒充。
- 实现 UNAVAILABLE / SCREENING_ONLY / CALIBRATED / RETIRED 状态、scope、calibration artifact、
  confidence interval、90 天 expiry、输入漂移、scope 越界和新 OOS 反证降级。
- 只有 CALIBRATED 才能输出预测胜率区间；其他状态 schema 与 UI 都必须输出 null/暂不可用。
- 不得因缺少尚未到期的真实 cohort 而制造数据、伪造 promotion 或提前打开 holdout。外部证据不足时，
  正确完成状态机、artifact contract、自动降级和 honest unavailable UI，即为当前可交付结果。

全程保持的硬边界：
- RESEARCH_ONLY / NO_AUTO_EXECUTION / NO_PERSONALIZED_SIZING；
- 不新增自动或半自动下单路径，不推荐账户级手数，不引入裸卖结构；
- relative value 与 absolute EV 永不合并成总分；
- executable entry 使用 short bid / long ask 及冻结成本模型，mid/mark 只可诊断；
- inverse/linear、premium/payoff/settlement currency 必须 unit-safe；
- 所有 unknown、stale、missing、inconclusive、failed 都 fail closed；
- 不新增依赖，除非任务确实无法以现有栈完成且先有明确证据和最小化理由；
- 保留现有兼容契约和用户修改，保持 diff 小、可审查、可回退。

必须覆盖的测试：
- contract/schema/golden fixture；
- negative EV、other_direction_is_positive、no edge at touch、unbounded loss；
- stale/missing/crossed quote、腿时间差 >2 秒、unit mismatch；
- 0 候选、1–3 候选、同策略族去重、确定性排序和 deterministic hash；
- history insufficient/exploratory/validated/failed；
- forecast unavailable/screening/calibrated/retired；
- promotion expiry、input drift、scope mismatch、OOS demotion；
- public/demo/fallback 不得冒充 live；
- 320–1440px 关键响应式、键盘和可访问性；
- execution_allowed 始终 false，复制组合不产生交易请求。

验证要求：
- 运行与改动相关的 Python Ruff、compile、pytest、API smoke；
- 运行 Web lint、typecheck、Vitest、internal/public/extension builds；
- 读取所有输出并修复失败，不得只报告“理论上通过”；
- 如完整测试受当前基线已有失败影响，先隔离并证明与本改动的关系，再继续修复范围内问题；
- 最终报告列出 changed files、实现的 v0.2/v0.3/v0.4 能力、测试证据、仍受未来真实 cohort
  阻塞的证据状态和剩余风险。

完成标准：不是每天一定产生推荐，而是有可靠证据时给出简单、精确、有限风险的策略卡；
没有可靠证据时简单、明确地告诉用户今天不交易。自动推进，不要在明显的下一步前询问是否继续。
```
