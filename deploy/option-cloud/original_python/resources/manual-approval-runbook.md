# Manual Approval Runbook

Version: `manual-approval.v1`

Status: locally verified procedure; external approval still required.

This runbook governs human review of research candidates. It does not enable
paper mode, generate orders, or authorize live trading. The platform remains
`RESEARCH_ONLY / NO_TRADE` unless a separately reviewed release changes the
mode contract.

## Preconditions

All of the following evidence must refer to the same report and market snapshot:

- current promoted market-data trust evidence and a complete required feed graph;
- a validated read-only account snapshot with no authentication or freshness error;
- a promoted calibration model and aligned out-of-sample backtest artifact;
- a persistent paper ledger with completed reconciliation observation;
- no active account, event, liquidity, exchange, position, or drawdown halt.

If any precondition is missing, stale, inconsistent, or unverifiable, record a
rejection and stop. Never infer approval from a green local component check.

## Review procedure

1. Record the immutable `report_id`, `snapshot_id`, calibration model version,
   backtest artifact id, and paper-ledger revision.
2. Compare the candidate economics, settlement currency, premium unit, expiry,
   strike, quantity, maximum loss, path-risk evidence, and kill conditions with
   the canonical report.
3. Confirm that recommended size and order instructions are absent while the
   effective mode is `research_only`.
4. Review account margin, existing positions, concentration, event windows,
   liquidity, and exchange status. Any HALT or unknown state is a rejection.
5. Record one decision: `APPROVE_FOR_PAPER_REVIEW`, `REJECT`, or
   `REQUEST_MORE_EVIDENCE`. This decision is advisory and cannot place an order.
6. Append the decision record to the operator-owned approval log and reconcile
   it against the paper ledger before the next review window.

## Required decision record

```json
{
  "schema_version": "manual_approval_record.v1",
  "decision": "REJECT",
  "report_id": "content-addressed report id",
  "snapshot_id": "content-addressed snapshot id",
  "candidate_id": "candidate id or null",
  "reviewer": "named human reviewer",
  "reviewed_at": "UTC timestamp",
  "reason_codes": ["FAIL_CLOSED_BY_DEFAULT"],
  "notes": "short evidence-based rationale"
}
```

The approval log must not contain API secrets, access tokens, refresh tokens,
or account credentials.

## Immediate stop conditions

- report, snapshot, model, backtest, or ledger ids do not match;
- data trust is not `trusted`, or any required feed is missing or stale;
- account evidence is missing, stale, authentication-failed, or not read-only;
- a candidate has unknown units, settlement semantics, or unbounded loss;
- any mode surface exposes a live order adapter or browser-controlled trade action;
- reconciliation detects an unexplained ledger difference.

## Rollback and escalation

On any inconsistency, retain the evidence, mark the decision `REJECT`, keep the
system in `RESEARCH_ONLY / NO_TRADE`, and escalate the exact artifact ids and
reason codes. Do not repair evidence in place and do not relax a gate to make a
candidate pass.
