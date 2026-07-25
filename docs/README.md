# Documentation map

This repository separates current product truth from active governance state and
historical evidence. A document being present does not automatically make it a
current acceptance contract.

## Current product truth

- [`../DESIGN.md`](../DESIGN.md) — product and interaction contract for the
  Evidence Console and Chrome companion.
- [`product/2026-07-25-cleanup-and-chrome-extension-plan.md`](product/2026-07-25-cleanup-and-chrome-extension-plan.md)
  — accepted local-extension migration and cleanup decisions.
- [`product/2026-07-25-local-chrome-companion-acceptance.md`](product/2026-07-25-local-chrome-companion-acceptance.md)
  — executable acceptance boundary for the personal unpacked Chrome companion.
- [`research/deribit-options-intelligence-platform-prd.md`](research/deribit-options-intelligence-platform-prd.md)
  — current platform north star.
- [`research/data-trustworthiness-prd.md`](research/data-trustworthiness-prd.md)
  — current evidence-quality contract.
- [`operations/production-runbook.md`](operations/production-runbook.md) —
  supported local and production runtime procedures.

## Active governance and audit state

`automation/` and `../issues/` contain active repository coordination state,
immutable migration evidence, and issue packets. They are not shipped in the
Python package or container, but they must remain byte-stable while the
coordination aggregate is active.

The current acceptance summary is
[`automation/project-acceptance-report.md`](automation/project-acceptance-report.md).
Individual handoffs and verification records are supporting evidence, not
product requirements.

## Historical material

Completed investigations, superseded plans, and point-in-time verification
reports should move under [`archive/`](archive/README.md) only after active
documents and hash-based governance records no longer reference their original
paths.

The root-level `crypto_options_short_call_system_*` documents are legacy inputs.
They remain in place temporarily because active automation packets still refer
to those paths; they do not supersede the current platform PRD.
