"""The historical browser case must exercise a valid interval, not its expiry."""

import shutil
import subprocess
from pathlib import Path


def test_historical_browser_clock_is_inside_the_actual_public_brief_window() -> None:
    script = """
import assert from 'node:assert/strict';
import { historicalAcceptanceClock } from './tools/public-browser-smoke.mjs';
const report = {
  publish_edition: { published_at: '2026-07-07T00:01:30Z', stale_after: '2026-07-09T00:01:00Z' },
  strategy_brief: { market: { as_of: '2026-07-07T00:01:00Z', expires_at: '2026-07-07T00:02:00Z' } },
};
const observed = historicalAcceptanceClock(report);
assert(observed > Date.parse(report.publish_edition.published_at));
assert(observed < Date.parse(report.strategy_brief.market.expires_at));
assert.equal(new Date(observed).toISOString(), '2026-07-07T00:01:45.000Z');
report.publish_edition.published_at = report.strategy_brief.market.expires_at;
assert.throws(() => historicalAcceptanceClock(report), /historical interval/);
report.publish_edition.published_at = 'not-a-clock';
assert.throws(() => historicalAcceptanceClock(report), /historical interval/);
"""
    result = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
