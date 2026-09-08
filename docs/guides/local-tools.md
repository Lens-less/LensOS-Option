# CLI、API 与本地扩展

[项目首页](../../README.md) · [文档地图](../README.md) · [English](local-tools.en.md)

以下命令均从仓库根目录运行，并已安装项目包。运维步骤依赖运行手册中明确的服务配置，不是离线演示的前置条件。
第一次使用请先跟随 [完整决策研究流程](decision-workflow.md)，其中连接了采集、浏览器启动与阻断恢复。

### CLI（内部管道）

```powershell
# 抓取一份实时公开快照，供离线分析
python -m crypto_options_report.cli pull-snapshot `
  --output artifacts/snapshots/btc-chain.json --compact

# 基于快照产出报告；市场数据被阻断时退出码为 10
python -m crypto_options_report.cli report `
  --snapshot-fixture artifacts/snapshots/btc-chain.json `
  --output artifacts/reports/latest.json --fail-on-blocked --compact

# 研究性风险告警（不含任何下单路径）
python -m crypto_options_report.cli alert-eval `
  --snapshot-fixture artifacts/snapshots/btc-chain.json --dry-run --fail-on-alert --compact
```

调度器退出码：`0` 命令成功 · `1` 硬错误 · `2` 参数错误。`report/alert-eval --fail-on-blocked`
在市场质量阻断时返回 `10`；`alert-eval --fail-on-alert` 在触发告警时返回 `11`。
`analysis` 没有 `--fail-on-blocked`，要读取准入决策；退出 `0` 不表示证据、策略或执行获准。
完整选项见对应子命令的 `--help`。

`--snapshot-fixture` 不冻结评估时间。当前研究要使用新采集的输入；历史复核需显式传
`--generated-at <snapshot-captured-at-with-timezone>`，或对 API 使用 `--replay`。
历史时钟只用于复核当时计算，不恢复当前资格。采样预算省略时使用当前采集器默认值；
主动缩小 `--instrument-limit` 可能减少可比较的期限与有效报价。

### HTTP API 与 Evidence Console

Evidence Console 与 API **固定同源**，避免跨源配置和浏览器参数改变生产报告语义。
同一输入版本在有效期内，各 GET 投影共享一个 `AnalysisRecord`；输入文件更新、证据或
信任窗口到期会重建记录。网页刷新只重新读取报告，底层文件仍旧时继续阻断，不会自动采集行情。

主要端点：`/evidence`（控制台）· `/strategy/brief` · `/research/report` · `/analysis/result` ·
`/health` · `/livez` · `/readyz`。完整列表、鉴权要求与响应契约见
[API 参考](../api-reference.md)。

`/research/signal` 与 `/research/series` 只接收带 `research_only=true`、允许 schema 和合法时间的
研究工件；任意深度的执行/下单/推荐手数字段均被拒绝。旧手工工件缺字段时用当前 CLI 重新生成；
measured、preflight、blocked、demo 产物及 `excluded_snapshots` 排除证据仍保留，详见
[v0.5.0 工件升级](../releases/v0.5.0.md#信号与序列工件升级)。

### Chrome 研究伴侣（个人本地）

面向个人本地使用的 Manifest V3 侧边栏（Chrome 114+）。从
[GitHub Releases](https://github.com/Lens-less/LensOS-Option/releases)
下载与引擎版本一致的 Chrome 扩展 ZIP，核对 `SHA256SUMS` 并解压；先运行
`crypto-options-report demo`，再在 `chrome://extensions` 打开“开发者模式”→
“加载已解压的扩展程序”→选择解压后的目录。

从源码构建时：

```powershell
cd web
npm ci
npm run build:extension
```

选择 `web/dist/chrome-extension/`，然后在 Deribit 页面点击工具栏图标。

侧边栏只读取 `http://127.0.0.1:<port>/research/report`，只识别当前 Deribit 合约并
展示研究上下文；**不包含订单、交易、张数或 sizing 控件**。合约上下文按标签页隔离。
连接失败时展开可见的连接设置，确认与本地服务一致的端口后重试；数据有效性仍由报告门禁决定。
