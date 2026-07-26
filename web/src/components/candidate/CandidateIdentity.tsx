import { instrumentOf } from "./format";
import { structureLabel, tierLabel, tierTone } from "./vocabulary";

/**
 * Who a candidate is, rendered the same way everywhere it appears.
 *
 * The instrument comes first because it is the identity; the structure is a
 * property of it. A table that led with the structure made every row read
 * `naked_short_call`, which is true of a hundred rows and identifies none.
 *
 * At 400px — the width the Chrome side panel lives at permanently — the parts
 * stack instead of truncating.
 */
export function CandidateIdentity({
  action,
  candidateId,
  expiryDate,
  structureType,
}: {
  action?: string | null;
  candidateId: string;
  expiryDate?: string | null;
  structureType?: string | null;
}): React.JSX.Element {
  return (
    <div className="candidate-identity">
      <strong className="candidate-identity-instrument">
        {instrumentOf(candidateId)}
      </strong>
      <span className="candidate-identity-meta">
        <span>{structureLabel(structureType)}</span>
        {expiryDate ? <time dateTime={expiryDate}>{expiryDate}</time> : null}
        {action ? (
          <span className="tier-badge" data-tone={tierTone(action)}>
            {tierLabel(action)}
          </span>
        ) : null}
      </span>
    </div>
  );
}
