import type { ScannerStatus } from "./candidateModel";

const HEADLINE: Record<Exclude<ScannerStatus, "validated">, string> = {
  unavailable: "候选筛选证据当前不可用",
  blocked: "候选筛选证据未通过验证",
};

const DETAIL: Record<Exclude<ScannerStatus, "validated">, string> = {
  unavailable: "本次报告没有生成 EV 候选扫描结果；页面不会构造示例候选或推断分层。",
  blocked: "EV 候选扫描结果未通过质量或口径校验，已被判定为不可信；筛选控件保持只读展示。",
};

export function ScreenerBlockedState({
  reasonCode,
  status,
}: {
  reasonCode: string | null;
  status: "unavailable" | "blocked";
}): React.JSX.Element {
  return (
    <div className="screener-blocked-state" role="status">
      <strong>{HEADLINE[status]}</strong>
      <p>{DETAIL[status]}</p>
      <code>{reasonCode ?? status.toUpperCase()}</code>
    </div>
  );
}
