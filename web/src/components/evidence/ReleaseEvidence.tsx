import type { ResearchReport } from "../../contracts";
import { OUTPUT_LABELS, evidenceItems, humanize } from "./reportModel";
import type { Blocker, Freshness, Queue } from "./reportModel";

function TruthStrip({
  freshness,
  report,
}: {
  freshness: Freshness;
  report: ResearchReport;
}): React.JSX.Element {
  const trustVerdict = report.data_trust?.verdict;
  const evidenceBoundary =
    freshness.phase === "current" && trustVerdict === "trusted"
      ? { label: "当前且可信", tone: "safe" }
      : freshness.phase === "current" &&
          report.data_status?.validated === true
        ? { label: "快照已验证 · 观察中", tone: "warning" }
      : freshness.phase === "warning" && trustVerdict === "trusted"
        ? { label: "临近失效", tone: "warning" }
        : freshness.phase === "expired"
          ? { label: "已失效", tone: "danger" }
          : { label: "不可声明", tone: "danger" };

  return (
    <section className="truth-strip" aria-label="四项运行边界">
      <dl>
        <div data-tone="safe">
          <dt>报告服务</dt>
          <dd>已连接并验证</dd>
        </div>
        <div data-tone={evidenceBoundary.tone}>
          <dt>市场证据</dt>
          <dd>{evidenceBoundary.label}</dd>
        </div>
        <div data-tone="danger">
          <dt>外部发布授权</dt>
          <dd>
            {report.full_system_surface?.release_readiness?.status ?? "NO-GO"}
          </dd>
        </div>
        <div data-tone="danger">
          <dt>执行边界</dt>
          <dd>RESEARCH_ONLY · NO_TRADE</dd>
        </div>
      </dl>
    </section>
  );
}

function BlockerQueue({
  blockers,
  description,
  title,
  queue,
}: {
  blockers: Blocker[];
  description: string;
  title: string;
  queue: Queue;
}): React.JSX.Element {
  return (
    <section className="blocker-queue" data-queue={queue} aria-label={title}>
      <div className="queue-heading">
        <div>
          <p className="section-kicker">{queue === "operator" ? "External" : "System"}</p>
          <h3>{title}</h3>
        </div>
        <span>{blockers.length} 项</span>
      </div>
      <p className="queue-description">{description}</p>
      <div className="blocker-list">
        {blockers.length === 0 ? (
          <p className="empty-state">当前没有此类待办。</p>
        ) : (
          blockers.map((blocker) => (
            <article className="blocker-item" key={blocker.code}>
              <div>
                <span className="owner-label">{blocker.ownerLabel}</span>
                <h4>{blocker.label}</h4>
              </div>
              <p>{blocker.action}</p>
              <code>{blocker.code}</code>
            </article>
          ))
        )}
      </div>
    </section>
  );
}

export function ReleaseBoundary({
  freshness,
  operatorBlockers,
  report,
  systemBlockers,
}: {
  freshness: Freshness;
  operatorBlockers: Blocker[];
  report: ResearchReport;
  systemBlockers: Blocker[];
}): React.JSX.Element {
  const blockedOutputs = report.blocked_outputs ?? [];
  const release =
    report.full_system_surface?.release_readiness?.status ?? "NO-GO";
  return (
    <section
      id="limitations"
      className="research-section limitations-section"
      aria-labelledby="limitations-title"
    >
      <header className="research-section-heading boundary-heading">
        <div>
          <p className="section-kicker">Release boundary / 次级状态</p>
          <h2 id="limitations-title">发布与能力边界</h2>
        </div>
        <div className="release-lockup">
          <span>发布状态</span>
          <strong>{release}</strong>
        </div>
      </header>
      <TruthStrip freshness={freshness} report={report} />
      <div className="blocked-output-note">
        <div>
          <strong>策略研究已形成，执行能力保持阻断。</strong>
          <p>不会生成交易建议、推荐仓位或订单指令。缺口只影响置信度与执行升级。</p>
        </div>
        <p>
          {blockedOutputs.length} 项输出已阻断：{" "}
          {blockedOutputs
            .map((output) => OUTPUT_LABELS[output] ?? humanize(output))
            .join(" · ")}
        </p>
      </div>
      <div className="boundary-priority">
        <div>
          <span>需要外部输入</span>
          <strong>{operatorBlockers.length} 项</strong>
          <p>
            {operatorBlockers
              .slice(0, 2)
              .map((blocker) => blocker.label)
              .join(" · ") || "当前无外部输入"}
          </p>
        </div>
        <div>
          <span>系统持续补齐</span>
          <strong>{systemBlockers.length} 项</strong>
          <p>
            {systemBlockers
              .slice(0, 2)
              .map((blocker) => blocker.label)
              .join(" · ") || "当前无系统缺口"}
          </p>
        </div>
      </div>
      <details className="diagnostic-drawer">
        <summary>
          <span>查看全部缺口与责任归属</span>
          <strong>{operatorBlockers.length + systemBlockers.length} 项</strong>
        </summary>
        <div className="queue-grid">
          <BlockerQueue
            blockers={operatorBlockers}
            description="需要凭证、账户快照或独立发布复核的外部输入。"
            queue="operator"
            title="操作员与外部动作"
          />
          <BlockerQueue
            blockers={systemBlockers}
            description="系统继续采集、计算或等待观察窗口，不归责给操作员。"
            queue="system"
            title="系统延续动作"
          />
        </div>
      </details>
    </section>
  );
}

export function EvidenceChain({
  report,
}: {
  report: ResearchReport;
}): React.JSX.Element {
  return (
    <section
      id="evidence-chain"
      className="research-section evidence-section"
      aria-labelledby="evidence-chain-title"
    >
      <header className="research-section-heading">
        <div>
          <p className="section-kicker">Evidence chain / 审计</p>
          <h2 id="evidence-chain-title">从市场数据到组合仲裁</h2>
        </div>
        <p>只展示报告中存在的状态；缺失值不会被估算或补齐。</p>
      </header>
      <ol className="evidence-chain">
        {evidenceItems(report).map((item) => (
          <li key={item.label} data-tone={item.tone}>
            <span className="chain-marker" aria-hidden="true" />
            <div>
              <p>{item.label}</p>
              <strong>{item.status}</strong>
              <small>{item.detail}</small>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
