# Public contract v1 compatibility fixtures

These are transport and schema regression examples, not current market evidence
or model promotion artifacts. `ready` means the available structural branch;
it does not mean execution readiness. Execution remains disabled.

- `ready.json`: published projections produced from the existing deterministic
  publication fixture; the independent `StrategyBrief` member reuses the existing
  strategy brief golden fixture so nonempty cards, legs, and historical scope
  remain represented. The report retains two real VRP observations to keep this
  shared transport fixture small. Full series are tested through publication.
- `missing.json`: report produced by `build_analysis_record` without a market
  snapshot, plus explicit nullable public summary/health and empty artifact
  branches.
- `degraded.json`: report produced from the same snapshot with a clock two
  minutes later, so the market quality gate blocks stale data.
- `mutations.json`: deliberate failures applied to `ready.json`. A path is an
  array of property names/list indices, with either `set` or `delete`. `common`
  applies to shared consumed fields; `public-only` applies to the stricter
publication allowlist. Internal reports may carry additional private fields.

Consumers validate each top-level member against its equally named component in
the fixed OpenAPI contract. The current fixtures must remain accepted when the
same API version is maintained; adding a new state does not regenerate schemas
from that state's values. Schema edits require explicit compatibility review.

`crypto_options_report/resources/public-openapi-v1.json` is the checked-in
OpenAPI snapshot, included in the wheel. Its equality regression detects schema
drift even when a new sample happens to pass. The authored field definitions are
`public_schema.py` and `public_artifact_schema.py`; `public_api_contract.py`
contains the route map and the supported-keyword validator. Do not update the
snapshot merely to make a failing compatibility test pass. A change to required
members, nullability, enums, or closed object fields must account for existing
consumers and may require a new contract version.

The stdlib validator intentionally supports only the keywords used by this
contract. It checks JSON shape, finite numbers and the declared date formats;
domain freshness, projection privacy, evidence promotion and release gates
remain separate checks. A shape-valid fixture does not pass those other gates
automatically.
