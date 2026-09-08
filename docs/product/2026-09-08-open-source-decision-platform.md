# v0.5.0 期权决策研究平台交付记录

日期：2026-09-08。本文记录本轮范围、验收方式和交付证据。本轮本地 Python、Web、三种构建、
公开包边界、独立 wheel 消费者与 36 项浏览器检查已通过。最终发布提交的远端 CI 与交付仍待执行。
未完成的项不视为通过，历史本地测试与旧版本 CI 不代替本轮证据。

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
| Python 全量测试 | 通过，含 1 项跳过 | `1424 passed, 1 skipped, 1685 subtests passed`；唯一跳过项为 Windows 上不具权威性的 POSIX 权限位检查，未作为通过计入 |
| 后续时钟修复定向回归 | 通过 | 新增时钟边界检查 `3 passed`；与前述完整 Python 测试分别记录，不合并成新的全量计数 |
| API smoke | 通过 | `python -m crypto_options_report.api --smoke` 通过 |
| 源码版本一致性 | 通过 | Python、Web、lockfile、lockfile root、扩展均为 `0.5.0` |
| 离线研究复现 | 通过 | 两次完整求值一致；实际输出 `untrusted`、`NO_TRADE`、`BLOCKED_BY_EVIDENCE`、`execution_allowed=false` |
| Web lint | 通过 | `tsc --noEmit --pretty false --noUnusedLocals --noUnusedParameters` 通过 |
| Web 全量测试 | 通过 | 43 个测试文件、480 项测试通过，包含真实扩展消息链路与缓存拒绝计数回归 |
| 三种 Web 构建与公开边界 | 通过 | 内部、公开、Chrome 扩展构建通过；公开 bundle 边界与扩展产物检查通过 |
| 独立 wheel 安装、版本与依赖 | 通过 | `0.5.0` wheel 干净安装；6 个 console launcher、包内资源、依赖与 API smoke 消费者检查通过 |
| 桌面、窄屏、键盘与故障恢复浏览器验收 | 通过 | 安装后 wheel 的 36 项检查通过，`passed=true`、0 个控制台/未处理错误、0 个外部页面请求；包含公开版恢复与真实原生 Chrome 侧栏连接、断线撤回、重试 |
| 跨平台 CI 与容器 | 待执行 | 仅记录本轮远端执行链接与结论 |
| 开源文档与命令 | 已核对 | 20 份文档、212 个仓库链接/锚点无错误；Release 说明中的 5 个文档链接使用绝对 GitHub URL 并核对目标路径/锚点；6 个 CLI/API 示例经当前 argparse 校验；文档 diff whitespace 检查通过；公开/私有历史隔离文档回归 1 项通过 |
| 公开分支整合、提交与 GitHub 推送 | 待执行 | 待记录公开提交和远端一致性 |
| v0.5.0 发布资产 | 待执行 | 若实际发布，填写 tag、Release 与校验和证据 |

本地证据分两阶段记录：先完成完整 Python 与基础检查；修复随后发现的时钟边界和真实侧栏
投影问题、缓存重投影丢失拒绝计数后，重新通过完整 Web、三种构建、独立 wheel 与 36 项浏览器流程。公开恢复脚本原先
错误等待折叠区域，现已校正，并通过实际公开构建的键盘展开与故障恢复重新验证。

浏览器覆盖离线导览在研究故障时仍可完成、快照到期撤回当前资格、公开版无效响应撤回与重试、
原生侧栏端到端连接恢复；桌面/窄屏简报、公开版与侧栏截图也已目视检查。后续小改动仍需对应
回归；最终发布提交以该提交自己的完整 CI 为准，不能把本地阶段记录当作尚未执行的远端结果。

唯一跳过项位于 `tests/test_review_transport_security.py:89`，原因是
`POSIX permission bits are not authoritative on Windows`。该文件定向复核结果为
`27 passed, 1 skipped, 6 subtests passed`。本地安装检查通过不代表 GitHub 发布资产或跨平台 CI 已完成。

[v0.5.0 离线教学截图](../assets/lensos-option-demo.png) 已从本轮安装包浏览器检查保存；
截图仅说明界面外观，不充当研究证据或浏览器总门禁的通过记录。

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
