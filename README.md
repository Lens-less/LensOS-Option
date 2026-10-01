# LensOS Option · 期权决策研究台

[English](README.en.md) · [使用指南](docs/decision-desk.md) · [贡献](CONTRIBUTING.md) · [变更记录](CHANGELOG.md)

[![CI](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml/badge.svg)](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Lens-less/LensOS-Option)](https://github.com/Lens-less/LensOS-Option/releases/latest)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

面向 Deribit BTC / ETH **USDC 线性期权**的本地研究台：发现候选，在同一组假设下对比，
再保存观察与复核。每个结果都能追到精确合约、双边报价、单位、时间和筛选原因。

- **发现**：按方向、到期和结构筛选；显示扫描覆盖、可比候选与排除原因。
- **对比 / 决定**：选择 2–3 个候选，使用共同的价格、时间与 IV 情景比较收益图、费用和边界。
- **观察**：将精确腿与研究假设保存在当前浏览器，重新取数时复核同一结构。

候选由确定性规则产生和排序，不是 AI 预测或正 EV 证明。到期收益、模型压力情景与真实概率
分开；原始期权收益边界不含手续费或动态交割费，不是最终损失上限。全过程仅研究，无账户连接、下单或
手数建议，`execution_allowed=false` 恒成立。

## 演示

默认启动提供明确标注的**离线合成演示**。用虚构的 BTC / ETH USDC 合约和报价体验
发现、对比和观察；它们不是 Deribit 当前行情、历史实绩或可信证据。旧版学习导览与
`research_report.v1` 证据界面保留在 `?view=legacy` 兼容入口，新研究合同为 `decision_desk.v1`。

## 快速开始

需要 Python ≥ 3.12。获取并安装公开源码：

```powershell
git clone https://github.com/Lens-less/LensOS-Option.git
cd LensOS-Option
python -m pip install .
crypto-options-report start
```

默认自动打开[本地研究台](http://127.0.0.1:8000/index.html)，终端也会打印地址。离线演示不需要
Node、网络、账户或密钥；Python 侧零第三方运行依赖。服务只监听 `127.0.0.1`。
`Ctrl+C` 停止；端口冲突时加 `--port 8001`，不自动打开浏览器时加 `--no-open-browser`。

在研究台点击“读取公开行情”即可切换；这一步才需要网络，无需重启服务。
也可停止当前服务后，直接启动公开行情模式：

```powershell
crypto-options-report start --current
```

这需要网络。完整合约登记与全链摘要用于扫描，只有受限短名单进一步读取双边报价；页面
分别显示扫描覆盖和深报价覆盖。“当前”描述数据来源，不保证有可比结构或已验证优势。
有效快照可能复用；重新取数须以实际数据截止时间为准。

已有旧报告采集文件，可在兼容界面回放：

```powershell
crypto-options-report start --snapshot artifacts/snapshots/btc-chain.json
```

`--snapshot` 打开旧版报告界面，读取原有市场快照格式；它不是新研究台的历史模式，
也不读取 `desk_market.v1`。刷新只重读本地文件，不能取得当前行情或提升旧报告门禁。
`--current` 与 `--snapshot` 不能同时使用。原有 `crypto-options-report demo`、采集 CLI
与 HTTP API 保持兼容；旧报告见 [历史研究流程](docs/guides/decision-workflow.md)。

按 [研究台使用指南](docs/decision-desk.md) 完成候选发现、共同情景对比和精确腿观察。
浏览器观察不自动监控、不记交易盈亏；复制记录也不构成订单。当前使用方式为本地运行，
这里不提供或承诺在线服务地址。

## 验证

配置开发环境后，在仓库根目录运行：

```powershell
python tools/verify.py
```

它检查 Python、Web、静态包与扩展构建，并验证安装后浏览器流程。需要已安装的 Chrome、
Chromium 或 Edge，可用 `BROWSER_PATH` 指定。`--quick` 跳过构建和浏览器；`--list` 只列步骤。
环境与产物同步要求见 [贡献指南](CONTRIBUTING.md#环境准备)。本地通过不替代跨平台 CI 或真实行情证据。

旧报告的离线固定复核入口仍可使用：

```powershell
python tools/reproduce_research.py --check
```

它复核旧合同的输入、门禁与标识；不验证新研究台的市场优势，也不证明盈利。

## 文档与边界

| 你要做什么 | 从这里开始 |
| --- | --- |
| 完成发现 → 对比 / 决定 → 观察 | [研究台使用指南](docs/decision-desk.md) |
| 了解新合同与兼容边界 | [当前设计](DESIGN.md#1-current-product-contract) |
| 复核旧报告、证据与模型门禁 | [历史研究流程](docs/guides/decision-workflow.md) · [离线案例](docs/guides/reproducible-case.md) |
| 使用既有采集 CLI、API 与扩展 | [本地工具](docs/guides/local-tools.md) · [API 参考](docs/api-reference.md) |
| 参与开发与验收 | [贡献指南](CONTRIBUTING.md) · [架构](docs/architecture.md) |
| 查阅既有版本和安全政策 | [发布说明](docs/releases/v0.5.0.md) · [安全政策](SECURITY.md) |

本 README 描述当前源码，下载版本以 [GitHub Releases](https://github.com/Lens-less/LensOS-Option/releases)
的实际资产为准。代码采用 [Apache-2.0](LICENSE)；仓库的 [数据许可](LICENSE-DATA) 不替代数据提供者的授权。
Deribit 将行情及派生数据限定为个人用途，其他发布或转发需事先书面许可；本工具的公开代码
不授予行情再分发权。[Deribit 条款 §2.10](https://support.deribit.com/hc/en-us/articles/25944532191645-Deribit-Exchange-Membership-Terms-Deribit-FZE)

`decision_desk.v1` 中的可比候选只是结构研究结果，不提升旧 `strategy_brief.v1`、
`EntryAdmissionDecision`、历史 `VALIDATED` 或预测 `CALIBRATED` 门禁。
缺失、过期或交叉报价不能生成当前可比结果；不支持 inverse 收益混算、账户资料、订单模板、
实盘或 paper/manual 执行控件。漏洞请按 [SECURITY.md](SECURITY.md) 私下报告。

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
