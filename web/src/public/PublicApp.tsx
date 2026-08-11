import { useCallback, useEffect, useRef, useState } from "react";

import type { ResearchReport } from "../contracts";
import { SeriesHistoryView, useSeriesArtifact } from "../components/series/SeriesHistoryView";
import { SignalValidationView, useSignalArtifact } from "../components/signal/SignalValidationView";
import { loadPublicReport, type LoadedPublicReport } from "./loadPublicReport";
import { PublicEvidenceView } from "./PublicEvidenceView";
import { PublicShell } from "./PublicShell";
import { selectPublicFreshness, type PublicView } from "./publicModel";

function readViewFromLocation(): PublicView {
  if (typeof window === "undefined") {
    return "evidence";
  }
  const view = new URLSearchParams(window.location.search).get("view");
  return view === "signal" || view === "series" ? view : "evidence";
}

type AppState =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      loaded: LoadedPublicReport;
      refreshing: boolean;
    };

function PublicLoadingState(): React.JSX.Element {
  return (
    <div className="app-shell state-shell">
      <main className="state-main">
        <section className="state-card" role="status" aria-live="polite">
          <p className="section-kicker">public_research_report.v1</p>
          <h1>正在读取公开研究</h1>
          <p>正在校验公开报告、曲面证据、候选研究与信号验证；不会补齐内部控制层数据。</p>
          <div className="error-boundary">
            <span>运行边界</span>
            <strong>RESEARCH_ONLY · NO_TRADE</strong>
          </div>
          <div className="loading-rule" aria-hidden="true" />
        </section>
      </main>
    </div>
  );
}

function PublicErrorState({
  onRetry,
}: {
  onRetry: () => void;
}): React.JSX.Element {
  return (
    <div className="app-shell state-shell">
      <main className="state-main">
        <section className="state-card error-card" role="alert">
          <p className="section-kicker">public report unavailable / fail closed</p>
          <h1>公开研究数据不可用</h1>
          <p>公开报告无法验证时，页面会保留失败关闭边界，不展示当前市场数字。</p>
          <div className="error-boundary">
            <span>运行边界</span>
            <strong>RESEARCH_ONLY · NO_TRADE</strong>
          </div>
          <button className="refresh-button" type="button" onClick={onRetry}>
            重新读取静态快照
          </button>
        </section>
      </main>
    </div>
  );
}

function ensurePublicReport(loaded: LoadedPublicReport): LoadedPublicReport {
  const report = loaded.report as ResearchReport;
  if (report.schema_version !== "research_report.v1") {
    throw new Error("public report schema is invalid");
  }
  return loaded;
}

export function PublicApp(): React.JSX.Element {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [view, setView] = useState<PublicView>(() => readViewFromLocation());
  const loadedPublication = state.status === "ready" ? state.loaded : null;
  const artifactCapturedAt =
    loadedPublication?.report.publish_edition?.captured_at ?? undefined;
  const artifactPublishedAt =
    loadedPublication?.report.publish_edition?.published_at ?? undefined;
  const artifactIdentity =
    loadedPublication && artifactCapturedAt && artifactPublishedAt
      ? `${artifactCapturedAt}|${artifactPublishedAt}|${loadedPublication.receivedAtMs}`
      : null;
  const artifactQuery = artifactIdentity
    ? `?edition=${encodeURIComponent(artifactIdentity)}`
    : "";
  const signalArtifact = useSignalArtifact(
    artifactIdentity ? `./research/signal${artifactQuery}` : null,
    artifactCapturedAt,
  );
  const seriesArtifact = useSeriesArtifact(
    artifactIdentity ? `./research/series${artifactQuery}` : null,
    artifactCapturedAt,
  );
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
      const loaded = ensurePublicReport(await loadPublicReport());
      if (requestSequence.current === sequence) {
        setNowMs(Date.now());
        setState({ status: "ready", loaded, refreshing: false });
      }
    } catch {
      if (requestSequence.current === sequence) {
        setState({ status: "error" });
      }
    }
  }, []);

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
        selectPublicFreshness(
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
    return <PublicLoadingState />;
  }
  if (state.status === "error") {
    return <PublicErrorState onRetry={() => void refresh()} />;
  }

  const report = state.loaded.report;
  const freshness = selectPublicFreshness(report, state.loaded.receivedAtMs, nowMs);

  return (
    <PublicShell
      freshness={freshness}
      onRefresh={() => void refresh()}
      refreshing={state.refreshing}
      report={report}
      view={view}
    >
      {view === "signal" ? (
        <SignalValidationView artifact={signalArtifact} />
      ) : view === "series" ? (
        <SeriesHistoryView artifact={seriesArtifact} />
      ) : (
        <PublicEvidenceView
          freshness={freshness}
          report={report}
          signalSection={
            <SignalValidationView artifact={signalArtifact} embedded />
          }
          summary={state.loaded.summary}
        />
      )}
    </PublicShell>
  );
}
