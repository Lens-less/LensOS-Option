import { useCallback, useEffect, useRef, useState } from "react";

import {
  EvidenceConsole,
  Masthead,
  friendlySource,
  reportFreshness,
} from "./components/evidence/EvidenceConsole";
import { AppShell } from "./components/shell/AppShell";
import type { AppView } from "./components/shell/AppShell";
import {
  SignalValidationView,
  useSignalArtifact,
} from "./components/signal/SignalValidationView";
import { ResearchWorkbench } from "./components/workbench/ResearchWorkbench";
import { validateResearchReport } from "./report";
import { loadResearchReportHttp } from "./transport";
import type { LoadedReport } from "./transport";

export { EvidenceConsole } from "./components/evidence/EvidenceConsole";
export type {
  EvidenceConsoleProps,
} from "./components/evidence/EvidenceConsole";
export { ResearchWorkbench } from "./components/workbench/ResearchWorkbench";
export type { ResearchWorkbenchProps } from "./components/workbench/ResearchWorkbench";

export type LoadReport = () => Promise<LoadedReport>;

function readViewFromLocation(): AppView {
  if (typeof window === "undefined") {
    return "evidence";
  }
  const view = new URLSearchParams(window.location.search).get("view");
  return view === "workbench" || view === "signal" ? view : "evidence";
}

type AppState =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      loaded: LoadedReport;
      refreshing: boolean;
    };

interface AppProps {
  loadReport?: LoadReport;
}

function LoadingState(): React.JSX.Element {
  return (
    <div className="app-shell state-shell">
      <Masthead refreshing={false} />
      <main className="state-main">
        <section className="state-card" role="status" aria-live="polite">
          <p className="section-kicker">research_report.v1</p>
          <h1>正在读取市场研究</h1>
          <p>正在核验 Deribit 快照、波动率曲面与候选研究；不会展示推断值。</p>
          <div className="loading-rule" aria-hidden="true" />
        </section>
      </main>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }): React.JSX.Element {
  return (
    <div className="app-shell state-shell">
      <Masthead refreshing={false} />
      <main className="state-main">
        <section className="state-card error-card" role="alert">
          <p className="section-kicker">report unavailable / fail closed</p>
          <h1>研究数据不可用</h1>
          <p>报告无法验证，BTC 价格、DVOL、曲面与候选均不展示。</p>
          <div className="error-boundary">
            <span>外部发布授权</span>
            <strong>NO-GO · NO_TRADE</strong>
          </div>
          <button className="refresh-button" type="button" onClick={onRetry}>
            重新读取
          </button>
        </section>
      </main>
    </div>
  );
}

function validateLoadedReport(loaded: LoadedReport): LoadedReport {
  if (!Number.isFinite(loaded.receivedAtMs)) {
    throw new Error("research report receipt time is invalid");
  }
  return {
    ...loaded,
    report: validateResearchReport(loaded.report),
  };
}

export function App({
  loadReport = loadResearchReportHttp,
}: AppProps): React.JSX.Element {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [view, setView] = useState<AppView>(() => readViewFromLocation());
  const signalArtifact = useSignalArtifact();
  const requestSequence = useRef(0);

  const switchView = useCallback((nextView: AppView) => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (nextView === "evidence") {
        params.delete("view");
      } else {
        params.set("view", nextView);
      }
      const query = params.toString();
      const nextUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
      window.history.pushState(window.history.state, "", nextUrl);
    }
    setView(nextView);
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      setView(readViewFromLocation());
    };
    window.addEventListener("popstate", handlePopState);
    return () => {
      window.removeEventListener("popstate", handlePopState);
    };
  }, []);

  const refresh = useCallback(async () => {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setState((current) =>
      current.status === "ready"
        ? { ...current, refreshing: true }
        : { status: "loading" },
    );
    try {
      const loaded = validateLoadedReport(await loadReport());
      if (requestSequence.current === sequence) {
        setNowMs(Date.now());
        setState({ status: "ready", loaded, refreshing: false });
      }
    } catch {
      if (requestSequence.current === sequence) {
        setState({ status: "error" });
      }
    }
  }, [loadReport]);

  useEffect(() => {
    void refresh();
    return () => {
      requestSequence.current += 1;
    };
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1_000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const handleVisibility = () => {
      if (
        document.visibilityState === "visible" &&
        state.status === "ready" &&
        !state.refreshing &&
        reportFreshness(
          state.loaded.report,
          state.loaded.receivedAtMs,
          Date.now(),
        ).phase !== "current"
      ) {
        void refresh();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refresh, state]);

  if (state.status === "loading") {
    return <LoadingState />;
  }
  if (state.status === "error") {
    return <ErrorState onRetry={() => void refresh()} />;
  }

  const report = state.loaded.report;
  const consoleProps = {
    nowMs,
    onRefresh: () => void refresh(),
    receivedAtMs: state.loaded.receivedAtMs,
    refreshing: state.refreshing,
    report,
  };

  return (
    <AppShell
      freshness={reportFreshness(report, state.loaded.receivedAtMs, nowMs)}
      onRefresh={() => void refresh()}
      onViewChange={switchView}
      refreshing={state.refreshing}
      report={report}
      source={friendlySource(report.data_status?.source)}
      view={view}
    >
      {view === "signal" ? (
        <SignalValidationView artifact={signalArtifact} />
      ) : view === "workbench" ? (
        <ResearchWorkbench {...consoleProps} embedded />
      ) : (
        <EvidenceConsole {...consoleProps} embedded />
      )}
    </AppShell>
  );
}
