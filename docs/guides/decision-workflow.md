# 完成一次期权决策研究

[项目首页](../../README.md) · [English](decision-workflow.en.md) · [研究方法](research-workflows.md)

从学习结构到复制研究复核，日常使用只需一个本地入口。当前主要研究 BTC 期权，使用
Deribit 公开行情。“证据不足，暂不形成策略”也是完整的研究结果。
`research_only=true`、`execution_allowed=false` 在任何结果下都成立。

## 1. 打开平台，先看懂结构

按 [快速开始](../../README.md#快速开始) 安装后运行：

```powershell
crypto-options-report start
```

浏览器默认自动打开离线学习导览。依次选择结构、拖动到期价格、查看研究依据。
教学价格是虚构点数；线性到期收益不包含真实成交、费用或到期前波动。
点击“进入研究简报”读取启动时选择的来源。默认离线启动使用包内脱敏历史快照，
保留评估时刻、证据状态和阻断原因。没有可靠策略卡是预期结果，教学结果不能补足研究证据。

服务只监听 `127.0.0.1`。`Ctrl+C` 停止；端口已占用时加 `--port 8001`，
不自动打开浏览器时加 `--no-open-browser`。

## 2. 明确本次研究的数据模式

停止演示后，选择一种输入，再打开“研究简报”：

```powershell
# 需要网络；通过已有 Deribit 公开数据源读取，无需账户或密钥
crypto-options-report start --current

# 历史回放；只读自己的本地输入
crypto-options-report start --snapshot artifacts/snapshots/btc-chain.json
```

已有标的历史可加 `--underlying-history artifacts/history/btc-daily.json`；
它只补充历史输入，不会生成历史期权链或已验证策略。`--current` 与 `--snapshot` 不能同时使用。

| 页面模式 | 更新按钮实际做什么 | 结论边界 |
| --- | --- | --- |
| Deribit 公开行情 | “更新公开行情”请求研究；有效期内复用已有分析，过期后重新采集 | 取数成功仍须通过质量、信任、费用与模型门禁 |
| 历史快照回放 | “重新读取快照”读取配置的本地文件，按采集时刻计算 | 回放窗口从该时点的年龄继续计时；历史通过不恢复当前资格 |
| 包内历史快照 | 重新读取包内脱敏案例，无网络采集 | 用于理解真实阻断，不代表当前行情 |
| 公开研究快照 | “重新载入本版”读取发布者预先生成的版次 | 网页不能生成新行情；以该版有效期为准 |

每次先核对模式、数据截止与有效期。重复点击不保证得到新报价或新的分析标识；
缓存复用时保留原评估时间。缺失、过期、不同步或交叉的报价，以及未完整列明的费用，
不能靠刷新变成可用策略。

## 3. 先读结论，再读依据

主导航保留“学习导览”和“研究简报”；需要细查时再打开“深入研究”中的候选工作台、
波动时序和排序验证。研究简报依次回答市场情况、是否有可靠策略、为什么。

| 顺序 | 看什么 | 如何解释 |
| --- | --- | --- |
| 来源与时效 | 来源、采集时间、评估时间、有效期 | 历史计算与当前可用性分别判断 |
| 总结论 | 策略卡或拒绝原因 | 没有合格策略时保持 `NO_TRADE`；卡片最高为 `WATCH` |
| 合约与报价 | 精确腿、到期日、bid/ask、币种与单位 | 报价来自该时点；单腿的一单位只表达结构比例，不是推荐手数 |
| 成本与风险 | 最低净权利金、分项成本、模型损失预算、取消条件 | 数字成本缺失时不生成卡片；预算不是实际含费损失的绝对上限 |
| 证据 | `data_status`、`data_trust`、原因码、历史与预测状态 | 质量通过不等于来源认证；排名不能换算成胜率 |
| 复核标识 | 分析标识、简报标识、评估时钟与来源 | 用于解释和重复计算，不构成执行授权 |

`entry.cost_breakdown` 明列入场费、滑点预算、分腿风险预算与交割费预算，单位与
`entry.currency` 一致。最低净权利金扣除前三项；损失预算还计入交割费预算。
`risk.max_loss_basis=PAYOFF_BOUND_PLUS_FROZEN_COST_BUDGET` 和
`delivery_fee_upper_bound_verified=false` 明示实际交割费上界未验证。
只勾选“已含费”或补零不能证明费用已覆盖。

历史胜率只在自身达到 `VALIDATED` 后显示，预测区间只在自身达到 `CALIBRATED` 后显示。
历史精确结构回放扣除交割费，但风险分母使用 payoff 损失加入场费，
以 `delivery_fee_in_risk_denominator=false` 明示。因此净 `R` 可以小于 `-1`，不能裁剪或隐藏。
各历史产物的结算口径需单独查看，信号验证使用日收盘结算代理。

## 4. 复制研究复核

有当前有效策略卡时，点击“复制研究复核”。文本保留精确腿、每腿 bid/ask 与单位、
报价时间、来源、分析与简报标识、评估时间、合约到期、最低净权利金、冻结成本、
模型损失预算、有效期、取消条件和重新取数要求。剪贴板不可用时，页面提供可手动复制的文本。

复制结果恒为 `WATCH / execution_allowed=false`，不产生订单，也不提供手数或仓位建议。
有效期过后不得沿用；再次复核前取得正的、同步的双边报价，并重新评估成本与所有证据。
没有策略卡时使用“复制拒绝原因”，保存本次 `NO_TRADE`、完整原因、来源、时间和分析标识。
过期记录明确标为资格暂停，不带旧策略腿或权利金指令。需要完整复现时另存原始 JSON，
不以教学卡或修改阈值替代结论。

完整复现另需保留原始快照、历史输入、UTC 评估时钟、构建版本与分析 JSON，保存到本地或
自有私有证据仓。公开缺陷报告只附最小脱敏 fixture、复现命令和预期/实际结果，
不附凭证或整份运行目录。无需新增交易日志或账户配置。

## 5. 按原因恢复

| 看到的状态 | 下一步 | 恢复成功的证据 |
| --- | --- | --- |
| 连接失败、超时或响应无效 | 检查本地服务、端口、文件和版本；恢复后重试 | 得到新的、合同校验通过的报告；旧结果不作为兜底 |
| 当前行情过期 | 点“更新公开行情”，等待采集与核验完成 | 新输入的截止时间和有效期可验证 |
| 历史快照过期 | 继续作为历史研究，或停止服务后用 `start --current` | 模式如实变化；不修改旧快照时间制造当前资格 |
| 公开版已停摆 | 等待操作者生成并发布合格版次 | 新版通过当前时效检查；重新载入旧版不能恢复 |
| 信任提升待完成、样本不足或产物未配置 | 按原因积累来源、到期 cohort 和模型协议所需证据 | 实际门槛通过；刷新、改 JSON 或离线复现都不能替代 |
| 证据过期或身份不匹配 | 核对协议、精确选腿、成本、有效期与来源，重新评估 | 当前策略对应的证据通过自身门禁 |
| 没有可靠策略 | 阅读拒绝原因，保存观察，等输入或证据变化再评估 | 不降低阈值；新研究真实通过所需门禁 |

具体原因以报告输出为准。账户或模型证据缺失是准入边界，不是要求初次体验者提交密钥。
预测校准所需协议见 [历史与预测规格](../product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md)。

## 6. 可选：手动采集与可复现工件

原有 CLI 与 HTTP API 保持兼容。需要明确保存输入、固定时钟或持续积累样本时，在仓库根目录
使用以下流程；它不属于首次打开平台的前置条件。需要网络，无需账户或 API 密钥，输出只写本地：

```powershell
python -m crypto_options_report.underlying_history_tool --currency BTC --days 1200 `
  --resolution 1D --output artifacts/history/btc-daily.json

crypto-options-report pull-snapshot --currency BTC `
  --output artifacts/snapshots/btc-chain.json --compact

crypto-options-report report `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/latest.json --quiet --fail-on-blocked

crypto-options-report analysis `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/analysis.json --compact
```

先采集较慢的历史，再采集短时有效的行情。快照摘要的质量结果不是信任提升证据。
`report --fail-on-blocked` 退出码 `10` 指市场质量阻断；退出 `0` 仍须检查信任、准入和简报。
`analysis` 保存构建身份、输入摘要、证据来源与实际条件。两条命令默认各用运行时钟；
严格比较时传同一个带时区的 `--generated-at`。

查看这些输入可直接运行 `start --snapshot … --underlying-history …`。已有 API 命令也可继续使用：

```powershell
python -m crypto_options_report.api --host 127.0.0.1 --port 8000 `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json
```

这个文件模式只重读配置文件；要更新市场必须先更新输入。加 `--replay` 才按采集时刻回放。
持续研究可用 `pull-snapshot --output-dir artifacts/snapshots/btc-series`，或现有
`python -m crypto_options_report.snapshot_sidecar --output <path>`；后者支持 `--once` 单次刷新
与 `--interval` 周期刷新。完整的历史、信号与序列维护见 [操作者指南](operator-guide.md)。
不要将原始行情、运行日志或私有证据加入公开提交。

无需网络的固定复核案例见 [离线研究案例](reproducible-case.md)：

```powershell
python tools/reproduce_research.py --check
```

复现成功说明同一构建、输入和时钟得到相同输出，不证明策略有效、可执行或能够盈利。
