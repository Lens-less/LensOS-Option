# LensOS Option · Options Decision Research Platform

English · [中文](README.md) · [Documentation](docs/README.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.en.md)

[![CI](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml/badge.svg)](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Lens-less/LensOS-Option)](https://github.com/Lens-less/LensOS-Option/releases/latest)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

A decision research platform for BTC options. Start with public Deribit data,
understand market conditions, compare finite-risk structures, and inspect costs,
risk, and evidence. A one-screen brief presents up to three auditable cards or an
explicit no-trade result. Follow candidates, history, and provenance to preserve
a reproducible research record.

- Cards identify exact legs, expiry, minimum net credit, itemized costs, modeled loss budgets, and cancellation conditions.
- Cards remain at most `WATCH`: bounded expiry payoff does not establish an absolute loss cap including delivery fees.
- Historical and forecast rates appear only after their respective `VALIDATED` and `CALIBRATED` gates pass.
- Missing, stale, or invalid evidence blocks. No orders or position sizing; `execution_allowed=false` is permanent.

New here? Follow the [independent first-run guide](docs/guides/first-run-review.en.md); no accounts, keys, or funds are needed.
For reviewable maintenance history and the limits of current adoption evidence, see [maintainer work and public value](docs/maintainer-impact.md).

## Demo

The current source includes a three-step **offline learning tour**: choose an
example, understand its risk, and inspect the evidence. Drag a fictional normalized
expiry price to explore a linear payoff. Teaching values never enter research
JSON, generate a success rate, or acquire research eligibility.

“**查看真实快照**” (View real snapshot) opens the bundled redacted snapshot's evidence
page. Its actual blocking state and evaluation time remain visible; a historical
pass does not imply current eligibility. No market-service setup is needed to learn the interface.

![The v0.5.0 offline learning tour: choose a finite-risk structure](docs/assets/lensos-option-demo.png)

_The image shows the v0.5.0 installed package's offline learning page. Fictional
points explain structure; they do not represent current quotes or research eligibility._

## Quickstart

Requires Python 3.12+. Fetch and install the public source:

```powershell
git clone https://github.com/Lens-less/LensOS-Option.git
cd LensOS-Option
python -m pip install .
crypto-options-report demo
```

Open the printed
[offline learning tour URL](http://127.0.0.1:8000/index.html?view=demo). Once installed,
the demo needs no third-party runtime dependencies, Node.js, keys, network, or
captured output. It binds to `127.0.0.1`; `Ctrl+C` stops it and a busy port produces a clear error.

For an isolated wheel installation, see the [v0.5.0 upgrade guide](docs/releases/v0.5.0.md#安装与升级).
Published downloads are the assets actually listed on
[GitHub Releases](https://github.com/Lens-less/LensOS-Option/releases).

Continue with the [complete decision workflow](docs/guides/decision-workflow.en.md)
to capture public data, inspect blocking and expiry states, and save a reproducible
record. No account setup is required to follow that workflow.

## Verification

After setting up the development environment, run from the repository root:

```powershell
python tools/verify.py
```

This checks Python, Web, public and extension artifacts, then launches a browser
journey from the final wheel. An installed Chrome, Chromium, or Edge is required;
`BROWSER_PATH` selects it. `--quick` explicitly skips builds and the browser;
`--list` lists steps. See [Contributing](CONTRIBUTING.md#环境准备) for setup.

Reproduce a fixed research case without network access:

```powershell
python tools/reproduce_research.py --check
```

It reports actual trust, gates, reason codes, missing evidence, and reproducible
hashes. **A matching replay does not establish trusted data or strategy performance.**
See the [offline case guide](docs/guides/reproducible-case.md) for saving and comparing output.

## Guides

| Your task | Start here |
| --- | --- |
| Move from learning to public-data research and a saved record | [Complete decision workflow](docs/guides/decision-workflow.en.md) |
| Understand relative value, EV, risk, and sample size | [Research workflows](docs/guides/research-workflows.en.md) |
| Use the CLI, HTTP API, or Chrome panel | [Local tools](docs/guides/local-tools.en.md) · [API reference](docs/api-reference.md) |
| Reproduce the packaged case | [Inputs, gates, and replay](docs/guides/reproducible-case.md) |
| Configure capture, scheduling, and publication | [Operator guide](docs/guides/operator-guide.en.md) |
| Make a bounded first contribution | [Starter tasks](CONTRIBUTING.md#首次贡献任务) |
| Understand modules and trust boundaries | [Architecture](docs/architecture.md) · [Current design](DESIGN.md#1-current-product-contract) |
| Check release and security policies | [v0.5.0 notes](docs/releases/v0.5.0.md) · [Security](SECURITY.md) · [Code of conduct](CODE_OF_CONDUCT.md) |

## Operator Lane (Windows-only, optional)

Continuous capture and scheduling have moved to the [operator guide](docs/guides/operator-guide.en.md).
They are not newcomer prerequisites. Process success does not imply usable
validation observations; a public instance must check evidence availability separately.

## Version and public release

This source version is v0.5.0. See the [release notes](docs/releases/v0.5.0.md) for
changes and upgrades, and the [delivery record](docs/product/2026-09-08-open-source-decision-platform.md)
for this iteration's verification evidence. Published versions and assets are listed on
[GitHub Releases](https://github.com/Lens-less/LensOS-Option/releases).
Code uses [Apache-2.0](LICENSE); public data artifacts use [CC BY 4.0](LICENSE-DATA).
Research publication does not change the permanent `NO-GO` for execution.

## Safety Boundary

Missing evidence never becomes a pass; teaching values never become real research.
There is no live-order adapter, order template, or position sizing. Historical
protocols and model state machines do not imply sufficient real cohorts or calibrated rates.
Report vulnerabilities privately through [SECURITY.md](SECURITY.md).

<a id="one-screen-strategy-brief"></a>
<a id="two-ways-to-use-it"></a>
<a id="static-public-edition-and-publishing"></a>
<a id="core-concepts"></a>
<a id="current-status"></a>
<a id="usage"></a>
<a id="what-happens-if-you-combine-these"></a>
<a id="finding-candidates-with-edge"></a>
<a id="candidate-universe"></a>
<a id="was-this-strike-also-this-expensive-yesterday"></a>
<a id="what-can-this-ranking-predict"></a>
<a id="operator-capture-and-scheduled-task-windows-only"></a>
<a id="ev-is-negative---which-kind-of-negative"></a>
<a id="cli-internal-plumbing"></a>
<a id="http-api-and-evidence-console"></a>
<a id="chrome-research-companion-personal-local"></a>
<a id="production"></a>
<a id="development"></a>
<a id="project-map"></a>
<a id="license"></a>

Previous sections now live in the guides above: [research](docs/guides/research-workflows.en.md), [capture and deployment](docs/guides/operator-guide.en.md), [CLI / API / extension](docs/guides/local-tools.en.md), and [development](CONTRIBUTING.md).
