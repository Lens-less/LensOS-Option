# Changelog

本文件记录值得使用者关注的变更，格式参考
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循
[语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增

- **排序信号的预测力验证**（`signal_validation.py`、CLI `validate-signal`）。
  此前没有任何证据表明排序主轴能预测什么：`backtest.py` 回测的是一个固定基线而不是
  排序，`calibration.py` 直接是 `not_implemented`。新模块用**生产代码路径本身**逐日
  产出候选，与到期后的真实盈亏配对，输出分档表与信息系数。
  - **样本量按到期日 cohort 计**，不按观测数。相邻两天的快照是同一批合约、同一个
    结算价，当成独立样本会把 t 值放大约"每个到期日的快照数"倍。
  - **相关性先做 moneyness 中性化**。原始相关系数被虚值程度主导：一个等价于"按行权价
    排序"的信号在无任何错价信息的对照组里也能拿到 0.95 的 IC。中性化后的系数是发布值，
    原始值并列展示以暴露这个混淆有多大。
  - 同时度量 4 个候选信号（原始残差 / z 化残差 / vega 美元化残差 / IV−历史波动率），
    让"现有主轴是否值得它的复杂度"成为可回答的问题。
- **采集预检**（`validate-signal --preflight`）。样本不可回补，所以采集缺陷不被发现多久就
  浪费多久。预检走与度量相同的曲面构建，按到期日报告已结算 / 待结算 cohort、各自能贡献
  多少观测、以及被什么挡住——让一个什么都产不出的序列在第一天就说出来，而不是第六十天。
  它立刻抓到了下面这条。
- 公开行情 ticker 预算 64 → 96，研究窗口的到期日**优先填满**，短期到期日不会挤占它。
- `COLLECTION_DTE_RANGE_DAYS` 记录了一条被实测否决的加速方案。7–35 天窗口内同时只有 3 个
  到期日、每周才新增一个，而 Deribit 的 1–5 天日到期看起来能把 cohort 累积速度提高八倍。
  实测：短期波段以 `INVALID_BID_IV` / `INSUFFICIENT_VALID_QUOTES` /
  `BAD_QUOTE_RATIO_EXCEEDED` 被质量门禁拒绝，而同一份快照的 7–35 波段干净通过；由于门禁按
  整份快照评估，混入短期合约会把健康的研究窗口报价一起废掉。**为验证方便放宽门禁，等于用
  报告自己的数据去换一批门禁本来就不接受的 cohort。**
- **信号池扩到 10 个，并附共线性报告**。除原有的微笑残差三种量纲与 IV 减历史波动率外，
  新增 IV 减 DVOL、期限溢价、局部偏斜、持仓量占比、深度失衡、报价宽度。全部在同一份样本里
  一次度量，而不是串行等三轮。
  - **数信号不等于数信息。** 任何形如「IV 减去一个当日常数」的信号在当日横截面内秩完全
    相同——用 DVOL 减和用历史波动率减是同一个排序，秩相关实测为 **1.000**。共线性块给出
    两两秩相关与 `distinct_signal_estimate`；没有它，读者会数出十个信号、看到几个一致，
    然后把「重复表述」读成「相互印证」。
- **EV 稳健性拆解**（`ev_robustness.py`、CLI `ev-robustness`）。一个负的预期价值至少对应
  三种处境且应对相反：样本期含有卖方被套的行情 / edge 夹在买卖价之间 / 卖这个形状本来
  就不划算而另一边才有意思。
  - **执行敏感度**：买卖两个方向 × 买价/中价/卖价。预期赔付与开仓价格无关，所以四个变体
    是同一次路径重放上的算术，不需要额外成本。
  - **期间敏感度**：在连续（非重采样）历史切片上重算，看符号是否翻转。用连续切片是因为
    问题恰恰是「结论是否属于某个行情阶段」，而打乱顺序正好毁掉能揭示它的那个次序。
  - `verdict` 只命名数字显示了什么。两边都亏被命名为 `no_capturable_edge_at_the_touch`
    而不是「edge 在价差里」——公允价落在买卖价之间是正常报价市场的样子，把它说成发现
    就是在制造结论。
- **多腿结构抽象**（`structures.py`）。此前 `naked_short_call` 与 `call_credit_spread`
  是散布在 path-risk、edge score、组合仲裁与 P&L 各处的字符串分支，且都写死了"卖方 +
  风险在上行"。现在统一为带符号数量的腿集合：终值盈亏、最大亏损、盈亏平衡点由分段线性
  payoff 精确求解，仓位希腊值按符号加总。**无界亏损是一个答案而不是缺失值**——裸卖的
  `max_loss` 是 `None`，下游比率因此无法悄悄成立。
- **候选宇宙扩展到双边**。曲面按期权类型分别拟合（put 的单调性方向与 call 相反），
  新增 `put_credit_spreads` 与 `iron_condors` 两张表；候选表名由 `structure_types`
  发布，消费者不再需要硬编码自己知道的那几张。
- **组合边际风险**（`combination_risk.py`）。回答"这几个一起做会怎样"：
  - 跨到期日**拒绝**给出联合最大亏损，只发布明确标注的上界（各成员最坏情况之和）；
    单一到期日时才计算真正的联合 payoff。
  - 净 vega 与**按到期日拆分的 vega** 并列发布，因为净值隐含了"波动率平行移动"这个
    假设。
  - 边际贡献按"移除该成员"计算，而不是它自己的最坏情况。
- **找出有 edge 的候选**。`ev_candidate_scanner` 从 51 行的空壳恢复为真实生产者：
  - 相对价值打分 `edge_score.py`（6 个分量），排序用 **Pareto 前沿 + 已发布字典序**，
    不做加权求和；被支配的候选附带 `dominated_by` 与 `losing_axes`。
  - 绝对预期价值：`收信用 − 预期赔付 − 手续费`，基于自采的标的历史收益分布。
  - `SUSPECT_PRICE_DIVERGENCE` 护栏：报价远离模型自身估值时标为可疑数据，而不是
    报告成巨大 edge。
- **自采历史行情**。`crypto-options-underlying-history` 抓取 Deribit 公开日线；
  `realized_vol.py` 计算实现波动率与收益分布，**样本量一律按独立非重叠窗口计**。
- `path_risk` 新增 `validated_underlying_price_history` 证据分级，并随报告发布
  重叠修正后的样本上限（`authoritative_sample_size`），显式标注内部的 similarity
  effective sample size **不考虑窗口重叠**。
- `surface.black_scholes_call_price`：补上此前缺失的理论价格原语。
- CLI/API 新增 `--underlying-history-fixture`；分析缓存身份纳入该文件。
- 规范化 JSON 编码统一到 `crypto_options_report/_canonical.py`，成为所有 SHA-256
  摘要与 HMAC 签名的唯一实现，并由 `tests/test_canonical_encoding.py` 锁定字节契约。
- 文档：[术语表](docs/glossary.md)、[HTTP API 参考](docs/api-reference.md)、
  [架构总览](docs/architecture.md)。
- 英文 README（[README.en.md](README.en.md)）。
- 贡献指南、PR 模板、issue 模板与 Dependabot 配置。
- CLI 增加使用示例、退出码说明；未指定市场数据源时给出明确提示（输出到 stderr，
  stdout 仍为纯 JSON）。
- 打包：补齐 PyPI 元数据（classifiers、keywords、project.urls），新增 `py.typed`
  标记，使 `Typing :: Typed` 声明对下游类型检查真实生效。
- `ruff` 纳入开发依赖与 CI。

### 变更

- **快照采集扩展到双边**。`_select_research_summaries` 此前硬过滤
  `option_type == "call"`——在只做 call 的时代是自洽的，但 put 垂直价差与铁鹰进入候选
  宇宙后，它会让实盘快照里的 put 表**永远为空**，而产物里没有任何字段说明原因。现在按
  「到期日 × 期权类型」分层，虚值带对 put 做镜像（`[0.7, 1.0]`，目标 0.9），沿用 call 带
  会选中深度实值的、报价最宽的那一端。
- **公开行情 ticker 预算 20 → 64**。双边宇宙每个到期日需要两侧各
  `min_valid_quotes_per_expiry`（8）条报价，20 的预算连一个到期日的两侧都填不满。
- `pull-snapshot` 新增 `--output-dir`：按采集时间命名，重复采集不再互相覆盖。
  `validate-signal` 消费的就是这个目录。
- `tools/capture-daily.ps1`：一次采集 = 一份链快照 + 一次标的历史刷新，附日志与
  非零退出码。历史必须同步刷新，否则最近结算的 cohort 会因为缺结算价而悄悄掉出样本。
- `signal_validation` 按「日期 × 合约」去重并报告 `duplicate_observations_dropped`。
  计划任务重跑、手动补跑都会让同一天出现多份快照，不去重会让重复行进入同一个横截面，
  把当日的秩相关系数向被重复的那部分拉紧，而且是无声的。
- **排序主轴改为标准化残差**。此前排序用的是原始 IV 点数残差，而它在不同链条之间不可比：
  在离散的微笑上 1.5 个点在拟合噪声之内，在平滑的微笑上是显著偏离。按到期日自身的残差
  标准差（含自由度修正）z 化后才可比。拟合太薄以致算不出残差尺度时**阻断该分量**，而不是
  退回原始点数——否则退化路径恰好会偏袒最不可信的链条。
- **`return_on_risk` 与盈亏平衡缓冲改由腿推导**，不再按结构名分支。put 垂直价差与铁鹰
  同样能拿到有定义的回报／风险比；净卖出 call 的比率价差同样被判为无界。缓冲取到最近的
  盈亏平衡点，因此下行结构不再被当作上行度量。
- **希腊值按仓位方向聚合**。此前每个调用点手工取负来把多头希腊值转成空头仓位的，这在
  结构方向混合时就错了；现在由带符号数量聚合，方向自带。
- 排名产物新增 `frontier_occupancy`：**当 Pareto 前沿吞掉几乎全部候选时如实报告**
  `effective_ranking_basis = lexicographic_on_...`。6 个维度下支配关系经常不再区分任何
  东西，此时"不做加权求和"这个主张只是把权重挪进了 tie-break 顺序，而不是消失了。
- 产品叙事重定位：面向用户的形态是 **Web 工作台 + Chrome 研究伴侣**，CLI 与 HTTP API
  降为驱动它们的内部管道。
- `portfolio_risk` 的影子 sizing 表改由 `recommended_size_allowed` 把关（契约强制为
  false，直到模型被提升），而不是"有候选就算"。排名与预期价值都不会开启它。
- README 重写：以「这是什么、给谁用、不做什么」开篇，生产部署细节移入运行手册。
- 文档语言策略：中文为主，另提供英文 README。
- 文档结构调整：时点性报告移入 `docs/archive/reports/`，v1.1 PRD 与 Spec 移入
  `docs/archive/v1-spec/` 并标注「已被取代」。
- Evidence Console：说明文字字号下限提升到 11px（对齐 DESIGN.md 的技术标签规范），
  状态徽章边框改用满足 WCAG 1.4.11 对比度的颜色。

### 修复

- **绝对预期价值不再建立在写死的 50% 波动率上**。`ev_scanner` 曾把
  `target_realized_vol: 0.5` 塞进 path-risk，后者据此把**每一条历史路径**按
  `目标/该窗口自身实现波动率` 缩放。这既是这个项目里唯一一个无证据来源的关键数字，也在
  统计上抹掉了波动率聚集与跨窗口的波动率分散——正是卖方尾部亏损的来源，结果是 CVaR 被
  系统性低估。现在默认**不缩放**；确需按当前波动率条件化时必须走 `vol_scaling.mode =
  evidence_target` 并附带 source 与 as_of，否则拒绝。旧 fixture 里的裸数值仍可回放，但
  会被标注为 `unevidenced`。报告同时发布路径集**实际的波动率离散度**，即缩放会破坏的东西。
- **IV 冲击压力腿的 vega 单位差了 100 倍**。`model_vega` 是"每 1 个 IV 点"的美元敏感度，
  而压力场景的 `iv_jump` 用的是绝对波动率（1.0 = 100 个点）。此前直接透传，使每一个
  IV 跳升的压力成本被低估两个数量级。
- **缺失希腊值不再被替换成占位数**。`build_absolute_ev` 曾在 delta/vega 缺失时代入
  `0.01` 与 `1.0`，让压力成本变成占位数的产物；现在返回 `MISSING_CANDIDATE_GREEKS`。
- **forward 与 spot 不再被静默混用**。归一化器此前在一个表达式里从
  `ticker.underlying_price`（该到期日的远期）跌落到 `index_price`（现货），输出里没有
  任何痕迹。这个替换会平移每个行权价的 moneyness、把拟合微笑压到报价之下，表现为一段
  其实来自缺失字段的"贵"——在趋势行情里其背后的基差是两位数年化。现在记录
  `underlying_price_source`、`forward_price`、`index_price` 与 `forward_basis`，
  用现货兜底时把残差分量降级为 `CAUTION`。
- `strategy_research` 比较 `ev_candidate_scanner.status != "available"`，但该字段的
  取值是 `blocked/validated/unavailable`，条件恒为真——解锁排名后会永久误报"EV 排名
  不可用"。
- `build_absolute_ev` 在 `permission_state` 缺失 regime 数据时抛出未捕获异常；改为
  中性输入 + 如实标注 `regime_similarity_applied: false`，并整体 fail-closed。
- Evidence Console：市场证据新鲜度不再对每秒变化的数值播报 `aria-live`，改为仅
  播报状态阶段变化，避免读屏软件持续朗读秒数。
- Chrome 侧边栏：本地引擎离线时给出中文说明、启动命令与 `role="alert"`，不再直接
  抛出英文 `TypeError` 文本。
- 移除 `_admission_conditions` 与 `_build_spread_playbook` 中已失效的死变量。
- `surface.py`：等长序列的 `zip()` 显式声明 `strict=True`，滑动窗口改用
  `itertools.pairwise`，避免长度不一致时静默截断。

### 移除

- 从仓库中移除 AI 协作流程的内部产物（`docs/automation/`、`issues/`、
  `tools/options_coordination*`）及其 9 个对应测试文件。它们描述的是本项目**如何被
  构建**，而非产品行为。历史提交中仍可追溯。
- `SECURITY.md` 中要求仓库保持私有的条款（其引用的目录已移除）。

### 安全

- 独立安全复查未发现 CRITICAL 或 HIGH 级别问题。README 中约 25 项安全声明经代码
  追踪验证属实（常数时间 token 比较、拒绝重定向、防 DNS rebinding、作业 ID 正则
  校验后再拼路径、子进程非 shell 调用且剔除凭证环境变量等）。
