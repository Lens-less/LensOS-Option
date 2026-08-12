# Deribit 期权定价错配与策略推荐平台 PRD / Engineering Spec

> 历史研究输入，已被 `docs/product/2026-08-02-public-product-spec.md` 与
> `docs/product/2026-08-12-continuity-and-consistency-spec.md` 取代；本文不定义
> 当前产品 North Star、发布验收或部署授权。

版本：1.0
日期：2026-07-10
状态：Ready for decomposition
Triage label：ready-for-agent
GitHub issue：https://github.com/Lens-less/LensOS-Option/issues/1
Issue type：Parent PRD / Epic；ready-for-agent 表示下一代理可直接执行 issue decomposition，不表示单个代理应一次实现全部 Gate
产品模式：RESEARCH_ONLY；paper/manual/live 保持 NO-GO
产品定位：从可信市场证据到可审计策略推荐，不是交易所，不复制 Deribit，不在本 PRD 中启用自动实盘

文档关系：

- 本 PRD 在撰写时取代“加密货币期权卖 Call 收租系统 PRD”，曾作为当时的产品方向。
- 原 short-call 能力保留为风险溢价类策略的首个垂直切片和回归基线，不再定义整个平台边界。
- Data Trustworthiness PRD 及 DT-001..010 作为 Gate 0 的既有子项目继续执行，不重复创建同类工作。
- DQR-001..012 和 ISSUE-001..015 只代表 local/replay scaffold 已接受，不代表 production data、model、paper 或 trading evidence 已满足。
- Next Backlog 中尚未完成的分析、运维和交易门槛被吸收到本文阶段路线图；在后续 issue 拆解完成后，本文成为产品规划主源。

## Problem Statement

目标用户需要的不是另一个 Deribit，也不是一张展示 mark IV 的 Dashboard，而是一个能够回答以下问题的期权分析与交易决策平台：

> 给定 Deribit 当前市场状态和用户组合，是否存在成本后、保证金后、模型不确定性后仍成立的期权异常；如果存在，应使用什么多腿结构表达；如果不存在或证据不足，系统应明确拒绝推荐并说明原因。

当前项目已经具备较强的研究模式边界、统一报告、fixture/replay、CLI/API 和浏览器控制台，但它主要解决“short-call research report 是否继续研究”，还没有解决目标产品的核心决策问题：

1. 市场数据不是持续、完整、可重放的市场状态。当前主要依赖一轮 REST snapshot，缺少 WebSocket sequence、gap detection、resync、统一限频、不可变原始事件和稳定历史数据资产。
2. 产品经济语义没有在全链路中强制。inverse 与 linear 的 premium、settlement、fee、contract size 和 USD shadow 仍可能在 quote、surface、EV、backtest 与 ledger 间丢失或被错误推断。
3. 定价内核尚未形成可信基准。现有曲面主要是 call-only 的简化线性拟合，缺少 puts、forward、discount/funding、无套利曲面、公允区间、模型不确定性和独立数值 oracle。
4. “错配”没有分类。模型无关套利、相对价值偏离和风险溢价预测被混在同一语言中，用户无法判断机会究竟是可执行套利、模型观点还是预测性风险承担。
5. 策略表达被 short call 和 call spread 固定逻辑限制。没有统一 StrategyLeg grammar、同步多腿报价、legging risk、深度、费用、保证金和组合增量风险比较。
6. 回测和校准仍包含 tracer/fixture 语义。部分接口会忽略请求体并返回固定 comparison；部分绩效数字不是从真实 trade ledger 推导。
7. 推荐缺少不可变证据账本。系统无法通过 recommendation ID 重建当时的数据、模型、参数、风险裁决、后续结果和撤销原因。
8. 页面作为风控状态页视觉成熟，但不是完整分析工作台。缺少 Option Chain、Surface Lab、Opportunity Board、Strategy Lab、组合风险、模型注册表和推荐历史等关键旅程。
9. 部分 fallback/fixture 数字看起来像真实、已校准结果。页面越精致，错误的可信感风险越高。
10. 当前任意字典合同和单文件前端使新增产品、策略、模型和数据源需要跨多个模块修改，扩展 locality 不足。

当前审计还复现了必须阻断平台升级的金融真值缺陷：

- 账户缺少观测时间且未运行 portfolio simulation 时，仍可能得到 GREEN / ALLOW_NEW。
- inverse 历史 payoff 即使错误到 5 BTC，仍可能被判定 ELIGIBLE。
- 9 个唯一时间点乘两个合约行会被当成 18 个时间点并生成虚假 7-day paths。
- 全部 crossed-market entry quotes 仍可能得到 ELIGIBLE / backtest_allowed=true，只是交易数为零。
- DVOL candle resolution 与 freshness policy 不一致，使正常数据在大部分时间天然 stale。
- 按 instrument name 排序后截取前 N 个合约造成单到期日、非代表性样本。
- 无效 backtest 请求仍可能返回 completed 和固定绩效。
- API 失败时页面仍可能显示“已校准”和看似真实的 Calmar 等 fixture 指标。

这些问题说明：当前测试绿色证明了 scaffold 和报告合同稳定，但还不能证明金融结论真实。若继续在当前基础上增加指标、策略或交易入口，会放大假阳性、错误单位和不可复现推荐的风险。

## Solution

建设一个 evidence-first 的 Deribit Options Intelligence Platform。平台从连续市场证据出发，将产品经济语义、定价、异常分类、策略表达、组合风险、回放验证和推荐治理串成一条可重放证据链。

### Historical Product North Star (已取代)

平台对每个分析时点输出零个或多个 RecommendationRecord。只有当保守净边际在 bid/ask、depth、fee、slippage、legging、hedge、margin reserve 和 model uncertainty 后仍为正，并且数据、模型和组合风险门槛全部通过，候选才可以从 research anomaly 晋级为 watch candidate。Trade proposal 仍受独立 paper/testnet/manual release gate 阻断。

当条件不满足时，“零推荐”是正常且有价值的产品结果。平台必须区分：

- 没有发现异常；
- 发现异常但不可成交；
- 数据不可信，无法判断；
- 模型未晋级，不能形成预测性推荐；
- 组合风险 veto；
- 推荐已过 TTL 或 kill condition 已触发。

### Edge Taxonomy

| Edge class | 定义 | 必需证据 | 允许语言 |
| --- | --- | --- | --- |
| E1 — Model-free arbitrage anomaly | Put-call parity、box、vertical monotonicity、butterfly convexity，以及严格前提下的 calendar violation | 同步多腿可成交报价、费用、深度、结算和下界收益 | 只有 edge lower bound 成本后为正时可称 arbitrage violation |
| E2 — Relative value | 相对无套利曲面的 strike/expiry residual、skew/term anomaly、cross-model disagreement | 可信曲面、公允区间、模型分歧和流动性 | relative value / model-dependent mispricing |
| E3 — Risk premium / forecast | IV-RV、VRP、regime、event、path/distribution 预测 | promoted OOS model、校准、可靠性和尾部风险证据 | forecast / risk-premium opportunity，不得称无风险套利 |
| E4 — Portfolio expression | 将 E1–E3 转换为适合当前组合的结构和对冲 | 增量保证金、Greeks、场景、CVaR、集中度、退出流动性 | 组合表达或风险优化，本身不是 edge |

### Product Defaults

1. MVP 首个验收标的是 BTC，支持 calls + puts；ETH 在 BTC golden path 通过后接入。
2. inverse BTC options 是首个 ProductEconomics golden path；USDC linear 作为第二条完整路径，不允许共用模糊金额字段。
3. 第一阶段先交付 E1，再交付 E2，E3 风险溢价和原 short-call 策略后置。
4. 产品刷新目标是约 30 秒级研究分析，不是 HFT 或 latency arbitrage。
5. 输出等级固定为 research anomaly、watch candidate、trade proposal。产品稳定态默认开放前两级；在 Gate 5 通过前仅开放 research anomaly。
6. 候选主排序使用保守成本后 edge 相对于 incremental margin/capital at risk；任何硬风险门优先于排序。
7. 初期为本地单用户、desktop-first；移动端只承担摘要、阻断原因和告警。
8. 每个 recommendation 都写入不可变 ledger；任何 UI 数字都必须能追溯到 snapshot、model 和 policy。
9. 当前系统继续保持 RESEARCH_ONLY / NO_TRADE / NO-GO，不允许 query parameter、fixture、单次 live smoke 或 UI 控件绕过。

### Success Outcomes

1. 用户在 30 秒内判断当前数据能否用于分析，并看到明确市场 as-of、source、age 和 trust verdict。
2. 用户在 2 分钟内解释 top candidate 的 edge class、公允区间、成本、保证金、组合影响和失效条件。
3. 所有经济字段都携带 product、unit、currency、kind、as-of 和 provenance；unknown 永远不被默认为可用。
4. 相同 raw event log、clock、config 和 model bundle 生成相同 snapshot hash、report hash、recommendation ledger 和结果。
5. apparent edge 被 spread、fee、slippage 或 margin reserve 覆盖后，系统输出零推荐。
6. fallback、fixture 和未晋级模型永远不会显示为当前市场、已校准或可交易结果。
7. live/replay 共享事件、时钟、定价和 detector 语义，回测不再是另一套系统。
8. paper/manual 只有在预先声明的 release criteria 和 30–60 天对账证据满足后，才可由独立授权流程讨论开启。

## User Stories

### Data trust and product economics

1. 作为期权研究员，我希望进入任何页面先看到 trust verdict、source、market as-of 和 data age，以便判断是否可以相信后续数字。
2. 作为期权研究员，我希望 trusted、degraded、untrusted 有稳定 reason codes，以便区分数据稀疏、网络故障、单位缺失和模型阻断。
3. 作为期权研究员，我希望“没有候选”和“没有可信数据”被明确区分，以便不会把数据故障误读成市场无机会。
4. 作为期权研究员，我希望每个金额都声明 settlement currency、premium unit 和 settlement/shadow kind，以便不会混淆 BTC 与 USDC。
5. 作为期权研究员，我希望 inverse PnL 以 coin 为真值、USD 仅为明确 shadow，以便研究结果符合真实结算语义。
6. 作为期权研究员，我希望 linear USDC 产品不经过 inverse 转换，以便不会重复乘 underlying 或套用错误 fee。
7. 作为风险负责人，我希望未知 settlement、contract size 或 premium unit 一律 NO_TRADE，以便错误默认值不能进入组合风险。
8. 作为风险负责人，我希望账户缺少 observed_at、过期或未完成 portfolio simulation 时一律 NO_TRADE，以便私有数据缺失不能出现 GREEN。
9. 作为模型验证人员，我希望历史 payoff tolerance 使用 settlement unit，以便币本位误差不会被美元 strike 尺度掩盖。
10. 作为数据工程人员，我希望 settlement 只来自 venue explicit field，以便 quote currency 不能被误当结算币种。
11. 作为审计人员，我希望每个 snapshot 和 report 都有 raw hash、source class 和生成配置，以便历史结论可以复现。
12. 作为产品负责人，我希望任何 fixture、fallback 或 synthetic input 都有显著水印，以便示例不会被误解为当前市场事实。

### Continuous market evidence

13. 作为期权研究员，我希望系统覆盖代表性的 expiry、type、moneyness 和 delta buckets，以便样本不被字典序截断偏置。
14. 作为期权研究员，我希望 Option Chain 同时显示 call 和 put 的 bid/ask、depth、IV、Greeks、OI 和 freshness，以便可以分析 parity 和相对价值。
15. 作为数据工程人员，我希望 REST bootstrap 与 WebSocket event stream 使用同一 canonical market state，以便启动和持续更新不会产生两套语义。
16. 作为数据工程人员，我希望检测 order-book sequence gap 并在 resync 前降为 untrusted，以便静默缺包不能形成错配。
17. 作为数据工程人员，我希望 reconnect 后恢复精确订阅集合，以便断线不会永久丢失某个 expiry 或 feed。
18. 作为数据工程人员，我希望重复和乱序事件幂等处理，以便重放不会重复改变盘口。
19. 作为数据工程人员，我希望 429、5xx、timeout 和 schema drift 都变成结构化 adapter events，以便运维可以区分重试和永久故障。
20. 作为运维人员，我希望 retry、backoff、jitter、Retry-After 和 circuit breaker 有界，以便单个 provider 故障不会耗尽线程。
21. 作为运维人员，我希望 DVOL resolution 与 freshness SLA 相容，以便正常 candle 不会在大部分时间天然 stale。
22. 作为研究员，我希望 raw market events 不可变保存并可按 snapshot ID 重放，以便模型研究不依赖事后重建。
23. 作为研究员，我希望 underlying bars、option quotes、instrument metadata 和 settlement events 分离存储，以便路径构建不会把合约行数当时间点。
24. 作为审计人员，我希望任何 sequence discontinuity、resync 和 provider failover 都记录在 snapshot manifest，以便数据完整性可证明。
25. 作为平台工程师，我希望 live canary 是显式 opt-in 且不阻塞离线 CI，以便测试稳定性不依赖公网。

### Pricing and model truth

26. 作为期权研究员，我希望平台使用 forward、funding/carry 和 discount inputs，而不是总以 spot 和零利率定价，以便 fair value 符合 crypto 市场。
27. 作为期权研究员，我希望同一 PricingKernel 支持 call、put、inverse 和 linear，以便不同产品共享可验证的定价合同。
28. 作为期权研究员，我希望可以查看 IV、model Greeks、exchange Greeks 和差异，以便识别模型风险和 venue 口径差异。
29. 作为期权研究员，我希望 Surface Lab 显示 strike、expiry、skew、term structure、fit residual 和覆盖范围，以便理解错配来自哪里。
30. 作为期权研究员，我希望曲面提供 fair-value interval 而不是单一伪精确数字，以便模型不确定性进入推荐。
31. 作为模型开发者，我希望曲面执行 vertical、butterfly、calendar 和 put-call parity 检查，以便不合法拟合不能产生候选。
32. 作为模型开发者，我希望 SVI/SABR 或受约束插值可以被替换和对比，以便平台不会绑定单一模型。
33. 作为模型验证人员，我希望 checked-in oracle corpus 标注 QuantLib/py_vollib 版本，以便价格、IV 和 Greeks 有独立数值基准。
34. 作为模型验证人员，我希望极端 strike、短到期、低/高 vol、非零 carry 和边界输入进入回归集，以便正常样例不会掩盖尾部错误。
35. 作为风险负责人，我希望 oracle divergence、未知 forward 或 surface arbitrage 自动阻断 E2/E3，以便低质量模型不能形成推荐。
36. 作为模型开发者，我希望每次模型输出包含 model version、input hash、parameter bounds 和 fit diagnostics，以便晋级和回滚可审计。
37. 作为模型治理人员，我希望 research fixture model 永远不能 promoted，以便 tracer 指标不会变成生产分数。
38. 作为模型治理人员，我希望任何 promotion 包含 dataset hash、holdout、purge/embargo、OOS metrics、reviewer 和 rollback target，以便晋级不是一个布尔开关。

### Opportunity detection and strategy expression

39. 作为期权研究员，我希望 detector 明确输出 E1、E2 或 E3，以便不会把预测观点包装成套利。
40. 作为期权研究员，我希望 E1 扫描 put-call parity、box、vertical、butterfly 和满足前提的 calendar violation，以便先覆盖最可解释的异常。
41. 作为期权研究员，我希望 E2 显示 surface residual、cross-model disagreement 和 fair band，以便理解相对价值依据。
42. 作为期权研究员，我希望 E3 只有 promoted OOS model 才能产生 watch candidate，以便未经校准的 short-call/VRP 只停留在研究。
43. 作为期权研究员，我希望每个 opportunity 包含 stable ID、snapshot ID、detector ID、model ID、expires_at 和 invalidation reasons，以便机会生命周期可跟踪。
44. 作为期权研究员，我希望 detector 使用同步且 freshness 合格的多腿报价，以便 stale leg 不会制造纸面套利。
45. 作为期权研究员，我希望 net executable edge 扣除 bid/ask、depth、fee、slippage、legging、hedge 和 margin reserve，以便排序基于可实现经济性。
46. 作为期权研究员，我希望成本覆盖 apparent edge 后候选自动消失，以便宽 spread 不被当作利润。
47. 作为策略研究员，我希望策略由统一 StrategyLeg grammar 表达，以便新增结构不需要跨多个模块硬编码。
48. 作为策略研究员，我希望支持 vertical、calendar、diagonal、butterfly、condor、box/parity、straddle、strangle、risk reversal 和 hedged-vol 结构，以便同一 edge 可以比较多种表达。
49. 作为策略研究员，我希望 defined-risk 结构优先于 naked short，以便平台默认选择更可控表达。
50. 作为策略研究员，我希望 payoff grid 等于各腿 payoff 之和，以便复杂结构可以用金融不变量验证。
51. 作为风险负责人，我希望 naked short 明确标记 unbounded loss，而不是展示伪 max loss，以便风险沟通真实。
52. 作为期权研究员，我希望 Strategy Lab 同屏比较 breakeven、payoff、Greeks、margin、CVaR、PoP、edge 和 exit liquidity，以便选择最合适结构。
53. 作为期权研究员，我希望推荐显示 why、why now 和 what invalidates，以便结果可以被人工挑战。
54. 作为风险负责人，我希望 kill condition 始终覆盖 score/rank，以便高分不能绕过数据、流动性、事件或组合风险。

### Portfolio risk, replay and calibration

55. 作为风险负责人，我希望查看新增策略对 portfolio Greeks、expiry/strike concentration 和 scenario PnL 的增量影响，以便不孤立评估单笔交易。
56. 作为风险负责人，我希望组合风险使用真实 signed legs 聚合，以便默认零 delta 或虚构 notional 不会产生假安全。
57. 作为风险负责人，我希望读取 Deribit positions/account 和 simulate_portfolio 只读结果，以便交易所保证金是 source of truth。
58. 作为风险负责人，我希望本地风险模型与 Deribit simulation 输出差异报告，以便本地 tail overlay 不伪装成 PM 复制品。
59. 作为风险负责人，我希望任一风险输入恶化时 final action 不得变宽松，以便 risk arbiter 保持单调性。
60. 作为风险负责人，我希望 risk veto 始终覆盖 opportunity rank，以便盈利候选不能越过组合硬限制。
61. 作为研究员，我希望 live 和 replay 使用同一 MarketEvent、clock、PricingKernel 和 detector，以便 backtest 不是另一套代码。
62. 作为研究员，我希望相同 event log 生成完全相同的 trade ledger 和 result hash，以便实验可复现。
63. 作为研究员，我希望未来数据 mutation 不改变 mutation 之前的 signal/order，以便检测 lookahead 和 leakage。
64. 作为研究员，我希望 fill model 覆盖 bid/ask、partial fill、legging、cancel/replace、latency、fee、funding、hedge 和 settlement，以便绩效不是 mid/mark 幻觉。
65. 作为研究员，我希望 crossed、empty、stale 或 unknown-unit 输入直接 INELIGIBLE，以便回测资格来自证据而不是常量。
66. 作为研究员，我希望所有 Calmar、CVaR、MDD 和收益指标从 trade ledger 推导，以便固定 comparison 不会出现在可信表面。
67. 作为研究员，我希望样本不足时显示 insufficient_evidence 而不是绩效图，以便界面不会奖励小样本。
68. 作为模型开发者，我希望 walk-forward fold 包含 dataset hash、cutoff、purge、embargo 和 regime/liquidity split，以便 OOS 证据可审计。
69. 作为模型验证人员，我希望模型晋级同时考察稳定性、尾部风险、可靠性和模型漂移，而不是只看 PnL/Calmar，以便避免过拟合。
70. 作为审计人员，我希望推荐结束后记录实际可成交退出、费用、settlement 和 outcome，以便推荐质量形成闭环。

### Platform, workbench and operations

71. 作为用户，我希望 Market Overview 汇总 spot/index、DVOL、期限结构、skew、provider、freshness 和 trust，以便快速理解市场背景。
72. 作为用户，我希望 Option Chain 可以按 expiry、delta、moneyness、liquidity 和 edge class 筛选，以便定位分析范围。
73. 作为用户，我希望从 chain drill down 到 surface，再到 opportunity 和 strategy，以便分析不是割裂的长页面。
74. 作为用户，我希望 Opportunity Board 可排序展示 market、fair band、edge lower bound、confidence、TTL 和 blockers，以便快速比较候选。
75. 作为用户，我希望候选详情保留原始 legs、报价、模型输入、成本分解和证据链接，以便人工复核。
76. 作为用户，我希望 Recommendation History 可以按 ID 重放历史结论，以便回看系统为什么推荐、拒绝或撤销。
77. 作为用户，我希望 0 候选空状态显示具体原因和修复入口，以便知道应等待市场还是修复数据。
78. 作为用户，我希望离线和 fallback 状态使用全页水印并隐藏 plausible performance，以便不会误读示例。
79. 作为用户，我希望 report generated_at、market as-of、data age 和 source 分开显示，以便绿色更新时间不替代数据可信。
80. 作为用户，我希望键盘、focus、对比度和窄屏摘要符合可访问性要求，以便高频研究操作可靠。
81. 作为平台工程师，我希望分析通过 job API 执行并返回 immutable report ID，以便 GET 不会重新拉取 live 数据。
82. 作为平台工程师，我希望 backtest POST 校验请求、支持幂等、状态、结果和取消，以便接口语义真实。
83. 作为平台工程师，我希望有界队列在满载时明确返回 429/503，以便高并发不会无限创建线程。
84. 作为运维人员，我希望 /health 只表示 liveness、/ready 表示依赖和最近 trust state，以便监控不会把活着误当可用。
85. 作为运维人员，我希望日志和 metrics 带 correlation、snapshot、report、job 和 model IDs，以便一次分析可端到端追踪。
86. 作为运维人员，我希望 metrics 覆盖 event lag、gap、resync、reconnect、adapter errors、trust、report latency 和 queue，以便故障可观察。
87. 作为安全负责人，我希望默认只绑定 loopback，remote bind 前必须 auth、rate limit 和 TLS boundary，以便本地研究 API 不被误公开。
88. 作为安全负责人，我希望凭证、webhook secret、签名和私有 payload 不进入日志或仓库，以便私有数据边界清晰。
89. 作为产品负责人，我希望 paper、testnet、manual 和 live 是四个独立 release gate，以便一次验收不能解锁所有交易能力。
90. 作为产品负责人，我希望 live automation 必须另立 PRD、显式授权和独立安全评审，以便本 PRD 不通过范围蔓延开启实盘。

## Implementation Decisions

### 1. Program boundary and document authority

1. 本 PRD 在撰写时曾作为产品方向；现行 North Star 由顶部所列产品规格定义。
2. Data Trustworthiness PRD 的 DT-001..010 保留 issue 身份和依赖顺序，整体纳入 Gate 0，不重复创建 trust tickets。
3. DQR 和既有 ISSUE acceptance 作为 local/replay regression baseline。任何当前反例可以重新阻断对应生产能力，历史 done 不覆盖新证据。
4. Next Backlog 中 A05–A12、T01–T05、N01–N06 映射到本文后续 Gate；机会告警只有在 path evidence 和 model promotion 后才能开启。
5. 现有 institutional calm、evidence-first 视觉原则保留，但产品 IA 从单一状态页扩展为 Trust → Market → Opportunity → Strategy → Portfolio → Evidence。

### 2. Normative invariants

6. Missing、stale、unknown 或 contradictory evidence 一律 fail closed。
7. RESEARCH_ONLY / NO_TRADE / NO-GO 不得被 query parameter、UI、fixture、单次 live smoke 或本地布尔值绕过。
8. 所有经济金额都使用 typed money/economic value，至少包含 amount、currency、kind、product type 和 contract scale。裸 scalar 不能跨 module boundary。
9. settlement 只来自 venue explicit field；quote currency 不得推断 settlement。
10. 所有 recommendation 必须版本化、可重放、可撤销，并包含 snapshot/model/policy lineage、edge class、fair band、legs、costs、margin、portfolio impact、TTL、kill conditions 和 outcome state。
11. 所有绩效必须从 immutable ledger 推导；fixture/tracer 常量不得进入可信 API 或 UI。
12. “无推荐”是合法输出；系统不得用降级证据填补候选。

### 3. One highest analysis seam

13. 平台新增一个最高层 AnalysisRun seam，输入固定 clock、market snapshot/event range、可选 account snapshot、config 和 model bundle，输出 immutable AnalysisRun。
14. 现有 research report builder 在迁移期作为 AnalysisRun 的兼容 projection，而不是继续直接创建所有依赖。
15. CLI、API、Dashboard、export 和 agent interface 只消费同一个 report ID/snapshot ID，不各自重算质量、定价或风险。
16. 大多数验收测试通过 AnalysisRun 完成；只有产品单位、定价数值、adapter failure 和 state machine 等高风险基础行为保留较低层测试。

### 4. Deep modules and typed contracts

17. ProductEconomics 负责 instrument identity、base/quote/settlement、premium unit、contract size、inverse/linear 和 USD shadow 规则。
18. MarketEvidence 负责 REST bootstrap、WebSocket events、canonical market state、trust verdict、raw manifest 和 replay。
19. PricingKernel 负责 forward/discount、price、IV、Greeks、surface、no-arbitrage 和 fair-value interval。
20. OpportunityEngine 负责 E1–E3 detector、evidence gate、stable opportunity identity 和 expiration。
21. StrategyEngine 负责 StrategyLeg grammar、多腿 payoff、executable economics、strategy comparison 和 kill conditions。
22. PortfolioRiskEngine 负责 signed Greeks、incremental margin、scenario/CVaR、concentration、exit liquidity 和 risk veto。
23. ReplayEngine 负责统一 event source、clock、fill model、order lifecycle、hedge、funding、settlement 和 ledger。
24. ModelRegistry 负责 artifact hash、dataset lineage、OOS evidence、promotion、rollback 和 owner/reviewer。
25. RecommendationLedger 负责不可变 recommendation、状态转移、撤销、outcome reconciliation 和审计。
26. PlatformProjection 负责 API/CLI/Workbench/exports；不得包含第二套业务判断。
27. ExecutionGateway 保持隔离且不属于默认运行图。Paper/testnet/manual 通过独立 adapter 和 release gate 逐级接入；live adapter 不在本 PRD 范围。

### 5. Market evidence plane

28. REST 只用于 instrument bootstrap、initial snapshot、gap resync 和明确不适合 streaming 的参考数据；实时 ticker/book/index/DVOL 使用 WebSocket。
29. 每个 event 携带 provider sequence、venue timestamp、receive timestamp、instrument ID 和 raw provenance。
30. order-book gap、duplicate、out-of-order、reconnect 和 resubscribe 必须经过同一 state transition，并可由 replay fixture 重现。
31. 任何 gap 在 resync 完成前将相关 instrument/feed 降为 untrusted。
32. Instrument sampling 不再按名称截前 N。测试/低带宽模式使用确定性的 expiry/type/moneyness/delta stratification，并报告 coverage；正式分析使用完整 policy scope。
33. DVOL resolution、poll/subscription interval 和 max age 使用同一配置来源，默认 60-second resolution 且 max age 不小于两个有效采样周期。
34. 原始事件采用 append-only、按日期/venue/feed 分区的本地研究存储；canonical snapshots 带 content hash。
35. 初期 job/metadata/ledger 可使用本地事务存储实现，但必须通过 repository port 隔离，以便后续迁移到生产数据库。
36. 一个真实历史来源或自采 corpus 必须经过 raw artifact → canonicalization → quarantine → eligible pipeline；没有 raw artifact 的行不能用于训练或回测资格声明。

### 6. Pricing and model governance

37. BTC calls + puts 和 inverse economics 先成为 golden path；USDC linear 在相同 contract/oracle suite 通过后开放。
38. PricingKernel 使用 forward/carry/funding 和 discount inputs，并明确输入缺失策略。
39. E1 detector 优先使用模型无关不等式与同步可成交报价，不依赖预测模型晋级。
40. E2 使用受约束 SVI/SABR 或经批准插值；每个输出包含 uncertainty/fair band、fit residual、coverage 和 extrapolation flags。
41. QuantLib 和 py_vollib 首先作为离线 oracle/golden vector 来源，不默认成为生产请求链的重依赖。
42. 模型 promotion 需要预注册阈值、真实 OOS、dataset/model/config hash、无 leakage 证据、reviewer 和 rollback target。
43. 单一 PnL、Calmar 或 opaque score 不足以晋级；必须同时报告可靠性、tail risk、stability 和分层表现。
44. E3 的原 short-call、IV-RV 和 regime 策略只有在真实 path library 与 promoted model 后才能成为 watch candidate。

### 7. Opportunity and strategy economics

45. OpportunityRecord 的 edge class 只能是 model-free-arbitrage、relative-value 或 risk-premium；portfolio expression 单独记录。
46. 所有 legs 必须来自同一同步窗口，且 freshness 和 source trust 满足 detector policy。
47. Net executable edge 必须显式分解 market edge、spread、fees、slippage、depth impact、legging reserve 和 hedge cost。Gate 5 前 account-specific margin/capital charge 必须标记 not_evaluated，因此输出不得超过 research anomaly；Gate 5 后才可加入真实 incremental margin 并参与 watch-candidate 排序。
48. StrategyLeg 支持 side、quantity、instrument、product economics、entry policy 和 exit policy；策略 payoff 只能由 legs 聚合。
49. 首批 strategy catalog 包含 parity/box、vertical、calendar/diagonal、butterfly/condor、straddle/strangle、risk reversal 和 delta-hedged volatility；naked short 保留为受限对照，不作为默认推荐。
50. 推荐排序先通过硬门，再使用 conservative edge / incremental margin；opaque aggregate score 只可作为辅助解释。
51. 每个 watch candidate 都必须包含 TTL、kill conditions、why、why now、what invalidates 和可观察的下一步。

### 8. Portfolio risk and private account

52. PortfolioRiskEngine 必须从真实 legs/positions 聚合 Greeks 和 scenarios，不允许缺字段时默认 0/1 后继续。
53. 只读 private account、positions 和 simulate_portfolio 作为后期 Gate；缺失、过期或 simulation 未运行时 fail closed。
54. Deribit margin simulation 是当前保证金 source of truth；本地模型只提供 conservative tail overlay 和差异解释。
55. Risk arbiter 保持 severity monotonic，risk veto 始终覆盖 opportunity rank。
56. 组合风险至少覆盖 incremental IM/MM、Greeks、expiry/strike concentration、scenario tensor、CVaR、gap risk 和 exit liquidity。
57. 任何本地与 venue simulation 差异超出预设 tolerance 时，trade proposal 保持 NO-GO。

### 9. Replay, backtest and recommendation lifecycle

58. live 与 replay 使用相同 MarketEvent、ReplayClock、PricingKernel、detector 和 risk policies。
59. Fill model 使用 buy ask / sell bid 起点，并覆盖 partial fill、legging、latency、cancel/replace、fees、funding、hedge 和 settlement。
60. crossed、stale、empty、unknown-unit 或 ineligible history 不得进入 backtest。
61. Backtest 结果由 trade/cash/position/fee/settlement ledger 派生；没有足够样本返回 insufficient_evidence。
62. Recommendation 状态至少包括 observed、watchlisted、proposed、vetoed、expired、invalidated、reconciled。Proposed 不等于 approved。
63. outcome horizon、可成交退出价、费用和 settlement 必须在 detector policy 中预先定义，不允许事后选择有利窗口。
64. 所有状态转移 append-only，记录 actor、time、reason、previous state 和 evidence IDs。

### 10. API, jobs and platform operations

65. 分析、backtest、calibration 和 export 使用 job service；合法提交返回 job ID 和 immutable result location。
66. Invalid/unknown request fields 返回 400/422；合法异步提交返回 202；相同 idempotency key 与 body hash 返回同一 job。
67. Job queue 有界，满载返回 429/503；单请求不得无限创建 outbound workers。
68. GET report/result 不触发 live refetch；dashboard 刷新读取同一 immutable report 或显式提交新 analysis job。
69. /health 只表示 process liveness；/ready 报告 provider、store、last trusted snapshot、queue 和 model readiness。
70. Snapshot/report/job/recommendation 都有稳定 ID，并进入 structured logs、metrics 和 trace context。
71. 默认 loopback bind、fixture sandbox 和 outbound allowlist 保留；remote mode 必须先有 authentication、rate limit、TLS termination、RBAC 和 audit。
72. Secret 只能通过受控 secret boundary 注入，不得进入 CLI history、process arguments、logs 或 artifacts。

### 11. Analysis workbench

73. Workbench 由九个工作区组成：Market Overview、Option Chain、Surface Lab、Opportunity Board、Strategy Lab、Portfolio Risk、Replay/Backtest/Model Registry、Data Trust/Ops、Recommendation History。
74. 主流程是 Trust → Market → Opportunity → Strategy → Portfolio → Evidence；每一层可 drill down 到上一层证据。
75. Offline/fallback 时隐藏 candidate、calibrated、Calmar 等 plausible metrics，并显示全页 NOT CURRENT MARKET DATA 水印。
76. 顶部独立显示 report generated time、market as-of/data age、source class 和 trust verdict。
77. 0 candidate 空状态必须解释是无异常、成本覆盖、数据阻断、模型阻断还是风险 veto，并提供相应入口。
78. Desktop 承担完整 chain/surface/strategy 分析；mobile 只提供 trust、top candidates、risk blockers 和 alerts 摘要。
79. 需要稳定 selectors、keyboard/focus、WCAG AA 对比度、reduced motion 和可验证 responsive contract。
80. 现有依赖零的单页可以在 Gate 0–2 继续承载 trust 修复；Gate 6 前通过独立 ADR/原型决定是否迁移 component frontend，不能让框架选择阻断金融真值工作。

### 12. Delivery gates and exit criteria

#### Gate 0 — Financial Truth Corrections

范围：

- 完成 DT-001..010；
- 修复账户、inverse payoff tolerance、path time axis、backtest eligibility 四个反例；
- 修复 DVOL resolution/freshness 和 expiry/delta stratification；
- 删除或强水印 fixture calibration/backtest；
- 使 backtest API 真实校验请求并使用 job contract；
- 建立 ProductEconomics 和金融 property tests。

退出标准：

- 缺 observed_at、stale account 或 simulation 未运行不可能得到 GREEN/ALLOW_NEW；
- 错误 inverse payoff 不可能 ELIGIBLE；
- path 数量只由唯一时间点和 cadence 决定；
- crossed/stale/unknown-unit quote 不可能 backtest eligible；
- 每个可见经济数字都有 unit、source、as-of 和 fixture state；
- 所有已知反例成为固定回归测试；
- paper/manual/live 保持 NO-GO。

#### Gate 1 — Continuous Market Evidence

范围：

- REST bootstrap + WebSocket ticker/book/index/DVOL；
- heartbeat、reconnect、resubscribe、gap/resync、rate limit；
- immutable event store、snapshot manifest、replay clock；
- 一个真实历史 source/corpus；
- report ID、/ready、metrics 和 failure-injection。

退出标准：

- 24 小时 soak 无未解释 gap，并积累至少 7 个连续自然日运行证据；
- 所有 sequence discontinuity 被检测，resync 前不发布 trusted；
- 相同 event log 生成相同 canonical snapshot/hash；
- 代表性 expiry/delta coverage 达标；
- stale、partial、unknown settlement 均不能产生 trusted state。

#### Gate 2 — Pricing and Mispricing Truth

范围：

- BTC calls + puts、inverse/linear economics；
- forward/funding/discount；
- price、IV、Greeks；
- arbitrage-free surface、fair interval、model registry；
- E1 detector 和 E2 research surface；
- QuantLib/py_vollib differential oracle。

退出标准：

- oracle corpus 在声明容差内 100% 通过；
- put-call parity、vertical、butterfly、calendar 等 property tests 通过；
- 所有 fair value 带 model/input/version/uncertainty；
- 未知 unit/forward、oracle divergence 或 surface violation 不进入 detector；
- 成本覆盖 synthetic edge 后 E1 候选消失。

#### Gate 3 — Opportunity and Strategy Engine

范围：

- E1–E3 detector contract；
- OpportunityRecord、StrategyLeg grammar；
- 不含账户特定 margin 的 multi-leg market-executable economics；
- strategy comparison、TTL、kill conditions；
- defined-risk first catalog。

退出标准：

- 每个 OpportunityRecord 包含 edge class、fair band、legs、market costs、TTL、kill 和 lineage；
- 所有 legs 来自同步且 trusted market state；
- apparent edge 被成本覆盖时输出零推荐；
- hard risk gate 不能被 score 覆盖；
- E3 未晋级时只能输出 research anomaly；
- Gate 5 通过前，margin 和 portfolio impact 必须显示 not_evaluated，任何 OpportunityRecord 都不得晋级 watch candidate 或 trade proposal。

#### Gate 4 — Replay, Backtest and Model Promotion

范围：

- live/replay 统一事件语义；
- multi-leg fill、latency、slippage、fee、hedge、funding、margin、settlement；
- walk-forward/OOS/model registry；
- immutable recommendation/outcome ledger。

退出标准：

- 相同输入两次运行 ledger/result hash 完全相同；
- cash、position、fee 和 settlement 可逐笔对账；
- lookahead/leakage tests 通过；
- 所有绩效来自 ledger，样本不足显示 insufficient_evidence；
- fixture/tracer 永远不能 promoted。

#### Gate 5 — Portfolio Risk and Read-only Account

范围：

- 只读 account/positions/simulate_portfolio；
- incremental margin、Greeks、scenario、CVaR、concentration、exit liquidity；
- venue/local reconciliation 和 risk veto。

退出标准：

- private evidence missing/stale/unsimulated 时 fail closed；
- venue/local margin 和 scenario 差异有明确 tolerance/report；
- aggregate Greeks 与 signed legs 对账；
- 风险恶化不能使 final action 变宽松；
- 只有 Gate 0–4 已满足、Gate 5 risk evaluation 通过的 OpportunityRecord 才可晋级 watch candidate；
- 仍不存在下单方法。

#### Gate 6 — High-quality Analysis Workbench

范围：

- 九个工作区、drill-down、saved filters/watchlist、export；
- truthful offline/fixture states；
- job progress、model/recommendation history；
- accessibility、responsive 和 performance。

退出标准：

- 用户 30 秒内找到准确 trust/block reason；
- 用户 2 分钟内解释 top candidate 的 edge、成本和风险；
- API 断开时不显示任何看似真实的 fixture performance；
- 主流程 keyboard 可完成，focus 可见，文本达到 WCAG AA；
- 五档 viewport 无 console/page error 和 page-level overflow。

#### Gate 7 — Paper, Testnet and Manual

定位：

- 本 Gate 是未来独立授权项目的 release rubric。本文定义证据门，但不授权当前代理实现、启用 paper/testnet/manual 或改变任何 mode gate。
- 进入本 Gate 前必须创建独立 child PRD/issue、获得用户显式授权并重新进行安全评审。

未来授权后的范围：

- persistent paper ledger；
- proposal/approval、testnet、kill switch；
- credential isolation、RBAC、audit；
- 30–60 天 reconciliation。

退出标准：

- Paper 前连续 7 天 required-feed availability 不低于 99.5%，无 unresolved gap、unknown unit 或 critical truth defect；
- Paper 至少 30 个自然日、目标 60 日，并覆盖至少 100 个 qualified opportunity observations；
- 100% proposal/fill/fee/settlement/outcome 完成对账，0 unresolved high-severity discrepancy；
- Testnet 连续 14 天并覆盖至少 100 个 order lifecycle scenarios，0 duplicate/orphan order；
- partial fill、cancel/replace、restart recovery、auth expiry、settlement 和 kill-switch drill 全部通过；
- Manual 仅在用户显式批准独立 release gate 后讨论；
- 自动 live execution 仍需独立 PRD 和授权。

### 13. Dependency and migration order

81. 默认顺序为 Gate 0 → Gate 1 → Gate 2 → Gate 3 → Gate 4 → Gate 5 → Gate 6 → Gate 7。
82. Gate 0 的 DT-001 与 DT-008 可并行；四个金融反例、backtest API 和 UI fallback 作为新增 corrective slices。
83. Gate 1 的 event/replay contract 可以与 Gate 2 的离线 oracle corpus 并行，但任何 live detector 必须等待 Gate 1 trust。
84. Gate 3 可以在 synthetic/golden data 上开发，但只能输出 research anomaly；Gate 0–5 全部通过后才可发布 watch candidate。
85. Gate 6 的 trust/fallback 修复属于 Gate 0；完整 IA 和 component migration 后置，避免 UI 领先于能力。
86. Gate 7 是不可压缩的日历与运营证据门，不得用 fixture 或单次 testnet 替代。

### 14. Open-source reference policy

87. NautilusTrader 用作 Deribit adapter、resync、replay 和 failure-contract 参考。
88. QuantLib 和 py_vollib 用作定价 oracle 和 golden vectors 参考。
89. Optopsy、OpenBB、OptionLab 等 GPL/AGPL 项目只允许 clean-room 行为、schema、测试和 UX 研究，未经法律评审不得复制代码。
90. CCXT/cryptofeed 只解决 transport normalization，不得让通用 schema 丢失 Deribit product economics。
91. 不一次性引入完整交易框架；每个外部依赖必须通过独立 ADR、许可证、安全、性能和替换成本评估。

## Testing Decisions

### Testing principles

1. 测试外部可观察业务行为和金融不变量，不锁定私有 helper、实现顺序或静态文本。
2. 最高层主验收 seam 是固定 clock + fixture/replay 的 AnalysisRun/research report。CLI、API、Dashboard 只验证同一 report ID/snapshot ID 的投影一致性。
3. 不建立第二套数据质量、定价或风险逻辑。live adapter 与 ReplayEventSource 必须经过同一 canonical state transition。
4. 数值模型使用 checked-in、版本化 oracle corpus；CI 不依赖运行时网络或大型第三方模型。
5. 公网/live tests 显式 opt-in，不作为普通 CI 绿色前提；但 release gate 必须附带 soak/canary 证据。
6. 每个 gate 都必须先证明失败路径 fail closed，再证明成功路径可用。
7. 任何历史 done 状态都不能覆盖新的可复现反例；反例必须进入 regression suite。

### Primary test seams

| Seam | 主要外部行为 |
| --- | --- |
| AnalysisRun / research report | 从固定 snapshot/account/model 到 trust、pricing、opportunity、risk、recommendation 的最终业务裁决 |
| ProductEconomics | inverse/linear、settlement、premium、fee、contract scale、USD shadow |
| MarketDataAdapter + MarketEvent + MarketState | REST/WS/replay 一致性、gap/resync、retry、sampling、trust |
| PricingKernel | price、IV、Greeks、surface、fair band、no-arbitrage |
| OpportunityRecord + StrategyLeg | edge taxonomy、可成交成本、多腿 payoff、TTL、kill |
| ReplayEngine + PortfolioRiskEngine | deterministic ledger、fill、margin、scenario、risk veto |
| BacktestJobService + JobStore | schema、async lifecycle、idempotency、bounded queue、immutable result |
| RecommendationLedger + Readiness | append-only state、outcome、metrics、release evidence |
| Workbench browser contract | trust/source/time、offline state、drill-down、accessibility、responsive |

### Blocking regression cases

1. 账户缺 observed_at 或 PM simulation 未运行：live_snapshot=false、NO_TRADE，禁止 GREEN/ALLOW_NEW。
2. 故意错误的 5 BTC inverse payoff：必须 quarantine/ineligible，tolerance 使用 settlement-unit scale。
3. 9 个 unique timestamps × 2 instruments：path count 只由 9 个时间点和 horizon 决定。
4. crossed/empty/stale/unknown-unit entry：INELIGIBLE、backtest_allowed=false、无绩效。
5. 无效 backtest request：400/422，禁止返回 completed fixture comparison。
6. API failure/fallback：全页离线水印，不显示 calibrated、Calmar、候选或看似真实 performance。
7. DVOL 60-second data 在配置 freshness 窗口内不应天然 stale；超时必须结构化降级。
8. Low instrument limit 仍按确定性 stratification 报告 coverage，不得只取一个 expiry。

### Quantitative and property acceptance

1. Oracle corpus 覆盖 call/put、inverse/linear、多个 forward/strike/T/vol/rate 和极端边界。
2. Oracle corpus 对每个 vector 同时保存 venue quote coordinate、每合约 settlement amount 和 dimensionless normalized underlying fraction；比较只能在相同 coordinate 与相同 unit 中进行。
3. Linear price tolerance：在 settlement currency per contract 坐标中，absolute error 不高于 max(1e-8 settlement currency, 1e-7 × expected settlement amount)。
4. Inverse price tolerance：在 base coin per contract 坐标中，absolute error 不高于 max(1e-10 base coin, 1e-7 × expected coin settlement amount)。
5. IV absolute error 不高于 1e-6。Greeks corpus 必须声明量纲：delta 使用 underlying units、gamma 使用每 settlement-price unit、vega 使用每 1 volatility point；非零基准的相对误差不高于 1e-5，接近零时使用 corpus 中预先声明的绝对容差。
6. Put-call parity 先通过 ProductEconomics 将所有 legs 转换到共同 settlement coordinate，再比较 normalized forward value；residual 不高于 max(1e-10 normalized units, 1e-6 × normalized forward value)。
7. Price bounds、strike monotonicity、convexity 和 calendar total-variance monotonicity全部通过；数值 tick tolerance 必须在 corpus 中声明。
8. Strategy payoff 等于 signed leg payoff 之和；linear 与 inverse 分别在各自 settlement coordinate 中验收，误差不高于对应 price tolerance。
9. Defined-risk max loss 与解析值一致；naked short 明确 unbounded。
10. Portfolio aggregate Greeks 等于 signed leg sum，误差不高于 1e-6。
11. 风险状态满足单调性：任一风险输入恶化不得使 final action 变宽松。
12. 相同 event log、clock、config 和 model bundle 两次运行的 canonical snapshot、ledger 和 result hash 完全相同。
13. Future-data mutation 不改变 mutation 时间之前的 signal、order 或 recommendation。

### Adapter, resilience and operations acceptance

1. Golden adapter cases至少覆盖 normal、empty、partial、duplicate、stale、429、5xx、timeout、schema drift 和 malformed payload；全部零 crash、零 silent drop。
2. REST snapshot 与 WS replay 对相同市场状态生成相同 canonical snapshot/hash/trust verdict。
3. prev_change_id gap 立即 untrusted 并触发 resync；完成前不得发布 trusted snapshot。
4. duplicate/out-of-order delta 幂等；reconnect 后恢复精确 subscription set。
5. 重试策略通过 injected clock 测试 Retry-After、exponential backoff、jitter 和最大上限。
6. 24 小时 soak 零未解释 gap；所有 gap 在 30 秒内 resync；WS 恢复 p95 小于 10 秒。
7. 6 小时稳态零 crash，warm-up 后 RSS 增长低于 20%。
8. Fixture report build 在固定基准机/数据集上的 p95 小于 2 秒；缓存 report GET p95 小于 250ms。
9. Structured logs 必须包含 correlation/snapshot/report/job/model IDs，secret 泄漏数为零。
10. Chaos cases 覆盖 429、502、timeout、schema drift、gap、store unavailable 和 job crash；每种都可观测且 fail closed。

### API and browser acceptance

1. Backtest/analysis POST 校验 JSON；invalid/unknown fields 返回 400/422；合法异步请求返回 202 + job ID + result location。
2. Idempotency key + body hash 相同返回同一 job，不同 body 冲突；队列满载明确 429/503。
3. Report/result immutable；GET 不重新拉取 live。
4. /ready 在依赖不满足时返回 503 和 reason codes。
5. CLI/API/Workbench 对相同 report ID 的 trust、pricing、opportunity 和 risk 业务值完全一致，不只 schema shape 一致。
6. 浏览器覆盖 trusted → degraded → untrusted → offline；fallback 不显示 plausible metrics。
7. 1440、1366、900、620、390 五档 viewport：零 console/page error、零 page-level overflow；局部表格可在容器内滚动。
8. 主流程键盘可完成、focus 可见、文本达到 WCAG AA。
9. Stable selectors 至少覆盖 trust banner、source、times、candidate empty reason、job state 和 recommendation ID。

### Model and release evidence

1. 每个 fold 包含 dataset hash、cutoff、purge、embargo 和 holdout evidence。
2. Risk-premium model promotion 需要真实 OOS、无 leakage、预注册阈值、external review、owner 和 rollback。
3. Research fixture/tracer 永远不能 promoted。
4. Paper 前：已知 P0 反例为零、oracle corpus 100% 通过、连续 7 天 required-feed availability 不低于 99.5%、零 unresolved gap/unknown unit/critical truth defect。
5. Paper 完成：至少 30 个自然日、目标 60 日、至少 100 个 qualified opportunity observations；100% proposal/fill/fee/settlement/outcome 对账；零 unresolved high-severity discrepancy。
6. Testnet：连续 14 天、至少 100 个 order lifecycle scenarios、零 duplicate/orphan order；partial fill、cancel/replace、restart recovery、auth expiry、settlement 和 kill-switch drill 全通过。
7. Manual/live 不由本 PRD 自动开启；manual 需显式人审、RBAC、audit、kill switch，live 必须独立 PRD。

## Out of Scope

1. 构建交易所、撮合、托管、钱包、清算或经纪业务。
2. 自动 live order placement；任何 live automation 必须另立 PRD 和显式授权。
3. HFT、做市、亚秒级 latency arbitrage 或盘口抢价。
4. 第一阶段支持所有交易所、所有币种、所有奇异期权。
5. MVP 同时覆盖 BTC 与 ETH 的完整 production golden path；ETH 在 BTC 验收后接入。
6. 复制或近似复刻 Deribit 非公开 Portfolio Margin 引擎。
7. 用 LLM、黑箱 ML 或主观叙事直接决定 fair value、方向或交易许可。
8. 在缺少数据、单位、账户、模型或回测证据时输出 trade proposal。
9. 用 mark/mid 作为默认可成交价格。
10. 完整 OMS、税务、会计、清算和跨 broker portfolio。
11. 多租户 SaaS、计费、组织管理和公共云生产部署；remote multi-user 需要单独安全设计。
12. 移动端完整 Chain/Surface/Strategy 工作台；移动端只提供摘要与告警。
13. 未经许可证和法律评审复制 GPL/AGPL 项目代码。
14. 将研究结果包装为保证收益、无条件套利或自动化财务建议。
15. 在 Gate 0–5 未关闭前用大规模视觉重构替代金融真值工作。
16. 在本历史 PRD 所述发布动作中实现或启用 paper、testnet、manual；Gate 7 只定义未来独立授权项目的 release rubric。

## Further Notes

### Delivery order

Gate 0 Financial Truth
→ Gate 1 Market Evidence
→ Gate 2 Pricing Truth
→ Gate 3 Opportunity & Strategy
→ Gate 4 Replay & Model Promotion
→ Gate 5 Portfolio Risk
→ Gate 6 Analysis Workbench
→ Gate 7 Paper/Testnet/Manual

可并行关系：

- Gate 0：DT-001 与 DT-008 可并行；新增 P0 corrective issues 可分成 account/unit、path/backtest、API/UI 三条窄切片。
- Gate 1 与 Gate 2：event/replay contract 和离线 pricing oracle corpus 可并行。
- Gate 3：可先在 synthetic/golden market states 开发 detector，但只能输出 research anomaly；watch candidate 必须等待 Gate 0–5。
- Gate 6：trust/fallback 修复属于 Gate 0；完整工作台后置。
- Gate 7：30–60 天 paper evidence 是不可压缩日历门。

### Major risks and mitigations

| 风险 | 缓解 |
| --- | --- |
| 历史 tick/order-book 数据授权、成本和留存不足 | 先建立自采 immutable raw corpus；再通过独立 spike 选择一个 vendor |
| 多腿报价不同步制造虚假套利 | 同一 synchronization window、per-leg freshness、atomic opportunity evidence |
| inverse/linear 结算和 fee 漂移 | ProductEconomics + venue fixtures + differential reconciliation |
| 稀疏盘口导致曲面不稳定 | coverage/fair band/extrapolation flags；低质量曲面阻断 E2/E3 |
| 用 Deribit mark 校准又证明自身 | 独立 oracle、真实成交/settlement、cross-model disagreement |
| 多重假设检验和过拟合 | 预注册 detector、holdout、purge/embargo、false-discovery control |
| 回测/live 语义漂移 | 同一 MarketEvent、clock、detector、fill/ledger contract |
| Portfolio Margin 非线性 | venue simulate_portfolio 为 source of truth，本地只做 conservative overlay |
| rate limit/gap/reconnect 静默不完整 | sequence/gap、resync、bounded retry、/ready 和 metrics |
| 用户把 E2/E3 误读为套利 | 强制 edge taxonomy、fair band、术语 policy 和 UI 文案 |
| GPL/AGPL 许可证风险 | clean-room 参考，依赖前独立 license review |
| 从 short-call 扩平台导致范围爆炸 | 严格 gate、BTC inverse golden path、E1 优先、逐垂直切片 |
| 任意字典与单文件 UI 扩展成本 | typed deep modules；Gate 6 前独立 frontend ADR/prototype |
| 本地单用户升级远程多用户的安全差异 | remote mode 单独安全 gate，不隐式开放 |

### Definition of Done for this PRD

本 PRD 的产品计划完成需要：

1. Gate 0–6 的退出标准全部有可重复验证证据。
2. 每个 AnalysisRun 都能从 raw event、product economics、model bundle、policy 和 account evidence 重建。
3. E1 与至少一个 E2 detector 在真实、可信 Deribit data 上运行，并在成本后正确拒绝 false positives。
4. RecommendationRecord 对每个候选提供完整 edge、legs、cost、margin、portfolio、TTL、kill 和 lineage。
5. 回放、回测、模型晋级和 outcome reconciliation 不再包含可信表面上的 fixture/tracer 常量。
6. Workbench 完成从 Trust 到 Evidence 的核心旅程，offline/fallback 不显示 plausible market/performance。
7. 只读账户与组合风险可 fail closed；仍不存在自动下单方法。
8. Paper/Testnet/Manual 是否继续由 Gate 7 独立决定；未满足时保持 NO-GO。
9. Live execution 明确不属于本文完成标准。

### First implementation move

不要立即重写平台。第一步应将 Gate 0 拆成独立 tracer-bullet issues：

1. 继续现有 DT-001，并可并行 DT-008。
2. 新增 account evidence fail-closed corrective slice。
3. 新增 inverse payoff tolerance + path unique-time corrective slice。
4. 新增 backtest eligibility + real job API corrective slice。
5. 新增 dashboard fallback truth + time/source separation corrective slice。
6. Gate 0 关闭后，再为 MarketEvent/Replay、ProductEconomics 和 PricingKernel 建立 ADR 与 vertical slice。

本 PRD 是需求与验收总纲，不授权修改交易模式，不授权 live order，不代表任何开源依赖已批准引入。
作为 Parent PRD / Epic，它必须先通过 issue decomposition 形成可独立领取、可验证的 vertical slices；不得把整个 Epic 当作单个实现 issue。
