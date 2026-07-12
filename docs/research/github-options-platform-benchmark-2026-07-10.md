# GitHub 期权分析平台对标研究（Deribit 定价错配与策略推荐）

日期：2026-07-10
范围：仅研究与架构决策；不引入第三方代码、不启用 paper/manual/live trading
目标产品：不是交易所，也不是 Deribit 的复制品；而是以 Deribit 期权为主要标的，完成可信数据、定价与波动率分析、错配发现、策略组合、组合风险与证据解释的研究平台。

## 结论先行

1. **最值得借鉴的不是某个“完整开源期权平台”，而是一组可组合的能力基准。** 推荐的五个主参考是：
   1. [NautilusTrader](https://github.com/nautechsystems/nautilus_trader)：Deribit 实时数据适配器、重放与故障合同；
   2. [QuantLib](https://github.com/lballabio/QuantLib)：定价、曲面、校准和数值回归基准；
   3. [Optopsy](https://github.com/goldspanlabs/optopsy)：期权策略扫描、滑点与组合回测方法；
   4. [OpenBB](https://github.com/OpenBB-finance/OpenBB)：provider 标准模型、Deribit 链路和分析工作台的信息架构；
   5. [py_vollib](https://github.com/vollib/py_vollib)：Python 内可快速落地的独立 Black/Black-Scholes/BSM、IV、Greeks 数值 oracle。
2. **Top 5 不等于应把五个依赖装进项目。** NautilusTrader/QuantLib 体量和运行时边界很重，Optopsy/OpenBB 分别是 AGPL-3.0，最合理做法是先移植“合同、测试思想和交互模式”，只对 py_vollib/QuantLib 做隔离的 dev-oracle 或 sidecar 评估。
3. **当前产品离高品质平台最大的差距不是多几个指标，而是“从数据到建议的证据闭环”。** 高品质推荐必须回答：数据是否连续、产品单位是什么、模型为什么可信、错配是否可成交、费用/滑点/保证金后还有多少 edge、什么情况下建议失效、组合加入后最坏会怎样。
4. **Deribit 的 mark IV/mark price 不能直接等同于错配真值。** Deribit 的 book summary 暴露 mark IV、underlying price 和 interest rate，但官方也建议实时场景改用 WebSocket ticker，而不是轮询 summary；真正可交易的机会必须以 bid/ask/depth、费用、滑点与模型区间计算。[官方 book summary](https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency) [市场数据最佳实践](https://docs.deribit.com/articles/market-data-collection-best-practices)
5. **开源项目无法替代历史数据资产。** 大部分“Deribit options dashboard”是即时快照或演示；少数历史下载项目没有测试、许可证或稳定数据合同。可信的 quote/order-book/settlement 历史库、版本化快照和长期 paper reconciliation 仍需本项目自己建设。

## 研究方法与判断规则

- 2026-07-10 使用 GitHub 官方仓库页面、GitHub API/仓库树、README、许可证、测试与项目官方文档复核；不采用博客、聚合榜单或二手评测。
- 不按 star 排名。优先考察：与 Deribit/期权错配的贴合度、测试深度、合同清晰度、维护状态、许可证、能否映射到本项目现有 Python 边界。
- 维护状态口径：
  - **活跃**：最近 90 天有 push 或 release；
  - **观察**：90 天至 12 个月；
  - **陈旧**：超过 12 个月；
  - **归档**：GitHub 标记 archived，不论最后 push 日期。
- 集成优先级口径：
  - **P0**：马上转化为本地合同、测试或隔离评估；
  - **P1**：一个季度内原型验证；
  - **P2**：只作架构/UX/测试参考；
  - **P3**：不集成，只保留反例或历史参考。
- “借鉴”默认指思想、schema、测试和交互模式，不表示复制源码。许可证判断仅作工程筛选，不构成法律意见。

## Top 5：最有价值的主参考

### 1. NautilusTrader：Deribit 数据平面与可重放运行时的最佳对标

**为什么排第一**

- 官方仓库将研究、确定性模拟和 live execution 放在同一事件驱动语义下，并提供被标为 stable 的 Deribit 集成。[README](https://github.com/nautechsystems/nautilus_trader#readme)
- Deribit 指南明确覆盖 options、option combos、instrument provider、HTTP、WebSocket、order-book resync、DVOL、自身 rate limiter，以及 inverse option amount 语义。[Deribit integration guide](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/integrations/deribit.md)
- 仓库包含成体系的 Deribit instrument、HTTP、WebSocket、option combo、portfolio、DVOL JSON fixtures 和 adapter tests，而不是只有 happy-path demo。[Deribit test data](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/adapters/deribit/test_data) [adapter tests](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/adapters/deribit/tests)

**本项目应借鉴**

- `snapshot -> event stream -> gap detection -> REST resync -> versioned replay` 的数据状态机；
- instrument provider 与 market-data client 分离；
- option、future、option combo 都使用明确 instrument identity 和 amount/contract 语义；
- 把 WS error、timeout、partial snapshot、reconnect、duplicate notification 变成可离线重放的 golden fixtures。

**不要直接照搬**

- 不要把整个 Rust/Python 交易引擎作为当前研究控制台的基础设施；LGPL-3.0、运行时复杂度和执行能力都会扩大当前安全边界。[许可证](https://github.com/nautechsystems/nautilus_trader/blob/develop/LICENSE)
- 当前阶段只吸收 public-data adapter 合同和测试形状，不接 execution client。

### 2. QuantLib：定价与无套利曲面的独立数值基准

**为什么重要**

- QuantLib 是持续维护的衍生品定价/风险库；2026-07-06 仍有 push，2026-04-17 有 release。[commits](https://github.com/lballabio/QuantLib/commits/master/) [releases](https://github.com/lballabio/QuantLib/releases)
- 源码包含 SVI、no-arbitrage SABR、Heston、Black variance surface、Andreasen-Huge interpolation 及对应测试。[SVI test](https://github.com/lballabio/QuantLib/blob/master/test-suite/svivolatility.cpp) [Andreasen-Huge test](https://github.com/lballabio/QuantLib/blob/master/test-suite/andreasenhugevolatilityinterpl.cpp) [Heston model](https://github.com/lballabio/QuantLib/tree/master/ql/models/equity)

**本项目应借鉴**

- 将价格、IV solver、Greeks、surface calibration 分成可替换组件；
- 为每个模型建立 benchmark vectors、极端输入、单调性和无套利回归；
- 当前曲面输出应增加：fit residual、参数边界、butterfly/calendar violation、外推区、报价覆盖度、模型间差异。

**不要直接照搬**

- QuantLib 的通用 equity/FX 抽象不能自动解决 Deribit inverse/linear、币本位 premium、forward、contract multiplier 和交易成本语义；
- 先作为离线 oracle/sidecar 做 differential testing，再决定是否引入 Python bindings；不要让一个大型 C++ 依赖成为核心请求链的单点故障。
- 许可证文本是 BSD-3-Clause 风格，但 GitHub SPDX 显示 `NOASSERTION`，依赖评审时需按实际文本确认。[许可证](https://github.com/lballabio/QuantLib/blob/master/LICENSE.TXT)

### 3. Optopsy：从“策略枚举”走向“可执行回测”的方法基准

**为什么重要**

- Optopsy 提供多腿期权回测、portfolio simulation、风险指标、profit target/stop loss、mid/spread/liquidity/per-leg slippage 等，且测试覆盖 data quality、timestamp、IV surface、portfolio simulator、metrics 和 schema。[README](https://github.com/goldspanlabs/optopsy#readme) [tests](https://github.com/goldspanlabs/optopsy/tree/main/tests)
- 2026-06-30 仍有 push，2026-03-02 有 release，属于活跃项目。[commits](https://github.com/goldspanlabs/optopsy/commits/main/) [releases](https://github.com/goldspanlabs/optopsy/releases)

**本项目应借鉴**

- 策略不是静态名称，而是“腿选择规则 + entry/exit policy + fill model + risk metric + trace”；
- 每个推荐策略必须同时输出 mid 理论收益和 executable 保守收益；
- 用 liquidity/slippage/commission/early-exit 场景把纸面 edge 打折，避免把宽 spread 当套利。

**不要直接照搬**

- 核心样例和数据假设更偏传统美股期权，不能直接套 Deribit 24/7、European cash settlement、inverse premium 和 crypto jump risk；
- AGPL-3.0 不适合作为闭源网络产品的无评审依赖，只能先参考行为和测试。[许可证](https://github.com/goldspanlabs/optopsy/blob/main/LICENSE)

### 4. OpenBB：标准化 provider 与分析工作台的信息架构

**为什么重要**

- OpenBB 的“connect once, consume everywhere”把 provider 数据统一暴露给 Python、REST、Workspace 与 AI agent，适合本项目未来从本地 JSON console 升级为分析平台的边界设计。[README](https://github.com/OpenBB-finance/OpenBB#readme)
- 仓库有标准 options-chain model、Deribit provider、provider response recordings 和派生策略工具。[standard options model](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/provider/standard_models/options_chains.py) [Deribit options provider](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/providers/deribit/openbb_deribit/models/options_chains.py) [Deribit recordings](https://github.com/OpenBB-finance/OpenBB/tree/develop/openbb_platform/providers/deribit/tests)

**本项目应借鉴**

- provider 原始字段与 canonical model 分层；
- schema 自描述、单位元数据、typed query、provider-specific extension；
- 一次接入同时服务 API、分析 notebook、dashboard 和 agent，而不是为每个 surface 重算一遍。

**不要直接照搬**

- AGPL-3.0，适合架构/交互参考，不适合未经法务评审直接嵌入网络服务。[许可证](https://github.com/OpenBB-finance/OpenBB/blob/develop/LICENSE)
- 当前 Deribit provider 将 `contract_size` 设为 1，并对部分 inverse price 做 USD 归一；而 Deribit 2026 年 linear altcoin options 存在不同 contract multiplier。该实现说明“统一 schema 很有价值”，也说明“归一化可丢失产品经济学”。[provider implementation](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/providers/deribit/openbb_deribit/models/options_chains.py) [Deribit linear options specification](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options)

### 5. py_vollib：最适合先落地的 Python 数值交叉校验器

**为什么重要**

- 提供 Black、Black-Scholes、Black-Scholes-Merton 的 price、IV、analytical/numerical Greeks；底层 LetsBeRational IV solver 适合作为本项目公式的独立 oracle。[README](https://github.com/vollib/py_vollib#readme)
- 仓库有 reference-Python differential tests；2026-05-29 有 push、2026-04-30 有 release。[tests](https://github.com/vollib/py_vollib/tree/master/tests) [releases](https://github.com/vollib/py_vollib/releases)
- MIT 许可证，依赖风险低于 GPL/AGPL 项目。[许可证](https://github.com/vollib/py_vollib/blob/master/LICENSE)

**本项目应借鉴/验证**

- 先将它作为 dev/test extra，而不是业务输出唯一来源；
- 对每个 canonical quote 同时跑本地公式与 py_vollib，比较 price、IV、delta/gamma/vega/theta；
- 覆盖 near-expiry、deep ITM/OTM、zero bid、宽 spread、异常 forward、极端 IV 与 inverse/linear 单位转换。

**不要直接照搬**

- 它不提供完整的无套利曲面、Deribit instrument/settlement、组合风险或执行模拟；准确的单点 Black 计算不等于可信的交易建议。

## 18 个项目决策表

> 维护日期是本次核验时 GitHub 默认分支的最近 push；“集成”包含测试/模式借鉴，不表示复制代码。

| # | 项目与覆盖面 | 维护 / License | 核心能力与最值得借鉴点 | 不能直接照搬 | 优先级 |
|---:|---|---|---|---|---|
| 1 | [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) — Deribit 数据、回放、交易引擎 | 活跃；2026-07-09；[LGPL-3.0](https://github.com/nautechsystems/nautilus_trader/blob/develop/LICENSE) | stable Deribit adapter、option/combo instrument、DVOL、order-book resync、fixtures、research/live 相同事件语义 | 整体引擎过重且扩大执行边界 | **P0：合同/fixtures 参考** |
| 2 | [lballabio/QuantLib](https://github.com/lballabio/QuantLib) — 定价、Greeks、曲面 | 活跃；2026-07-06；[BSD-3-style / SPDX NOASSERTION](https://github.com/lballabio/QuantLib/blob/master/LICENSE.TXT) | SVI/SABR/Heston/Andreasen-Huge、数值测试与模型分层 | 不理解 Deribit 产品单位、费用和流动性；C++ 运行时重 | **P1：隔离 oracle** |
| 3 | [vollib/py_vollib](https://github.com/vollib/py_vollib) — 单点定价/IV/Greeks | 活跃；2026-05-29；[MIT](https://github.com/vollib/py_vollib/blob/master/LICENSE) | Python 独立 IV/Greeks oracle，适合 differential tests | 无曲面、组合、交易所和风险语义 | **P0：dev/test extra 评估** |
| 4 | [goldspanlabs/optopsy](https://github.com/goldspanlabs/optopsy) — 策略扫描、组合回测 | 活跃；2026-06-30；[AGPL-3.0](https://github.com/goldspanlabs/optopsy/blob/main/LICENSE) | 多腿策略、portfolio simulation、risk metrics、slippage/liquidity、强测试面 | 传统期权假设；AGPL 网络传播风险 | **P0：行为/测试参考** |
| 5 | [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) — provider/API/workbench | 活跃；2026-07-08；[AGPL-3.0](https://github.com/OpenBB-finance/OpenBB/blob/develop/LICENSE) | canonical options schema、Deribit provider、provider recordings、一次连接多 surface | 产品单位归一可能失真；AGPL；Workspace 并非完全开源 UI | **P0：schema/IA 参考** |
| 6 | [QuantConnect/Lean](https://github.com/QuantConnect/Lean) — options engine/backtest | 活跃；2026-07-09；[Apache-2.0](https://github.com/QuantConnect/Lean/blob/master/LICENSE) | option chain、strategy factory、exercise/assignment/margin/fill，大量 regression algorithms | C# 大引擎；主要是传统 equity/index/future options，不是 Deribit 语义 | **P1：场景测试目录** |
| 7 | [rgaveiga/optionlab](https://github.com/rgaveiga/optionlab) — 策略收益/概率解释 | 活跃；2026-07-09；[GPL-3.0](https://github.com/rgaveiga/optionlab/blob/main/LICENSE) | 每腿 Greeks、盈亏区间、profit probability、expected gain/loss，API 小而易懂 | 非真实 execution/backtest；GPL；没有 crypto settlement/margin | **P1：recommendation explainability** |
| 8 | [OpenGamma/Strata](https://github.com/OpenGamma/Strata) — 市场数据/情景风险 | 活跃；2026-07-02；[Apache-2.0](https://github.com/OpenGamma/Strata/blob/main/LICENSE.txt) | immutable market-data box、scenario arrays、FX option vol surfaces、SABR calibration、深测试 | Java/OTC 定位，直接引入不合当前 Python 体量 | **P2：domain model 参考** |
| 9 | [OpenSourceRisk/Engine](https://github.com/OpenSourceRisk/Engine) — 定价/压力/XVA 风险 | 活跃；2026-06-11；[BSD-3-style](https://github.com/OpenSourceRisk/Engine/blob/master/license.txt) | scenario/stress/reporting、风险配置、透明风险引擎和综合测试 | 面向机构 OTC/XVA，C++、配置和构建复杂度远超当前需求 | **P2：风险报告 schema** |
| 10 | [quants-net/PyFENG](https://github.com/quants-net/PyFENG) — 多模型研究 | 活跃；2026-06-23；[GPL-2.0](https://github.com/quants-net/PyFENG/blob/main/LICENSE) | BSM、SABR、Heston、rough vol、SVI 和 benchmark data | 研究库不是生产曲面服务；GPL；无 Deribit/执行语义 | **P1：数值 benchmark 参考** |
| 11 | [marcdemers/py_vollib_vectorized](https://github.com/marcdemers/py_vollib_vectorized) — 批量定价/Greeks | 陈旧；2024-12-02；[MIT](https://github.com/marcdemers/py_vollib_vectorized/blob/main/LICENSE) | numpy/pandas 批量 price/IV/Greeks，适合 1k+ 合约性能基线 | 维护停滞；monkey-patch 风格；不解决数据和风险正确性 | **P1：性能 benchmark** |
| 12 | [ccxt/ccxt](https://github.com/ccxt/ccxt) — Deribit REST/WS 通用适配 | 活跃；2026-07-09；[MIT](https://github.com/ccxt/ccxt/blob/master/LICENSE.txt) | 多语言 Deribit adapter、统一错误/限流、静态 request/response fixtures。[Deribit TS adapter](https://github.com/ccxt/ccxt/blob/master/ts/src/deribit.ts) [static fixtures](https://github.com/ccxt/ccxt/tree/master/ts/src/test/static) | 通用归一模型可能抹掉 settlement、contract multiplier、combo/portfolio 细节；不能作 canonical truth | **P1：conformance/fallback oracle** |
| 13 | [joaquinbejar/deribit-websocket](https://github.com/joaquinbejar/deribit-websocket) — typed Deribit WS | 活跃；2026-07-08；[MIT](https://github.com/joaquinbejar/deribit-websocket/blob/main/LICENSE) | reconnect、heartbeat、timeout、request-id matching、backpressure；mock/integration tests 很完整。[tests](https://github.com/joaquinbejar/deribit-websocket/tree/main/tests) | Rust 边界；项目年轻、使用面小；execution 方法超出当前范围 | **P0：故障合同参考** |
| 14 | [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed) — 多交易所 WS feed | **归档**；2026-02-01；[自定义 permissive / SPDX NOASSERTION](https://github.com/bmoscon/cryptofeed/blob/master/LICENSE) | Deribit feed normalization、REST mixin、sample data、integration test。[Deribit adapter](https://github.com/bmoscon/cryptofeed/blob/master/cryptofeed/exchanges/deribit.py) | 已归档；统一 feed 丢失 options 专属语义；不宜新增生产依赖 | **P2：历史测试参考** |
| 15 | [coinmetrics/terifi](https://github.com/coinmetrics/terifi) — Deribit 历史数据下载 | 陈旧；2025-06-20；**NOASSERTION** | 到期日分组下载 Greeks/IV/price/OI 的数据分区思想。[README](https://github.com/coinmetrics/terifi#readme) | 无 tests/CI；README 声称 MIT 但仓库缺少 LICENSE 文件；依赖 Coin Metrics API；CSV schema 很薄 | **P3：只参考目录结构** |
| 16 | [jothamteo/deribit-options-dashboard](https://github.com/jothamteo/deribit-options-dashboard) — 直接可比的 Deribit 分析 UI | 活跃；2026-05-24；[MIT](https://github.com/jothamteo/deribit-options-dashboard/blob/main/LICENSE) | GEX、SVI、surface、25Δ RR/BF、max pain、公式方法页、fit RMSE、渐进渲染、browser tests。[methodology](https://github.com/jothamteo/deribit-options-dashboard/tree/main/docs) [tests](https://github.com/jothamteo/deribit-options-dashboard/tree/main/tests) | browser 直连、无持久化/服务端 trust；使用 mark IV；未做跨期限无套利；dealer GEX sign 假设脆弱 | **P0：最佳小型 UX/解释参考** |
| 17 | [wepoets1107/icefire-options-workbench](https://github.com/wepoets1107/icefire-options-workbench) — 本地 Deribit 工作台 | 活跃；2026-06-14；[MIT](https://github.com/wepoets1107/icefire-options-workbench/blob/main/LICENSE) | BTC/ETH gamma、skew、IV term structure、large trades、FastAPI + WS + DuckDB 的小型信息架构 | 本次树审查没有 tests/CI；Gamma put/call sign 和 skew 定义过于简化；不是定价错配引擎 | **P2：布局/本地快照参考** |
| 18 | [dwasse/vol-surface-visualizer](https://github.com/dwasse/vol-surface-visualizer) — Deribit vol surface 可视化 | 陈旧；2022-12-08；**无许可证** | 直观展示 strike/delta × expiry 的 3D surface；前后端 + PostgreSQL 的早期样例 | naive Black-Scholes + mid、无 license、无现代测试、密钥文件方式过时 | **P3：视觉历史参考** |

## 按能力域的参考选择

### A. 定价、Greeks 与波动率曲面

推荐组合：**py_vollib（快速独立 oracle） + QuantLib（深模型/no-arb oracle） + 本项目自有 Deribit product economics**。

- py_vollib 用来尽快锁住单点 price/IV/Greeks 正确性；
- QuantLib/PyFENG 用来建立 SVI/SABR/Heston、曲面无套利和数值极端值 benchmark；
- 产品自己的曲面服务必须保留原始 bid/ask/mark、forward source、settlement currency、premium unit、contract size、data timestamp 和 source lineage，不能只保留归一后的 `iv`。
- 每个曲面切片应输出：报价点数、双边报价率、最大 stale age、fit RMSE/MAE、parameter bounds、calendar/butterfly violations、extrapolation flag、model disagreement。

**关键判断：**“模型价格与 mark price 不同”不等于错配。mark 本身是交易所风险系统产物；错配应来自独立模型区间、跨行权价/期限一致性和可执行报价的共同证据。[Deribit inverse option mark-price说明](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options)

### B. 回测与策略扫描

推荐组合：**Optopsy 的 fill/slippage/portfolio 方法 + Lean 的回归场景目录 + OptionLab 的解释输出**。

- 策略 scanner 要把单腿/多腿候选建模为统一 leg graph，而不是硬编码一堆页面按钮；
- 最低策略集应包含：single-leg relative value、vertical、calendar/diagonal、risk reversal、straddle/strangle、butterfly/condor、box/parity violation；
- entry/exit 必须使用当时可见报价与可获得的 size，禁止未来数据、收盘后选择、同 timestamp 先看后下；
- 回测同时输出：mid PnL、executable PnL、fill probability proxy、slippage、fees、margin usage、hedge turnover、tail loss、liquidation/forced-close count；
- 每个策略都要有 walk-forward、regime split、liquidity bucket、expiry bucket、stress replay 和 holdout。

### C. Deribit 数据与接口

推荐组合：**Deribit 官方规范为唯一产品语义源 + Nautilus/joaquinbejar 作为适配器和故障测试参考 + CCXT 作为对照 oracle**。

- Deribit 官方要求实时数据优先使用 WebSocket，使用 `change_id/prev_change_id` 检测 order-book gap，并在 gap 后用 REST resync；应订阅 instrument lifecycle，而不是持续轮询全部 instruments。[市场数据最佳实践](https://docs.deribit.com/articles/market-data-collection-best-practices)
- `public/get_instruments` 明确给出 `settlement_currency`、`quote_currency`、`instrument_type`、`contract_size`、expiration 和 state；这些必须进入 canonical instrument registry，不能从名称或 quote currency 猜。[get_instruments](https://docs.deribit.com/api-reference/market-data/public-get_instruments)
- DVOL 应通过 subscription 成为带 timestamp/source 的一等 feed，而不是可有可无的装饰指标。[DVOL subscription](https://docs.deribit.com/subscriptions/market-data/deribit_volatility_indexindex_name)
- 数据层至少要有四种时间：exchange event time、receive time、normalized time、report generated time；跨 instrument 不能假设原子同步。

### D. 组合风险与保证金

推荐组合：**Strata 的 scenario market data + ORE 的 stress/report 思路 + Deribit 自身 margin simulation**。

- 风险不能只显示 Greeks 总和；要有 spot × vol × skew × time × liquidity 的联合情景矩阵；
- 对候选策略同时展示 standalone risk、incremental portfolio risk、concentration、margin delta、worst scenario 和 exit liquidity；
- Deribit `private/simulate_portfolio` 能返回模拟持仓后的初始/维持保证金，调用受 1 req/s 限制；未来只应通过 read-only private adapter 和 cache 使用。[simulate_portfolio](https://docs.deribit.com/api-reference/account-management/private-simulate_portfolio)
- 未来 portfolio margin 深化可参考 `private/pme/simulate` 的 ERM 场景输出，但当前 NO-GO 阶段不需要接交易权限。[PME simulate](https://docs.deribit.com/api-reference/account-management/private-simulate)

### E. 可视化与分析工作台

推荐组合：**OpenBB 的 canonical result/workspace 思路 + jothamteo 的方法透明度与 progressive render + IceFire 的本地快照体验**。

高品质页面不应只是漂亮图表，应形成以下阅读顺序：

1. **Trust banner**：数据 fresh/complete/continuous、单位/结算是否可信；
2. **Market map**：forward curve、ATM term structure、skew/smile、surface quality；
3. **Opportunity board**：按 executable edge、confidence、liquidity、capital efficiency 排序；
4. **Strategy detail**：每腿 bid/ask/depth、理论区间、费用、P&L cone、Greeks、margin、失效条件；
5. **Portfolio impact**：加入前后风险对比和 stress waterfall；
6. **Evidence drawer**：原始 snapshot ID、model version、fit diagnostics、backtest cohort、reason codes；
7. **Methods**：公式、假设、数据限制和可复现实验入口。

3D surface 只应是 drill-down；默认页面优先 2D slice、quality heatmap 和异常点，因为它们更容易判断价格错配是否来自坏数据或坏拟合。

## 对当前项目最关键的外部启示

### 1. 从 polling snapshot 升级为可证明连续的 market-data state

当前快照/报告链适合 research-only，但要成为高品质平台，必须补齐：

- WS subscription manager；
- instrument lifecycle manager；
- per-instrument sequence/gap detector；
- gap-triggered REST resync；
- event log + deterministic replay；
- feed lag、dropped/duplicate/out-of-order、reconnect、coverage metrics；
- schema version 与 raw payload retention。

这不是“为了低延迟”，而是为了能证明一次推荐使用了什么市场状态。

### 2. 建立真正的 product economics layer

Deribit 目前同时存在 inverse coin-settled 与 linear USDC options。inverse premium 以 base coin 表示；linear altcoin options 还可能有不同 contract multiplier，2026 年 linear settlement 流程也发生过变化。[inverse options](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options) [linear options](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options)

Canonical instrument 至少必须显式携带：

- product type：inverse / linear；
- base / quote / settlement / margin currency；
- amount、quantity、contract size/multiplier；
- premium unit、PnL unit、shadow USD conversion source；
- underlying index、expiry-matched future/synthetic forward；
- option style、settlement process、delivery timestamp；
- fee schedule、tick size steps、minimum amount、state。

### 3. 把“错配”定义成可执行的置信区间，而不是一个 model-minus-mark 数字

建议使用保守定义：

```text
long_edge  = fair_value_lower_bound - executable_ask - fees - slippage - model_reserve
short_edge = executable_bid - fair_value_upper_bound - fees - slippage - margin_capital_charge - model_reserve
```

其中 fair-value band 由多个 model/surface、quote uncertainty、fit residual 和 regime stress 共同决定。只有 edge 在所有必要成本后仍为正、数据 trusted、报价有容量、模型分歧在阈值内，才能进入“候选”；否则只显示“异常/需复核”。

### 4. 策略推荐必须从单腿 anomaly 升级为组合优化

推荐引擎应回答：

- 该错配最适合 outright、vertical、calendar、risk reversal 还是 delta-hedged structure？
- 哪个组合在相同风险预算下有最高 conservative EV/capital？
- 是否存在比裸卖 option 更好的 defined-risk 表达？
- 增加这一策略后，portfolio gamma/vega/skew/liquidity/margin concentration 是否恶化？
- 哪些 market move、surface repair、spread widening、data degradation 会使建议失效？

### 5. 历史与 paper evidence 是产品护城河，不是附属功能

开源项目最薄弱的共同点就是历史 quote/depth/settlement 证据。平台需要自己积累：

- full-chain snapshots 与 order-book/trade events；
- instrument registry/version changes；
- DVOL、forward、funding/basis、settlement/delivery；
- raw + normalized + quarantine 三层数据；
- model version、feature snapshot、recommendation snapshot；
- 后续 fill/reject/exit、fee、slippage、margin、realized path reconciliation。

没有这条 lineage，回测优秀和 UI 精美都不能证明建议可信。

## 建议的集成路线图

### Phase 0 — 数据可信底座（P0，先于新策略）

1. 以 Deribit 官方 schema 更新 canonical instrument registry；覆盖 inverse/linear、multiplier、expiry future 和 lifecycle。
2. 按 Nautilus/joaquin 的测试形状补齐 WS mock server、ID matching、timeout、reconnect、duplicate、gap/resync golden fixtures。
3. 建立 append-only raw event/snapshot store 和 deterministic replay；report 暴露 snapshot ID、sequence coverage、latency 与 schema version。
4. 用 CCXT/OpenBB/Nautilus 的 Deribit 输出做**对照**，差异进入 reconciliation，不把任何第三方归一结果当真值。

**出阶段门槛：**在断线、乱序、重复、schema drift、instrument 上下线时不崩溃、不静默丢数据、不产生 trusted recommendation。

### Phase 1 — 定价与曲面可信度（P0/P1）

1. 引入 py_vollib dev oracle；建立本地公式 differential suite。
2. 评估 QuantLib sidecar/offline harness，建立 SVI/SABR/Heston/no-arb benchmark corpus。
3. surface report 增加 fit residual、quote coverage、parameter stability、calendar/butterfly arbitrage、extrapolation 与 model disagreement。
4. 明确 forward source，禁止把 spot 或交易所 mark IV 无条件当模型输入/真值。

**出阶段门槛：**所有参与 scanner 的点都有双边报价/允许的替代规则、单位、forward、fit quality 和模型置信区间；坏曲面只产生诊断，不产生机会。

### Phase 2 — 错配与策略推荐（P1）

1. 建立 anomaly taxonomy：put-call parity、vertical convexity、calendar monotonicity、surface residual、cross-model disagreement、IV-RV、cross-expiry/underlying relative value。
2. 建立 strategy leg graph 与 constraint solver；优先 defined-risk 结构。
3. 借鉴 Optopsy 的 slippage/liquidity/per-leg fill 和 OptionLab 的收益/概率解释输出。
4. 推荐对象必须携带：每腿 executable quote、capacity、net cost/credit、fees/slippage、Greeks、margin、scenario P&L、confidence、reason/kill codes。

**出阶段门槛：**不存在仅凭 mark/mid 的正收益；所有候选能重放、能解释、能被 kill condition 自动撤销。

### Phase 3 — 组合风险与验证（P1/P2）

1. 参考 Strata/ORE 建立 scenario cube 和 portfolio incremental risk；
2. 接 read-only/testnet private replay 前，继续保持 margin/sizing NO-GO；
3. 接入后用 Deribit simulate_portfolio 对本地 margin proxy 做 reconciliation；
4. 扩展 walk-forward、purged split、regime/liquidity/expiry buckets、stress days、bootstrap uncertainty。

**出阶段门槛：**至少 30–60 天 paper reconciliation，成交/费用/滑点/保证金和风险预测均有可审计差异报告。

### Phase 4 — 高品质分析工作台（与 Phase 1–3 同步，但不提前包装假能力）

1. 保留当前 shared report contract，发展为 canonical analysis API；
2. 建立 trust → market → opportunity → strategy → portfolio → evidence 的信息层级；
3. 借鉴 jotham 的 methodology/fit-quality/progressive render，但所有数据由服务端 snapshot 驱动，不由 browser 直连交易所；
4. 提供 comparison mode：市场 mark、独立 model、surface fair、executable bid/ask、历史 percentile 同屏；
5. 每个图都显示 data timestamp、source、quality 和可下载 evidence，而不是隐藏在 tooltip。

## 明确不建议的做法

- **不建议整体迁移到 Lean、NautilusTrader、ORE 或 Strata。** 它们应是行为基准，不是当前产品的架构替代品。
- **不建议复制 GPL/AGPL 项目源码。** OptionLab、PyFENG、Optopsy、OpenBB 分别有强/网络 copyleft 约束；只做 clean-room 行为参考，除非完成法律与发布模式评审。
- **不建议依赖无许可证的 Deribit demo。** 无许可证不等于可自由复制。
- **不建议 browser 直连 Deribit 作为生产数据面。** 无法可靠保存 raw evidence、统一 freshness、gap/resync 和多用户 rate budget。
- **不建议把交易所 Greeks/mark IV 当独立验证。** 它们可以作为输入和对照，不是自有模型的独立 oracle。
- **不建议把通用 multi-exchange normalized schema 当 canonical instrument truth。** 归一层最容易丢 settlement、quantity/amount、contract multiplier、combo 与 margin 语义。
- **不建议用 3D surface、GEX 或 max pain 代替错配引擎。** 它们是观察工具；没有可执行报价、置信区间和成本模型时不能生成交易建议。
- **不建议过早开放自动下单。** 高品质首先表现为能拒绝坏数据、坏模型和不可成交机会。

## 项目级成功标准

平台达到“高品质”至少应同时满足：

1. **数据**：连续性、freshness、coverage、instrument economics、provenance 可证明；
2. **模型**：独立 oracle、no-arb diagnostics、uncertainty、版本和回归齐全；
3. **机会**：edge 基于 executable quotes，扣除费用/滑点/资本成本；
4. **策略**：多腿结构、容量、margin、情景损益、失效条件完整；
5. **组合**：增量 Greeks、tail/stress、liquidity、margin concentration 可解释；
6. **验证**：walk-forward、holdout、replay、paper reconciliation 不泄漏；
7. **稳定性**：断线、rate limit、schema drift、partial feed、model failure 均 fail closed；
8. **UX**：先显示可信度和结论，再允许钻取公式、原始数据与证据；
9. **治理**：模型/数据版本、审批、审计日志、release gate 和回滚明确；
10. **安全**：research-only 与 NO-TRADE 在证据不足时保持不可绕过。

## 一手来源索引

### Deribit 官方

- [API 首页与接口选择](https://docs.deribit.com/)
- [JSON-RPC 与 WebSocket 规范](https://docs.deribit.com/articles/json-rpc-overview)
- [市场数据采集最佳实践](https://docs.deribit.com/articles/market-data-collection-best-practices)
- [public/get_instruments](https://docs.deribit.com/api-reference/market-data/public-get_instruments)
- [public/get_book_summary_by_currency](https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency)
- [DVOL subscription](https://docs.deribit.com/subscriptions/market-data/deribit_volatility_indexindex_name)
- [inverse options contract specification](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options)
- [linear USDC options contract specification](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options)
- [private/simulate_portfolio](https://docs.deribit.com/api-reference/account-management/private-simulate_portfolio)

### 开源仓库

- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader)
- [QuantLib](https://github.com/lballabio/QuantLib)
- [py_vollib](https://github.com/vollib/py_vollib)
- [Optopsy](https://github.com/goldspanlabs/optopsy)
- [OpenBB](https://github.com/OpenBB-finance/OpenBB)
- [LEAN](https://github.com/QuantConnect/Lean)
- [OptionLab](https://github.com/rgaveiga/optionlab)
- [Strata](https://github.com/OpenGamma/Strata)
- [Open Source Risk Engine](https://github.com/OpenSourceRisk/Engine)
- [PyFENG](https://github.com/quants-net/PyFENG)
- [py_vollib_vectorized](https://github.com/marcdemers/py_vollib_vectorized)
- [CCXT](https://github.com/ccxt/ccxt)
- [deribit-websocket](https://github.com/joaquinbejar/deribit-websocket)
- [cryptofeed](https://github.com/bmoscon/cryptofeed)
- [Terifi](https://github.com/coinmetrics/terifi)
- [Deribit BTC Options Dashboard](https://github.com/jothamteo/deribit-options-dashboard)
- [IceFire Options Workbench](https://github.com/wepoets1107/icefire-options-workbench)
- [vol-surface-visualizer](https://github.com/dwasse/vol-surface-visualizer)
