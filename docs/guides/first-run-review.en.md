# Independent first run and feedback

[中文](first-run-review.md) · [Project](../../README.en.md) · [Maintainer evidence](../maintainer-impact.md)

Check whether a newcomer can install the software, distinguish teaching from research,
and describe a success or failure without help. **No exchange account, wallet, API key,
funds, or paid service is needed.** Download/setup requires network access; the installed
demo and fixed-case replay do not. Do not deploy a public service or enable execution.

## A. Try the released wheel

Download `crypto_options_research_console-0.5.0-py3-none-any.whl` and `SHA256SUMS`
from the [repository's v0.5.0 release](https://github.com/Lens-less/LensOS-Option/releases/tag/v0.5.0)
into a new directory. This is not a PyPI installation. You need Python 3.12+ and a
browser, but not source code, Node, or the Chrome extension. The current CI matrix
covers Windows/Linux with Python 3.12–3.14; macOS is not covered by that matrix.

In that download directory, compare the wheel's SHA-256 with its line in `SHA256SUMS`.
Stop if they differ. Confirm your chosen Python is at least 3.12 before continuing.

**Windows PowerShell:**

```powershell
python --version
Get-FileHash -Algorithm SHA256 .\crypto_options_research_console-0.5.0-py3-none-any.whl
Get-Content .\SHA256SUMS
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --no-deps .\crypto_options_research_console-0.5.0-py3-none-any.whl
.\.venv\Scripts\python.exe -m crypto_options_report.cli demo
```

**Linux/macOS shell:**

```bash
python3 --version
# On macOS, use shasum -a 256 instead of sha256sum if needed.
sha256sum ./crypto_options_research_console-0.5.0-py3-none-any.whl
cat ./SHA256SUMS
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps ./crypto_options_research_console-0.5.0-py3-none-any.whl
.venv/bin/python -m crypto_options_report.cli demo
```

Virtual-environment activation is not needed. Open the local URL printed by the
command. Complete the three steps: choose an example, explore risk, and inspect
evidence. Move the teaching price, then choose **查看真实快照** (View real snapshot).
Fictional points are not current quotes; the research snapshot keeps its own timestamp
and evidence limitations. Press `Ctrl+C` to stop. Keep the service on loopback.

## B. Optionally replay the fixed research case

This path needs Git and the source-only `tools/reproduce_research.py`; the script is
not a command shipped in the wheel. Use a separate directory and environment so
release and development builds are not mixed:

```bash
git clone --branch v0.5.0 --depth 1 https://github.com/Lens-less/LensOS-Option.git LensOS-Option-v0.5.0
cd LensOS-Option-v0.5.0
git rev-parse HEAD
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps .
.\.venv\Scripts\python.exe tools/reproduce_research.py --check
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --no-deps .
.venv/bin/python tools/reproduce_research.py --check
```

Source installation may obtain build tools from the package index; offline replay
does not imply offline first-time setup. Expect `repeatability=PASS` together with
`trust=untrusted`, `action=NO_TRADE`, `admission=BLOCKED_BY_EVIDENCE`, and
`execution_allowed=false`. The blocked result is intentional, not a request for
credentials or permission to trade. Repeatability is not profitability or data trust.
Record unexpected results rather than changing inputs to manufacture a pass.
See the [fixed-case explanation](reproducible-case.md).

## Report only what you actually tried

Use the [first-run feedback form](https://github.com/Lens-less/LensOS-Option/issues/new?template=first_run.yml).
Include the version/commit, OS and Python versions, chosen path, exact failing step,
and expected behavior. Mark unattempted steps as not run. Successful, unsuccessful,
and confusing experiences are all useful. Stars, positive reviews, and trading are
not prerequisites. Do not present someone else's output as your own run.

Paste only the minimum sanitized error excerpt. Never upload raw logs, private
snapshots, account details, email addresses, wallet addresses, credentials, cookies,
sessions, organization IDs, or screenshots containing them. Remove local usernames
and absolute paths. Use [private security reporting](../../SECURITY.md) for vulnerabilities.

## Common blockers

| Symptom | Next step |
| --- | --- |
| Python is older than 3.12 | Select a newer installed interpreter before making the environment |
| A command cannot be found | Use the explicit environment Python and `-m crypto_options_report.cli`, not global PATH |
| The local port is busy | Stop your own previous instance and retry; do not kill unidentified processes |
| Linux lacks venv support | Follow your distribution's instructions for the matching Python venv package |
| Evidence is insufficient or `NO_TRADE` appears | Inspect the snapshot time and reasons; this is expected for the fixed case |
| Identical-input replays differ or the page fails | Report the revision, steps, and sanitized excerpt; do not weaken checks |

Maintainers can connect a reproduced report to a fix PR or documented limitation.
An issue is not automatically a unique or independent user.
