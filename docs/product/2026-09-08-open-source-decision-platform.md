# v0.5.0 期权决策研究平台交付记录

日期：2026-09-08。v0.5.0 功能已合并至公开仓库，PR 与功能合并提交 CI、Release 工作流、
公开下载资产校验和独立安装均已通过。本轮也完成了本地 Python、Web、三种构建、公开包边界、
独立 wheel 消费者与 36 项浏览器检查。以下按验证层级记录范围、结果和对应证据。

## 交付目标

把首次体验、真实公开数据研究、证据解释、失败恢复、复现和开源维护连成完整流程。
核心体验仍是统一的 `strategy_brief.v1`：市场解释、至多三张有限风险策略卡、证据状态和限制。
教学导览解释结构，实际研究依照数据、准入、历史与预测门禁输出；
`research_only=true`、`execution_allowed=false` 不变。

## 交付范围与检查入口

| 范围 | 交付内容 | 检查入口 |
| --- | --- | --- |
| 首次使用 | 包内离线导览、教学收益交互、真实快照入口 | demo 单元测试、最终 wheel 浏览器流程 |
| 研究界面 | 当前/历史时效区分、证据阻断、错误重试、窄屏与键盘操作 | Web 测试、浏览器桌面/窄屏记录 |
| 分析内核 | 不可变分析输入、单次求值、分组准入、惰性兼容投影 | Python 合同/迁移/准入测试、mypy |
| 研究数值 | 数字成本、损失预算、逐腿交割费、无前视路径权重、预测成本绑定 | 成本/回放/路径风险与跨端合同回归 |
| 公开契约 | 固定 OpenAPI/schema、公开产物校验、前端白名单边界 | 公开合同测试、public bundle 检查 |
| 可复现交付 | 构建身份、版本一致性、固定案例、安装后 wheel 和扩展 | `tools/verify.py`、版本检查、release CI |
| 开源文档 | 中英文入口、完整研究工作流、恢复与贡献指南、版本说明 | 链接和命令核对 |

## 本轮验收证据

| 验收项 | 状态 | 本轮证据 |
| --- | --- | --- |
| Python lint、语法与静态类型 | 通过 | `tools/verify.py` 中 Ruff、compileall 与 mypy 通过；12 个严格类型检查文件无错误 |
| 本地阶段 Python 全量测试 | 通过，含 1 项跳过 | `1424 passed, 1 skipped, 1685 subtests passed`；唯一跳过项为 Windows 上不具权威性的 POSIX 权限位检查，未作为通过计入 |
| 后续时钟修复定向回归 | 通过 | 新增时钟边界检查 `3 passed`；与前述完整 Python 测试分别记录，不合并成新的全量计数 |
| 跨平台边界定向回归 | 通过 | 非法 runbook 路径、读取失败与深层 JSON 的组合回归 `64 passed, 12 subtests passed`；路径仍返回缺失/无效证据，JSON 接受解码层 400 或字段校验层 422 的精确错误，并检查后续服务正常 |
| API smoke | 通过 | `python -m crypto_options_report.api --smoke` 通过 |
| 源码版本一致性 | 通过 | Python、Web、lockfile、lockfile root、扩展均为 `0.5.0` |
| 离线研究复现 | 通过 | 两次完整求值一致；实际输出 `untrusted`、`NO_TRADE`、`BLOCKED_BY_EVIDENCE`、`execution_allowed=false` |
| Web lint | 通过 | `tsc --noEmit --pretty false --noUnusedLocals --noUnusedParameters` 通过 |
| Web 全量测试 | 通过 | 43 个测试文件、480 项测试通过，包含真实扩展消息链路与缓存拒绝计数回归 |
| 三种 Web 构建与公开边界 | 通过 | 内部、公开、Chrome 扩展构建通过；公开 bundle 边界与扩展产物检查通过 |
| 独立 wheel 安装、版本与依赖 | 通过 | `0.5.0` wheel 干净安装；6 个 console launcher、包内资源、依赖与 API smoke 消费者检查通过 |
| 桌面、窄屏、键盘与故障恢复功能验收 | 通过 | 安装后 wheel 与 Release 浏览器流程的 36 项功能检查通过，`passed=true`、0 个控制台/未处理错误、0 个外部页面请求；包含公开版恢复与真实原生 Chrome 侧栏连接、断线撤回、重试 |
| 中文视觉复核 | Windows 通过 | 本地 Windows 的桌面/窄屏简报、公开版与原生侧栏截图已目视检查；Linux CI 字体环境与功能结果分别说明 |
| 公开 PR 跨平台 CI 与容器 | 通过 | [CI 34180532675](https://github.com/Lens-less/LensOS-Option/actions/runs/34180532675) 的 Web、容器、Windows/Ubuntu × Python 3.12/3.13/3.14 共 8 个作业全部 `success` |
| Windows 最终 PR Python 全量测试 | 通过，含平台跳过 | Python 3.12、3.13、3.14 每个作业均为 `1429 passed, 1 skipped, 1693 subtests passed` |
| Ubuntu 最终 PR Python 全量测试 | 通过，含平台跳过 | Python 3.12、3.13、3.14 每个作业均为 `1428 passed, 2 skipped, 1688 subtests passed` |
| 合并提交 CI | 通过 | [main CI 34181013524](https://github.com/Lens-less/LensOS-Option/actions/runs/34181013524) 在功能合并提交 `0bac2f6` 上完成，结论为 `success` |
| 开源文档与命令 | 已核对 | 20 份文档、212 个仓库链接/锚点无错误；Release 说明中的 5 个文档链接使用绝对 GitHub URL 并核对目标路径/锚点；6 个 CLI/API 示例经当前 argparse 校验；文档 diff whitespace 检查通过；公开/私有历史隔离文档回归 1 项通过 |
| 公开分支整合、提交与 GitHub 推送 | 完成 | [PR #17](https://github.com/Lens-less/LensOS-Option/pull/17) 已 squash 合并；功能合并提交为 [`0bac2f6`](https://github.com/Lens-less/LensOS-Option/commit/0bac2f64704e50732842de49e4e72ed09e918c16)，与全绿 PR head 的 Git tree 相同 |
| v0.5.0 标签 | 已确认 | 远端 annotated tag 解引用为功能合并提交 `0bac2f64704e50732842de49e4e72ed09e918c16` |
| v0.5.0 发布工作流 | 通过并已发布 | [Release 34181058655](https://github.com/Lens-less/LensOS-Option/actions/runs/34181058655) 的 8 个验证作业、构建与发布共 10 个作业全部成功；[v0.5.0 Release](https://github.com/Lens-less/LensOS-Option/releases/tag/v0.5.0) 于 `2026-09-08T02:53:54Z` 正式发布，非草稿、非预发布 |
| 公开下载资产独立验收 | 通过 | 实际下载的 wheel 与扩展 ZIP 均逐项匹配 `SHA256SUMS`；标签/源码/wheel/ZIP 版本均为 `0.5.0`；新建无运行依赖环境的安装、6 个启动入口、资源、依赖与 API smoke 通过 |
| 发布包源码身份 | 通过 | wheel 内嵌功能合并提交 `0bac2f6`、`git_state=clean`；源码摘要与干净公开 `v0.5.0` 标签检出的 239 个声明源文件一致 |
| 发布包边界独立复核 | 通过 | wheel 90 个文件、89 个 RECORD 条目校验通过，82 个标签受控文件比对一致；扩展 ZIP 11 个文件、manifest 引用完整；包内敏感内容扫描 0 发现 |

本地证据分两阶段记录：先完成完整 Python 与基础检查；修复随后发现的时钟边界和真实侧栏
投影问题、缓存重投影丢失拒绝计数后，重新通过完整 Web、三种构建、独立 wheel 与 36 项浏览器流程。公开恢复脚本原先
错误等待折叠区域，现已校正，并通过实际公开构建的键盘展开与故障恢复重新验证。

浏览器覆盖离线导览在研究故障时仍可完成、快照到期撤回当前资格、公开版无效响应撤回与重试、
原生侧栏端到端连接恢复。中文视觉复核采用本地 Windows 截图。
本地阶段和最终 PR CI 的计数分别列示；功能合并提交 CI 与 Release 工作流均已独立通过。

已发布 Release 的 Ubuntu 浏览器流程通过 36 项功能检查，其原始截图因缺少 CJK 字库而出现中文方框，
不作为中文视觉通过证据。[Linux CI](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml)
与发布工作流已补充 Noto CJK 安装和字体解析检查，后续截图与执行证据由维护 CI 记录。
此项环境与文档维护不修改应用源码、资源、版本或已发布资产。

跳过项均有平台范围：Windows 不执行 `test_remote_bearer_token_file_rejects_broad_posix_permissions`，
因为 POSIX 权限位在 Windows 上不具权威性；Ubuntu 不执行 `test_capture_daily_script.py` 中
`test_evidence_sync_pushes_versioned_artifacts_to_local_bare_remote` 与
`test_evidence_sync_rejects_matching_product_fetch_or_push_identity`，因为它们属于 Windows PowerShell 采集车道。
CI 日志给出跳过总数，跳过原因依据受测源码的平台条件核对。
本地权限测试文件另外通过 `27 passed, 1 skipped, 6 subtests passed` 的定向复核。

[v0.5.0 离线教学截图](../assets/lensos-option-demo.png) 已从本轮 Windows 安装包浏览器检查保存；
截图仅说明界面外观，不充当研究证据或浏览器总门禁的通过记录。

## 公开整合与版本身份

[PR #17](https://github.com/Lens-less/LensOS-Option/pull/17) 于 `2026-09-08T02:43:00Z` 实际 squash 合并。
完整 PR CI 检查的 head 为 `b7a363d9e842f5a96fd99e76cd299798f0a40456`，功能合并提交为
`0bac2f64704e50732842de49e4e72ed09e918c16`；两者的 tree 均为
`127e954999e886785fff036c3687513b7b3cd618`。提交身份不同，代码内容相同。

`setuptools==84.0.0` 与 `@types/node==26.4.1` 已纳入公开 `main`。
[PR #15](https://github.com/Lens-less/LensOS-Option/pull/15) 和
[PR #16](https://github.com/Lens-less/LensOS-Option/pull/16) 以被本轮整合替代的原因关闭，状态为
`CLOSED`，不计作已合并 PR。私有 archive 历史不属于此次公开整合。

## 发布资产与独立安装

[v0.5.0 Release](https://github.com/Lens-less/LensOS-Option/releases/tag/v0.5.0) 的三个资产均已上传。
实际下载后的两个构建产物与发布的
[SHA256SUMS](https://github.com/Lens-less/LensOS-Option/releases/download/v0.5.0/SHA256SUMS) 逐项匹配：

| 资产 | 大小（字节） | SHA-256 |
| --- | --- | --- |
| [Python wheel](https://github.com/Lens-less/LensOS-Option/releases/download/v0.5.0/crypto_options_research_console-0.5.0-py3-none-any.whl) | 619893 | `968318b12b24cb44f404f714032fac5536ffb70cdfa794e0ab7226b9759622a3` |
| [Chrome 扩展 ZIP](https://github.com/Lens-less/LensOS-Option/releases/download/v0.5.0/lensos-option-chrome-extension-v0.5.0.zip) | 96608 | `825865a075968a38610194bc3aa6a68193e28ccd39d35813112df0be29f9b2c4` |

下载的 wheel 在新建虚拟环境中使用 `--no-index --no-deps` 安装，随后由
`tools/check_installed_wheel.py` 检查 6 个 console launcher、包内资源、运行依赖和 API smoke，全部通过。
`tools/check_release_versions.py` 同时核对标签、源码、wheel 与扩展 ZIP 的版本为 `0.5.0`。

包内源码摘要为 `sha256:5e720738782a5239c5cd7d98d28468f22782e1e3efbf410948de8c1b749a4cbf`，
以干净公开标签检出核对源码摘要，确认与该版本声明的源文件一致。构建身份指向功能合并提交
`0bac2f64704e50732842de49e4e72ed09e918c16`，Git 状态为 `clean`。

## 本机公开数据实测

2026-09-08T01:27:17Z，以 `pull-snapshot --instrument-limit 20` 验证公开采集连通性：
返回 5 个 feed（vol_index、order_book、index_spot、events、funding_basis）、908 条合约元数据、
20 行快照、0 个 fetch error，`quality_gate_passed=true`，1 个可供验证的到期日（2026-09-18）。

在同一捕获时钟、package 0.5.0 下运行 `analysis`，实际结果为 `trust=degraded`、
`BLOCKED_BY_EVIDENCE`，原因包含 `MARKET_EVIDENCE_NOT_TRUSTED`、`TRUST_EVIDENCE_NOT_OBSERVED`
与 `DATA_TRUST_THRESHOLD_EVIDENCE_MISSING`，且 `execution_allowed=false`。原始临时采集不进入公开发布。

这证明本机当时可读取公开来源且研究门禁保留阻断；小预算采集不证明全期限覆盖、连续运营、
可信提升、策略有效或模型就绪。

## 研究与运营边界

自动化检查证明相应的软件行为；固定快照复现证明相同构建、输入与时钟的确定性。
两者都不能证明真实策略的胜率、预测校准或盈利能力。实际 cohort 与提升证据不足时，
继续保留 `INSUFFICIENT`、`EXPLORATORY`、`UNAVAILABLE` 或阻断状态。

本轮公开源码交付与静态站运营分别验收。公开 GitHub 推送或 Release 成功不解除
[公开部署挂起条件](../operations/public-deployment-suspension.md)。生产、密钥、付款和交易执行
不是本文的软件验收结果。

私有 archive 的历史不属于公开整合范围。公开开发以 `Lens-less/LensOS-Option` 的历史为基线；
需要的工作区改动经审查后应用，不能将旧 archive 分支、tag 或内部协作记录并入公开历史。

用户工作流见 [完成一次期权决策研究](../guides/decision-workflow.md)，面向安装者的变化与升级方法见
[v0.5.0 发布说明](../releases/v0.5.0.md)。
