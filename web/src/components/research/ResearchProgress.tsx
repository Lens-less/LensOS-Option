import type { ReactNode } from "react";

import { readPublicReasonCode } from "../../public/publicReasonCodes";

export function evidenceCount(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;
}

export function countLabel(value: unknown): string {
  return evidenceCount(value)?.toLocaleString("zh-CN") ?? "未提供";
}

/** Only progress backed by an explicit artifact count and requirement is drawn. */
export function ResearchProgress({
  label,
  conclusion,
  evidenceState,
  nextStep,
  missing,
  progress,
  dates,
  generatedAt,
  reasonCodes = [],
  children,
}: {
  label: string;
  conclusion: string;
  evidenceState: string;
  nextStep: string;
  missing: string[];
  progress?: { label: string; current: number | null; required: number | null };
  dates?: string[];
  generatedAt?: string;
  reasonCodes?: string[];
  children?: ReactNode;
}): React.JSX.Element {
  const meter = progress && progress.current !== null &&
    progress.required !== null && progress.required > 0
    ? { value: progress.current, max: progress.required }
    : null;
  const codes = Array.from(new Set(reasonCodes));
  return (
    <section className="research-progress" aria-label={label}>
      <p className="research-progress-state">{evidenceState}</p>
      <h2>{conclusion}</h2>
      <p className="research-next-step"><strong>下一步</strong>{nextStep}</p>
      {children}
      {progress ? (
        <div className="research-progress-meter">
          <p>
            <span>{progress.label}</span>
            <strong>{countLabel(progress.current)} / {countLabel(progress.required)}</strong>
          </p>
          {meter ? (
            <progress aria-label={progress.label} value={meter.value} max={meter.max} />
          ) : null}
          <small>这是证据采集进度，不代表模型可信度或验证已经通过。</small>
        </div>
      ) : null}
      {missing.length > 0 ? (
        <div className="research-missing">
          <h3>还缺什么</h3>
          <ul>{missing.map((line) => <li key={line}>{line}</li>)}</ul>
        </div>
      ) : null}
      {dates !== undefined ? (
        <div className="research-capture-dates">
          <h3>已有有效采集日</h3>
          {dates.length > 0 ? (
            <ul>{Array.from(new Set(dates)).map((date) => (
              <li key={date}><time dateTime={date}>{date}</time></li>
            ))}</ul>
          ) : <p>产物未提供有效采集日期。</p>}
        </div>
      ) : null}
      {codes.length > 0 ? (
        <details className="research-reason-details">
          <summary>查看具体原因（{codes.length}）</summary>
          <ul>{codes.map((code) => {
            const reading = readPublicReasonCode(code);
            return (
              <li key={code}>
                <strong>{reading.title}</strong>
                <p>{reading.detail}</p>
                <code>{code}</code>
              </li>
            );
          })}</ul>
        </details>
      ) : null}
      {generatedAt ? (
        <p className="research-artifact-time">
          产物生成时间 <time dateTime={generatedAt}>{generatedAt}</time>
        </p>
      ) : null}
    </section>
  );
}
