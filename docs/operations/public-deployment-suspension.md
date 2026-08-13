# Public deployment suspension backlog item

> Backlog ID: `OPS-DEPLOY-001` · Public deployment: `SUSPENDED` · Second-capture route: `SELECTED / NOT_ACCEPTED` · Decision date: 2026-08-13

Public site deployment remains explicitly suspended until the owner supplies
the external publication prerequisites. This does not suspend daily capture or
public-bundle verification. Capture-lane admission and site-publication
admission are separate fail-closed gates.

## Second capture point

The selected DS-6 route is the GitHub Actions Windows lane in
`.github/workflows/publish.yml`, scheduled at `08:10 UTC` and identified as
`github_actions_0810_utc`. Route selection is closed; do not reopen it in
automation.

The workflow currently runs best-effort capture, but the lane is **not accepted
or operationally durable** until all capture prerequisites are present:

- `LENSOS_EVIDENCE_REPO_SYNC_ENABLED=true`
- `LENSOS_EVIDENCE_REPO_SLUG` and `LENSOS_EVIDENCE_REPO_PUSH_TOKEN`
- valid public-HTTPS `CAPTURE_FAILURE_WEBHOOK_URL`
- valid public-HTTPS `CAPTURE_SUCCESS_HEARTBEAT_URL`

Missing or invalid capture prerequisites still allow a capture attempt and a
private-repository recovery artifact, then make the workflow fail. A suspended
site deployment does not bypass this capture-lane gate. DNS, hosting identity,
and the external `stale_after` monitor are not prerequisites for capture-lane
acceptance.

After credentials are configured, close DS-6 only when the private evidence
repository contains three consecutive UTC dates with usable immutable receipts
from both `local_windows_scheduler` and `github_actions_0810_utc`, with every
referenced snapshot hash verified. The path must be the clean top-level of the
private evidence Git repository, on a named branch already pushed byte-for-byte
to `origin`; a loose or merely local directory cannot pass:

```powershell
python tools/check-dual-capture-acceptance.py `
  --evidence-root C:\path\to\LensOS-Option-Evidence `
  --required-origin local_windows_scheduler `
  --required-origin github_actions_0810_utc `
  --days 3
```

Exit `0` is accepted, `10` is still collecting, and `11` means invalid or
conflicting evidence.

## Public deployment gate

Reason code: `DEPLOY_SUSPENDED`.

Clearing public deployment additionally requires:

- a final owned HTTPS origin with live public DNS;
- a non-interactive deployment identity bound to that target; and
- a fresh independent `lensos_stale_monitor_attestation.v1` proof.

The repository may be made public while site deployment remains suspended;
the open-source tool and the later hosted research edition are separate
decisions. Repository cutover must follow
[`public-release-cutover.md`](public-release-cutover.md).

## Raw Actions artifact boundary

The `captured-evidence` recovery artifact is permitted only while this product
repository is private. Before changing repository visibility, the owner must
inventory and remove or privately archive historical workflow artifacts/runs.
The workflow itself permits this recovery upload only while GitHub reports the
repository visibility as `private`; a public repository skips it. Raw capture
is not implicitly a CC BY public release.

## Acceptance contract

- Automation records `DEPLOY_SUSPENDED`; it never claims a site deploy.
- Capture and public-bundle verification continue while deployment is suspended.
- Capture-lane admission requires durable sync plus both notification surfaces.
- Site origin and stale-monitor proof are evaluated only for active publication.
- Placeholder or merely non-empty URLs do not qualify.
- No action here enables paper, manual, testnet, or live trading.
