# 加密货币期权卖 Call 收租系统 — 完整开发 Spec

版本：v1.0  
日期：2026-07-07  
状态：Engineering Spec / Research System Design  
适用范围：BTC/ETH 加密货币期权卖 Call 收租策略的研究、回测、选券、风控与半自动化执行支持  
非投资建议：本系统输出研究与决策支持信号，不是自动化交易指令；所有阈值、模型权重、regime 边界必须经过历史校准、walk-forward 验证和纸面交易验证后才可进入实盘。

---

## 1. 一句话定义

本系统不是"固定卖 0.1 Delta Call"的脚本，而是一个 **Regime-aware、Vol-surface-aware、Portfolio-risk-aware 的加密货币期权短 Call 决策系统**。

系统的核心任务是回答：

> 在当前市场状态、当前 IV/skew/term structure、当前账户风险预算和可成交盘口条件下，是否存在某个 Call 或 Call Credit Spread，其可成交权利金显著高于模型估计的真实世界上行尾部损失，并且组合层面的保证金、回撤、gamma、流动性风险可控？

系统最终输出：

```json
{
  "action": "SELL_CALL_SPREAD | SELL_NAKED_CALL | NO_TRADE",
  "currency": "BTC",
  "regime": "Bear Trend",
  "sell_leg": "BTC-14JUL26-69000-C",
  "buy_leg": "BTC-14JUL26-76000-C",
  "dte": 7,
  "sell_leg_delta": 0.084,
  "net_credit": 0.0018,
  "score": 78,
  "size": "0.8x_standard",
  "p_itm_physical": 0.071,
  "p_touch_physical": 0.183,
  "cvar_99_nav_pct": 0.46,
  "portfolio_risk_light": "GREEN",
  "entry_rule": "post_only_limit",
  "take_profit": "close_after_65pct_premium_capture",
  "risk_exit": "reduce_if_delta_gt_0.25_or_loss_gt_2.5x_credit",
  "reasons": [
    "Regime permits short call carry",
    "Bid IV exceeds fair physical IV after costs",
    "Strike is above hazard zone",
    "Spread structure caps breakout loss"
  ]
}
```

---

## 2. 背景与业务目标

### 2.1 策略背景

用户已在回测系统中拉取 2019 年以来两轮牛熊数据，并观察到：

1. 2021 年以前熊市末期，卖当周 0.1 Delta 末日虚值 Call 基本盈亏平衡。
2. 2021 年牛市快速拉升期间策略会出现回撤，但牛市高 IV 使利润恢复较快。
3. 2022 年熊市中该策略盈利能力很强，回撤较低。
4. 2023-2025 年慢牛行情中，涨幅往往集中在短时间内，策略遭遇多次较大回撤，但依靠 2022 年利润垫仍维持正收益。
5. 2025 年牛转熊后，策略再次出现类似 2022 年的爆发力。

这说明策略优势可能来自：

- 熊市/弱反弹中上行尾部实际发生概率低于市场或散户需求定价。
- 短期限 OTM Call 的 theta 周转快。
- 牛市初期/慢牛急拉期 short gamma 暴露会显著伤害策略。
- 机械卖 0.1 Delta 不足以穿越所有 regime。

### 2.2 产品目标

系统目标是把"熊市卖 Call 收租"的经验策略升级为可复现、可解释、可回测、可风控的决策工具：

- 判断当前是否适合卖 Call。
- 判断该裸卖还是做 Call Credit Spread。
- 判断哪个 DTE、哪个 Delta、哪个 Strike 最优。
- 判断当前权利金是否足以覆盖真实世界尾部风险、手续费、滑点、对冲成本和保证金占用。
- 给出可执行的候选合约、仓位、入场价、止盈、止损、roll、hedge 规则。
- 在 2023-2025 这类慢牛急拉环境中自动降仓、改 spread 或 no-trade。

### 2.3 非目标

MVP 阶段不做：

- 全自动实盘下单。
- 所有交易所全覆盖。
- 所有 altcoin 期权覆盖。
- 高频做市。
- 复杂机器学习黑箱信号。
- 无风控的裸卖 Call 杠杆放大。

---

## 3. 产品形态与分层架构

系统按依赖关系分为五层。

| 层级 | 名称 | 形态 | 优先级 | 说明 |
|---|---|---|---|---|
| L0 | 数据存储与配置 | Postgres/TimescaleDB + Parquet/DuckDB + YAML config | P0 | 全系统地基，负责数据落库、版本化、配置管理 |
| L1 | 数据与评分引擎 | Python 后端服务 + 定时任务 + CLI | P0 | 核心资产，所有决策逻辑在此实现 |
| L2 | 回测与校准引擎 | Python research package + reports | P0 | 校准 regime、评分权重、风控阈值 |
| L3 | Dashboard | Streamlit/Gradio/FastAPI frontend | P1 | 展示 vol surface、regime、候选排名、组合风险 |
| L4 | 对话与插件层 | Kiro skill / Chrome extension | P2/P3 | L1 的薄客户端；最后做 |

架构原则：

```text
Deribit / Historical Vendors / Account API
               |
               v
        Data Ingestion Layer
               |
               v
      Normalized Market Data Store
               |
               v
  Vol Surface + Regime + Pricing + Risk Engines
               |
               v
      Candidate Recommendation API
               |
       -----------------------
       |          |          |
      CLI     Dashboard   Chat/Plugin
```

L1 是唯一不可替代的核心。Dashboard、Kiro skill、Chrome 插件都只消费 L1 API，不重复实现逻辑。

---

## 4. 核心用户故事

### 4.1 每日决策

作为交易者，我希望每天看到：

- 当前 BTC/ETH 是否处于适合卖 Call 的 regime。
- 当前裸卖是否被允许，还是只能用 Call Spread。
- 当前最优的 1-3 个候选合约或组合。
- 每个候选的 EV、P_ITM、P_Touch、CVaR、保证金占用、score、推荐仓位。
- 明确的 no-trade 理由。

### 4.2 风控监控

作为交易者，我希望系统持续监控：

- 当前组合净 delta/gamma/vega。
- Initial Margin / NAV。
- NAV / Maintenance Margin。
- 单一到期、单一 strike、单一标的集中度。
- spot +5%/+10%/+20%/+30% 与 IV +10/+25 vol shock 下的压力亏损。
- 是否需要减仓、roll、hedge 或停机。

### 4.3 回测与校准

作为策略研究者，我希望比较：

- 固定 7D 0.1 Delta 卖 Call baseline。
- 只加 regime gating 的版本。
- 只加定价/EV 评分的版本。
- 完整系统版本。

系统必须说明完整系统是否真的降低 2023-2025 慢牛急拉阶段的回撤。

### 4.4 半自动执行

作为执行者，我希望系统生成：

- 推荐订单。
- post-only limit 价格。
- 最大成交数量。
- 若未成交，如何改价或取消。
- 成交后的止盈/止损/roll 监控规则。

MVP 只生成建议，不自动下单。

---

## 5. 市场机制与产品约束

### 5.1 支持产品

MVP 阶段：

```yaml
universe:
  primary: BTC
  secondary: ETH
  venue: Deribit
  products:
    preferred: USDC_LINEAR_OPTIONS
    fallback: INVERSE_OPTIONS_WITH_USD_SHADOW_NAV
  structures:
    - naked_short_call
    - call_credit_spread
```

优先使用 BTC，ETH 第二阶段加入。SOL/XRP/其他 alt options 不进入 MVP。

### 5.2 USDC linear options

用于 USD/USDC 计价账户时，优先使用 USDC linear options：

- 期权为欧式。
- 价格与结算以 USDC 进行。
- 到期 ITM 的处理可能涉及先结算进对应 futures，再现金结算，但经济结果等价于现金结算。

系统要求：

```text
若 USDC linear options 的 bid/ask、OI、depth 达标：
    优先使用 USDC linear
否则：
    可使用 inverse，但必须启用 USD shadow NAV 风控
```

### 5.3 Inverse options

Inverse options 的 premium、保证金和 PnL 以 BTC/ETH 计价。裸卖 Call 在 inverse 模式下有两个风险：

1. 标的上涨导致 short call 内在损失扩大。
2. 币本位保证金和 PnL 在美元维度下剧烈变化，容易掩盖真实 USD 回撤。

系统必须同时计算：

```text
coin_pnl
usd_pnl
coin_margin
usd_margin
coin_nav
usd_shadow_nav
usd_stress_loss
```

### 5.4 到期与结算窗口

系统必须内置以下执行约束：

- Daily/weekly/monthly/quarterly options 到期通常围绕 08:00 UTC。
- 到期交割价使用到期前 30 分钟 TWAP，即 07:30-08:00 UTC 窗口。
- 结算期间可能暂停撮合或拒绝新订单。
- 07:30-08:00 UTC 不开新的短到期 short gamma 仓位。

### 5.5 费用

回测和实盘估算必须逐笔扣除：

- Entry trading fee。
- Exit trading fee。
- Delivery fee，如持仓到期且涉及交割。
- Perp/future hedge fee。
- Funding cost。
- Slippage。

深虚值期权权利金很小时，手续费占权利金比例会显著影响 EV，不能忽略。

### 5.6 Delta 不是固定虚值百分比

系统硬规则：

> 禁止用 flat vol 估算 0.1 Delta 对应的 strike。必须基于当天实际 vol surface 计算 delta、distance、P_ITM、P_Touch 和 Greeks。

原因：BTC/ETH 期权经常存在 skew，call wing IV、put wing IV、ATM IV、期限结构不同。flat vol 会错误估计行权价距离和尾部风险。

---

## 6. 数据层设计

### 6.1 数据源

#### 6.1.1 实时/近实时 Deribit 数据

| 数据 | 接口/通道 | 用途 |
|---|---|---|
| 全链摘要 | `public/get_book_summary_by_currency` | 快速获取所有 instruments 的 OI、volume、best bid/ask、mark 等 |
| 单合约 ticker | `public/ticker` / WebSocket ticker | best bid/ask、mark、OI、Greeks、bid_iv/ask_iv/mark_iv |
| 盘口深度 | `public/get_order_book` | depth、可成交量、滑点估算 |
| 指数价格 | `public/get_index_price` / index channel | spot/index、结算、风险计算 |
| volatility index | `public/get_volatility_index_data` / websocket | DVOL 类指标、波动率 regime、sizing |
| mark price updates | `markprice.options` WebSocket | 持仓估值与 surface 更新 |

#### 6.1.2 历史数据

历史回测优先使用用户已有的 2019-2026 数据库。若缺口较大，按优先级补：

| 来源 | 用途 | 说明 |
|---|---|---|
| Tardis | 2019 起 Deribit options/futures tick、quote、markprice、DVOL 等 | 适合回补 2019 起完整链路 |
| Amberdata | options/futures historical data、greeks、surface、funding、OI | 适合标准化分析和机构级数据 |
| CryptoDataDownload | DVOL、OHLCV、基础历史数据 | 可作为辅助与交叉验证 |
| 自建采集 | 从系统上线日起持续全链快照 | 必须做，保证未来研究可持续 |

重要修正：不要再写"DVOL 完全没有官方历史 API"。Deribit 已有 volatility index candle API，可用于 volatility index 历史图表数据。但完整历史 option chain、历史 bid/ask、order book、mark IV surface 仍需第三方数据或自建长期采集。

### 6.2 采集频率

| 数据 | MVP 频率 | 生产建议 | 说明 |
|---|---:|---:|---|
| option chain snapshot | 15 分钟 | 1-5 分钟 + WebSocket | 候选扫描与 surface 拟合 |
| selected order book | 1 分钟 | 实时 | 对候选和持仓重点跟踪 |
| volatility index | 15 分钟/每日 | 实时 + candle | regime 与 sizing |
| spot/index | 1 分钟 | 实时 | risk 与 trigger |
| futures basis/funding | 5-15 分钟 | 实时/交易所更新 | squeeze、对冲成本 |
| account risk | 30 秒 | 5-15 秒 | 实盘风控 |
| event calendar | 每日 | 每日 + 手动确认 | 宏观/监管/ETF/交易所事件 |

### 6.3 数据质量要求

任何实盘或半实盘推荐前必须通过数据质量门槛：

```text
market_data_age <= 60 seconds
account_data_age <= 30 seconds
best_bid <= mid <= best_ask
ask > bid
mark_iv > 0
bid_iv >= 0
expiry > now
strike > 0
underlying_price > 0
no duplicate instrument snapshot for same ts
surface_fit_quality >= threshold
```

数据不达标时输出：

```json
{"action": "NO_TRADE", "reason": "DATA_STALE_OR_INVALID"}
```

### 6.4 数据库 Schema

建议使用 Postgres/TimescaleDB 存近期结构化数据，Parquet/DuckDB 存大规模历史研究数据。

#### 6.4.1 option_chain_snapshot

```sql
CREATE TABLE option_chain_snapshot (
    ts TIMESTAMPTZ NOT NULL,
    venue TEXT NOT NULL,
    currency TEXT NOT NULL,
    settlement_currency TEXT,
    instrument_name TEXT NOT NULL,
    expiry TIMESTAMPTZ NOT NULL,
    dte DOUBLE PRECISION NOT NULL,
    strike DOUBLE PRECISION NOT NULL,
    option_type TEXT NOT NULL,
    bid DOUBLE PRECISION,
    ask DOUBLE PRECISION,
    mid DOUBLE PRECISION,
    mark_price DOUBLE PRECISION,
    bid_iv DOUBLE PRECISION,
    ask_iv DOUBLE PRECISION,
    mark_iv DOUBLE PRECISION,
    model_iv DOUBLE PRECISION,
    underlying_price DOUBLE PRECISION,
    underlying_index TEXT,
    open_interest DOUBLE PRECISION,
    volume_24h DOUBLE PRECISION,
    depth_bid_1 DOUBLE PRECISION,
    depth_ask_1 DOUBLE PRECISION,
    depth_bid_5 DOUBLE PRECISION,
    depth_ask_5 DOUBLE PRECISION,
    raw JSONB,
    PRIMARY KEY (ts, venue, instrument_name)
);
```

#### 6.4.2 option_greeks_snapshot

```sql
CREATE TABLE option_greeks_snapshot (
    ts TIMESTAMPTZ NOT NULL,
    instrument_name TEXT NOT NULL,
    exchange_delta DOUBLE PRECISION,
    exchange_gamma DOUBLE PRECISION,
    exchange_theta DOUBLE PRECISION,
    exchange_vega DOUBLE PRECISION,
    exchange_rho DOUBLE PRECISION,
    model_delta DOUBLE PRECISION,
    model_gamma DOUBLE PRECISION,
    model_theta DOUBLE PRECISION,
    model_vega DOUBLE PRECISION,
    model_rho DOUBLE PRECISION,
    PRIMARY KEY (ts, instrument_name)
);
```

#### 6.4.3 vol_surface_snapshot

```sql
CREATE TABLE vol_surface_snapshot (
    ts TIMESTAMPTZ NOT NULL,
    currency TEXT NOT NULL,
    settlement_currency TEXT,
    expiry TIMESTAMPTZ NOT NULL,
    tenor_days DOUBLE PRECISION NOT NULL,
    delta_bucket DOUBLE PRECISION,
    strike DOUBLE PRECISION,
    fitted_iv DOUBLE PRECISION,
    bid_iv DOUBLE PRECISION,
    ask_iv DOUBLE PRECISION,
    atm_iv DOUBLE PRECISION,
    rr_25d DOUBLE PRECISION,
    rr_10d DOUBLE PRECISION,
    bf_25d DOUBLE PRECISION,
    bf_10d DOUBLE PRECISION,
    svi_a DOUBLE PRECISION,
    svi_b DOUBLE PRECISION,
    svi_rho DOUBLE PRECISION,
    svi_m DOUBLE PRECISION,
    svi_sigma DOUBLE PRECISION,
    no_arb_error DOUBLE PRECISION,
    fit_quality_score DOUBLE PRECISION,
    PRIMARY KEY (ts, currency, expiry, strike)
);
```

#### 6.4.4 regime_features

```sql
CREATE TABLE regime_features (
    ts TIMESTAMPTZ PRIMARY KEY,
    currency TEXT NOT NULL,
    spot DOUBLE PRECISION,
    return_1d DOUBLE PRECISION,
    return_7d DOUBLE PRECISION,
    return_30d DOUBLE PRECISION,
    rv_7d DOUBLE PRECISION,
    rv_14d DOUBLE PRECISION,
    rv_30d DOUBLE PRECISION,
    iv_rv_spread_7d DOUBLE PRECISION,
    dvol DOUBLE PRECISION,
    dvol_percentile DOUBLE PRECISION,
    term_structure_slope DOUBLE PRECISION,
    funding_8h DOUBLE PRECISION,
    futures_basis_7d DOUBLE PRECISION,
    futures_basis_30d DOUBLE PRECISION,
    call_put_volume_ratio DOUBLE PRECISION,
    call_put_oi_ratio DOUBLE PRECISION,
    rr_25d DOUBLE PRECISION,
    rr_10d DOUBLE PRECISION,
    trend_score DOUBLE PRECISION,
    squeeze_score DOUBLE PRECISION,
    breakout_score DOUBLE PRECISION,
    event_score DOUBLE PRECISION,
    primary_regime TEXT,
    regime_confidence DOUBLE PRECISION
);
```

#### 6.4.5 candidate_scores

```sql
CREATE TABLE candidate_scores (
    ts TIMESTAMPTZ NOT NULL,
    currency TEXT NOT NULL,
    structure_type TEXT NOT NULL,
    sell_leg TEXT NOT NULL,
    buy_leg TEXT,
    score DOUBLE PRECISION,
    action TEXT NOT NULL,
    ev_after_cost DOUBLE PRECISION,
    premium DOUBLE PRECISION,
    fair_value_physical DOUBLE PRECISION,
    fair_value_risk_neutral DOUBLE PRECISION,
    p_itm DOUBLE PRECISION,
    p_touch DOUBLE PRECISION,
    cvar_95 DOUBLE PRECISION,
    cvar_99 DOUBLE PRECISION,
    stress_loss_nav_pct DOUBLE PRECISION,
    margin_required DOUBLE PRECISION,
    suggested_size DOUBLE PRECISION,
    reason_codes TEXT[],
    raw JSONB,
    PRIMARY KEY (ts, structure_type, sell_leg, COALESCE(buy_leg, ''))
);
```

#### 6.4.6 portfolio_risk_snapshot

```sql
CREATE TABLE portfolio_risk_snapshot (
    ts TIMESTAMPTZ PRIMARY KEY,
    nav_usd DOUBLE PRECISION,
    nav_coin DOUBLE PRECISION,
    initial_margin DOUBLE PRECISION,
    maintenance_margin DOUBLE PRECISION,
    margin_usage DOUBLE PRECISION,
    nav_to_mm DOUBLE PRECISION,
    net_delta_usd DOUBLE PRECISION,
    net_gamma_usd DOUBLE PRECISION,
    net_vega_usd DOUBLE PRECISION,
    short_call_notional DOUBLE PRECISION,
    expiry_concentration JSONB,
    strike_concentration JSONB,
    stress_up_5 DOUBLE PRECISION,
    stress_up_10 DOUBLE PRECISION,
    stress_up_20 DOUBLE PRECISION,
    stress_up_30 DOUBLE PRECISION,
    stress_iv_up_10vol DOUBLE PRECISION,
    stress_iv_up_25vol DOUBLE PRECISION,
    risk_light TEXT
);
```

#### 6.4.7 execution_log

```sql
CREATE TABLE execution_log (
    ts TIMESTAMPTZ NOT NULL,
    order_id TEXT,
    instrument_name TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT,
    post_only BOOLEAN,
    limit_price DOUBLE PRECISION,
    filled_price DOUBLE PRECISION,
    filled_size DOUBLE PRECISION,
    bid_at_submit DOUBLE PRECISION,
    ask_at_submit DOUBLE PRECISION,
    mark_at_submit DOUBLE PRECISION,
    fee DOUBLE PRECISION,
    slippage DOUBLE PRECISION,
    reason_code TEXT,
    raw JSONB,
    PRIMARY KEY (ts, order_id)
);
```

---

## 7. Vol Surface 与 Greeks 模块

### 7.1 目标

将交易所原始报价转成一致、可插值、可风控的波动率曲面，并用该曲面重新计算模型 Greeks。

### 7.2 输入

- option_chain_snapshot。
- bid/ask/mark_iv。
- underlying price/index price。
- expiry、strike、option type。
- 利率/借贷成本，可先用 0 或稳定币利率近似。

### 7.3 过滤规则

```text
过滤报价：
- bid <= 0 且 ask 也无效
- ask <= bid
- spread / mid > max_spread_threshold
- dte < min_dte_for_surface
- open_interest 太低且没有盘口深度
- mark_iv <= 0
- 明显离群 IV
```

### 7.4 拟合方法

MVP：

- 按 expiry 分组。
- 使用 OTM calls、OTM puts、ATM 附近双边报价。
- 对 delta bucket 或 log-moneyness 做平滑插值。
- 输出 ATM IV、10D/25D risk reversal、butterfly、term structure。

生产版：

- 使用 SVI 或 SABR。
- 做 no-arbitrage 检查。
- calendar arbitrage 检查。
- butterfly arbitrage 检查。
- 输出 fit_quality_score。

### 7.5 Greeks

系统保留两套 Greeks：

```text
exchange_greeks:
    Deribit ticker 返回值，用于对齐交易所界面和账户风控

model_greeks:
    使用自拟合 surface 重新计算，用于评分、压力测试和策略判断
```

评分逻辑优先使用 model Greeks，但展示时同时显示 exchange Greeks。

---

## 8. Regime 分类器

### 8.1 目标

将市场状态映射为策略权限：是否能卖 Call、是否能裸卖、是否必须做 spread、仓位乘数是多少。

输出：

```json
{
  "primary_regime": "Bear Trend",
  "regime_confidence": 0.73,
  "sell_call_permission": 1.0,
  "naked_call_permission": true,
  "spread_required": false,
  "size_multiplier": 1.0,
  "squeeze_score": 0.22,
  "breakout_score": 0.18,
  "event_score": 0.10
}
```

### 8.2 Regime 类型

| Regime | 定义 | 策略动作 |
|---|---|---|
| Bear Trend | 价格低于长期趋势，反弹乏力，funding 中性/负，call demand 弱 | 允许 7-14D 0.08-0.15 Delta 裸卖或 spread |
| Late Bear / Exhaustion | 熊市末期低位震荡，IV 低，反弹风险上升 | 降 delta，优先 14D 或 spread |
| Bear Squeeze Risk | 支撑位强反弹，空头拥挤，funding/OI 上升 | 禁止大仓裸卖，只允许小仓 spread 或 no-trade |
| Range / Chop | 横盘，RV 低于 IV，趋势不强 | 允许 7D，但控制 gamma 和事件风险 |
| Slow Bull | 价格在 200D 上方，涨幅集中在少数天 | 禁止裸卖，只允许远 OTM spread 或 no-trade |
| Fast Bull / Breakout | 突破关键均线/前高，funding 和 call skew 转强 | 禁止新开 short call |
| Event Regime | 宏观/监管/ETF/交易所事件窗口 | 禁止短期限裸卖，已持仓减仓或转 spread |

### 8.3 特征工程

| 模块 | 特征 | 作用 |
|---|---|---|
| 趋势 | price vs 50D/100D/200D MA、MA slope、ATH drawdown | 判断牛熊结构 |
| 动量 | return 1D/7D/30D、breakout days、涨幅集中度 | 捕捉急拉风险 |
| 波动 | RV 7/14/30、DVOL、ATM IV percentile、IV/RV | 判断卖波动补偿 |
| skew | 10D/25D RR、call wing IV、put wing IV | 判断上行需求 |
| 杠杆 | funding、basis、OI z-score、清算量 | 判断 squeeze 风险 |
| 期限结构 | front IV/back IV、term slope | 判断短 gamma 是否被充分补偿 |
| 事件 | CPI/FOMC/NFP、ETF、监管、交易所异常 | 控制跳跃风险 |
| 盘口 | spread、depth、quote stability | 判断可交易性 |

### 8.4 初始规则

```python
def classify_regime(features):
    trend_bear = (
        features.spot < features.ma_200 and
        features.ma_20_slope < 0 and
        features.funding_8h <= 0
    )

    slow_bull = (
        features.spot > features.ma_200 and
        features.top3_up_days_contribution_30d >= 0.50
    )

    fast_bull = (
        features.breaks_recent_high and
        features.funding_z > 1.0 and
        features.rr_25d > 0
    )

    squeeze = (
        features.rebound_from_support and
        features.funding_8h > 0 and
        features.spot < features.ma_200 and
        features.dvol_percentile < 0.35
    )

    if fast_bull:
        return Regime("Fast Bull / Breakout", sell=0.0, naked=False, spread=True, size=0.0)
    if squeeze:
        return Regime("Bear Squeeze Risk", sell=0.3, naked=False, spread=True, size=0.3)
    if slow_bull:
        return Regime("Slow Bull", sell=0.4, naked=False, spread=True, size=0.4)
    if trend_bear:
        return Regime("Bear Trend", sell=1.0, naked=True, spread=False, size=1.0)
    if features.rv_20d_percentile < 0.30:
        return Regime("Range / Chop", sell=0.75, naked=True, spread=False, size=0.75)
    return Regime("Neutral", sell=0.5, naked=False, spread=True, size=0.5)
```

### 8.5 校准方法

使用 2019-2026 历史数据：

1. 给每一天打初始 regime 标签。
2. 对照用户已知四阶段历史描述检查标签是否合理。
3. 统计每个 regime 中固定 7D 0.1 Delta short call 的收益、MDD、CVaR、touch 率、roll 失败率。
4. 用 grid search / Optuna 优化阈值，但必须设置稳健性约束，避免过拟合。
5. 采用 walk-forward：2019-2022 训练，2023-2024 验证，2025-2026 样本外；或滚动 24 个月训练、后 3 个月测试。

### 8.6 验收标准

- Regime 标签能大致复现历史四阶段。
- Slow Bull/Breakout 中 naked short call 权限显著降低。
- 分 regime 表现统计能解释策略主要利润和主要回撤来源。
- 2023-2025 回撤在引入 regime gating 后显著改善。

---

## 9. 候选生成模块

### 9.1 候选类型

系统生成两类候选：

```text
A. Naked Short Call
B. Call Credit Spread = Sell OTM Call + Buy further OTM Call same expiry
```

策略规则：

```text
Bear Trend / Range:
    可评估 Naked Short Call 和 Call Spread

Late Bear / Squeeze / Slow Bull:
    只评估 Call Spread 或极小仓远 OTM Naked Call

Fast Bull / Event:
    不生成新 short call 候选
```

### 9.2 预过滤

```python
def build_short_call_base(chain, account):
    return chain[
        (chain.option_type == "C") &
        (chain.dte.between(account.min_dte, account.max_dte)) &
        (chain.model_delta.between(0.03, 0.15)) &
        (chain.bid > 0) &
        (chain.open_interest >= account.min_oi) &
        (((chain.ask - chain.bid) / chain.mid) <= account.max_spread_mid)
    ]
```

默认参数：

```yaml
candidate_filter:
  min_dte: 2
  max_dte: 35
  primary_dte: [7, 14]
  max_spread_mid: 0.15
  max_spread_mid_deep_otm: 0.25
  min_open_interest_btc: 50
  min_open_interest_eth: 200
  min_bid: 0
```

### 9.3 DTE 规则

| DTE | 默认动作 | 说明 |
|---:|---|---|
| 0-1 | 禁用 | gamma 太高，只用于研究模式 |
| 2-4 | 小仓/特殊机会 | 需要 Bear Trend + IV edge 很厚 + event_score 很低 |
| 7 | 主力 | theta 足，gamma 尚可控 |
| 14 | 主力 | 当前 IV 偏低或 squeeze risk 偏高时优先 |
| 21-35 | spread/远阻力 | 不作为裸卖主力 |
| >35 | 禁用 | 不符合收租周转逻辑 |

### 9.4 Delta 规则

| Regime | Naked Call | Call Spread Sell Leg | Protection Buy Leg |
|---|---:|---:|---:|
| Bear Trend | 0.08-0.15 | 0.08-0.15 | 0.01-0.04 |
| Range / Chop | 0.07-0.12 | 0.07-0.12 | 0.01-0.04 |
| Late Bear | 0.05-0.10 小仓 | 0.05-0.10 | 0.01-0.04 |
| Bear Squeeze Risk | 禁止或 0.03-0.07 极小仓 | 0.05-0.10 | 0.01-0.04 |
| Slow Bull | 禁止 | 0.03-0.07 | 0.01-0.03 |
| Fast Bull / Breakout | 禁止 | 禁止新开 | - |

### 9.5 Hazard Zone 过滤

不能只看 Delta。系统必须计算危险区：

```text
hazard_zone_upper = max(
    recent_swing_high,
    ma_cluster_upper,
    high_volume_node_upper,
    implied_expected_move_upper,
    liquidation_cluster_upper,
    prior_breakdown_level
)
```

规则：

```text
if candidate.strike <= hazard_zone_upper + 0.5 * ATR_14:
    reject_or_penalize(candidate, reason="STRIKE_INSIDE_HAZARD_ZONE")
```

---

## 10. 定价与真实世界分布模块

### 10.1 核心公式

对 naked short call：

```text
EV = executable_credit - E_P[(S_T - K)+] - fees - slippage - hedge_cost
```

对 call credit spread：

```text
EV = net_credit - E_P[min(max(S_T - K_sell, 0), K_buy - K_sell)] - fees - slippage - hedge_cost
```

其中：

- `executable_credit` 必须用 bid 或保守可成交价。
- `net_credit` = sell_leg_bid - buy_leg_ask。
- `E_P` 是真实世界分布，不是风险中性分布。
- `fees/slippage/hedge_cost` 必须入账。

### 10.2 真实世界分布 MVP

MVP 用 regime-conditioned bootstrap：

```python
def estimate_physical_distribution_mvp(spot, dte, current_regime, historical_returns):
    sample = historical_returns[
        (historical_returns.regime == current_regime) &
        (historical_returns.horizon_days == dte)
    ]
    bootstrapped_returns = bootstrap(sample.forward_return, n=10000)
    terminal_prices = spot * np.exp(bootstrapped_returns)
    return EmpiricalDistribution(terminal_prices)
```

输出：

```text
expected_call_payoff
p_itm_physical
p_touch_physical
loss_2x_premium_probability
loss_3x_premium_probability
cvar_95
cvar_99
```

### 10.3 迭代版分布模型

生产版使用 ensemble：

```text
Model A: Regime-conditioned bootstrap
Model B: EWMA / HAR realized volatility forecast
Model C: Implied-vol anchored tail adjustment
Model D: Jump / EVT upside tail adjustment
```

组合：

```text
physical_distribution = wA*A + wB*B + wC*C + wD*D
```

权重通过 walk-forward 校准。

### 10.4 P_Touch 估计

P_Touch 比 P_ITM 更重要，因为 short call 经常到期归零，但中途触碰会造成巨大回撤或保证金压力。

MVP：

- 使用历史路径 bootstrap，统计存续期内是否触及 strike。

备选近似：

- Brownian bridge approximation。
- Monte Carlo path simulation。

输出：

```text
p_touch_by_expiry
expected_max_adverse_excursion
prob_delta_gt_0.25
prob_delta_gt_0.35
```

---

## 11. 评分引擎

### 11.1 指标

| 指标 | 定义 | 用途 |
|---|---|---|
| EV_after_cost | 扣费、滑点、对冲成本后的期望收益 | 正期望核心 |
| IV_RV_Edge | bid IV - forecast RV | 卖波动补偿 |
| VRP | bid_iv² - rv_forecast² | 方差风险溢价 |
| Carry | theta_usd / margin_required | 资金效率 |
| Premium/CVaR | premium / cvar_99 | 尾部补偿质量 |
| P_ITM | 到期 ITM 概率 | 胜率 |
| P_Touch | 存续期触碰概率 | 路径风险 |
| GammaRisk | gamma × spot² / NAV | 急拉风险 |
| LiquidityScore | spread、depth、OI、volume | 可执行性 |
| EventPenalty | 事件窗口惩罚 | 跳跃风险 |
| RegimePermission | regime 对卖 Call 的许可度 | 策略 gating |

### 11.2 评分公式

不直接用固定 100 分加权。先算 utility，再映射 0-100：

```python
utility = (
    w_ev       * z(ev_after_cost / margin_required)
  + w_vrp      * z(vrp)
  + w_carry    * z(theta_usd / margin_required)
  + w_premium  * z(premium / cvar_99)
  + w_distance * z(distance_to_hazard_zone)
  + w_liquidity* z(liquidity_score)
  + w_regime   * regime.sell_call_permission
  - w_tail     * z(cvar_99 / nav)
  - w_touch    * z(p_touch)
  - w_gamma    * z(gamma_risk)
  - w_event    * event_penalty
  - w_margin   * margin_penalty
)

score = 100 * sigmoid(utility)
```

初始权重：

```yaml
score_weights:
  w_ev: 1.50
  w_vrp: 1.20
  w_carry: 0.80
  w_premium: 1.20
  w_distance: 0.80
  w_liquidity: 0.70
  w_regime: 1.00
  w_tail: 1.80
  w_touch: 1.00
  w_gamma: 1.20
  w_event: 1.50
  w_margin: 2.00
```

这些权重是初始值，必须由历史数据校准。

### 11.3 决策映射

| Score | 动作 |
|---:|---|
| >= 80 | 标准仓位，可交易 |
| 65-80 | 半仓或必须 spread |
| 50-65 | 观察或极小仓，不建议裸卖 |
| < 50 | No Trade |

### 11.4 Kill Conditions

Kill condition 优先于 score：

```yaml
kill_conditions:
  - ev_after_cost <= 0
  - bid_iv <= fair_physical_iv
  - spread_mid > max_allowed
  - depth_available < 3x_order_size
  - regime == Fast_Bull_Breakout
  - event_score > 0.75
  - portfolio_risk_light in [YELLOW, RED]
  - nav_to_mm < 1.50
  - market_data_age > 60_seconds
  - account_data_age > 30_seconds
  - settlement_window_active
  - candidate_strike_inside_hazard_zone_and_not_spread
```

### 11.5 输出解释

每个候选必须有 reason_codes：

```text
POSITIVE_EV
HIGH_VRP
GOOD_PREMIUM_CVAR
REGIME_ALLOWED
LIQUIDITY_OK
STRIKE_ABOVE_HAZARD_ZONE
SPREAD_REQUIRED_BY_REGIME
REJECT_FAST_BULL
REJECT_EVENT_RISK
REJECT_LOW_IV_EDGE
REJECT_MARGIN_YELLOW
REJECT_WIDE_SPREAD
```

---

## 12. 组合风险模块

### 12.1 原则

评分引擎决定"这一笔值不值得做"。组合风控决定"账户能不能承受"。最终执行取更保守结果。

### 12.2 保证金红绿灯

```yaml
margin_lights:
  green:
    im_nav_max: 0.30
    nav_to_mm_min: 2.00
    action: allow_new_trades
  yellow:
    im_nav_min: 0.30
    im_nav_max: 0.50
    nav_to_mm_min: 1.50
    nav_to_mm_max: 2.00
    action: no_new_trades_only_reduce
  red:
    im_nav_min: 0.50
    nav_to_mm_max: 1.50
    action: force_reduce_and_stop_for_day
```

### 12.3 仓位大小

用 stress loss 反推仓位，不用主观"卖几张"：

```python
size_by_cvar = account.max_single_trade_loss_usd / max(candidate.cvar_99, 1e-9)
size_by_stress = account.max_single_trade_loss_usd / max(candidate.stress_loss_up20_iv25, 1e-9)
size_by_delta = account.max_delta_usd / max(abs(candidate.delta_usd), 1e-9)
size_by_margin = account.max_new_margin_usd / max(candidate.margin_per_contract, 1e-9)
size_by_liquidity = candidate.visible_depth * account.max_depth_fraction
size_by_score = score_to_size_cap(candidate.score)
size_by_regime = regime.size_multiplier

final_size = min(
    size_by_cvar,
    size_by_stress,
    size_by_delta,
    size_by_margin,
    size_by_liquidity,
    size_by_score
) * size_by_regime
```

默认风险预算：

```yaml
risk_budget:
  max_single_spread_loss_nav: 0.015
  max_single_naked_stress_loss_nav: 0.0075
  max_expiry_stress_loss_nav: 0.030
  max_portfolio_stress_loss_nav: 0.080
  max_net_delta_nav: 0.08
  target_net_delta_after_hedge_nav: 0.03
  max_expiry_concentration: 0.40
  max_strike_concentration: 0.25
  inverse_position_size_multiplier: 0.70
```

### 12.4 压力测试

每次推荐前计算：

```text
spot +5%, IV unchanged
spot +10%, IV +10 vol
spot +20%, IV +25 vol
spot +30%, IV +25 vol
liquidity exit at ask
funding cost shock
basis shock
```

### 12.5 Delta Hedge

规则：

```text
if net_delta_usd > 8-10% NAV:
    hedge with perp/future to 3-5% NAV

if spot_up_1d > 7-10% or dvol_jump > 15-20 vol:
    immediate hedge 70-100% of excess delta

if gamma_risk too high:
    do not rely only on perp hedge; reduce short call or buy protection call
```

Perp hedge 只能对冲一阶 delta，不能解决 short gamma。gamma 风险超标时优先减仓或买保护腿。

### 12.6 Roll 规则

```text
主动 roll:
- DTE <= 7 且 delta 仍在 0.10-0.25
- 已赚 50%+ 权利金但剩余 gamma 风险恶化

防守 roll:
- delta 0.25-0.35: 减半或 roll up/out
- delta 0.35-0.40: 强制转 spread 或平仓
- delta > 0.40: 不再 roll，当作止损

禁止:
- 同一批仓位单月 roll 超过 2 次
- roll 后 stress loss 更大
- roll 只是为了避免确认亏损
```

### 12.7 熔断

```yaml
circuit_breakers:
  batch_loss_nav_3pct:
    action: reduce_batch_50pct
  batch_loss_nav_5pct:
    action: close_batch
  strategy_mdd_50pct_of_cap:
    action: reduce_all_50pct
  strategy_mdd_80pct_of_cap:
    action: close_all_and_pause
  repeated_roll_failure_3_times:
    action: pause_and_review
  data_or_exchange_abnormal:
    action: no_new_trades
```

---

## 13. 执行规则

### 13.1 入场

```text
1. 只对评分最高的 1-3 个候选下单。
2. 默认 post-only limit；目的为控制成交价格和避免吃穿盘口，不假设期权有 maker fee 优惠。
3. 裸卖用 sell leg bid 或更优报价估算。
4. Spread 用 sell leg bid - buy leg ask 估算。
5. 净权利金必须大于手续费 + 滑点的 5 倍。
6. 价差过宽不交易。
7. 事件窗口内不新开裸卖仓位。
8. candidate strike 在 hazard zone 内时，降低 delta、换 14D、做 spread 或 no trade。
9. 07:30-08:00 UTC 结算窗口不新开短到期仓位。
```

### 13.2 止盈

```text
take_profit_1:
- 已赚初始权利金 60%
- 买回 50% 仓位

take_profit_2:
- 已赚初始权利金 80%
- 全部平仓

theta_exhaustion:
- 剩余权利金 < 交易成本 3-5 倍
- 提前平仓

delta_decay:
- short call delta < 0.02-0.03
- 平仓或滚动到新候选
```

### 13.3 止损

```text
soft_stop:
- delta > 0.25
- 或 mark loss > 2x initial credit
- 减仓或转 spread

hard_stop:
- delta > 0.35
- 或 mark loss > 3x initial credit
- 平仓或 roll up/out，但必须降低 stress loss

breakout_stop:
- price 突破关键阻力
- funding / basis / call skew 同时转强
- 立即降仓，不等下一次评分周期
```

### 13.4 订单状态机

```text
PROPOSED -> APPROVED -> SUBMITTED -> PARTIALLY_FILLED -> FILLED
                  |             |             |
                  v             v             v
              REJECTED       CANCELED      MANAGED
```

MVP 只到 `PROPOSED`，由人工执行。

---

## 14. 回测与校准引擎

### 14.1 回测原则

必须模拟真实可执行性，不能用 mark 或 mid 做乐观成交。

```text
开仓:
- naked short call: sell at bid
- call spread: sell leg at bid, buy leg at ask

平仓:
- buy back short leg at ask
- sell long protection leg at bid
```

### 14.2 必须记录的路径指标

```text
trade_id
entry_ts
exit_ts
structure_type
entry_bid_ask
exit_bid_ask
entry_fee
exit_fee
max_adverse_excursion
max_favorable_excursion
pnl_path
delta_path
gamma_path
vega_path
margin_usage_path
touch_event
forced_exit_event
roll_event
hedge_event
regime_at_entry
regime_at_exit
reason_codes
```

### 14.3 回测组别

必须比较四组：

| 组别 | 说明 |
|---|---|
| Baseline | 固定 7D 0.1 Delta short call |
| Regime Only | regime gating 调整 DTE/Delta/结构，不做 EV 定价 |
| Pricing Only | EV/评分选券，不做 regime gating |
| Full System | regime + pricing + portfolio risk + execution rules |

### 14.4 训练/验证/样本外

方案 A：

```text
2019-2022: 训练 regime 阈值和评分权重
2023-2024: 验证
2025-2026: 样本外
```

方案 B：

```text
rolling 24 months train
next 3 months validate/test
walk-forward through all history
```

### 14.5 评价指标

不能只看 Sharpe。

```text
CAGR
Max Drawdown
Calmar
Sortino
weekly worst loss
monthly worst loss
CVaR 95/99
margin call count
forced liquidation count
premium captured ratio
premium / cvar
profit by regime
loss by regime
roll success rate
hedge cost / premium income
days to recover
```

### 14.6 验收标准

Full System 必须满足：

- 在 2023-2025 慢牛急拉阶段显著降低 MDD 或 CVaR。
- 在 2022 Bear Trend 阶段不过度牺牲策略收益。
- 样本外表现优于 Baseline 的 Calmar 和 CVaR。
- 强平次数为 0。
- 事件窗口损失显著下降。

---

## 15. API 与接口 Spec

### 15.1 服务划分

```text
market_data_service
surface_service
regime_service
pricing_service
risk_service
recommendation_service
backtest_service
report_service
```

### 15.2 REST API

#### GET /health

```json
{
  "status": "ok",
  "market_data_age_sec": 12,
  "account_data_age_sec": 4,
  "database": "ok"
}
```

#### GET /v1/regime/current?currency=BTC

```json
{
  "currency": "BTC",
  "ts": "2026-07-07T08:00:00Z",
  "primary_regime": "Bear Trend",
  "confidence": 0.73,
  "sell_call_permission": 1.0,
  "naked_call_permission": true,
  "spread_required": false,
  "size_multiplier": 1.0,
  "scores": {
    "trend": 0.81,
    "squeeze": 0.22,
    "breakout": 0.18,
    "event": 0.10
  }
}
```

#### GET /v1/surface/current?currency=BTC

```json
{
  "currency": "BTC",
  "ts": "2026-07-07T08:00:00Z",
  "tenors": [
    {
      "dte": 7,
      "atm_iv": 0.36,
      "rr_25d": -0.02,
      "rr_10d": -0.04,
      "fit_quality_score": 0.94
    }
  ]
}
```

#### POST /v1/recommendation/scan

Request：

```json
{
  "currency": "BTC",
  "account_id": "research_default",
  "structures": ["naked_short_call", "call_credit_spread"],
  "mode": "research",
  "top_n": 5
}
```

Response：

```json
{
  "ts": "2026-07-07T08:00:00Z",
  "currency": "BTC",
  "portfolio_risk_light": "GREEN",
  "regime": {
    "primary": "Bear Trend",
    "sell_call_permission": 1.0,
    "naked_call_permission": true
  },
  "action": "SELL_CALL_SPREAD",
  "best": {
    "structure_type": "call_credit_spread",
    "sell_leg": "BTC-14JUL26-69000-C",
    "buy_leg": "BTC-14JUL26-76000-C",
    "score": 78.2,
    "net_credit": 0.0018,
    "ev_after_cost": 0.00042,
    "p_itm": 0.071,
    "p_touch": 0.183,
    "cvar_99_nav_pct": 0.46,
    "suggested_size": 1.0,
    "entry_rule": "post_only_limit"
  },
  "candidates": [],
  "no_trade_reasons": []
}
```

#### GET /v1/risk/current

```json
{
  "ts": "2026-07-07T08:00:00Z",
  "nav_usd": 100000,
  "initial_margin_nav_pct": 0.22,
  "nav_to_mm": 2.8,
  "risk_light": "GREEN",
  "net_delta_nav_pct": 0.04,
  "net_gamma_usd": -120000,
  "net_vega_usd": -8500,
  "stress": {
    "spot_up_10_iv_up_10": -1200,
    "spot_up_20_iv_up_25": -4800,
    "spot_up_30_iv_up_25": -9200
  }
}
```

### 15.3 CLI

```bash
# 拉取一次全链快照
python -m shortcall.data collect --currency BTC --kind option

# 拟合 vol surface
python -m shortcall.surface fit --currency BTC --ts latest

# 生成当前 regime
python -m shortcall.regime classify --currency BTC

# 扫描候选
python -m shortcall.recommend scan --currency BTC --top 5

# 跑回测
python -m shortcall.backtest run --config configs/backtest_2019_2026.yaml

# 生成报告
python -m shortcall.report build --run-id RUN_20260707_001
```

---

## 16. Dashboard Spec

### 16.1 页面结构

#### Page 1: Today Overview

展示：

- Current regime。
- Sell Call Permission。
- Naked Call Permission。
- Portfolio Risk Light。
- Top 5 Recommendations。
- No-trade reason。

#### Page 2: Vol Surface

展示：

- ATM IV by tenor。
- 10D/25D risk reversal。
- 10D/25D butterfly。
- Term structure。
- Call wing vs put wing。
- Today vs 7D average vs 30D average。

#### Page 3: Candidate Ranking

表格列：

```text
rank
structure
sell_leg
buy_leg
dte
strike
model_delta
bid
ask
bid_iv
fair_iv
ev_after_cost
p_itm
p_touch
premium_margin
premium_cvar
stress_loss_nav_pct
score
action
reason_codes
```

#### Page 4: Portfolio Risk

展示：

- NAV。
- IM/NAV。
- NAV/MM。
- Net Delta/Gamma/Vega。
- Expiry concentration。
- Strike concentration。
- Stress up 5/10/20/30。
- Risk light。

#### Page 5: Backtest Reports

展示：

- Baseline vs Full System。
- By regime PnL。
- MDD timeline。
- CVaR。
- 2023-2025 drawdown focus。
- Walk-forward summary。

---

## 17. 配置文件 Spec

```yaml
system:
  mode: research
  base_currency: USD
  timezone: UTC
  venue: deribit

universe:
  primary: BTC
  secondary: ETH
  enable_eth: false
  products:
    preferred: USDC_LINEAR_OPTIONS
    fallback: INVERSE_OPTIONS_WITH_USD_SHADOW_NAV

candidate_filter:
  min_dte: 2
  max_dte: 35
  primary_dte: [7, 14]
  disabled_dte: [0, 1]
  max_spread_mid: 0.15
  max_spread_mid_deep_otm: 0.25
  min_net_premium_to_cost: 5.0
  min_open_interest_btc: 50
  min_open_interest_eth: 200

regime:
  fast_bull_breakout_threshold: 0.70
  squeeze_threshold: 0.65
  event_threshold: 0.75
  slow_bull_top3_up_days_contribution: 0.50
  rv_low_percentile: 0.30

delta_bands:
  bear_trend_naked: [0.08, 0.15]
  range_naked: [0.07, 0.12]
  late_bear_naked: [0.05, 0.10]
  squeeze_spread_sell_leg: [0.05, 0.10]
  slow_bull_spread_sell_leg: [0.03, 0.07]
  protection_buy_leg: [0.01, 0.04]

score:
  full_size: 80
  half_size: 65
  observe: 50
  no_trade_below: 50
  weights:
    w_ev: 1.50
    w_vrp: 1.20
    w_carry: 0.80
    w_premium: 1.20
    w_distance: 0.80
    w_liquidity: 0.70
    w_regime: 1.00
    w_tail: 1.80
    w_touch: 1.00
    w_gamma: 1.20
    w_event: 1.50
    w_margin: 2.00

risk:
  green_im_nav_max: 0.30
  yellow_im_nav_max: 0.50
  red_im_nav_min: 0.50
  min_nav_to_mm: 1.50
  max_single_spread_loss_nav: 0.015
  max_single_naked_stress_loss_nav: 0.0075
  max_expiry_stress_loss_nav: 0.03
  max_portfolio_stress_loss_nav: 0.08
  max_net_delta_nav: 0.08
  target_net_delta_after_hedge_nav: 0.03
  max_expiry_concentration: 0.40
  max_strike_concentration: 0.25
  inverse_position_size_multiplier: 0.70

execution:
  order_type: POST_ONLY_LIMIT
  top_n_candidates: 3
  settlement_no_trade_window_utc: "07:30-08:00"
  take_profit_pct_1: 0.60
  take_profit_pct_2: 0.80
  soft_stop_delta: 0.25
  hard_stop_delta: 0.35
  soft_stop_loss_multiple: 2.0
  hard_stop_loss_multiple: 3.0

kill_conditions:
  ev_after_cost_lte_zero: true
  bid_iv_lte_fair_physical_iv: true
  fast_bull_breakout_score_gt: 0.70
  event_score_gt: 0.75
  no_trade_if_risk_light: [YELLOW, RED]
  nav_to_mm_lt: 1.50
  data_stale: true
  insufficient_depth: true
```

---

## 18. 代码结构建议

```text
shortcall-system/
  README.md
  pyproject.toml
  configs/
    default.yaml
    research.yaml
    backtest_2019_2026.yaml
  shortcall/
    __init__.py
    common/
      types.py
      config.py
      logging.py
      time.py
    data/
      deribit_client.py
      collectors.py
      normalizers.py
      validators.py
      storage.py
    surface/
      filters.py
      fitter.py
      svi.py
      greeks.py
      no_arb.py
    regime/
      features.py
      classifier.py
      calibration.py
    pricing/
      physical_distribution.py
      payoff.py
      ev.py
      touch_probability.py
    scoring/
      candidates.py
      score.py
      reasons.py
      kill_conditions.py
    risk/
      portfolio.py
      margin.py
      stress.py
      sizing.py
      hedge.py
      circuit_breakers.py
    execution/
      orders.py
      state_machine.py
      post_only.py
      logs.py
    backtest/
      simulator.py
      fills.py
      fees.py
      walk_forward.py
      metrics.py
      reports.py
    api/
      main.py
      routes_regime.py
      routes_surface.py
      routes_recommendation.py
      routes_risk.py
    dashboard/
      app.py
      pages/
    tests/
      unit/
      integration/
      regression/
  notebooks/
    calibration.ipynb
    surface_debug.ipynb
    regime_validation.ipynb
  migrations/
  docs/
    architecture.md
    api.md
    runbook.md
```

---

## 19. 开发阶段与交付物

### Phase 0: 风险参数与账户定义

交付：

- `configs/research.yaml`
- 账户 NAV、base currency、允许产品、最大回撤、单笔风险预算。

验收：

- 不同账户配置可生成不同仓位建议。
- 未配置风险参数时系统拒绝输出交易建议。

### Phase 1: 数据管道

交付：

- Deribit option chain collector。
- ticker/order book collector。
- volatility index collector。
- index/futures/funding collector。
- 数据落库与数据质量检查。

验收：

- 连续采集 7 天无中断。
- 数据延迟、重复、缺失可监控。
- 全链 snapshot 可重建某一时点候选池。

### Phase 2: Vol Surface + Greeks

交付：

- surface fitter。
- delta bucket interpolation。
- SVI MVP 或平滑插值。
- model Greeks。
- surface dashboard。

验收：

- 7D/14D/30D surface 可稳定拟合。
- model_delta 与 exchange_delta 差异可解释。
- no-arb error 过高时不输出建议。

### Phase 3: Regime 分类器

交付：

- feature builder。
- initial rule-based classifier。
- daily regime label series。
- regime validation report。

验收：

- 能识别 Bear Trend、Slow Bull、Fast Bull/Breakout。
- 2023-2025 慢牛急拉特征能被 Slow Bull / Squeeze risk 捕捉。

### Phase 4: 评分与推荐引擎

交付：

- candidate builder。
- physical distribution MVP。
- EV/P_ITM/P_Touch/CVaR。
- scoring + kill conditions。
- CLI JSON recommendation。

验收：

- 任意时点可输出 top N candidate。
- no-trade 有明确 reason。
- 可复现，不同运行结果一致。

### Phase 5: 回测与校准

交付：

- realistic fill simulator。
- fees/slippage/margin path。
- baseline/regime-only/pricing-only/full-system comparison。
- walk-forward calibration report。

验收：

- Full System 在样本外优于 baseline 的 Calmar/CVaR。
- 2023-2025 回撤改善可量化。
- 无 lookahead bias。

### Phase 6: Dashboard

交付：

- Today Overview。
- Vol Surface。
- Candidate Ranking。
- Portfolio Risk。
- Backtest Report。

验收：

- 交易前 2 分钟内能完成一次完整扫描。
- 所有推荐可追溯到数据和 reason codes。

### Phase 7: 半自动执行

交付：

- Paper trading。
- Order proposal。
- Manual approval。
- Post-only limit execution helper。
- Execution log。

验收：

- Testnet/paper 环境跑满 30 天。
- 推荐、成交、风控、退出都能形成闭环。
- 实盘前只读 API 与交易 API 权限分离。

---

## 20. 测试计划

### 20.1 Unit Tests

```text
instrument parser
DTE calculation
option payoff
spread payoff
fee calculation
surface interpolation
delta band filter
regime rule logic
kill condition logic
position sizing
stress scenario PnL
```

### 20.2 Integration Tests

```text
Deribit API fetch -> normalize -> store
store -> surface fit -> greeks
surface + regime -> candidates
candidates -> score -> recommendation
positions -> portfolio risk -> risk light
```

### 20.3 Regression Tests

固定历史时间点：

```text
2021 bull rally week
2022 bear trend week
2023 slow bull squeeze week
2024/2025 sharp rally week
2025 bear transition week
```

每个时间点保存 expected recommendation snapshot，后续改代码必须说明输出变化。

### 20.4 Backtest QA

检查：

```text
无 lookahead bias
开仓只使用当时可见 bid/ask
平仓使用当时可见 bid/ask
事件日过滤不使用未来信息
regime 标签只使用当时之前数据
手续费正确封顶
保证金路径逐时间步计算
```

### 20.5 Production QA

```text
data freshness alert
API rate limit handling
exchange downtime handling
invalid quote handling
surface fit failure fallback
risk light failure defaults to no trade
```

---

## 21. 安全与运维

### 21.1 API 权限

MVP：只读 API key。

半自动执行阶段：

- Read-only key 与 trading key 分离。
- Trading key 禁止提现。
- 子账户隔离。
- 每日最大下单次数与最大 notional 限制。
- 所有订单写入 execution_log。

### 21.2 Secrets

```text
.env 只用于本地开发
生产使用 secret manager
日志中禁止打印 API key/secret
```

### 21.3 Alerting

触发通知：

```text
risk_light turns yellow/red
data stale
surface fit failure
portfolio stress loss > threshold
candidate action changes from trade to no-trade
position delta > soft/hard stop
settlement window approaching with short DTE position
```

### 21.4 Runbook

必须写清：

- 如何启动采集器。
- 如何补数据。
- 如何重跑某日 surface。
- 如何重跑某次 recommendation。
- 如何停机。
- 如何从数据异常中恢复。

---

## 22. 已知风险与未决问题

| 问题 | 风险 | 处理 |
|---|---|---|
| Regime 样本不足 | Slow Bull/Breakout 样本少，阈值不稳 | walk-forward + 保守 gating |
| 历史盘口缺失 | 回测成交过于乐观 | 优先采购/回补 quote/order book |
| IV surface 拟合不稳 | Delta/EV 错误 | fit_quality gate + fallback no-trade |
| Tail 模型低估跳跃 | 牛市急拉损失 | spread_required + stress sizing |
| Inverse USD 风险 | 币本位 PnL 掩盖真实损失 | USD shadow NAV |
| 交易所/API 异常 | 无法退出 | data stale kill + 多交易所资金分散 |
| 过拟合 | 样本内好看，实盘失效 | OOS + rolling walk-forward + ablation |
| 事件风险 | 单日跳跃穿仓 | event calendar + no short gamma window |

---

## 23. Definition of Done

系统达到 v1.0 可用标准必须满足：

1. 能稳定采集 BTC option chain、selected order book、volatility index、index price、funding/basis。
2. 能拟合 7D/14D/30D vol surface，并输出 model Greeks。
3. 能每日输出 regime label、permission、size multiplier。
4. 能扫描 naked short call 和 call credit spread 候选。
5. 能计算 EV、P_ITM、P_Touch、CVaR、Premium/CVaR、stress loss。
6. 能在 no-trade 时给出清晰 reason。
7. 能做组合层 risk light，并强制覆盖单笔评分。
8. 能回测 baseline、regime-only、pricing-only、full-system。
9. 能通过 2019-2026 walk-forward 验证。
10. Dashboard 能展示今日推荐、surface、regime、组合风险和回测结果。
11. 所有推荐可复现、可审计、可追溯数据版本。
12. 实盘前至少 30 天 paper trading 无严重系统故障。

---

## 24. 最终推荐默认策略配置

```text
主标的：BTC
次标的：ETH，第二阶段
默认产品：USDC linear options
备选产品：inverse options，但仓位 ×0.7 且启用 USD shadow NAV
默认结构：Bear Trend/Range 可裸卖；其他 regime 优先 call credit spread
默认 DTE：7D 与 14D
默认 naked delta：0.07-0.15，按 regime 调整
默认 spread sell leg：0.03-0.10，按 regime 调整
默认 protection buy leg：0.01-0.04
默认入场：post-only limit
默认止盈：60-80% premium captured
默认软止损：delta > 0.25 或亏损 > 2x credit
默认硬止损：delta > 0.35 或亏损 > 3x credit
默认 no-trade：Fast Bull/Breakout、Event risk、Low IV edge、Risk Yellow/Red、Data stale
```

---

## 25. 参考资料

以下资料用于交易所机制、API 与历史数据可用性核验：

1. Deribit API — public/get_book_summary_by_currency。
2. Deribit API — public/ticker。
3. Deribit API — public/get_order_book。
4. Deribit API — public/get_volatility_index_data。
5. Deribit Support — Linear USDC Options。
6. Deribit Support — Inverse Options。
7. Deribit Support — Fees。
8. Deribit Support — Settlement。
9. Tardis.dev — Deribit historical market data details。
10. Amberdata — Deribit market data。
