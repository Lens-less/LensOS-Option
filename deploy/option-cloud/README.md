# LensOS Option private interaction acceptance version

Upstream: https://github.com/Lens-less/LensOS-Option/pull/30
Pinned engine source: `30102e5d99994346a48d99e97972fd4266cf106b`. GitHub comparison confirms the final upstream `15f3f4e792f060d788326e5d52188a26c7e24301` changes only a transport test; runtime source is identical.

This separate Site is a synthetic replay for online interaction acceptance. It does not run the CPython HTTP backend. It has no live market/account/trading requests, no proxy endpoint and no financial execution.

- Original Python source is retained under `original_python/` and unchanged. `scripts/generate-preview.py` produces frozen fixtures directly with `demo_desk_snapshot`, `build_desk`, and `compare_candidates` from that source.
- Frozen evaluation clock: 2026-10-01 15:00 UTC. Source timestamps, analysis identities, candidate identities and original quote deadlines are retained. A preview-only replay clock permits interacting with the archived sample; this is not a current quotation qualification.
- BTC and ETH each expose three fixed sample candidates and four discrete precomputed scenarios. All 2- and 3-way selections have an exact original engine output. Unsupported identities/scenarios/filter changes reject.
- No pricing or fee math has been ported to JavaScript. Adapter reads frozen output only.
- Private browser-local observations use a separate preview storage key. Save/reload/notes remain real interactions. Review explicitly returns unavailable with a no-live-backend reason.
- The original Python product and main branch are unchanged. A buildable copy of this deployment lives under `deploy/option-cloud/` on the dedicated `deploy/option-cloud-acceptance` GitHub branch. The Site repository remains the canonical publication source.

Validation: `npm run lint`; `npm test` (9 targeted interaction and safety tests); `npm run build`; unchanged original Python source; all 32 regenerated comparisons reproduce fixture SHA-256 `6c8a937882f1da466fecebe0a5f925deb0339bac027f8b6cb35b999c0cb99ee4`. Browser-localhost inspection was unavailable in dot's cloud browser (`ERR_BLOCKED_BY_CLIENT`), so no completed real-browser visual QA is claimed for this adaptation.

Deployment is owner-private native Sites static hosting. No recurring updates were requested or scheduled.

Acceptance polish: active preset clicks retain the loaded comparison; structure-filter counts match the visible subset; timestamps include the year; entry cash is distinguished from profit; local observations reject live/current-market relabeling; storage failure preserves the current comparison and manual-copy fallback.

GitHub deployment checkout: run `npm ci && npm run fixtures && npm test && npm run build` in this directory. The generated fixture JSON is reproduced by the unchanged retained Python source; it is not separately committed in this mirror.
