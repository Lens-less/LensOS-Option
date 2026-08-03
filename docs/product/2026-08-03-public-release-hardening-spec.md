# LensOS Option · 上线前加固 Spec（第二轮）

> 状态：提案 · 起草日 2026-08-03 · 前置文档 [2026-08-02-public-product-spec.md](2026-08-02-public-product-spec.md)
>
> 第一轮 spec 回答"要做什么"。本文档回答**"做完的这一版，为什么还不能挂出去"**，
> 并给出到可发布状态的完整修复计划。

---

## 0. 核查结论

**Codex 的完成情况报告基本属实，工程质量高。** 逐条核过：

| 声明 | 核查结果 |
| --- | --- |
| `793 passed, 1 skipped, 1249 subtests` | ✅ 独立复跑，完全一致（98.29s） |
| 两个文件只是 CRLF 标记，未覆盖用户文件 | ✅ `git diff` 无内容，index 与 HEAD 一致 |
| 静态站 17 文件、字节数与 SHA-256 全通过 | ✅ manifest 自洽 |
| 双门禁：`research_publication=GO` / `execution_authorization=NO-GO` | ✅ 存在且语义正确 |
| `published` 模式、48 小时停摆、五幕导航、VRP 温度计、公开 API、法务四页 | ✅ 均真实存在 |
| 8,991 行新增 / 64 文件 | ✅ 不是文档工程，是可运行产品 |

**但它不能上线。** 三路并行深审 + 独立核查共发现 **4 类阻断缺陷**：

1. **头条指标建立在一次未被察觉的 API 截断上**，并对外发布了三条与事实不符的元数据；
2. **不可再生数据的离线备份存在永久漏洞**，且"任务停了"这个最常见的故障不产生任何告警；
3. **公开投影不是 deny-by-default——50.7% 的发布字节绕过白名单**，已复现泄露；
4. **公开 API 在法律上不可使用**，辅助页语言与主站不一致。

> **审计覆盖说明（诚实标注）**：本轮共派出四路深审。指标数学、采集/发布运维、
> 发布管线与隐私/安全三路完成；**前端与信息架构一路因会话额度中断未完成**。
> 本文档中界面相关的结论（S-16 ~ S-23）来自我自己的浏览器实测与代码阅读，
> 覆盖面窄于其余三路——**§2 的界面部分应视为不完整**，R3 开工前建议补跑。

关键背景数据：**需要保护的不可再生资产只有 2.4 MB**（快照 2.1 MB + 历史 260 KB），
而它周围一次性的构建垃圾有 **56 MB**。没有任何理由让前者继续只存在于一台笔记本上。

---

## 1. 阻断项（BLOCKER · 上线前必须清零）

### B-1 · DVOL 历史未分页，头条建立在静默截断的数据上

**证据链（已对 live API 验证）：**

```
artifacts/history/btc-dvol.json:
  requested_days   : 1095
  observation_count: 1000        ← 少 95 天
  coverage_ratio   : 1.0         ← 谎报
  missing_day_count: 0           ← 谎报
```

`crypto_options_report/vrp.py:83-97` 的 `fetch_deribit_dvol_history` 只读
`result["data"]`。Deribit 的 `get_volatility_index_data` 单页上限 1000 行，
并在响应里返回 `continuation` 令牌。**全仓库产品代码零处引用 `continuation`。**

我直接打了 live API 验证：

```
请求 1095 天 → keys: ['data','continuation']，rows: 1000，
                continuation: 1699228800000 (= 2023-11-06T00:00:00Z)
分页 2 次   → 1,958 个唯一日观测，2021-03-24 → 2026-08-02，零缺日
```

**数据是有的，只是没去取第二页。**

**后果一：三条对外声明与事实不符。**

| 发布位置 | 声明 | 事实 |
| --- | --- | --- |
| `thermo.json` | `window_days: 1095` | 1000 |
| 首页 / `VrpOverview.tsx:72` | "三年经验百分位" / aria-label "VRP 三年时序" | 2.74 年 |
| `publication.py:1437`、`methodology.html:24` | "1095-day rolling window" | 1000 天 |
| `btc-dvol.json` | `coverage_ratio: 1.0`、`missing_days: []` | 真实覆盖 1000/1096 = 0.912，缺 96 天 |

`_coverage_from_observations`（`vrp.py:665-685`）只统计**首末观测之间**的缺日，
所以窗口起点被截断在结构上不可见——这就是它能一路带着"完美覆盖"发布出去的机制。

**后果二：头条百分位是错的。** 我用完整分页历史重算了 2026-08-02：

| 窗口 | n | percentile | band |
| --- | --- | --- | --- |
| 当前发布（1000 天截断） | 1000 | **0.558** | neutral |
| 规格声明的 1095 天 | 1095 | **0.523** | neutral |
| 全部可用历史 | 1171 | 0.525 | neutral |

偏差约 **3.5 个百分点**。今天它没跨越刻度带边界，所以结论不变——**但这是运气，不是设计**。
靠近 P70 或 P30 时同样量级的偏差会直接翻转对外结论。

**修复**：
1. `fetch_deribit_dvol_history` 加分页循环，消费 `continuation` 直到覆盖 `requested_days`；
2. 取不满请求天数时**必须失败关闭**并给出 reason code，不得静默返回短序列；
3. `_coverage_from_observations` 的分母改为**请求窗口**而不是首末观测跨度；
4. `window_days` / "三年" 全部改为从实际数据派生并发布，不得硬编码。

**注意下一个天花板**：标的历史 `--days` 默认 1200，当前 1201 天，可算 VRP 的点是 1171 个。
DVOL 修好后，**标的历史成为新的约束**。要支撑 1095 天窗口够用（1171 ≥ 1095），
但没有余量做更长窗口。

---

### B-2 · 1000 样本地板恰好等于 API 单页上限，零余量

`vrp.py:39` `MIN_VRP_SERIES_SAMPLE_COUNT = 1000`，而 API 单页正好返回 1000 行。

`series_sample_count` 是真实计数（无截断、无切片），所以它**不是伪造的**——
但它以**恰好一个样本**的余量通过门禁，而且只因为两个毫不相干的数字碰巧相等。

实测扰动：

| 扰动 | 样本数 | 结果 |
| --- | --- | --- |
| 基线 | 1000 | 发布 |
| 少一天 DVOL | 999 | **整站阻断** |
| 少一天标的 | 969 | **整站阻断** |
| 历史陈旧 20 天 | 980 | **整站阻断** |

这个闸门现在测的不是"样本够不够"，而是"API 有没有返回满一页"。
**B-1 修好后它自动获得 95 天余量，才开始真正起作用**——两个问题必须一起修。

---

### B-3 · 标的历史重复日期静默损坏 RV30，仍标记 `validated`

DVOL 侧强制"每 UTC 日一行"（`vrp.py:407-410`）。标的侧只检查时间戳递增
（`vrp.py:439-485`、`market_data.py:2982/3046`），**没有按日唯一性检查**。
`_values_by_date`（`vrp.py:501`）后写覆盖先写。

在 `btc-daily.json` 追加一条 2026-08-02 09:00 的重复行：

| | 发布值 | 含重复行 |
| --- | --- | --- |
| `rv30_percent` | 27.04826 | **28.193383** |
| `vrp_percent_points` | 8.46174 | **7.316617** |
| `percentile` | 0.558 | **0.493** |
| `status` | validated | **validated** ← 无任何 reason code |

**这不是假想场景。** `artifacts/logs/` 显示 2026-08-02 有两次采集
（08:55:33Z 和 09:00:14Z），都写同一个 `btc-daily.json`。
重采集改为追加而非替换的那天，头条就会静默变错。

**修复**：标的历史校验器补上与 DVOL 同款的按 UTC 日唯一性检查，重复即失败关闭。

---

### B-4 · 历史序列的百分位是扩张窗口，N=1 也标"极贵"

`_empirical_percentile`（`vrp.py:317-337`）用 `≤` 且**把当前观测算进自己的历史**，
所以 N=1 时按构造返回 1.0。发布的 `thermo.json` 序列第一行就是：

```json
{"observed_at":"2023-11-07T08:00:00Z","percentile":1.0,"band":"P90+"}
```

**一个观测算出来的"P90+ 极贵"，画在三年图上。** 1000 个点里有 99 个的百分位
窗口不足 100 样本，前 30 个不足 30 样本。全序列刻度带分布因此偏斜：

| 带 | 实测占比 | 真实滚动百分位应有 |
| --- | --- | --- |
| P90+ | 7.6% | 10% |
| P70+ | **10.6%** | 20% |
| neutral | 45.5% | 40% |
| P30- | 22.8% | 20% |
| P10- | 13.5% | 10% |

而且 `publication.py:1099-1110` 把 `percentile_sample_count` 从每个序列点里**剥掉了**，
所以 `thermo.json` 的消费者完全无法察觉这件事。

对照：`realized_vol.py:31` 对一个远不如它显眼的数字，在独立窗口不足 20 时就失败关闭。
这里没有任何逐点门禁。

**这正是 README 里那句话所反对的**："只出现三天的合约会靠三个读数排到最前面——
这正是这个项目到处在防的样本量错误。"

**修复**：逐点设最小窗口样本门禁（建议与序列地板同源），不足的点发布为
`percentile: null, band: null` 并在图上留空隙；把 `percentile_sample_count`
放回每个序列点。

---

### B-5 · 同步失败的那一天，永远不会被任何后续运行补传

`tools/capture-daily.ps1:868-877` — 已用真实 bare remote 复现：

```
day A  正常                          → 已推送
day B  操作者留了一个杂散文件 → 失败关闭  → rc=1，未推送
day C  清理后正常                     → 已推送

本地   : [A, B, C]
远端   : [A,    C]
永久缺 : B 那天的快照
```

`Invoke-EvidenceRepoSync` 的 `-SourceFiles` 只由**本次运行**的变量构造，
没有任何"本地有哪些快照还不在证据仓"的对账步骤。任何一次到达同步阶段的失败
——杂散文件、笔记本离线、令牌过期、非快进推送、`.gitignore` 命中（见 B-9）、
detached HEAD——都会把一个**瞬时**问题变成离线副本里的**永久**空洞，
而且日志、摘要、运行手册都不会报告"有 N 份本地采集不在证据仓里"。

**采集与同步本身是解耦的**（已验证：同步失败时本地快照完好，这一点做对了）。
问题是那份没被同步的采集**再也没人来接**。

**修复**：源文件清单改为**本地序列与证据仓内容的差集**，而不是本次运行的产物；
并在每次运行的摘要里发布 `unsynced_local_capture_count`。

---

### B-6 · 没有正向心跳；Actions 60 天自动停用无任何防护

系统里**每一条通知路径都是失败触发的**。而现实中最主要的失败模式
——**任务根本没有运行**——不产生任何失败事件：

- GitHub Actions 的 `schedule:` 在仓库 60 天无活动后**自动停用**。第一轮 spec
  两处点名了这个风险并把缓解分配给 WS-I。全仓库 grep
  `heartbeat|心跳|keepalive|60-day|auto-disable|UptimeRobot|Cronitor` —— **零命中**。
- GitHub 在高负载时也会静默丢弃计划运行。没有运行 = 没有失败 = 没有 webhook。
- 本地侧 `exit 1` 只进 Task Scheduler 的 `LastTaskResult`，无人轮询；
  笔记本关机则连结果都没有。

第一轮 spec 的验收标准"模拟一次采集中断，30 分钟内收到告警"**今天无法通过**。

**修复**：外部心跳（拉 `/api/v1/health.json` 比较 `stale_after`）+ 每日成功
ping（dead-man's switch）。这两者都不能依赖被监控的系统自己发消息。

---

### B-7 · workflow 把采集 gate 在通知配置上，密钥缺失直接跳过采集

`.github/workflows/publish.yml:39-55` 的 `Preflight explicit workflow config`
在 `CAPTURE_FAILURE_WEBHOOK_URL` 未设置时 `throw`。而 `Capture evidence`（:68）
**没有 `if: always()`**。

所以一个过期或误删的 webhook 密钥 = **当天完全不采集**。在临时 runner 上
没有本地副本兜底，这一天就此消失。

通知是**汇报**关切，绝不能有能力让一次采集消失。正确顺序是：先采集，
再因通知配置缺失让 job 硬失败。

---

### B-8 · 隔离守卫只检查路径，不检查仓库身份——产品仓的 worktree 能通过全部检查

`tools/capture-daily.ps1:396-419` 校验：不是产品根、不在产品树内、产品不在它里面、
是 git toplevel、有命名 remote、四个目录齐备、工作区干净。
**它从不比较 `git rev-parse --git-common-dir` 或 remote URL。**

产品仓的一个 linked worktree（`git worktree add ../evidence-worktree`）满足全部条件。
复现结果：

```
capture rc=0 status=ok
!! 私有采集序列被推进了产品仓自己的 origin：
   snapshots/btc-series/btc-chain-20260804T090000.json
```

这正是 `.gitignore:26` 和第一轮 WS-G0 第 1 条（"**不**放进产品仓"）要防的事。
**如果那个 origin 是公开仓，这是一次数据泄露，不只是仓库膨胀。**

**修复**：证据仓的 `git-common-dir` 不得解析到产品仓内部，且其 remote URL
必须与产品仓的每一个 remote URL 都不同。

---

### B-9 · 公开投影不是 deny-by-default：50.7% 的发布字节绕过白名单（已复现泄露）

主报告的投影**做得很好**：`_build_public_report`（`publication.py:292-322`）加约 15 个
`_project_*` 函数逐字段枚举，测试还锁死了顶层键集。**问题是另外三个文件是原样透传的**，
只经过一个 36 项的**黑名单**筛查：

- `publication.py:248` → `research/signal`
- `publication.py:249` → `research/series`
- `publication.py:997` → `api/v1/signal.json` 内嵌的 `"artifact": signal_payload`

**已复现的泄露。** 往信号产物里加一个不在黑名单上的键：

```python
p['operator_notes'] = {'account_equity_usd': 123456.78,
                       'sub_account': 'test-account', 'host': 'DESKTOP-TEST'}
```

结果：**发布成功，无任何报错**，四个值原样出现在 `research/signal` 与
`api/v1/signal.json` 里。对照组（用黑名单上的 `portfolio_risk`）被正确拦截。

字节占比：`research/series` + `research/signal` + `api/v1/signal.json` + `assets/*`
+ 两份 manifest = **519,795 / 1,024,611 字节 = 50.7% 在白名单之外**。

**为什么这是阻断而不是"严重"**：这两份产物由**不同的命令**（`validate-signal`、
`series-history`）生产，各自独立演进。将来任何一次引擎升级往 cohort 或序列行里
加一个字段，**它落地那天就是公开的**，而且是静默的。
`docs/api-public.md:14` 的措辞（"若包含私有/执行键则拒绝"）把这个弱点写成了设计。

**修复**：`research/signal` 与 `research/series` 也走显式白名单投影；
或者让生产命令自己声明 `public_fields`，发布器取交集。黑名单保留为第二层，不是唯一一层。

---

### B-10 · 公开 JSON API 在法律上不可使用

`terms.html` 自相矛盾：

> "All rights are reserved unless a separate written grant says otherwise."
> "Attribute the source when quoting the public JSON outputs."

**保留全部权利 = 没有任何授权可供引用**；同时又要求引用时署名，等于承认了一个
不存在的授权。仓库无 `LICENSE` 文件。

后果：WS-E 那套公开 API（kimpremium 式"CORS 放开、无需 key"）**今天没有人可以合法使用**。
它的全部价值取决于一个尚未做出的决定。

---

## 2. 严重项（SERIOUS · 上线前应清零）

### 数据与指标

| # | 问题 | 位置 |
| --- | --- | --- |
| S-1 | `missing_days` 系统性少报：缺一天标的会让 **31 个图上点消失**，而 `missing_days` 只列 1 天 | `vrp.py:283-286, 505-524` |
| S-2 | 无 VRP 评估日陈旧门禁。把地板降到 900 后，20 天陈旧的历史照样 `validated`、`reason_codes` 为空 | `vrp.py:230-249` |
| S-3 | 两条腿用不同的日界，且末根 K 未收盘。DVOL 是 00:00Z 桶，标的是 **08:00Z** 桶，按日期字符串 join → 恒定 8 小时偏移（可辩护但**未披露**）。采集时刻标的桶只走了 4%，被当作完整日收益年化：头条 8.46174，用已收盘 K 重算是 **8.15837**。**头条点与它被排序对比的 999 个历史点口径不同。** | — |
| S-4 | `_date_to_observed_at` 伪造时间戳：所有 1000 个点标 `08:00:00Z`，而 DVOL 观测在 `00:00:00Z` | `publication.py:1328-1331` |
| S-5 | forward-implied vs trailing-realized 的口径错配**全仓库零处披露**（DESIGN/README/docs/methodology/UI 均无） | — |
| S-6 | 同一统计三份实现：百分位在 `vrp.py:542` 与 `regime.py:552`（空输入行为不同，后者抛 `ZeroDivisionError`）；刻度带阈值在 `vrp.py:550` 与 `publication.py:1334` **各写一遍** | — |
| S-7 | **测试没有锁住 RV30 的数值行为。** 所有 `build_vrp_status` 测试都用常数价格列表，故 `RV_30 ≡ 0`。变异测试：`365→252` **15 passed**；RV 少乘 100（100× 单位错）**15 passed**；总体标准差替换样本标准差 **15 passed** | `tests/test_vrp.py:64-94` |

### 运维与数据资产

| # | 问题 | 位置 |
| --- | --- | --- |
| S-8 | 云端运行覆盖累积产物：临时 runner 上 `artifacts/` 为空，`series-history.json` 由单份快照重建、`capture-daily.log` 只剩本次行数，两者都在同步清单里，直接盖掉累积版本（快照本身安全，因按时间戳命名） | `capture-daily.ps1:480-506, 874` |
| S-9 | `try` 之前抛错 = 零日志、零摘要、零 webhook。已复现：一个无法识别的环境变量值 → `EXITCODE=1`，**未创建任何文件**。该区域含 `Get-EnvFlag`×3、`Ensure-Directory`、`Set-Location`——正是计划任务最常撞上的配置与环境故障 | `capture-daily.ps1:100, 649-671`（try 始于 751） |
| S-10 | 证据仓里任何命中同步路径的 `.gitignore` 会让同步**永久**失败（`git add --` 指名忽略路径时退出 1）。`*.log` 不是假设——产品仓自己的 `.gitignore:36` 就有这行。叠加 B-5 = 从此每天永久缺 | `capture-daily.ps1:557-558` |
| S-11 | 无 `concurrency:` 块；push 无 fetch/rebase/retry。两个 runner 重叠时第二次推送非快进失败，该采集只剩 90 天 artifact | `publish.yml` / `capture-daily.ps1:590` |
| S-12 | 部分降级快照被记为 `ok`：`pull-snapshot` 仅在 `fetch_errors and not rows`（**完全**失败）时返回阻断码。96 个里只抓到 12 个照样退出 0，无 webhook，一份稀薄横截面静默进入不可再生序列 | `cli.py:553-554` |
| S-13 | 通知通道：`Invoke-WebRequest` **缺 `-UseBasicParsing`**（5.1 下走 IE COM 解析器，在服务账户/精简镜像上抛错并被 catch 吞成 `delivered:false`）；单次尝试、无重试、非投递只写本地 JSON。测试只跑过 `127.0.0.1` 明文 HTTP，真实 HTTPS 路径从未执行 | `capture-daily.ps1:604-641` |
| S-14 | **无部署目标，所以 WS-G-5"失败时保留旧内容"是空的，不是满足的。** 且采集失败时 publish 步骤把 `workflow-failure.json` 写进 `dist/site` 后抛错，而上传步骤 `if: always()` + `if-no-files-found: error` 会**成功**上传一个单文件 blocked marker。**一旦有人接上消费该 artifact 的部署，那天就会用空站盖掉好站** | `publish.yml:190-196` |
| S-15 | README 的计划任务注册命令**关掉了本轮加的全部硬化**：无 `-FailureWebhookUrl`、无 `-EnableEvidenceRepoSync`、无 `-EvidenceRepoRoot`。照抄的操作者得到的是旧行为。且 `-ExecutionTimeLimit 15 分钟`，慢链路上刷新 1200+1095 天历史超时会被杀 | `README.md:220-230` |

### 发布管线与隐私

| # | 问题 | 位置 |
| --- | --- | --- |
| S-24 | **`.js` / `.css` 资产豁免全部隐私检查。** 已复现：往 bundle 追加含 `api_key` / `dk_live_test` / `portfolio_risk` / `123456.78` 的合成字符串后发布，**无报错，原样上线**。而这个 327 KB bundle **就是完整的内部 dashboard**——它已经带着 `margin_snapshot`、`portfolio_risk`、`account_status`、`max_new_margin_nav`、`reference_margin_usdc` 的渲染代码和内部 runbook 文案。今天不泄露**值**（SPA 在 `mode==="published"` 时运行期过滤），但私有界面的**形状**和内部 reason-code 目录是公开的，且该文件无任何守卫。Vite 的 `define:` / `import.meta.env` 一次改动就会把构建期字符串替换直接送上 CDN | `publication.py:1155-1156` |
| S-25 | **manifest 在隐私筛查之后写入，从不被筛查。** 已用合成路径复现：`git_sha` 传 `built from C:\Users\operator\... on host DESKTOP-TEST`、`--web-build` 目录名含 `C_Users_operator_secret_build` → **发布成功**，两处绝对路径进入 `manifest.json` 与 `.well-known` 副本。同样的字符串放进信号产物会被正确拦截。修复是一行：把 `_ensure_publication_privacy` 移到 manifest 写入之后 | `publication.py:262` vs `:272-273` |
| S-26 | **`research_publication = GO` 四项证据里三项是自证常量，且在证据存在之前就断言了。** `publish_manifest:"verified"` / `methodology:"present"` / `disclaimer:"present"` 全是硬编码，`research_publication_ready=True` 无条件传入；而 `methodology.html` / `disclaimer.html` 在 `:256-257`、manifest 在 `:272-273` 写入——**都在门禁已经认证它们"present/verified"之后**。把两个 HTML 写入器删掉，门禁照样 GO | `publication.py:187-196` |
| S-27 | 零安全响应头：无 CSP、`X-Content-Type-Options`、`Referrer-Policy`、`frame-ancestors`。对一个卖点是"我们不持凭证、不加载第三方"的站，`default-src 'self'` 几乎免费，能把这句话从"今天恰好为真"变成"被强制执行"。缺 `frame-ancestors` 意味着本站可被嵌套改皮成别人的交易信号——正是 `terms.html` 用文字禁止的那件事 | `publication.py:1385-1396` |
| S-28 | **CI 在失败时把 runner 绝对路径写进部署根目录，然后无条件上传。** `:107` 写 `workflow-failure.json`（含 `summary_path`）、`:163` 写 `publish-contract.json`（含**全部五条输入的绝对路径**加内部 reason code 与 runbook 文案），二者由 PowerShell 直接写进 `dist/site`，**从不经过 `_ensure_publication_privacy`**。今天没有部署步骤所以没上网；一旦接上 `wrangler pages deploy dist/site`，被阻断的那次运行发布的目录里**只有** runner 路径和内部代码 | `publish.yml:107,163,190-196` |
| S-29 | WS-E 的"每个数值字段都带 evidence class"未达成：`candidates.json` 的 `ev_after_cost_usdc` / `executable_credit_usdc` / `ranking_score` / `cvar_95_usdc` / `p_itm` / `authoritative_sample_size`，以及 `signal.json` 的全部 cohort 计数器，都没有相邻的 evidence class。消费者读到 `ev_after_cost_usdc: -199.72` 时，没有任何相邻字段告诉它这是未校准的筛选输出 | `publication.py:824-876, 990-998` |
| S-30 | `/research/*` 被 `docs/api-public.md:7-18` 列为公开 API 路径，但 `_headers` 只给 `/api/v1/*` 开 CORS。最大最丰富的那份产物（281 KB 的 `research/report`）跨源不可读。要么给它 CORS，要么别把它写进 API 文档 | `publication.py:1387-1396` |

### 产品与界面

> ⚠️ 本节覆盖不完整（前端深审中断）。以下为独立实测所得，不是穷尽清单。

| # | 问题 | 证据 |
| --- | --- | --- |
| S-16 | **`status.html` 结构上无法报告失败。** 它只是本次成功发布自身元数据的快照；发布挂了它就不再生成，永远停在"一切正常"。这与 `health.json` 正确避开的"静态布尔谎报"是同一个陷阱 | 已读全文 |
| S-17 | 五张辅助页（methodology/privacy/terms/disclaimer/status）**全英文**、`lang="en"`，用 Georgia 衬线 + `#f7f3ea` 米色纸底——与 `lang="zh-CN"` 的主站和 DESIGN.md 的视觉系统都不一致。免责声明用读者可能不读的语言写，法律保护力也更弱 | 已读全文 |
| S-18 | 候选工作台 `?view=workbench` **公开可达但无任何导航入口**。孤立界面得不到设计与 QA 关注——CHANGELOG 里记的正是这个 bug："两个界面的填充态从来没被人看见过，因此从来没被设计过" | 浏览器实测 |
| S-19 | 工作台 DTE 列全是 `—`（`ranked_candidates[*].dte_days` 全为 `None`），DTE 筛选器同样是死的。CHANGELOG 明确记录修过这个字段。且 DESIGN.md §14.1 禁止用 em dash 表示缺失（"never an em dash that could read as zero"） | 浏览器实测 + `research/report` |
| S-20 | 同一页两个矛盾的新鲜度：市场证据"数据年龄 **28,480 秒**"，进场条件"发布计算时数据新鲜度 通过 / 当次评估 **0 秒** / 要求 ≤60 sec"。读者无法调和。且 28,480 秒对外不可读，应为"约 7.9 小时" | 浏览器实测 |
| S-21 | 导航模型不自洽：①③⑤ 是同页锚点，②④ 跳到另一个视图。且**② "贵在哪里" 指向 `?view=series`（残差热力图）**，而真正回答"贵在哪里"的曲面证据在主页滚动流里；**③ "卖它值不值" 指向 `#framework`**，而真正做相对价值 vs 绝对 EV 对比的工作台没有入口 | `read_page` 实测 |
| S-22 | 静态站上的"刷新"按钮：拉的是同一份静态 JSON，永远不可能更新，却暗示实时数据 | `AppShell` |
| S-23 | 公开 UI 里有一列 `排序分`（`ranking_score`）。DESIGN.md §14.2："UI 必须不把单一混合数字呈现为'那个分数'" | `research/report` |

---

## 3. 次要项（MINOR）

- 主页最大的一块是 8 阶段"DECISION WORKFLOW"（采集/分析/结构/进场/风控/退出/监控/复盘），
  含"卖出腿距离 10.65%"、"参考盈亏平衡 $70,095"、"单份参考最大损失 $4,934"。
  措辞守住了 research-only，但对**公开访客**读起来像一份带价位的交易方案。
  内部工具没有这个风险（用户知道边界），公开站有。
- `research_publication = GO` 与 `data_status.evidence_class = degraded` 并存，
  站上没有向读者解释"降级证据仍然发布"是什么意思。
- `_headers` 是 Cloudflare Pages 专有格式；在 GitHub Pages / S3 上**静默失效**，
  CORS 与缓存策略全部不生效。文档未说明。
- 无 CSP / X-Content-Type-Options / Referrer-Policy。
- 无 `og:image`（只有 og:title/description），`twitter:card` 是 `summary` 而非
  `summary_large_image`。**对这一类产品，被截图分享的那个数字就是主要传播机制**，
  第一轮 WS-J 要求的"含当日 VRP 数值的动态 OG 卡"未做。
- 无 `robots.txt` / `sitemap.xml`。
- 无日环比。kimpremium 的核心回访理由是 `alert.level` 的**变化**；
  LensOS 每天发布，但页面上没有任何"较昨日"的信息。
- 无历史版本存档。每次发布覆盖上一次。今天的 manifest 可验证，
  **昨天的结论无法验证**——这削弱了本项目最核心的可复算主张，
  也让 M4"成绩单"未来无法回溯"发布当天到底说了什么"。
- 无机器可读 API schema。kimpremium 在 `/api/openapi.json` 发布 OpenAPI 3.1。
- `thermo.json` 单文件 207 KB，整站一次加载约 1.0 MB（未压缩）。
- `sample_count`（百分位窗口计数）与 `minimum_series_sample_count`（序列长度地板）
  是两个不同统计量，并排发布且今天恰好相等（因 B-1），易被误读。
- `thermo.json` 的 `schema_version` 是 **`vrp_status.v1`**——内部 schema，不是像其他端点那样的
  `public_*.v1`。内部 VRP schema 一升版，公开 API 就跟着静默升版。
- 刻度带枚举混用两套词汇：`P90+` / `P70+` / `P30-` / `P10-` / **`neutral`**。
  `_project_vrp_band` 在两端返回 `P90+/P70+/P30-/P10-`，中间**穿透上游原值**；
  而 `methodology.html` 声明的词汇表是 `P90+ / P70+ / P30-P70 / P30- / P10-`
  ——**`neutral` 根本不在里面**。按 `band` 做 switch 的消费者会漏 case。
- `docs/api-public.md` 与实际产出不匹配：没有文档里有而实际没有的（好），
  但未文档化的产出很多——每个端点的 `schema_version`、5 个端点的
  `disclaimer_url`/`methodology_url`、health 的 `status_url`、thermo 的
  `captured_at`/`published_at`/`evidence_class`，以及 `candidates.json`（10 键）、
  `signal.json`（6 键）、`manifest.json`（15 键）的**整个 body**。
  WS-E 要求的"逐字段数据字典 + curl 示例"：无 curl 示例，`summary.vrp` 之外无逐字段类型/单位。
- 五张生成页**彼此之间没有任何导航链接**，页脚也没有免责声明文字或
  `/disclaimer.html` 链接——而第一轮 spec §8 要求"页脚每页有免责声明"。SPA 页脚两样都有。
- `evidence_class: "degraded"` 没有公开数据字典。`api-public.md:42` 只说它是
  "the report's data-trust verdict"，不枚举取值也不解释含义；五张 HTML 页里
  一次都没出现这个词。
- `research/report|signal|series` 无扩展名，`_headers` 也不设 `Content-Type`，
  主机会按 `application/octet-stream` 发；叠加缺 `nosniff`，既是（小的）MIME 嗅探面，
  也让浏览器下载而不是显示。
- `marketModel.ts:88-94` 用 `Math.abs(value) <= 2 ? value*100 : value` **猜单位**，
  而 `summary.json` 的 `field_evidence` 已显式声明单位。
- `Add-Content -Encoding utf8` 在 5.1 下写 **BOM**、在 Actions 的 pwsh 7 下不写，
  同一文件编码随执行车道翻转，在证据仓里产生整文件伪 diff。
- `Write-CaptureSummary` 在同步阶段**之前**调用，所以复制进证据仓的摘要
  永远不可能包含 `evidence_repo_sync` 的结果。
- `README.en.md` 自 `7dce936` 未更新，完全没有 publish / VRP / 静态公开版的内容，
  而 `README.md` 首行就链接它。
- `docs/README.md` 文档地图**未收录**三份新文档（`api-public.md`、
  `public-publishing.md`、本轮产品 spec）。按该地图自己的约定
  "文档存在本身不代表它是当前的验收契约"，三份承重文档目前不是契约。
- `CHANGELOG.md` 三个发布提交**零条目**（此前每个提交都写）。
- README 开篇仍是"一个期权入场前的研究工具"+"两种使用形态（Web 工作台 / Chrome 伴侣）"，
  公开观测台是第 72 行的一个小节。定位未重新居中。第一轮 WS-K 建议把 Chrome 伴侣
  移出首发范围，未执行。

---

## 3.5 已核验为干净（不要在这些地方花时间）

这些是被**执行验证过**的，不是读代码读过去的。列在这里是为了避免返工，
也因为其中几项做得确实好：

| 领域 | 结论 |
| --- | --- |
| **确定性 / 可复算** | ✅ **从仓库输入逐字节复现了 `site-final-5587795`**（`manifest_sha256 7df87900…` 吻合）。两次独立运行 19 个文件哈希全等。无墙钟读取、无字典序漂移、无浮点 repr 漂移。`published_at` 确实污染 19 个文件里的 12 个哈希，但 `input_hashes.*` 与 `analysis_record_sha256` 与它无关——**可复算主张不是空话** |
| **失败关闭** | ✅ 14/14 场景全部正确阻断：缺 DVOL、空 DVOL、DVOL 不足 1000、标的陈旧、标的全在采集时刻之后、截断的 series/snapshot JSON、`published_at < captured_at`、输出路径是文件、五种真实数据质量失败。**每一次都零残留**。且被阻断的发布无法覆盖已有好目录（`_prepare_output_directory` 拒绝非空目标，已验证） |
| **执行门禁** | ✅ 四层防御，攻不动。`build_release_gates` 根本没有能影响执行的参数；15 个环境变量开关试过 → 仍 NO-GO；kwarg 注入 → `TypeError`；从快照顶层、`full_system_surface.release_gates`、信号产物三处注入 → 全部被 `publication.py:218` 无条件覆盖。SPA 再独立校验一次 |
| **时效契约** | ✅ 做得好。`next_expected_at` / `stale_after` 由 `PUBLISH_INTERVAL` **派生而非硬编码**；无任何静态布尔谎报；SPA 用 1 秒 `setInterval` + 真实墙钟算 `ageSec`，`expired && published` → 整个 `<main>` 换成停摆卡片，**VRP / DVOL / 曲面 / 候选 / 策略各自独立渲染停摆态**，值全部隐藏 |
| **供应链 / 隐私声明** | ✅ 站内唯一的外部 URL 是 React 错误模板里的 `react.dev` 字符串（从不请求）和 XML 命名空间常量。零 `url()`、零 `@font-face`、零 analytics、零 CDN。favicon 是 inline data URI。**`privacy.html` 的声明是真的** |
| **manifest 自洽** | ✅ 17 项列表与磁盘字节数、SHA-256 全部吻合。磁盘 19 个文件，两份 manifest 自身排除在外且**在 `manifest_policy.self_hash_excluded_paths` 里显式声明**——自哈希缺口是承认的，不是隐藏的 |
| **构建产物卫生** | ✅ `.gitignore` / `.dockerignore` 覆盖完整，`git ls-files artifacts` 为空。对全部 17 份站点副本做真实路径正则扫描，零命中 |
| **测试质量（发布侧）** | ✅ 777 行零 mock、零 monkeypatch，全部真实临时目录 + 真实重读重哈希，其中一条起了真实 `ThreadingHTTPServer` GET 全部 17 条路由。**这是好的那种测试** |
| **采集与同步解耦** | ✅ 同步失败不会毁掉本地采集（已验证）。这一点做对了——问题是那份没同步的采集再也没人来接（B-5） |
| **cron 时刻 / 去重 / 密钥** | ✅ `10 8 * * *` 在 08:00 UTC 结算后 10 分钟，Actions cron 只会晚不会早。`(日期 × 合约)` 去重对新产物仍成立，两条采集车道文件名不可能撞。两个 workflow 都不在 `pull_request` 上触发，无 fork 取密钥路径，webhook URL 在日志与摘要里都是 `redacted`（有测试） |
| **PowerShell 5.1 正确性** | ✅ 零 `&&`/`\|\|`/三元/`??`/`-AsHashtable`；JSON 走显式 `UTF8Encoding($false)` 而非 `Set-Content`；`2>` 处理是**知情的**（存/改/`finally` 恢复 `$ErrorActionPreference`，并注释了 `git push` 成功时也写 stderr） |
| **reparse point 守卫** | ✅ 不只是看起来对。`-Force` + `ReparsePoint` 属性位是正确写法，`GetFullPath` 归一后逐段重查祖先。试过从目标祖先、证据仓根本身、硬链接三个方向绕，全被挡。无 `--force`、无 `+refs` |
| **VRP 单位与前瞻偏差** | ✅ 年化因子确实是 365 不是 252：独立从 `btc-daily.json` 重算 2026-08-02 得 **27.048260**，与发布值六位全等。无任何未来观测进入任何一点 |
| **百分位窗口语义 / 刻度带边界** | ✅ `window_days` 确实是**日历日**而非观测数（合成数据验证）；八个边界探针全部符合规格，`extremely_thin` 可达，`0.558 → neutral` 正确 |

---

## 4. 修复计划

### 阶段 R0 · 止血（今天，0.5 天）

**这不是工程任务，是配置任务，但它是全部工作里唯一有永久损失风险的。**

1. 建立独立私有证据仓，配置 `LENSOS_EVIDENCE_REPO_SLUG` / `..._SYNC_ENABLED=true` /
   `LENSOS_EVIDENCE_REPO_PUSH_TOKEN` / `CAPTURE_FAILURE_WEBHOOK_URL`。
   **今天开关还是 `false`，11 份不可再生快照仍只在这台笔记本上。**
2. 手工推送当前基线（2.4 MB，一次推送的事）。
3. 证据仓加 `.gitattributes`（`* -text`），**不要**加任何会命中 `snapshots/`、
   `history/`、`logs/`、`reports/` 的 `.gitignore`（见 S-10、M3）。
4. 本地计划任务重新注册，带上 `-FailureWebhookUrl` / `-EnableEvidenceRepoSync` /
   `-EvidenceRepoRoot`，`-ExecutionTimeLimit` 提到 45 分钟（S-15）。

### 阶段 R1 · 指标可信（3 天）

修 B-1 → B-4 与 S-1 ~ S-7。顺序有依赖：

1. **B-1 分页** —— 先做，因为 B-2 的余量依赖它。取不满即失败关闭。
2. **B-2** 地板与页大小解耦；B-1 修好后 1095 天窗口有 95 天余量。
3. **B-3** 标的历史按 UTC 日唯一性校验。
4. **B-4** 逐点最小窗口门禁；不足的点发 `null` 并在图上留空隙；
   把 `percentile_sample_count` 放回序列点。
5. **S-3/S-4** 统一日界：两条腿都对齐到 Deribit 08:00Z 结算界；
   **头条只用已收盘 K**，未收盘当日不进入序列（这会让头条滞后一天，是正确的代价）。
   去掉 `_date_to_observed_at` 的伪造时间戳。
6. **S-6** 百分位与刻度带阈值各收敛到一处实现。
7. **S-7 测试** —— 补：RV30 已知答案测试（手算对拍）、年化因子断言、
   标的侧无插值测试、重复日期测试、999/1000 地板边界、刻度带临界值
   （0.6999 / 0.3001 / 0.1001）。**变异测试作为验收手段**：
   `365→252` 与 100× 单位错必须让测试变红。
8. **S-5** 在方法论页和图注里披露 forward-implied vs trailing-realized 的口径错配。
9. 全仓库清理 "1095 / 三年" 的硬编码声明，改为从数据派生。

**验收**：把 `365` 改成 `252` 会让测试失败；删掉一天 DVOL 仍能发布（有余量）；
`coverage_ratio` 对齐请求窗口；序列首点的 `percentile` 为 `null` 而非 `1.0`。

### 阶段 R2 · 数据资产不可失（2.5 天）

1. **B-5** 同步源清单改为本地↔证据仓差集；摘要发布 `unsynced_local_capture_count`。
2. **B-6** 外部心跳 + 每日成功 ping（dead-man's switch）。两者都不能由被监控系统自己发。
3. **B-7** 采集先于通知配置校验；通知缺失让 job 事后硬失败，绝不跳过采集。
4. **B-8** 证据仓身份校验（`git-common-dir` + remote URL 比对）。
5. **S-8** 云端运行不同步全语料派生产物；日志改为追加。
6. **S-9** `try` 前移到脚本最开头，让任何抛错都能进日志与通知。
7. **S-11** 加 `concurrency`；push 加 fetch/rebase/retry。
8. **S-12** 部分降级快照阈值化（如有效行 < 60% 记为降级并告警）。
9. **S-13** 加 `-UseBasicParsing`、重试与退避；补一条真实 HTTPS 投递测试。

**验收**：第一轮 spec 那条今天不通过的标准 ——"人为让一次采集失败，
30 分钟内收到告警" —— 必须通过；再加一条"停掉调度器 25 小时，收到心跳告警"。

### 阶段 R2b · 发布面收口（2 天）

安全审计给出的"先做这三件"，全部是小改动、高杠杆：

1. **B-9** `research/signal` 与 `research/series` 改走显式白名单投影
   （或让生产命令声明 `public_fields`，发布器取交集）。黑名单降级为第二层。
2. **S-25 + S-24 一起修**：把 `_ensure_publication_privacy` 从 `:262` 移到
   manifest 写入（`:273`）**之后**；删掉 `:1155-1156` 的 `.js`/`.css` 豁免，
   对 bundle 跑同一套 token 与路径正则。两处小编辑同时关掉两个洞。
3. **S-26** 把三个自证常量换成真断言：`publish_manifest` 只在 manifest 写完并与磁盘
   重新核过哈希后才算 verified；`methodology`/`disclaimer` 只在
   `(out_path / "*.html").is_file()` 为真后才算 present。**门禁计算移到最后**。
4. **S-5** `git_sha` 校验格式，并断言 `git status --porcelain` 为空（CI 里恒真，
   本地才是裸声明）。
5. **S-27** 加 CSP（`default-src 'self'`）、`nosniff`、`Referrer-Policy`、`frame-ancestors`。
6. **S-28** CI 的 `workflow-failure.json` / `publish-contract.json` 写到 `dist/site`
   **之外**；未来的部署步骤 gate 在 `steps.publish_site.outcome == 'success'`。
7. **S-29** 给 `candidates.json` / `signal.json` 的数值字段补 evidence class。
8. **S-30** 给 `/research/*` 开 CORS，或把它从 API 文档里拿掉。

**验收（每条都要能变红）**：往信号产物塞一个未列名的私有键 → 发布失败；
往 bundle 塞 `api_key` → 发布失败；`git_sha` 传绝对路径 → 发布失败；
**删掉 `methodology.html` → 门禁翻成 NO-GO**。

### 阶段 R3 · 可对外（3 天）

1. **B-10 许可证决策**（见 §6，需要你拍板）+ `LICENSE` 落地 + `terms.html` 消除自相矛盾。
2. **S-16** `status.html` 重做：改为消费**证据仓里的发布历史**（近 30 天每日
   发布成败、当日采集条数、被质量门禁挡掉多少、快照被排除数），
   并且**由外部心跳而非发布器自身**驱动"当前是否停摆"的判定。
3. **S-17** 五张辅助页中文化 + 并入 DESIGN.md 视觉系统（保留英文版作为 `/en/`）。
4. **S-18 ~ S-23** 界面修复：
   - 工作台要么给导航入口并纳入五幕，要么在公开发布中移除（**建议：纳入 ③**，
     因为它才是"卖它值不值"的真实答案）；
   - 修 `dte_days`；缺失值改为显式"不可用"而非 em dash；
   - 统一新鲜度呈现，进场条件表标注"按发布时钟评估"，页面年龄用小时；
   - 导航模型二选一（全锚点或全视图），②③ 指向修正；
   - 静态站移除"刷新"或改为"重新载入"；
   - `排序分` 列改为呈现前沿位置/被支配轴，或明确标注为非加权总分。
5. 免责声明补"非持牌投资顾问"。

### 阶段 R4 · 可传播（2 天，可与 R3 并行）

1. 动态 OG 卡（当日 VRP 数值 + 刻度带），`summary_large_image`。
2. `robots.txt` / `sitemap.xml` / CSP 等安全响应头。
3. **日环比**：`summary.json` 增 `change` 块（VRP 变动、百分位变动、刻度带是否切换），
   页面头条下一行显示"较昨日 +1.2 pt，仍为中性"。
   同时增 `alert`-风格字段供 agent 轮询（对标 kimpremium 的 `alert.level`）。
4. **历史版本存档**：发布到 `/editions/YYYY-MM-DD/`，`/` 指向最新。
   这是本项目可复算主张的必然要求，也是 M4 成绩单可回溯的前提。
5. OpenAPI 3.1 schema（`/api/openapi.json`）。
6. `thermo.json` 分片（近 90 天 + 按年归档），降低首屏负载。
7. 文档一致性：`README.md` 定位重新居中、`README.en.md` 更新、
   `docs/README.md` 收录三份新文档、`CHANGELOG.md` 补三个提交的条目。

### 阶段 R5 · 部署（1.5 天，依赖域名/托管决策）

1. 接部署目标；**部署必须 gate 在 `steps.publish_site.outcome == 'success'`**，
   不能 gate 在 artifact 存在（S-14）。
2. 保留最近 30 个版本 + 一条命令回滚（第一轮 WS-I 第 3 条，至今无实现无文档）。
3. 运行手册补齐四个恢复场景：连续缺采 3 天、证据仓损坏/分叉、坏发布回滚、令牌轮换。
   补 B-5 孤儿采集的手工补传流程、证据仓约束清单、以及**云端采集回流到本地**的路径
   （目前本地 `validate-signal` 永远看不到云端采集，"双采集"并没有真正扩大本地样本）。

---

## 5. 修订后的里程碑

```
R0   止血（配置）                       今天         0.5d   ← 唯一有永久损失风险的一项
R1   指标可信                           → 08-08      3d
R2   数据资产不可失                     → 08-12      2.5d
R2b  发布面收口（隐私 / 门禁 / 头）      → 08-14      2d
R3   可对外                             → 08-19      3d
R4   可传播（与 R3 并行）               → 08-19      2d
R5   部署                               → 08-22      1.5d
────────────────────────────────────────────────────────
补跑：前端与信息架构深审（本轮中断）      R3 开工前     —
正式对外                                ≈ 2026-08-23（原计划 08-31，仍有余量）

M4  信号验证出结论                      ≈ 2026-09-26（不变，数据决定）
    当前：4 个 cohort 在途（08-07 / 08-14 / 08-21 / 08-28），需 8 个
          11 份快照，1 份因 MARKET_DATA_QUALITY_FAIL 被剔除（约 9% 损耗）
```

净工时约 14.5 人日。**关键路径是 R1 → R2b → R3**；R0 与其余全部工作独立，今天就该做完。

---

## 6. 需要你拍板的决策

| # | 决策 | 建议 | 不决的后果 |
| --- | --- | --- | --- |
| D-1 | **许可证** | 代码 Apache-2.0；数据产物 CC BY 4.0 | 公开 API 无人可合法使用，WS-E 的价值为零 |
| D-2 | **域名 + 静态托管** | Cloudflare Pages（`_headers` 已按它的格式写） | 无法部署；且 `_headers` 在别的平台静默失效 |
| D-3 | **头条是否滞后一天** | 是。只用已收盘 K，避免头条与其 999 个比较基准口径不同（S-3） | 同日两次采集给出不同头条 |
| D-4 | **8 阶段决策工作流是否保留在公开站** | 收进折叠式二级披露，或移到"给自己用"的本地版 | 公开访客读成带价位的交易方案 |
| D-5 | **Chrome 伴侣** | 首发范围外，README 降级为"本地开发者可选" | 定位分散；且它连的是 loopback，公开用户装了没用 |
| D-6 | **失败通知通道** | Slack/Discord webhook + 一个外部 dead-man's switch（Cronitor/Healthchecks 免费档） | B-6 无法闭环 |
| D-7 | **公开 bundle 是否与内部 SPA 同一份** | 拆分：公开构建只打包五幕需要的组件，内部 dashboard 代码不进公开 bundle | S-24 只能靠运行期过滤兜底，私有界面形状与内部 reason-code 目录持续公开 |

---

## 7. 值得说的一件事

这一轮的缺陷有一个共同形状，值得单独记下来：

**它们几乎全部是"守卫写对了，但守卫守的那个维度不是会出事的那个维度"。**

- 隔离守卫把路径、junction、force-push、脏工作区全查了一遍，**唯独没查仓库身份**（B-8）。
- 采集与同步正确解耦，同步失败不会毁掉本地采集，**但没人回头去接那份没同步的采集**（B-5）。
- 失败通知做得很完整，**但"任务停了"不产生失败**（B-6）。
- `health.json` 正确地拒绝发布一个会变成谎言的布尔值，
  **而 `status.html` 整页就是那个布尔值**（S-16）。
- 覆盖率统计诚实地报告缺日，**但分母是首末观测之间，所以起点截断在结构上不可见**（B-1）。
- 样本量地板设在 1000，**恰好等于它无从得知的 API 页大小**（B-2）。
- 主报告的公开投影是严格的 deny-by-default 且逐字段枚举，
  **但另外三个文件走的是黑名单，占了一半发布字节**（B-9）。
- 隐私筛查跑得很彻底，**但 manifest 在它之后才写**（S-25）；
  **`.js`/`.css` 被显式豁免**，而那个 bundle 正好是完整的内部 dashboard（S-24）。
- 发布门禁列了四项证据，**其中三项是硬编码常量，且在被证明的东西存在之前就断言了**（S-26）。
- 测试有 793 个，**但没有一个能发现把年化因子从 365 改成 252**（S-7）；
  黑名单测试重新声明了一遍同一份黑名单，**断言"我们剥掉的键被剥掉了"，不可能失败**（B-9）。

这不是粗心，是这套系统已经足够复杂，以至于**"我检查了 X" 不再蕴含 "X 是会出事的地方"**。
对应的工程动作只有一个：**验收标准从"这个检查存在"改成"故意破坏它，看它是否叫"**。
R1 的变异测试验收和 R2 的中断演练验收，都是照这条写的。
