# 收尾与产品形态改造方案（2026-07-25）

> **历史方案，已被后续事实契约部分替代。**
> 若与当前 CI、公开发布契约或现行 URL 兼容层冲突，以
> `docs/product/2026-08-12-continuity-and-consistency-spec.md`、`.github/workflows/ci.yml`
> 与现行运行时/测试行为为准。本文保留为决策记录，不再定义当前交付边界。

本文回答两个问题：

1. 这个仓库现在到底乱在哪里，怎么收尾；
2. 做成挂在 deribit.com 上的 Chrome 插件是不是最好的产品形态。

结论先说：

- **插件方向是对的，但不是"把项目改成插件"**。Python 决策引擎不可能搬进浏览器，插件只能是**第二个前端**。好消息是现有代码已经为这件事留好了缝。
- **真正的乱不在代码质量，而在三处**：两个最核心模块从未提交、同一个产品有两套 UI 实现、5k 行项目管理元工具混在产品包里。
- **最大的结构性问题**：`NO-GO` 在当前设计里是永久的，所以"收尾"没有定义。这必须先由你决定，否则任何清理都收不了尾。

## 2026-07-25 实施决议

本节覆盖下文尚未执行的原始建议；原文保留作为决策记录。

- 当前交付选择 **A · 插件 + 本地引擎**，面向个人自用，以 unpacked
  extension 交付；Chrome Web Store、托管引擎 B、用户认证和 Deribit
  非个人数据许可全部后置。
- 暂时继续提交 `static/evidence` 构建产物。当前 wheel 与 Docker 都不会运行
  Node 构建；在多阶段发布链完成前停止追踪产物会让 clean checkout 缺少前端。
  Content hash 保留，CI 继续验证源码构建后工作树无差异。
- `options_coordination_v2` 仍被 active state、迁移 hash fence 和安全文档消费，
  不执行 bulk delete。它继续与产品运行时隔离，未来只能连同状态、测试和历史证据
  作为一个原子 aggregate 迁出。
- 删除重复的 `static/dashboard.html` 渲染实现，但保留 `/dashboard` JSON/CLI
  投影；旧页面 URL 兼容到同一 Evidence Console，避免无必要的 schema v2。
- 不把 `NO-GO` schema 重写作为插件前置条件。现有执行边界、运行时 readiness
  与外部发布授权已经分离；当前工作只改善用户可见语义，并继续保持 fail-closed
  安全断言。
- 实施顺序改为：可信基线 → 本地 A 垂直切片 → 共享 validator/view-model/transport
  → 旧 UI 兼容退役 → 文档与治理隔离 → 全量验收。

---

## 第 0 部分 · 实测现状

不是读文档得出的，是跑出来的。

| 项目 | 实测值 |
| --- | --- |
| `crypto_options_report/` | 25,186 行 Python，零运行时依赖（纯 stdlib） |
| `tests/` | 20,321 行；**597 passed, 2 skipped, 684 subtests, 119 秒** |
| `tools/options_coordination_v2/` | 4,935 行 |
| `web/` | 6,674 行（`App.tsx` 2,467 + `styles.css` 2,690） |
| Deribit 实时链路 | 可用。`ingestion-status --live-deribit` 返回 `graph_complete: true`，7 个 feed 全部 `available/fresh`，872 个上游合约 |
| `research_report.v1` 载荷 | 114,612 字节 |
| 工作区脏文件 | 62 项 |

**技术健康度其实很好**：测试全绿、零依赖、fail-closed 契约有真实测试覆盖、CI 跑 4 个平台组合 + wheel 验证 + 容器 readyz 断言。这不是一个烂项目。

它给人"乱"的感觉，来自下面这些。

---

## 第 1 部分 · 乱在哪里（按严重度）

### 1.1 两个最核心的模块从未进入版本控制 ← 最严重

```
?? crypto_options_report/analysis_run.py        4,111 行
?? crypto_options_report/strategy_research.py   1,242 行
?? tests/test_analysis_run_contract.py          1,174 行
?? tests/test_strategy_research.py
?? tests/test_analysis_projection_surfaces.py
?? tests/test_storage.py
```

`analysis_run.py` 是 `README.md:184` 自己声明的"拥有 mandate/evidence/policy/opportunity/strategy/manifest/domain-event/entry-admission 全部契约"的模块，`AnalysisRun.evaluate()` 是 `DESIGN.md:259` 声明的"唯一公共应用缝"。**整个可信决策图的实现是未跟踪文件。** 一次 `git clean` 就没了。

### 1.2 CI 现在必然是红的

`.github/workflows/ci.yml` 最后一步：

```yaml
- name: Verify committed evidence bundle matches source
  run: git diff --exit-code -- crypto_options_report/static/evidence
```

而当前状态：

```
AD crypto_options_report/static/evidence/assets/index-CNnh1vsx.css   ← 入索引后被删
AD crypto_options_report/static/evidence/assets/index-yexXaVAb.js
?? crypto_options_report/static/evidence/assets/index-CbJc3_mz.css   ← 新产物未跟踪
?? crypto_options_report/static/evidence/assets/index-DLORoI2j.js
```

提交的 bundle 和 `web/` 源码已经不一致。**把 Vite 的 content-hash 产物提交进 git 本身就是持续冲突源**——每次 build 文件名都变，产生一对"删除+新增"。

### 1.3 同一个产品有两套 UI 实现

| 实现 | 体量 | 状态 |
| --- | --- | --- |
| `crypto_options_report/static/dashboard.html` | 97,910 字节手写单文件 | `README.md:29` 称"作为兼容的 dependency-free 页面保留" |
| `web/` → `static/evidence/` | 6,674 行 TSX/CSS，产物 278KB | `README.md:19` 称"推荐入口" |

两套都有专属测试（`test_dashboard_truthfulness.py` 893 行 + `test_evidence_console_delivery.py`），`full_surface.py` 把两套都注册成必须存在的 surface。**"兼容"是给谁的？没有外部消费者。** 这是 98KB 的死重，且每次改契约要改两遍。

### 1.4 5k 行项目管理元工具住在产品仓库里

`tools/options_coordination_v2/` 是一台 issue 追踪状态机——`coordinator.py`、`machine.py`、`git_candidate.py`、`github_readback.py`、`migration_v1.py`、`cutover_v1.py`。它和期权、和 Deribit、和产品**一点关系都没有**。

配套的还有 ~3,500 行测试（`test_options_platform_*.py` 共 9 个文件）和 `docs/automation/` 下 20+ 个 goal board / manifest / project-state / permissions 文件。

CI 甚至在 `python -m compileall -q crypto_options_report tools` 里编译它。

### 1.5 文档沉积成四层，且互相矛盾

```
根目录:  crypto_options_short_call_system_prd_v1_1.md            32 KB
        crypto_options_short_call_system_spec_v1_1_audit_fixed.md 61 KB
issues/: ISSUE-000..015 + DQR-001..012
docs/automation/: goal-board, 17 个 handoff, evidence-store 哈希文件,
                  options-platform-* 12 个文件, archive/
docs/research/:   10 份 PRD/审计/landscape
docs/operations/: 6 份 plan/report/runbook
design-previews/: 3 轮设计稿（未跟踪）
```

`project-acceptance-report.md:9` 自己写着：

> The Claude Fable remediation invalidates the earlier blanket claim that every ISSUE-001..015 and DQR-001..012 capability was complete. … Those claims are superseded.

也就是说：**大部分 handoff 文档是已被作废的历史叙事**，但它们和当前有效文档放在同一层目录里，读者无法分辨。

### 1.6 结构性问题：`NO-GO` 是永久的，"收尾"没有定义

这是最需要你先做决定的一点。

- `full_surface` 永远返回 `status: NO-GO`、`external_release_authorization: awaiting_external`
- 生产 `/readyz` 按设计返回 503，因为 `MODEL_NOT_READY`——而模型提升（ISSUE-013 walk-forward calibration）状态是 `not implemented`
- `web/src/App.tsx:2307` 的 `assertSafeResearchReport()` **硬断言** `release_readiness.status === "NO-GO"`，否则前端直接抛错

所以：只要 calibration 不实现，产品永远 `NO-GO`；而 calibration 是 P2 的事。**"收尾"在当前定义下不可能达成。** 你要么改 DoD 的含义，要么承认这是一个 research 工具而不是待发布产品（见 4.3）。

---

## 第 2 部分 · Chrome 插件形态：结论与实证

### 2.1 方向判断：对

三个真实理由：

1. **上下文贴合**。这个工具的输出是"入场前准入判断"——它唯一有意义的消费时刻，就是你正盯着 Deribit 期权链的那一刻。另开一个 `127.0.0.1:8000` 标签页，等于要求用户在两个信息源之间做心算对齐。浮层消除了这个对齐成本。
2. **数据同源**。用户在 `deribit.com` 上看到的价格和你的引擎判断的价格，可以在同一屏被对照——这正好服务于 `DESIGN.md:22` 的"快照有多新、多可信"。
3. **分发**。Web Store 是零摩擦分发渠道；让人 `pip install` + 跑 Docker + 配 HMAC 密钥，不是分发。

### 2.2 技术可行性：已核实的四个事实

**① 浮层不会被 Deribit 的 CSP 挡住。** Chrome 官方文档确认 content script 默认运行在 isolated world，有自己的 CSP；只有主动注入 main world 时页面 CSP 才生效。所以在 Shadow DOM 里挂 UI 是安全的，不管 Deribit 的 CSP 多严。

**② 网络请求必须在 service worker 里发，不能在 content script 里发。** Chromium 安全文档明确：自 Chrome 85，content script 的跨源 `fetch()` 携带**页面的 origin** 并受 CORS 约束；官方推荐模式是 content script 发消息 → background/service worker 取数 → 消息回传。这条决定了插件的骨架，也顺带绕开了 https 页面访问 `http://127.0.0.1` 的 mixed-content 争议（service worker 是 `chrome-extension://` 上下文）。

**③ 现有 API 零改动就能被插件读取。** `api.py:1011-1020`：

```python
if (
    self.command in {"POST", "DELETE"}
    and origin
    and not _origin_matches_host(origin, host_header)
):
```

Origin 校验**只作用于 POST/DELETE**。`GET /research/report` 带 `Origin: chrome-extension://<id>` 会通过。反过来 `POST /backtest/run` 会被拒（`_origin_authority` 只接受 https 或 loopback host，不接受 `chrome-extension:` scheme）——如果插件需要触发回测，这是一个精确的小改动，不是架构问题。

**④ React 前端已经是可移植的。** `web/src/App.tsx:2298`：

```tsx
export function App({ loadReport = loadResearchReport }: AppProps)
```

`loadReport` 是可注入的。换成"向 service worker 发消息"的实现，同一份 `EvidenceConsole` 就能跑在插件 side panel 里。**这是全项目最值钱的一个设计决定**，它让 2.4 的方案不需要重写 UI。

### 2.3 Python 引擎不能进浏览器

25,186 行 stdlib Python，核心是 `canonical_sha256` 内容寻址、HMAC 认证的 evidence sidecar、子进程隔离的回测、`PolicyCatalog` 集中裁决。移植意味着：

- 用 JS 重写 4,111 行 `analysis_run.py` 并保证 canonical JSON 哈希逐字节一致——否则 `decision_manifest` 的可复现审计链断裂，而那是整个产品的立论基础；
- Pyodide 不是答案：~10MB WASM 载荷、Web Store 审核阻力，而且"浏览器里算出的结论"和"引擎算出的结论"变成两个需要对账的东西。

**所以插件必须是引擎的客户端，不是引擎的替代。**

### 2.4 三种落地形态

| | A · 插件 + 本地引擎 | B · 插件 + 托管引擎 | C · 纯插件 JS 重写 |
| --- | --- | --- | --- |
| 用户要做什么 | 跑 Docker/wheel，配 HMAC 密钥 | 装插件，完 | 装插件，完 |
| 受众规模 | 你 + 少数几个 quant | 真实产品 | 真实产品 |
| Deribit 限流 | 每个用户自己的 IP | 集中一份快照扇出给 N 个客户端（更优） | 每个用户自己的 IP |
| 审计链 | 完整 | 完整 | **断裂** |
| 你的责任 | 零 | 向陌生人提供研究结论 | 同 B |
| 工作量 | 小 | 中 | 极大 |

**推荐路径：A 作为 Phase 3 的踏脚石，B 作为终点。C 不做。**

B 有一个漂亮的架构契合点，值得单独说：`README.md:60` 描述的三进程拆分——公共市场 sidecar / 私有只读账户 sidecar / Web API——**正好就是 B 需要的形状**：

```
你的 VPS:  market sidecar (一个 IP 轮询 Deribit, HMAC 签名快照)
              ↓
           engine API  ──→ N 个插件客户端（只读 GET /research/report）

用户本地:  account sidecar  ← 永远不托管
```

账户 sidecar 天然留在用户本地（凭证不出本机），所以托管引擎只提供市场研究，sizing 因缺少 account snapshot 而保持 blocked——**这恰好是现在代码已有的行为**（`DESIGN.md:52`："A missing account snapshot blocks sizing, not the rest of the research narrative"）。你不需要为托管场景新写安全边界，现有的 fail-closed 已经对了。

### 2.5 三个必须正视的风险

**① 引擎部署方式决定产品是否存在。** 这不是技术细节，是唯一的产品分岔点。选 A，你做的是一个自用工具的更好视图；选 B，你运营一个服务。**先决定这个，再写任何代码。**

**② Deribit 速率限制与 ToS 需要你亲自确认。** 官方 API Usage Policy 页面拒绝自动抓取（HTTP 403），我无法核实具体数值。检索到的政策要点是：Deribit 要求不要发送过量/冗余请求，否则会施加更严限流。设计影响：

- 形态 B 天然友好——一个 IP 一份快照，扇出给所有用户；
- 形态 A 每个用户独立轮询，规模化后是风险；
- **另外需要你自己去读 Deribit ToS 关于在其页面注入第三方 UI 的条款。** 客户端浮层通常不触犯条款，但你没有合作关系，Deribit 有权改 DOM 结构让你的锚点失效（这也是下面 Phase 3 要求"DOM 依赖最小化"的原因）。

**③ 定位张力，这是最深的一条。** 整个项目的伦理是 fail-closed、research-only、`execution_allowed=false`、`DESIGN.md:242` 明令禁止任何 sizing/order 控件。但你把它放到**交易屏幕上**，用户的第一反应必然是"那我该下多少手"。

浮层在交易界面旁边显示"入场准入：BLOCKED"，比同样内容显示在独立研究页上，更容易被读成交易建议。**如果做插件，`DESIGN.md` 第 11 节的 Do-not 清单需要针对"交易上下文内展示"重写一遍**，而不是照搬。

---

## 第 3 部分 · 改造方案

### Phase 0 · 收尾止血（半天到一天，无条件先做）

目标：让仓库进入一个可信状态。这一阶段不做任何设计决策。

1. **提交核心模块。** `analysis_run.py`、`strategy_research.py` 及其 4 个测试文件立即入库。这是当前最高优先级的单件事。
2. **停止提交构建产物。** 把 `crypto_options_report/static/evidence/assets/` 移出版本控制（加进 `.gitignore`），改为 CI/发布时构建。用固定文件名（Vite `rollupOptions.output.entryFileNames`）替代 content-hash，或者干脆保留 hash 但不入库。
   - 相应地把 CI 的 `git diff --exit-code -- crypto_options_report/static/evidence` 门禁换成"构建成功 + 产物存在 + `test_evidence_console_delivery.py` 通过"。
   - 打包链路（`pyproject.toml` 的 `package-data`）保持不变——wheel 里仍然带产物，只是产物来自构建而非 git。
3. **清理其余 62 项脏文件**：审阅现有 modified 内容，一次或几次语义清晰的提交落地。`design-previews/` 决定入库（作为 `selection.json` 的证据，`DESIGN.md:8` 引用了它）还是排除。
4. **跑绿 CI**，确认 Phase 0 完成。

### Phase 1 · 切掉非产品代码（一到两天）

1. **`tools/options_coordination_v2/` 迁出仓库。** 连带 9 个 `tests/test_options_platform_*.py`（~3,500 行）和 `docs/automation/options-platform-*`（12 个文件）。
   - 如果它还在用：迁到独立仓库；如果不在用：删除，git 历史留着。
   - CI 的 `compileall` 去掉 `tools`。
   - **净减约 8,400 行**，且测试时间会明显下降。
2. **文档降沉积。** 建立三层，物理隔离：
   ```
   docs/
     product/     ← 当前有效：DESIGN.md, 本文, 验收报告
     reference/   ← 当前有效的技术参考：runbook, data-quality PRD
     archive/     ← 全部历史叙事：issues/, handoffs/, 根目录两份 spec,
                    evidence-store/, 被 superseded 的 report
   ```
   `docs/archive/README.md` 一句话说明："以下内容为历史审计记录，不构成当前验收证据"——这句话 `project-acceptance-report.md` 已经写了，只是位置不对。
   把根目录的 32KB PRD 和 61KB spec 移进 `archive/`。

### Phase 2 · 单一前端（两到三天）

1. **删除 `static/dashboard.html`（97,910 字节）及其 893 行测试。** 从 `full_surface.py` 的必需 surface 列表里移除 `dashboard`、`/dashboard.html`、`/dashboard/page`、`/dashboard`。这是一次契约变更，需要 `full_system_surface` 的 schema 处理（`DESIGN.md:313` 说 schema version 在 P0 内 append-only，所以这一步可能需要 `full_system_surface.v2`）。
   - **如果你判断这个 fallback 有价值**（比如你希望在没有 Node 工具链的环境里也能看报告），那就反过来：明确写下它的唯一职责是"降级视图"，砍掉它复刻 React 版全部内容的部分，让它只显示 market pulse + admission decision + reason codes，从 98KB 降到 10KB 量级。**但不要维持两套等价实现。**
2. **`App.tsx` 2,467 行拆分。** 按 `DESIGN.md:33` 已定义的阅读序列切成组件文件（Masthead / MarketBrief / StrategyFramework / SurfaceResearch / CandidateTable / ReleaseBoundary / EvidenceChain）。这不是为了好看——Phase 3 要复用其中一个子集到插件里，2,467 行单文件做不到选择性复用。
3. **抽出 `loadReport` 抽象层**，为 Phase 3 的双传输（HTTP / 扩展消息）留缝。这一层现在已经存在（`App.tsx:2298`），只需要显式化成 `web/src/transport/` 模块。

### Phase 3 · 插件 MVP（一周左右，前提：你已选定 A 或 B）

架构：

```
manifest.json (MV3)
├── service_worker.ts     ← 唯一的网络出口
│     host_permissions: [<engine origin>]
│     GET /research/report → 校验 schema_version → 缓存 → 消息回传
│     绝不代理任意 URL（chromium 安全文档明确警告的 open-proxy 反模式）
├── content_script.ts     ← isolated world，Shadow DOM 挂载点
│     只做一件事：找锚点、挂 root、转发消息
│     DOM 依赖必须最小化且有降级——Deribit 会改版
└── sidepanel/            ← 复用 Phase 2 拆出的组件
      loadReport = () => chrome.runtime.sendMessage({type:"REPORT"})
      assertSafeResearchReport() 原样保留
```

关键约束，写进插件自己的 DESIGN：

- **service worker 是唯一网络出口**，content script 永不 fetch（技术原因见 2.2②，安全原因见 chromium 的 open-proxy 警告）。
- **114KB 的 report 载荷**通过 `chrome.runtime.sendMessage` 传递是可行的，但要做投影裁剪——插件浮层不需要完整 `evidence_lineage`，那部分放 side panel 按需拉。
- **`assertSafeResearchReport()` 必须原样保留**，包括 `NO-GO` 硬断言。插件是安全边界更需要被强制的地方，不是更少。
- **浮层默认折叠**。交易界面上的常驻浮层会被当成信号源；折叠 + 明确的 `READ-ONLY` 徽标是 2.5③ 张力的最低缓解。
- 不要 `content_security_policy` 里开 `unsafe-eval`，不要远程代码——Web Store 会拒。

如果选 B（托管引擎），额外需要：

- 引擎侧 bearer token 已经实现（`api.py` 的 `_request_requires_bearer_auth`），复用即可；
- `chrome-extension://<id>` 加入 `CRYPTO_OPTIONS_API_TRUSTED_ORIGINS` 的接受条件（`api.py:2228` 当前只接受 https / loopback host），仅在插件需要 POST 时才必要；
- TLS 反代 + 集中 market sidecar，按 `docs/operations/production-runbook.md` 已有的方案。

### Phase 4 · 重新定义发布门禁（决策，非编码）

见 4.3。这一步必须在 Phase 3 之前或并行完成，否则你会做出一个"永久显示 NO-GO"的插件——那不是产品。

---

## 第 4 部分 · 需要你决定的三件事

我把这三件事单独列出，因为它们不是技术选择，且**任何一件没定，后面的工作都会白做**。

### 4.1 引擎部署形态：A（本地）还是 B（托管）？

这决定插件是"自用工具的更好视图"还是"产品"。也决定 Deribit 限流风险、你的责任边界、以及是否需要用户认证。

我的建议：**按 A 实现 Phase 3（验证形态可行），但从第一行代码起就把 engine origin 做成可配置**，这样切到 B 不需要重构。

### 4.2 `static/dashboard.html` 的命运：删除，还是降级为 10KB fallback？

我倾向删除。它没有外部消费者，98KB 手写 HTML 复刻 React 版全部内容，每次契约变更要改两遍并维护两套 truthfulness 测试。但如果你有"无 Node 环境也要能看"的真实场景，就走降级方案——不要维持等价双实现。

### 4.3 `NO-GO` 的含义：这是最重要的一个

当前 `NO-GO` 同时承载了三种完全不同的含义，混在一个布尔里：

| 实际含义 | 现在的表达 |
| --- | --- |
| "本产品不含下单能力"（永久设计选择，**这是特性**） | `NO-GO` |
| "walk-forward calibration 未实现"（P2 工作项） | `NO-GO` |
| "生产运行时依赖未就绪"（运维状态） | `NO-GO` + `/readyz` 503 |

三者混一，导致：用户看到 `NO-GO` 无法知道这是"设计如此"还是"东西坏了"；而你无法"收尾",因为其中一项永远为真。

建议拆成三个独立的、语义清晰的字段：

- `execution_capability: "absent_by_design"` — 永久，是产品声明，不是缺陷；
- `model_promotion: "not_implemented"` — 明确的 P2 待办；
- `runtime_readiness: ready | degraded | unavailable` — 运维状态，可以为 ready。

这样"收尾"就有了定义：**当 research-only 核心的 `runtime_readiness` 能达到 `ready`、且 `execution_capability` 被正确表述为设计选择时，v1.0 就可以发布。** calibration 留在 roadmap 里，不再阻塞发布。

这是一次 schema 变更（`full_system_surface`、`web/src/App.tsx:2307` 的断言、`test_full_system_surfaces.py`、CI 的容器断言都要跟着改），但它是这个项目从"永久 NO-GO 的研究装置"变成"可发布产品"的唯一路径。

---

## 附：工作量与收益估算

| Phase | 工作量 | 代码净变化 | 收益 |
| --- | --- | --- | --- |
| 0 收尾止血 | 0.5–1 天 | +5,300 行入库 | 核心代码不再可能丢失；CI 转绿 |
| 1 切非产品代码 | 1–2 天 | **−8,400 行** | 仓库只剩产品；测试变快 |
| 2 单一前端 | 2–3 天 | **−98 KB**，App.tsx 拆分 | 契约变更只改一处；为插件解锁复用 |
| 3 插件 MVP | ~1 周 | +1,500 行（复用 UI） | 产品形态验证 |
| 4 门禁重定义 | 1 天决策 + 1 天改 | 少量 | **"收尾"变得可能** |

顺序建议：**0 → 1 → 4（决策）→ 2 → 3**。把 4.3 的决策提前到 Phase 2 之前，因为它会影响 Phase 2 里 `full_surface` 的 schema 改动方向，避免改两次。
