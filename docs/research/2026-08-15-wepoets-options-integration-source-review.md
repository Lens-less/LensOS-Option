# Wepoets 期权项目整合评估（2026-08-15）

## 结论摘要

不建议把 12 个仓库中的任何一个整体合并、作为 Git 子模块接入，或把其 FastAPI/Flask/静态页面直接嵌入 LensOS Option。当前项目已经有 Deribit 快照、波动率曲面、候选扫描、多腿 payoff、组合 Greeks、告警、回放、信号验证与 React 工作台；真正值得补的是持续市场证据、模型可替换性、市场微观结构上下文和事件研究。

建议形成三条主线和两条实验线：

1. **主线 A — 实时市场证据与 SABR 对照模型**：参考 `options-eye`，但重新实现 WebSocket 事件契约、缺口/重同步和 SABR 模型插件，绝不引入其执行目录。
2. **主线 B — 市场上下文**：参考 `icefire-options-workbench` 的 term structure、delta skew 和 trade radar；Gamma 必须改称可验证的 gross gamma/OI proxy，不能伪装成 dealer net GEX。
3. **主线 C — 事件波动率研究**：参考 `event-volatility-trading-lab` 与 `us-options-buyer-strategy` 的事件窗口和 priced-vs-realized move 思路，但事件日期、修订状态和市场数据必须来自可追溯数据源。
4. **实验线 D — 教学/解释层**：可做独立 Greeks Lab 和证据受限的解释投影；不得影响准入结论。
5. **实验线 E — 分布距离研究**：`vol-surface-opt-trans` 只作为论文/方法线索，在离线环境重新实现和验证。

## LensOS Option 的现有基线

- 产品是 Deribit 加密期权卖方的入场前研究工具，可信输出止于 `execution_allowed=false`，不连接下单接口（[README](../../README.md)）。
- 后端运行时坚持零第三方依赖（[pyproject.toml](../../pyproject.toml)）；前端是 React/TypeScript/Vite（[web/package.json](../../web/package.json)）。
- 当前已有二次 IV 曲面拟合、no-arb 检查、Black-Scholes/Greeks 一致性、候选扫描、局部 skew 信号、信号验证、组合风险、payoff 图和告警（[`surface.py`](../../crypto_options_report/surface.py)、[`signal_validation.py`](../../crypto_options_report/signal_validation.py)、[`combination_risk.py`](../../crypto_options_report/combination_risk.py)、[`alerts.py`](../../crypto_options_report/alerts.py)）。
- 当前宏观日历被明确标为 `not_collected`，REST 快照也尚未成为带 sequence/gap/resync 的持续事件流（[`market_data.py`](../../crypto_options_report/market_data.py)、[平台 PRD](deribit-options-intelligence-platform-prd.md)）。
- 本仓库现有开源政策要求借鉴概念、schema、测试和架构，不直接复制第三方代码；无明确许可证的项目只能参考（[open-source-integration-opportunities.md](open-source-integration-opportunities.md)）。

## 逐项目判断

| # | 项目 | 结论 | 可整合内容 | 不应整合的内容 |
|---|---|---|---|---|
| 1 | [options-eye](https://github.com/wepoets1107/options-eye) | **高优先级，部分整合/重新实现** | 公共 WS supervisor、退避重连思路；SABR 作为对照模型；残差异常分类；告警去重语义 | `execution/`、测试网一键下单、对冲和平仓；现有轮转缓存和 SABR 代码不可原样进入可信链 |
| 2 | [binghuodao-DDH-tools](https://github.com/wepoets1107/binghuodao-DDH-tools) | **核心不整合** | 最多把阈值/定时 delta hedge 变成离线 `HedgePolicyReplay` 测试场景 | API key、订单、成交、mainnet/testnet 切换、实时 DDH runtime；全部越过当前永久 NO-TRADE 边界 |
| 3 | [icefire-options-workbench](https://github.com/wepoets1107/icefire-options-workbench) | **高优先级，部分整合/重新实现** | 25Δ/10Δ skew、ATM/FWD IV 期限结构、近期大额成交证据、市场上下文 UI | FastAPI/DuckDB 整套运行时；Call 正/Put 负的所谓 GEX；基于 mark/mid 的粗糙金额口径 |
| 4 | [us-options-buyer-strategy](https://github.com/wepoets1107/us-options-buyer-strategy) | **概念复用，暂不接美股** | ATM straddle priced move 与历史事件实际移动的比较；流动性硬门槛 | yfinance/Nasdaq 数据接入、160+ 美股 universe、买方推荐评分；会把产品扩成另一类资产与用户 |
| 5 | [us-options-strategy-assistant](https://github.com/wepoets1107/us-options-strategy-assistant) | **暂不整合** | 未来多资产版本可参考 provider adapter 与结构化 intent | 美股数据链、AAPL 白名单、独立 BSM/payoff 实现；当前项目已有更严格的 payoff/Greeks 契约 |
| 6 | [crypto-options-strategy-assistant](https://github.com/wepoets1107/crypto-options-strategy-assistant) | **中优先级，小范围整合** | 策略目录作为结构 grammar 的测试用例；用户观点/期限的结构化输入；可选解释 UI | “只推荐一个策略”、资金/张数判断、自由 LLM 决定方向或策略；不能影响 `EntryAdmissionDecision` |
| 7 | [astrooptions-compass](https://github.com/wepoets1107/astrooptions-compass) | **不整合** | 无独特能力；其中 DVOL、skew、PCR、basis 均有更可信实现路径 | 占星/星宿信号和由此驱动的策略评分，与 evidence-first 原则直接冲突 |
| 8 | [greeks-lab](https://github.com/wepoets1107/greeks-lab) | **可选独立 Lab，clean-room 实现** | 参数滑杆、1/2/3 阶 Greeks 曲线、人话解释的教学交互 | 不能另建一套未经 oracle 锁定的定价公式；默认树未见明确许可证，代码和视觉资产不复制 |
| 9 | [crypto-options-blind-box](https://github.com/wepoets1107/crypto-options-blind-box) | **不进入产品** | 若未来做独立营销活动，只可借鉴“最大亏损先固定”的文案主题 | 随机抽卡、币种/任务随机化会弱化严肃研究定位；默认树未见明确许可证 |
| 10 | [mbti-options-personality-test](https://github.com/wepoets1107/mbti-options-personality-test) | **不进入产品** | 最多作为完全分离的获客 microsite 概念 | 人格到策略的映射不是研究证据；默认树未见明确许可证和独立素材授权 |
| 11 | [event-volatility-trading-lab](https://github.com/wepoets1107/event-volatility-trading-lab) | **高产品价值，代码仅作原型参考** | 事件日历、T±1/3/7 窗口、BTC/DVOL 事件研究、当前 regime 的事件上下文 | 现有硬编码/规则生成日期、简单样本均值和阈值策略矩阵不能进入可信链 |
| 12 | [vol-surface-opt-trans](https://github.com/wepoets1107/vol-surface-opt-trans) | **离线研究参考，不复制代码** | SVI、风险中性/实际分布、W1/W2、期限匹配 VRP 的实验设计 | SPX 数据管线和生产信号；仓库是 fork、默认树/pyproject 未声明许可证，README 也承认关键结果仅样本内且未完成稳健性验证 |

## 关键源码核验

### 1. `options-eye` 是有价值的原型，不是可直接移植的采集器

其 [WebSocket 客户端](https://github.com/wepoets1107/options-eye/blob/main/data/deribit_ws.py) 具备重连、指数退避和 watchdog，但存在可信数据链不能接受的行为：

- 单连接每 30 秒轮转最多 200 个 ticker，得到的是跨数十秒乃至数分钟的异步横截面，不是同一观察时点的曲面。
- 缓存时间使用本机 `time.time()`，没有保留 venue timestamp、raw payload、sequence/gap 或 snapshot manifest。
- 全局 `last_ticker_ts` 可以被一个活跃合约刷新，无法证明每个合约/到期日都新鲜。
- 订阅失败路径仍把目标集合写入 `subscribed`，可能使缺失订阅被当成已订阅。

其 [SABR 校准器](https://github.com/wepoets1107/options-eye/blob/main/sabr/calibrator.py) 使用 NumPy/SciPy `least_squares`、固定 beta、mark IV 和单一 RMSE 阈值；没有 bid/ask band、权重、参数不确定性、跨初值稳定性或 no-arb/promotion 契约。它适合作为模型接口和 oracle 测试的起点，不适合作为生产实现。其 [依赖](https://github.com/wepoets1107/options-eye/blob/main/requirements.txt) 也与 LensOS 后端零运行时依赖约束冲突。

Deribit 当前官方 ticker 订阅允许 `raw`、`100ms`、`agg2`，并建议用推送而非轮询；实现应以[官方订阅契约](https://docs.deribit.com/subscriptions/upcoming/market-data/tickerinstrument_nameinterval)为准，而不是把上游 README 的实测假设固化为本项目协议。

### 2. `icefire` 的图表方向好，但 Gamma 口径必须重做

[`build_gamma_map`](https://github.com/wepoets1107/icefire-options-workbench/blob/main/app/main.py) 计算 `gamma × OI × spot² / 100` 后，直接把 Call 设正、Put 设负。公开 OI 不能告诉我们 dealer/客户谁长谁短，因此该值不能命名为 dealer net GEX。可接受的输出是：

- `gross_open_interest_gamma`（非负）；或
- 在未知持仓方向下的上下界/情景；或
- 有只读账户证据时计算“本账户净 Gamma”，但仍不能外推全市场 dealer 仓位。

Skew、ATM/FWD IV 和成交雷达可以用 LensOS 现有规范化快照重算。Deribit 官方近期成交端点只覆盖最近 24 小时，因此若要回放或做基线，必须在采集时追加保存原始成交事件，而不能依赖事后回补（[官方端点](https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_currency_and_time)）。

### 3. 事件实验室应借鉴 schema，不应借用事件表

上游 [`events.py`](https://github.com/wepoets1107/event-volatility-trading-lab/blob/main/app/core/events.py) 混合硬编码 CPI/NFP/FOMC 日期与“每月第一个工作日/最后工作日”等规则推导；部分 PCE/GDP 日期共享同一占位集合，也没有公告版本、修订记录、抓取时间或来源文档 ID。其 [`analyzer.py`](https://github.com/wepoets1107/event-volatility-trading-lab/blob/main/app/core/analyzer.py) 主要做简单窗口收益汇总和固定阈值分类，缺少显式评估时钟、重叠事件处理、数据泄漏控制与多重比较治理。

正确整合方式是定义可审计的 `EventCalendarRecord`，把“原定时间、实际发布时间、修订版本、来源、retrieved_at、as_of”作为证据，再复用 LensOS 的回放、非重叠样本、信号验证和 pre-registration 机制。

### 4. `vol-surface-opt-trans` 只适合离线方法研究

该项目的 [README](https://github.com/wepoets1107/vol-surface-opt-trans) 明确把 W1-VRP 关系称为 in-sample association，并列出跨期限和子样本稳健性尚未验证；[pyproject.toml](https://github.com/wepoets1107/vol-surface-opt-trans/blob/main/pyproject.toml) 依赖 Polars、NumPy、SciPy、arch、PyArrow、Matplotlib 等，且未声明 license。即使未来使用，也应在隔离的研究环境中基于原始论文 clean-room 实现，输出 `exploratory/not_promoted`，不能进入候选排名。

## 推荐目标架构

```text
Deribit WS / REST / verified calendar providers
                    │
                    ▼
       read-only collectors / sidecars
       - no order API, no trade credentials
       - append-only raw events + provenance
                    │
                    ▼
     MarketEvent.v1 / EventCalendar.v1
       gap + resync + per-key freshness
                    │
                    ▼
          canonical snapshot + HMAC
                    │
                    ▼
      existing AnalysisRun / evidence chain
          │               │
          ▼               ▼
 SurfaceFit.v2      MarketContext.v1
 quadratic + SABR   skew/term/gamma proxy/trades
          │               │
          └───────┬───────┘
                  ▼
       existing report projection + React UI
                  │
                  ▼
 optional explanation/labs (read-only projection)
```

### 新契约建议

1. `MarketEvent.v1`
   - provider/channel/instrument、venue timestamp、receive timestamp、source sequence（可空但必须说明）、raw hash、schema version。
   - book/trade 通道分别用 `change_id`/`trade_seq` 做 gap 检查；ticker 无 sequence 时用 freshness、重订阅和 REST resync 证明覆盖。
2. `SurfaceFit.v2`
   - `model_id/model_version/params`、fit sample hash、bid/ask/mark 口径、RMSE/robust residual、coverage、uncertainty、extrapolation、no-arb verdict。
   - 当前 quadratic 保持基线；SABR 先标 `experimental`。模型分歧是证据，不允许动态选择“更会发现异常”的模型。
3. `MarketContext.v1`
   - 25Δ/10Δ risk reversal、ATM/FWD IV term structure、gross gamma proxy、近期成交、各字段 provenance/freshness/availability。
4. `EventCalendar.v1` / `EventStudy.v1`
   - source/revision/as-of、事件重叠标签、T±窗口、独立样本数、priced move、realized move 分布、缺失原因。
5. `Explanation.v1`
   - 只引用 `AnalysisRecord` 已存在字段与 evidence IDs；LLM/模板输出不得创建数值、改变排序或提升准入状态。

## 实施顺序

### Phase 0 — 来源与契约冻结

- 固定每个参考仓库的 commit SHA、许可证和可参考文件清单。
- 对 MIT 项目即使只借鉴，也保留来源记录；无许可证项目只读不复制。
- 为 WS、SABR、skew、term structure、event study 建 golden fixtures 和失败路径测试。

### Phase 1 — 持续市场证据（最高优先级）

- 扩展现有市场 sidecar，产出 append-only `MarketEvent.v1` 与周期 snapshot manifest。
- REST 只做 bootstrap/resync；WS 负责 ticker/book/trades/DVOL。
- 验收：断线、乱序、重复、漏序、schema drift、局部 stale、重订阅失败全部 fail closed；同一 event log + clock 生成相同 hash。

### Phase 2 — 模型可替换与异常对照

- 抽出 `SurfaceModel` 接口；保留现有二次拟合，新增 `sabr_experimental`。
- 增加 bid/ask/mark 分拟合、模型分歧、残差稳定性和 no-arb 检查。
- SABR 在 oracle、跨初值、跨快照稳定性和 OOS 信号验证通过前，只展示，不排名。

### Phase 3 — 市场上下文面板

- 在现有 React 工作台新增 Skew/期限结构/成交/Gamma proxy 视图，不嵌入上游 Vanilla JS 页面。
- 复用现有 report selectors、可视化 token、reason code 和 freshness banner。

### Phase 4 — 事件波动率研究

- 接入有版本和来源的事件日历；先只显示事件上下文。
- 生成 BTC/DVOL 的 T±1/3/7 研究，以及 ATM straddle priced move vs 历史条件分布。
- 只有预注册、独立样本和 OOS 验证通过后，事件信号才可进入现有 `signal_validation`；否则恒为 `exploratory`。

### Phase 5 — 可选 Labs

- `/labs/greeks`：用后端 golden vectors 锁定单位和公式，前端只负责交互。
- `/labs/scenario`：用户选择观点/期限后比较多个有限风险结构；不输出张数，不自动推荐一个“最佳”。
- 可选解释器只消费 immutable report，失败或未配置时不影响报告。

### Phase 6 — Optimal Transport 离线研究

- 等待连续、可回放的 BTC 曲面历史足够后，再研究 SVI → 风险中性密度、物理分布与 W1/W2。
- 单独依赖环境、固定随机种子、walk-forward/OOS、交易成本和子样本稳健性完成前，不进入产品评分。

## 不可妥协的验收门槛

- 不引入任何订单 API、API key 输入、测试网按钮或执行模块；`execution_allowed=false` 保持不变。
- 核心 Python 包继续零运行时依赖；WebSocket/数值重依赖若批准，只能存在于隔离 sidecar 或离线 research extra。
- 跨合约曲面必须声明共同观察窗口和每个点的 freshness；“收到任意一个 ticker”不能证明整条链新鲜。
- 公开 OI 不得推断 dealer long/short；Gamma 图必须在标题、schema 和解释中声明 proxy/assumption。
- 宏观日历缺失是 `not_collected/unknown`，不能当作“无事件”。
- 新模型、新信号和 LLM 解释均不得绕过已有 evidence、replay、pre-registration 和 fail-closed 门禁。
- 任何复制代码/素材的提议必须先有精确许可证、版权归属、NOTICE 和依赖审查；缺许可证默认不复制。

## 最终优先级

1. `options-eye` 的问题域：**WS 证据链优先，SABR 次之；代码重写**。
2. `icefire-options-workbench`：**Skew/期限结构/成交 UI；Gamma 口径重做**。
3. `event-volatility-trading-lab` + `us-options-buyer-strategy`：**可信事件日历与 priced-vs-realized move**。
4. `crypto-options-strategy-assistant`：**仅策略 grammar/场景交互/受限解释**。
5. `greeks-lab`：**独立教育页，clean-room**。
6. `vol-surface-opt-trans`：**长期离线研究**。
7. DDH、美股完整产品、占星、盲盒、MBTI：**不进入当前核心路线**。
