<!-- 请不要在 PR 中包含凭证、账户数据或私有行情快照。 -->
<!-- English contributions are welcome; every section may be completed in English. -->

## 变更内容

<!-- 这个 PR 做了什么，为什么需要它。 -->

## 关联 issue

<!-- 例：Closes #123 -->

## 验证

请勾选实际运行过的检查（未运行的请留空，不要预先勾选）：

- [ ] `python tools/verify.py` 完整检查（含安装后 wheel 的浏览器流程）
- [ ] 若仅运行 `python tools/verify.py --quick`，已明确说明跳过构建、产物与浏览器检查
- [ ] 修改了 `web/` 且已提交重新构建的 `crypto_options_report/static/evidence/`
- [ ] 产品入口、合同或模块边界有变更时，已同步 README / DESIGN / 架构文档

<!-- 粘贴关键输出；UI 变更附桌面/窄屏证据，说明失败恢复和过期状态验证。未运行的检查请写明。 -->

## 安全边界确认

本项目刻意不提供实盘下单能力，可信输出上限是 `execution_allowed=false` 的
`EntryAdmissionDecision`。详见 [SECURITY.md](../SECURITY.md)。

- [ ] 本 PR **没有**引入下单路径、订单模板、手数/仓位 sizing 输出或 paper/manual 下单控件
- [ ] 本 PR **没有**放宽任何 fail-closed 门禁；若确有放宽，已在下方说明理由与新增证据
- [ ] 教学示例未进入研究 JSON，也未被标为 VALIDATED / CALIBRATED

<!-- 如果本 PR 改变了任何门禁或准入语义，请在此详细说明。 -->
