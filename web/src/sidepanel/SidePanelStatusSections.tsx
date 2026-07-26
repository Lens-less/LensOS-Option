import React from "react";
import type { DeribitContext } from "../extension/messages";
import type { SidePanelViewModel } from "../report";
import {
  coveredUnderlyingFromModel,
  contextEntryPointNotice,
  labelForFreshness,
  labelForMatch,
  labelForSource,
  labelForTrust,
} from "./sidepanelFormatters";

export type PanelStatus = "loading" | "ready" | "offline" | "error";

const ENGINE_START_COMMAND =
  "python -m crypto_options_report.api --host 127.0.0.1 --port 8000";

interface SidePanelStatusSectionsProps {
  context: DeribitContext | null;
  effectiveInstrument: string;
  error: string | null;
  evidenceUrl: string;
  /** True only while `status === "offline"` and a last-known report is being
   * shown from cache; drives the persistent "stale" banner instead of the
   * full-page first-run checklist. */
  isStaleOffline: boolean;
  manualInstrument: string;
  model: SidePanelViewModel | null;
  status: PanelStatus;
  onManualInstrumentChange: (value: string) => void;
  onRetry: () => void;
  onSyncContext: () => void;
}

interface SidePanelSettingsProps {
  configError: string | null;
  draftOrigin: string;
  savingOrigin: boolean;
  onDraftOriginChange: (value: string) => void;
  onSaveOrigin: () => void;
}

export function SidePanelSettings({
  configError,
  draftOrigin,
  savingOrigin,
  onDraftOriginChange,
  onSaveOrigin,
}: SidePanelSettingsProps): React.JSX.Element {
  return (
    <section className="panel-card panel-settings">
      <header className="panel-card-header">
        <div>
          <p className="panel-section-kicker">Loopback origin</p>
          <h2>本地引擎设置</h2>
        </div>
      </header>
      <label className="panel-field">
        <span>HTTP loopback 地址（必须包含端口）</span>
        <input
          className="panel-input"
          onChange={(event) => onDraftOriginChange(event.target.value)}
          placeholder="http://127.0.0.1:8000"
          spellCheck={false}
          type="text"
          value={draftOrigin}
        />
      </label>
      <div className="panel-inline-actions">
        <button
          className="panel-button"
          disabled={savingOrigin}
          onClick={onSaveOrigin}
          type="button"
        >
          {savingOrigin ? "保存中…" : "保存地址"}
        </button>
      </div>
      {configError ? (
        <p className="panel-inline-error" role="alert">
          {configError}
        </p>
      ) : null}
    </section>
  );
}

export function SidePanelStatusSections({
  context,
  effectiveInstrument,
  error,
  evidenceUrl,
  isStaleOffline,
  manualInstrument,
  model,
  status,
  onManualInstrumentChange,
  onRetry,
  onSyncContext,
}: SidePanelStatusSectionsProps): React.JSX.Element {
  const entryPointNotice = contextEntryPointNotice(
    context,
    coveredUnderlyingFromModel(model),
  );

  return (
    <>
      <section className="panel-card">
        <header className="panel-card-header">
          <div>
            <p className="panel-section-kicker">Context / trust</p>
            <h2>当前合约与数据可信度</h2>
          </div>
        </header>

        <div className="panel-context-grid">
          <label className="panel-field">
            <span>已识别 / 手动合约</span>
            <input
              className="panel-input panel-input-contract"
              onChange={(event) =>
                onManualInstrumentChange(event.target.value.toUpperCase())
              }
              placeholder={context?.instrument ?? "BTC-7AUG26-71000-C"}
              spellCheck={false}
              type="text"
              value={manualInstrument}
            />
          </label>
          <button
            className="panel-button panel-button-secondary"
            onClick={onSyncContext}
            type="button"
          >
            同步当前合约
          </button>
          <div className="panel-context-copy">
            <strong>{effectiveInstrument || "尚未选择合约"}</strong>
            <p>
              {context?.href ??
                "打开 Deribit 期权页面，或在上方手动输入完整合约名。"}
            </p>
          </div>
        </div>
        {entryPointNotice ? (
          <p
            className={`panel-context-message${
              entryPointNotice.isWarning ? " is-warning" : ""
            }`}
          >
            {entryPointNotice.text}
          </p>
        ) : model ? (
          <p
            className={`panel-context-message${
              model.contractMatch.status === "mismatch" ||
              model.contractMatch.status === "strategy_candidate"
                ? " is-warning"
                : ""
            }`}
          >
            {model.contractMatch.message}
          </p>
        ) : null}

        <dl className="panel-stats">
          <div>
            <dt>来源</dt>
            <dd>{model ? labelForSource(model.sourceLabel) : "读取中…"}</dd>
          </div>
          <div>
            <dt>证据年龄</dt>
            <dd>{model ? labelForFreshness(model) : "读取中…"}</dd>
          </div>
          <div>
            <dt>信任</dt>
            <dd>{model ? labelForTrust(model.trustVerdict) : "读取中…"}</dd>
          </div>
          <div>
            <dt>当前上下文</dt>
            <dd>{model ? labelForMatch(model) : "等待中…"}</dd>
          </div>
        </dl>

        {model ? (
          <dl className="panel-identifiers" aria-label="完整研究标识">
              <div>
                <dt>Analysis run</dt>
                <dd>{model.analysisRunId ?? "未提供"}</dd>
              </div>
              <div>
                <dt>ETag</dt>
                <dd>{model.etag ?? "未提供"}</dd>
              </div>
              <div>
                <dt>Candidate</dt>
                <dd>{model.strategyCandidateId ?? "未提供"}</dd>
              </div>
              <div>
                <dt>Transport</dt>
                <dd>{model.cached ? "session cache" : "direct HTTP"}</dd>
              </div>
          </dl>
        ) : null}
      </section>

      {status === "loading" ? (
        <section className="panel-card panel-status" role="status">
          <p>正在读取本地研究报告…</p>
        </section>
      ) : null}

      {status === "offline" && isStaleOffline ? (
        <section
          className="panel-card panel-status panel-status-stale"
          role="alert"
        >
          <p className="panel-status-title">本地引擎离线 · 显示上次结果</p>
          <p>
            当前无法连接本地研究引擎；下方仍是最近一次成功读取的研究结果，可能已经过期。请核对证据年龄后再参考。
          </p>
          <pre className="panel-status-command">{ENGINE_START_COMMAND}</pre>
          {error ? (
            <p className="panel-status-detail">
              技术细节：<code>{error}</code>
            </p>
          ) : null}
          <div className="panel-inline-actions">
            <button className="panel-button" onClick={onRetry} type="button">
              重试
            </button>
            <a
              className="panel-link-button"
              href={evidenceUrl}
              rel="noreferrer"
              target="_blank"
            >
              打开完整证据
            </a>
          </div>
        </section>
      ) : null}

      {status === "offline" && !isStaleOffline ? (
        <section className="panel-card panel-status" role="alert">
          <p className="panel-status-title">本地引擎离线 · 首次设置</p>
          <p>还没有连接到本地研究引擎，也没有可显示的历史结果。三步即可开始：</p>
          <ol className="panel-onboarding-steps">
            <li>在本机启动研究引擎（下方命令可直接复制）。</li>
            <li>在 Chrome 中打开一个 Deribit 期权详情页。</li>
            <li>回到这里点击“重试”。</li>
          </ol>
          <pre className="panel-status-command">{ENGINE_START_COMMAND}</pre>
          {error ? (
            <p className="panel-status-detail">
              技术细节：<code>{error}</code>
            </p>
          ) : null}
          <div className="panel-inline-actions">
            <button className="panel-button" onClick={onRetry} type="button">
              重试
            </button>
            <a
              className="panel-link-button"
              href={evidenceUrl}
              rel="noreferrer"
              target="_blank"
            >
              打开完整证据
            </a>
          </div>
        </section>
      ) : null}

      {status === "error" ? (
        <section className="panel-card panel-status" role="alert">
          <p className="panel-status-title">报告校验失败</p>
          <p>报告未通过校验，已按 fail-closed 策略拒绝显示。</p>
          {error ? (
            <p className="panel-status-detail">
              技术细节：<code>{error}</code>
            </p>
          ) : null}
          <div className="panel-inline-actions">
            <button className="panel-button" onClick={onRetry} type="button">
              重试
            </button>
            <a
              className="panel-link-button"
              href={evidenceUrl}
              rel="noreferrer"
              target="_blank"
            >
              打开完整证据
            </a>
          </div>
        </section>
      ) : null}
    </>
  );
}
