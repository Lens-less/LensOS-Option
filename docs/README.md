# 文档地图

本目录按三层组织：

1. 当前产品契约 - 描述现在的公开行为与支持边界。
2. 参考资料 - PRD、架构、术语和运行手册等输入文档。
3. 历史归档 - 已完成、已替代或仅供追溯的材料。

首次使用从 [README 快速开始](../README.md#快速开始) 进入离线学习导览；修改界面先读
[DESIGN 的当前契约](../DESIGN.md#1-current-product-contract)，修改研究字段先读
[策略简报规格](product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md)。
历史设计解释兼容实现的来由，不替代当前合同或门禁。

## 按任务阅读

| 任务 | 文档 |
| --- | --- |
| 从离线学习到公开采集、研究、阻断恢复与复核 | [完整决策研究流程](guides/decision-workflow.md) · [English](guides/decision-workflow.en.md) |
| 原 README 中的研究方法、EV、风险与样本量 | [研究工作流](guides/research-workflows.md) · [English](guides/research-workflows.en.md) |
| CLI、HTTP API 与本地扩展 | [本地工具](guides/local-tools.md) · [English](guides/local-tools.en.md) |
| 采集、计划任务、证据积累和静态发布 | [操作者指南](guides/operator-guide.md) · [English](guides/operator-guide.en.md) |
| 无网络复核一次实际研究结果 | [离线案例](guides/reproducible-case.md) |
| 选择首次贡献范围 | [首次贡献任务](../CONTRIBUTING.md#首次贡献任务) |

## 当前产品契约

| 文档 | 说明 |
| --- | --- |
| [`product/2026-09-08-open-source-decision-platform.md`](product/2026-09-08-open-source-decision-platform.md) | v0.5.0 范围、验收矩阵、实际交付证据与研究边界。 |
| [`releases/v0.5.0.md`](releases/v0.5.0.md) | v0.5.0 使用者变化、安装与升级方法；发布状态以实际资产为准。 |
| [`glossary.md`](glossary.md) | 术语表。阅读其他文档前建议先看这里。 |
| [`api-reference.md`](api-reference.md) | 内部 HTTP API 参考，含路由、方法、鉴权与响应契约。 |
| [`api-public.md`](api-public.md) | 公开静态 JSON schema、字段字典、curl 示例与证据分级说明。 |
| [`architecture.md`](architecture.md) | 架构总览与信任链路。 |
| [`operations/public-publishing.md`](operations/public-publishing.md) | Cloudflare Pages 公开发布契约、头条一日滞后、恢复与证据仓约束。 |
| [`operations/production-runbook.md`](operations/production-runbook.md) | 本地与生产运行、健康检查、回滚和密钥轮换。 |
| [`../DESIGN.md`](../DESIGN.md) | 开头两节是当前一屏简报、教学导览、状态与恢复契约；旧流程已标为历史/兼容说明。 |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | 环境准备、统一 verify 入口、浏览器前置条件和贡献检查。 |
| [`../SECURITY.md`](../SECURITY.md) | 安全边界与漏洞报告流程。 |
| [`../CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) | 社区行为、私下报告与执行准则。 |
| [`operations/public-deployment-suspension.md`](operations/public-deployment-suspension.md) | 公开部署的显式挂起决议与解除前置条件。 |
| [`operations/public-history-rewrite.md`](operations/public-history-rewrite.md) | 历史净化的隔离演练、固定工具版本、PR refs 阻塞与验收契约。 |
| [`operations/public-release-cutover.md`](operations/public-release-cutover.md) | 切 public 前的一次性冻结、历史、Actions、GitHub 设置与 v0.1.0 清单。 |
| [`product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md`](product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md) | v0.2–v0.4 极简策略简报、同构历史和精确策略校准的 canonical 规格。 |
| [`product/2026-09-05-first-use-iteration.md`](product/2026-09-05-first-use-iteration.md) | 首次使用迭代的输入规格：离线教学、过期状态一致性、错误恢复与 wheel 浏览器验收。 |
| [`product/2026-09-05-completion-plan.md`](product/2026-09-05-completion-plan.md) | 职责拆分与开源改造的输入计划；最新交付状态见 v0.5.0 记录。 |
| [`product/strategy-brief-historical-protocols-v1.md`](product/strategy-brief-historical-protocols-v1.md) | 三个初始策略族的历史回放、冻结协议与 holdout 边界。 |
| [`product/exact-strategy-forecast-protocol-v1.md`](product/exact-strategy-forecast-protocol-v1.md) | 精确策略预测校准、提升、过期与自动降级协议。 |
| [`releases/v0.1.0.md`](releases/v0.1.0.md) | 首个公开版本的安装、产物、完整性校验与研究边界说明。 |
| [`releases/v0.4.0.md`](releases/v0.4.0.md) | v0.2–v0.4 一体化交付能力、证据纪律和未成熟 cohort 边界。 |

## 一级目录归属

- [`operations/`](operations/) - 当前运维契约、公开发布边界与生产运行手册。
- [`guides/`](guides/) - 任务教程与从 README 迁入的研究、工具和操作者说明。
- [`product/`](product/) - 当前产品规格、发布硬化规格与后续 superseding 决议。
- [`research/`](research/) - 研究输入与历史方向；不是当前 North Star，也不直接构成发布验收。
- [`archive/`](archive/) - 已完成、已替代或仅供追溯的历史材料。

## 参考资料

- [`model-promotion.md`](model-promotion.md) - 模型提升提案与门槛。
- [`product/2026-08-02-public-product-spec.md`](product/2026-08-02-public-product-spec.md) - 早期公开产品规格；首页叙事以当前策略简报规格为准。
- [`product/2026-08-03-public-release-hardening-spec.md`](product/2026-08-03-public-release-hardening-spec.md) - 公开发布硬化的原始范围。
- [`product/2026-08-12-continuity-and-consistency-spec.md`](product/2026-08-12-continuity-and-consistency-spec.md) - 运营连续性修复的原始范围。
- [`product/2026-08-12-data-usability-and-open-source-readiness-spec.md`](product/2026-08-12-data-usability-and-open-source-readiness-spec.md) - 数据可用性、历史净化与开源切换的原始范围。

## 历史归档

- [`archive/`](archive/) - 已完成或已替代的调研、报告与旧规格。
- [`releases/`](releases/) - 版本说明与资产使用指引；实际发布状态以对应记录及 GitHub 资产为准。

## 语言约定

- 仓库主文档以中文为主。
- 公开静态页以中文为默认页；英文镜像如发布，则放在 `/en/`。
