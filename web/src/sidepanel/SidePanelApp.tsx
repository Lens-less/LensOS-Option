import React from "react";
import { selectSidePanelViewModel } from "../report";
import type { LoadedReport } from "../transport";
import type { DeribitContext } from "../extension/messages";
import {
  chromeSidePanelRuntime,
  type SidePanelRuntime,
} from "../extension/runtime";
import { SidePanelResearchSections } from "./SidePanelResearchSections";
import {
  type PanelStatus,
  SidePanelSettings,
  SidePanelStatusSections,
} from "./SidePanelStatusSections";
import { isOfflineError } from "./sidepanelFormatters";

interface PanelState {
  status: PanelStatus;
  origin: string;
  context: DeribitContext | null;
  loaded: LoadedReport | null;
  error: string | null;
}

const INITIAL_STATE: PanelState = {
  status: "loading",
  origin: "http://127.0.0.1:8000",
  context: null,
  loaded: null,
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

  const load = React.useCallback(
    async (force = false) => {
      setRefreshing(force);
      try {
        const [origin, context] = await Promise.all([
          runtime.getEngineOrigin(),
          runtime.getContext(),
        ]);
        setDraftOrigin(origin);
        const loaded = await runtime.getReport(force);
        setNowMs(Date.now());
        setPanel({
          status: "ready",
          origin,
          context,
          loaded,
          error: null,
        });
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "side panel failed to load";
        const origin = await runtime
          .getEngineOrigin()
          .catch(() => INITIAL_STATE.origin);
        const context = await runtime.getContext().catch(() => null);
        setDraftOrigin(origin);
        setPanel({
          status: isOfflineError(message) ? "offline" : "error",
          origin,
          context,
          loaded: null,
          error: message,
        });
      } finally {
        setRefreshing(false);
      }
    },
    [runtime],
  );

  React.useEffect(() => {
    void load(false);
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

  const model = React.useMemo(() => {
    if (!panel.loaded) {
      return null;
    }
    return selectSidePanelViewModel(panel.loaded, {
      nowMs,
      currentInstrumentName:
        manualInstrument.trim() || panel.context?.instrument || null,
    });
  }, [manualInstrument, nowMs, panel.context, panel.loaded]);

  const syncContext = React.useCallback(async () => {
    setManualInstrument("");
    const context = await runtime.getContext().catch(() => null);
    setPanel((current) => ({ ...current, context }));
  }, [runtime]);

  const saveOrigin = React.useCallback(async () => {
    setSavingOrigin(true);
    setConfigError(null);
    try {
      const origin = await runtime.setEngineOrigin(draftOrigin);
      setDraftOrigin(origin);
      setPanel((current) => ({ ...current, origin }));
      await load(true);
    } catch (error) {
      setConfigError(
        error instanceof Error ? error.message : "引擎地址保存失败",
      );
    } finally {
      setSavingOrigin(false);
    }
  }, [draftOrigin, load, runtime]);

  const effectiveInstrument =
    manualInstrument.trim() || panel.context?.instrument || "";
  const evidenceUrl = runtime.getEvidenceUrl(panel.origin);

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
            disabled={refreshing}
            onClick={() => void load(true)}
            type="button"
          >
            {refreshing ? "刷新研究中…" : "刷新研究"}
          </button>
        </div>
      </header>

      <div className="panel-chip-row">
        <span className="panel-chip panel-chip-readonly">READ-ONLY</span>
      </div>

      <SidePanelStatusSections
        context={panel.context}
        effectiveInstrument={effectiveInstrument}
        error={panel.error}
        evidenceUrl={evidenceUrl}
        manualInstrument={manualInstrument}
        model={model}
        onManualInstrumentChange={setManualInstrument}
        onRetry={() => void load(true)}
        onSyncContext={() => void syncContext()}
        status={panel.status}
      />
      <SidePanelResearchSections model={model} />

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
          READ-ONLY · RESEARCH_ONLY · 风险与退出为未校准研究模板，不构成交易建议。
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
