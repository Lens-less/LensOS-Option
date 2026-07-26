# Deribit 数据与开源项目版图（2026-07-12）

日期：2026-07-12
目标：为当前 `research_only` Dashboard 的真实数据补全选择可复核的数据平面；不启用 paper/manual/live trading，不把 fixture、回放文件或演示数据冒充生产数据。

## 结论先行

1. **没有任何一个仓库能“装上就让 Dashboard 全绿”。** 当前页面读取本项目自己的 `research_report.v1`；外部项目最多提供采集、重连、历史或存储能力，仍必须经过本项目的 canonical snapshot、质量门禁、信任摘要和发布前置条件映射。
2. **近期落地首选 CCXT，数据完整性首选 Tardis，可靠性设计首选 NautilusTrader。**
   - CCXT：最贴合当前 Python 边界，MIT，Deribit 同时覆盖 HTTP 与 WebSocket、public/private、option chain、Greeks、trades、order book，并内置限流和 WS 指数退避重连；缺点是没有持久化和长期历史数据资产。
   - Tardis Machine/SDK：最适合补齐真实历史 tick、逐笔、完整 L2、options chain 与本地压缩缓存；但历史数据是付费服务，开源的是客户端/本地服务，不是数据本身，而且不覆盖 private account。
   - NautilusTrader：Deribit adapter 的契约、盘口序列缺口恢复、令牌桶、心跳、重认证和订阅恢复最成熟；但整套 Rust/Python 交易引擎对当前零运行时依赖的研究控制台过重，应优先借鉴契约/测试，或隔离为只读 sidecar。
3. **Cryptofeed 的功能很合适，但 2026-07-12 GitHub 已标记 archived。** 它仍是“WS 采集 → 重连 → Redis/PostgreSQL/Kafka/QuestDB 等 backend”非常好的实现参考，不宜成为新的核心依赖。
4. **官方 Deribit GitHub 组织目前没有公开仓库。** 当前一手权威是官方 API 文档、示例与下载包；旧 `deribit-api` Python 包最后发布于 2017 年，且所指向的官方 GitHub 仓库已经不可访问，不应作为生产依赖。
5. **真实历史数据必须单独采购或自行长期采集。** 回放 fixture 只能证明解析与门禁；它不能证明当前行情、连续性、无缺口或账户真实性。

## 研究口径

- 只采用一手来源：项目 GitHub 仓库、README/源码/LICENSE/release、GitHub REST metadata、Deribit/Tardis/CCXT 官方文档。
- Stars、默认分支最近 push、release 和 archived 状态是 2026-07-12 快照；stars 只反映关注度，不等于生产适配度。
- “历史数据”严格区分：
  - 交易所当前/近期 HTTP 查询；
  - 用户自己的 private order/trade history；
  - 公共逐笔/L2 的长期归档；
  - fixture/replay 测试样本。
- “持久化”是项目自身是否提供可运行的存储/缓存路径，不把进程内滑动窗口算作持久化。
- License 仅作工程筛选，不构成法律意见。

## 官方 Deribit 是能力上限，也是判定基准

Deribit 官方明确提供 JSON-RPC over WebSocket、JSON-RPC over HTTP 和 FIX；WebSocket 是大多数实时场景的推荐接口。[API overview](https://docs.deribit.com/) [Quickstart](https://docs.deribit.com/articles/deribit-quickstart)

对本项目最重要的官方约束是：

- 每个 instrument 内事件有顺序，order book 提供 `change_id`/`prev_change_id` 用于连续性检查；跨 instrument 的时间本来就是异步的。[Market data best practices](https://docs.deribit.com/articles/market-data-collection-best-practices)
- 实时行情应使用订阅而不是 REST 轮询；期权集合应由 `instrument.state.option.<currency>` 生命周期通知维护，并可用 `public/get_expirations` 初始化/校验。[Market data best practices](https://docs.deribit.com/articles/market-data-collection-best-practices)
- raw book/trade 数据量大且 raw public feed 需要认证；普通研究 Dashboard 通常应使用 100ms 聚合流，只有确需逐 tick 时才用 raw。[Market data best practices](https://docs.deribit.com/articles/market-data-collection-best-practices)
- `public/get_instruments`、subscribe 和 matching-engine 请求各有不同 credit/burst 限制；触发 `10028` 可能导致会话断开，客户端必须等待 credit 恢复后重连。[Rate limits](https://docs.deribit.com/articles/rate-limits)
- 官方文档所说“永久保留”的历史记录是列出的 **private** user orders/trades；它不是公共 L2/全市场逐笔档案。[Historical trades and orders](https://docs.deribit.com/articles/accessing-historical-trades-orders)
- Dashboard/监控只需 private read 时，应使用 read-only scope，不授予任何 `:write` 权限。[Creating API keys](https://docs.deribit.com/articles/creating-api-key)

### 官方 clients 的现状

- [Deribit GitHub 组织](https://github.com/deribit) 在 2026-07-12 显示“no public repositories”。
- Deribit Dev Hub 仍提供 Python/Rust、Java、FIX 下载包和官方示例，但这些是下载包，不具备可公开审计的 GitHub stars、commit 活跃度或清晰仓库级 license。[Deribit Dev Hub](https://insights.deribit.com/dev-hub/)
- 旧 [PyPI `deribit-api`](https://pypi.org/project/deribit-api/) 最新版为 1.1.1（2017-09-10），其 README 指向的 `deribit/deribit-api-python` 已不可访问。

因此，“官方 client”适合作为协议/行为基准和最小示例来源，不适合作为当前项目的可持续依赖。

## GitHub 维护与许可快照

| 项目 | Stars | 默认分支最近 push / 最新 release | License / 状态 | 一手来源 |
|---|---:|---|---|---|
| Deribit 官方 API/下载包 | N/A | 官方文档持续更新；无公开 repo | 下载包 license/维护历史不可公开审计 | [GitHub org](https://github.com/deribit) · [Docs](https://docs.deribit.com/) |
| CCXT | 43,290 | 2026-07-12 / v4.5.64 (2026-07-03) | MIT；活跃 | [metadata](https://api.github.com/repos/ccxt/ccxt) · [release](https://github.com/ccxt/ccxt/releases/tag/v4.5.64) · [license](https://github.com/ccxt/ccxt/blob/master/LICENSE.txt) |
| NautilusTrader | 24,630 | 2026-07-12 / v1.230.0 (2026-06-29) | LGPL-3.0；活跃 | [metadata](https://api.github.com/repos/nautechsystems/nautilus_trader) · [release](https://github.com/nautechsystems/nautilus_trader/releases/tag/v1.230.0) · [license](https://github.com/nautechsystems/nautilus_trader/blob/develop/LICENSE) |
| Cryptofeed | 2,867 | 2026-02-01 / v2.4.1 (2025-02-08) | GitHub `NOASSERTION`，实际为带额外署名条款的 permissive 文本；**archived** | [metadata](https://api.github.com/repos/bmoscon/cryptofeed) · [license](https://github.com/bmoscon/cryptofeed/blob/master/LICENSE) |
| Tardis Machine | 305 | 2026-07-10 / 16.6.2 (2026-07-10) | MPL-2.0；活跃 | [metadata](https://api.github.com/repos/tardis-dev/tardis-machine) · [release](https://github.com/tardis-dev/tardis-machine/releases/tag/16.6.2) |
| Tardis Node | 353 | 2026-07-10 / 16.6.3 (2026-07-10) | MPL-2.0；活跃 | [metadata](https://api.github.com/repos/tardis-dev/tardis-node) · [release](https://github.com/tardis-dev/tardis-node/releases/tag/16.6.3) |
| Tardis Python | 146 | 2026-07-03 / 4.2.1 (2026-07-03) | MPL-2.0；活跃 | [metadata](https://api.github.com/repos/tardis-dev/tardis-python) · [release](https://github.com/tardis-dev/tardis-python/releases/tag/4.2.1) |
| OpenBB | 70,477 | 2026-07-08 | AGPL-3.0；活跃 | [metadata](https://api.github.com/repos/OpenBB-finance/OpenBB) · [license](https://github.com/OpenBB-finance/OpenBB/blob/develop/LICENSE) |
| VeighNa `vnpy_deribit` | 21 | 2023-06-05 / 2.0.1.1 (2021-09-24) | MIT；维护陈旧 | [metadata](https://api.github.com/repos/veighna-global/vnpy_deribit) · [release](https://github.com/veighna-global/vnpy_deribit/releases/tag/2.0.1.1) |
| RiveChen `deribit-historical-data` | 31 | 2026-05-26 / 无 release | MIT；近期活跃但项目较新 | [metadata](https://api.github.com/repos/RiveChen/deribit-historical-data) · [license](https://github.com/RiveChen/deribit-historical-data/blob/main/LICENSE) |
| schepal `deribit_data_collector` | 73 | 2020-08-29 / 无 release | 无明确 license；陈旧 | [metadata](https://api.github.com/repos/schepal/deribit_data_collector) |
| `binance-deribit-btc` | 381 | 2026-06-22 / 无 release；仓库创建于 2026-06-07 | MIT；非常新，不能仅凭 stars 判成熟 | [metadata](https://api.github.com/repos/beijingcao/binance-deribit-btc) · [license](https://github.com/beijingcao/binance-deribit-btc/blob/main/LICENSE) |

## 能力矩阵

“是”表示仓库当前源码/文档明确覆盖；“部分”表示只覆盖一个切面或必须自行补充关键能力。

| 项目 | Public / Private | HTTP / WS | 期权链 / Greeks | 逐笔 / Order book | 长期历史 | 持久化 | 重连与限流 | 对当前 Dashboard 的直接贡献 |
|---|---|---|---|---|---|---|---|---|
| 官方 Deribit API | 是 / 是 | 是 / 是 | 是 / 是 | 是 / 是 | 部分：private orders/trades；公共 L2 需自采 | 无客户端存储 | 规范完整，实现自负 | 协议基准；仍需本地 adapter、存储与质量门禁 |
| CCXT | 是 / 是 | 是 / 是（Pro） | 是 / 是 | 是 / 是 | 交易所接口可取范围；无长期公共档案 | 无 | REST 内置限流；Pro 指数退避重连 | **高：最快补当前链、ticker、book、account 输入** |
| Cryptofeed | 是 / 是；部分市场流需认证 | 部分 REST / 是 | instrument parser 有 option；不提供完整 surface | trades、L1/L2、ticker、OI、liquidations | 部分 REST；不自带历史资产 | Redis、PostgreSQL、Mongo、Kafka、InfluxDB、QuestDB 等 | 指数退避重连、超时重启、429 retry | 高，但 archived 使新核心依赖风险过大 |
| NautilusTrader | 是 / 是 | 是 / 是 | option、option combo、expirations、Greeks/DVOL | trades、snapshot/delta、gap 自动 resync | Deribit 可查询范围 + 自建 catalog | Parquet catalog；Redis/Postgres cache | **最完整：token bucket、heartbeat、重认证、订阅恢复** | 高；完整引擎嵌入成本也最高 |
| Tardis Machine/SDK | **仅 public market data** | 是 / 是 | 历史 options_chain；实时可走原生/normalized stream | tick trades、完整 L2 snapshot+delta | **是，Deribit 自 2019-03-30；托管服务** | 本地压缩磁盘 cache | Node 实时流自动处理 closed/stale reconnect | **高：历史、盘口与回放；不能补 private account** |
| OpenBB Deribit provider | public / 否 | HTTP + 一次性 WS | **是 / 是** | ticker；不提供持续 L2 collector | futures 历史；非完整 options tick/L2 | 无 | 每 expiry 建 WS、2 秒 timeout；非长期 daemon | 中：适合 options-chain schema/展示，不适合生产采集 |
| VeighNa `vnpy_deribit` | 是 / 是 | 否 / 是 | 是 / ticker Greeks | ticker、book | 否；源码 `query_history` 未实现 | gateway 本身无 | 基础 WS client 重连；本 adapter 无清晰限流层 | 低：可参考字段映射，不宜直接接入 |
| RiveChen 历史下载器 | public / 否 | 是 / 否 | 只枚举 option instruments；无实时链/Greeks | **public trades**；无 L2 | **全部 public trades**（按 trade sequence） | JSONL + SQLite checkpoint + Parquet | 20 RPS limiter、429 `Retry-After`、指数退避 | 中：只补历史逐笔，不会让实时 Dashboard 全绿 |
| schepal collector | public / 否 | 是 / 否 | 当前链、mark IV/OI | 否 / 否 | 只算历史波动率，不是逐笔/L2 档案 | 可写 CSV | 无生产级重连/限流证据 | 低：过时且无 license，只能参考输出字段 |
| `binance-deribit-btc` | 是 / 是，含交易 | 是 / 是 | 扫描 Deribit BTC options | 有实时监控，非通用数据产品 | 非市场历史产品 | Redis 状态 + SQLite 交易/权益 | preflight、systemd restart、运行监控 | 仅参考 preflight/状态恢复/UI；**执行能力必须隔离** |

## 逐项评价

### 1. CCXT：近期最现实的只读 adapter 候选

一手证据：

- Deribit REST/HTTP adapter 明确声明 `option=true`、`fetchOptionChain`、`fetchGreeks`、`fetchVolatilityHistory`、`fetchTrades`、`fetchOrderBook`、`fetchBalance`、positions/orders 等能力。[Deribit adapter](https://github.com/ccxt/ccxt/blob/master/python/ccxt/deribit.py)
- Pro adapter 明确支持 `watchTicker(s)`、`watchTrades`、`watchOrderBook`、`watchBalance`、`watchOrders` 和 `watchMyTrades`。[Deribit Pro adapter](https://github.com/ccxt/ccxt/blob/master/python/ccxt/pro/deribit.py)
- CCXT REST rate limiter 默认启用；CCXT Pro 文档说明 streaming 默认应用限流与指数退避重连。[CCXT manual](https://github.com/ccxt/ccxt/wiki/manual) [CCXT Pro manual](https://docs.ccxt.com/docs/pro-manual)

对本项目的价值：

- 可快速实现一个 `CcxtDeribitProvider -> canonical market_snapshot/account_payload` 的只读适配器。
- 一个统一 Python API 可同时拉期权链、Greeks、盘口、逐笔和只读账户，减少手写 JSON-RPC endpoint 漂移。
- MIT，且与当前 Python 3.12 边界匹配。

不能直接解决的部分：

- CCXT 的 WS cache 是进程内滑动窗口，不是持久化历史库；必须自己写 raw event log、snapshot version、gap evidence 和恢复 checkpoint。
- 统一模型会隐藏一部分 Deribit 特有语义；必须保留 raw payload、instrument name、settlement currency、contract size、inverse/linear 标记和 exchange sequence。
- 引入 CCXT 是新依赖，需单独批准；在批准前可先作为 shadow/conformance oracle，不替换现有 stdlib adapter。

集成成本：**中**。风险：模型归一化丢语义、依赖体积、对 Deribit 特有字段覆盖不足。

### 2. Cryptofeed：最贴近“采集 → 存储”的 Python 参考，但已归档

一手证据：

- Deribit handler 支持 option symbol，public/private subscription，trades、L1/L2 book、ticker、funding、open interest、liquidations、orders、fills 与 balances，并检查 order-book sequence。[Deribit source](https://github.com/bmoscon/cryptofeed/blob/master/cryptofeed/exchanges/deribit.py)
- README 提供 Redis、PostgreSQL、MongoDB、Kafka、InfluxDB、QuestDB、RabbitMQ、ZeroMQ 等 backend。[README backends](https://github.com/bmoscon/cryptofeed#backends)
- connection handler 对断线/异常执行指数退避重连，对 stale connection 重启；HTTP 层可在 429 后等待重试。[connection handler](https://github.com/bmoscon/cryptofeed/blob/master/cryptofeed/connection_handler.py) [connection layer](https://github.com/bmoscon/cryptofeed/blob/master/cryptofeed/connection.py)

对本项目的价值：

- 最值得借鉴 callback envelope、raw/normalized 双写、sequence gap、backend sink 和 backpressure 形状。
- 若项目决定自建 collector，可把其状态机变成自己的测试规范，而不是复制 archived 依赖。

不能直接解决的部分：

- GitHub 已 archived；未来 Deribit API 漂移无人保证修复。
- License 文本虽 permissive，但 GitHub `NOASSERTION` 且带额外署名条款，需依赖审查。
- 它是数据采集框架，不提供本项目的信任门禁、发布 readiness 或 account replay contract。

集成成本：**中到高**。结论：**reference-only**。

### 3. NautilusTrader：最成熟的 Deribit 数据可靠性实现

一手证据：

- 官方 integration guide 明确覆盖 live market data、execution、HTTP、WS、options、option combos、active expirations、historical trades、DVOL 和账户/订单。[Deribit integration](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/integrations/deribit.md)
- order book 通过 `change_id/prev_change_id` 检测 gap；发生缺口时停止 delta、unsubscribe、resubscribe 获取新 snapshot，然后恢复发布。
- adapter 有 HTTP/account/order/WS subscription token buckets、30 秒 heartbeat、重连时重认证和 subscription recovery，并为 recoverable error 提供 retry 配置。[Deribit integration: rate and connection management](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/integrations/deribit.md#rate-limiting)
- 框架提供 Parquet data catalog，以及可配置的 Redis/Postgres cache persistence。[Persistence API](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/api_reference/persistence.md) [Cache persistence](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/cache.md)
- 仓库具有大量真实协议形状的 Deribit fixtures 与 adapter tests，不只是 README 示例。[test data](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/adapters/deribit/test_data) [tests](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/adapters/deribit/tests)

对本项目的价值：

- 直接借鉴 `instrument provider / public data client / private execution client` 分离。
- 直接借鉴 `snapshot -> delta -> sequence gap -> REST resync -> evidence` 状态机和 fixtures。
- 如果必须复用运行时代码，优先评估独立 `nautilus-deribit` crate/只读 sidecar，而不是把整个交易引擎嵌入 Web API。

不能直接解决的部分：

- LGPL-3.0、Rust/PyO3 构建、运行时体量和 execution surface 都扩大当前项目边界。
- 它提供基础设施，不提供已采集的 Deribit 长期数据资产。
- 必须物理隔离 execution client，保持本项目 `RESEARCH_ONLY / NO_TRADE / NO-GO`。

集成成本：完整嵌入 **高**；只读 sidecar **中到高**；借鉴契约/测试 **低**。

### 4. Tardis：真正补历史与 L2 的方案，但数据服务是付费的

一手证据：

- Tardis 提供 Deribit 自 2019-03-30 起的公共历史数据，包含 trades、incremental L2、book snapshots、quotes、derivative ticker、liquidations 和 options_chain；首日样本可免费，完整访问需要订阅/API key。[Data FAQ](https://docs.tardis.dev/faq/data) [CSV overview](https://docs.tardis.dev/downloadable-csv-files/overview) [Billing](https://docs.tardis.dev/faq/billing-and-subscriptions)
- Tardis Machine 是本地可运行 HTTP/WS 服务，具有透明压缩磁盘缓存，并可在相同接口上切换 historical replay 与 consolidated real-time。[Tardis Machine](https://github.com/tardis-dev/tardis-machine)
- Node SDK 支持直接连接交易所 public WS 的实时流、closed/stale connection 自动重连、full order-book reconstruction 和本地 cache；Python SDK 当前重点是历史 replay/CSV download。[Tardis Node](https://github.com/tardis-dev/tardis-node) [Tardis Python](https://github.com/tardis-dev/tardis-python)
- Tardis 明确说明 raw 数据原样保存，可能包含异常值，且因交易所停机或采集故障仍可能有永久 gap；消费者必须继续做验证和 incident-aware quarantine。[Data FAQ](https://docs.tardis.dev/faq/data)

对本项目的价值：

- 最快获得真实、可版本化的 options/trades/L2 历史，用于 backtest alignment、walk-forward、gap 检查和生产级 replay。
- `tardis-machine` 可作为隔离 sidecar，本项目继续保持零依赖核心，通过 HTTP/WS 读取。
- 能明确区分“实时直连”和“付费历史”，避免拿 fixture 冒充历史资产。

不能直接解决的部分：

- 不提供 private account、margin、positions 或 user order history。
- 历史是商业服务；必须评估价格、数据授权、缓存保留和 vendor lock-in。
- Tardis 原样保存坏值，不替代本项目的数据质量门禁。

集成成本：Machine sidecar **中**；直接 Node/Python SDK **中**。商业与合规风险：**中**。

### 5. OpenBB：成熟的 options-chain schema/展示参考，不是生产 collector

一手证据：

- Deribit provider 覆盖 BTC、ETH、XRP、SOL、BNB、PAXG options chains，以及 futures curve/info/history。[provider README](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/providers/deribit/README.md)
- options-chain fetcher 枚举 instruments 后，为每个 expiration 建立一次 WS，订阅 `ticker.<instrument>.100ms`，聚合 bid/ask IV、Greeks、OI、mark 等字段，并在 2 秒超时后给出 incomplete warning。[provider source](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/providers/deribit/openbb_deribit/models/options_chains.py)

价值：标准 model、字段元数据、typed query、provider response recordings 很适合借鉴到本项目 `/research/report` 与 Dashboard。

限制与风险：它不是持续 collector、没有 L2/persistence/private account；options provider 的每-expiry WS + 2 秒 timeout 不等同生产完整性，而且源码固定 `contract_size=1`，本项目不能照搬。主仓库 AGPL-3.0，且引入 pandas/numpy/pydantic/websockets 等重依赖。

集成成本：嵌入 **高**；schema/reference **低**。结论：**reference-only**。

### 6. VeighNa `vnpy_deribit`：字段映射可参考，运行时不推荐

README 声明支持 futures、perpetual 和 options；源码通过 Deribit WS JSON-RPC 完成 instruments、ticker/book、private account/positions/orders/fills，并输出 option Greeks。[README](https://github.com/veighna-global/vnpy_deribit) [gateway source](https://github.com/veighna-global/vnpy_deribit/blob/main/vnpy_deribit/deribit_gateway.py)

但是默认分支最后 push 在 2023-06-05，最新 release 在 2021；`query_history` 未实现，contract 标记 `history_data=False`，adapter 内也没有当前 Deribit credit-based limiter 的清晰实现。适合参考字段映射，不适合接管当前数据面。

集成成本：**高**。结论：**reference-only**。

### 7. RiveChen `deribit-historical-data`：免费的 public trade history 补充件

该项目从 Deribit History API 按 `trade_seq` 下载 BTC/ETH futures 和 options 的全部 public trades，提供 20 RPS limiter、`Retry-After`/指数退避、SQLite checkpoint、JSONL、Parquet merge/dedup 和 gap validation。[README](https://github.com/RiveChen/deribit-historical-data) [client](https://github.com/RiveChen/deribit-historical-data/blob/main/src/deribit_fetcher/client.py) [storage](https://github.com/RiveChen/deribit-historical-data/blob/main/src/deribit_fetcher/storage.py)

它能低成本补“历史逐笔”研究，却不能补实时 chain、L2、DVOL、private account 或数据授权保证。项目较新、stars 低，适合作为隔离 ETL/对照工具，不应成为在线 Dashboard 请求链的一部分。

集成成本：离线 ETL **低到中**。

### 8. schepal collector：精确命中旧式 options-chain 快照，但已不适用生产

仓库可下载 BTC/ETH 当前 option chain，并返回 last/mark IV/OI 等字段。[README](https://github.com/schepal/deribit_data_collector)

但是最后 push 在 2020 年，依赖锁定 pandas 1.0.3 / numpy 1.17.3，没有明确 license，也没有 WS、L2、private、持久化可靠性或现代限流。只能作为历史字段/Notebook 参考。

### 9. `binance-deribit-btc`：可借运维模式，不能借执行边界

该项目确有 Deribit BTC options 扫描、REST/WS client、Redis restart recovery、SQLite、preflight、Telegram 与 Flask monitor。[README](https://github.com/beijingcao/binance-deribit-btc)

但仓库创建于 2026-06-07，非常新；更重要的是它包含自动下单/对冲和交易状态。对本项目只能借鉴 preflight、health、状态恢复和 Dashboard 运维字段，禁止直接复用 execution path。

## 对截图中缺失项的逐项映射

| 当前缺失/红灯 | 外部项目能提供什么 | 仍需本项目完成什么 |
|---|---|---|
| `data_quality` / 市场数据缺失 | 官方 API、CCXT、Nautilus、Cryptofeed、OpenBB 可提供实时 chain/ticker；Tardis 可提供历史/实时 public | canonical normalization、timestamp/source lineage、quality flags、raw payload hash、fail-closed 状态 |
| `public_response_contract` | CCXT/Nautilus/Cryptofeed 可覆盖 success/partial/rate-limit/network/schema-drift 输入 | 继续维护本项目 response class、reason codes 与 replay contract；外部库异常不能直接映射为“validated” |
| `public_feed_graph_complete` | Nautilus/Cryptofeed/Tardis 最接近 chain + ticker + trades + L2；CCXT 可组合调用/订阅 | 把 option chain、ticker、order book、DVOL/index/spot、instrument lifecycle 变成可观测 feed graph，并证明 freshness/sequence continuity |
| `private_account_replay_contract` | 官方 read-only API、CCXT、Nautilus、Cryptofeed、VeighNa 有 private account/position/order 能力 | read-only scope、secret isolation、sanitized raw capture、deterministic replay、live-order impossible proof |
| `vol_surface` 与 candidates 为空 | CCXT/OpenBB/Nautilus 提供 chain/Greeks；Tardis 提供历史 chain | 仍由本项目做 bid/ask/depth、unit/settlement、no-arb、fit quality、candidate kill conditions |
| `walk_forward_calibration` / backtest alignment | Tardis 最完整；RiveChen 只补 trades；Nautilus 提供 catalog/replay 模式 | 版本化数据集、gap quarantine、训练/评估时间切分、vendor reconciliation、promotion evidence |
| `paper_ledger_persistence` / manual runbook | 外部市场数据项目不能解决 | 继续由本项目独立实现；不得因数据接通自动放开 paper/manual/live |

## 推荐落地组合

### P0：保留本项目 canonical contract，先做 provider 边界

不让 Dashboard 直接消费任一外部库对象。统一边界建议为：

```text
Provider raw payload
  -> immutable raw capture + source/time/hash
  -> canonical instrument/quote/book/account events
  -> response contract + feed coverage + sequence/freshness evidence
  -> research_report.v1
  -> /research/report -> Dashboard
```

这样既能切换 official/CCXT/Tardis/Nautilus，也不会让 vendor schema 穿透 UI。

### P1：CCXT 只读 shadow adapter

- 先只覆盖 `fetchOptionChain`、`fetchGreeks`、`fetchOrderBook`、`watchTicker`/`watchOrderBook` 和 read-only account。
- raw payload 与 CCXT normalized payload 双写；本项目 canonical validator 决定是否 validated。
- 禁用任何 create/edit/cancel/withdraw 能力；API key 只授予 read scope。
- 在正式加依赖前，先用固定时间/固定 instrument 做 current adapter vs CCXT differential probe。

### P1：Tardis Machine 历史 sidecar

- 只作为 public history/replay source，不进入 private/account 边界。
- 先用免费月首样本完成 options_chain/trades/L2 schema、sequence 与 gap probe，再决定是否采购。
- 保存 vendor dataset version、incident report、download checksum 和 license/entitlement evidence。

### P2：吸收 Nautilus 的恢复合同

- 把 sequence gap、resubscribe snapshot、heartbeat、retry bucket、re-auth、subscription restoration 变成本地状态机与回归 fixture。
- 除非单独完成 LGPL/构建/部署/执行隔离评审，否则不嵌入整个 engine。

## 最终排序

1. **CCXT — 最优近期集成候选。** 最快补 public/private HTTP+WS 与 option-chain/Greeks/order-book，MIT、活跃、Python 兼容；必须自建持久化和 Deribit 特有语义保真层。
2. **Tardis Machine + Tardis data — 最优历史与回放候选。** 能真正补 tick/L2/options-chain 历史和本地 cache；历史数据为付费服务，且不能补 private account。
3. **NautilusTrader Deribit adapter — 最优可靠性标杆。** 盘口 gap recovery、限流、心跳、重认证、订阅恢复和测试面最强；应先借契约/测试，完整嵌入成本高。

不建议作为新核心依赖：已 archived 的 Cryptofeed、陈旧的 `vnpy_deribit`、无 license 的 schepal collector、以及包含自动交易路径的 `binance-deribit-btc`。OpenBB 适合作为 options-chain schema/展示参考，不适合作为本项目的持续生产采集器。
