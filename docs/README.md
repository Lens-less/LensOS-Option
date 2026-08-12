# 文档地图

本目录按三层组织：

1. 当前产品契约 - 描述现在的公开行为与支持边界。
2. 参考资料 - PRD、架构、术语和运行手册等输入文档。
3. 历史归档 - 已完成、已替代或仅供追溯的材料。

## 当前产品契约

| 文档 | 说明 |
| --- | --- |
| [`glossary.md`](glossary.md) | 术语表。阅读其他文档前建议先看这里。 |
| [`api-reference.md`](api-reference.md) | 内部 HTTP API 参考，含路由、方法、鉴权与响应契约。 |
| [`api-public.md`](api-public.md) | 公开静态 JSON schema、字段字典、curl 示例与证据分级说明。 |
| [`architecture.md`](architecture.md) | 架构总览与信任链路。 |
| [`operations/public-publishing.md`](operations/public-publishing.md) | Cloudflare Pages 公开发布契约、头条一日滞后、恢复与证据仓约束。 |
| [`operations/production-runbook.md`](operations/production-runbook.md) | 本地与生产运行、健康检查、回滚和密钥轮换。 |
| [`../DESIGN.md`](../DESIGN.md) | Evidence Console 与 Chrome 伴侣的产品和交互契约。 |
| [`../SECURITY.md`](../SECURITY.md) | 安全边界与漏洞报告流程。 |
| [`product/2026-08-02-public-product-spec.md`](product/2026-08-02-public-product-spec.md) | 公开产品规格。 |
| [`product/2026-08-03-public-release-hardening-spec.md`](product/2026-08-03-public-release-hardening-spec.md) | 本轮公开发布硬化规格。 |
| [`product/2026-08-12-continuity-and-consistency-spec.md`](product/2026-08-12-continuity-and-consistency-spec.md) | 运营连续性与 fail-closed 一致性修复规格（验证等待期的工程优先级）。 |
| [`operations/public-deployment-suspension.md`](operations/public-deployment-suspension.md) | 公开部署的显式挂起决议与解除前置条件。 |

## 一级目录归属

- [`operations/`](operations/) - 当前运维契约、公开发布边界与生产运行手册。
- [`product/`](product/) - 当前产品规格、发布硬化规格与后续 superseding 决议。
- [`research/`](research/) - 研究输入与 North Star PRD；提供方向，不直接构成发布验收。
- [`automation/`](automation/) - 自动化运行手册、goal board、handoff 与验证记录；保留为过程证据与运维上下文，**不是当前产品/部署契约**。
- [`archive/`](archive/) - 已完成、已替代或仅供追溯的历史材料。

## 参考资料

- [`model-promotion.md`](model-promotion.md) - 模型提升提案与门槛。

## 历史归档

- [`archive/`](archive/) - 已完成或已替代的调研、报告与旧规格。
- [`automation/`](automation/) 中与已结束 Goal、旧 controller、交付记录相关的文件，除被现行文档显式引用外，都按“历史过程记录”解读，不单独定义需求、验收或部署授权。

## 语言约定

- 仓库主文档以中文为主。
- 公开静态页以中文为默认页；英文镜像如发布，则放在 `/en/`。
