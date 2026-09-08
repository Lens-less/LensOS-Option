# 贡献指南

从 [README 的快速开始](README.md#快速开始) 体验离线学习导览，再阅读下面的产品边界和
检查方法。当前交互契约在 [DESIGN.md](DESIGN.md)，研究数据合同在
[策略简报规格](docs/product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md)。
完整用户流程见 [决策研究指南](docs/guides/decision-workflow.md)，当前版本的验收证据见
[v0.5.0 交付记录](docs/product/2026-09-08-open-source-decision-platform.md)。
旧策略简报规格是基线；v0.5.0 的数字成本、风险口径与工件收紧以
[升级说明](docs/releases/v0.5.0.md#v040-用户必须重新生成报告) 为准。

## 设计红线

这是一个**入场前研究**工具，不是交易系统。

- 可信输出上限是不可变的 `EntryAdmissionDecision`，且恒有 `execution_allowed=false`。
- 仓库中**没有**实盘下单适配器，这是刻意的设计，不是待办事项。
- 不接受新增：下单路径、订单模板、手数/仓位 sizing 输出、paper/manual 下单控件。
- 所有门禁都是 fail-closed：证据缺失时必须降级为「阻断」，不得默认放行。
- 离线教学示例独立于真实研究报告；虚构价格不能进入研究 JSON 或成为已验证证据。

如果你认为某个门禁过严，请先开 issue 讨论，并在其中给出支持放宽的证据，不要直接
在 PR 中改门禁。

## 环境准备

需要 Python ≥ 3.12 和 Node 22.22.2（或 `web/package.json` 允许的更新版本）。Python 侧运行时零依赖，
只有构建、测试和开发工具需要安装。这些工具由 `constraints.txt` 精确约束；先按约束
安装 installer 与 build backend，再禁用浮动的隔离构建环境安装开发 extra：

```powershell
python -m pip install --upgrade -c constraints.txt pip setuptools
python -m pip install --no-build-isolation -c constraints.txt -e ".[dev]"

npm --prefix web ci
```

CI 与发布流程使用同一份约束。日常升级由 Dependabot 发起；升级 PR 必须同时更新
`constraints.txt`，并通过完整 Python 版本矩阵后才能合并。

## 本地检查

在仓库根目录运行统一入口：

```powershell
python tools/verify.py
```

完整检查运行 Python Ruff（含 tests）、静态类型、编译、测试和 API/sidecar smoke，Web lint、测试、
三种构建、公开 bundle 边界和扩展文件检查，最后构建 wheel、在临时环境离线安装，再启动
demo 完成浏览器流程。CI 还负责支持平台矩阵、容器和构建产物与源码的一致性检查。

浏览器验收需要本机已安装的 Chrome、Chromium 或 Edge。脚本会查找常见安装位置；找不到时，
用 `BROWSER_PATH` 指向可执行文件。它不会自动下载浏览器或安装项目依赖。

```powershell
# 可选：指定浏览器
$env:BROWSER_PATH = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

# 日常反馈；明确跳过构建、产物和浏览器检查
python tools/verify.py --quick

# 查看计划执行的步骤，不运行检查
python tools/verify.py --list
```

Python 的渐进静态类型范围由 `pyproject.toml` 配置，单独运行 `python -m mypy --no-incremental`；mypy 是开发
依赖，不进入运行时。新增类型边界应在该配置下验证，不用大范围 `Any` 或忽略注释掩盖新错误。

快速检查不是完整验收。单独检查一个已安装的 wheel 时，向浏览器脚本传入该虚拟环境的
Python 绝对路径；用 `--output-dir` 保存桌面/窄屏截图和 `report.json`：

```powershell
node tools/browser-smoke.mjs --python C:\path\to\wheel-venv\Scripts\python.exe --extension-dir C:\path\to\Option\web\dist\chrome-extension --output-dir artifacts/browser-smoke
```

`--extension-dir` 指向已构建的扩展目录，增加首次连接和重试恢复检查；省略时仅检查网页。
浏览器流程验证离线导览、真实快照阻断和窄屏/键盘交互；通过它不代表真实行情、历史胜率或模型
校准已经具备证据。脚本选项以 `--help` 为准。

### 可选：pre-commit 钩子

仓库提供了最小的 `.pre-commit-config.yaml`（ruff lint、合并冲突标记、超大文件检查），
作为**可选**的本地辅助：

```powershell
pip install pre-commit
pre-commit install
```

它只提供提交前的快速提醒；完整验收仍使用 `tools/verify.py` 和 CI。

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

界面变更还应覆盖用户看到的状态：过期后不再显示当前资格，历史判定带评估时间，加载失败
撤下旧结果且重试能恢复。教学导览验证交互与收益示例，真实报告验证证据门禁，两者分开断言。

## 代码风格

- Python 由 `ruff` 约束，配置在 `pyproject.toml`。提交前跑 `python -m ruff check --fix`。
- TypeScript 由 `tsc` 严格模式约束（`npm run lint`）。
- 代码标识符、API 字段名、日志与错误信息一律使用英文；文档以中文为主。
- 错误信息要可操作：告诉用户该**做什么**，而不只是哪里错了。

## 首次贡献任务

下面是可独立提交的小任务，供认领时选择；不是本轮已经实现的功能。先在 issue 中确认仍未被
认领，一个 PR 只选一项。文件入口、验收和边界均列在表中，不要求连接行情或配置账户。

| 小任务 | 文件入口 | 验收 | 范围限制 |
| --- | --- | --- | --- |
| 为教学收益曲线增加可读数值表 | `web/src/components/demo/DemoGuide.tsx` 与同目录测试 | 每种结构列出保护腿两侧、盈亏平衡点和当前滑块价格的损益；键盘/读屏可读，数值与现有 payoff 一致 | 只用教学点数；不增加真实行情、费用假设、胜率或下单控件 |
| 为复现不一致提供字段级说明 | `tools/reproduce_research.py`、`tests/test_reproduce_research.py` | `--verify` 失败时列出不同的顶层字段；相同输入仍成功，改时钟/改结果的案例仍非零退出 | 不自动修正旧结果、不忽略构建身份、不修改 trust 或门禁 |
| 完善英文复现教程 | `docs/guides/reproducible-case.md`，新增英文镜像并接入文档地图 | 保留所有可执行命令、退出码和未验证边界；读者能完成生成/复核两步 | 不翻译机器字段、不硬编码当前构建摘要、不增加金融结论 |
| 给术语表补充可复核的状态例子 | `docs/glossary.md`、`docs/guides/reproducible-case.md` | 用复现结果解释 `untrusted`、`BLOCKED_BY_EVIDENCE` 和 `NO_TRADE` 的不同层次，各给字段路径和下一步 | 不能把“重现成功”写成模型或市场已通过；例子不要求账户凭证 |

首次 PR 建议附 `python tools/reproduce_research.py --check` 的短输出，说明读到的真实阻断。
改界面时再附桌面与窄屏结果；完整检查仍按上面的验证入口执行。

## 提交与 PR

- 从公开仓库 `Lens-less/LensOS-Option` 的最新默认分支创建开发分支。旧私有 archive 只用于历史追溯，
  不将其分支、tag 或提交祖先合并回公开仓库；推送前核对实际 remote URL，见 [安全政策](SECURITY.md#repository-hygiene)。
- 一个 PR 只做一件事，便于审阅和回滚。
- commit message 说明「为什么」，而不只是「改了什么」。
- 填写 PR 模板中的验证清单，只勾选你实际运行过的项。
- 变更产品入口、合同或模块边界时，同步 README、DESIGN 或架构文档；旧实现仍兼容时明确标注。

验收报告写清实际版本、输入、命令、结果和仍未运行的层级。测试通过、HTTP 200、快照复现、
浏览器交互、跨平台 CI 与发布资产分别举证；不要用历史计数或本地成功替代本轮远端结果。
报告研究问题时附 `reason_codes` 和必要的脱敏输入，不以截图中的“通过”推断模型已提升。

## 安全问题

不要为安全漏洞提交公开 issue。请通过
[GitHub Security Advisory](https://github.com/Lens-less/LensOS-Option/security/advisories/new)
私下报告，详见 [SECURITY.md](SECURITY.md)。

## English contributor summary

This is a pre-entry research tool, not a trading system. Contributions must
preserve `execution_allowed=false`, keep every gate fail-closed, and must not add
order placement, position sizing, or paper/manual execution controls.

Use Python 3.12+ and a Node version accepted by `web/package.json`. After installing
the development dependencies and running `npm --prefix web ci`, run
`python tools/verify.py` from the repository root. Full mode checks Python, Web,
all three build targets, public and extension artifacts, then installs a fresh
wheel in a temporary environment and tests its browser journey. An installed
Chrome, Chromium, or Edge is required; set `BROWSER_PATH` if automatic discovery
cannot find it. No browser or dependency is downloaded automatically.

`python -m mypy --no-incremental` checks the gradual Python type boundary configured in
`pyproject.toml`; mypy is a development dependency only. The starter-task table
above offers four bounded contributions with concrete files and acceptance
criteria. Choose one task and preserve the explicit scope limits.

`--quick` skips artifact and browser verification; `--list` only prints steps.
To inspect an already installed wheel, run `node tools/browser-smoke.mjs --python
<absolute-venv-python-path> --extension-dir <absolute-built-extension-directory>
--output-dir <directory>` for screenshots and a JSON report. Omitting the extension
directory checks the web surface only. CI additionally checks the supported platform matrix, container, and
committed build synchronization.

Optionally, `pip install pre-commit && pre-commit install` enables the minimal
local hooks in `.pre-commit-config.yaml`; these do not replace full verification.
Tests must use deterministic fixtures and explicit clocks; do not call the live
Deribit API. Changes to `web/` must include the synchronized
`crypto_options_report/static/evidence/` build output.

Keep fictional teaching examples outside research JSON and evidence promotion.
Test stale-state labeling and recovery after failed loads at the visible UI
boundary. Update the current product or architecture documentation when changing
those contracts, while identifying compatibility behavior that still exists.

Keep each pull request focused, explain why the change is needed, and report
security or conduct issues privately through GitHub Security Advisories rather
than a public issue. See [SECURITY.md](SECURITY.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Base contributions on the public repository's current default branch. Keep the
old private archive history isolated; review changes without importing its
ancestry. Verify the actual remote URL before pushing. Report evidence for this
build and distinguish unit tests, browser behavior, CI, and published assets.
