# 加密货币期权卖Call收租系统 — 技术规格文档 (Spec)

版本: v0.1 draft
日期: 2026-07-07
作者: Kiro (综合用户策略描述 + 内部调研 workflow + 外部方案审阅)

---

## 0. 背景与目标

用户的核心策略假设："在熊市/弱反弹环境中，持续卖出深度虚值 Call 收权利金，是一个低回撤、正期望的现金流策略；只要该策略仍能稳定盈利，就说明熊市尚未结束。" 2019年至今两轮牛熊回测显示该策略在2022年熊市中表现最强，在2023-2025年慢牛/急拉行情中经受最大考验但仍维持正收益。

用户诉求：不再凭直觉判断"该卖哪个到期日/哪个Delta/哪个执行价的Call"，而是构建一个数据驱动的决策工具，用真实市场数据（IV、skew、期限结构、regime信号）评估当前定价是否合理，并给出具体可执行的选券建议。

本文档目标：给出该系统的完整技术方案，包括产品形态、数据管道、regime分类器、定价/选券评分引擎、风险管理框架、回测改进方案，以及分阶段落地路径。

**重要边界声明**：本系统输出的是研究和决策支持信号，不是自动化交易指令。所有阈值、权重、regime边界在初始版本中均为经验估计，必须用用户已有的历史回测数据做校准和walk-forward验证后才能作为实盘参考。

---

## 1. 产品形态：分层架构，非单一选择

不在 "Chrome插件 / Web应用 / CLI" 之间三选一，而是按依赖顺序分层：

| 层级 | 形态 | 优先级 | 理由 |
|---|---|---|---|
| L1 数据与评分引擎 | Python 后端服务/脚本 + 定时任务 | P0，必须最先做 | 需要7×24小时稳定采集（DVOL无历史API，需自行每日攒），不能依赖浏览器是否打开 |
| L2 可视化 | 本地 Dashboard（Streamlit/Gradio 起步） | P1 | vol surface、regime时间序列、候选期权排名表用图表看，文本报告不够直观 |
| L3 对话式查询 | Kiro skill 封装 | P2，可选 | 复用 L1 引擎，提供"现在该卖哪个"的自然语言接口 |
| L4 下单页面增强 | Chrome 插件 | P3，最后做 | 在 Deribit 原生页面叠加评分标签，是 L1 API 的薄客户端，无独立价值 |

L1 是唯一的核心资产。L2-L4 都是 L1 的呈现层，可以并行或按需推迟。

---

## 2. 市场机制基础（约束条件）

系统设计必须遵守以下已核实的交易所机制：

- **合约类型**：Deribit 主力是 inverse（币本位）合约：strike 美元计价，premium/保证金/盈亏以 BTC/ETH 结算；也有 USDC 结算的 linear 期权。欧式行权，到期现金结算，结算价取 index 在到期日 08:00 UTC（daily/weekly/monthly）或对应到期时点的数值。
- **inverse 合约的顺周期性风险**：裸卖 Call 最怕标的上涨，而 inverse 合约保证金本身随币价上涨"美元贬值"，双重不利。**系统必须支持同时计算币本位 PnL 和美元 PnL**，且优先建议 USDC 结算品种用于该策略。
- **到期节奏**：daily / weekly / monthly / quarterly。流动性集中在当月/当季档。
- **Delta 惯例**：0.1 delta 不对应固定的虚值百分比，由当天 IV 水平和剩余期限共同决定。**选券引擎计算行权价距离时必须使用当天实际拟合的 vol surface，禁止假设 flat vol**（flat vol 假设会在 put skew 占优、call翼IV更低的市场中系统性低估真实的距离风险——同样 0.1 delta 对应的行权价会比 flat-vol 算出来的更靠近现价，风险比看起来更高）。
- **保证金机制**：Standard 模式按现价百分比 + mark price 计算 IM/MM；Portfolio Margin 用价格/vol冲击的压力测试网格，但超出情景假设的行情会导致保证金被低估，不能作为唯一风控依据。
- **手续费与结算细节**（需在回测引擎中还原）：Deribit BTC 期权交易费约 0.03% underlying（约 0.0003 BTC/张），封顶为权利金的 12.5%；到期交割价基于结算窗口前 30 分钟 TWAP；07:30-08:00 UTC 结算窗口前不宜开新的短期到期仓位。

---

## 3. 数据层设计

### 3.1 数据源

- **实时/近实时**：Deribit Public API
  - `get_book_summary_by_currency`（BTC/ETH, kind=option）：全市场期权链快照，含 bid/ask/mark/mark_iv/OI/volume
  - `ticker` / `get_order_book`：单合约 best bid/ask、Greeks（Black-Scholes Delta/Gamma/Theta/Vega/Rho）、bid_iv/ask_iv/mark_iv
  - `get_index_price`：现货指数价格
  - `get_historical_volatility`：仅返回已实现波动率，**不能替代 DVOL 历史**
- **历史数据冷启动**（解决 DVOL/IV surface 无长历史 API 的问题）：
  - Amberdata：Deribit 期权/期货历史 tick、order book、Greeks、IV term structure、skew、DVOL、realized vol
  - CryptoDataDownload：Deribit BTC/ETH 期权 OHLCV（按到期日组织）、DVOL 历史
  - 建议直接采购/拉取以上数据源做半年至一年的历史回补，而非从今天起自行攒数据等待半年

### 3.2 采集频率

- 期权链快照：建议每 15-30 分钟一次（MVP），后续视延迟需求提升到分钟级或 WebSocket 订阅
- DVOL 快照：每日至少一次（因无历史 API，必须自行持续攒）；同时用 Amberdata/CDD 回补历史
- 现货价格与 regime 特征：每日收盘 + 日内可选高频更新

### 3.3 数据库 Schema

```
option_chain_snapshot
- ts, venue, currency, instrument_name, expiry, dte, strike, option_type
- bid, ask, mid, mark_price, bid_iv, ask_iv, mark_iv
- underlying_price, underlying_index, open_interest, volume_24h

option_greeks_snapshot
- ts, instrument_name, delta, gamma, theta, vega, rho

vol_surface
- ts, currency, tenor, delta_bucket, fitted_iv, atm_iv
- call_10d_iv, put_10d_iv, rr_25d, rr_10d, svi_params

regime_features
- ts, spot_return_1d/7d/30d, rv_7d/14d/30d, iv_rv_spread, dvol
- funding, futures_basis, trend_score, squeeze_score, event_score

candidate_scores
- ts, instrument_name, action, score, ev, p_itm, p_touch, cvar
- margin_required, suggested_size, exit_rule
```

---

## 4. Regime 分类器

### 4.1 为什么必须做

用户自述的四阶段历史表现（2021前熊市末期盈亏平衡 / 2021牛市急拉阶段性回撤但IV高恢复快 / 2022熊市爆发盈利 / 2023-2025慢牛多次大回撤但靠22年利润垫维持正收益）说明：**同一套机械规则（固定卖0.1 delta）在不同regime下的风险收益比差异巨大**。regime分类器是把这四阶段的直觉判断转成可复现、可实时判断的量化逻辑，是本系统区别于"随便设个delta阈值"的核心价值所在。

### 4.2 初始量化边界（草案，需用历史数据校准）

| Regime | 判断条件（初始草案） | 卖Call策略调整 |
|---|---|---|
| Bear Trend | 现价 < 200日均线，且20日价格斜率 < 0，funding rate ≤ 0 | 正常卖出，7-14D，0.1 delta附近 |
| Bear Squeeze Risk | 价格从明显支撑位反弹，空头拥挤（funding转正但价格仍<200日均线），IV处于低位 | 降低delta或暂停 |
| Range/Chop | 20日已实现波动率处于其自身历史分位30%以下 | 可卖7D，控制gamma |
| Slow Bull | 现价 > 200日均线，且滚动30天内单日涨幅最大的3天贡献当月涨幅50%以上 | 仅用spread结构或降至0.05-0.07 delta |
| Fast Bull/Breakout | 价格突破关键均线，funding显著转正，call skew由负转正 | 禁止裸卖Call |

**"滚动30天内最大3天贡献50%以上涨幅"这条规则专门用于捕捉用户描述的"慢牛上涨集中在很短时间"的现象**，需要用2023-2025样本重点验证阈值是否合理。

### 4.3 校准方法

用用户已有的2019-2025回测数据，反推验证：
1. 按上述规则给历史每一天打regime标签
2. 对比该标签序列与用户口头描述的四阶段时间边界是否吻合
3. 如不吻合，调整阈值（斜率窗口、分位数、贡献占比等），迭代到吻合为止
4. 同时统计各regime下机械卖0.1delta策略的实际表现分布，验证regime与"风险收益比"的相关性

---

## 5. 选券评分引擎

### 5.1 核心问题重述

不是"该卖哪个0.1 delta的Call"，而是：**在当前regime下，哪个到期日、哪个delta/执行价的Call，其可成交权利金高于对真实世界上行尾部损失的估计，且回撤、保证金、流动性都在预算内。**

### 5.2 候选筛选（预过滤）

```
候选池 = 期权链 中满足:
  option_type == "Call"
  dte ∈ [2, 35]
  delta ∈ [0.03, 0.15]
  open_interest >= 账户最小OI要求
  bid > 0
  (ask - bid) / mid <= 账户最大spread容忍度
```

### 5.3 核心指标

| 指标 | 定义 | 交易含义 |
|---|---|---|
| IV_RV_Edge | 当前bid IV − 期限匹配的RV预测 | 正值越大，卖方波动率溢价越厚 |
| VRP | bid_iv² − rv_forecast² | 方差风险溢价，理论基础指标 |
| Tail_EV | 真实世界分布下的期望payoff (S_T-K)+ | 决定EV是否为正 |
| P_ITM | 真实世界到期ITM概率（不能用delta替代） | 真实胜率估计 |
| P_Touch | 存续期内触碰执行价的概率 | 决定中途回撤/保证金压力，而非只看到期结果 |
| Premium/Margin | 权利金/占用保证金 | 资金效率 |
| Premium/CVaR | 权利金/尾部损失（99%置信区间条件期望损失） | 风险质量核心，比单纯收益率更重要 |
| BidAsk/Premium | 价差占权利金比例 | 深虚值期权最容易被手续费和滑点吃掉 |

### 5.4 真实世界分布估计

**MVP版本**（优先实现，避免过度设计）：
- 用当前regime标签，在历史数据中找同regime窗口，做经验分布bootstrap
- 不做EVT尾部厚化，先跑通全流程

**迭代版本**（MVP验证后再加）：
- regime-conditioned bootstrap + HAR/EWMA已实现波动率预测 + 跳跃/EVT尾部调整
- 用implied vol surface作为交叉校验锚点

### 5.5 行权价距离计算（关键修正点）

**禁止使用flat vol近似计算delta对应的行权价**。必须用当天实际的vol surface（按tenor和delta bucket插值拟合），因为BTC/ETH期权市场普遍存在put skew（虚值put比虚值call贵，call翼IV更低）。若用flat vol，会系统性高估call翼虚值程度，即低估真实的距离风险。

### 5.6 评分公式（初始草案，权重待校准）

```
Score = 25·z(EV) + 20·z(VRP) + 15·z(Carry) + 15·RegimeScore
        + 10·z(Liquidity) − 20·z(TailRisk) − 10·EventPenalty − 10·z(GammaRisk)
```

其中：
- EV = executable_credit − expected_payoff − fees − slippage
- Carry = theta_usd / margin_required
- RegimeScore：由第4节regime分类器给出的当前regime对"卖Call"策略的适配度打分
- EventPenalty：CPI/FOMC/NFP/ETF决议/大额解锁等事件窗口的惩罚项
- GammaRisk：normalize(gamma × underlying_price² / NAV)

**权重合理性声明**：25/20/15/15/10/-20/-10 这组系数目前没有实证依据，属于合理性排序的初始猜测（EV和VRP最重要，尾部风险惩罚最重）。**必须用walk-forward方法在历史数据上校准**，不能直接用于实盘决策。校准方法见第7节。

### 5.7 决策映射

| Score | 动作 |
|---|---|
| ≥ 75 | 正常仓位卖出 |
| 60-75 | 半仓，或改用call credit spread |
| 45-60 | 极小仓/观察 |
| < 45 | 不交易 |

### 5.8 Kill Condition（强制不交易，优先于分数）

- 实际bid IV 低于模型拟合的fair IV
- bid-ask spread 超过权利金的 15-25%
- 重大宏观/行业事件窗口内（CPI/FOMC/NFP/ETF决议/交易所异常）
- 当前regime被判定为 Fast Bull/Breakout
- 保证金压力已处于黄色/红色区间（见第6节）

---

## 6. 风险管理框架（组合层，独立于单笔评分）

评分引擎决定"这一笔该不该卖、卖多少"，风险框架决定"整个账户能承受多少"，**两者取更保守的结果执行**。

### 6.1 仓位规模（Sizing）

- 方向性风险预算 = NAV × 目标Delta敞口比例（常态5-8%）
- DVOL分层sizing系数：DVOL<40用1.0，40-70用0.7，70-100用0.4，>100用0.2或暂停
- 单一到期日敞口 ≤ 总敞口40%；单一执行价敞口 ≤ 总敞口25%
- 最终仓位 = min(评分引擎建议仓位, sizing规则上限, 杠杆系数上限)

### 6.2 保证金红绿灯

- 绿色：总Initial Margin占用 < NAV的30%
- 黄色：30-50%，禁止新开仓
- 红色：>50%，强制减仓至35%以下，当日不再开新仓
- Maintenance Margin buffer ratio（NAV/MM）< 1.5 视为强平边缘，无条件立即减仓，不等交易所触发
- inverse合约：因保证金顺周期性，杠杆系数在标准值基础上再打7折；建立"美元影子净值"监控，定期模拟标的+30%/+50%/+80%情景下的美元覆盖率

### 6.3 Roll规则

- DTE ≤ 7-14天且delta仍在10-25区间：主动roll到下一档到期
- delta从10-25跳升至35-40：roll up and out（买回当前仓位+卖出更高执行价更远到期）
- 已知事件（FOMC/CPI等）前2-3天，若到期日覆盖该事件：提前roll或减仓
- 同一批仓位单月roll超过2次：触发人工复盘，不再继续机械滚仓

### 6.4 Delta对冲（用永续合约）

- 组合净Delta > NAV的8-10%：用永续合约对冲回3-5%
- 标的单日涨幅超7-10%，或DVOL单日跳升超15-20点：不等精算完成，先对冲70-100%
- 对冲的资金费率成本纳入策略净收益核算，超过权利金收入20%需重新评估

### 6.5 尾部风险/熔断

- 单批次浮亏达NAV 3-5%：强制平仓该批次
- 账户回撤达最大可承受回撤(MDD cap)的50%：全局减仓50%
- 账户回撤达MDD cap的80%以上：全部平仓离场，暂停策略，人工复盘后才可重开
- 权利金收入固定拨出20-30%作为"尾部保护基金"，不计入可分配利润
- 保证金资产分散在2家以上交易所（参考FTX事件的交易对手风险）

---

## 7. 回测系统改进要求

用户已有2019年至今的回测系统，需在现有基础上补充以下能力，否则容易被"平均收益好、尾部一天归零"的假象误导：

1. **真实bid/ask成交**：卖出用bid，买保护腿用ask，平仓用不利边，而非用mid或mark
2. **手续费与封顶规则**：0.03% underlying/张，封顶权利金12.5%，深虚值小权利金时手续费占比会很高
3. **保证金路径模拟**：不只看到期盈亏，模拟中途mark-to-market和margin usage的时间序列
4. **触碰概率统计**：区分"到期归零"和"中途触碰导致强制减仓/保证金追缴"两种不同的实现路径
5. **事件过滤**：标记CPI/FOMC/NFP/ETF决议/大额清算窗口，单独统计事件期表现
6. **分regime统计**：不能只看全样本Sharpe，必须拆分Bear Trend/Bear Squeeze/Range/Slow Bull/Fast Bull五个regime下的独立表现
7. **Walk-forward验证**：建议用2019-2022训练regime边界和评分权重，2023-2024验证，2025-2026做真正的样本外测试；或滚动18-24个月训练+3个月验证
8. **压力测试**：+5%/+10%/+20%单日上行冲击；IV+10/+25 vol点冲击；模拟盘口消失只能用ask平仓的极端流动性场景

---

## 8. 执行规则（写死，不留自由发挥空间）

**入场**：
- 只对评分最高的前1-3个候选下单，不铺满整条链
- 优先用post-only limit单，避免意外吃单方吃到不利价格
- spread/mid ≤ 10-15%，深虚值可放宽但需在评分中扣分
- 扣除手续费后的净权利金需超过最小阈值，否则不值得卖
- 若0.1delta行权价低于明显技术阻力位，降低delta或换更远到期
- 事件窗口内不新开裸卖仓位

**止盈**：
- 权利金已兑现60-80%：平仓
- delta回落至0.02-0.03：平仓或滚动
- 剩余权利金 < 手续费+滑点的3-5倍：不再持有，提前离场

**止损/减仓**：
- delta升至0.25-0.30：减仓或转为spread结构
- mark价浮亏达初始权利金2-3倍：减仓
- 现货突破关键均线且funding/basis/call需求同步转强：强制降仓
- 结算窗口（07:30-08:00 UTC）前禁止开新的短到期仓位

---

## 9. 分阶段落地路径

| 阶段 | 内容 | 交付物 |
|---|---|---|
| 阶段1 | 数据管道：期权链定时快照 + DVOL每日自采 + Amberdata/CDD历史回补（先BTC，ETH第二批） | 可持续写入的数据库 |
| 阶段2 | Regime分类器：按4.2节初始边界实现，用历史数据校准阈值 | 每日regime标签时间序列，与用户口头四阶段描述对比验证 |
| 阶段3 | 简化版评分引擎：经验分布bootstrap + 等权重或粗略权重，CLI输出JSON报告 | 每次运行输出候选期权排名和action |
| 阶段4 | 回测引擎改造：接入第7节全部改进项，做walk-forward校准regime边界和评分权重 | 校准后的regime边界和评分权重，分regime表现报告 |
| 阶段5 | 本地Dashboard可视化 | vol surface图、regime时间线、候选排名表 |
| 阶段6 | Kiro skill封装 + Chrome插件 | 对话式查询接口 + Deribit页面标签叠加 |

---

## 10. 已知局限性与未决问题

- DVOL无官方历史API，冷启动依赖第三方数据源（Amberdata/CryptoDataDownload），需验证其历史数据与Deribit官方口径的一致性
- 当前市场快照数据仅来自Deribit单一交易所，未做跨所（OKX/Binance）交叉验证
- Regime分类边界和评分权重在校准前均为经验估计，不能直接用于实盘
- 真实世界分布估计的MVP版本（同regime历史bootstrap）在样本量不足的regime（如Fast Bull/Breakout历史样本较少）下可靠性存疑
- 系统假设用户能获取funding rate、期货基差等衍生品指标的实时数据源，这部分在初期调研中未能验证具体API可用性，需要在阶段1数据管道设计时专门核实
