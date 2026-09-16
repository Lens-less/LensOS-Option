# Maintainer work and public value

[Project](../README.en.md) · [中文首页](../README.md) · [Independent first run](guides/first-run-review.en.md)

**Evidence snapshot: 2026-09-16.** LensOS Option is an early-stage, Apache-2.0
BTC options research project maintained by `Lens-less`. This document separates
shipped software, maintenance evidence, intended usefulness, and unverified adoption.
It is not a claim of funding, endorsement, validated trading performance, or broad adoption.

## Who the software is for

Independent researchers and developers need to distinguish a plausible options
idea from a conclusion supported by usable data. This project makes that distinction
inspectable: teaching examples stay separate from research, stale or invalid evidence
blocks eligibility, and an offline case can be replayed with an explicit clock.

The potential reusable value is in input provenance, deterministic replay, visible
failure reasons, and consistent evidence contracts across Python, the Web UI, and a
Chrome side panel. These are intended benefits, not claims of downstream adoption.
The software does not place orders or recommend position sizes.

## Shipped, publicly inspectable evidence

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| [v0.5.0 release](https://github.com/Lens-less/LensOS-Option/releases/tag/v0.5.0), published 2026-09-08 | Published Python wheel, Chrome extension ZIP, and checksums | Unique users, monthly downloads, or strategy profitability |
| [Release delivery PR #17](https://github.com/Lens-less/LensOS-Option/pull/17) | A reviewable record of product, contract, packaging, and verification work | Independent community demand or independent third-party review |
| [Delivery follow-up PR #18](https://github.com/Lens-less/LensOS-Option/pull/18) | Release verification, CJK browser rendering work, and documented runner limitations | A security certification |
| [Main-branch CI for the delivery follow-up](https://github.com/Lens-less/LensOS-Option/actions/runs/34182899217) | A successful recorded CI run for that revision | Successful verification of every later revision |
| [CI configuration](../.github/workflows/ci.yml) | Linux/Windows and Python 3.12–3.14 coverage, Web, package, extension, and container checks | That every supported environment has independent users |
| [Fixed-input replay](guides/reproducible-case.md) | Repeatability for the same build, inputs, and evaluation clock | Trusted market data, calibrated forecasts, or authorization to trade |

See the [versioned delivery record](product/2026-09-08-open-source-decision-platform.md)
for the historical verification counts and their platform-specific qualifications.
Those counts are not new test results from this document's publication.

## Adoption: report what is known

The [repository API](https://api.github.com/repos/Lens-less/LensOS-Option) reported
**0 stars and 0 forks** at this snapshot. There is no verified monthly-download,
monthly-active-user, or independent-user figure asserted here. Release asset counters
are cumulative per asset, may include maintainer verification downloads, and must not
be presented as unique or monthly users. Source installations are not measured by
those counters either.

A [first-run guide](guides/first-run-review.en.md) and an opt-in
[first-run feedback form](https://github.com/Lens-less/LensOS-Option/issues/new?template=first_run.yml)
provide a path to collect real experience. Their existence is not a completed user study.
Maintainer runs, CI runs, bot dependency PRs, and AI-assisted checks must remain
separate from independent-user reports. Failure reports are as useful as successes.

When reporting later adoption, record the date range, measurement definition, source,
and limitations. Link voluntarily public reports rather than copying personal data.
Do not pay for stars, require positive reviews, create fake users, or infer an
independent review merely from an issue or PR existing.

## Current maintainer responsibilities

The visible responsibilities include reviewing changes and dependency updates,
maintaining Python/Web/extension contracts, reproducing data-boundary failures,
checking cross-platform packaging and browser behavior, updating bilingual guides,
and releasing verifiable artifacts. [Contributing](../CONTRIBUTING.md) and
[Security](../SECURITY.md) define the existing contribution and vulnerability paths.

## Proposed next six months of maintenance

This is a proposed allocation of work, not completed delivery or a promise of funding.

| Work area | Concrete acceptance evidence |
| --- | --- |
| Newcomer reliability | Voluntary first-run reports; each reproduced failure linked to a fix or a documented limitation; follow-up on the tested revision |
| Evidence and contract regression | Reviewed tests for missing, stale, malformed, or incompatible evidence; unchanged execution prohibition |
| Release and security maintenance | Dependency review, package/install/browser checks on the release revision, and authorized review of local API, snapshot authentication, extension permissions, and dependency boundaries |

Codex/API support would be used for these repository maintenance tasks, with human
review and CI, not for trading execution, return promises, unrelated commercial work,
or credential sharing. Security review would cover only authorized code in this
public repository. Private recovery captures, account material, and third-party
systems are outside that scope. No new runtime service or credential is required by
this documentation work.
