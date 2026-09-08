# LensOS Option · 期权决策研究平台

[English](README.en.md) · [文档](docs/README.md) · [贡献](CONTRIBUTING.md) · [变更记录](CHANGELOG.md)

[![CI](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml/badge.svg)](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Lens-less/LensOS-Option)](https://github.com/Lens-less/LensOS-Option/releases/latest)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

面向 BTC 期权研究者的决策平台：从 Deribit 公开行情出发，解释市场、比较有限风险结构，
再逐项复核成本、风险与证据。首页用一屏策略简报给出至多三张可复核的策略卡；证据不足时
明确显示“今日暂无可靠策略”。你可以继续追到候选、历史与证据来源，并保存可复现的研究记录。

- 策略卡列明精确合约、到期日、最低净权利金、分项成本、模型损失预算和取消条件。
- 卡片最高为 `WATCH`：结构到期收益有界不代表实际含交割费损失有绝对上限；费用上界未经验证。
- 历史与预测胜率只有在各自证据达到 `VALIDATED` / `CALIBRATED` 后才显示。
- 缺失、过期或校验失败一律阻断；不下单、不推荐手数，`execution_allowed=false` 永久成立。

## 演示

当前源码内置三步**离线学习导览**：选择示例 → 理解风险 → 查看依据。虚构标准化价格和线性
到期收益解释有限风险结构，拖动价格即可观察损益。教学数值不进入研究 JSON，不产生胜率或研究资格。

“**查看真实快照**”进入包内脱敏快照的证据页。页面保留真实阻断和评估时刻；历史通过不代表当前
可用。学习导览与研究结果分开，无需为了看懂产品先配置行情服务。

![v0.5.0 离线学习导览：选择有限风险结构](docs/assets/lensos-option-demo.png)

_图为 v0.5.0 安装包的离线教学页面；示例点数用于理解结构，不代表当前行情或策略资格。_

## 快速开始

需要 Python ≥ 3.12。首次获取公开源码：

```powershell
git clone https://github.com/Lens-less/LensOS-Option.git
cd LensOS-Option
python -m pip install .
crypto-options-report demo
```

打开命令输出的
[离线学习导览](http://127.0.0.1:8000/index.html?view=demo)。安装后的演示零第三方运行依赖，
不需要 Node、密钥、网络或采集产物。服务只监听 `127.0.0.1`；`Ctrl+C` 退出，端口冲突会明确报错。

需要隔离安装或使用 wheel 时，见 [v0.5.0 安装与升级](docs/releases/v0.5.0.md#安装与升级)。
下载包以 [GitHub Releases](https://github.com/Lens-less/LensOS-Option/releases) 的实际资产为准。

导览之后，按 [完成一次期权决策研究](docs/guides/decision-workflow.md) 采集公开数据、启动研究界面、
阅读阻断与到期状态，并保存复核记录。此流程不需要先配置账户。

## 验证

开发环境安装后，仓库根目录运行：

```powershell
python tools/verify.py
```

它验证 Python、Web、公开包和扩展产物，再从最终 wheel 启动浏览器流程。需要已安装的
Chrome、Chromium 或 Edge，可用 `BROWSER_PATH` 指定。`--quick` 明确跳过构建和浏览器，
`--list` 只列步骤；前置条件见 [贡献指南](CONTRIBUTING.md#环境准备)。

想先复核研究结果，运行无需网络的固定案例：

```powershell
python tools/reproduce_research.py --check
```

输出实际 trust、门禁、原因码、证据缺口和可复核摘要；**复现成功不等于证据可信或策略有效**。
保存与比较方法见 [离线研究案例](docs/guides/reproducible-case.md)。

## 专题入口

| 你要做什么 | 从这里开始 |
| --- | --- |
| 从学习导览走到真实数据研究与记录 | [完整决策研究流程](docs/guides/decision-workflow.md) |
| 理解相对价值、EV、风险与样本量 | [研究方法与工作流](docs/guides/research-workflows.md) |
| 使用 CLI、HTTP API 或 Chrome 侧栏 | [本地工具](docs/guides/local-tools.md) · [API 参考](docs/api-reference.md) |
| 复核包内固定研究案例 | [输入、门禁与复现](docs/guides/reproducible-case.md) |
| 配置采集、计划任务和静态发布 | [操作者指南](docs/guides/operator-guide.md) |
| 贡献一个范围清楚的小改动 | [首次贡献任务](CONTRIBUTING.md#首次贡献任务) |
| 了解模块和信任边界 | [架构](docs/architecture.md) · [当前设计](DESIGN.md#1-current-product-contract) |
| 查阅版本和安全政策 | [v0.5.0 说明](docs/releases/v0.5.0.md) · [安全政策](SECURITY.md) · [行为准则](CODE_OF_CONDUCT.md) |

## 操作者车道（Windows-only，可选）

采集、计划任务与静态发布已迁至 [操作者指南](docs/guides/operator-guide.md)，不属于首次使用
前置条件。进程成功不等于产生了可用于验证的观测；公开实例需独立检查证据可用性。

## 版本与公开发布

本版源码为 v0.5.0；改动与升级方法见 [发布说明](docs/releases/v0.5.0.md)，本轮检查与交付证据见
[验收记录](docs/product/2026-09-08-open-source-decision-platform.md)。已发布版本与下载资产以
[GitHub Releases](https://github.com/Lens-less/LensOS-Option/releases) 为准。代码按 [Apache-2.0](LICENSE)，公开数据产物按
[CC BY 4.0](LICENSE-DATA) 发布。研究发布与交易执行授权分开；后者永久 `NO-GO`。

## 安全边界

缺失证据不会变成通过；教学数据不会变成真实研究。系统不提供实盘适配器、订单模板或推荐手数。
历史协议和模型状态机存在，不代表当前已有足够的真实 cohort 或已校准的胜率。
漏洞请按 [SECURITY.md](SECURITY.md) 私下报告。

<a id="一屏策略简报"></a>
<a id="两种使用形态"></a>
<a id="静态公开版与发布"></a>
<a id="核心概念"></a>
<a id="当前状态"></a>
<a id="使用方式"></a>
<a id="找出有-edge-的候选"></a>
<a id="候选宇宙"></a>
<a id="这几个一起做会怎样"></a>
<a id="这个行权价昨天也这么贵吗"></a>
<a id="这个排序到底能不能预测什么"></a>
<a id="操作者采集与计划任务windows-only"></a>
<a id="ev-是负的到底是哪一种负"></a>
<a id="cli内部管道"></a>
<a id="http-api-与-evidence-console"></a>
<a id="chrome-研究伴侣个人本地"></a>
<a id="生产部署"></a>
<a id="开发"></a>
<a id="项目地图"></a>
<a id="许可"></a>

旧章节已迁至上方专题入口：[研究方法](docs/guides/research-workflows.md)、[采集与部署](docs/guides/operator-guide.md)、[CLI / API / 扩展](docs/guides/local-tools.md)、[开发与模块](CONTRIBUTING.md)。
