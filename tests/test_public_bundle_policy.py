import json
from pathlib import Path

from crypto_options_report.public_bundle_policy import forbidden_bundle_tokens

ROOT = Path(__file__).resolve().parents[1]


def test_python_and_node_scanners_share_one_forbidden_token_policy() -> None:
    policy_path = (
        ROOT
        / "crypto_options_report"
        / "resources"
        / "public_bundle_forbidden_tokens.json"
    )
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    tokens = payload["tokens"]

    assert payload["schema_version"] == "public_bundle_forbidden_tokens.v1"
    assert tokens == sorted(set(tokens))
    assert all(token == token.lower() for token in tokens)
    assert {
        "api_key",
        "execution_authorization",
        "margin_snapshot",
        "view=workbench",
    }.issubset(tokens)
    assert forbidden_bundle_tokens() == frozenset(tokens)

    node_scanner = (
        ROOT / "web" / "scripts" / "assert-public-bundle-boundary.mjs"
    ).read_text(encoding="utf-8")
    assert "public_bundle_forbidden_tokens.json" in node_scanner
    assert "const forbiddenTokens = [" not in node_scanner
