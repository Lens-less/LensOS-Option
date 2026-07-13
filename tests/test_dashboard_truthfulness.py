import json
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from crypto_options_report.api import dashboard_page_html


class _DashboardMarkupParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.hidden_ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if not element_id:
            return
        self.ids.append(element_id)
        if "hidden" in attributes:
            self.hidden_ids.append(element_id)


class DashboardTruthfulnessTests(unittest.TestCase):
    def test_local_pass_labels_never_imply_trade_authorization(self):
        html = dashboard_page_html()

        self.assertIn("Regime 研究上限（非交易授权）", html)
        self.assertIn('"allow_new": "局部门禁通过"', html)
        self.assertNotIn('"allow_new": "允许新交易"', html)
        self.assertIn("scrollbar-width: none", html)
        self.assertIn(".nav::-webkit-scrollbar", html)

    def test_offline_fallback_has_page_truth_state_without_plausible_metrics(self):
        html = dashboard_page_html()

        for selector in (
            'id="market-data-truth-state"',
            'id="report-generated-time"',
            'id="market-as-of-time"',
            'id="market-data-age"',
            'id="market-data-source"',
            'id="market-data-trust"',
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, html)
        self.assertIn("NOT CURRENT MARKET DATA", html)

        fallback = re.search(
            r"const FALLBACK_REPORT = \{(?P<body>.*?)\n    \};",
            html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(fallback)
        fallback_body = fallback.group("body").lower()
        for forbidden in (
            "calmar",
            'status: "calibrated"',
            "ev_candidate_scanner",
            "ranked_candidates",
            "walk_forward_calibration",
            "walk_forward_fixture",
            "system_comparison",
            "backtest_comparison",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, fallback_body)

    def test_offline_render_distinguishes_unavailable_evidence_from_zero_results(self):
        state = self._render_dashboard(mode="offline")

        self.assertFalse(state["truth"]["hidden"])
        self.assertEqual("offline", state["truth"]["dataset"]["state"])
        self.assertEqual("NOT CURRENT MARKET DATA", state["truthLabel"]["text"])
        self.assertIn("报告 API", state["truthDetail"]["text"])
        self.assertEqual("未生成", state["reportTime"]["text"])
        self.assertEqual("无当前市场时间", state["marketTime"]["text"])
        self.assertEqual("不可用", state["marketAge"]["text"])
        self.assertEqual("未配置", state["marketSource"]["text"])
        self.assertEqual("不可信", state["marketTrust"]["text"])
        self.assertEqual("未评估", state["candidateCount"]["text"])
        self.assertIn("无可信市场数据", state["candidateEmpty"]["text"])
        self.assertEqual("未运行", state["calibration"]["text"])
        self.assertEqual("无可信证据", state["modelVersion"]["text"])
        self.assertEqual("未配置", state["matrixAccount"]["text"])
        self.assertIn("非系统错误", state["matrixAccountNote"]["text"])
        self.assertEqual([], state["consoleErrors"])

    def test_trusted_report_separates_report_and_market_times_and_zero_candidates(self):
        report = self._report()

        state = self._render_dashboard(mode="live", report=report)

        self.assertTrue(state["truth"]["hidden"])
        self.assertEqual("current-trusted", state["truth"]["dataset"]["state"])
        self.assertEqual("CURRENT TRUSTED MARKET DATA", state["truthLabel"]["text"])
        self.assertEqual("2026-07-12T12:34:56Z", state["reportTime"]["text"])
        self.assertEqual("2026-07-12T12:34:40Z", state["marketTime"]["text"])
        self.assertEqual("16 秒", state["marketAge"]["text"])
        self.assertEqual("deribit_public", state["marketSource"]["text"])
        self.assertEqual("可信", state["marketTrust"]["text"])
        self.assertEqual("0", state["candidateCount"]["text"])
        self.assertIn("0 个候选", state["candidateEmpty"]["text"])
        self.assertIn("扫描结果", state["candidateEmpty"]["text"])
        self.assertNotIn("无可信市场数据", state["candidateEmpty"]["text"])
        self.assertEqual([], state["consoleErrors"])

    def test_fresh_public_data_with_pending_trust_keeps_live_scanner_truth(self):
        report = self._report()
        report["data_trust"] = {
            "verdict": "untrusted",
            "source_class": "live",
            "reason_codes": ["LIVE_TRUST_PROMOTION_PENDING"],
        }
        report["data_status"]["collection_scope"] = {
            "scope": "research_sample",
            "upstream_instrument_count": 58,
            "selected_instrument_count": 20,
            "coverage_ratio": 0.3448,
            "selection_policy": {"name": "research_candidate_stratified_v1"},
        }
        report["ev_candidate_scanner"] = {
            "status": "blocked",
            "reason_code": "ACCOUNT_SNAPSHOT_NOT_AVAILABLE",
            "score_status": "UNCALIBRATED_RESEARCH_ONLY",
            "recommended_size_allowed": False,
            "trade_instruction_allowed": False,
            "paper_manual_candidates_allowed": False,
            "ranked_candidates": [],
            "summary": {"candidates_scanned": 0},
        }

        state = self._render_dashboard(mode="live", report=report)

        self.assertFalse(state["truth"]["hidden"])
        self.assertEqual("current-public-trust-pending", state["truth"]["dataset"]["state"])
        self.assertEqual("CURRENT PUBLIC DATA · TRUST PENDING", state["truthLabel"]["text"])
        self.assertIn("市场数据当前且质量通过", state["truthDetail"]["text"])
        self.assertIn("共享信任裁决待完成", state["truthDetail"]["text"])
        self.assertEqual("0", state["candidateCount"]["text"])
        self.assertIn("已阻断", state["candidateMeta"]["text"])
        self.assertIn("ACCOUNT_SNAPSHOT_NOT_AVAILABLE", state["candidateMeta"]["text"])
        self.assertIn("0 个候选", state["candidateEmpty"]["text"])
        self.assertIn("ACCOUNT_SNAPSHOT_NOT_AVAILABLE", state["candidateEmpty"]["text"])
        self.assertNotIn("未评估", state["candidateEmpty"]["text"])
        self.assertEqual("上游 58 → 入选 20", state["collectionCounts"]["text"])
        self.assertIn("覆盖率 34.48%", state["collectionCoverage"]["text"])
        self.assertIn("research_sample", state["collectionCoverage"]["text"])
        self.assertEqual("RESEARCH_ONLY", state["action"]["text"])
        self.assertNotIn("允许", self._all_text(state["modeGateList"]))
        self.assertEqual([], state["consoleErrors"])

    def test_unaligned_backtest_hides_plausible_metrics(self):
        report = self._report()
        report["backtest_status"] = {
            "status": "not_aligned",
            "aligned": False,
            "reason_code": "BACKTEST_ALIGNMENT_PENDING",
        }
        report["full_system_surface"]["backtest_comparison"] = [
            {"variant": "full_system", "calmar": 9.99},
        ]

        state = self._render_dashboard(mode="live", report=report)

        self.assertTrue(state["backtestBars"]["hidden"])
        self.assertEqual([], state["backtestBars"]["children"])
        self.assertFalse(state["backtestEmpty"]["hidden"])
        self.assertIn("证据不足", state["backtestEmpty"]["text"])
        self.assertNotIn("Calmar", self._all_text(state["backtestBars"]))
        self.assertEqual([], state["consoleErrors"])

    def test_aligned_backtest_is_the_only_state_that_renders_comparison(self):
        report = self._report()
        report["backtest_status"] = {
            "status": "aligned",
            "aligned": True,
            "reason_code": None,
        }
        report["full_system_surface"]["backtest_comparison"] = [
            {"variant": "baseline", "calmar": 0.48},
            {"variant": "full_system", "calmar": 0.92},
        ]

        state = self._render_dashboard(mode="live", report=report)

        self.assertFalse(state["backtestBars"]["hidden"])
        self.assertEqual(2, len(state["backtestBars"]["children"]))
        self.assertTrue(state["backtestEmpty"]["hidden"])
        self.assertIn("0.92 Calmar", self._all_text(state["backtestBars"]))
        self.assertEqual([], state["consoleErrors"])

    def test_readiness_renders_evidence_release_and_reason_instead_of_missing(self):
        report = self._report()
        report["full_system_surface"]["release_readiness"] = {
            "status": "NO-GO",
            "paper_mode_allowed": False,
            "prerequisites": [
                {
                    "name": "data_quality",
                    "satisfied": False,
                    "evidence_state": "verified_local",
                    "release_state": "awaiting_external",
                    "reason": "等待外部生产证据",
                },
                {
                    "name": "paper_ledger_reconciliation",
                    "satisfied": False,
                    "evidence_state": "not_run",
                    "release_state": "awaiting_calendar",
                    "reason_codes": ["MISSING_30_60_DAY_RECONCILIATION"],
                },
            ],
        }

        state = self._render_dashboard(mode="live", report=report)

        rows = state["readinessList"]["children"]
        self.assertEqual(2, len(rows))
        self.assertEqual("verified_local", rows[0]["dataset"]["evidenceState"])
        self.assertEqual("awaiting_external", rows[0]["dataset"]["releaseState"])
        self.assertIn("本地已验证", self._all_text(rows[0]))
        self.assertIn("等待外部证据", self._all_text(rows[0]))
        self.assertIn("等待外部生产证据", self._all_text(rows[0]))
        self.assertNotIn("缺失", self._all_text(state["readinessList"]))
        self.assertEqual("2 项发布阻断", state["missingCount"]["text"])
        self.assertEqual([], state["consoleErrors"])

    def test_truth_metadata_stacks_on_mobile(self):
        html = dashboard_page_html()

        mobile_rule = re.search(
            r"@media \(max-width: 620px\) \{(?P<body>.*?)\n\s*\}",
            html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(mobile_rule)
        self.assertIsNotNone(re.search(
            r"@media \(max-width: 620px\).*?\.truth-meta-grid\s*\{\s*grid-template-columns:\s*1fr;",
            html,
            flags=re.DOTALL,
        ))

    def test_inline_dashboard_script_passes_node_syntax_check(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for dashboard syntax verification")
        html = dashboard_page_html()
        scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
        self.assertTrue(scripts)

        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dashboard-inline.js"
            script_path.write_text(scripts[-1], encoding="utf-8")
            completed = subprocess.run(
                [node, "--check", str(script_path)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)

    @staticmethod
    def _all_text(node):
        return " ".join(
            [node.get("text", "")]
            + [DashboardTruthfulnessTests._all_text(child) for child in node.get("children", [])]
        )

    @staticmethod
    def _report():
        return {
            "generated_at": "2026-07-12T12:34:56Z",
            "mode": "research_only",
            "effective_mode": "research_only",
            "action": "RESEARCH_ONLY",
            "risk_state": "HALT",
            "reason_codes": [],
            "mode_gate": {},
            "data_trust": {
                "verdict": "trusted",
                "source_class": "live",
                "reason_codes": [],
            },
            "data_status": {
                "status": "validated",
                "source": "deribit_public",
                "validated": True,
                "snapshot_captured_at": "2026-07-12T12:34:40Z",
                "market_data_age_sec": 16,
            },
            "account_status": {
                "status": "not_configured",
                "source": "not_configured",
                "trade_gate": "NO_TRADE",
                "margin_light": "HALT",
            },
            "vol_surface_status": {"status": "not_run", "summary": {}, "expiries": []},
            "permission_state": {"status": "blocked", "sell_permission": 0},
            "portfolio_risk": {"final_action": "halt_system", "signals": [], "summary": {}},
            "ev_candidate_scanner": {
                "status": "evaluated",
                "score_status": "uncalibrated",
                "ranked_candidates": [],
                "summary": {},
            },
            "calibration_status": {"status": "not_run", "model_version": None},
            "backtest_status": {
                "status": "not_run",
                "aligned": False,
                "reason_code": "BACKTEST_NOT_RUN",
            },
            "full_system_surface": {
                "release_readiness": {
                    "status": "NO-GO",
                    "paper_mode_allowed": False,
                    "prerequisites": [],
                },
            },
        }

    def _render_dashboard(self, *, mode, report=None):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for dashboard behavior verification")

        html = dashboard_page_html()
        scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
        self.assertTrue(scripts, "dashboard must include an inline script")
        parser = _DashboardMarkupParser()
        parser.feed(html)

        harness = f"""
import vm from "node:vm";

const source = {json.dumps(scripts[-1], ensure_ascii=False)};
const mode = {json.dumps(mode)};
const report = {json.dumps(report, ensure_ascii=False)};
const elementIds = {json.dumps(parser.ids, ensure_ascii=False)};
const hiddenIds = new Set({json.dumps(parser.hidden_ids, ensure_ascii=False)});
const consoleErrors = [];

class FakeElement {{
  constructor(id = "") {{
    this.id = id;
    this.textContent = "";
    this.className = "";
    this.hidden = hiddenIds.has(id);
    this.children = [];
    this.style = {{}};
    this.dataset = {{}};
    this.attributes = {{}};
    this.disabled = false;
    this.listeners = {{}};
    this.classList = {{
      add: (...names) => {{
        const values = new Set(this.className.split(/\\s+/).filter(Boolean));
        names.forEach((name) => values.add(name));
        this.className = [...values].join(" ");
      }},
      remove: (...names) => {{
        const rejected = new Set(names);
        this.className = this.className
          .split(/\\s+/)
          .filter((name) => name && !rejected.has(name))
          .join(" ");
      }}
    }};
  }}

  get firstChild() {{
    return this.children[0] || null;
  }}

  appendChild(child) {{
    this.children.push(child);
    return child;
  }}

  removeChild(child) {{
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    return child;
  }}

  addEventListener(name, handler) {{
    this.listeners[name] = handler;
  }}

  setAttribute(name, value) {{
    this.attributes[name] = String(value);
  }}
}}

const elements = new Map(elementIds.map((id) => [id, new FakeElement(id)]));
const document = {{
  getElementById(id) {{ return elements.get(id) || null; }},
  createElement() {{ return new FakeElement(); }}
}};
const window = {{
  location: {{ protocol: "http:", origin: "http://dashboard.test" }},
  setTimeout() {{ return 1; }},
  clearTimeout() {{}}
}};
class FakeAbortController {{
  constructor() {{ this.signal = {{}}; }}
  abort() {{}}
}}
const fakeConsole = {{
  log() {{}},
  warn(...args) {{ consoleErrors.push(`warn: ${{args.join(" ")}}`); }},
  error(...args) {{ consoleErrors.push(`error: ${{args.join(" ")}}`); }}
}};
const fetch = async () => {{
  if (mode === "offline") throw new Error("report API unavailable");
  return {{ ok: true, status: 200, json: async () => report }};
}};
const context = {{
  AbortController: FakeAbortController,
  Intl,
  URL,
  console: fakeConsole,
  document,
  fetch,
  window
}};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context, {{ filename: "dashboard-inline.js" }});
await new Promise((resolve) => setImmediate(resolve));
await new Promise((resolve) => setImmediate(resolve));

function snapshot(id) {{
  const node = elements.get(id);
  return node ? {{
    text: node.textContent,
    hidden: node.hidden,
    className: node.className,
    dataset: node.dataset,
    attributes: node.attributes,
    children: node.children.map((child) => snapshotNode(child))
  }} : null;
}}

function snapshotNode(node) {{
  return {{
    text: node.textContent,
    hidden: node.hidden,
    className: node.className,
    dataset: node.dataset,
    attributes: node.attributes,
    children: node.children.map((child) => snapshotNode(child))
  }};
}}

process.stdout.write(JSON.stringify({{
  truth: snapshot("market-data-truth-state"),
  truthLabel: snapshot("market-data-truth-label"),
  truthDetail: snapshot("market-data-truth-detail"),
  reportTime: snapshot("report-generated-time"),
  marketTime: snapshot("market-as-of-time"),
  marketAge: snapshot("market-data-age"),
  marketSource: snapshot("market-data-source"),
  marketTrust: snapshot("market-data-trust"),
  collectionCounts: snapshot("market-collection-counts"),
  collectionCoverage: snapshot("market-collection-coverage"),
  action: snapshot("action"),
  modeGateList: snapshot("mode-gate-list"),
  candidateCount: snapshot("candidate-count"),
  candidateMeta: snapshot("candidate-meta"),
  candidateEmpty: snapshot("candidate-empty"),
  candidateTable: snapshot("candidate-table-wrap"),
  calibration: snapshot("calibration"),
  modelVersion: snapshot("model-version"),
  backtestBars: snapshot("backtest-bars"),
  backtestEmpty: snapshot("backtest-empty"),
  readinessList: snapshot("readiness-list"),
  missingCount: snapshot("missing-count"),
  matrixAccount: snapshot("matrix-account"),
  matrixAccountNote: snapshot("matrix-account-note"),
  consoleErrors
}}));
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            harness_path = Path(temp_dir) / "dashboard-harness.mjs"
            harness_path.write_text(harness, encoding="utf-8")
            completed = subprocess.run(
                [node, str(harness_path)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
