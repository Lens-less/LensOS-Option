> **已归档 / 已被取代。** 本文档记录 2026-07-07 的 v1.1 开发 Spec，其中包含
> paper trading、walk-forward 校准与半自动执行等**当前产品刻意不具备**的能力。
> 它不描述现在的产品行为，也不构成需求。
>
> 现行产品契约：[`docs/product/2026-08-02-public-product-spec.md`](../../product/2026-08-02-public-product-spec.md)
> 与 [`docs/product/2026-08-12-continuity-and-consistency-spec.md`](../../product/2026-08-12-continuity-and-consistency-spec.md)
>
> `docs/research/deribit-options-intelligence-platform-prd.md` 仅保留为研究输入与历史方向，不是当前 PRD / 验收契约。
> 当前安全边界：[`SECURITY.md`](../../../SECURITY.md)

# 加密货币期权卖 Call 收租系统 — 审计修复版完整开发 Spec

版本：v1.1 Audit-Fixed
日期：2026-07-07
状态：Engineering Spec / Research & Risk System Design
适用范围：BTC/ETH 加密货币期权短 Call / Call Credit Spread 策略的研究、回测、选券、组合风控与半自动执行支持
非投资建议：本系统输出研究与决策支持信号，不是自动化交易指令；任何实盘动作必须经过回测、walk-forward、纸面交易、账户风控和人工确认。

---

## 0. v1.1 的修订目标

v1.0 的问题不是“写得不够漂亮”，而是若干方法论和工程接口没有闭环。v1.1 的修订目标是把这些问题从“免责声明”改成“可编码规则”。

核心修订：

1. **证据先于结论**：评分引擎不再早于回测/校准上线。Phase 顺序改成“数据 → 合约/PnL/保证金适配器 → 回测执行仿真 → regime/分布校准 → 评分推荐”。
2. **Regime 不再对照主观叙事调参**：用户的历史描述只能做 sanity check，不允许作为优化目标。阈值由可证伪的未来风险/收益目标和 walk-forward 验证决定。
3. **Bootstrap 改成路径级 block bootstrap**：不再对 terminal forward_return 做无条件重采样，避免破坏慢牛急拉中的自相关和波动率聚集。
4. **评分公式去伪精度**：z-score 基准、训练窗口、特征去共线、权重校准算法全部定义；EV 是核心，VRP 不再和 EV 双重计权。
5. **保证金字段来源明确**：实时账户 IM/MM/equity 以 Deribit 私有账户接口为 source of truth；自研压力测试只做独立风控，不试图复刻交易所 PM 模型。
6. **Inverse / linear PnL 公式落地**：币本位、美元影子净值、mark-to-market、到期 payoff、spread payoff 全部写成可实现公式。
7. **风控规则统一仲裁**：MDD 熔断、保证金红绿灯、事件风险、数据异常、持仓止损进入同一个 risk arbiter，按最保守动作执行。
8. **Roll 与止损合并为持仓状态机**：delta 0.35 以上不再出现“可以 roll / 必须平仓”的冲突。
9. **Regime 不是 if/elif 优先级链**：每个风险状态独立打分，动作由 risk cap 的 min/max 仲裁决定，不由代码顺序偶然决定。
10. **Bear Trend 加 DVOL 分层**：熊市中也不能在极端波动下满仓；DVOL/ATM IV percentile 成为独立仓位上限。
11. **第三方历史数据口径必须验收**：Tardis/Amberdata/CDD/自采数据进入统一 normalization 和 reconciliation 流程，未通过不得用于校准。

---

## 1. 审计问题判定与修复映射

| # | 问题 | 是否真实存在 | v1.1 修复 |
|---:|---|---|---|
| 1 | Regime 过拟合/事后拟合 | 成立 | 删除“对照用户口头描述调阈值”为优化步骤；改为以未来 touch、CVaR、基准策略收益为训练目标，用户叙事只做事后 sanity check |
| 2 | 评分公式虚假精度 | 成立 | 定义 robust z、训练分布、权重学习、score calibration、VIF/相关性门槛；生产分数来自校准模型而非手填权重 |
| 3 | 稀疏 regime bootstrap | 成立 | block/path bootstrap + hierarchical pooling + effective sample size 下限 + sparse regime 强制 no naked / spread only |
| 4 | Inverse 合约 PnL 只有字段没有公式 | 成立 | 写入 inverse call、inverse spread、linear call、linear spread 的币本位与 USD PnL 公式 |
| 5 | Phase 顺序结论先于证据 | 成立 | 评分推荐引擎移到回测和校准之后；Phase 4 以前只允许 feature/report，不允许交易建议 |
| 6 | 第三方历史数据口径一致性空白 | 成立 | 加入 vendor reconciliation：instrument metadata、timestamp、bid/ask、IV、settlement、PnL replay 多层验收 |
| 7 | 保证金字段来源未定义 | 成立 | 实时 IM/MM/equity 读取 Deribit `get_account_summary` / `get_positions` / PM simulation；如果接口不可用，系统 no-trade |
| 8 | Bootstrap 破坏自相关和波动率聚集 | 成立，且高优先级 | 改为路径级 stationary/circular block bootstrap；P_Touch 由路径最大值估计 |
| 9 | MDD 熔断与保证金红绿灯可能矛盾 | 成立 | 统一 risk arbiter，所有风控子系统输出 action severity，最终取最保守动作 |
| 10 | Roll 与 hard stop 冲突 | 成立 | 合并为 `PositionManagementState`，delta 0.35 以上默认退出，只有能立即降低 stress loss 的转 spread 例外 |
| 11 | Regime if/elif 优先级无理论依据 | 成立 | 改为独立 risk scores + permission caps；breakout/event 是 kill cap，不靠代码顺序 |
| 12 | VRP 与 EV 高度共线 | 成立 | EV 为主；VRP 改为 residual/tie-breaker/diagnostic；高 VIF 时自动剔除 |
| 13 | Bear Trend 缺 DVOL 分层 | 对 v1.0 成立 | 新增 `volatility_cap`，即使 Bear Trend 也按 DVOL/IV percentile 压仓或禁止裸卖 |

---

## 2. 一句话定义

本系统不是“固定卖 0.1 Delta Call”的脚本，而是一个：

> **Regime-aware、Path-risk-aware、Vol-surface-aware、Portfolio-risk-aware 的加密货币期权短 Call 决策系统。**

它回答的问题是：

> 在当前市场状态、当前 IV/skew/term structure、当前账户风险预算和真实可成交盘口条件下，是否存在某个 Call 或 Call Credit Spread，其可成交权利金显著高于模型估计的真实世界上行路径损失，并且组合层面的保证金、回撤、gamma、流动性和交易所风险都可控？

最终输出不是“买/卖建议”，而是结构化研究报告：

```json
{
  "action": "SELL_CALL_SPREAD | SELL_NAKED_CALL | NO_TRADE",
  "confidence": "CALIBRATED_OOS_ONLY",
  "currency": "BTC",
  "settlement_currency": "USDC",
  "risk_state": "GREEN | YELLOW | RED | HALT",
  "regime_report_label": "Bear Trend",
  "sell_permission": 0.65,
  "naked_permission": false,
  "sell_leg": "BTC-14JUL26-69000-C",
  "buy_leg": "BTC-14JUL26-76000-C",
  "dte": 7,
  "sell_leg_delta_model": 0.084,
  "net_credit_executable": 0.0018,
  "ev_after_cost_usd": 184.50,
  "p_itm_physical": 0.071,
  "p_touch_physical": 0.183,
  "cvar_99_nav_pct": 0.46,
  "stress_up20_iv25_nav_pct": 0.71,
  "score": 78,
  "size_contracts": 0.8,
  "entry_rule": "post_only_limit_or_better",
  "take_profit": "close_50pct_after_60pct_premium_capture; close_all_after_80pct",
  "risk_exit": "state_machine_defined",
  "reason_codes": [
    "REGIME_PERMITS_SPREAD_ONLY",
    "EV_POSITIVE_AFTER_COST",
    "STRIKE_ABOVE_HAZARD_ZONE",
    "PORTFOLIO_RISK_GREEN",
    "PATH_TOUCH_WITHIN_LIMIT"
  ]
}
```

---

## 3. 产品目标与非目标

### 3.1 目标

1. 判断当前是否适合卖 Call。
2. 判断裸卖还是只允许 Call Credit Spread。
3. 在 7D/14D/21D/30D 候选中选择最优 DTE、Delta、Strike。
4. 用真实可成交 bid/ask、手续费、滑点、对冲成本、保证金和流动性计算 EV。
5. 用路径分布计算 P_ITM、P_Touch、MAE、CVaR、delta 穿越概率。
6. 用组合风险仲裁确定是否允许新开仓、是否必须减仓或停机。
7. 通过 walk-forward 和样本外测试证明：full system 相比固定 7D 0.1D short call baseline，在 2023-2025 慢牛急拉阶段显著降低回撤或 CVaR。

### 3.2 非目标

MVP 阶段不做：

- 全自动实盘交易。
- 高频做市或抢价。
- 所有交易所和所有 altcoin 期权覆盖。
- 用黑箱机器学习替代风控规则。
- 未经校准的分数实盘下单。
- 复刻 Deribit 非公开 Portfolio Margin 引擎作为保证金 source of truth。

---

## 4. 产品范围与合约选择

### 4.1 标的范围

```yaml
universe:
  primary: BTC
  secondary: ETH
  excluded_in_mvp:
    - SOL
    - XRP
    - all_altcoin_options
```

BTC 是主标的，因为期权链、盘口、历史样本和退出能力最好。ETH 作为第二资产，但默认 size multiplier 低于 BTC，直到 ETH 样本外验证通过。

### 4.2 结算产品优先级

```yaml
product_priority:
  preferred: USDC_LINEAR_OPTIONS
  fallback: INVERSE_OPTIONS_WITH_USD_SHADOW_NAV
```

理由：

- 若账户绩效基准是 USD/USDC，USDC linear options 的 PnL、保证金、回撤统计更直观。
- Inverse options 可以交易，但必须计算币本位 PnL 与美元影子净值。标的上涨时，short call 的币本位损失和 USD 计价损失路径可能表现不同，不能只看收了多少 BTC premium。

---

## 5. 外部事实与交易所接口依据

本 Spec 的交易所接口设计基于以下公开文档事实：

| 主题 | 事实 | 工程含义 |
|---|---|---|
| 全链行情 | Deribit `public/get_book_summary_by_currency` 可按币种和 kind 获取全部 instruments 的 OI、volume、bid/ask、mark 等摘要；官方建议实时更新使用 WebSocket ticker 而非轮询 | L1 market collector 使用 snapshot + ticker websocket |
| 单合约行情 | `public/ticker` 返回 best bid/ask、mark、OI、volume 等；期权还返回 greeks | 候选实时刷新和风险监控用 ticker/order book |
| volatility index | `public/get_volatility_index_data` 返回 volatility index candles，支持 start/end/resolution | 不再写 DVOL 完全无官方历史；但 full option chain 历史仍需第三方/自采 |
| 账户摘要 | `private/get_account_summary` 返回 balance、equity、available funds、initial margin、maintenance margin 等账户级信息，scope 为 `account:read` | 实时 IM/MM/equity 的 source of truth |
| 持仓 | `private/get_positions` 返回 open positions，包括 size、mark、PnL、initial_margin、maintenance_margin、delta/greeks 等，scope 为 `trade:read` | 持仓风险、逐仓 margin、PnL 对账 |
| PM simulation | `private/simulate_portfolio` / `private/pme/simulate` 可模拟 portfolio margin/risk metrics/ERM，文档注明计算复杂、限频 | 下单前 margin impact 用交易所模拟器；不可用时禁止给交易建议 |
| Portfolio Margin | Deribit PM 使用场景压力测试，最差场景只是测试网格内的 worst case，不代表最大可能亏损 | 交易所 margin 不是真实尾部损失；系统必须另算 stress/CVaR |
| Inverse options | inverse option premium 以 BTC/ETH 显示；每张 BTC/ETH option 代表 1 BTC/ETH；ITM settlement amount in underlying = USD intrinsic / delivery price | PnL 公式必须用 coin payoff，并同步 USD shadow NAV |
| Linear USDC options | linear option Black-Scholes 公式以 forward/strike 的 USDC 价格计算 | USDC 产品用线性 USD/USDC payoff |
| Settlement | Deribit options 是欧式、现金结算；到期交割价为 07:30-08:00 UTC 30 分钟 TWAP；无实物交割 | 回测和执行要处理结算窗口和 delivery fee |
| Fees | BTC/ETH options 费率为 `MIN(0.0003 coin, 0.125 * option_price) * amount`；USDC linear options 费用为 `MIN(0.0003 * IndexPrice, 0.125 * OptionPrice) * Contracts * ContractSize`；combo 有 fee discount 规则 | 回测逐笔扣费；不能把 post-only 简化成期权免手续费 |

---

## 6. 系统架构

### 6.1 分层

| 层级 | 名称 | 形态 | 优先级 | 说明 |
|---|---|---|---|---|
| L0 | 配置、账户、数据存储 | YAML + Postgres/TimescaleDB + Parquet/DuckDB | P0 | 所有数据、参数、版本化配置 |
| L1 | 市场数据与账户适配器 | Python services + scheduler + websocket | P0 | 行情、账户、持仓、margin simulation |
| L2 | 合约/PnL/费用/保证金模型 | Python library | P0 | 统一 payoff、fee、coin/USD PnL、margin source |
| L3 | 回测与校准引擎 | Research package + reports | P0 | 先证明，再推荐 |
| L4 | Vol surface / regime / distribution / scoring | Python modules | P0 | 决策模型，但必须由 L3 校准 |
| L5 | Dashboard / CLI / API | Streamlit/FastAPI/CLI | P1 | 研究输出和人工确认入口 |
| L6 | 半自动执行 | order proposal + manual approval | P2 | 后期；不得先做自动交易 |

### 6.2 关键原则

```text
Data freshness gate -> Contract/PnL validation -> Account/margin source -> Backtest simulator -> Calibration -> Recommendation
```

禁止路径：

```text
Market data -> Handwritten score -> Trade recommendation
```

如果校准模型不存在、数据质量未通过、账户接口不可用、回测模拟器未对齐，则系统只能输出 `RESEARCH_ONLY`，不能输出 `TRADE_CANDIDATE`。

---

## 7. 数据层设计

### 7.1 数据源

| 数据 | 实时源 | 历史源 | 用途 |
|---|---|---|---|
| option chain summary | Deribit `get_book_summary_by_currency` | 自采 + Tardis/Amberdata | 候选池、流动性、mark/bid/ask |
| ticker/order book | Deribit websocket / `public/ticker` / `get_order_book` | Tardis/Amberdata quote/order book | 执行可成交性、滑点、Greeks |
| index/spot | Deribit index + external reference | Deribit/Kaiko/自采 | payoff、margin、regime |
| volatility index | Deribit `get_volatility_index_data` | Deribit + Tardis/Amberdata/CDD 对照 | DVOL regime、sizing |
| futures/perp basis/funding | Deribit ticker / funding endpoints | 自采 + vendor | squeeze/breakout risk |
| account summary | Deribit private API | 交易日志 | IM/MM/equity/available funds |
| positions | Deribit private API | 交易日志 | 持仓 Greeks、PnL、逐仓 margin |
| event calendar | 外部日历 + 手工表 | 历史事件标注 | CPI/FOMC/NFP/ETF/监管/交易所异常 |

### 7.2 数据库 schema

```sql
CREATE TABLE instrument_metadata (
    venue TEXT,
    instrument_name TEXT PRIMARY KEY,
    currency TEXT,
    base_currency TEXT,
    quote_currency TEXT,
    settlement_currency TEXT,
    product_type TEXT,
    option_type TEXT,
    expiry TIMESTAMPTZ,
    strike DOUBLE PRECISION,
    contract_size DOUBLE PRECISION,
    tick_size DOUBLE PRECISION,
    source_vendor TEXT,
    first_seen_ts TIMESTAMPTZ,
    last_seen_ts TIMESTAMPTZ
);

CREATE TABLE option_chain_snapshot (
    ts TIMESTAMPTZ,
    venue TEXT,
    currency TEXT,
    settlement_currency TEXT,
    instrument_name TEXT,
    expiry TIMESTAMPTZ,
    dte DOUBLE PRECISION,
    strike DOUBLE PRECISION,
    option_type TEXT,
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
    best_bid_amount DOUBLE PRECISION,
    best_ask_amount DOUBLE PRECISION,
    depth_bid_5 DOUBLE PRECISION,
    depth_ask_5 DOUBLE PRECISION,
    quote_age_ms INTEGER,
    data_vendor TEXT,
    quality_status TEXT
);

CREATE TABLE account_risk_snapshot (
    ts TIMESTAMPTZ,
    venue TEXT,
    subaccount_id TEXT,
    currency TEXT,
    equity DOUBLE PRECISION,
    balance DOUBLE PRECISION,
    margin_balance DOUBLE PRECISION,
    available_funds DOUBLE PRECISION,
    initial_margin DOUBLE PRECISION,
    maintenance_margin DOUBLE PRECISION,
    nav_usd DOUBLE PRECISION,
    im_nav DOUBLE PRECISION,
    nav_to_mm DOUBLE PRECISION,
    source_endpoint TEXT,
    data_age_ms INTEGER
);

CREATE TABLE position_snapshot (
    ts TIMESTAMPTZ,
    venue TEXT,
    subaccount_id TEXT,
    instrument_name TEXT,
    direction TEXT,
    size DOUBLE PRECISION,
    average_price DOUBLE PRECISION,
    average_price_usd DOUBLE PRECISION,
    mark_price DOUBLE PRECISION,
    index_price DOUBLE PRECISION,
    floating_pnl_coin DOUBLE PRECISION,
    floating_pnl_usd DOUBLE PRECISION,
    realized_pnl_coin DOUBLE PRECISION,
    initial_margin DOUBLE PRECISION,
    maintenance_margin DOUBLE PRECISION,
    delta DOUBLE PRECISION,
    gamma DOUBLE PRECISION,
    theta DOUBLE PRECISION,
    vega DOUBLE PRECISION,
    source_endpoint TEXT
);

CREATE TABLE vol_surface_snapshot (
    ts TIMESTAMPTZ,
    currency TEXT,
    settlement_currency TEXT,
    expiry TIMESTAMPTZ,
    tenor_days DOUBLE PRECISION,
    delta_bucket DOUBLE PRECISION,
    strike DOUBLE PRECISION,
    bid_iv DOUBLE PRECISION,
    ask_iv DOUBLE PRECISION,
    fitted_iv DOUBLE PRECISION,
    atm_iv DOUBLE PRECISION,
    rr_25d DOUBLE PRECISION,
    rr_10d DOUBLE PRECISION,
    bf_25d DOUBLE PRECISION,
    bf_10d DOUBLE PRECISION,
    svi_params JSONB,
    no_arb_error DOUBLE PRECISION,
    fit_quality_score DOUBLE PRECISION
);

CREATE TABLE regime_features (
    ts TIMESTAMPTZ,
    currency TEXT,
    spot DOUBLE PRECISION,
    ret_1d DOUBLE PRECISION,
    ret_7d DOUBLE PRECISION,
    ret_30d DOUBLE PRECISION,
    rv_7d DOUBLE PRECISION,
    rv_14d DOUBLE PRECISION,
    rv_30d DOUBLE PRECISION,
    dvol DOUBLE PRECISION,
    dvol_percentile_2y DOUBLE PRECISION,
    atm_iv_percentile_2y DOUBLE PRECISION,
    term_structure_slope DOUBLE PRECISION,
    funding_8h DOUBLE PRECISION,
    funding_z_90d DOUBLE PRECISION,
    basis_7d DOUBLE PRECISION,
    basis_30d DOUBLE PRECISION,
    rr_25d DOUBLE PRECISION,
    rr_10d DOUBLE PRECISION,
    call_put_volume_ratio DOUBLE PRECISION,
    call_put_oi_ratio DOUBLE PRECISION,
    top3_up_days_contribution_30d DOUBLE PRECISION,
    rebound_from_support BOOLEAN,
    breaks_recent_high BOOLEAN,
    event_score DOUBLE PRECISION
);

CREATE TABLE candidate_scores (
    ts TIMESTAMPTZ,
    currency TEXT,
    structure_type TEXT,
    sell_leg TEXT,
    buy_leg TEXT,
    dte DOUBLE PRECISION,
    score DOUBLE PRECISION,
    score_model_version TEXT,
    ev_after_cost_usd DOUBLE PRECISION,
    premium_usd DOUBLE PRECISION,
    fair_value_physical_usd DOUBLE PRECISION,
    p_itm DOUBLE PRECISION,
    p_touch DOUBLE PRECISION,
    cvar_95_usd DOUBLE PRECISION,
    cvar_99_usd DOUBLE PRECISION,
    stress_up20_iv25_usd DOUBLE PRECISION,
    margin_required_usd DOUBLE PRECISION,
    suggested_size DOUBLE PRECISION,
    action TEXT,
    reason_codes JSONB,
    calibration_status TEXT
);
```

---

## 8. 数据质量与第三方数据口径一致性

### 8.1 必须修复的历史数据问题

第三方历史数据不能直接混用。Tardis、Amberdata、CDD、自采数据可能在以下方面不一致：

- instrument naming。
- timestamp 时区与截面时间。
- mark price / mid / last 的定义。
- IV 是 bid/ask IV、mark IV 还是 vendor-fitted IV。
- inverse vs linear 的 quote currency 与 settlement currency。
- OI 单位：contracts、base coin、notional USD。
- missing quotes 与 stale quotes 处理。
- 到期日、结算价、delivery fee。

### 8.2 Canonicalization 规则

所有 vendor 数据入库前统一成 canonical schema：

```python
def canonicalize_option_row(raw, source):
    meta = map_instrument_metadata(raw.instrument_name, source)
    return CanonicalOptionQuote(
        ts=normalize_timestamp(raw.ts),
        venue="DERIBIT",
        instrument_name=meta.instrument_name,
        currency=meta.base_currency,
        settlement_currency=meta.settlement_currency,
        expiry=meta.expiry,
        strike=meta.strike,
        option_type=meta.option_type,
        bid=normalize_price(raw.bid, meta),
        ask=normalize_price(raw.ask, meta),
        mark=normalize_price(raw.mark, meta),
        bid_iv=normalize_iv(raw.bid_iv),
        ask_iv=normalize_iv(raw.ask_iv),
        open_interest=normalize_oi(raw.oi, meta),
        vendor=source
    )
```

### 8.3 Vendor reconciliation 验收

每个历史源必须通过以下测试才可用于训练：

| 测试 | 阈值 | 失败处理 |
|---|---:|---|
| metadata match | expiry/strike/type/settlement 100% 可映射 | quarantine instrument |
| timestamp alignment | 同一 snapshot 偏差 <= 60 秒，日线 <= 1 bar | resample 或剔除 |
| bid/ask sanity | bid <= ask，mid > 0，spread 非负 | quarantine quote |
| IV sanity | 1% <= IV <= 500%，异常 winsor 但保留 flag | bad quote flag |
| mark/mid drift | mark 与 mid 偏离超过阈值需解释 | 不用于成交模拟 |
| overlapping vendor diff | 同时段 mid 差异中位数 < 1 tick 或 < 2% | 调查 vendor |
| payoff replay | 到期 PnL 与官方 delivery price 误差 < 1bp notional | 不可用于 PnL backtest |
| OI/volume unit | 与 Deribit current API 对照可还原 | 单位映射失败则不用 |
| surface no-arb | 大量 butterfly/calendar arbitrage 触发 quality fail | 不用于 surface fit |

### 8.4 数据可用性 gating

```yaml
data_quality_gate:
  market_data_age_max_sec: 60
  account_data_age_max_sec: 30
  stale_quote_max_sec: 120
  min_valid_quotes_per_expiry: 8
  max_bad_quote_ratio_per_expiry: 0.25
  max_surface_no_arb_error: 0.03
  vendor_reconciliation_required: true
  action_if_fail: RESEARCH_ONLY_NO_TRADE
```

---

## 9. 合约、PnL、费用公式

### 9.1 符号

```text
q       = contracts, positive quantity for strategy size
S0      = entry index price
St      = current index price
ST      = delivery price at expiry
K       = strike
Ks      = spread sell-leg strike
Kb      = spread buy-leg strike, Kb > Ks
p0      = option premium at entry
mt      = option mark price at time t
fee     = trading and delivery fee
c       = contract size, BTC/ETH options default 1 for BTC/ETH; some linear alt products may differ
```

### 9.2 Linear USDC short call

Entry credit:

```text
credit_usdc = q * c * p0_usdc
```

Expiry payoff to long call:

```text
payoff_long_usdc = q * c * max(ST - K, 0)
```

Short call expiry PnL:

```text
pnl_short_call_usdc = q * c * p0_usdc - q * c * max(ST - K, 0) - fees_usdc
```

Mark-to-market liability at time t:

```text
liability_usdc_t = q * c * mt_usdc
unrealized_pnl_usdc_t = q * c * (p0_usdc - mt_usdc) - fees_paid_usdc
```

### 9.3 Linear USDC call credit spread

```text
net_credit_usdc = q * c * (p_sell_bid_usdc - p_buy_ask_usdc)
spread_payoff_usdc = q * c * min(max(ST - Ks, 0), Kb - Ks)
pnl_spread_usdc = net_credit_usdc - spread_payoff_usdc - fees_usdc
max_loss_usdc = q * c * (Kb - Ks) - net_credit_usdc + fees_usdc
```

### 9.4 Inverse short call

Deribit inverse BTC/ETH options use coin settlement. For a call, the USD intrinsic is divided by delivery price to get settlement in underlying coin.

Long call expiry settlement in coin:

```text
payoff_long_coin = q * max(ST - K, 0) / ST
```

Short call expiry PnL in coin:

```text
pnl_short_call_coin = q * p0_coin - q * max(ST - K, 0) / ST - fees_coin - delivery_fee_coin
```

USD shadow PnL at expiry:

```text
pnl_short_call_usd_shadow = pnl_short_call_coin * ST
```

Mark-to-market at time t:

```text
liability_coin_t = q * mt_coin
liability_usd_shadow_t = liability_coin_t * St
unrealized_pnl_coin_t = q * (p0_coin - mt_coin) - fees_paid_coin
unrealized_pnl_usd_shadow_t = unrealized_pnl_coin_t * St
```

Account USD shadow equity:

```text
nav_usd_shadow_t = usdc_balance_t
                 + sum_coin_balances_i * spot_i_t
                 - option_liabilities_coin_t * spot_underlying_t
                 + linear_pnl_usdc_t
                 + futures_perp_pnl_usd_t
```

### 9.5 Inverse call credit spread

```text
net_credit_coin = q * (p_sell_bid_coin - p_buy_ask_coin)
spread_payoff_coin = q * (
    max(ST - Ks, 0) / ST
  - max(ST - Kb, 0) / ST
)
pnl_spread_coin = net_credit_coin - spread_payoff_coin - fees_coin
pnl_spread_usd_shadow = pnl_spread_coin * ST
```

For Kb > Ks, maximum intrinsic spread in coin occurs as ST changes. The USD spread payoff is capped at `q * (Kb - Ks)`, but coin payoff equals USD payoff divided by ST. Therefore both coin and USD max loss must be reported:

```text
max_loss_usd_shadow = q * (Kb - Ks) - net_credit_coin * ST_entry_adjusted + fees_usd_est
max_loss_coin_scenario(ST) = q * (Kb - Ks) / ST - net_credit_coin + fees_coin
```

Production sizing uses the larger of:

```text
stress_loss_usd_shadow
coin_liquidity_loss_converted_to_usd
exchange_margin_increment_usd
```

### 9.6 Fees

```python
def option_fee_inverse(option_price_coin, amount, coin):
    # BTC/ETH options
    return min(0.0003, 0.125 * option_price_coin) * amount


def option_fee_linear(option_price_usdc, index_price, contracts, contract_size=1):
    return min(0.0003 * index_price, 0.125 * option_price_usdc) * contracts * contract_size
```

For combo orders, fee discount rules must be modelled separately. Backtest must record both conservative non-combo fees and combo-discount fees; production default should use conservative fees unless order is actually submitted as a combo and fill logs verify the discount.

---

## 10. 保证金与账户接口

### 10.1 Source of truth

保证金字段不得空想。生产系统采用：

```text
Current account equity / IM / MM / available funds:
    Deribit private/get_account_summary or private/get_account_summaries

Current position-level margin / greeks / PnL:
    Deribit private/get_positions

Projected post-trade margin impact:
    Deribit private/simulate_portfolio or private/pme/simulate, when available for account type

Independent tail risk:
    Internal stress engine, not exchange source
```

### 10.2 不复刻 PM 模型作为交易所保证金源

规则：

```text
如果账户是 Standard Margin:
    可以实现官方公开公式作为 sanity check。
    但实盘 gating 仍以 private API 返回 IM/MM 为准。

如果账户是 Portfolio Margin:
    不尝试复刻交易所完整 PM 引擎作为 source of truth。
    使用 exchange simulation endpoint 获取 projected IM/MM。
    内部 stress engine 只用于更保守的尾部风险约束。

如果 simulation endpoint 不可用、限频、认证失败或返回异常:
    不输出新开仓建议。
```

### 10.3 账户风控字段

```python
@dataclass
class AccountRiskSnapshot:
    ts: datetime
    currency: str
    equity: float
    margin_balance: float
    available_funds: float
    initial_margin: float
    maintenance_margin: float
    nav_usd: float
    im_nav: float
    nav_to_mm: float
    margin_model: str
    data_age_sec: float
    source_endpoint: str
```

计算：

```text
im_nav = total_initial_margin_usd / nav_usd
nav_to_mm = nav_usd / max(total_maintenance_margin_usd, eps)
```

### 10.4 Pre-trade margin impact

每个候选必须计算：

```text
current_im
current_mm
projected_im_after_trade
projected_mm_after_trade
delta_im = projected_im_after_trade - current_im
delta_mm = projected_mm_after_trade - current_mm
projected_im_nav
projected_nav_to_mm
```

候选 kill condition：

```text
if projected_im_nav >= 0.30 and risk_policy.no_new_above_yellow:
    reject
if projected_nav_to_mm <= 2.00:
    reject_or_reduce
if projected_nav_to_mm <= 1.50:
    reject_and_force_reduce_existing
```

---

## 11. Vol Surface 与 Greeks

### 11.1 原则

禁止用 flat vol 推 0.1 Delta strike。每个候选必须使用当天、对应 expiry、对应 wing 的 surface IV 重算 Greeks。

### 11.2 拟合流程

```text
1. 按 expiry 分组。
2. 过滤坏报价：bid <= 0、ask <= bid、spread/mid 过宽、stale quote、OI/depth 不达标。
3. 使用 OTM calls、OTM puts、ATM 附近双边报价。
4. 先用平滑插值 MVP；生产使用 SVI/SABR，并做 no-arb 检查。
5. 输出 fitted_iv、delta、gamma、theta、vega、risk-neutral p_itm。
6. 若 fit_quality_score < threshold 或 no_arb_error > threshold，则该 expiry 不可交易。
```

### 11.3 Greeks 双轨

```text
exchange_greeks:
    与交易所 UI / margin 风险对齐。

model_greeks:
    用自拟合 surface 重新计算，用于选券、回测、风险归因。
```

差异处理：

```text
if abs(model_delta - exchange_delta) > delta_diff_threshold:
    candidate.status = REVIEW_OR_REJECT
```

---

## 12. Regime 与风险许可模型

### 12.1 关键修正：不是 if/elif 标签机

v1.1 不再让 action 由 `if fast_bull: ... elif squeeze: ... elif bear: ...` 的顺序决定。系统计算多个独立风险 score，然后每个 score 输出一个 permission cap。最终交易许可由最保守 cap 决定。

### 12.2 Risk scores

```python
@dataclass
class RegimeRiskScores:
    bear_trend_score: float
    range_score: float
    squeeze_score: float
    slow_bull_score: float
    fast_bull_breakout_score: float
    event_score: float
    volatility_stress_score: float
    data_quality_score: float
```

### 12.3 Permission caps

```python
def permission_caps(scores):
    caps = []

    # Kill caps: 市场结构意味着上行 convexity 风险不可卖
    if scores.event_score > 0.75:
        caps.append(Permission(sell=0.0, naked=False, spread=False, reason="EVENT_KILL"))
    if scores.fast_bull_breakout_score > 0.70:
        caps.append(Permission(sell=0.0, naked=False, spread=False, reason="BREAKOUT_KILL"))

    # Squeeze / slow bull caps
    if scores.squeeze_score > 0.65:
        caps.append(Permission(sell=0.30, naked=False, spread=True, reason="SQUEEZE_CAP"))
    if scores.slow_bull_score > 0.60:
        caps.append(Permission(sell=0.40, naked=False, spread=True, reason="SLOW_BULL_CAP"))

    # Volatility cap applies to all regimes, including Bear Trend
    caps.append(volatility_permission_cap(scores.volatility_stress_score))

    # Bear/Range positive permissions are upper bounds, not overrides
    if scores.bear_trend_score > 0.60:
        caps.append(Permission(sell=1.00, naked=True, spread=True, reason="BEAR_TREND_OK"))
    elif scores.range_score > 0.60:
        caps.append(Permission(sell=0.75, naked=True, spread=True, reason="RANGE_OK"))
    else:
        caps.append(Permission(sell=0.50, naked=False, spread=True, reason="NEUTRAL"))

    return most_conservative(caps)
```

### 12.4 Volatility cap

```python
def volatility_permission_cap(vol_stress_score, dvol_percentile=None, atm_iv_percentile=None):
    p = max(dvol_percentile or 0, atm_iv_percentile or 0)
    if p >= 0.98:
        return Permission(sell=0.0, naked=False, spread=False, reason="EXTREME_VOL_HALT")
    if p >= 0.95:
        return Permission(sell=0.20, naked=False, spread=True, reason="VOL_95_CAP")
    if p >= 0.80:
        return Permission(sell=0.40, naked=False, spread=True, reason="VOL_80_CAP")
    if p >= 0.60:
        return Permission(sell=0.65, naked=False, spread=True, reason="VOL_60_CAP")
    return Permission(sell=1.0, naked=True, spread=True, reason="VOL_NORMAL")
```

### 12.5 Regime label 只用于报告

```text
primary_regime_label = argmax(score among bear/range/squeeze/slow_bull/breakout)
```

但 action 不由 label 决定。action 由 permission caps、risk arbiter、candidate EV、portfolio risk 共同决定。

### 12.6 Regime 校准：删除循环论证

禁止优化目标：

```text
“让标签看起来符合用户口头四阶段描述”
```

允许用途：

```text
用户叙事只做 post-hoc sanity check，不参与阈值优化，不参与模型选择。
```

训练目标：

```text
y_touch_h = 1{baseline 7D/14D 0.1D short call 在存续期触碰 strike}
y_loss_h = 1{baseline mark loss > 2x premium 或 3x premium}
y_cvar_h = realized loss percentile / NAV
utility_h = realized_pnl_after_cost / max(initial_margin, stress_loss)
```

校准流程：

```text
1. 使用 t 时点之前可见的 features。
2. 构造未来 h 天 baseline short call 的 realized path labels。
3. 使用 purged walk-forward：训练窗口 24 个月，测试窗口 3 个月，embargo = max_dte。
4. 用 logistic / isotonic / monotonic GBM 估计 adverse path probability。
5. 阈值选择目标：最大化 OOS utility，同时约束 MDD、CVaR、touch-rate、turnover。
6. 只保留跨多个 OOS folds 稳定的阈值。
7. 最后才检查标签是否大体能解释历史阶段；不吻合不自动调参，除非 OOS 指标也支持。
```

---

## 13. 真实世界分布与 P_Touch

### 13.1 旧方案问题

对同 regime 的 terminal forward_return 做无条件 bootstrap 会破坏：

- 日收益自相关。
- 波动率聚集。
- 慢牛急拉中“几天内连续上冲”的路径结构。
- P_Touch 和 gamma path 的估计。

这会在策略最怕的 2023-2025 类环境下低估触碰概率。

### 13.2 MVP 采用路径级 block bootstrap

历史样本单位不是单个 terminal return，而是一段长度为 H 的路径：

```python
@dataclass
class HistoricalPath:
    start_ts: datetime
    horizon_days: int
    regime_scores: dict
    feature_vector: np.ndarray
    daily_log_returns: np.ndarray      # length H
    daily_rv: np.ndarray               # length H
    spot_path_normalized: np.ndarray   # starts at 1.0
    max_up_return: float
    terminal_return: float
```

路径库构建：

```python
def build_path_library(spot_series, features, horizons=(2,3,7,14,21,30,35)):
    paths = []
    for h in horizons:
        for t in valid_start_dates:
            r = log_returns[t+1:t+h+1]
            path = np.exp(np.cumsum(r))
            paths.append(HistoricalPath(
                start_ts=t,
                horizon_days=h,
                regime_scores=features.loc[t].regime_scores,
                feature_vector=features.loc[t].values,
                daily_log_returns=r,
                daily_rv=rolling_rv.loc[t:t+h],
                spot_path_normalized=np.r_[1.0, path],
                max_up_return=path.max() - 1.0,
                terminal_return=path[-1] - 1.0
            ))
    return paths
```

### 13.3 Similarity-weighted path sampling

```python
def sample_similar_paths(current_features, path_library, h, n=10000):
    candidates = [p for p in path_library if p.horizon_days == h and p.start_ts < current_date]

    weights = []
    for p in candidates:
        feature_distance = mahalanobis(current_features.core, p.feature_vector.core)
        regime_distance = l2(current_features.regime_scores, p.regime_scores)
        recency_penalty = recency_decay(p.start_ts)
        weights.append(np.exp(-feature_distance) * np.exp(-regime_distance) * recency_penalty)

    ess = effective_sample_size(weights)
    if ess < MIN_EFFECTIVE_PATHS:
        return sparse_regime_fallback(current_features, path_library, h)

    return weighted_sample(candidates, weights, n=n)
```

### 13.4 Stationary / circular block bootstrap

如果需要从更长历史重采样日收益，采用 block bootstrap：

```python
def stationary_block_bootstrap(returns, h, expected_block_len, n_paths):
    paths = []
    p_new_block = 1.0 / expected_block_len
    for _ in range(n_paths):
        i = random_start()
        path = []
        while len(path) < h:
            path.append(returns[i])
            if random.random() < p_new_block:
                i = random_start()
            else:
                i = (i + 1) % len(returns)
        paths.append(path[:h])
    return np.array(paths)
```

Block length 选择：

```text
expected_block_len = max(
    2,
    min(h, first_lag_where_abs_return_acf_below_0.1 or volatility_half_life)
)
```

### 13.5 Volatility scaling

用历史路径时，要把历史局部波动率缩放到当前 forecast vol：

```python
def vol_scale_path(path_returns, hist_vol, current_vol_forecast):
    standardized = path_returns / max(hist_vol, eps)
    return standardized * current_vol_forecast
```

当前波动率 forecast：

```text
sigma_forecast = blend(
    EWMA_RV,
    HAR_RV,
    ATM_IV_adjusted,
    current_DVOL_level
)
```

### 13.6 Stress mixture floor

MVP 也必须加入保守尾部 floor，不等 EVT 生产版：

```text
P_final = (1 - q_stress) * P_bootstrap + q_stress * P_stress
```

其中：

```text
q_stress = max(1%, historical_up_jump_frequency_similar_state, event_adjustment)
P_stress includes:
    +5%, +10%, +20%, +30% spot paths
    IV +10/+25 vol paths
    liquidity exit at ask paths
```

### 13.7 Sparse regime fallback

```python
if effective_sample_size < 80:
    naked_permission = False
    distribution = hierarchical_pooling(
        current_regime_paths,
        parent_regime_paths,
        all_market_paths,
        stress_mixture_floor
    )
    confidence_penalty += HIGH
```

Sparse fallback 动作：

```text
- Fast Bull / Breakout sparse: no-trade。
- Squeeze sparse: spread-only，size <= 0.25x。
- Bear sparse: spread preferred，naked cap <= 0.50x。
```

### 13.8 P_Touch 估计

P_Touch 由路径最大值估计，不由 terminal distribution 估计：

```python
def estimate_touch(paths, spot, strike):
    touched = []
    for r_path in paths:
        spot_path = spot * np.exp(np.cumsum(r_path))
        touched.append(spot_path.max() >= strike)
    return np.mean(touched)
```

输出：

```text
p_itm_physical
p_touch_physical
expected_max_adverse_excursion
prob_delta_gt_0.25
prob_delta_gt_0.35
cvar_95
cvar_99
stress_loss_up20_iv25
```

---

## 14. 候选生成

### 14.1 候选类型

```text
A. Naked Short Call
B. Call Credit Spread = Sell OTM Call + Buy further OTM Call same expiry
```

### 14.2 预过滤

```python
def build_base_calls(chain, account):
    return chain[
        (chain.option_type == "C") &
        (chain.dte.between(account.min_dte, account.max_dte)) &
        (chain.model_delta.between(0.03, 0.15)) &
        (chain.bid > 0) &
        (chain.open_interest >= account.min_oi) &
        (((chain.ask - chain.bid) / chain.mid) <= account.max_spread_mid) &
        (chain.quote_age_sec <= account.max_quote_age_sec) &
        (chain.fit_quality_score >= account.min_surface_quality)
    ]
```

### 14.3 DTE 规则

| DTE | 默认动作 | 说明 |
|---:|---|---|
| 0-1 | 禁用 | gamma 太高，只保留研究模式 |
| 2-4 | 特殊机会，小仓 | 需要 Bear Trend + EV 厚 + event 低 + P_Touch 可控 |
| 7 | 主力 | theta 足，gamma 可监控 |
| 14 | 主力 | 当前 IV 偏低或 squeeze risk 偏高时优先 |
| 21-35 | spread/远阻力 | 不作为裸卖主力 |
| >35 | 默认禁用 | 周转慢，vega 暴露大 |

### 14.4 Delta 规则

| Permission state | Naked Call | Spread sell leg | Protection leg |
|---|---:|---:|---:|
| Bear + vol normal | 0.08-0.15 | 0.08-0.15 | 0.01-0.04 |
| Range + vol normal | 0.07-0.12 | 0.07-0.12 | 0.01-0.04 |
| Bear + vol elevated | 禁止或 0.05-0.08 小仓 | 0.05-0.10 | 0.01-0.04 |
| Squeeze | 禁止 | 0.05-0.10 | 0.01-0.04 |
| Slow Bull | 禁止 | 0.03-0.07 | 0.01-0.03 |
| Breakout/Event | 禁止 | 禁止新开 | - |

### 14.5 Hazard zone

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
    if structure_type == "NAKED": reject
    if structure_type == "SPREAD": penalize or require smaller size
```

---

## 15. EV 定价

### 15.1 基础公式

Naked short call:

```text
EV = executable_credit - E_P[call_payoff] - fees - slippage - hedge_cost
```

Call credit spread:

```text
EV = net_credit - E_P[spread_payoff] - fees - slippage - hedge_cost
```

### 15.2 可成交价格

```text
naked short:
    executable_credit = sell_leg_bid * q

spread:
    executable_credit = sell_leg_bid * q - buy_leg_ask * q
```

禁止：

```text
- 用 mark 价开仓。
- 用 mid 价乐观成交。
- 忽略平仓时不利边。
```

### 15.3 Fair IV 与 EV 的关系

系统不直接说“bid_iv > RV 就卖”。必须通过真实世界路径分布计算 `E_P[payoff]`。Fair IV 只用于诊断和 sanity check：

```text
if bid_iv <= fair_physical_iv:
    reject
```

---

## 16. 评分引擎：去伪精度版

### 16.1 评分不是手填权重

生产版 score 必须来自校准模型：

```text
score = calibrated_percentile(expected_oos_utility | feature vector)
```

MVP 可以输出 feature table 和 raw EV，但不得输出“可交易分数”。

### 16.2 特征分组

| 组 | 特征 | 说明 |
|---|---|---|
| Edge | EV_after_cost/margin、Premium/CVaR、Stress-adjusted EV | 核心收益质量 |
| Path risk | P_Touch、MAE、prob_delta_gt_0.25/0.35、GammaRisk | short gamma 路径风险 |
| Vol diagnostics | IV_RV_Edge、VRP_residual、term slope、skew | 诊断，不与 EV 重复计权 |
| Execution | spread/mid、depth、quote age、OI、fill probability | 可执行性 |
| Portfolio | delta usage、margin impact、expiry concentration | 组合容量 |
| Regime permission | sell cap、naked permission、vol cap | gating，不做正向 alpha 加分 |
| Event/data | event score、data quality score | 惩罚或 kill |

### 16.3 Robust z-score 定义

```python
def robust_z(x, reference_values):
    med = median(reference_values)
    mad = median(abs(reference_values - med))
    z = 0.6745 * (x - med) / max(mad, eps)
    return clip(z, -5, 5)
```

reference population：

```text
same currency
same structure_type
same dte_bucket: [2-4, 5-10, 11-20, 21-35]
same delta_bucket: [0.03-0.05, 0.05-0.08, 0.08-0.12, 0.12-0.15]
training window only
```

禁止使用：

```text
- 当前全样本未来数据做标准化。
- 包含测试期的 median/MAD。
- 未分 DTE/delta bucket 的全市场混合 z-score。
```

### 16.4 EV 与 VRP 去共线

EV 已经吸收了对真实世界波动和 payoff 的估计。VRP 与 EV 同源，不能同时高权重线性相加。

生产规则：

```python
features = compute_features(...)

# In training window only
vif_table = compute_vif(features)
corr = spearman_corr(features["ev_after_cost_margin"], features["vrp"])

if abs(corr) > 0.60 or vif_table["vrp"] > 5:
    features["vrp_residual"] = residualize(
        y=features["vrp"],
        X=["ev_after_cost_margin", "forecast_rv", "bid_iv", "p_touch"]
    )
    drop("vrp")
else:
    keep("vrp")
```

最终模型中：

```text
EV_after_cost/margin 是核心 edge 特征。
VRP_residual 只作为诊断或 tie-breaker。
如果 residual 无 OOS 贡献，则剔除。
```

### 16.5 校准目标

训练标签：

```text
realized_utility = realized_pnl_after_cost / max(initial_margin, stress_loss_up20_iv25)
adverse_event = 1 if mark_loss > 2x_credit or delta > 0.35 or forced_exit else 0
```

模型：

```text
Model 1: Ridge / ElasticNet regression for realized_utility
Model 2: Logistic / isotonic calibration for adverse_event
Model 3: Ranking model for top-N candidate selection
```

决策分数：

```python
expected_utility = model_utility.predict(features)
p_adverse = model_adverse.predict_proba(features)
score_raw = expected_utility - lambda_adverse * p_adverse
score = 100 * empirical_cdf_train(score_raw)
```

### 16.6 决策映射

```yaml
score_policy:
  trade_standard: score >= 80 and p_adverse <= trained_threshold_low
  trade_half_or_spread: 65 <= score < 80 and p_adverse <= threshold_mid
  observe_only: 50 <= score < 65
  no_trade: score < 50
```

但任何 kill condition 优先于 score。

---

## 17. Kill conditions

```yaml
kill_conditions:
  ev_after_cost <= 0: NO_TRADE
  bid_iv <= fair_physical_iv: NO_TRADE
  spread_mid > max_allowed: NO_TRADE
  depth_available < 3x_order_size: NO_TRADE
  fast_bull_breakout_score > 0.70: NO_TRADE
  event_score > 0.75: NO_TRADE
  risk_state in [RED, HALT]: NO_TRADE_OR_REDUCE
  risk_state == YELLOW: NO_NEW_TRADES_ONLY_REDUCE
  projected_nav_to_mm < 2.00: NO_TRADE
  projected_nav_to_mm < 1.50: FORCE_REDUCE
  market_data_age > 60s: NO_TRADE
  account_data_age > 30s: NO_TRADE
  settlement_window_active: NO_NEW_SHORT_DATED
  vendor_quality_fail: RESEARCH_ONLY
  uncalibrated_score_model: RESEARCH_ONLY
```

---

## 18. 组合风险仲裁器

### 18.1 风控冲突修复

MDD、保证金、事件、数据质量、持仓止损不再各说各话。所有子系统输出统一 action severity。

### 18.2 Severity levels

```python
class ActionSeverity(IntEnum):
    ALLOW_NEW = 0
    REDUCE_SIZE = 1
    SPREAD_ONLY = 2
    NO_NEW_TRADES = 3
    REDUCE_EXISTING = 4
    CLOSE_BATCH = 5
    CLOSE_ALL_AND_PAUSE = 6
    HALT_SYSTEM = 7
```

### 18.3 Risk sub-states

```python
@dataclass
class RiskSignal:
    source: str
    severity: ActionSeverity
    reason: str
    expires_at: datetime | None
```

sources：

```text
margin_light
mdd_circuit
batch_loss
event_risk
data_quality
exchange_status
position_state
liquidity_state
```

### 18.4 仲裁规则

```python
def arbitrate_risk(signals):
    final = max(signals, key=lambda s: s.severity)
    return final
```

例子：

```text
margin_light = GREEN, severity ALLOW_NEW
mdd_circuit = CLOSE_ALL_AND_PAUSE
final = CLOSE_ALL_AND_PAUSE
```

这解决了“保证金已绿但历史回撤触发熔断”的矛盾。

### 18.5 保证金红绿灯

```yaml
margin_lights:
  green:
    im_nav_max: 0.30
    nav_to_mm_min: 2.00
    severity: ALLOW_NEW
  yellow:
    im_nav_min: 0.30
    im_nav_max: 0.50
    nav_to_mm_min: 1.50
    nav_to_mm_max: 2.00
    severity: NO_NEW_TRADES
  red:
    im_nav_min: 0.50
    nav_to_mm_max: 1.50
    severity: REDUCE_EXISTING
```

### 18.6 MDD 熔断

```yaml
mdd_circuit:
  mdd_50pct_of_cap:
    severity: REDUCE_EXISTING
    action: reduce_all_positions_50pct
  mdd_80pct_of_cap:
    severity: CLOSE_ALL_AND_PAUSE
    action: close_all_and_pause_until_review
```

---

## 19. 仓位 sizing

### 19.1 风险反推仓位

```python
size_by_cvar = account.max_single_trade_loss_usd / max(candidate.cvar_99_usd, eps)
size_by_stress = account.max_single_trade_loss_usd / max(candidate.stress_up20_iv25_usd, eps)
size_by_delta = account.max_delta_usd / max(abs(candidate.delta_usd), eps)
size_by_margin = account.max_new_margin_usd / max(candidate.delta_initial_margin_usd, eps)
size_by_liquidity = candidate.visible_depth * account.max_depth_fraction
size_by_score = score_to_size_cap(candidate.score)
size_by_permission = permission.sell_cap
size_by_vol = volatility_size_multiplier(dvol_percentile, atm_iv_percentile)

raw_size = min(
    size_by_cvar,
    size_by_stress,
    size_by_delta,
    size_by_margin,
    size_by_liquidity,
    size_by_score
)

final_size = raw_size * min(size_by_permission, size_by_vol, inverse_multiplier)
```

### 19.2 DVOL/IV multiplier

```python
def volatility_size_multiplier(dvol_pct, atm_iv_pct):
    p = max(dvol_pct, atm_iv_pct)
    if p >= 0.98: return 0.0
    if p >= 0.95: return 0.20
    if p >= 0.80: return 0.40
    if p >= 0.60: return 0.65
    return 1.00
```

### 19.3 默认预算

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

---

## 20. 持仓管理状态机

### 20.1 状态定义

```python
class PositionState(Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    DEFENSE = "DEFENSE"
    EXIT_REQUIRED = "EXIT_REQUIRED"
    FORCE_CLOSE = "FORCE_CLOSE"
    PAUSED = "PAUSED"
```

### 20.2 状态转移

| 条件 | 状态 | 允许动作 |
|---|---|---|
| delta <= 0.20 且 loss < 1x credit | NORMAL | 持有、止盈、常规 roll |
| 0.20 < delta <= 0.25 或 loss 1-2x | CAUTION | 不加仓，准备减仓/hedge |
| 0.25 < delta <= 0.35 或 loss 2-3x | DEFENSE | 减仓、买保护腿转 spread、delta hedge；禁止扩大风险 roll |
| 0.35 < delta <= 0.40 或 loss > 3x | EXIT_REQUIRED | 默认平仓；仅允许能立即降低 stress loss 的转 spread |
| delta > 0.40 或 breakout kill | FORCE_CLOSE | 平仓；禁止 roll up/out 延长风险 |
| MDD/数据/交易所熔断 | PAUSED | 关闭或冻结；人工复盘 |

### 20.3 Roll 规则统一

主动 roll：

```text
仅 NORMAL/CAUTION 允许。
DTE <= 7 且 delta 0.05-0.20。
roll 后 EV、P_Touch、stress loss 必须优于原仓。
```

防守处理：

```text
DEFENSE: 可以减仓、买保护腿、或 roll up/out，但 roll 后 total stress loss 必须下降至少 30%，且不得增加净 short gamma。
EXIT_REQUIRED: 不允许 roll up/out 作为亏损递延；只有买保护腿转 defined-risk spread 或平仓。
FORCE_CLOSE: 只平仓或执行预定义灾难保护，不 roll。
```

禁止：

```text
- 同一批仓位单月 roll 超过 2 次。
- roll 后 stress loss 更大。
- roll 后 DTE 更长但没有降低 CVaR。
- roll 只是为了避免确认亏损。
```

---

## 21. Delta hedge

```text
if net_delta_usd > 8-10% NAV:
    hedge with perp/future to 3-5% NAV

if spot_up_1d > 7-10% or dvol_jump > 15-20 vol:
    immediate hedge 70-100% of excess delta

if gamma_risk too high:
    do not rely only on perp hedge;
    reduce short call or buy protection call
```

Funding cost：

```text
hedge_cost = realized_funding + trading_fee + slippage
if hedge_cost > 20% of collected premium:
    reevaluate position; do not keep hedge indefinitely as hidden loss
```

---

## 22. 执行规则

### 22.1 入场

```text
1. 只对评分最高的 1-3 个候选生成 proposal。
2. 默认 post-only limit；目的为控制成交价格与避免吃穿盘口，不假设期权 maker 免手续费。
3. naked short 用 sell leg bid 或更保守价格估算。
4. spread 用 sell leg bid - buy leg ask 估算。
5. 净权利金必须大于手续费 + 滑点的 5 倍。
6. 事件窗口不新开 naked short。
7. strike 在 hazard zone 内：naked reject；spread 降仓或 no-trade。
8. 07:30-08:00 UTC 结算窗口不新开短到期仓位。
```

### 22.2 止盈

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
- 平仓或进入新一轮候选扫描
```

### 22.3 订单状态机

```text
PROPOSED -> REVIEWED -> APPROVED -> SUBMITTED -> PARTIALLY_FILLED -> FILLED -> MANAGED
                  |          |             |             |
                  v          v             v             v
              REJECTED    EXPIRED       CANCELED      EXITED
```

MVP 只允许到 `PROPOSED` 和 `REVIEWED`，由人工下单。

---

## 23. 回测与校准

### 23.1 先回测，后推荐

Phase 5 以前系统不得输出“建议交易”。可以输出：

```text
- candidate features
- raw EV estimate
- risk report
- no-trade reason
```

但不能输出：

```text
- score >= 80 可交易
- recommended size
- trade instruction
```

### 23.2 成交模拟

```text
开仓 naked short: sell at bid
开仓 spread: sell leg at bid, buy leg at ask
平仓 short: buy back at ask
平仓 long protection: sell at bid
```

### 23.3 路径模拟

逐时点记录：

```text
mark-to-market pnl
coin pnl
usd shadow pnl
delta/gamma/vega/theta
margin usage
account nav_to_mm
position state
risk arbiter output
touch event
hedge event
roll event
forced exit event
```

### 23.4 Walk-forward

```text
Training window: 24 months
Validation/test window: 3 months
Embargo: max_dte days
Purge overlapping labels: yes
Recalibration cadence: monthly or quarterly
```

比较组：

```text
Baseline: fixed 7D 0.1D naked short call
Regime-only: permission caps, no EV scoring
Pricing-only: EV scoring, no regime/risk caps
Full-system: regime + path distribution + EV + risk arbiter + execution rules
```

验收指标：

```text
CAGR
Max Drawdown
Calmar
Sortino
weekly worst loss
monthly worst loss
CVaR 95/99
touch rate
forced exit count
margin breach count
liquidation count
premium captured ratio
premium / cvar
profit by regime
loss by regime
roll success rate
hedge cost / premium income
days to recover
```

### 23.5 必须通过的验收

```text
1. Full System OOS Calmar > Baseline。
2. Full System OOS CVaR_99 < Baseline。
3. 2023-2025 慢牛急拉阶段 MDD 或 worst-month loss 明显改善。
4. 没有 lookahead bias。
5. vendor data reconciliation 通过。
6. 实盘纸面交易至少 30-60 天，proposal 与实际盘口可成交性吻合。
```

---

## 24. API / CLI / Dashboard

### 24.1 REST API

```text
GET /health
GET /market/chain?currency=BTC
GET /surface?currency=BTC&expiry=...
GET /regime?currency=BTC
GET /risk/account
GET /risk/portfolio
GET /candidates?currency=BTC
POST /recommendation
POST /backtest/run
GET /backtest/report/{id}
```

### 24.2 CLI

```bash
crypto-call-system ingest --currency BTC
crypto-call-system fit-surface --currency BTC
crypto-call-system build-features --currency BTC
crypto-call-system backtest --config configs/research.yaml
crypto-call-system calibrate --window 24m --test 3m
crypto-call-system scan --currency BTC --mode research
crypto-call-system recommend --currency BTC --mode paper
```

### 24.3 Dashboard

页面：

```text
1. 今日总览：risk_state、sell permission、no-trade reasons。
2. Vol surface：ATM IV、skew、term structure、surface quality。
3. Regime：scores, permission caps, label timeline。
4. 候选排名：EV、P_Touch、CVaR、stress、score、size。
5. 组合风险：IM/NAV、NAV/MM、delta/gamma/vega、MDD、stress table。
6. Backtest：baseline vs full-system。
7. Data quality：vendor reconciliation, stale quotes, missing snapshots。
```

---

## 25. 开发阶段与交付物

### Phase 0 — 风险参数、账户模型、保证金接口 Spike

交付：

```text
- configs/account.yaml
- account adapter: get_account_summary/get_positions
- PM simulation spike: simulate_portfolio / pme/simulate availability test
- margin source decision document
```

验收：

```text
- 能读取 equity/IM/MM/positions。
- 能识别 margin_model。
- 能计算 nav_usd、im_nav、nav_to_mm。
- simulation endpoint 不可用时系统返回 NO_TRADE。
```

### Phase 1 — 数据管道与质量门槛

交付：

```text
- option chain collector
- ticker/order book collector
- volatility index collector
- index/funding/basis collector
- vendor ingestion + normalization
- data quality gate
```

验收：

```text
- 连续 7 天采集无中断。
- 任一时点可重建 option chain。
- vendor reconciliation report 通过。
```

### Phase 2 — 合约、PnL、费用、结算模型

交付：

```text
- inverse/linear payoff library
- fee model
- delivery settlement model
- USD shadow NAV model
- unit tests with known examples
```

验收：

```text
- inverse call example: K=100000, ST=125000, long settlement=0.2 BTC。
- linear spread max loss 计算正确。
- fee cap 计算正确。
```

### Phase 3 — 回测执行仿真器

交付：

```text
- realistic fill simulator
- path MTM and margin simulator
- position state machine
- risk arbiter replay
```

验收：

```text
- baseline 固定策略可复现。
- 逐笔 PnL、fee、margin、state 可追踪。
- 不使用 mid/mark 乐观成交。
```

### Phase 4 — Vol surface、features、regime risk 校准

交付：

```text
- surface fitter
- model greeks
- regime feature builder
- permission cap model
- walk-forward validation
```

验收：

```text
- 7D/14D/30D surface 稳定。
- permission caps OOS 降低 adverse touch/loss。
- 用户叙事只作为 sanity check 附录。
```

### Phase 5 — Path distribution 与评分模型校准

交付：

```text
- path/block bootstrap distribution
- P_Touch / CVaR / stress module
- score calibration
- feature de-collinearity report
```

验收：

```text
- 2023-2025 慢牛急拉 P_Touch 不被系统性低估。
- EV/VRP VIF 处理完成。
- OOS score 与 realized utility 有单调关系。
```

### Phase 6 — Research CLI 与 Dashboard

交付：

```text
- scan/recommend CLI in research/paper mode
- dashboard
- JSON report
```

验收：

```text
- no-trade reason 明确。
- top-N candidates 可解释。
- 不通过校准时只输出 RESEARCH_ONLY。
```

### Phase 7 — 纸面交易与半自动执行

交付：

```text
- paper trading ledger
- proposal approval workflow
- post-only limit order template
- execution log reconciliation
```

验收：

```text
- 30-60 天 paper trade。
- 预估成交价、fee、slippage 与实际盘口吻合。
- 风控 state machine 能正确触发。
```

---

## 26. YAML 配置模板

```yaml
system:
  mode: research_only   # research_only | paper | manual_execution
  require_calibrated_model: true
  require_account_api: true
  require_vendor_reconciliation: true

universe:
  primary: BTC
  secondary: ETH
  product_priority:
    - USDC_LINEAR_OPTIONS
    - INVERSE_OPTIONS_WITH_USD_SHADOW_NAV

candidate_filter:
  min_dte: 2
  max_dte: 35
  primary_dte: [7, 14]
  min_delta: 0.03
  max_delta: 0.15
  max_spread_mid: 0.15
  max_spread_mid_deep_otm: 0.25
  min_open_interest_btc: 50
  min_open_interest_eth: 200
  max_quote_age_sec: 120

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

margin_gate:
  green_im_nav_max: 0.30
  yellow_im_nav_max: 0.50
  min_nav_to_mm_for_new_trade: 2.00
  force_reduce_nav_to_mm: 1.50

volatility_cap:
  dvol_or_atm_iv_pct_60: 0.65
  dvol_or_atm_iv_pct_80: 0.40
  dvol_or_atm_iv_pct_95: 0.20
  dvol_or_atm_iv_pct_98: 0.00

path_distribution:
  method: similarity_weighted_block_bootstrap
  min_effective_paths: 80
  stress_mixture_min_weight: 0.01
  horizons: [2, 3, 7, 14, 21, 30, 35]
  block_length_method: abs_return_acf_or_vol_half_life

score_calibration:
  train_window_months: 24
  test_window_months: 3
  embargo_days: 35
  robust_z: median_mad_by_currency_structure_dte_delta
  vif_threshold: 5
  corr_threshold: 0.60
  vrp_handling: residualize_or_drop

position_state:
  caution_delta: 0.20
  defense_delta: 0.25
  exit_required_delta: 0.35
  force_close_delta: 0.40
  soft_loss_multiple: 2.0
  hard_loss_multiple: 3.0
  max_rolls_per_month_per_batch: 2

execution:
  order_type: post_only_limit
  min_net_premium_to_cost: 5.0
  no_new_short_settlement_window_utc: "07:30-08:00"
  max_top_candidates: 3
```

---

## 27. 测试计划

### 27.1 Unit tests

```text
- inverse call payoff。
- inverse spread payoff。
- linear call/spread payoff。
- fee cap。
- robust z 不使用未来数据。
- EV/VRP residualization。
- risk arbiter severity ordering。
- position state transitions。
- block bootstrap path length and touch calculation。
```

### 27.2 Integration tests

```text
- Deribit market data ingestion。
- account summary / positions adapter。
- simulation endpoint fallback。
- surface fit from live chain。
- candidate scan from historical snapshot。
- backtest full replay for fixed time window。
```

### 27.3 Regression tests

```text
- 2021 fast bull window。
- 2022 bear trend window。
- 2023-2025 slow bull acute rally windows。
- 2025 bear transition window。
```

### 27.4 Safety tests

```text
- stale account data -> NO_TRADE。
- MDD HALT + margin GREEN -> HALT wins。
- delta 0.38 -> EXIT_REQUIRED, no roll-up/out unless stress loss decreases。
- fast_bull + bear score both high -> BREAKOUT_KILL wins。
- sparse regime ESS < 80 -> no naked。
```

---

## 28. Definition of Done

系统 v1.1 可进入 paper/manual mode 的条件：

```text
1. 账户 API、持仓 API、margin simulation 可用，或不可用时能强制 no-trade。
2. 期权链、ticker、vol index、funding/basis 数据质量通过。
3. historical vendor reconciliation 通过。
4. inverse/linear PnL 和 fee 单测通过。
5. backtest engine 能复现 fixed 0.1D baseline。
6. path bootstrap 能输出 P_Touch/CVaR，且在慢牛急拉窗口不低估 touch。
7. score model 经过 walk-forward 校准，OOS score 与 realized utility 单调。
8. full system OOS 指标优于 baseline，尤其 2023-2025 MDD/CVaR 改善。
9. risk arbiter 能处理所有冲突状态。
10. paper trading 至少 30-60 天，执行价格和手续费对账通过。
```

---

## 29. 最终原则

这套系统的核心不是找到“最便宜/最远/最高年化”的 Call，而是避免在错误 regime 中出售没有补偿的上行 convexity。

最终生产原则：

> **熊市卖 Call 可以是正期望策略，但只能在路径风险、波动补偿、保证金、流动性和组合风控同时通过时执行。慢牛急拉、挤空、突破、极端 DVOL、数据异常或账户风控冲突时，系统必须自动降仓、转 defined-risk spread 或 no-trade。**

---

## 30. 参考来源

1. Deribit API — `public/get_book_summary_by_currency`: https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency
2. Deribit API — `public/ticker`: https://docs.deribit.com/api-reference/market-data/public-ticker
3. Deribit API — `public/get_volatility_index_data`: https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data
4. Deribit API — `private/get_account_summary`: https://docs.deribit.com/api-reference/account-management/private-get_account_summary
5. Deribit API — `private/get_positions`: https://docs.deribit.com/api-reference/account-management/private-get_positions
6. Deribit API — `private/simulate_portfolio`: https://docs.deribit.com/api-reference/upcoming/account-management/private-simulate_portfolio
7. Deribit API — `private/pme/simulate`: https://docs.deribit.com/api-reference/account-management/private-simulate
8. Deribit Support — Portfolio Margin: https://support.deribit.com/hc/en-us/articles/25944756247837-Portfolio-Margin
9. Deribit Support — Inverse Options: https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options
10. Deribit Support — Linear USDC Options: https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options
11. Deribit Support — Settlement: https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement
12. Deribit Support — Fees: https://support.deribit.com/hc/en-us/articles/25944746248989-Fees
