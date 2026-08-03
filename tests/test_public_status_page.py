from crypto_options_report.public_status_page import render_public_status_html


def _status(history: dict) -> dict:
    return {
        "published_at": "2026-08-03T09:00:00Z",
        "next_expected_at": "2026-08-04T08:00:00Z",
        "stale_after": "2026-08-05T08:00:00Z",
        "research_publication_status": "GO",
        "execution_authorization_status": "NO-GO",
        "is_stale_at_publish": False,
        "publish_manifest_status": "verified",
        "publication_history": history,
    }


def test_chinese_status_localizes_empty_history_reason() -> None:
    html = render_public_status_html(
        _status(
            {
                "status": "collecting",
                "window_days": 30,
                "history": [],
                "reason": "No durable publication receipts are available in the 30-day window.",
            }
        ),
        language="zh-CN",
    )

    assert "收集中" in html
    assert "尚无持久化发布回执" in html
    assert "No durable publication" not in html


def test_status_page_renders_durable_success_and_failure_receipts() -> None:
    history = {
        "status": "available",
        "window_days": 30,
        "reason": None,
        "history": [
            {
                "date": "2026-08-02",
                "captured_at": None,
                "published_at": "2026-08-02T09:00:00Z",
                "status": "failed",
                "research_publication_status": "NO-GO",
                "capture_row_count": 0,
                "quality_gate_blocked_count": 1,
                "excluded_snapshot_count": 0,
                "reason_code": "CAPTURE_FAILED",
            },
            {
                "date": "2026-08-03",
                "captured_at": "2026-08-03T08:55:00Z",
                "published_at": "2026-08-03T09:00:00Z",
                "status": "success",
                "research_publication_status": "GO",
                "capture_row_count": 96,
                "quality_gate_blocked_count": 0,
                "excluded_snapshot_count": 2,
                "reason_code": None,
            },
        ],
    }

    zh = render_public_status_html(_status(history), language="zh-CN")
    en = render_public_status_html(_status(history), language="en")

    for expected in ("2026-08-02", "CAPTURE_FAILED", "2026-08-03", "96", "2"):
        assert expected in zh
        assert expected in en
    assert "成功" in zh and "失败" in zh
    assert "success" in en and "failed" in en
