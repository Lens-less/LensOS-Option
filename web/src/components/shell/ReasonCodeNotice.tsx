import { useState } from "react";

import { readReasonCode } from "./reasonCodes";

function CopyableCommand({ command }: { command: string }): React.JSX.Element {
  const [copied, setCopied] = useState(false);
  return (
    <div className="reason-remedy-command">
      <code>{command}</code>
      <button
        onClick={() => {
          void navigator.clipboard
            ?.writeText(command)
            .then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 2000);
            })
            .catch(() => setCopied(false));
        }}
        type="button"
      >
        {copied ? "已复制" : "复制"}
      </button>
    </div>
  );
}

/**
 * Renders reason codes as something a reader can act on.
 *
 * Fail-closed means the blocked state is the most-viewed screen in the product,
 * and on a first run it is the only one. Showing `MISSING_VALIDATED_PATH_RISK`
 * and nothing else makes that screen a dead end: it says what is absent without
 * saying what would supply it. The code is still printed, because it is what
 * the engine emits and what a bug report needs, but it is secondary.
 */
export function ReasonCodeNotice({
  codes,
  heading,
}: {
  codes: string[];
  heading?: string;
}): React.JSX.Element | null {
  const unique = Array.from(new Set(codes.filter(Boolean)));
  if (unique.length === 0) {
    return null;
  }
  return (
    <section className="reason-notice" aria-label={heading ?? "阻断原因"}>
      {heading ? <h3>{heading}</h3> : null}
      <ul>
        {unique.map((code) => {
          const reading = readReasonCode(code);
          return (
            <li key={code}>
              <div className="reason-notice-head">
                <strong>{reading.title}</strong>
                <code className="reason-notice-code">{code}</code>
              </div>
              <p>{reading.detail}</p>
              {reading.remedy ? (
                <div className="reason-remedy">
                  <span>{reading.remedy.label}</span>
                  <CopyableCommand command={reading.remedy.command} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
