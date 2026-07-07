# 加密货币期权卖 Call 收租系统 PRD

版本：v1.1 PRD
来源：`crypto_options_short_call_system_spec_v1_1_audit_fixed.md`
日期：2026-07-07
状态：Product Requirements Document / Research & Risk System
适用范围：BTC/ETH 加密货币期权短 Call 与 Call Credit Spread 的研究、回测、选券、组合风控、纸面交易与人工确认执行支持
合规边界：本产品只输出研究与决策支持，不输出自动化实盘交易指令；任何实盘动作必须经过回测、walk-forward、纸面交易、账户风控和人工确认。

---

## Problem Statement

加密货币期权卖 Call 收租看起来像一个简单的高胜率策略，但实际风险集中在少数慢牛急拉、挤空、突破、极端波动和流动性恶化路径中。固定卖 7D 0.1 Delta Call 的规则无法回答几个关键问题：当前市场状态是否真的适合卖 Call，卖裸 Call 还是只能卖 defined-risk spread，当前权利金是否足以补偿真实世界路径损失，账户保证金、回撤、gamma、流动性和事件风险是否允许新增风险。

现有 v1.0 思路的问题不在于功能不够多，而在于证据链没有闭环。评分和推荐早于数据验收、合约 PnL 校验、保证金来源、回测仿真和样本外校准，导致系统可能用主观 regime 叙事、手填权重、乐观 mid 价、未验证第三方数据和不完整的 inverse PnL 公式给出看似精确但不可交易的建议。

用户需要的是一个先证明、再推荐的研究与风控系统：在数据质量、合约模型、保证金接口、路径风险分布、EV、组合风险和执行可成交性都通过时，才允许输出结构化 trade candidate；否则必须明确降级为 research-only、spread-only、no-trade、reduce 或 halt。

## Solution

构建一个 regime-aware、path-risk-aware、vol-surface-aware、portfolio-risk-aware 的加密货币期权短 Call 决策系统。系统以 BTC 为主标的、ETH 为次标的，优先支持 USDC linear options，fallback 支持 inverse options 但必须同步计算币本位 PnL 与 USD shadow NAV。

系统采用证据优先的产品流程：数据与账户接入先行，随后实现合约/PnL/费用/保证金适配器，再建立真实成交假设的回测执行仿真，之后进行 vol surface、regime、真实世界路径分布和评分模型校准，最后才输出候选排名、风险报告和纸面/人工执行 proposal。

最终用户看到的不是“直接卖某个 Call”的指令，而是一个可解释的研究报告：action、risk state、sell permission、naked permission、候选腿、DTE、Delta、可成交 credit、EV after cost、P_ITM、P_Touch、CVaR、stress loss、score、suggested size、entry rule、exit rule 和 reason codes。任何 kill condition、数据异常、账户接口不可用、未校准模型或风险仲裁更保守动作都必须覆盖评分结果。

## Product Goals

1. 判断当前市场和账户状态是否允许卖 Call。
2. 区分允许裸卖、只允许 Call Credit Spread、只允许观察、禁止新开仓、需要减仓或系统停机。
3. 在 2D-35D 候选范围中选择合适 DTE、Delta、Strike 和结构。
4. 用真实可成交 bid/ask、手续费、滑点、对冲成本、保证金增量和流动性计算 EV。
5. 用真实世界路径分布估计 P_ITM、P_Touch、MAE、CVaR、delta 穿越概率和 stress loss。
6. 用统一 risk arbiter 仲裁 MDD、保证金、事件、数据质量、交易所状态、流动性和持仓状态。
7. 用 walk-forward 和样本外测试证明 full system 相比固定 7D 0.1D short call baseline 改善 Calmar、CVaR 和慢牛急拉阶段回撤。
8. 在进入 paper/manual mode 前，完成数据验收、合约公式验收、回测复现、评分校准、风险冲突测试和 30-60 天纸面交易对账。

## Success Metrics

1. Full System OOS Calmar 高于固定 7D 0.1D naked short call baseline。
2. Full System OOS CVaR 99 低于 baseline。
3. 2023-2025 慢牛急拉窗口中的 MDD 或 worst-month loss 明显改善。
4. 无 lookahead bias，walk-forward 使用 purged split 与 max DTE embargo。
5. Vendor reconciliation 通过，失败数据不能进入训练和成交模拟。
6. 回测成交假设使用 sell at bid、buy at ask，不使用 mid/mark 乐观开仓。
7. Inverse/linear payoff、fee、delivery settlement、USD shadow NAV 单测通过。
8. Risk arbiter 在冲突状态下始终选择最保守动作。
9. Score 模型 OOS 分数与 realized utility 单调相关，未校准时只输出 RESEARCH_ONLY。
10. Paper trading 30-60 天内，proposal 的成交价、fee、slippage 与实际盘口可成交性吻合。

## Users And Actors

1. 期权策略研究员：需要验证卖 Call 策略是否有样本外边际，并分析不同 regime 的收益和尾部损失。
2. 交易决策者：需要在每天或盘中判断当前能否开仓、开多大、用裸 Call 还是 spread。
3. 风控负责人：需要看到账户 IM/MM、NAV/MM、MDD、CVaR、stress、delta/gamma/vega、集中度和 kill reason。
4. 执行人员：需要拿到人工确认用的 proposal、post-only limit 价格、腿信息、成本估计和退出规则。
5. 数据/平台工程师：需要接入 Deribit、vendor 历史数据、数据库、回测和监控。
6. 模型开发者：需要实现 surface fit、path distribution、regime permission、EV 和 score calibration。
7. 运维负责人：需要知道系统何时 research-only、no-trade、pause、halt，以及为什么降级。

## User Stories

1. 作为期权策略研究员，我希望系统先验收历史和实时数据质量，以便避免在错误报价或口径不一致的数据上训练模型。
2. 作为期权策略研究员，我希望第三方数据进入统一 canonical schema，以便 Tardis、Amberdata、CDD 和自采数据可以被可解释地对齐。
3. 作为期权策略研究员，我希望 vendor reconciliation 输出失败原因，以便决定某个 instrument、snapshot 或 vendor 是否应被隔离。
4. 作为期权策略研究员，我希望系统记录 quote age、bad quote ratio 和 surface no-arb error，以便识别 stale quote 或不可交易 expiry。
5. 作为期权策略研究员，我希望任一历史时点能重建 option chain，以便回测和候选扫描可复现。
6. 作为数据工程师，我希望实时行情使用 snapshot 加 websocket ticker 更新，以便减少轮询延迟和漏数。
7. 作为数据工程师，我希望 volatility index、funding、basis、spot/index 和 event calendar 都进入特征层，以便 regime 和风险许可有完整输入。
8. 作为数据工程师，我希望数据质量失败时系统自动降级 RESEARCH_ONLY_NO_TRADE，以便错误数据不会驱动交易候选。
9. 作为模型开发者，我希望每个 instrument 的 metadata、settlement currency、contract size、expiry 和 strike 被标准化，以便 payoff 和 fee 计算不混淆 inverse/linear 产品。
10. 作为模型开发者，我希望 OI 和 volume 单位被明确归一化，以便流动性过滤和 size 计算不被单位错误放大。

11. 作为策略研究员，我希望 linear USDC short call 的 entry credit、expiry payoff、MTM liability 和 PnL 公式被固定，以便回测和实盘报告一致。
12. 作为策略研究员，我希望 linear call credit spread 的 net credit、spread payoff 和 max loss 被固定，以便 defined-risk spread 的风险可解释。
13. 作为策略研究员，我希望 inverse short call 同时输出 coin PnL 和 USD shadow PnL，以便标的上涨时不会低估美元风险。
14. 作为策略研究员，我希望 inverse spread 同时报告 coin scenario max loss 和 USD shadow max loss，以便 sizing 使用更保守口径。
15. 作为风控负责人，我希望系统明确 Deribit private account API 是当前 equity、IM、MM 和 available funds 的 source of truth，以便保证金判断不依赖自研猜测。
16. 作为风控负责人，我希望 Portfolio Margin 账户使用交易所 simulation endpoint 估计 post-trade margin impact，以便不复刻非公开 PM 引擎。
17. 作为风控负责人，我希望 simulation endpoint 不可用时系统拒绝新开仓建议，以便保证金未知时不会冒险。
18. 作为风控负责人，我希望内部 stress engine 独立于交易所 margin，以便捕捉交易所压力网格外的尾部损失。
19. 作为平台工程师，我希望账户快照包含 nav_usd、im_nav、nav_to_mm、margin_model 和 data age，以便 risk gate 可以自动判断账户状态。
20. 作为交易决策者，我希望每个候选都计算 projected IM/MM 和 nav_to_mm，以便新增交易不会把账户推入 yellow/red 区间。

21. 作为模型开发者，我希望每个 expiry 都拟合 vol surface，而不是用 flat vol 估算 0.1 Delta strike，以便候选 Greeks 与 wing IV 匹配。
22. 作为模型开发者，我希望 surface fit 有质量分和 no-arb 检查，以便低质量 expiry 自动不可交易。
23. 作为模型开发者，我希望 exchange Greeks 与 model Greeks 双轨输出，以便交易所 UI 风险和自研模型风险都可见。
24. 作为模型开发者，我希望 model delta 和 exchange delta 差异过大时候选进入 review/reject，以便避免 surface 或交易所口径异常。
25. 作为策略研究员，我希望 regime 不是 if/elif 标签机，以便行动不受代码顺序偶然影响。
26. 作为策略研究员，我希望 bear、range、squeeze、slow bull、fast bull breakout、event、vol stress 和 data quality 独立打分，以便风险状态可以同时存在。
27. 作为风控负责人，我希望每个 risk score 输出 permission cap，并由最保守 cap 决定 sell permission，以便正向 regime 不能覆盖 kill state。
28. 作为风控负责人，我希望 Bear Trend 也受 DVOL/ATM IV percentile 限仓，以便熊市极端波动时不会满仓裸卖。
29. 作为模型开发者，我希望用户历史叙事只做 post-hoc sanity check，以便 regime 阈值不被事后故事过拟合。
30. 作为模型开发者，我希望 regime 阈值由 future touch、loss、CVaR 和 utility 的 walk-forward 结果决定，以便 permission cap 可证伪。

31. 作为模型开发者，我希望 P_Touch 来自路径最大值而非 terminal return，以便慢牛急拉路径不会被低估。
32. 作为模型开发者，我希望使用 similarity-weighted historical paths 和 block bootstrap，以便保留自相关、波动聚集和连续上冲结构。
33. 作为模型开发者，我希望 sparse regime 时触发 hierarchical pooling 和 stress mixture floor，以便样本不足时不会过度自信。
34. 作为风控负责人，我希望 effective sample size 低于阈值时禁止 naked 或强制 spread-only，以便稀疏状态不产生裸卖建议。
35. 作为策略研究员，我希望路径分布输出 P_ITM、P_Touch、MAE、delta 穿越概率、CVaR 和 stress loss，以便候选风险不只看到期收益。
36. 作为策略研究员，我希望 stress mixture 覆盖 spot +5/+10/+20/+30、IV jump 和 liquidity exit，以便极端路径有保守 floor。
37. 作为交易决策者，我希望候选生成只覆盖 naked short call 和 call credit spread，以便 MVP 聚焦最重要策略。
38. 作为交易决策者，我希望候选预过滤包含 DTE、delta、bid、OI、spread/mid、quote age 和 surface quality，以便明显不可交易合约先被剔除。
39. 作为交易决策者，我希望 7D/14D 是主力 DTE，0-1D 默认禁用，21-35D 偏向 spread，以便 gamma 和 vega 风险受控。
40. 作为交易决策者，我希望不同 permission state 对 naked delta、spread sell leg 和 protection leg 有不同范围，以便结构随市场风险变化。
41. 作为交易决策者，我希望 hazard zone 内 naked 被拒绝、spread 被降仓或拒绝，以便关键阻力/清算/expected move 区域不会被轻易卖出 convexity。
42. 作为交易决策者，我希望 EV 使用真实可成交 credit、真实世界 payoff、费用、滑点和 hedge cost，以便候选 edge 不被 mid 价虚增。
43. 作为交易决策者，我希望 bid_iv <= fair_physical_iv 时候选被拒绝，以便 IV 诊断能阻止没有波动补偿的交易。
44. 作为模型开发者，我希望 score 来自校准模型而非手填权重，以便评分能代表样本外 utility percentile。
45. 作为模型开发者，我希望 robust z 只使用训练窗口、同币种、同结构、同 DTE bucket 和同 delta bucket，以便标准化不泄露未来。
46. 作为模型开发者，我希望 EV 与 VRP 做相关性/VIF 检查，以便同源特征不会被重复计权。
47. 作为交易决策者，我希望未校准模型只能输出 feature table、raw EV 和 risk report，以便系统不会伪装成可交易推荐。
48. 作为交易决策者，我希望 score policy 能映射 standard、half/spread、observe 和 no-trade，以便不同质量候选有清晰动作。
49. 作为风控负责人，我希望任何 kill condition 都优先于 score，以便模型分数不能覆盖硬风险。

50. 作为风控负责人，我希望 MDD、保证金、事件、数据质量、交易所状态、流动性和持仓状态统一输出 action severity，以便冲突状态下可以自动仲裁。
51. 作为风控负责人，我希望 risk arbiter 取最高 severity，以便 margin green 不能覆盖 MDD halt。
52. 作为风控负责人，我希望保证金红绿灯使用 im_nav 和 nav_to_mm，以便账户风险可解释。
53. 作为风控负责人，我希望 MDD 触发 reduce、close all and pause，以便亏损进入预设熔断路径。
54. 作为风控负责人，我希望 sizing 同时受 CVaR、stress、delta、margin、liquidity、score、permission 和 volatility cap 限制，以便单一维度不会放大仓位。
55. 作为风控负责人，我希望默认风险预算限制单笔 spread loss、naked stress loss、expiry stress、portfolio stress、net delta 和集中度，以便组合层面可控。
56. 作为交易决策者，我希望持仓状态机区分 NORMAL、CAUTION、DEFENSE、EXIT_REQUIRED、FORCE_CLOSE 和 PAUSED，以便 roll、hedge、减仓和平仓不互相冲突。
57. 作为交易决策者，我希望 delta 0.35 以上默认退出，仅允许立即降低 stress loss 的转 spread，以便亏损递延不会被伪装成 roll。
58. 作为交易决策者，我希望主动 roll 只在 NORMAL/CAUTION 且风险改善时允许，以便 roll 不增加 short gamma 和 CVaR。
59. 作为交易决策者，我希望 net delta 超过 8-10% NAV 时通过 perp/future 降至 3-5% NAV，以便 directional exposure 可控。
60. 作为风控负责人，我希望 hedge cost 超过已收权利金一定比例时重新评估仓位，以便 hedge 不变成隐藏亏损。

61. 作为执行人员，我希望系统只为 top 1-3 候选生成 proposal，以便人工审核聚焦高质量机会。
62. 作为执行人员，我希望默认入场是 post-only limit 或更优价格，以便控制成交价格和盘口穿透。
63. 作为执行人员，我希望 naked 用 sell bid、spread 用 sell bid - buy ask 估算，以便 proposal 成交假设保守。
64. 作为执行人员，我希望净权利金至少大于 fee + slippage 的 5 倍，以便小边际交易不会被成本吞噬。
65. 作为执行人员，我希望事件窗口和结算窗口禁止短到期新开仓，以便规避非策略性跳变风险。
66. 作为执行人员，我希望订单流从 PROPOSED 到 REVIEWED，后续 APPROVED/SUBMITTED/FILLED/MANAGED 只在后期启用，以便 MVP 保持人工确认边界。
67. 作为交易决策者，我希望止盈规则支持赚 60% 平半仓、赚 80% 全平、theta 耗尽提前平仓，以便收益回收有纪律。
68. 作为研究员，我希望 backtest 逐时点记录 MTM、coin PnL、USD shadow PnL、Greeks、margin、state、touch、hedge、roll 和 forced exit，以便可审计每笔结果。
69. 作为研究员，我希望 full system 与 baseline、regime-only、pricing-only 做对照，以便证明是哪一层带来改进。
70. 作为研究员，我希望报告按 regime 分解收益、亏损、touch、forced exit、hedge cost 和 recovery days，以便找到系统弱点。
71. 作为用户，我希望 dashboard 第一屏显示 risk state、sell permission 和 no-trade reasons，以便立即知道今天能不能做。
72. 作为用户，我希望 dashboard 能查看 vol surface、regime、候选排名、组合风险、backtest 和 data quality，以便从机会到风险都有证据链。
73. 作为平台工程师，我希望 REST API 提供 health、chain、surface、regime、account risk、portfolio risk、candidates、recommendation 和 backtest report，以便 CLI/dashboard 可以复用同一服务。
74. 作为平台工程师，我希望 CLI 支持 ingest、fit-surface、build-features、backtest、calibrate、scan 和 recommend，以便研发和运维可以脚本化执行。
75. 作为运维负责人，我希望系统模式明确区分 research_only、paper 和 manual_execution，以便功能开放程度与校准成熟度一致。

## Functional Requirements

### P0 Evidence Chain

1. 系统必须按数据、合约/PnL/费用/保证金、回测仿真、regime/路径分布校准、评分推荐的顺序交付。
2. Phase 5 之前不得输出可交易分数、recommended size 或 trade instruction。
3. 校准模型不存在、数据质量失败、账户接口不可用、回测模拟器未对齐时，系统必须输出 RESEARCH_ONLY 或 NO_TRADE。
4. 所有 recommendation 必须包含 action、confidence、risk_state、permission、candidate legs、EV、path risk、portfolio risk、entry/exit rule 和 reason codes。

### P0 Data And Quality

1. 系统必须采集 Deribit option chain summary、ticker/order book、index/spot、volatility index、funding/basis、account summary、positions 和 event calendar。
2. 系统必须支持第三方历史数据 normalization 和 reconciliation，覆盖 metadata、timestamp、bid/ask、IV、mark/mid、vendor diff、payoff replay、OI/volume unit 和 no-arb 检查。
3. 数据质量 gate 必须覆盖 market data age、account data age、stale quote、valid quotes per expiry、bad quote ratio、surface no-arb error 和 vendor reconciliation。
4. 数据质量失败时，该数据不得用于训练、校准、成交模拟或交易候选。

### P0 Contract, PnL, Fee And Margin

1. 系统必须支持 linear USDC short call、linear USDC call credit spread、inverse short call 和 inverse call credit spread。
2. 系统必须为 inverse 产品输出 coin PnL、USD shadow PnL 和 USD shadow NAV。
3. 系统必须实现 BTC/ETH inverse options fee、USDC linear options fee、delivery fee 和 combo fee discount 的 conservative fallback。
4. 当前账户 equity、IM、MM、available funds 必须来自 Deribit private account endpoints。
5. 当前持仓 margin、Greeks 和 PnL 必须来自 Deribit positions endpoint。
6. Post-trade margin impact 必须优先使用 Deribit simulation endpoint；不可用时不得输出新开仓建议。

### P0 Models And Decisioning

1. 候选 Greeks 必须基于对应 expiry 和 wing 的 surface IV，而不是 flat vol。
2. Regime 必须以多个独立 risk scores 计算，不得由 if/elif label 顺序直接决定 action。
3. Permission caps 必须由最保守限制决定，并覆盖 Bear/Range 等正向信号。
4. DVOL/ATM IV percentile 必须作为全 regime 仓位上限，极端波动时可以 halt。
5. P_Touch 必须由路径最大值估计，不得由 terminal distribution 近似。
6. Path distribution 必须支持 similarity-weighted path sampling、stationary/circular block bootstrap、vol scaling、stress mixture floor 和 sparse fallback。
7. EV 必须基于可成交价格、真实世界 payoff、fee、slippage 和 hedge cost。
8. Score 必须来自 walk-forward 校准模型，VRP 只能作为 residual/tie-breaker/diagnostic，不能与 EV 重复高权重计分。

### P0 Risk And Position Management

1. 系统必须实现统一 risk arbiter，并以最保守 severity 作为最终动作。
2. Kill conditions 必须覆盖 EV、fair IV、spread、depth、breakout、event、risk state、margin、data age、settlement window、vendor quality 和 score calibration。
3. Sizing 必须取 CVaR、stress、delta、margin、liquidity、score、permission、vol cap 和 inverse multiplier 的综合最小约束。
4. 持仓管理必须由状态机驱动，解决 roll 与 hard stop 冲突。
5. Delta 0.35 以上默认 EXIT_REQUIRED，delta 0.40 以上或 breakout kill 为 FORCE_CLOSE。
6. Roll 后必须降低 EV/P_Touch/stress loss 或 total stress loss，不得只是递延亏损。
7. Hedge 必须计入 funding、fee 和 slippage，并在成本过高时触发仓位重评估。

### P1 Product Surfaces

1. Dashboard 必须包含今日总览、vol surface、regime、候选排名、组合风险、backtest 和 data quality 页面。
2. CLI 必须支持 ingestion、surface fitting、feature building、backtest、calibration、scan 和 recommendation。
3. API 必须支持 health、market chain、surface、regime、account risk、portfolio risk、candidates、recommendation、backtest run 和 report query。
4. JSON report 必须可被 dashboard、CLI 和后续人工审批 workflow 复用。

### P2 Execution Support

1. MVP 只允许 PROPOSED 和 REVIEWED，不做自动下单。
2. 纸面交易通过后可以进入 manual_execution，仍需人工确认。
3. 半自动执行必须保留 approval、order template、execution log reconciliation 和 post-trade review。
4. 自动实盘交易不属于本 PRD 范围。

## Implementation Decisions

1. 系统采用 research-only 优先的模式。默认模式为 research_only；paper 和 manual_execution 只有在 Definition of Done 通过后才可启用。
2. 系统分层为配置/账户/数据存储、市场数据与账户适配器、合约/PnL/费用/保证金模型、回测与校准引擎、vol surface/regime/distribution/scoring、dashboard/CLI/API、半自动执行。
3. 数据存储需要支持 instrument metadata、option chain snapshot、account risk snapshot、position snapshot、vol surface snapshot、regime features 和 candidate scores 等核心实体。
4. 第三方历史数据必须先进入 canonicalization，再进入 reconciliation；未通过的数据进入 quarantine 或 research-only，不得进入训练集。
5. Deribit account summary、positions 和 PM simulation 是账户与保证金 source of truth；内部模型只做 sanity check 和更保守 tail risk，不替代交易所接口。
6. USDC linear options 是首选产品，因为 PnL、保证金和回撤统计与 USD/USDC 账户绩效基准一致。
7. Inverse options 是 fallback 产品，但所有报告、回测和 sizing 必须同时维护 coin PnL 与 USD shadow NAV。
8. Vol surface MVP 可先使用平滑插值，但生产必须引入 no-arb 检查，并在 fit quality 不足时拒绝交易。
9. Exchange Greeks 用于对齐交易所 UI 和 margin 风险；model Greeks 用于选券、回测和风险归因。
10. Regime label 只用于报告展示；实际动作由 permission caps、risk arbiter、candidate EV、portfolio risk 和 kill conditions 共同决定。
11. Permission caps 是上限而不是正向授权；event、breakout、vol stress、data quality 等 kill/cap 可以覆盖 Bear/Range。
12. Path risk 使用路径库和 block bootstrap 估计，核心输出是 touch、adverse excursion、delta crossing、CVaR 和 stress loss。
13. Sparse regime 的默认产品行为是更保守：breakout sparse no-trade，squeeze sparse spread-only and small size，bear sparse spread preferred。
14. 候选生成只覆盖 naked short call 和 call credit spread；DTE 默认 2-35 天，7D/14D 为主力。
15. Candidate EV 使用 bid/ask conservative execution，不使用 mark 或 mid 作为默认可成交价格。
16. Score calibration 使用 realized utility、adverse event 和 ranking objective；未校准时只能输出 raw EV、feature table、risk report 和 no-trade reason。
17. Risk arbiter 使用统一 severity 语义，所有风控子系统只输出 signal，不直接绕过仲裁。
18. Position state machine 是持仓管理唯一入口；roll、hedge、reduce、close 必须由状态决定。
19. Order workflow MVP 停在 PROPOSED/REVIEWED；APPROVED 之后的提交、成交、管理状态只作为后续扩展。
20. Dashboard、CLI 和 API 共享同一 recommendation/report schema，避免不同界面出现不同口径。
21. 开发顺序按 Phase 0 到 Phase 7 推进，不允许为了 UI 或推荐效果提前绕过校准和数据验收。

## Milestones And Deliverables

### Phase 0 - 风险参数、账户模型、保证金接口 Spike

交付账户配置、account adapter、positions adapter、PM simulation 可用性 spike 和 margin source 决策文档。验收标准是能读取 equity/IM/MM/positions，能识别 margin model，能计算 nav_usd、im_nav、nav_to_mm，simulation endpoint 不可用时返回 NO_TRADE。

### Phase 1 - 数据管道与质量门槛

交付 option chain collector、ticker/order book collector、volatility index collector、index/funding/basis collector、vendor ingestion、normalization 和 data quality gate。验收标准是连续 7 天采集无中断，任一时点可重建 option chain，vendor reconciliation report 通过。

### Phase 2 - 合约、PnL、费用、结算模型

交付 inverse/linear payoff library、fee model、delivery settlement model、USD shadow NAV model 和已知样例单测。验收标准是 inverse call example、linear spread max loss 和 fee cap 计算正确。

### Phase 3 - 回测执行仿真器

交付 realistic fill simulator、path MTM and margin simulator、position state machine 和 risk arbiter replay。验收标准是 baseline 固定策略可复现，逐笔 PnL/fee/margin/state 可追踪，不使用 mid/mark 乐观成交。

### Phase 4 - Vol Surface、Features、Regime Risk 校准

交付 surface fitter、model Greeks、regime feature builder、permission cap model 和 walk-forward validation。验收标准是 7D/14D/30D surface 稳定，permission caps OOS 降低 adverse touch/loss，用户叙事只作为 sanity check 附录。

### Phase 5 - Path Distribution 与评分模型校准

交付 path/block bootstrap distribution、P_Touch/CVaR/stress module、score calibration 和 feature de-collinearity report。验收标准是 2023-2025 慢牛急拉 P_Touch 不被系统性低估，EV/VRP VIF 处理完成，OOS score 与 realized utility 有单调关系。

### Phase 6 - Research CLI 与 Dashboard

交付 research/paper mode 的 scan/recommend CLI、dashboard 和 JSON report。验收标准是 no-trade reason 明确，top-N candidates 可解释，不通过校准时只输出 RESEARCH_ONLY。

### Phase 7 - 纸面交易与半自动执行

交付 paper trading ledger、proposal approval workflow、post-only limit order template 和 execution log reconciliation。验收标准是 30-60 天 paper trade，预估成交价/fee/slippage 与实际盘口吻合，风控 state machine 能正确触发。

## Testing Decisions

测试原则是只测试外部可观察行为和风险结果，不测试实现细节。最高优先级测试切面是历史回放/回测报告，因为它同时覆盖数据、合约、成交、路径、风控、状态机、评分和报告输出。较低层测试只用于锁定数学公式、数据标准化、仲裁规则和状态转移这些高风险基础行为。

### Primary Test Seams

1. 历史 snapshot 到 candidate scan/report 的端到端研究切面。
2. Backtest replay 切面，用固定时间窗口复现 baseline 和 full-system 行为。
3. Contract/PnL/Fee 切面，用已知例子锁定 linear 和 inverse 产品公式。
4. Data normalization/reconciliation 切面，用 vendor overlap 和官方 delivery price 验收数据口径。
5. Risk arbiter 切面，用冲突信号验证最保守 severity 获胜。
6. Position state machine 切面，用 delta、loss multiple、breakout 和 MDD 场景验证动作限制。
7. Score calibration 切面，用 walk-forward split 验证 no leakage、OOS monotonicity 和 uncalibrated fallback。
8. Dashboard/API/CLI report schema 切面，验证所有入口共享同一结构化输出。

### Unit Tests

1. Linear short call payoff、linear spread payoff 和 max loss。
2. Inverse short call coin payoff、USD shadow PnL 和 inverse spread scenario loss。
3. BTC/ETH inverse option fee、USDC linear option fee、delivery fee 和 conservative combo fallback。
4. Robust z 只使用训练窗口和正确 reference bucket。
5. EV/VRP correlation、VIF、residualization 或 drop 行为。
6. Risk arbiter severity ordering。
7. Margin light green/yellow/red 规则。
8. Position state transitions 和 roll prohibition。
9. Block bootstrap path length、touch calculation 和 stress mixture floor。
10. Data freshness gate 和 stale quote rejection。

### Integration Tests

1. Deribit market data ingestion 到 canonical quote。
2. Account summary、positions 和 simulation fallback。
3. Surface fit from live or recorded chain。
4. Candidate scan from historical snapshot。
5. Backtest full replay for fixed window。
6. Recommendation/report JSON 被 CLI、API 和 dashboard 读取一致。
7. Vendor reconciliation report 通过和失败路径。
8. Paper trading ledger 与 proposal price/fee/slippage 对账。

### Regression Tests

1. 2021 fast bull window。
2. 2022 bear trend window。
3. 2023-2025 slow bull acute rally windows。
4. 2025 bear transition window。
5. Event window、settlement window 和 exchange abnormal state。

### Safety Tests

1. Stale account data 触发 NO_TRADE。
2. Market data age 超限触发 NO_TRADE。
3. MDD HALT 与 margin GREEN 同时出现时 HALT 获胜。
4. Delta 0.38 进入 EXIT_REQUIRED，不允许 roll up/out，除非 stress loss 立即下降。
5. Fast bull breakout 与 bear score 同时高时 BREAKOUT_KILL 获胜。
6. Sparse regime ESS 低于阈值时禁止 naked。
7. Vendor quality fail 时只输出 RESEARCH_ONLY。
8. Uncalibrated score model 时不得输出 recommended size。
9. Projected nav_to_mm 低于 2.00 时禁止新开仓，低于 1.50 时触发 reduce。
10. Settlement window active 时禁止新开短到期仓位。

## Out Of Scope

1. 全自动实盘交易。
2. 高频做市、抢价、盘口微结构 alpha 或 latency-sensitive execution。
3. SOL、XRP 或其他 altcoin options。
4. 未经验证的黑箱机器学习替代风控规则。
5. 未经校准的分数实盘下单。
6. 复刻 Deribit 非公开 Portfolio Margin 引擎作为保证金 source of truth。
7. 将用户主观历史叙事作为模型优化目标。
8. 用 mid/mark 价假设真实可成交。
9. 在数据、账户、回测或校准缺失时输出交易建议。
10. 作为投资建议或自动化财务顾问系统。

## Definition Of Done

1. 账户 API、持仓 API、margin simulation 可用，或不可用时能强制 no-trade。
2. 期权链、ticker、vol index、funding/basis 数据质量通过。
3. Historical vendor reconciliation 通过。
4. Inverse/linear PnL 和 fee 单测通过。
5. Backtest engine 能复现 fixed 0.1D baseline。
6. Path bootstrap 能输出 P_Touch/CVaR，且在慢牛急拉窗口不低估 touch。
7. Score model 经过 walk-forward 校准，OOS score 与 realized utility 单调。
8. Full system OOS 指标优于 baseline，尤其 2023-2025 MDD/CVaR 改善。
9. Risk arbiter 能处理所有冲突状态。
10. Paper trading 至少 30-60 天，执行价格和手续费对账通过。
11. Dashboard、CLI 和 API 输出一致的 JSON report。
12. Product mode gate 能阻止 research_only 系统输出可交易 recommendation。

## Further Notes

1. 本 PRD 以源 Spec 的审计修复结论为产品边界，核心产品原则是避免在错误 regime 中出售没有补偿的上行 convexity。
2. MVP 的价值不在于更早下单，而在于用数据质量、回测、路径分布和风控仲裁证明何时不该交易。
3. BTC 是主标的，ETH 是第二资产；ETH 的 size multiplier 应低于 BTC，直到 ETH 样本外验证通过。
4. Paper/manual mode 的前置门槛很高，这是产品安全设计的一部分，不是实现拖延。
5. 当前仓库未提供 issue tracker 和 triage label 配置；本次交付为本地 PRD Markdown。若后续接入 issue tracker，应将该 PRD 发布为需求条目并标记 `ready-for-agent`。
