import { useCallback, useEffect, useRef, useState } from "react";

import {
  EvidenceConsole,
  Masthead,
  friendlySource,
  reportFreshness,
} from "./components/evidence/EvidenceConsole";
import { AppShell } from "./components/shell/AppShell";
import type { AppView } from "./components/shell/AppShell";
import { ResearchErrorBoundary } from "./components/shell/ResearchErrorBoundary";
import {
  SeriesHistoryView,
  useSeriesArtifact,
} from "./components/series/SeriesHistoryView";
import {
  SignalValidationView,
  useSignalArtifact,
} from "./components/signal/SignalValidationView";
import { ResearchWorkbench } from "./components/workbench/ResearchWorkbench";
import { LearningApp } from "./components/demo/LearningApp";
import { APP_INDEX_HREF } from "./publicPaths";
import { validateResearchReport } from "./report";
import { loadResearchReportHttp } from "./transport";
import type { LoadedReport } from "./transport";
import { ReportLoadError, reportLoadErrorCopy, reportLoadErrorKind, type ReportLoadErrorKind } from "./transport/requestJson";

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
  return view === "workbench" || view === "signal" || view === "series" || view === "demo"
    ? view
    : "evidence";
}

type AppState =
  | { status: "loading" }
  | { status: "error"; kind: ReportLoadErrorKind }
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
          <div className="error-boundary">
            <span>执行边界</span>
            <strong>RESEARCH_ONLY · NO_TRADE</strong>
          </div>
          <div className="loading-rule" aria-hidden="true" />
          <a className="state-learning-link" href={`${APP_INDEX_HREF}?view=demo`}>先学习期权结构与风险</a>
        </section>
      </main>
    </div>
  );
}

function ErrorState({ onRetry, kind }: { onRetry: () => void; kind: ReportLoadErrorKind }): React.JSX.Element {
  const failure = reportLoadErrorCopy(kind);
  return (
    <div className="app-shell state-shell">
      <Masthead refreshing={false} />
      <main className="state-main">
        <section className="state-card error-card" role="alert">
          <p className="section-kicker">report unavailable / fail closed</p>
          <h1>研究数据不可用</h1>
          <p><strong>{failure.title}</strong>。{failure.action}</p>
          <p>本次报告无法验证，BTC 价格、DVOL、曲面与候选均不展示。</p>
          <div className="error-boundary">
            <span>执行边界</span>
            <strong>RESEARCH_ONLY · NO_TRADE</strong>
          </div>
          <button className="refresh-button" type="button" onClick={onRetry}>
            重新读取
          </button>
          <p className="state-recovery-help">等待数据恢复时，可以先学习如何阅读策略、损益与证据。</p>
          <a className="state-learning-link" href={`${APP_INDEX_HREF}?view=demo`}>进入离线学习导览</a>
        </section>
      </main>
    </div>
  );
}

function validateLoadedReport(loaded: LoadedReport): LoadedReport {
  try {
    if (!Number.isFinite(loaded.receivedAtMs)) throw new ReportLoadError("invalid");
    return { ...loaded, report: validateResearchReport(loaded.report) };
  } catch {
    throw new ReportLoadError("invalid");
  }
}

export function App({
  loadReport = loadResearchReportHttp,
}: AppProps): React.JSX.Element {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [view, setView] = useState<AppView>(() => readViewFromLocation());
  const validatedLoad = view !== "demo" && state.status === "ready" ? state.loaded : null;
  const signalArtifact = useSignalArtifact(validatedLoad ? "/research/signal" : null, undefined, validatedLoad);
  const seriesArtifact = useSeriesArtifact(validatedLoad ? "/research/series" : null, undefined, validatedLoad);
  const requestSequence = useRef(0);

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
    } catch (error) {
      if (requestSequence.current === sequence) {
        setState({ status: "error", kind: reportLoadErrorKind(error) });
      }
    }
  }, [loadReport]);

  useEffect(() => {
    if (view === "demo") return;
    void refresh();
    return () => {
      requestSequence.current += 1;
    };
  }, [refresh, view]);

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
        view !== "demo" &&
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
  }, [refresh, state, view]);

  if (view === "demo") {
    return <LearningApp />;
  }

  if (state.status === "loading") {
    return <LoadingState />;
  }
  if (state.status === "error") {
    return <ErrorState kind={state.kind} onRetry={() => void refresh()} />;
  }

  const report = state.loaded.report;
  const consoleProps = {
    nowMs,
    onRefresh: () => void refresh(),
    receivedAtMs: state.loaded.receivedAtMs,
    refreshing: state.refreshing,
    report,
  };
  const recoveryProps = {
    resetKey: state.loaded,
    onRetry: () => void refresh(),
    retrying: state.refreshing,
  };

  return (
    <AppShell
      freshness={reportFreshness(report, state.loaded.receivedAtMs, nowMs)}
      onRefresh={() => void refresh()}
      refreshing={state.refreshing}
      report={report}
      source={friendlySource(report.data_status?.source)}
      view={view}
    >
      {view === "signal" ? (
        <ResearchErrorBoundary label="信号验证视图" {...recoveryProps}>
          <SignalValidationView artifact={signalArtifact} />
        </ResearchErrorBoundary>
      ) : view === "series" ? (
        <ResearchErrorBoundary label="序列历史视图" {...recoveryProps}>
          <SeriesHistoryView artifact={seriesArtifact} />
        </ResearchErrorBoundary>
      ) : view === "workbench" ? (
        <ResearchErrorBoundary label="候选研究工作台" {...recoveryProps}>
          <ResearchWorkbench {...consoleProps} embedded />
        </ResearchErrorBoundary>
      ) : (
        <ResearchErrorBoundary label="证据控制台" {...recoveryProps}>
          <EvidenceConsole {...consoleProps} embedded />
        </ResearchErrorBoundary>
      )}
    </AppShell>
  );
}
