import React from "react";
import {
  selectContractComparison,
  selectReportFreshness,
  selectSidePanelViewModel,
} from "../report";
import {
  type StrategyBriefSurfaceState,
  validateStrategyBrief,
} from "../report/strategyBrief";
import type { LoadedReport } from "../transport";
import { marketDisplayState } from "../report/display";
import type { DeribitContext } from "../extension/messages";
import { ResearchErrorBoundary } from "../components/shell/ResearchErrorBoundary";
import { StrategyBriefView } from "../components/strategyBrief/StrategyBriefView";
import {
  chromeSidePanelRuntime,
  type SidePanelRuntime,
} from "../extension/runtime";
import { SidePanelComparisonSection } from "./SidePanelComparisonSection";
import { SidePanelResearchSections } from "./SidePanelResearchSections";
import {
  type PanelStatus,
  SidePanelSettings,
  SidePanelConnectionStatus,
  SidePanelStatusSections,
} from "./SidePanelStatusSections";
import { isOfflineError } from "./sidepanelFormatters";
import { normalizeEngineOrigin } from "../extension/config";

interface PanelState {
  status: PanelStatus;
  origin: string;
  context: DeribitContext | null;
  loaded: LoadedReport | null;
  /**
   * Last report cached for the current origin, kept only while `status` is
   * `"offline"`. Only provenance remains visible; current research is hidden.
   */
  cachedLoaded: LoadedReport | null;
  error: string | null;
}

const INITIAL_STATE: PanelState = {
  status: "loading",
  origin: "http://127.0.0.1:8000",
  context: null,
  loaded: null,
  cachedLoaded: null,
  error: null,
};

export function SidePanelApp({
  runtime = chromeSidePanelRuntime,
}: {
  runtime?: SidePanelRuntime;
}): React.JSX.Element {
  const [panel, setPanel] = React.useState<PanelState>(INITIAL_STATE);
  const [manualInstrument, setManualInstrument] = React.useState("");
  const [draftOrigin, setDraftOrigin] = React.useState(INITIAL_STATE.origin);
  const [savingOrigin, setSavingOrigin] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const [showSettings, setShowSettings] = React.useState(false);
  const [configError, setConfigError] = React.useState<string | null>(null);
  const [nowMs, setNowMs] = React.useState(() => Date.now());
  const requestSequence = React.useRef(0);

  const load = React.useCallback(
    async (force = false) => {
      const sequence = ++requestSequence.current;
      const isCurrent = () => requestSequence.current === sequence;
      setRefreshing(true);
      try {
        const [configuredOrigin, context] = await Promise.all([
          runtime.getEngineOrigin(),
          runtime.getContext(),
        ]);
        if (!isCurrent()) return;
        const origin = normalizeEngineOrigin(configuredOrigin);
        setDraftOrigin(origin);
        const loaded = await runtime.getReport(force, origin);
        if (!isCurrent()) return;
        setNowMs(Date.now());
        setPanel({
          status: "ready",
          origin,
          context,
          loaded,
          cachedLoaded: null,
          error: null,
        });
      } catch (error) {
        if (!isCurrent()) return;
        const message =
          error instanceof Error ? error.message : "side panel failed to load";
        const configuredOrigin = await runtime
          .getEngineOrigin()
          .catch(() => INITIAL_STATE.origin);
        let origin = INITIAL_STATE.origin;
        try { origin = normalizeEngineOrigin(configuredOrigin); } catch { /* Keep links on the safe default. */ }
        const context = await runtime.getContext().catch(() => null);
        if (!isCurrent()) return;
        setDraftOrigin(origin);
        const offline = isOfflineError(message);
        const cachedLoaded = offline
          ? await runtime.getCachedReport(origin).catch(() => null)
          : null;
        if (!isCurrent()) return;
        if (!cachedLoaded) setShowSettings(true);
        setPanel({
          status: offline ? "offline" : "error",
          origin,
          context,
          loaded: null,
          cachedLoaded,
          error: message,
        });
      } finally {
        if (isCurrent()) setRefreshing(false);
      }
    },
    [runtime],
  );

  React.useEffect(() => {
    void load(false);
    return () => { requestSequence.current += 1; };
  }, [load]);

  React.useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
      void runtime
        .getContext()
        .then((context) => {
          setPanel((current) => {
            if (
              current.context?.detectedAt === context?.detectedAt &&
              current.context?.instrument === context?.instrument &&
              current.context?.href === context?.href
            ) {
              return current;
            }
            return { ...current, context };
          });
        })
        .catch(() => undefined);
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [runtime]);

  // Cached data supplies provenance only; current evidence requires a ready report.
  const displayLoaded = panel.loaded ?? panel.cachedLoaded;
  const isStaleOffline =
    panel.status === "offline" && panel.cachedLoaded !== null;
  const marketState = displayLoaded
    ? marketDisplayState(displayLoaded.report, selectReportFreshness(displayLoaded.report, displayLoaded.receivedAtMs, nowMs))
    : "quality_blocked";
  const showCurrentEvidence = panel.status === "ready" && marketState === "available";

  const effectiveInstrumentName =
    manualInstrument.trim() || panel.context?.instrument || null;

  const model = React.useMemo(() => {
    if (!displayLoaded) {
      return null;
    }
    return selectSidePanelViewModel(displayLoaded, {
      nowMs,
      currentInstrumentName: effectiveInstrumentName,
    });
  }, [displayLoaded, effectiveInstrumentName, nowMs]);

  const comparison = React.useMemo(() => {
    if (!displayLoaded) {
      return null;
    }
    return selectContractComparison(
      displayLoaded.report,
      effectiveInstrumentName,
    );
  }, [displayLoaded, effectiveInstrumentName]);

  const syncContext = React.useCallback(async () => {
    setManualInstrument("");
    const context = await runtime.getContext().catch(() => null);
    setPanel((current) => ({ ...current, context }));
  }, [runtime]);

  const saveOrigin = React.useCallback(async () => {
    // Invalidate the prior request and withdraw its result before changing origins.
    requestSequence.current += 1;
    setSavingOrigin(true);
    setRefreshing(true);
    setConfigError(null);
    setPanel((current) => ({ ...current, status: "loading", loaded: null, cachedLoaded: null, error: null }));
    try {
      const origin = await runtime.setEngineOrigin(draftOrigin);
      setDraftOrigin(origin);
      setPanel((current) => ({ ...current, origin }));
      await load(true);
    } catch {
      setConfigError("引擎地址保存失败。请使用包含端口的本机 HTTP 地址，例如 http://127.0.0.1:8000。");
      setPanel((current) => ({ ...current, status: "error", error: "[report:aborted]" }));
    } finally {
      setSavingOrigin(false);
      setRefreshing(false);
    }
  }, [draftOrigin, load, runtime]);

  const effectiveInstrument = effectiveInstrumentName ?? "";
  const evidenceUrl = runtime.getEvidenceUrl(panel.origin);
  const strategyBrief = React.useMemo(() => {
    try {
      return displayLoaded?.report.strategy_brief
        ? validateStrategyBrief(displayLoaded.report.strategy_brief)
        : null;
    } catch {
      return null;
    }
  }, [displayLoaded]);
  const strategyBriefSurface = React.useMemo(() => {
    if (!displayLoaded || !strategyBrief) {
      return undefined;
    }
    return sidePanelStrategyBriefSurface(
      displayLoaded.report,
      selectReportFreshness(displayLoaded.report, displayLoaded.receivedAtMs, nowMs),
      isStaleOffline,
      nowMs,
    );
  }, [displayLoaded, isStaleOffline, nowMs, strategyBrief]);

  return (
    <main className="sidepanel-shell">
      <header className="panel-header">
        <div>
          <p className="panel-kicker">LensOS Option / Deribit</p>
          <h1>期权研究伴侣</h1>
        </div>
        <div className="panel-header-actions">
          <button
            className="panel-button"
            disabled={refreshing || savingOrigin}
            onClick={() => void load(true)}
            type="button"
          >
            {refreshing ? "刷新研究中…" : "刷新研究"}
          </button>
        </div>
      </header>

      <div className="panel-chip-row">
        <span className="panel-chip panel-chip-readonly">READ-ONLY</span>
        <span className="panel-chip panel-chip-readonly">RESEARCH_ONLY</span>
        <span className="panel-chip panel-chip-readonly">NO_TRADE</span>
      </div>

      <SidePanelConnectionStatus
        error={panel.error}
        evidenceUrl={evidenceUrl}
        isStaleOffline={isStaleOffline}
        onRetry={() => void load(true)}
        status={panel.status}
      />
      {panel.status === "ready" && !showCurrentEvidence ? (
        <section className="panel-card panel-status" role="status">
          <p className="panel-status-title">{marketState === "stale" ? "当前研究证据已失效" : "当前研究证据不可用"}</p>
          <p>当前排名、策略条件与研究数值已收起。请刷新取得时效与质量均有效的新报告。</p>
        </section>
      ) : null}

      <ResearchErrorBoundary
        label="研究数据区"
        onRetry={() => void load(true)}
        resetKey={displayLoaded}
        retrying={refreshing}
      >
        <StrategyBriefView
          brief={strategyBrief}
          surface={strategyBriefSurface}
        />
        <details className="strategy-brief-details panel-details">
          <summary>查看依据</summary>
          <SidePanelStatusSections
            currentEvidence={showCurrentEvidence}
            context={panel.context}
            effectiveInstrument={effectiveInstrument}
            manualInstrument={manualInstrument}
            model={model}
            onManualInstrumentChange={setManualInstrument}
            onSyncContext={() => void syncContext()}
          />
          {showCurrentEvidence ? (
            <>
              <SidePanelComparisonSection comparison={comparison} onSelectInstrument={setManualInstrument} />
              <SidePanelResearchSections model={model} />
            </>
          ) : null}
        </details>
      </ResearchErrorBoundary>

      <section className="panel-settings-toggle" aria-label="本地设置">
        <button
          aria-expanded={showSettings}
          className="panel-button panel-button-secondary"
          onClick={() => setShowSettings((value) => !value)}
          type="button"
        >
          {showSettings ? "收起引擎设置" : "引擎设置"}
        </button>
      </section>
      {showSettings ? (
        <SidePanelSettings
          configError={configError}
          draftOrigin={draftOrigin}
          onDraftOriginChange={setDraftOrigin}
          onSaveOrigin={() => void saveOrigin()}
          savingOrigin={savingOrigin}
        />
      ) : null}

      <footer className="panel-footer">
        <p>
          READ-ONLY · RESEARCH_ONLY · NO_TRADE ·
          风险与退出为未校准研究模板，不构成交易建议或下单授权。
        </p>
        <a
          className="panel-link-button"
          href={evidenceUrl}
          rel="noreferrer"
          target="_blank"
        >
          打开完整 Evidence Console
        </a>
      </footer>
    </main>
  );
}

function sidePanelStrategyBriefSurface(
  report: LoadedReport["report"],
  freshness: ReturnType<typeof selectReportFreshness>,
  isStaleOffline: boolean,
  nowMs: number,
): StrategyBriefSurfaceState {
  const runtime = report.runtime_context;
  if (!runtime) {
    return {
      freshness_status: "UNAVAILABLE",
      source_kind: "fallback",
      presented_as: "published",
      source_label: "Runtime provenance unavailable",
      now_ms: nowMs,
    };
  }
  const mode = runtime.mode;
  const displayState = marketDisplayState(report, freshness);
  const currentFreshness =
    report.data_status?.validated !== true || displayState === "quality_blocked"
      ? "UNAVAILABLE"
      : isStaleOffline || displayState === "stale" || freshness.phase === "warning"
      ? "STALE"
      : "CURRENT";
  return {
    freshness_status: currentFreshness,
    source_kind:
      mode === "published"
        ? "published"
        : mode === "replay"
          ? "replay"
          : runtime.demo_mode
            ? "demo"
            : "live",
    presented_as:
      mode === "published"
        ? "published"
        : mode === "replay"
          ? "replay"
          : "live",
    source_label:
      mode === "published"
        ? "Published edition"
        : mode === "replay"
          ? runtime.demo_mode
            ? "Demo snapshot"
            : "Replay snapshot"
          : isStaleOffline
            ? "Cached live report"
            : "Live API snapshot",
    now_ms: nowMs,
  };
}
