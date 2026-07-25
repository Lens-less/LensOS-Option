# 本地 Chrome 研究伴侣验收契约

## 交付边界

本轮交付是面向单一研究者的本地 A 形态：

- Python 引擎继续是唯一研究结论来源；
- Chrome Manifest V3 Side Panel 只读本机 loopback API；
- 最低支持 Chrome 114（`chrome.sidePanel` 的首个稳定版本）；
- 扩展以 `Load unpacked` 方式安装，不上架、不托管、不登录；
- content script 只识别当前 Deribit 页面上下文，不读取完整报告，也不发网络请求；
- service worker 按标签页隔离 Deribit 上下文，并只向面板发送经过二次校验的
  紧凑报告投影；
- 不提供下单、交易、合约张数、仓位 sizing 或执行控制。

Chrome Web Store、托管引擎、远程认证、多人分发以及非个人场景下的
Deribit 数据许可，均明确属于后续 B 形态，而不是本轮验收阻塞项。

## 不可退让的可信边界

1. Side Panel 和完整 Evidence Console 必须使用同一个
   `research_report.v1` 运行时校验器。
2. `execution_allowed` 必须保持 `false`，发布状态必须保持 fail-closed；
   前端不得把缺失字段或未知状态解释为允许执行。
3. 报告来源、市场证据年龄、信任状态、完整合约标识以及 `READ-ONLY`
   边界在常用 Side Panel 宽度下始终可见。
4. 缓存报告保留实际 HTTP 接收时间；重新打开面板不得把旧缓存伪装成新报告。
5. 当前 Deribit 合约未被报告覆盖时，必须显示“不匹配”，不得把全局 BTC
   结论冒充为该合约研究。
6. 引擎地址只接受 `http://127.0.0.1:<port>` 或
   `http://localhost:<port>`；消息接口不得成为任意 URL 或 HTTP 方法代理。

## 功能验收

### 三秒阅读顺序

Side Panel 从上到下回答：

1. 当前 Deribit 合约是什么，以及报告是否覆盖；
2. 来源、证据年龄和可信状态；
3. 当前 stance、结构、完整双腿和为什么现在/为什么不；
4. 全部进场硬条件；
5. 最大风险模板、止盈、时间退出与 kill switches；
6. 监控、退出状态和复盘要求；
7. 如何打开完整本地 Evidence Console。

### 必须覆盖的状态

- 首次加载；
- 本地引擎离线；
- 非法或不安全报告；
- 当前报告、临近过期和已过期；
- 当前合约匹配与不匹配；
- Deribit DOM/URL 无法识别时的手动合约回退；
- service worker 被回收后从 `chrome.storage.session` 恢复；
- 显式强制刷新；
- loopback 引擎地址保存成功与非法地址拒绝。

## 构建与回归门禁

自动化验收至少包括：

```text
web: typecheck + lint + unit tests + Evidence Console build
extension: manifest/message/origin/cache/context/view-model tests + MV3 build
python: full pytest + compileall
package: wheel 安装后 smoke
container: Evidence Console 主入口与 legacy URL 兼容 smoke
repository: committed Evidence bundle 与源码一致，git diff --check
```

最终人工验收必须在 320–600px 面板宽度和桌面 Evidence Console 各做两轮
“渲染 → 批评 → 修正”，重点检查信息层级、中文断行、长合约名、来源/年龄可见性、
错误恢复动作和研究只读边界。
