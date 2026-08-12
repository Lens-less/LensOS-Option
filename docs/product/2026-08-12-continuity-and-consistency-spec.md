# LensOS Option · 运营连续性与 fail-closed 一致性 Spec

> 状态：提案 · 起草日 2026-08-12 · 前置文档 [2026-08-03-public-release-hardening-spec.md](2026-08-03-public-release-hardening-spec.md)
>
> 第二轮 spec 回答"为什么还不能挂出去"。本文档回答**"在信号验证样本凑齐之前
> （预计 2026-10 中旬），工程时间应该花在哪、明确不花在哪"**。
> 全部结论基于 2026-08-12 的独立核查，每条都附证据。

---

## 0. 现状基线（2026-08-12 独立核查）

| 维度 | 核查结果 |
| --- | --- |
| 测试 | ✅ `887 passed, 1 skipped, 1460 subtests`（154.6s，独立复跑） |
| Lint | ✅ ruff 零告警 |
| 运行时依赖 | ✅ `pyproject.toml` `dependencies = []`，包内无第三方 import，零依赖承诺未被违反 |
| 每日采集 | ✅ 序列 22 份快照，计划任务 `LensOS-Option-DailyCapture` 状态 Ready，每日 17:00 本地 |
| 采集告警 | ❌ **失败 webhook 与成功心跳均未配置**（见 O-1） |
| 采集韧性 | ❌ 2026-08-07 采集失败，单次尝试无重试，当日管道全部跳过（见 O-2） |
| 信号验证样本 | ⏳ research_window 带：**1/8 cohort 已结算**，还差 7 个；下一个待结算到期日 2026-08-14 |
| 公开站部署 | ❌ 外部僵局：`research.lensos.dev` DNS 与非交互部署身份不存在（提交 `0818a4a` 已三轮确认） |
| 分支卫生 | ⚠️ `codex/overnight-data-strategy-deploy` 领先 `main` 3 个提交未合并；工作树两个文件为纯 CRLF 噪音（diff 为空） |
| 入库构建产物 | ✅ `static/evidence/` 12 文件 / 0.4 MB，无旧 hash bundle 残留 |

**代码结构量化**（三路审查汇总）：46 个 Python 模块共 37,563 行（4 个模块 >2000 行，
十余个函数 >200 行）；`web/src` 非测试约 13,721 行（最大组件 1,121 行）；
`tests/` 23,310 行；`docs/` 20,279 行（其中 `automation/` 占 73% 且不在文档地图内）；
CI 每个 PR 全量 pytest 跑 4 遍（2 OS × 2 Python）。

---

## 1. 第一性原理与范围

本产品的可信输出 = **被验证的排序信号 × 可信的公开发布**，当前两者分别卡在：

1. 信号验证需要 8 个已结算 cohort，现有 1 个。**任何工程投入都不能加速它**；
   唯一相关的工程动作是保护采集连续性——这份数据不可回补，丢一天就永久推迟一天。
2. 公开发布已本地验证完毕，卡在只有 owner 能提供的域名与部署身份上。

因此本 spec 的优先级排序原则是：

- **P0（§2）**：保护不可再生资产、解除外部决策悬置。多数不是写代码。
- **P1（§3）**：修复违反项目自身 fail-closed 铁律的代码。在这个产品里这类问题
  不是普通 bug，而是对核心承诺的直接伤害——产品卖的就是 fail-closed。
- **P2（§4）**：消除会导致"两个界面对同一份报告给出不同解读"的复制漂移。
- **§5 是刻意的"不做"清单**，与做什么同等重要：在验证结果出来之前，
  冻结一切新表面、新机制、新抽象。

---

## 2. P0 · 资产保护（本周内）

### O-1 · 配置采集失败告警与成功心跳

**证据：** 2026-08-07 采集失败摘要
`artifacts/logs/capture-daily-btc-20260807T090003326Z.summary.json`：

```json
"status": "failed",
"failed_stage": "snapshot",
"error": "pull-snapshot exited 10",
"webhook":           { "configured": false, "attempted": false },
"success_heartbeat": { "configured": false, "attempted": false }
```

失败发生了，**没有任何通知发出**。README 与 capture 脚本早已支持
`CAPTURE_DAILY_FAILURE_WEBHOOK_URL` / `CAPTURE_DAILY_SUCCESS_HEARTBEAT_URL`，
只是从未配置。

**后果：** 采集不可回补。连续静默失败 N 天 = 验证时间表永久后移 N 天。
8 月 7 日只损失一天是运气（次日自愈），不是设计。

**修复：**

1. 为计划任务的运行账户注入两个 webhook 环境变量（README 已写明：不得把 URL
   明文写进其他本机用户可读的任务参数）。
2. 心跳接入任一 dead-man 服务（healthchecks.io 或等价物），超时阈值 26 小时。
3. 顺手修一处日志诚实性问题：未配置心跳时日志仍打印 `success_heartbeat ok`
   （见 `artifacts/logs/capture-daily.log` 2026-08-06 行），应改为
   `success_heartbeat skipped (not configured)`——"ok"不能同时表示"发出了"
   和"没配置所以没发"。

**验收：** 手工触发一次故意失败（如临时改错 snapshot 输出目录），确认收到失败
通知；次日正常运行后摘要中两个 `configured` 均为 `true`、心跳服务收到 ping。

### O-2 · 给采集加失败重试

**证据：** `capture-daily.log`：

```
2026-08-07T09:00:03Z  capture start ...
2026-08-07T09:00:16Z  snapshot FAILED pull-snapshot exited 10
（当日再无任何行——underlying_history / dvol / series / preflight 全部跳过）
```

退出码 10 是市场数据质量门禁阻断（`INVALID_BID_IV` 等），**通常是瞬态的**。
脚本 fail-closed 立即终止是正确的；错的是整天只尝试一次。且当日恰是第一个
cohort（2026-08-07 到期）的结算日，历史刷新被跳过，全靠次日运行补上结算价。

**修复（二选一，推荐 1）：**

1. Task Scheduler 层：`Set-ScheduledTask` 配置
   `-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 20)`。
   脚本失败时 `exit 1`，调度器自动在 20/40/60 分钟后重试，无需改脚本。
2. 脚本层：对退出码 10 做最多 3 次、间隔 15 分钟的内部重试。

**验收：** 模拟一次失败，确认任务在配置间隔后自动重跑；重试成功的那次产出
正常摘要与心跳。

### O-3 · 对公开站部署做一次真正的决定

**证据：** 最近三个提交（`0818a4a`、`2cc6b74`、`0ac9075`）反复验证同一结论：
发布产物已逐字节复核（72 文件、70 个 manifest 哈希、本地 HTTP smoke 全过），
但 `research.lensos.dev` 无 DNS 记录、无部署身份，**任何自动化都无法继续**。

**后果：** 悬而未决的成本是持续的：后续每一轮自动化都会重新撞墙、重新验证、
重新记录同一个僵局。

**修复（二选一，都可接受，不可继续悬置）：**

1. **解锁**：购置/配置 `research.lensos.dev` DNS，创建非交互部署身份
   （Cloudflare Pages token 或等价物），按 `docs/operations/public-publishing.md`
   走一次完整发布 + 外部 HTTPS smoke。
2. **挂起**：在 backlog 明确记录"公开站部署挂起，等待基础设施"，并在
   automation 指令中移除部署目标，停止在此消耗轮次。

**验收：** 路线 1——公网 HTTPS smoke 通过、`health.json` 外部监控就位；
路线 2——backlog 条目存在，后续 automation 不再产生部署尝试记录。

### O-4 · 分支与行尾卫生

**证据：** `main...HEAD` = 0 落后 / 3 领先；`git diff` 对
`analysis_run.py`、`contract.py` 内容为空，仅 CRLF→LF 警告
（`.gitattributes` 声明 `* text=auto eol=lf`，某工具以 CRLF 写盘）。

**修复：** 合并当前分支进 `main`（fast-forward 即可）；
`git add --renormalize .` 后提交或直接 `git checkout --` 恢复两文件；
排查是哪个编辑器/工具在写 CRLF，避免噪音复发。

**验收：** `git status` 干净；`main` 包含全部三个提交。

---

## 3. P1 · fail-closed 一致性修复（一至两周，每条独立小 PR + 回归测试）

> 仓库测试约定要求优先覆盖证据缺失/损坏路径。本节每条的验收测试都必须
> 包含至少一个"输入缺失/矛盾 → 阻断"的断言。

### C-1 · 信任门槛三处不一致（6/60 vs 3/30），缺字段时填宽松默认

**证据：**

- `crypto_options_report/market_data.py:120-122`：证据生产方的提升门槛
  `TRUST_MINIMUM_CONSECUTIVE_PASSES = 6`、`..._OBSERVATION_SECONDS = 60`。
- `crypto_options_report/analysis_run.py:251-252`：`PolicyCatalog` 默认
  `trust_minimum_consecutive_passes: int = 3`、`..._observation_seconds: int = 30`。
- `crypto_options_report/contract.py:1424-1427`：投影侧在字段**缺失时填入**
  `default=3.0`（passes）与 `default=30.0`（seconds）。

**后果：** 同一条信任链上，策略与投影比生产方宽松一倍；contract 的
"查不到就填宽松默认"正是 `docs/architecture.md` 自己定义的 bug 形态
（fail-open）。DESIGN.md §13 规定 `PolicyCatalog` 是 P0 信任规则的唯一 owner，
当前事实上有三个 owner。

**修复：**

1. `PolicyCatalog` 默认值改为 6/60，成为唯一权威；`market_data.py` 的两个
   常量改从 policy 导入（或反向，二选一，但**只能有一处字面量**）。
2. `contract.py:1424` 起的两处 `default=` 删除：字段缺失 → 该证据判
   `degraded/unknown` 并给 reason code，不得代入任何默认门槛。

**验收：** 新增测试断言三处读到同一数值（改一处即红）；构造缺
`minimum_consecutive_passes` 字段的快照，断言信任不被提升。

### C-2 · `vrp.py` 是唯一会跟随 HTTP 重定向的网络入口

**证据：** `crypto_options_report/vrp.py:20` 直接
`from urllib.request import Request, urlopen`，`:893` 使用默认 opener；
`market_data.py:36-46`、`alerts.py`、`account_snapshot_sidecar.py` 均显式
拒绝重定向。

**修复：** DVOL 拉取改用与 `market_data` 相同的无重定向 opener
（实施上与 D-3 的 `_http.py` 合并做，见 §4）。

**验收：** 测试断言 3xx 响应被拒绝并 fail-closed。

### C-3 · development 下浏览器可钉死评估时钟，且此类缓存永不过期

**证据：**

- `crypto_options_report/api.py:1939`：query 路径接受客户端传入
  `generated_at`（production 的锁定路径 `:1909` 用的是进程级
  `_evaluation_clock(runtime)`，正确）。
- `api.py:1800-1801`：`_analysis_cache_entry_current` 对带显式
  `generated_at` 的缓存直接 `return True`（永不过期）。
- `api.py:213-223` 的注释自己写明：钉钟必须是 operator 的进程级决策，
  "A pinned clock makes stale data look current"。

**后果：** 陈旧快照可在 development 界面上读起来像"当前"，绕过新鲜度门禁——
`--replay` 特性存在的全部意义就是让这件事只能显式、带横幅地发生。

**修复：** 从 HTTP query 白名单中移除 `generated_at`（回放需求已由启动参数
`--replay` 完整覆盖）；`:1800` 的永不过期分支仅对 replay 运行时保留，
query 来源一并删除。`build_local_report` 等测试辅助入口改走进程级参数。

**验收：** 带 `generated_at` 的 query 返回 422；replay 模式行为与横幅不变；
现有回放测试全绿。

### C-4 · publication 在 DTE 冲突时静默改值

**证据：** `crypto_options_report/publication.py:1837-1847`：
显式 `dte_days` 与从 `expiry_date` 推导值相差 >1 天时**静默改用推导值**；
`expiry_date`/时钟解析失败时静默返回显式值。两个方向都在矛盾证据下继续发布。

**修复：** 冲突（>1 天）→ 该候选整行阻断并给 reason code
（如 `DTE_EVIDENCE_CONFLICT`）；解析失败同样阻断。发布器对含矛盾证据的
候选的正确态度与快照质量门禁一致：宁缺毋假。

**验收：** 构造 explicit=10 / derived=20 的候选，断言不出现在发布产物且
reason code 可见；解析失败路径同断言。

### C-5 · 写请求缺 Origin 头时 CSRF 校验被跳过

**证据：** `crypto_options_report/api.py:1069-1078`：仅当 `origin` 存在时
才校验同源；无 Origin 的 POST/DELETE 直接放行（loopback 无 bearer 的默认
部署下无任何门禁）。

**修复：** POST/DELETE 在无 Origin 时：若配置了 bearer 且通过 → 放行；
否则拒绝 403。**设计注记**：这会要求本机非浏览器客户端（curl 脚本等）
显式带 `Origin: http://127.0.0.1:<port>` 或配置 bearer——这是可接受的成本，
写路径本就只有回测作业等少数端点。

**验收：** 无 Origin + 无 bearer 的 POST 返回 403；带正确 Origin 或 bearer
通过；Chrome 扩展（自带 Origin）回归不受影响。

### C-6 · 分析缓存满时资源耗尽被伪装成客户端错误

**证据：** `crypto_options_report/api.py:360-361` 缓存达 64 条时抛
`ValueError`，`do_GET` 统一映射为 400。

**修复：** 改为逐出最旧的隐式时钟条目（显式时钟条目是不可变回放记录，
数量有限）；若仍满则返回 503 + `Retry-After`，不再是 400。

**验收：** 填满缓存后请求新组合：得到成功响应（逐出生效）或 503，绝不 400。

### C-7 · 死代码清理

**证据：**

- `api.py:921-933`：`_write_html` 全仓无调用，残留的 CSP 还含
  `'unsafe-inline'`（比现行证据页策略宽松，是误导性样板）。
- `regime.py:645-658`：`_score_value` 无调用。
- `api.py:87-88`：`GET_SURFACE_PATHS` 含字面量 `"/backtest/report/{id}"`，
  永不匹配任何请求（真实路由靠 `_is_backtest_report_path`）。

**修复：** 三处直接删除；`GET_SURFACE_PATHS` 若用于文档/测试枚举，改为
生成式来源。

**验收：** ruff + 全量测试绿；grep 无残留引用。

---

## 4. P2 · 防漂移整并（10 月验证节点前机会性完成）

### D-1 · public 界面复用真正的共享报告边界

**证据：** `docs/architecture.md` 声称 `web/src/report/` 是共享边界，
evidence/sidepanel/extension 确实在用；但 `web/src/public/publicModel.ts`
（376 行）平行实现了 `selectPublicFreshness`（与 `report/selectors.ts` 的
`selectReportFreshness` 同构，各约 76/77 行），且 `marketModel.ts` 与
`publicModel.ts` 的 `formatTimestamp` / `formatExpiry` / `formatPercent` /
`formatDecimal` / `formatDvol` **字节级相同**。公开 bundle 的边界扫描
（`web/scripts/assert-public-bundle-boundary.mjs`）是 token 扫描，
**并不禁止**从 `report/` 复用纯函数。

**后果：** 新鲜度/格式逻辑双份维护，漂移的后果正是本产品最不能接受的形态：
两个界面对同一份报告给出不同解读（48 小时停摆判定尤其敏感）。

**修复：** public 改为直接 import `report/` 与共享 format 的纯函数，
删除平行实现（预计净删 150+ 行）。不新建任何抽象层——直接 import。

**验收：** `publicModel.ts` 中不再存在与共享层同名的本地实现；
边界扫描与公开 bundle 构建保持绿；public 快照测试输出逐字节不变
（格式函数本就相同，输出必须不变）。

### D-2 · reason-code 文案收敛为单一来源

**证据：** 三套表并存——`components/shell/reasonCodes.ts`（34 码）、
`public/publicReasonCodes.ts`（29 码，与前者交集 22）、
`components/evidence/reportModel.ts` 内 `REASON_COPY`（21 码，队列/责任人
语义轴）。同一机器码多套中文解释。

**修复：** 合并为一个源文件（每码一条记录，可含 per-surface 字段），
各界面做投影。public 若需裁剪词表，由构建期投影而不是手抄第二份。

**验收：** 新增测试：枚举产物中实际出现的全部 reason code，断言在单一来源
中都有条目；删除两份旧表。

### D-3 · Python 侧三个内部 helper 模块，消掉全部已知复制

**证据：**

- `_RejectRedirects` + opener：`market_data.py:36-46`、`alerts.py`、
  `account_snapshot_sidecar.py` 三份近乎相同；
- `_get_json`：`market_data.py` ↔ `vrp.py`（后者还是 C-2 的事故点）；
- `utc_timestamp`：`market_data.py:178`、`contract.py:124`、`path_risk.py:76`、
  `backtest.py:43`、`historical.py:182` 五份同实现；
  `evidence_store._utc_timestamp` 保留微秒，语义已漂移；
- `_log_json`：`api.py` / 两个 sidecar 三份（architecture.md 已知债）。

**修复：** 新增 `_http.py`（opener + `_get_json`）、`_time.py`
（`utc_timestamp`）、`_logging.py`（`_log_json`），迁移全部调用点。
**注记：** `evidence_store` 的微秒精度先保持原样并加注释（其时间戳是否
参与既有摘要需单独确认，本 spec 不冒这个险）；其余五处统一到秒精度实现。

**验收：** grep 确认旧副本清零（evidence_store 例外并有注释）；全量测试绿。

### D-4 · 文档收敛：一个 North Star

**证据：**

- `docs/archive/README.md` 仍把含 paper/交易路线的旧 PRD
  （`docs/research/deribit-options-intelligence-platform-prd.md`）标为
  "当前 PRD"；`docs/README.md` 把现行契约指向
  `docs/product/2026-08-02-public-product-spec.md`。两套 North Star 并存。
- `docs/automation/`：90 文件 / 14,817 行（占全部文档 73%），不在文档地图。
- 抽查过时：`docs/research/open-source-integration-opportunities.md` 引用
  已不存在的 `static/dashboard.html`；
  `2026-07-25-cleanup-and-chrome-extension-plan.md` Phase 0 与 CI 现行的
  static 入库校验直接矛盾。

**修复：** 归档而不是重写——旧 PRD 指针改为归档措辞；`docs/automation/`
整体挂到归档层或在地图中标注"自动化过程记录，非契约"；两处过时引用修正。
7/25 计划与 CI 的矛盾按现状裁决（CI 行为是事实契约）并在计划文档头部标注
已被替代。

**验收：** `docs/README.md` 地图覆盖或显式归档全部一级目录；
全仓 grep `dashboard.html` 无现行文档引用；"当前 PRD"仅一处定义。

---

## 5. 明确不做（与做什么同等重要）

| 编号 | 不做的事 | 理由 |
| --- | --- | --- |
| N-1 | 实现 model promotion 机制（`docs/model-promotion.md` §4/§6/§7） | 项目已刻意推迟："现在写实现只能对着为此发明的数据测试"。维持原判，等样本接近凑齐再建。 |
| N-2 | `analysis_run.py` 四段大拆分 | 测试全绿、当前无高频改动需求。拆分收益只在下一次真正要改它时兑现——届时顺手拆改动路径上的那一段。`_admission_conditions`（617 行）是唯一例外：若 C-1 落地时顺路，可拆出信任相关的 condition builder。 |
| N-3 | 为 public 复用建共享格式化"框架" | D-1 的正确形态是删代码 + 直接 import，不是新抽象层。 |
| N-4 | 新信号、新界面、新机制 | 预登记纪律的全部意义就是等这份样本。10 个信号已经带来了多重比较负担，第 11 个只会加重。 |
| N-5 | 重写 `capture-daily.ps1`（1681 行）或 `publish.yml`（901 行） | 两者错误处理已被验证可靠（fail-closed、失败即停、有测试锁定）。体量是债，但当前唯一在生产运行的就是它们——验证期内稳定性 > 优雅。 |
| N-6 | CI 矩阵缩减、`artifacts/` 140 MB 残渣清理 | 有收益但不紧急，排 P3：PR 只跑 ubuntu + 3.12、`main`/nightly 全矩阵；`artifacts/build-check*` 与 `goal-*` 一次性删除。 |

---

## 6. 实施顺序与总验收门禁

```
第 1 周   O-1 → O-2 → O-4（半天量级）· O-3 做出决定
第 2-3 周 C-1 … C-7（每条独立 PR，可并行，无相互依赖；C-2 与 D-3 合并实施）
10 月前   D-1 → D-2 → D-4（机会性；D-1 优先，因为它防的是对外解读漂移）
10 月中   验证节点：8 个 cohort 结算 → validate-signal 出结果 →
          据结果重新评估 N-1/N-2 的解冻与下一阶段投入方向
```

每个 PR 的统一门禁（与仓库现行约定一致）：

1. `python -m pytest -q` 全绿；`ruff` 零告警；涉及 web 的改动
   `npm test && npm run lint && npm run build` 并同步提交 `static/evidence/`。
2. §3 的每条修复必须附带至少一个**证据缺失/矛盾 → 阻断**的回归测试。
3. reason code 与 schema 版本 append-only；不引入新运行时依赖；
   不触碰 `execution_allowed=false` 边界。

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| C-1 收紧门槛后，历史录制快照在回放中被降级 | 预期行为（更严是安全方向）；回放界面本就展示 reason code。若既有测试 fixture 依赖 3/30，更新 fixture 而不是保留宽松默认。 |
| C-3 移除 query 钉钟破坏某些开发工作流 | `--replay` 已覆盖全部合法场景；受影响的只可能是本不该存在的用法。 |
| C-5 拒绝无 Origin 写请求影响本机脚本 | 影响面仅限 HTTP 写端点（回测作业等）；脚本加一个 Origin 头即可，成本一次性。 |
| D-1 复用改动引起 public 渲染回归 | 格式函数字节级相同，输出必须逐字节不变；以 public 快照测试为准绳。 |
| D-3 时间戳精度统一影响摘要 | evidence_store 微秒实现显式保留（见 D-3 注记），其余五处本就同实现。 |
| 所有 P1/P2 改动 | 均为小 PR，可独立 revert；不改 schema、不改摘要编码（`_canonical.py` 不触碰）。 |
