# Public deployment suspension backlog item

> Backlog ID: `OPS-DEPLOY-001` · Status: `SUSPENDED` · Owner action required · Decision date: 2026-08-12

Public deployment remains explicitly suspended until the owner supplies the
external prerequisites that this repository cannot create or self-attest.
This decision does not weaken any fail-closed gate: daily capture, evidence
production, and public-bundle verification continue, while publication and
hosting cutover do not run.

## Second capture point

The prepared default route is the existing GitHub Actions cloud lane scheduled
by `.github/workflows/publish.yml` at `08:10 UTC`. It remains operationally
**suspended**, together with public deployment, until the private evidence-repo
push credential and notification endpoints below are configured. The workflow
definition stays enabled and fail-closed, but a scheduled run without those
owner inputs is not acceptance evidence for an active second capture point.

Do not re-open route selection in automation while this item is suspended.
After activation, close the DS-6 acceptance gate only after three consecutive
days show both local and cloud snapshots and no evidence-repository conflict.

## Reason code

`DEPLOY_SUSPENDED`

## Owner prerequisites to clear the suspension

- Provision the final owned HTTPS origin with live public DNS.
- Supply a non-interactive deployment identity bound to that exact target.
- Configure the private evidence repository sync surface and push credential.
- Configure the failure webhook and success heartbeat.
- Supply an independent `lensos_stale_monitor_attestation.v1` source for the
  owned origin.

## Acceptance contract

- Automation records `DEPLOY_SUSPENDED`; it does not claim or attempt a deploy.
- Capture and public-bundle verification continue while suspended.
- The Actions cloud lane is the prepared DS-6 route; activation remains blocked
  on an owner decision and credentials, and acceptance requires the three-day
  dual-capture observation above.
- Clearing the suspension requires an intentional repository change plus
  verified owner-controlled infrastructure inputs; placeholder values do not
  qualify.
- No action here enables paper, manual, or live trading.
