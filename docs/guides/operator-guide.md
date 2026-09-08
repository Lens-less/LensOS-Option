# 操作者指南

[项目首页](../../README.md) · [文档地图](../README.md) · [English](operator-guide.en.md)

以下命令均从仓库根目录运行，并已安装项目包。运维步骤依赖运行手册中明确的服务配置，不是离线演示的前置条件。

## 操作者车道（Windows-only，可选）

本节及后文的日采集、计划任务与静态发布只用于维护一个持续运行的公开实例，依赖
PowerShell、可选的私有证据仓和外部托管。它们不是快速开始或贡献代码的前置条件。

### 静态公开版与发布

公开站不运行会访问 Deribit 或持有凭证的服务。日更任务先用
[`tools/capture-daily.ps1`](../../tools/capture-daily.ps1) 固化市场快照、标的历史、DVOL 历史与研究产物，
再把经过白名单裁剪的报告和前端一起发布成纯静态目录：

```powershell
$siteOrigin = $env:LENSOS_PUBLIC_SITE_ORIGIN
if ([string]::IsNullOrWhiteSpace($siteOrigin)) {
  throw '请先把 LENSOS_PUBLIC_SITE_ORIGIN 设为最终自有 HTTPS 域名。'
}

crypto-options-report publish `
  --snapshot artifacts/snapshots/btc-series/<capture>.json `
  --underlying-history artifacts/history/btc-daily.json `
  --dvol-history artifacts/history/btc-dvol.json `
  --signal-artifact artifacts/reports/signal-preflight.json `
  --series-artifact artifacts/reports/series-history.json `
  --publication-history artifacts/reports/publication-history.json `
  --web-build web/dist-public `
  --site-origin $siteOrigin `
  --out dist/site --published-at <UTC-RFC3339> --git-sha <commit>
```

`--site-origin` 必须是最终自有的 HTTPS 纯域名（不能带路径、查询、凭证或非默认端口）；
它会进入 canonical 分享元数据、`robots.txt` 与 `sitemap.xml`。发布器会拒绝
`example.*`、`.invalid`、`.alt`、localhost、单标签域名和 IP 字面量；正式工作流还会拒绝
解析到 IANA 特殊用途/非公网地址的主机。未确定正式域名时只构建并测试 `web/dist-public`，
不要生成带虚假 canonical 的发布树。

输出目录按 Cloudflare Pages 的 `_headers` 契约构建。质量门禁失败、VRP 历史不足或含账户/仓位/订单字段时
发布器会失败关闭；浏览器按版次携带的 `stale_after` 判断时效，截止时间到期后进入“发布已停摆”态。
完整接口与运维约定见
[公开 API](../api-public.md) 和[静态发布手册](../operations/public-publishing.md)。

公开 bundle 只包含公开观测站所需的静态页面与 JSON，不包含 workbench 或 Chrome companion。

`research_publication` 只回答“这份静态研究能否公开”；`execution_authorization` 只回答
“系统能否用于交易执行”。两者互不提升，后者永久保持 `NO-GO`。

#### 操作者采集与计划任务（Windows-only）

下面的日采集与 Windows 计划任务是可选的运营车道，不属于陌生人快速开始。每天抓一次，
文件按采集时间命名，不会互相覆盖：

```powershell
crypto-options-report pull-snapshot --currency BTC `
  --output-dir artifacts/snapshots/btc-series --compact
```

`tools/capture-daily.ps1` 把这一步和标的历史刷新打包成一次采集，**历史必须一起刷新**：
它为已到期合约提供 `daily_close_proxy` 日收盘结算代理，不能复现交易所结算窗口均价；
历史过期会使最近到期的 cohort 缺少代理价格。注册为
每日计划任务（本地 17:00，即 Deribit 08:00 UTC 结算之后）：

```powershell
$repo = "C:\path\to\Option"
$evidenceRepo = "C:\path\to\LensOS-Option-Evidence"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$repo\tools\capture-daily.ps1`" -RepoRoot `"$repo`" -CaptureOrigin local_windows_scheduler -EnableEvidenceRepoSync -EvidenceRepoRoot `"$evidenceRepo`" -EvidenceRepoRemote origin -HistoryDays 1200 -DvolHistoryDays 1095" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At 17:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 45) `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName "LensOS-Option-DailyCapture" `
  -Action $action -Trigger $trigger -Settings $settings -Force
```

失败通知和成功 dead-man ping 分别从 `CAPTURE_DAILY_FAILURE_WEBHOOK_URL` 与
`CAPTURE_DAILY_SUCCESS_HEARTBEAT_URL` 读取。不要把 webhook URL 直接写进可被其他本机用户
读取的计划任务参数；应通过运行该任务的专用账户注入。外部监控还必须独立拉取公开
`health.json` 并比较 `stale_after`，成功 ping 不能替代这条正向检查。

摘要与两个通知 payload 都会写入 `usable_for_validation`、可用性 reason codes，以及连续
可用/不可用天数。即使脚本退出成功，只要连续两个采集日没有推进验证序列，也会触发失败
webhook；快照阶段失败时，互不依赖的标的历史和 DVOL 历史仍会继续刷新。

第二采集点已选定为 GitHub Actions 的 `08:10 UTC` 车道，标识为
`github_actions_0810_utc`。配置私有 evidence repo 与两个通知端点后，用不可变 receipt
验收连续三天的双车道数据。`$evidenceRepo` 必须指向干净、已把当前命名分支完整推送到
`origin` 的私有 Git 仓顶层；工具会核对远端 commit 中的 receipt 与 snapshot blob。
退出码 `0/10/11` 分别表示通过/继续收集/证据无效：

```powershell
python tools/check-dual-capture-acceptance.py `
  --evidence-root $evidenceRepo `
  --required-origin local_windows_scheduler `
  --required-origin github_actions_0810_utc `
  --days 3
```

采集日志在 `artifacts/logs/capture-daily.log`。同一天跑多次是安全的：验证器按
“日期 × 合约”去重并报告丢弃了多少条，不会让重复行把当日横截面的相关性拉紧。

**样本量按实际合格、已到期的 cohort 计算，不按运行次数或日历天数承诺完成时间。**
期限分布、缺采集、坏报价和历史价格缺口都会影响积累速度。纵向 series/preflight
隔离失败的到期日，健康到期日仍可进入对应 cohort；全链报告与公开发布保留整份快照门禁。
不要降低报价质量或独立样本阈值来加速通过。

等待期间用 preflight 监控采集是否真的在产出观测——**采集不可回补，一个缺陷不被发现多久
就浪费多久**：

```powershell
crypto-options-report validate-signal --preflight `
  --snapshot-dir artifacts/snapshots/btc-series `
  --underlying-history-fixture artifacts/history/btc-daily.json `
  --output artifacts/reports/signal-preflight.json --compact
```

它按到期日列出已结算 / 待结算的 cohort、每个能贡献多少观测、以及被什么挡住了。

把产物交给引擎，就能在界面的“信号验证”页里读，不必反复跑命令看 JSON：

```powershell
python -m crypto_options_report.api --replay `
  --snapshot-fixture <快照> --underlying-history-fixture artifacts/history/btc-daily.json `
  --signal-artifact artifacts/reports/signal-preflight.json
```

攒够之后：

```powershell
crypto-options-report validate-signal `
  --snapshot-dir artifacts/snapshots/btc-series `
  --underlying-history-fixture artifacts/history/btc-daily.json --compact
```

样本不足时它会 `blocked` 并写明差多少——**这是正常的，不是故障**。

它一次度量 10 个候选信号（微笑残差的三种量纲、IV 减历史波动率、IV 减 DVOL、期限溢价、
局部偏斜、持仓量占比、深度失衡、报价宽度），并附一份**共线性报告**：数信号不等于数信息。
任何形如“IV 减去一个当日常数”的信号在当日内秩完全相同——拿 DVOL 减和拿历史波动率减
是同一个排序穿了两件衣服。`distinct_signal_estimate` 给出实际有几个不同的排序。

## 生产部署

推荐把公共行情、私有只读账户和 Web API 拆成三个进程：凭证只存在于 sidecar 进程，
API 进程只读取脱敏后的 JSON。生产 HTTP 禁止浏览器指定 fixture、账户场景、评估时间
或实时抓取。

服务默认只监听 loopback，必须部署在认证 / TLS 反向代理之后，不能直接暴露到公网。

完整的容器、健康检查、HMAC 密钥管理、密钥轮换、回滚与验证步骤见
**[生产运行手册](../operations/production-runbook.md)**；环境变量清单见
[`.env.example`](../../.env.example)。
