# LensOS Option · 数据可用性止损与开源就绪 Spec

> 状态：提案 · 起草日 2026-08-12（晚间，`435d078` 落地后） · 前置文档
> [2026-08-12-continuity-and-consistency-spec.md](2026-08-12-continuity-and-consistency-spec.md)
>
> 第三轮 spec 回答"验证等待期工程时间花在哪"。本轮回答两个新问题：
> **"为什么数据资产还在无声流失、怎么止住"**，以及
> **"从私有仓到高品质公开仓之间，还隔着什么"**。
> 全部结论基于 2026-08-12 晚间的独立核查，每条都附证据。

---

## 0. 现状基线（2026-08-12 晚间独立核查）

| 维度 | 核查结果 |
| --- | --- |
| 测试 | ✅ `922 passed, 1 skipped, 1479 subtests`（335.3s，独立复跑，与 codex 报告一致） |
| 代码修复 | ✅ `435d078` 已提交（DTE 冲突阻断、Origin 门禁、信任阈值、reason-code canonical catalog、CI 矩阵、constraints.txt），工作树干净 |
| 采集文件 | ✅ 23 份快照，日历日 2026-07-26 → 08-12 连续无空洞 |
| **采集可用性** | ❌ **`series-history.json` 可用日止于 2026-08-06（仅 9 天）**；此后 9 份采集全部被剔除（8× `MARKET_DATA_QUALITY_FAIL`、1× `EXCHANGE_FULL_LOCK`） |
| cohort 进度 | ⏳ research_window `settled_cohorts=1/8`；**三个待结算 cohort（08-14/21/28）的 `last_capture_date` 全部停在 08-06** |
| 采集告警 | ❌ 失败 webhook 与成功心跳在 Process/User/Machine 三个作用域均未配置（第三轮 O-1 至今未执行，剩余唯一运维 P0） |
| 第二采集点 | ❌ 不存在（`435d078` Not-tested 清单自证） |
| 证据备份 | ✅ 私有证据仓每日自动 push（`LensOS-Option-Evidence`，最新 commit 08-12 17:00） |
| 仓库可见性 | 🔒 `Lens-less/LensOS-Option` 为 **private**；66 个提交，无 semver tag，0 个 release |
| **历史 PII** | ❌ **审计基线 25/66 个提交内容含本机 home 路径**；57 个提交作者为私人邮箱、56 个作者名含本机账户标识（含 `.codex\worktrees` 等路径） |
| HEAD 卫生 | ⚠️ 仍 track 4 份 `docs/automation/` 过程文档（含部署侦探记录）与 `.workflow/verify-dashboard-cdp.mjs`（硬编码本机 Chrome 路径）；`.claude/` 未被 ignore |
| 开源构件 | ✅ LICENSE（Apache-2.0）/ LICENSE-DATA（CC BY 4.0）/ SECURITY / CONTRIBUTING / issue & PR 模板 / dependabot 齐备；`pyproject.toml` 无 `authors`；无 CODE_OF_CONDUCT |
| 当前树 PII | ✅ tracked 树对已登记私有标识零命中；`.env` 从未进过历史；CI 不读 secrets，fork PR 可绿 |

---

## 1. 第一性原理

**数据侧。** 验证消耗的不是"采集了多少天"，而是"多少天通过了质量门禁"。
现状是：计划任务每天报 `ok`，心跳（如果配了）每天会发绿灯，
**而可用样本自 08-06 起零增长**。这比 08-07 那次硬失败更危险——硬失败至少
在摘要里写着 `failed`，可用性流失连一行告警语义都没有。采集不可回补：
每一个被整份剔除的日历日，是三个以上在途 cohort 各自永久少一个观测。

结构性根因在裁决粒度：质量门禁**逐到期日**评估（每个到期日有自己的
status 与 reason codes），但**裁决按整份快照**——任何一个到期日失败，
整天对全部 cohort 一起作废。`market_data.py:64-79` 的注释自己记录了这个
行为（"the gate is evaluated over the whole snapshot, mixing them in blocked
the healthy research-window quotes too"）。当年它挡住的是刻意不采的 1-5 天
日到期合约；现在同一机制正在把研究窗口内的正常交易日成片烧掉。

**开源侧。** 高品质开源 = 陌生人 30 分钟能跑 + 历史经得起审计 + 治理构件
完整。工程质量已经达标（零运行时依赖、900+ 测试、fail-closed 文化、
三版本双平台 CI）。硬阻塞只有一个：**git 历史里的本机路径与真实身份**。
`SECURITY.md:29-39` 早已自我要求"公开前重写历史"。这件事只能在切 public
之前做——公开之后，历史就永远是别人的了。

**顺序原则**：数据止损先于开源改造（前者每天都在产生不可逆损失，后者是
静态债务）；历史净化必须发生在可见性切换之前，且只做一次。

---

## 2. P0 · 数据可用性止损（本周）

### DS-1 · 诊断剔除潮：坏报价是市场性的，还是选样性的

**证据：** 剔除自 08-04 开始成为常态（07-31 也有一次）：

- 08-04/05：到期日 2026-08-14 `bad_quote_ratio = 0.2812 / 0.3214`（阈值 0.25）；
- 08-08：到期日 2026-08-28（20 DTE，研究窗口正中）invalid 26/71 = 0.3662；
- 08-12：valid 60 / invalid 36；主导 flag 均为 `INVALID_BID_IV`；
- 08-11：报价可过，但 `exchange_locked=true` → `EXCHANGE_FULL_LOCK`（真停牌，正确阻断）。

**两个假设，处置相反：**
(a) 市场状态——远翼买盘消失是近期行情属性，门禁如实反映；
(b) 选样策略——moneyness 带 0.7–1.3 在当前波动率下选入了大量无买盘深虚值，
坏报价是采集自己选出来的。

**修复：** 写一份数据诊断：对 08-04 以来每份被剔快照，按到期日 × moneyness
分桶统计 `INVALID_BID_IV` 的分布，与 07-26–08-03 通过日对照。产出一个明确
结论供 DS-2 引用。若为 (b)，修选样（收窄带宽或按报价活性过滤），阈值不动。

**验收：** 诊断文档入库（`docs/research/`）；结论指名根因假设并附分桶数据。

### DS-2 · 裁决粒度：从"整份快照一票否决"改为"按到期日隔离"

**证据：** `market_data.py:1405-1468` 已产出逐到期日的
`status/reason_codes/bad_quote_ratio`；`:1448-1451` 把任一到期日的失败汇入
`overall_reason_codes`，series-history 与 signal validation 消费的是整份
verdict（`series-history.json` 的 `excluded_captures` 按整份剔除）。
后果：08-21 cohort 因 08-28 到期日的坏报价而丢观测——**证据单元之间连坐**。

**修复：** series-history 与 signal validation 的消费粒度改为按到期日：
fail 的到期日隔离（保留 reason codes，空心格语义照旧），pass 的到期日照常
入库。报告级（全链分析、发布）门禁维持整份裁决不变；**任何阈值都不放宽**。

**验收：**
1. 构造"一个到期日 fail、其余 pass"的快照 fixture：pass 到期日的观测进入
   series 与 preflight，fail 到期日带 reason code 被隔离；全 fail 快照仍整体剔除。
2. 用 08-08–08-12 的真实快照重放：若诊断（DS-1）显示当日存在 pass 的到期日，
   对应 cohort 的 `last_capture_date` 必须前进。
3. 现有整份阻断的回归测试全部保持绿（报告级行为不变）。

**注记：** 这不是放宽 fail-closed，是把爆炸半径对齐到证据单元。fail-closed
的单位是"一份证据"，不是"一个日历日"。若 DS-1 结论是当日全部到期日都坏，
DS-2 对那些天无可挽回——但它仍然消除结构放大器本身。

### DS-3 · "成功"必须蕴含"可用"：摘要与告警接入可用性语义

**证据：** 08-08 起摘要天天 `status=ok`，preflight 却持续剔除；
`success_heartbeat` 若已配置会连发五天绿灯。"脚本没崩" 与 "资产在增值"
是两个命题，现在的通知语义只覆盖前者。

**修复：** capture-daily 在采集后追加 usability 判定：快照质量 verdict +
本次是否推进了可用序列，写入摘要（`usable_for_validation: bool` + reason
codes）；连续 2 天不可用 → 触发失败 webhook（即使脚本自身成功）；
心跳 payload 携带可用连续天数。

**验收：** 用 08-12 快照跑一遍，摘要含 `usable_for_validation=false` 与
reason codes；模拟连续两天不可用收到通知。

### DS-4 · 告警链闭环（owner 动作，第三轮 O-1 的最后执行）

**证据：** 本轮独立核查：`CAPTURE_DAILY_FAILURE_WEBHOOK_URL` /
`CAPTURE_DAILY_SUCCESS_HEARTBEAT_URL` 在 Process/User/Machine 全部未设置。
方案、脚本支持、README 指引三者齐备已一周，缺的只是配置动作本身。

**修复：** 按第三轮 O-1 执行（webhook + dead-man 心跳 26h 阈值），
叠加 DS-3 后告警语义才完整。

**验收：** 故意失败一次收到通知；连续不可用两天收到通知；心跳服务收到
含可用天数的 ping。

### DS-5 · 阶段解耦：快照失败不得跳过历史刷新

**证据：** 08-07 日志：`snapshot FAILED pull-snapshot exited 10` 后，
underlying_history / dvol / series / preflight 当日全部跳过。结算价来自
历史刷新；结算日恰逢快照失败时，cohort 结算依赖次日运行补救（08-07 正是
第一个 cohort 的结算日，靠 08-08 自愈是运气）。

**修复：** `capture-daily.ps1` 阶段重排：快照失败仍执行 underlying_history
与 DVOL 刷新（二者不依赖快照产物），series/preflight 跳过可接受；
退出码保持非零、摘要分阶段记录。

**验收：** 模拟快照失败，断言历史文件当日仍被刷新，摘要逐阶段可见。

### DS-6 · 第二采集点：做一次真正的决定（二选一，不可悬置）

**证据：** 单机采集；08-07 的失败原因是本机 SSL 瞬断
（`UNEXPECTED_EOF_WHILE_READING`）——正是第二采集点能天然冗余掉的故障类型。
`publish.yml` 的云采集车道存在但被 `OPS-DEPLOY-001` 挂起（secrets 未配）。

**修复（建议路线 1）：**
1. **启用**：为 Actions 车道配置 evidence-repo token 与 webhook secrets，
   每日 08:10 UTC 云采集与本地互补（8-03 spec S-8 的覆盖问题修复状态需先验证）；
2. **挂起**：在 `OPS-DEPLOY-001` 同一文档显式记录第二采集点一并挂起，
   automation 不再重复评估。

**验收：** 路线 1——连续 3 天云端与本地各自产出快照且证据仓无冲突；
路线 2——挂起记录存在。

---

## 3. P1 · 小修与已核查为非问题

### 小修（各自独立小 PR，附"矛盾→阻断"回归测试）

| # | 问题 | 位置 | 修复 |
| --- | --- | --- | --- |
| F-1 | DTE 冲突时函数仍双返回 `derived + DTE_EVIDENCE_CONFLICT`，靠调用方丢弃推导值，易回归 | `publication.py:1890` | 冲突分支只返回阻断信号，不再携带推导值 |
| F-2 | `macro_events` 恒为 `[]`，消费者会读成"确认无事件" | `market_data.py:1116` | 改为 `null` + 契约注记，或在 feed contract 里显式标 `not_collected` |
| F-3 | 选样宽域 fallback 的 `fallback_used=true` 只留在 `selection_policy`，不进质量裁决可见面 | `market_data.py:810-842` | fallback 使用时在快照质量 verdict 附 reason code（不改变 pass/fail） |

### 已核查为非问题（防止未来审计重复挖掘）

| 嫌疑点 | 核查结论 |
| --- | --- |
| `market_data.py:1509-1514` 解析失败填 `1970-01-01`/`unknown` | ✅ fail-closed：该行必带 `INSTRUMENT_PARSE_FAILED`/`MISSING_CANONICAL_METADATA` 并判 `invalid`（`:1615-1620`），占位值不可能进入有效样本 |
| `market_data.py:431-432` trust 状态读失败返回 `{}` | ✅ fail-closed 方向：空证据 = 不提升信任；HMAC 校验失败同路径。可选改进是加观测性 reason code，非缺陷 |
| `advance_trust_evidence` 对 `None` 阈值填默认 | ✅ 填的是 C-1 修复后的唯一权威 `PolicyCatalog`（6/60），是 Python API 默认参数，不是数据缺字段回填 |
| `market_data.py:1540-1548` spot 回填 forward | ✅ 有意的、被记录的替代（`underlying_price_source="index_spot_fallback"`），注释完整披露语义 |

---

## 4. P2 · 开源改造（OS-1 至 OS-5 是切 public 的前置；顺序执行）

### OS-1 · 历史净化（硬阻塞，只做一次）

**证据（全部独立核查）：**
- 审计基线 25/66 个提交内容含本机账户标识（本机 home 与 `.codex\worktrees` 路径）；
- 作者元数据：私人邮箱 × 57、含本机账户标识的作者名 × 56；
- 历史含已删除的 `docs/automation/evidence-store`（约 99 路径 / 1.56 MB）、
  `issues/`、coordination 工具、历代 hash-named JS bundle（≥15 次，各 271–348 KB）；
- GitHub 远端仍广告 12 个只读 `refs/pull/*/head`；其中旧 PR tree 仍含本机标识，
  普通 branch/tag force-push 无法更新这些 ref；
- `SECURITY.md:29-39`："Before making this repository public, rewrite history
  to purge them"——项目对自己的要求。

**修复：** `git filter-repo` 一次性完成三件事：
1. **路径删除**：历史中的 `docs/automation/`（保留现行 4 文件的去留由 OS-2 决定）、
   `issues/`、coordination 工具、旧 bundle blob；
2. **文本替换**（`--replace-text`）：本机 home 及 worktree 路径 → `<LOCAL_USER_HOME>` 占位符；
3. **作者改写**（mailmap）：两个真实身份 → 公开身份（建议 GitHub noreply 邮箱）。

先在镜像 clone 上演练并跑核对脚本，本地保留一份包含 PR refs 的私有完整镜像。
本地重写通过仍不代表原 GitHub 仓可公开：必须由 GitHub Support 删除/解引用旧 PR refs
与缓存；若无法取得确认，则把只含重写后 `main` 的 bundle 推入**全新 public 仓库**，
旧仓永久 private。dependabot 分支在新历史上重建。

**验收：** 对全部 refs 的已登记本机账户标识、私人作者 ID 与本机 home 前缀零命中；
逐 revision 内容扫描零命中；作者列表只含公开身份、GitHub 与 dependabot；
私有镜像存档可访问；public ref allowlist 只含 `main`；重写后
`pytest`/`ruff`/web 三件套全绿；远端 PR refs 单独复核为零，或采用全新 public 仓。

**注记：** 证据仓 `LensOS-Option-Evidence` **永久保持 private**；公开数据
只经由 CC BY 4.0 的发布产物这一条通道。

### OS-2 · HEAD 卫生

**证据：** `git ls-files` 仍含 `docs/automation/final-report.md` /
`goal-board.md` / `handoff.md` / `strategy-eval-spec.md`（2026-08-12 部署僵局
的内部侦探记录：NXDOMAIN、无 SSH、EC2 线索）与
`.workflow/verify-dashboard-cdp.mjs`（`:6` 硬编码本机 Chrome 路径）。
`.gitignore` 声明了 `docs/automation/` 但已 track 路径不受 ignore 保护；
`.claude/` 完全未被 ignore（含 `settings.local.json`）。

**修复：** 5 个文件 `git rm --cached`（有存档价值的移入私有证据仓）；
`.gitignore` 补 `.claude/`；`docs/README.md` 地图移除 automation 目录的
公开叙事。最后跑一次 `git add -A` 演练确认 140 MB 工作区残渣
（`artifacts/`、`dist/`、`.wheel-verify/`、`.workflow/`）全部仍被忽略。

**验收：** `git ls-files` 无 `docs/automation`、无 `.workflow`；
`git add -A ; git status` 不引入任何非预期路径。

### OS-3 · 法务与元数据

**证据：** `pyproject.toml` 无 `authors`/`maintainers`；LICENSE 附录占位符
属 Apache-2.0 标准原文（合规，无需改），但项目自身无任何版权声明；
GitHub description 为空、无 topics。

**修复：** `pyproject.toml` 补公开身份的 `authors`；GitHub
description/topics/website 填齐；README 首屏加 CI/license/Python 版本徽章；
新增 `CODE_OF_CONDUCT.md`（Contributor Covenant 即可）。

**验收：** wheel 元数据完整；repo About 区完整。

### OS-4 · 陌生人 30 分钟路径

**证据：** README `:54-57` 的 evidence console 示例指向
`artifacts/snapshots/btc-series/<capture>.json`——clone 后不存在；
采集/发布链是 Windows + 计划任务专有；`README.en.md` 结构存在但落后。

**修复：** 快速开始的每条命令只依赖 `tests/fixtures/`；"操作者车道"
（采集、计划任务、发布）单独成节并标注 Windows-only、外部基建可选；
`README.en.md` 与中文版结构对齐；`CONTRIBUTING.md` 补英文镜像段。

**验收：** 干净环境（新 venv、仅 clone）按 README 顺序执行全部快速开始
命令一次成功；30 分钟内在浏览器看到 evidence console。

### OS-5 · 版本与发布治理

**证据：** 无 semver tag、0 release；CHANGELOG 中英双轨混排、未与
`0.1.0` 对齐；第三轮 spec 也点名"告警链未闭环前不制造误导性发布"。

**修复：** CHANGELOG 收敛出 `0.1.0` 节（语言单轨或中英分文件）；
**在历史净化完成之后**打 `v0.1.0` tag + GitHub Release；Release notes 明确
定位："research console 工具开源；信号验证 1/8 cohort 在途，结论未出"。

**验收：** tag、`pyproject.toml` 版本、Release notes 三者一致。

### OS-6 · 切 public 时序（一次执行的 checklist）

```
冻结窗口（暂停 automation 写入，main 与 origin 同步）
  → OS-1 镜像演练 + 核对 → force push → dependabot 分支重建
  → OS-2 / OS-3 / OS-4 / OS-5
  → 全套验证：pytest · ruff · npm test/lint/build · CI 全绿 · 陌生人测试
  → GitHub 设置核查：Actions 对 fork PR 需批准、branch protection、
    secrets 仅存在于 publish.yml 所需（fork 不可达）、Security Advisory 开启
  → gh repo edit --visibility public → 打 v0.1.0 → 公告
```

---

## 5. 明确不做（与做什么同等重要）

| 编号 | 不做的事 | 理由 |
| --- | --- | --- |
| N-1 | 为开源实现 DQR-005/007（vendor 历史、私有账户 live 适配器） | README 状态表已如实 NO-GO；`not_implemented` 墙是产品边界不是待办。对外解释即可 |
| N-2 | 把 Windows 采集链重写为跨平台 | 唯一在生产运行的车道；验证期稳定 > 优雅（沿袭第三轮 N-5）。文档标注 Windows-only 即可 |
| N-3 | 停止提交 `static/evidence/` bundle、改为 CI 构建 | 现行契约有 CI 一致性校验锁定；改机制属于新表面，验证期冻结。历史里的旧 bundle blob 在 OS-1 顺手清除 |
| N-4 | 全量文档英文化 | "中文为主"是既有语言决议（`docs/README.md:45`）。只做 README.en 对齐 + CONTRIBUTING 英文镜像 |
| N-5 | 放宽任何质量阈值换验证速度 | DS-2 改的是裁决粒度不是阈值。README 原话："为验证方便放宽门禁，正是这个项目存在的意义所反对的" |
| N-6 | 在 8 cohort 凑齐前打 v1.0 或宣传信号有效性 | v0.1.0 的定位是工具开源；信号验证结论是 10 月中的事，预登记纪律不因开源改变 |

---

## 6. 实施顺序与总验收门禁

```
第 1 周   DS-4（owner，半天）→ DS-1 诊断 → DS-2 → DS-3 → DS-5 · DS-6 做决定
第 2 周   F-1..F-3 小 PR · OS-2 / OS-3 / OS-4 / OS-5 备料
冻结日    OS-1 演练 → force push → OS-6 checklist → 切 public + v0.1.0
10 月中   验证节点（不变；届时按结果决定 v0.2 方向）
```

每个 PR 沿用仓库统一门禁（pytest 全绿、ruff 零告警、web 三件套 +
static/evidence 同步提交、reason code append-only、不触碰
`execution_allowed=false`）。在此之上，本轮的三个**总验收测试**：

1. **数据止损测试**：构造部分到期日 fail 的快照 → pass 到期日观测入库；
   连续 2 天不可用 → 收到通知。（DS-2 + DS-3 + DS-4 联合验收）
2. **历史审计测试**：全部 refs 对已登记本机账户标识、私人作者 ID、旧作者名前缀与本机 home 前缀零命中。
3. **陌生人测试**：干净机器 clone → README 快速开始 → 30 分钟内
   evidence console 出图，全程不接触 `artifacts/` 与任何 owner 基建。

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 历史重写不可逆 / 出错 | 只在镜像上演练直到核对脚本全绿；本地保留私有完整镜像；原仓的只读 PR refs 不能靠 force-push 清除，Support 不确认时改用全新 public 仓——**这个窗口公开后永久关闭** |
| 重写后既有文档里的 commit SHA 引用（`435d078`、`0818a4a` 等）失效 | 保留 filter-repo 的 commit-map 于私有镜像；归档文档头部加一行"历史于 2026-08 重写，旧 SHA 见私有映射" |
| DS-2 被误解为放宽门禁 | 阈值零改动；单元级 fail-closed 与报告级整份裁决都不动；以"全 fail 快照仍整体剔除"的回归测试为证 |
| DS-2 改动 series/preflight 消费面引起回放漂移 | 以既有快照 fixture 的逐字节快照测试为准绳；仅新增可用观测，不改既有观测的编码 |
| 历史重写移除既有提交/标签签名 | 这是 `git-filter-repo` 的预期副作用；发布新历史后用新身份签署 `v0.1.0`，不声称旧 Verified 徽章可保留 |
| 开源后 secrets / Actions artifact 暴露面 | CI 不读 secrets（已核查）；切 public 前清点并删除或私下归档旧 workflow artifacts/runs，且停止在 public 产品仓上传 raw capture；再核 fork 审批设置 |
| 08-14 cohort 结算在即（2 天后） | DS-5 与历史刷新的独立性保证结算价可得；这正是 DS 系列排在本周的现实理由 |

---

## 8. Owner 决策状态

| # | 决策 | 状态 | 落地 |
| --- | --- | --- | --- |
| D-1 | 历史重写后的公开作者身份 | **待 owner** | 需确认公开姓名与已验证 noreply 邮箱；final rewrite 在此之前 fail-closed |
| D-2 | 第二采集点路线 | **已选** | Actions `08:10 UTC`，origin=`github_actions_0810_utc`；需凭证与三日双车道验收后才 accepted |
| D-3 | 切 public 时点 | **已选** | 数据止损 + OS-1..5 后切，不等 10 月信号验证；公共站点可继续 `SUSPENDED` |
| D-4 | issue/PR 模板语言 | **已选** | 中文为主，模板顶部提供英文提交指引 |
