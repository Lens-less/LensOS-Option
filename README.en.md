# LensOS Option · Options Decision Desk

English · [中文](README.md) · [User guide](docs/decision-desk.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.en.md)

[![CI](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml/badge.svg)](https://github.com/Lens-less/LensOS-Option/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Lens-less/LensOS-Option)](https://github.com/Lens-less/LensOS-Option/releases/latest)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

A local research desk for Deribit BTC / ETH **linear USDC options**. Discover
candidates, compare them under shared assumptions, then retain an observation
for recheck. Every result identifies exact legs, bid/ask quotes, units, times,
and screening reasons.

- **Discover:** filter direction, expiry, and structure; inspect coverage, comparable candidates, and exclusions.
- **Compare / Decide:** choose 2–3 candidates and compare payoff, costs, and boundaries under the same price, time, and IV scenario.
- **Observe:** retain exact legs and assumptions in this browser, then recheck the same structure against new data.

Generation and ranking are deterministic, not AI predictions or proof of positive
EV. Expiry payoff, modeled stress, and actual probabilities stay separate. A
raw option payoff bound excludes trading and dynamic delivery fees; it is not a total loss cap.
No accounts, orders, or position-size recommendations; `execution_allowed=false`
is permanent.

## Demo

Default startup provides a clearly labeled **offline synthetic demo**. Fictional
BTC / ETH USDC contracts and quotes let you try discovery, comparison, and
observation. They are not current Deribit data, historical results, or trusted
evidence. The old learning tour and `research_report.v1` evidence interface remain
available through `?view=legacy`; the new contract is `decision_desk.v1`.

## Quickstart

Requires Python 3.12+. Fetch and install the public source:

```powershell
git clone https://github.com/Lens-less/LensOS-Option.git
cd LensOS-Option
python -m pip install .
crypto-options-report start
```

The [local desk](http://127.0.0.1:8000/index.html) opens automatically; the terminal
also prints its address. The offline demo needs no Node.js, network, account, or
keys. Python has zero third-party runtime dependencies. The server binds only
to `127.0.0.1`; `Ctrl+C` stops it. Add `--port 8001` if occupied, or
`--no-open-browser` to open the URL yourself.

Choose “读取公开行情” in the desk to switch; only that step requires a network,
with no server restart. Alternatively, stop the running service and start directly
in public-data mode:

```powershell
crypto-options-report start --current
```

Network access is required. A full instrument registry and chain summary support
the scan; only a bounded shortlist receives deeper bid/ask quotes. Scan coverage
and deep-quote coverage are reported separately. Current mode identifies the
source, not a guarantee of comparable structures or validated edge. Valid
snapshots may be reused; check the actual data cutoff after refresh.

Replay an existing legacy-report capture through the compatibility interface:

```powershell
crypto-options-report start --snapshot artifacts/snapshots/btc-chain.json
```

`--snapshot` opens the old report interface and reads its original market-snapshot
format. It is not a historical mode for the new desk and does not read
`desk_market.v1`. Refresh only rereads local inputs; it cannot collect current
data or promote legacy gates. `--current` and `--snapshot` are mutually exclusive.
Existing `crypto-options-report demo`, capture CLI, and HTTP API remain compatible;
see the [legacy workflow](docs/guides/decision-workflow.en.md).

Follow the [desk guide](docs/decision-desk.md) for discovery, shared scenarios,
and exact-leg observations. Browser observations do not monitor automatically
or record trading P&L; copied research does not create an order. Current usage
is local. No hosted service address is provided or promised here.

## Verification

After setting up development dependencies, run from the repository root:

```powershell
python tools/verify.py
```

It checks Python, Web, static and extension builds, and the installed browser
journey. An installed Chrome, Chromium, or Edge is required; `BROWSER_PATH`
selects it. `--quick` skips builds and browser checks; `--list` lists steps.
See [Contributing](CONTRIBUTING.md#环境准备) for setup and build synchronization.
Local success does not replace platform CI or evidence about live markets.

The old report's fixed offline reproduction remains available:

```powershell
python tools/reproduce_research.py --check
```

It checks legacy inputs, gates, and identities. It does not validate the new
desk's market edge or demonstrate profitability.

## Guides And Boundaries

| Your task | Start here |
| --- | --- |
| Complete Discover → Compare / Decide → Observe | [Desk guide](docs/decision-desk.md) |
| Understand the new contract and compatibility | [Current design](DESIGN.md#1-current-product-contract) |
| Inspect legacy evidence and model gates | [Legacy workflow](docs/guides/decision-workflow.en.md) · [Offline case](docs/guides/reproducible-case.md) |
| Use existing capture CLI, API, and extension | [Local tools](docs/guides/local-tools.en.md) · [API reference](docs/api-reference.md) |
| Develop and verify changes | [Contributing](CONTRIBUTING.md) · [Architecture](docs/architecture.md) |
| Check existing releases and security policy | [Release notes](docs/releases/v0.5.0.md) · [Security](SECURITY.md) |

This README describes current source; published assets are those actually listed
on [GitHub Releases](https://github.com/Lens-less/LensOS-Option/releases). Code
uses [Apache-2.0](LICENSE). The repository's [data license](LICENSE-DATA) does not
replace provider permissions. Deribit limits market and derived data to personal
use; other publication or forwarding needs prior written approval. Public code
does not grant data redistribution rights. [Deribit Terms §2.10](https://support.deribit.com/hc/en-us/articles/25944532191645-Deribit-Exchange-Membership-Terms-Deribit-FZE)

Comparable candidates in `decision_desk.v1` do not promote legacy
`strategy_brief.v1`, `EntryAdmissionDecision`, historical `VALIDATED`, or forecast
`CALIBRATED` gates. Missing, stale, or crossed quotes cannot produce current
comparability. No mixed inverse payoff assumptions, account data, order templates,
live execution, or paper/manual execution controls. Report vulnerabilities
privately through [SECURITY.md](SECURITY.md).

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
