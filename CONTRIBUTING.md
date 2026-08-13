# 贡献指南

感谢你考虑为本项目贡献代码。开始之前，请先读完「设计红线」一节——本项目有一条
不可协商的产品边界，不了解它提交的 PR 很可能会被直接拒绝。

## 设计红线

这是一个**入场前研究**工具，不是交易系统。

- 可信输出上限是不可变的 `EntryAdmissionDecision`，且恒有 `execution_allowed=false`。
- 仓库中**没有**实盘下单适配器，这是刻意的设计，不是待办事项。
- 不接受新增：下单路径、订单模板、手数/仓位 sizing 输出、paper/manual 下单控件。
- 所有门禁都是 fail-closed：证据缺失时必须降级为「阻断」，不得默认放行。

如果你认为某个门禁过严，请先开 issue 讨论，并在其中给出支持放宽的证据，不要直接
在 PR 中改门禁。

## 环境准备

需要 Python ≥ 3.12 和 Node 22.22.2（或 `web/package.json` 允许的更新版本）。Python 侧运行时零依赖，
只有构建、测试和开发工具需要安装。这些工具由 `constraints.txt` 精确约束；先按约束
安装 installer 与 build backend，再禁用浮动的隔离构建环境安装开发 extra：

```powershell
python -m pip install --upgrade -c constraints.txt pip setuptools
python -m pip install --no-build-isolation -c constraints.txt -e ".[dev]"

cd web
npm ci
```

CI 与发布流程使用同一份约束。日常升级由 Dependabot 发起；升级 PR 必须同时更新
`constraints.txt`，并通过完整 Python 版本矩阵后才能合并。

## 本地检查

提交前请在本地跑完这些，它们与 CI 一致：

```powershell
# Python
python -m pytest -q
python -m ruff check crypto_options_report tools
python -m crypto_options_report.api --smoke

# Web
cd web
npm test
npm run lint
npm run build
```

### 可选：pre-commit 钩子

仓库提供了最小的 `.pre-commit-config.yaml`（ruff lint、合并冲突标记、超大文件检查），
作为**可选**的本地辅助：

```powershell
pip install pre-commit
pre-commit install
```

它不替代任何门禁——CI 的权威门禁仍是上面的 pytest / ruff / web 三件套。

### 修改了 `web/` 时的额外要求

`crypto_options_report/static/evidence/` 是打进 Python wheel 的前端构建产物，它被
提交在仓库中。修改前端后必须重新构建并**一并提交产物**，否则 CI 会失败：

```powershell
cd web
npm run build
git add ../crypto_options_report/static/evidence
```

CI 通过 `git diff --exit-code -- crypto_options_report/static/evidence` 校验产物与
源码一致。

## 测试约定

本项目是 evidence-first、可回放的：测试应基于 `tests/fixtures/` 中的固定快照和显式
的 `--generated-at` 时钟，不依赖实时网络。新增功能请附带覆盖**证据缺失/损坏**路径的
测试，而不只是 happy path——fail-closed 行为正是本项目的核心价值。

不要在测试中访问真实的 Deribit 接口。

## 代码风格

- Python 由 `ruff` 约束，配置在 `pyproject.toml`。提交前跑 `python -m ruff check --fix`。
- TypeScript 由 `tsc` 严格模式约束（`npm run lint`）。
- 代码标识符、API 字段名、日志与错误信息一律使用英文；文档以中文为主。
- 错误信息要可操作：告诉用户该**做什么**，而不只是哪里错了。

## 提交与 PR

- 一个 PR 只做一件事，便于审阅和回滚。
- commit message 说明「为什么」，而不只是「改了什么」。
- 填写 PR 模板中的验证清单，只勾选你实际运行过的项。

## 安全问题

不要为安全漏洞提交公开 issue。请通过
[GitHub Security Advisory](https://github.com/Lens-less/LensOS-Option/security/advisories/new)
私下报告，详见 [SECURITY.md](SECURITY.md)。

## English contributor summary

This is a pre-entry research tool, not a trading system. Contributions must
preserve `execution_allowed=false`, keep every gate fail-closed, and must not add
order placement, position sizing, or paper/manual execution controls.

Use Python 3.12+ and a Node version accepted by `web/package.json`. Install the
development environment and run the same local checks shown above: the complete
Python test suite, Ruff, the API smoke test, and the web test/lint/build trio.
Optionally, `pip install pre-commit && pre-commit install` enables the minimal
local hooks in `.pre-commit-config.yaml`; the authoritative gates remain the
pytest/ruff/web checks above.
Tests must use deterministic fixtures and explicit clocks; do not call the live
Deribit API. Changes to `web/` must include the synchronized
`crypto_options_report/static/evidence/` build output.

Keep each pull request focused, explain why the change is needed, and report
security or conduct issues privately through GitHub Security Advisories rather
than a public issue. See [SECURITY.md](SECURITY.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
