# Claude Fable 评审整改报告

更新时间：2026-07-14
评审固定点：`f53aae1c6e0c6501c06150789790590cc7570056`
固定点历史基线：`344 passed, 1 skipped, 160 subtests passed`
当前验证状态：**本地代码、合同、CLI/API、安装包与第四冻结复核均已通过；Docker 运行时验证因本机无 Docker CLI 保持 pending**

## 整改总判定

原评审指出的金融单位、证据来源、Windows 运行时和传输安全问题中，
存在多项可复现的真实缺陷。本轮整改将这些意见落实为公共边界上的可测试
约束，没有把它们仅作为代码风格建议处理。

整改后的产品边界保持收紧：

- 确定性、fail-closed 的研究核心在最终验证台账全绿后可判定为
  **conditional GO**；
- 生产发布、校准排名、缺少显式观测的仓位经济学、paper/manual 工作流和
  任何执行能力均为 **NO-GO**；
- `RESEARCH_ONLY`、`NO_TRADE`、`NO-GO` 必须继续对外可见；
- 仓库中不存在 live-order adapter 或 order-submission transport；
- 唯一外部发布状态为
  `external_release_authorization: awaiting_external`，运行时输入不能将其改为
  通过。

本报告不是生产授权。历史测试数字、handoff、fixture、tracer 输出以及绿色
`/livez` 都不能替代最终验证台账或外部运营证据。

## 最终验证台账

| 验证项 | 结果 | 证据边界 |
| --- | --- | --- |
| Fable 聚焦回归套件 | **PASS — 184 passed, 394 subtests passed in 26.24s** | 明确列出的 numeric、evidence-honesty、runtime-integrity、transport-security、historical/path-risk、sidecar-auth、account provenance 和 async-job 回归模块 |
| 全仓：`python -m pytest -q` | **PASS — 486 passed, 1 skipped, 586 subtests passed in 75.96s** | 第四冻结数值补强后的干净运行；零失败，skip 为既有可选环境边界，不被计作通过证据 |
| `python -m unittest discover -s tests -p 'test_*.py'` | **PASS — Ran 487 tests in 70.441s; OK (skipped=1)** | 第二测试发现入口独立通过 |
| `python -m compileall -q crypto_options_report tools tests` | **PASS — exit 0** | Python 语法与导入编译 |
| `python -m crypto_options_report.api --smoke` | **PASS — exit 0；输出通过 report contract 且保持 HALT/NO-GO** | 仅证明本地 API smoke，不证明生产 readiness |
| wheel 构建、安装与 console entry smoke | **PASS — wheel SHA-256 `7e96747520c9e9b245058d10477bcb884b1702b677e73b9ff260fb5038f8a649`；isolated venv `pip check`、4 个 entrypoint `--help`、installed API smoke 全通过** | 从非源码 cwd 证明 import 来自 venv `site-packages` |
| 容器构建与 secure-default/liveness/readiness 探针 | **verification pending** | 本机 Docker CLI 不可用（`Get-Command docker` 未找到命令），不得声称本地容器 PASS |
| CI workflow YAML/静态安全结构 | **PASS — YAML parse exit 0；相关回归测试通过** | 只证明配置可解析及 secure-default 断言，不替代容器运行 |
| `git diff --check` + immutable evidence fence | **PASS — exit 0；两个受保护 evidence 路径零差异** | 补丁、空白及不可变审计边界完整性 |
| Standards + Spec + trust-boundary 冻结复核 | **PASS — 最终只读复核未发现剩余 P0–P2；第四冻结发现的 2 个 P2 已 test-first 修复并独立复验** | 两条独立审查通道重放原始及追加反例；极端相似度输出 ESS=0、触发 conservative hierarchical pooling，所有路径数值字符串均被拒绝 |

Docker 项必须保持 pending，直到在 Docker-capable 主机或 CI 上实际执行。
Dockerfile/workflow 静态测试可以防回归，但不能证明镜像可构建或容器探针通过。

## A. 正确性问题 A1-A12

下表中的测试名称是验收闸门；其结果已由上方零失败聚焦套件与全仓套件覆盖。

| 项 | 核验结论 | 整改 | 回归证据 | 仍阻塞 / 拒绝理由 |
| --- | --- | --- | --- | --- |
| A1 | **确认属实。** 配置的无套利容忍度没有成为实际判定边界。 | butterfly/convexity error 使用配置容忍度；重复、非单调及非法 strike 仍是硬失败。 | `tests/test_review_numeric_remediation.py::test_surface_accepts_nonzero_no_arb_error_within_configured_tolerance` 及既有 surface fail-closed 测试。 | 无产品范围阻塞；最终套件仍是验收闸门。 |
| A2 | **确认属实。** fraction 与 percent-point IV 经过不一致启发式进入拟合和 Greeks。 | 边界必须提供显式 IV 单位；surface 统一为 percent-points，历史/rolling 统一为 fraction，并保留 provenance；缺失、未知或冲突单位 fail closed。 | `test_surface_canonicalizes_declared_iv_units_before_fit_and_greeks`、历史/rolling/DVOL 显式单位及缺失/冲突/未知单位用例。 | 单位未知的生产数据继续 blocked，这是预期行为。 |
| A3 | **确认属实。** 简单收益缩放可越过完全损失并产生非正价格。 | 改用 log-return 缩放；拒绝 bool、非有限值、`<= -1` 收益、非法波动率、溢出/下溢、零或非整数 horizon/block/path count、非法 NAV/spot/mixture；空历史、空 block、空 path 均结构化失败；所有模拟价格必须有限且为正。 | `tests/test_review_numeric_remediation.py` 与 `tests/test_path_risk_report.py` 的 total-loss、non-finite、domain、empty-bootstrap、scale、underflow、positive-path 用例。 | 没有授权的真实历史语料前，真实 path ranking 仍 unavailable。 |
| A4 | **确认属实。** inverse payoff 与容差跨币种/单位比较。 | 复用 inverse coin settlement 公式；容差以 payoff currency 表达；运算前拒绝 bool 和非有限 delivery/payoff。 | inverse good/bad、North Star 精度及 `test_historical_payoff_replay_rejects_boolean_and_non_finite_numbers`。 | 单位未知行不得进入 training/backtest eligible。 |
| A5 | **确认属实。** IV 水平被当作 percentile，形成伪量化 permission。 | 删除 IV-level fallback；只有绑定可信证据的显式 rank 或经验 rolling history 可以形成 permission；畸形 score 不得经 coercion/clamp 变成权限。 | `test_regime_with_partial_scores_and_no_percentiles_is_always_collecting`、`test_regime_ignores_handwritten_complete_inputs_without_bound_history`。 | 可信 rank/history 缺失时保持 collecting/blocked。 |
| A6 | **确认属实。** 缺失 freshness 可被解释为零年龄。 | 从 observed timestamp 重算年龄；缺失、过期、未来或畸形时间均成为 market/account 依赖输出的 kill condition。 | account sidecar age/freshness/missing-observed-at、market stale/future replay 及 EV kill-condition 用例。 | 生产数据必须持续提供可信时间戳。 |
| A7 | **确认属实。** timezone-naive 文本可能按宿主本地时区解释。 | market/account 时间戳只接受显式 offset 或 `Z`，naive 时间直接拒绝。 | `test_market_timestamps_require_an_explicit_timezone`、`test_naive_account_timestamp_is_not_assumed_to_be_utc`。 | 无；naive timestamp 按设计 fail closed。 |
| A8 | **确认属实。** 真实仓位与虚构 premium/hedge/roll/protective economics 混合。 | 不再从绝对 PnL 推断 collected premium；只有显式观测输入可产生数值，否则输出 unavailable。 | `tests/test_review_evidence_honesty.py::test_account_positions_do_not_receive_synthetic_management_numbers` 及 position replay 合同测试。 | ISSUE-012 保持 blocked；删除假数字不等于能力完成。 |
| A9 | **确认属实。** 畸形账户数值可逃逸为异常或不安全的部分状态。 | bool、非有限、畸形和不安全值归一为结构化 `malformed` + `NO_TRADE`；margin/simulation 必须完整且安全。 | `tests/test_review_runtime_integrity.py` 的 account integrity 用例及 account sidecar 非有限输入用例。 | 非 USD equity 未显式转换时不得标成 USD；不完整证据继续 blocked。 |
| A10 | **确认属实。** job-store `OSError`/Windows sharing violation 可中断 HTTP 而无结构化响应。 | corrupt/unavailable store 读写映射为可重试结构化 `503`，不得泄露私有路径或原始异常。 | `test_job_store_os_error_returns_structured_503`、corrupt record 和 corrupt content-addressed artifact 用例。 | retryable response 不允许静默丢弃失败写入。 |
| A11 | **确认属实，并发现二阶问题。** executor 失败可污染幂等 key；失败状态写盘异常还会留下没有 future 的 replayed ghost `queued` job；mapping 写失败还可能丢掉 changed-body 冲突证据。 | changed body 永远冲突；同 key/body 在 pre-admission 失败后可重试；orphan queued mapping 必须恢复或重新 admission；mapping 写失败后保留 request-hash tombstone，重启恢复时从 job record 重建，不得回放幽灵任务。 | executor/mapping failure、restart recovery、HTTP retry 及 ghost-job/tombstone 用例。 | North Star 明确要求 async 合同，因此“删除 job API”被拒绝。 |
| A12 | **部分属实并已加固。** `os.replace` 竞争真实存在，但原评审把 process liveness 与 dependency readiness 混为一谈。 | bounded Windows replace retry；`/livez` 只表示进程存活；`/readyz` 分别报告 market provider、authenticated last-trusted snapshot、authenticated account、store、queue、model 及 reason codes。 | `test_atomic_replace_retries_transient_windows_lock`、runtime/readiness dependency 用例和 CI 结构性 fail-closed 断言。 | model/外部证据不可用时 production readiness 保持 false；数据 stale 不等于进程死亡。 |

## B. 安全问题 B1-B4

| 项 | 核验结论 | 整改 | 回归证据 | 仍阻塞 / 拒绝理由 |
| --- | --- | --- | --- | --- |
| B1 | **确认属实。** 私有 credential/token 位于 URL query 时可进入代理和服务端日志。 | auth 参数放 JSON POST body；private token 只放 `Authorization: Bearer`；日志和错误结构化脱敏。 | `test_deribit_credentials_never_appear_in_request_urls` 及 account sidecar credential/redaction 用例。 | credential 和 private payload 必须继续置于仓库外。 |
| B2 | **确认属实。** 镜像默认暴露无认证 remote bind，且本地 API 若接受任意 `Host` 会留下浏览器 DNS-rebinding 面。 | image/API 默认 loopback；删除 baked-in remote permission；远程绑定必须显式 opt-in；只有字面 loopback IP 或严格 `localhost` 可走本地绑定路径，任意 DNS 名称不能靠解析结果自我认证；请求默认只接受 loopback `Host`，反代外部 authority 必须进入精确 allowlist，带 `Origin` 的 mutating request 必须与请求 authority 的 hostname 和显式 port 同时一致。 | Dockerfile/workflow 静态断言、任意 DNS bind、untrusted/allowlisted Host 与 cross-port Origin 回归。 | 本机 Docker 不可用，runtime container verification pending；生产暴露仍 NO-GO。 |
| B3 | **确认属实。** webhook 签名缺少 replay binding，redirect 可逃离已验证目的地。 | 签名 `timestamp.delivery_id.body`；发送 timestamp/delivery-ID header；拒绝 redirect 和 URL userinfo；dry-run 只返回 origin，不回显可能承载 credential 的 path/query/fragment。 | webhook signature、redirect、userinfo、redaction 用例。 | receiver 端 timestamp window 与 delivery-ID 去重仍是已文档化的 operator 责任。 |
| B4 | **确认属实。** snapshot 可以自我声明 trust。 | 忽略 snapshot 内嵌 trust；独立状态绑定规范化后的 snapshot payload content（而非空白与 key 顺序敏感的原始文件字节）；market/account 使用不同的 HMAC domain tag 与两个不同、严格 32-byte、regular-file 的 operator key；所有 payload/state 在验签前单句柄有界读取；双向拒绝 payload/key 同路径或相对路径 alias，并拒绝 public-digest forgery、跨域签名复用、tamper、post-load mutation、超限读取及 TOCTOU digest mismatch；只有 loader 附着的 authenticated state 可提升 readiness。 | `tests/test_sidecar_auth.py`、market/account domain separation、binding/TOCTOU、bounded I/O、authenticated account readiness 及 trust promotion/reset 用例。 | key/state 缺失或不可验证时保持 collecting/untrusted；HMAC verifier 必须持有对称 key，因此 API 进程被攻陷时仍可伪造本域签名。要获得 verifier 不能 mint 的边界，未来需引入 sidecar 私钥/API 公钥签名；当前 authentication 绝不等于 production authorization。 |

## 二次对抗审查追加闭环

首轮 A/B 项修复后又执行了独立的 fail-open、合同篡改与安装入口审查。该轮不是
把原评审机械翻译成补丁，而是验证整改自身是否引入新的自相矛盾。

| 追加项 | 可复现问题 | 整改与证据 |
| --- | --- | --- |
| R1 Portfolio arbiter | `NaN`/字符串/越界 permission、非 bool flag、未知 MDD/override 可异常或错误放行；`final_action` 可与最高严重信号分离后仍通过合同。 | permission 严格有限数值 `[0,1]`，flags 严格 bool；只有 `None` 表示 override 缺省，显式 clear/normal/online 必须使用已知状态，其他均 `halt_system`；`final_signal` 必须完整匹配最高严重信号，`final_action` 必须与其 severity 相等；halt 时不再计算 shadow size cap。 |
| R2 Account/JSON contract | `projected_margin.nav_usd=NaN` 可通过整份合同，CLI/API 还能输出非标准 JSON `NaN`。 | 所有 projected-margin 非空值必须为非 bool 的有限数值，available 状态不得为 null；CLI/API 序列化统一 `allow_nan=False`，API 将序列化错误映射为不泄露 payload 的结构化 `500 NON_JSON_RESPONSE_PAYLOAD`。 |
| R3 Calibration/paper forgery | unavailable calibration 可伪造 promoted artifact；unsupported paper 可伪造 external approval、999 proposals 与 reconciled/ready。 | validator 锁定 unavailable/not-implemented registry、空 artifact、唯一 blocker 与 release gate；paper 锁定 not-authorized/NO-GO、零 proposal、无 persistence、未审批且 reconciliation not-run/not-ready，整份合同篡改回归覆盖。 |
| R4 EV summary forgery | 空 ranking 可伪造 scanned/review count 和 top candidate，仍通过合同。 | summary counts、actions、kill-condition count 与 top fields 必须精确由 `ranked_candidates` 推导；unavailable 继续要求空 ranking 与 null top。 |
| R5 CLI feature regression | 诚实删除 `feature_standardization` 假证据后，`build-features`/`feature-status` 因旧字段强索引退出 `1`。 | 两个入口改为输出 `status=not_implemented`、`evidence_class=unavailable`、reason/policy 与空 features；源码与隔离 wheel 入口均 smoke 通过。 |
| R6 API authority/Origin | 任意 DNS 名可能借 loopback 解析绕过 remote opt-in；同 hostname 跨 port、不同 scheme，或把外部 `http` 写入 trusted env 可误通过。 | bind 仅接受字面 loopback/严格 localhost；Origin 精确匹配 scheme+hostname+显式 port：loopback 直连保留 `http`，非 loopback authority 即使被配置也只接受精确 `https` origin，且仍须与 `Host` authority 一致。 |
| R7 Job/idempotency integrity | 合法 JSON 但缺字段/多未知字段的 job、pointer 或 artifact 可自证 store ready；孤儿、跨记录不一致、生命周期倒序、无 start 的 timeout 或恢复前矛盾 active state 仍可能被当成可信记录。 | current job ID 从 key/request/fixture hash 重算，mapping、job、文件名和目标记录交叉一致；生命周期严格单调且 failure reason 与 start state 绑定，cancelled 不得伪造 started；恢复只转换先通过原状态校验的 queued/running job，损坏状态保持损坏并使 store fail closed；succeeded job 必须引用通过 content hash、exact schema 与 fixture provenance 校验的不可变 artifact；default pointer v2 必须交叉链接真实 succeeded job，严格 v1 仅作为 direct-artifact 兼容合同且必须指向已验证的不可变 artifact，不得被描述成 job-backed evidence。畸形/orphan/mismatch 均使 readiness false 并返回结构化 `503`；有效 legacy promotion record 仅在其受限兼容合同内保留。 |
| R8 Path/historical numeric contract | path/historical 配置、结构参数、stress mass、horizon/cardinality、ESS/confidence、midpoint 与 no-arb/payoff 阈值可被 `NaN`、超大有限值、字符串、bool、未知字段或跨字段矛盾绕过；极端但有限的相反特征还可令全部 kernel weight 下溢为零并触发 ESS 除零，进而丢失概率质量、溢出为 `Infinity` 或错误输出 `ELIGIBLE`。 | 两个配置入口均使用 exact schema；candidate、history、bootstrap、stress、regime 与 random-seed 数值边界只接受原生数值并执行完整范围/顺序约束；spread 必须 `long_strike > short_strike` 且 entry credit 不超过宽度乘 size；相似度采用 scale-safe distance 与 log-sum-exp，全部相似度质量消失时 ESS 明确为 0 并进入 conservative hierarchical pooling；只有 stress 启用时归一为完整概率质量，所有 scenario 权重必须合计 1；历史 path 的声明 horizon、候选 horizon 与 return 数严格一致；midpoint 使用溢出安全计算，历史报告递归拒绝非有限数值且 CLI strict JSON；no-arb error 上限不超过 1，payoff tolerance 不超过 10,000 bps，并再次校验派生容差有限。 |
| R9 Persisted artifact public schema | 仅重算 content hash 仍可把未知字段、未知 failure code，甚至把一个已知对象 shape 移到错误语义路径后作为“可信”结果反射给 API consumer。 | 对 content-addressed baseline artifact 的每个语义路径实施版本化 exact keysets，覆盖 empty/row/window/expiry/buyback 合法变体；`failure_counts` 限定为已知失败码；顶层、nested 与 known-shape misplacement 均被 tamper 回归拒绝，哈希完整性不再替代公共合同验证。 |
| R10 Account/RPC provenance | 未签名账户 snapshot 虽不能提升 `/readyz`，仍可由 `/account/risk` 显示 `available/ALLOW_NEW`；私有 JSON-RPC 只要有 `result` 就接受错误或缺失的 envelope/id。 | API 装载边界把所有未认证且非 missing 的账户 payload 降级为脱敏 `auth_failed`、空仓位、`NO_TRADE`、`auth_safe=false`；有效 HMAC payload 才能保持 available；RPC response 必须精确 `jsonrpc=2.0` 且整数 id 与请求一致，缺失、错配和 bool id 全部 fail closed。 |

## C. 证据诚实化

类别结论为 **确认属实**：若干输出把 fixture 常量或静态声明包装成 measured
evidence。本轮原则是宁可明确 unavailable，也不输出貌似可信的伪计算。

| 项 | 核验结论 | 整改 | 回归证据 | 仍阻塞 / 拒绝理由 |
| --- | --- | --- | --- | --- |
| C1 Calibration | 常量 score/correlation/VIF 和散文式 leakage pass 不是 walk-forward 证据。 | 输出 `not_implemented` / `unavailable`；没有真实 folds 和 content-addressed artifact 时不输出任何统计或 promotion claim。 | `test_calibration_reports_unimplemented_without_plausible_fixture_metrics` 及 calibration 合同测试。 | ISSUE-013、DQR-009 blocked，直到真实 OOS/model promotion 证据存在。 |
| C2 EV/path ranking | 固定收益和固定路径不能标成 validated history 并参与排名。 | 无 validated path/model 时返回 `unavailable`，不输出 plausible EV/CVaR/P-touch；构造冲击统一命名 `synthetic-stress-*`。 | EV unavailable 与 path-risk regression 用例。 | ISSUE-010 blocked；synthetic stress 只可用于敏感性研究。 |
| C3 Position economics | 虚构 hedge/roll/premium 数字会污染真实账户记录。 | 保留观测状态迁移；缺少显式经济输入时不输出数值。 | position honesty 与 replay 测试。 | ISSUE-012 blocked。 |
| C4 Interface inventory | 静态自画像不能自证 runtime available。 | CLI/API inventory 与真实 parser/handler 对齐；无 probe 时标为 declared/unverified。 | full-surface evidence-honesty、CLI/API/dashboard parity 用例。 | inventory 只是导航元数据，不是 availability 证据。 |
| C5 Production gates | 十三个伪计算 gate 和不存在的 WebSocket 通过文案制造假确定性。 | 发布授权折叠为唯一 external/manual state；dashboard 删除“research trust=production ready”和伪 WS pass 文案。 | external authorization、dashboard truthfulness、CI `/readyz` fail-closed 断言。 | 外部 gap/resync、soak 和 calendar evidence 仍缺失，production NO-GO。 |
| C6 Paper ledger | 不可达的 proposal/approval 机器不能算能力。 | executable output 为小型 `unsupported` 状态：不生成 proposal、不 approval、不 persistence、不自授权 reconciliation。 | paper honesty、unwritten storage、existing-file cannot self-authorize 用例。 | ISSUE-015、DQR-012 blocked；Gate 7 必须另行授权。 |

## D. 结构简化与拒绝项

复杂度诊断有价值，但部分删除建议违反当前 North Star。以下每项都记录取舍，
避免未来重复探索已经拒绝的路径。

| 项 | 核验结论 | 整改 / 取舍 | 回归证据 | 仍阻塞 / 拒绝理由 |
| --- | --- | --- | --- | --- |
| D1 Async job | A10/A11 说明实现需要加固，但 async 合同本身不是可删除的“仪式”。 | 保留 async `202`、bounded queue、idempotency、lifecycle、timeout、immutable result；修复公开边界。 | async admission/idempotency/timeout/recovery/API 测试。 | 同步 POST 或删除 job service 被拒绝：North Star 明确要求现有合同。 |
| D2 Readiness/I/O | `/readyz` 全量构建报告及重复 snapshot 读取没有必要。 | readiness 改为依赖导向；同一配置 snapshot 只读取并传递一次。 | readiness dependency 与 `test_readiness_reads_configured_market_snapshot_once`。 | liveness 与 readiness 必须继续分离。 |
| D3 Alias/schema | 同包双向 alias 会扩大受信输入面，但一刀切可能破坏已发布 consumer。 | 新输出只写 canonical key；仅在有兼容证据的 input boundary 接受 legacy alias。 | component/contract regression suite。 | blanket compatibility deletion 被拒绝，需单独迁移证据。 |
| D4 Forbidden keys | 封锁 strike/expiry 等通用领域词不是安全控制。 | 只封锁真正 executable/order-directive 概念；安全依赖结构性无下单 transport、mode gate 和输出行为。 | research report safety/forbidden-output tests。 | 不再以键名替代行为安全。 |
| D5 Builder-validator mirror | 大量进程内镜像校验只会验证自身漂移，但持久化公共 artifact 是跨进程信任边界。 | 普通 production validation 收敛到稳定 public/safety invariants；只有 content-addressed persisted artifact 使用版本化 exact schema，详细内部 shape 仍由 component tests 负责。 | report contract、artifact tamper 与各 builder component tests。 | 进一步删除需另开先锁行为的 refactor，不在本轮扩大。 |
| D6 Duplicate helpers | 重复 helper 的确增加维护成本。 | 只在能缩短当前 diff 且不新增依赖层时合并。 | compileall 与 486-test 全仓套件通过。 | 为“统一”新增抽象层或依赖被拒绝。 |

## E. 仓库卫生

原评审对 workflow debris 的判断部分正确，但“automation/issues/tools/coordination
tests 全部零消费者”的推断过宽。

| 项 | 核验结论 | 整改 / 取舍 | 回归证据 | 仍阻塞 / 拒绝理由 |
| --- | --- | --- | --- | --- |
| E1 Ultracode 运行产物 | 这类过程产物不应继续污染 active tree。 | 263 个 tracked `.workflow/ultracode/` 路径从 active tree 删除，并加入 ignore；历史仍可从 Git 恢复。 | scoped diff、ignore 检查与 486-test 全仓套件通过。 | 若需审计旧 run product，必须从 Git 历史恢复，不得重新写入 active tree。 |
| E2 保留的 workflow/runtime 文件 | 并非 `.workflow/` 下所有内容都无消费者。 | 保留 `.workflow/verify-dashboard-cdp.mjs`、sidecar wrappers 及有明确 CI/runtime consumer 的文件。 | 路径存在性、CI/runtime 引用及相关测试。 | blanket `.workflow/` 删除被拒绝。 |
| E3 automation/issues/tools | “零运行时依赖”不能推出“零治理/安全消费者”。 | 不 bulk-delete；过期 handoff 改标 audit-only，当前 board/issue/tool contract 保留。 | governance consistency、link check、controller/security tests。 | 整树删除被拒绝，避免破坏 Goal projection、CI、SECURITY 和运维边界。 |
| E4 immutable evidence | V2 cutover/content-addressed evidence 是审计栅栏。 | `docs/automation/archive/options-platform-v1/` 与 `docs/automation/evidence-store/` 保持不可变。 | 相对固定点的 scoped diff 对两个路径均为空。 | 不以“减重”为由删除不可变审计证据。 |

本报告不宣称最终减少百分比或最终文件数。只有最终 diff 完成 review 且 retained
consumer 边界验证通过后，才接受仓库卫生结论。

## 治理真相对齐

| 范围 | 当前状态 | 含义 |
| --- | --- | --- |
| ISSUE-001..009、ISSUE-011、ISSUE-014 | conditional accepted | 仅限确定性/fail-closed 研究能力，不代表生产或执行 |
| ISSUE-010、ISSUE-012、ISSUE-013、ISSUE-015 | blocked | 分别为 ranking unavailable、缺显式 economics、calibration not implemented、paper/manual unsupported |
| ISSUE-DQR-001..008、ISSUE-DQR-010..011 | conditional accepted | 有确定性证据支撑的 local/replay 合同 |
| ISSUE-DQR-009、ISSUE-DQR-012 | blocked | 无 promoted model artifact；无持久化 30-60 天 paper reconciliation 证据 |

`reopened` 是审计状态迁移，不是另一个终态：它表示 2026-07-14 复核推翻了旧的
completion claim。所有 reopened 项的当前 canonical board state 都是 `blocked`。

## 仍然 NO-GO 的工作

- 在 Docker-capable 主机或 CI 上实际运行容器 build 及
  secure-default/liveness/readiness 探针，并回填精确证据；
- 收集 authenticated WebSocket gap/resync、连续 24 小时 clean soak 和七个连续
  calendar days；
- 接入授权历史语料，生成真实 OOS folds 和 content-addressed model promotion
  证据后，才允许 EV ranking/sizing；
- 提供显式 premium/hedge/roll/protective observations 后，仓位经济学才能从
  unavailable 升级；
- 以独立授权范围定义 paper/manual，并获得真实 30-60 天 reconciliation；不得
  复活 tracer 常量充当验收；
- credential、HMAC key 和 private payload 必须始终置于仓库外。

在上述条件满足前，唯一正确的发布结论是：
**RESEARCH_ONLY / NO_TRADE / NO-GO**。
