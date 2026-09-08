# 离线复核一次研究结果

[项目首页](../../README.md) · [贡献指南](../../CONTRIBUTING.md)

这个案例回答“同一构建、同一输入和同一评估时间，是否得到相同研究结果”。它使用已安装包中的
两个固定资源，通过公开 `build_analysis_record` 入口运行；不导入测试 fixture，不访问网络，
不读取账户凭证，不写 ledger、信任状态或模型提升记录。

它与浏览器中的虚构教学收益示例分开。这里重放的是包内脱敏研究快照，保留实际的证据不足和阻断。

## 两步复核

先在仓库根目录安装当前包：`python -m pip install .`。随后运行：

```powershell
# 固定输入和时钟连续计算两次；完整结果不同则非零退出
python tools/reproduce_research.py --check

# 显式保存独立案例文件，再从当前安装包重算并比较
python tools/reproduce_research.py --output research-case.json
python tools/reproduce_research.py --verify research-case.json
```

只有 `--output` 写用户指定的案例文件。默认和 `--check` 只输出摘要，`--verify` 不修改旧结果。
案例是复核记录，不是可导入研究引擎的可信工件。生成和比较成功退出 `0`；不一致、非法时钟、
输入读取或合同校验失败退出非零。`--help` 给出全部选项。

## 固定的是什么

| 输入 | 内容 |
| --- | --- |
| `resources/demo-snapshot.json` | 包内 BTC 期权快照，采集于 `2026-07-07T00:01:00Z` |
| `resources/demo-underlying-history.json` | 包内 40 条标的历史观测；不等于 40 个独立策略 cohort |
| 评估时钟 | 默认显式固定为 `2026-07-07T00:01:30Z`，不是机器的当前时间 |
| 代码与规则 | 当前安装包的公共分析入口、policy/model 引用及 manifest 构建身份 |

`inputs.*.sha256` 绑定实际读入的资源。`manifest` 保留分析引擎报告的构建、时钟、规则与证据身份；
`analysis_output_hash` 是引擎输出摘要，`case_sha256` 绑定整份案例。文档不硬编码当前提交或输出摘要。
换构建、改资源、改时钟或改规则后，旧案例可能不再匹配；应解释差异，不把新的摘要写回以冒充复现。

需要观察时间变化时显式指定另一时钟：

```powershell
python tools/reproduce_research.py --generated-at 2026-07-08T00:01:30Z --check
```

这会重算那一时刻的证据状态，不把快照改成新鲜数据。验证以另一时钟保存的案例时也须传相同的
`--generated-at`。

## 如何读结果

包内案例当前保留以下结果；实际值始终以命令输出为准：

| 字段 | 包内案例结果 | 含义 |
| --- | --- | --- |
| `trust_verdict` | `untrusted` | 固定资源不具备认证后的市场信任证据 |
| `decisions[].status` | `BLOCKED_BY_EVIDENCE` | 准入停在证据层 |
| `reason_codes` | `DATA_TRUST_PROMOTION_PENDING`、`MARKET_EVIDENCE_NOT_TRUSTED` | 原因来自分析记录，脚本没有替换或放宽它们 |
| `strategy_brief.action` | `NO_TRADE` | 没有通过门禁的策略卡 |
| `execution_allowed` | `false` | 研究结果始终不能用于自动执行 |
| `missing_evidence` | 账户、历史、入场前风险证据及已提升模型的缺口 | 根据当前 manifest 的缺失字段列出，不是要求首次用户补齐的账户配置清单 |

`decisions[].conditions` 保留每个实际门禁的 observed、requirement、status 和 reason code。
`evidence_lineage` 保留证据来源、评估时间、认证状态和摘要；更早的阻断可能使后续策略门禁根本未执行。

重复计算成功只证明这个构建下的确定性。它不认证行情，不证明历史表现，不校准预测，更不授权交易。
缺少认证或足够样本时，正确结果仍是阻断；重复运行不会逐次积累信任或提升模型。

## 复核一个安装后的 wheel

工具脚本属于源码仓库，输入属于安装包。可使用独立虚拟环境的 Python 从干净目录运行工具，
确认没有依赖仓库测试目录；不需要复制 `tests/`：

```powershell
C:\path\to\wheel-venv\Scripts\python.exe -I C:\path\to\Option\tools\reproduce_research.py --check
```

请先把所需 wheel 安装进该虚拟环境。使用同一虚拟环境生成和校验案例；如果改用另一构建，身份差异
本身就是应检查的结果。

## English summary

Run `python tools/reproduce_research.py --check` to evaluate the packaged resources
twice with a fixed explicit clock. Only `--output PATH` writes a standalone case;
`--verify PATH` reproduces it without updating the saved file. Matching replay is
not a promotion: the packaged case remains untrusted, blocked by evidence, and
`NO_TRADE`, with execution disabled. Compare within the same build and clock;
inspect the manifest when they change.
