# 文档地图

文档分三层：**当前产品契约**（描述产品现在的行为）、**参考资料**（研究与调研输入）、
**历史归档**（已完成或已被取代的材料）。文档存在本身不代表它是当前的验收契约。

## 当前产品契约

| 文档 | 内容 |
| --- | --- |
| [`glossary.md`](glossary.md) | 术语表。项目自造词较多，读其他文档前建议先看这里。 |
| [`api-reference.md`](api-reference.md) | HTTP 端点参考：路径、方法、鉴权、响应契约。 |
| [`architecture.md`](architecture.md) | 面向贡献者的架构总览与信任链路。 |
| [`model-promotion.md`](model-promotion.md) | **提案**：模型提升需要什么证据、改变什么、以及如何降级。信号验证出结果之前必须先定下来的那些决定。 |
| [`../DESIGN.md`](../DESIGN.md) | Evidence Console 与 Chrome 伴侣的产品与交互契约。 |
| [`operations/production-runbook.md`](operations/production-runbook.md) | 支持的本地与生产运行流程、健康检查、回滚、密钥轮换。 |
| [`../SECURITY.md`](../SECURITY.md) | 安全边界与漏洞报告流程。 |
| [`product/2026-07-25-local-chrome-companion-acceptance.md`](product/2026-07-25-local-chrome-companion-acceptance.md) | 个人本地 Chrome 伴侣的可执行验收边界。 |
| [`product/2026-07-25-cleanup-and-chrome-extension-plan.md`](product/2026-07-25-cleanup-and-chrome-extension-plan.md) | 已接受的扩展迁移与清理决策。 |

## 参考资料

`research/` 是产品方向与数据质量的输入，不是验收契约：

- [`research/deribit-options-intelligence-platform-prd.md`](research/deribit-options-intelligence-platform-prd.md) — 当前平台北极星 PRD。
- [`research/data-trustworthiness-prd.md`](research/data-trustworthiness-prd.md) — 当前证据质量契约。
- [`research/crypto-options-data-quality-remediation-prd.md`](research/crypto-options-data-quality-remediation-prd.md) — 数据质量整改 PRD。
- [`research/data-remediation-backlog.md`](research/data-remediation-backlog.md) — 数据整改待办。
- [`research/current-data-fetching-audit.md`](research/current-data-fetching-audit.md) — 现有抓取路径审计。
- [`research/open-source-integration-opportunities.md`](research/open-source-integration-opportunities.md) — 开源集成机会调研。
- [`operations/production-hardening-plan.md`](operations/production-hardening-plan.md) — 生产加固计划。

## 历史归档

[`archive/`](archive/README.md) 保留已完成的调研、被取代的方案和时点报告：

- `archive/v1-spec/` — 2026-07-07 的 v1.1 PRD 与开发 Spec。**已被取代**，其中描述的
  paper trading、半自动执行等能力是当前产品刻意不提供的。
- `archive/reports/` — 时点性的整改报告、验证报告与竞品调研。

归档内容不定义当前产品行为，除非有当前文档明确引用其中某个工件作为证据。

## 关于本仓库的构建过程产物

本仓库曾跟踪一批 AI 协作流程的内部产物（handoff、evidence store、controller
状态、`issues/` 工单包）。它们已于 2026-07-26 从仓库移除并加入 `.gitignore`，
因为它们描述的是**本项目是怎么被构建的**，而不是产品做什么。相关说明见
[`../SECURITY.md`](../SECURITY.md)。
