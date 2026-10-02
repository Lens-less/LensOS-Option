import { previewNow } from "./preview";
import { useCallback, useEffect, useRef, useState } from "react";

import { discoverDesk, compareDesk, reviewObservation } from "./preview";
import { CompareWorkspace } from "./CompareWorkspace";
import { candidateComparable, deskExpired, deskTime, DiscoverWorkspace } from "./DiscoverWorkspace";
import { ObserveWorkspace } from "./ObserveWorkspace";
import { loadObserveState, saveObservation } from "./observeStore";
import { scenarioForSelection } from "./scenario";
import { DEFAULT_DESK_CRITERIA, DEFAULT_DESK_SCENARIO } from "./types";
import type { DecisionDesk, DeskAsset, DeskCandidate, DeskComparison, DeskCriteria, DeskMode, DeskScenario } from "./types";
import "./decisionDesk.css";

type Workspace = "discover" | "compare" | "observe";
const WORKSPACES: { id: Workspace; label: string; step: string }[] = [
  { id: "discover", label: "发现机会", step: "01" },
  { id: "compare", label: "比较决策", step: "02" },
  { id: "observe", label: "观察复盘", step: "03" },
];

function initialMode(): DeskMode {
  return "demo";
}

function initialAsset(): DeskAsset {
  return new URLSearchParams(window.location.search).get("asset") === "ETH" ? "ETH" : "BTC";
}

function failureCopy(error: unknown): string {
  if (error instanceof Error && /timeout|超时/i.test(error.message)) return "本次请求超时；当前结果已停止更新，请稍后重试。";
  return "无法完成这次研究请求。请重置样例后重试；本预览只允许列明的固定组合和情景。";
}

export interface DecisionDeskAppProps {
  loadDesk?: typeof discoverDesk;
  loadComparison?: typeof compareDesk;
  reviewRecord?: typeof reviewObservation;
}

export function DecisionDeskApp({ loadDesk = discoverDesk, loadComparison = compareDesk,
  reviewRecord = reviewObservation }: DecisionDeskAppProps): React.JSX.Element {
  const [workspace, setWorkspace] = useState<Workspace>("discover");
  const [asset, setAsset] = useState<DeskAsset>(initialAsset);
  const [mode] = useState<DeskMode>(initialMode);
  const [criteria, setCriteria] = useState<DeskCriteria>({ ...DEFAULT_DESK_CRITERIA });
  const [desk, setDesk] = useState<DecisionDesk | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [scenario, setScenario] = useState<DeskScenario>({ ...DEFAULT_DESK_SCENARIO });
  const [comparison, setComparison] = useState<DeskComparison | null>(null);
  const [scenarioAdjusted, setScenarioAdjusted] = useState(false);
  const [scenarioNotice, setScenarioNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(previewNow);
  const [initialObserve] = useState(loadObserveState);
  const [observeState, setObserveState] = useState(initialObserve.state);
  const [storageError, setStorageError] = useState<string | null>(initialObserve.error);
  const discoverySequence = useRef(0);
  const comparisonSequence = useRef(0);
  const criteriaRef = useRef(criteria);
  criteriaRef.current = criteria;
  const scenarioRef = useRef(scenario);
  scenarioRef.current = scenario;
  const headingRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async (nextAsset: DeskAsset, nextMode: DeskMode, nextCriteria: DeskCriteria) => {
    const sequence = ++discoverySequence.current;
    ++comparisonSequence.current;
    setBusy(true); setComparing(false); setError(null); setComparisonError(null); setNotice(null);
    setSelectedIds([]); setComparison(null); setScenarioAdjusted(false); setDesk(null);
    const previous = scenarioRef.current;
    const reset = scenarioForSelection(null, [], previous);
    scenarioRef.current = reset; setScenario(reset);
    setScenarioNotice(previous.time_days === reset.time_days ? null
      : "样例选择已重置，共同情景恢复为原始假设。重新选腿后可切换预计算情景。");
    try {
      const result = await loadDesk(nextAsset, nextCriteria, nextMode);
      if (sequence !== discoverySequence.current) return;
      setDesk(result); setNowMs(previewNow());
    } catch (failure) {
      if (sequence === discoverySequence.current) setError(failureCopy(failure));
    } finally {
      if (sequence === discoverySequence.current) setBusy(false);
    }
  }, [loadDesk]);

  useEffect(() => {
    void refresh(asset, mode, criteriaRef.current);
    return () => { ++discoverySequence.current; ++comparisonSequence.current; };
  }, [asset, mode, refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(previewNow()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const navigate = (next: Workspace) => {
    setWorkspace(next); setNotice(null);
    window.scrollTo({ top: 0, behavior: "instant" });
    window.setTimeout(() => headingRef.current?.focus(), 0);
  };

  const select = (candidate: DeskCandidate) => {
    if (!desk) return;
    let nextIds: string[];
    if (selectedIds.includes(candidate.candidate_id)) {
      nextIds = selectedIds.filter((id) => id !== candidate.candidate_id);
    } else {
      if (deskExpired(desk, previewNow())) return;
      if (!candidateComparable(candidate) || selectedIds.length >= 3) return;
      const first = desk.candidates.find((item) => item.candidate_id === selectedIds[0]);
      if (first && first.expiry_date !== candidate.expiry_date) {
        setNotice("为了使用同一时间假设，请选择同一到期日的结构。"); return;
      }
      nextIds = [...selectedIds, candidate.candidate_id];
    }
    const nextCandidates = desk.candidates.filter((item) => nextIds.includes(item.candidate_id));
    const previous = scenarioRef.current;
    const normalized = scenarioForSelection(desk, nextCandidates, previous);
    setSelectedIds(nextIds); scenarioRef.current = normalized; setScenario(normalized);
    if (normalized.time_days !== previous.time_days) setScenarioNotice(
      "样例组合已变化，共同情景恢复为可用的原始预设。");
    ++comparisonSequence.current; setComparing(false); setComparison(null); setScenarioAdjusted(false); setComparisonError(null);
  };

  const runComparison = async () => {
    if (!desk || deskExpired(desk, previewNow()) || selectedIds.length < 2) return;
    if (!selectedIds.every((id) => {
      const candidate = desk.candidates.find((item) => item.candidate_id === id);
      return candidate !== undefined && candidateComparable(candidate);
    })) { setComparisonError("所选结构的报价已到复核期限，请重新读取行情后比较。"); return; }
    const sequence = ++comparisonSequence.current;
    setComparing(true); setComparisonError(null); setNotice(null);
    const previous = scenarioRef.current;
    const normalized = scenarioForSelection(desk,
      desk.candidates.filter((candidate) => selectedIds.includes(candidate.candidate_id)), previous);
    scenarioRef.current = normalized; setScenario(normalized);
    if (normalized.time_days !== previous.time_days) setScenarioNotice(
      `经过时间已调整为所选结构允许的 ${normalized.time_days} 天；本次计算使用调整后的共同情景。`);
    try {
      const result = await loadComparison(desk.snapshot_id, selectedIds, normalized, desk.analysis_id);
      if (sequence === comparisonSequence.current) { setComparison(result); setScenarioAdjusted(false); }
    } catch (failure) {
      if (sequence === comparisonSequence.current) { setComparison(null); setComparisonError(failureCopy(failure)); }
    } finally {
      if (sequence === comparisonSequence.current) setComparing(false);
    }
  };

  const save = (candidateId: string, note: string) => {
    if (!desk || !comparison || deskExpired(desk, previewNow())) return;
    if (!comparison.members.every((member) => {
      const candidate = desk.candidates.find((item) => item.candidate_id === member.candidate_id);
      return candidate !== undefined && candidateComparable(candidate);
    })) { setNotice("比较中的报价已到复核期限，保存已暂停；请重新读取数据。"); return; }
    try {
      const saved = saveObservation(observeState, { desk, candidate_id: candidateId, comparison,
        viewpoint: desk.criteria.viewpoint, note });
      setObserveState(saved.state); setStorageError(null); setWorkspace("observe");
      setNotice("已保存在此浏览器本地；原快照和共同假设已冻结，本预览不能取得新报价。");
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch (failure) {
      setStorageError(failure instanceof Error ? failure.message
        : "浏览器本地存储不可用，记录尚未保存。可先复制研究复核；不要关闭当前比较。");
      setNotice("保存未完成，当前比较仍保留。请先复制研究复核。");
    }
  };

  const expired = desk ? deskExpired(desk, nowMs) : false;
  const dataLabel = desk
    ? expired ? "当前资格已暂停" : desk.qualification.data_status === "partial" ? "部分报价可用"
      : desk.qualification.data_status === "current" ? mode === "demo" ? "固定样例已载入" : "报价核验完成" : "数据不可用"
    : busy ? mode === "demo" ? "正在读取离线样例" : "正在采集与核验" : "数据读取失败";
  const selectedCandidates = selectedIds.map((id) => desk?.candidates.find((candidate) => candidate.candidate_id === id))
    .filter((candidate): candidate is DeskCandidate => candidate !== undefined);

  return <div className="decision-desk" data-mode={mode}>
    <a className="desk-skip-link" href="#decision-desk-main">跳到工作区</a>
    <header className="desk-masthead"><a className="desk-brand" href="?view=desk&mode=demo" aria-label="LensOS DecisionDesk 首页"><span aria-hidden="true">L</span>
      <div><strong>LensOS <span>DecisionDesk</span></strong><small>从结构发现，到研究判断</small></div></a>
      <nav aria-label="研究工作区">{WORKSPACES.map((item) => <button type="button" key={item.id}
        aria-current={workspace === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><span>{item.step}</span>{item.label}
        {item.id === "compare" && selectedIds.length > 0 ? <i>{selectedIds.length}</i> : null}
        {item.id === "observe" && observeState.records.length > 0 ? <i>{observeState.records.length}</i> : null}</button>)}</nav>
      <span className="desk-help-link">私有交互版</span>
    </header>

    <div className="desk-context-bar"><div className="desk-market-choice"><div className="desk-segmented desk-asset-picker" aria-label="研究标的">
      {(["BTC", "ETH"] as DeskAsset[]).map((item) => <button type="button" key={item} aria-pressed={asset === item}
        disabled={busy || comparing} onClick={() => { setWorkspace("discover"); setAsset(item); }}>{item}</button>)}</div>
      <span className="desk-context-family">Deribit · USDC 线性期权</span></div>
      <div className="desk-context-source"><span className="desk-pill" data-tone={mode === "demo" || expired ? "warning" : desk && !busy ? "good" : "neutral"}>
        {mode === "demo" ? "离线样例" : "公开行情"}</span><div><strong>{dataLabel}</strong><small>{desk ? `样例时刻 ${deskTime(desk.source.captured_at)}` : "完整合约腿和数据来源逐项保留"}</small></div></div>
      <div className="desk-context-actions"><button type="button" className="desk-button desk-button-quiet" disabled={busy || comparing}
        onClick={() => void refresh(asset, mode, desk?.criteria ?? criteria)}>{busy ? "读取中…" : mode === "demo" ? "重置样例选择" : "更新公开行情"}</button>
        <button className="desk-button desk-button-primary" disabled type="button" title="此预览未运行 Python 行情后端">实时行情未接入</button></div></div>
    <aside className="preview-banner" aria-label="预览限制"><strong>固定合成回放 · 不是真实机会</strong><p>固定评估时钟：2026-10-01 15:00 UTC。BTC / ETH 各提供 3 个结构、4 个预计算情景，共 32 组固定比较结果；虚构合约与报价由原 Python 引擎生成。本页不采集行情、不重新定价，当前时钟不代表报价仍有效。</p></aside><div className="desk-boundary-line"><p>{mode === "demo" ? "仅提供发现 → 预设比较 → 本地观察的交互预览；实时发现、任意重算与新报价复核不可用。" : "公开行情无需账户或密钥；数据刷新可能复用仍在有效窗口内的快照。"}</p><span>仅研究 · 不连接交易</span></div>
    {notice ? <div className="desk-global-notice" role="status">{notice}</div> : null}
    {storageError && workspace !== "observe" ? <div className="desk-global-notice" role="alert">{storageError}</div> : null}
    <div ref={headingRef} tabIndex={-1} className="desk-workspace-focus" aria-label={WORKSPACES.find((item) => item.id === workspace)!.label} />

    {workspace === "observe" ? <ObserveWorkspace state={observeState} onChange={(next) => { setObserveState(next); setStorageError(null); }} onReview={reviewRecord} storageError={storageError ?? undefined} />
      : !desk ? <main className="desk-workspace" id="decision-desk-main"><section className="desk-empty" role={error ? "alert" : "status"}>
        <span className={busy ? "desk-loading-mark" : ""} aria-hidden="true">{busy ? "◌" : "○"}</span><h1>{busy ? mode === "demo" ? "准备你的研究工作台" : "正在读取公开期权结构" : "这次数据尚未读取成功"}</h1>
        <p>{error ?? "先扫描合约范围，再核验入选结构的每一条腿。不推断缺失报价。"}</p>
        {error ? <button className="desk-button desk-button-primary" type="button" onClick={() => void refresh(asset, mode, criteria)}>重新读取</button> : null}</section></main>
      : workspace === "discover" ? <DiscoverWorkspace desk={desk} criteria={criteria} selectedIds={selectedIds} busy={busy || comparing} nowMs={nowMs}
        onCriteriaChange={setCriteria} onApply={() => void refresh(asset, mode, criteria)} onSelect={select}
        onCompare={() => { navigate("compare"); void runComparison(); }} />
      : <CompareWorkspace desk={desk} candidates={selectedCandidates} comparison={comparison} scenario={scenario} busy={comparing} nowMs={nowMs}
        error={comparisonError} scenarioAdjusted={scenarioAdjusted} scenarioNotice={scenarioNotice} onScenarioChange={(next) => {
          if (next.price_change_pct === scenario.price_change_pct && next.time_days === scenario.time_days
            && next.iv_shift_points === scenario.iv_shift_points) return;
          ++comparisonSequence.current;
          const normalized = scenarioForSelection(desk, selectedCandidates, next);
          scenarioRef.current = normalized; setScenario(normalized); setScenarioNotice(null);
          setComparison(null); setScenarioAdjusted(true); setComparing(false); setComparisonError(null);
        }} onRunComparison={() => void runComparison()}
        onRemove={(id) => { const candidate = desk.candidates.find((item) => item.candidate_id === id); if (candidate) select(candidate); }}
        onSave={save} onBack={() => navigate("discover")} />}

    <footer className="desk-footer"><p>LensOS DecisionDesk <span>合成样例 · 条件比较 · 本地笔记</span></p>
      <p>不提供订单、账户连接或仓位建议。条件损益与模型值不代表盈利概率。</p></footer>
  </div>;
}
