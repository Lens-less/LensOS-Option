import ast
import json
import re
import unittest
from pathlib import Path

from crypto_options_report.contract import generate_research_report
from crypto_options_report.market_data import load_snapshot_fixture
from crypto_options_report.publication import _build_public_report

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "web" / "src" / "reasonCodes" / "catalog.json"
PYTHON_CATALOG_PATH = (
    ROOT
    / "crypto_options_report"
    / "resources"
    / "reason_code_catalog.json"
)
SNAPSHOT_FIXTURE = (
    ROOT / "tests" / "fixtures" / "deribit_btc_option_chain_snapshot.json"
)
REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*_[A-Z0-9_]+$")


def _load_catalog() -> dict[str, dict[str, object]]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _module_string_constants(module: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in module.body:
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if not (
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and REASON_CODE_RE.fullmatch(value.value)
        ):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _reachable_local_functions(
    module: ast.Module,
    *,
    entrypoints: set[str],
) -> set[str]:
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    reachable: set[str] = set()
    pending = list(entrypoints)
    while pending:
        name = pending.pop()
        if name in reachable or name not in functions:
            continue
        reachable.add(name)
        for node in ast.walk(functions[name]):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in functions
            ):
                pending.append(node.func.id)
    return reachable


def _extract_reachable_reason_codes(
    module: ast.Module,
    *,
    entrypoints: set[str],
) -> set[str]:
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    constants = _module_string_constants(module)
    codes: set[str] = set()
    for name in _reachable_local_functions(module, entrypoints=entrypoints):
        for node in ast.walk(functions[name]):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and REASON_CODE_RE.fullmatch(node.value)
            ):
                codes.add(node.value)
            elif isinstance(node, ast.Name) and node.id in constants:
                codes.add(constants[node.id])
    return codes


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _static_public_surface_codes() -> set[str]:
    publication_codes = _extract_reachable_reason_codes(
        _module(ROOT / "crypto_options_report" / "publication.py"),
        entrypoints={"_build_public_report"},
    )
    full_surface_codes = _extract_reachable_reason_codes(
        _module(ROOT / "crypto_options_report" / "full_surface.py"),
        entrypoints={"build_full_system_surface_report", "build_release_gates"},
    )
    signal_codes = _extract_reachable_reason_codes(
        _module(ROOT / "crypto_options_report" / "signal_validation.py"),
        entrypoints={"build_signal_validation_report", "build_signal_preflight_report"},
    )
    series_codes = _extract_reachable_reason_codes(
        _module(ROOT / "crypto_options_report" / "series_history.py"),
        entrypoints={"build_series_history_report"},
    )
    return publication_codes | full_surface_codes | signal_codes | series_codes


def _canonical_published_report() -> dict[str, object]:
    snapshot = load_snapshot_fixture(SNAPSHOT_FIXTURE)
    report = generate_research_report(
        generated_at=str(snapshot["captured_at"]),
        market_snapshot=snapshot,
    )
    report["runtime_context"] = {
        "evaluation_clock": snapshot["captured_at"],
        "mode": "published",
    }
    return _build_public_report(report)


def _artifact_reason_codes(value: object) -> set[str]:
    codes: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "reason_code" and isinstance(item, str) and item:
                codes.add(item)
            elif key == "reason_codes" and isinstance(item, list):
                codes.update(
                    code
                    for code in item
                    if isinstance(code, str) and code
                )
            codes.update(_artifact_reason_codes(item))
    elif isinstance(value, list):
        for item in value:
            codes.update(_artifact_reason_codes(item))
    return codes


class ReasonCodeCatalogContractTest(unittest.TestCase):
    def test_reachable_function_detector_finds_new_public_reason_code(self) -> None:
        module = ast.parse(
            """
def _build_public_report():
    return _project_status()

def _project_status():
    return {"reason_code": "SYNTHETIC_REASON_UNREGISTERED"}
"""
        )

        self.assertEqual(
            {"SYNTHETIC_REASON_UNREGISTERED"},
            _extract_reachable_reason_codes(
                module,
                entrypoints={"_build_public_report"},
            ),
        )

    def test_generated_python_catalog_matches_the_canonical_web_catalog(self) -> None:
        generated = json.loads(PYTHON_CATALOG_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            "public_reason_code_copy_catalog.v1",
            generated["schema_version"],
        )
        self.assertEqual(
            [
                code
                for code, entry in _load_catalog().items()
                if "public" in entry
            ],
            generated["codes"],
        )

    def test_public_artifact_reason_codes_are_cataloged(self) -> None:
        public_report = _canonical_published_report()
        codes = _static_public_surface_codes() | _artifact_reason_codes(
            public_report
        )

        self.assertTrue(
            {
                "DTE_EVIDENCE_CONFLICT",
                "EXCHANGE_NO_ACTIVE_LOCKS",
                "RESEARCH_PUBLICATION_EVIDENCE_INCOMPLETE",
                "EXECUTION_DISABLED_BY_PRODUCT_DEFINITION",
                "DEFINED_RISK_STRUCTURE_PREFERRED",
                "NAKED_PERMISSION_FALSE",
                "UNBOUNDED_TAIL_LOSS",
            }.issubset(codes)
        )
        self.assertEqual(set(), codes - set(_load_catalog()))

    def test_published_top_level_reasons_have_public_copy(self) -> None:
        public_report = _canonical_published_report()
        catalog = _load_catalog()
        reason_codes = set(public_report["reason_codes"])
        reason_codes.update(public_report["mode_gate"]["reason_codes"])

        self.assertNotIn("MISSING_ACCOUNT_API_SNAPSHOT", reason_codes)
        self.assertNotIn("SIMULATION_NOT_REQUESTED", reason_codes)
        self.assertEqual(
            set(),
            {
                code
                for code in reason_codes
                if "public" not in catalog.get(code, {})
            },
        )
