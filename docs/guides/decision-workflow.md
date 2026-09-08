# 完成一次期权决策研究

[项目首页](../../README.md) · [English](decision-workflow.en.md) · [研究方法](research-workflows.md)

本指南把“看懂平台”到“保存可复核结论”连起来。当前主要研究 BTC 期权，使用 Deribit
公开行情；平台提供市场解释、有限风险结构与证据门禁。每次研究的有效结果包括“证据不足，
暂不形成策略”。`research_only=true`、`execution_allowed=false` 在任何结果下都成立。

## 1. 先走完离线导览

按 [快速开始](../../README.md#快速开始) 安装后运行 `crypto-options-report demo`，打开命令输出的
`/index.html?view=demo`。依次选择结构、拖动到期价格、核对最大收益与亏损，再进入研究依据。
教学价格是虚构点数，线性到期收益不包含真实成交、费用或到期前波动。

点击“查看真实快照”，观察包内脱敏快照的评估时刻、证据状态和阻断原因。此处没有可靠策略卡
是预期结果。需要核对机器输出时，在源码根目录运行：

```powershell
python tools/reproduce_research.py --check
```

固定案例比较的是同一构建、输入和时钟的完整输出。具体字段与保存方法见
[离线复核案例](reproducible-case.md)。

## 2. 采集自己的公开市场输入

以下步骤需要网络，但无需 Deribit 账户或 API 密钥。在仓库根目录运行；输出仅写本地
`artifacts/`。不要将行情原始文件、运行日志或后续账户数据加入公开提交。

```powershell
python -m crypto_options_report.underlying_history_tool --currency BTC --days 1200 `
  --resolution 1D --output artifacts/history/btc-daily.json

crypto-options-report pull-snapshot --currency BTC `
  --output artifacts/snapshots/btc-chain.json --compact
```

先刷新较慢的历史，再采集短时有效的行情。快照摘要包含 `quality_gate_passed`、`quality_reason_codes`、
`validation_eligible_expiry_count` 和输出路径。保存成功不代表整条期权链通过质量门禁，
更不代表数据已经完成可信提升。历史工具只采集标的指数历史；它不生成历史期权链或已验证策略。

网络失败或采样不足时保留原因，待来源恢复后重新采集。持续研究使用
`pull-snapshot --output-dir artifacts/snapshots/btc-series` 追加快照，再按
[操作者指南](operator-guide.md) 同步维护历史、信号与序列产物。

## 3. 生成报告，并在浏览器复核

```powershell
crypto-options-report report `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/latest.json --quiet --fail-on-blocked

crypto-options-report analysis `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/analysis.json --compact
```

`report --fail-on-blocked` 的退出码 `10` 指市场质量阻断；退出 `0` 只表示命令及该检查成功，
仍须读取 `data_trust`、准入决策和 `strategy_brief`。`analysis` 保存不可变分析记录，
其中包括构建身份、输入摘要、证据来源与实际执行的条件。两条命令默认各用运行时钟，
因此其 ID 不必相同；需要严格对比时，为两者传同一个带时区的 `--generated-at`。

在单独终端启动只读本地服务；若 demo 占用 8000，先 `Ctrl+C` 停止它，或为下列命令改用 8001：

```powershell
python -m crypto_options_report.api --host 127.0.0.1 --port 8000 `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --underlying-history-fixture artifacts/history/btc-daily.json
```

打开 [研究简报](http://127.0.0.1:8000/evidence)。先看数据时间与总结果，再看候选和证据。
服务读取配置的文件；网页刷新不会替你重新采集市场数据。重复研究时先更新本地输入，再刷新报告。

要复核旧快照在采集时刻的计算，为服务加 `--replay`。页面仍按读者当前时间显示数据年龄；
回放计算通过不恢复当前研究资格。不要为了消除过期提示修改快照时间或冒充当前行情。

## 4. 按证据顺序读结论

| 顺序 | 看什么 | 如何解释 |
| --- | --- | --- |
| 来源与时效 | 来源、采集时间、评估时间、过期提示 | 历史计算与当前可用性分别判断 |
| 数据质量与信任 | `data_status`、`data_trust`、原因码 | 字段完整和质量通过不等于来源已认证 |
| 市场与候选 | 相对价值、成本后 EV、风险、排名依据 | 排名表示比较顺序，不能换算成胜率 |
| 策略简报 | `strategy_brief.action`、精确腿、到期日、分项成本、损失口径和取消条件 | 无合格策略时保持 `NO_TRADE`；卡片最高为 `WATCH` |
| 历史与预测 | 各自状态、样本范围、协议和精确选腿身份 | 历史到 `VALIDATED` 才显示胜率，预测到 `CALIBRATED` 才显示区间 |
| 复核记录 | manifest、条件、证据来源与摘要 | 支持解释和重复计算，不构成执行授权 |

策略卡的 `entry.cost_breakdown` 明列入场费、滑点预算、分腿风险预算与交割费预算，单位与
`entry.currency` 一致。最低净权利金扣除前三项；损失预算还计入交割费预算。
`risk.max_loss_basis=PAYOFF_BOUND_PLUS_FROZEN_COST_BUDGET` 表示“到期 payoff 边界加冻结成本预算”，
`delivery_fee_upper_bound_verified=false` 明确实际交割费上界未验证。**模型损失预算不是实际含费
损失的绝对上限**。数字成本缺失时不生成卡片；只勾选“已含费”或补零不能证明费用已覆盖。

历史精确结构回放的净 PnL 扣除按其费用规则计算的交割费，但风险分母使用 payoff 损失加入场费，
以 `delivery_fee_in_risk_denominator=false` 明示不含交割费。因此净 `R` 可以小于 `-1`；
这不是应裁剪或隐藏的结果。各历史产物的结算口径还需单独查看，信号验证使用日收盘结算代理。

## 5. 遇到阻断时恢复

| 看到的状态 | 下一步 | 恢复成功的证据 |
| --- | --- | --- |
| 连接失败、超时或 HTTP 错误 | 确认本地服务、端口和文件路径；服务恢复后点“重新读取” | 得到新的、合同校验通过的报告 |
| 响应不是 JSON 或合同不合法 | 检查服务版本与响应；修复输入/服务后重试 | 无错误提示且有效报告重新显示；旧结果不会作为兜底 |
| 数据过期 / 发布已停摆 | 本地重新采集输入；公开实例由操作者重新生成并发布合格版次 | 新输入或新版本的截止时间可验证，页面重新评估时效 |
| `DATA_TRUST_PROMOTION_PENDING` 等信任阻断 | 按运行手册积累可认证的观测与来源证据 | 实际可信门槛通过；重复刷新和改 JSON 都不能替代 |
| 历史样本不足、信号产物未提供 | 持续采集并保留到期 cohort，生成且配置对应产物 | 页面明确区分未配置、采集中和统计结论 |
| 历史或预测证据过期、身份不匹配 | 检查协议、选腿、有效期和证据来源；按模型协议重新评估 | 当前策略对应的有效证据通过自身门禁 |
| 没有可靠策略 | 读完整拒绝原因，保存本次观察；等输入或证据变化再评估 | 新研究真实通过所需门禁；不以降低阈值制造卡片 |

具体原因以报告输出为准。账户或模型证据缺失是准入边界，不是要求初次体验者提交密钥的配置清单。
预测校准不能靠重跑离线案例获得，所需协议见 [历史与预测规格](../product/2026-08-30-actionable-strategy-brief-v0.2-v0.4-spec.md)。

## 6. 留下能被复核的研究记录

保留原始快照、历史输入、UTC 评估时钟、构建版本和分析 JSON；记录观察结论、阻断原因以及
下一次需要新增的证据。研究记录保存在本地或自有私有证据仓。向公开 issue 报告缺陷时提供
最小脱敏 fixture、复现命令和预期/实际结果，不附账户资料、凭证或整份运行目录。

完成这一流程意味着输入、结论和限制可复核；并不要求每次产生策略卡，也不证明策略能够盈利。
