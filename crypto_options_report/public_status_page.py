# ruff: noqa: RUF001
"""Localized static publication-status page rendering."""

from __future__ import annotations

from html import escape
from typing import Any


def render_public_status_html(status: dict[str, Any], *, language: str) -> str:
    if language == "zh-CN":
        return _render_zh(status)
    if language == "en":
        return _render_en(status)
    raise ValueError("status page language must be zh-CN or en")


def _render_zh(status: dict[str, Any]) -> str:
    history = dict(status["publication_history"])
    history_status = {
        "available": "可用",
        "collecting": "收集中",
    }.get(str(history.get("status")), str(history.get("status") or "不可用"))
    history_body = _history_rows(history, language="zh-CN")
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        "    <title>发布状态 | LensOS Option</title>\n"
        '    <link rel="stylesheet" href="./static-page.css" />\n'
        "  </head>\n"
        '  <body><main><div class="page-shell">\n'
        '    <header class="page-header"><a href="./index.html">返回公开首页</a>'
        '<nav aria-label="语言切换"><a href="./en/status.html">English</a></nav></header>\n'
        '    <div class="page-title"><p>Status / 发布状态</p><h1>发布状态</h1>'
        "<p>这里记录最后一次成功生成的静态版本、失效边界，以及证据仓保存的逐日发布结果。</p></div>\n"
        '    <section class="page-section">\n'
        f"      <p>成功发布：<code>{_text(status['published_at'])}</code></p>\n"
        f"      <p>下次应发布：<code>{_text(status['next_expected_at'])}</code></p>\n"
        f"      <p>失效边界：<code>{_text(status['stale_after'])}</code></p>\n"
        f"      <p>研究发布门禁：<strong>{_text(status['research_publication_status'])}</strong></p>\n"
        f"      <p>执行授权：<strong>{_text(status['execution_authorization_status'])}</strong></p>\n"
        f"      <p>发布时已失效：<strong>{'是' if status['is_stale_at_publish'] else '否'}</strong></p>\n"
        f"      <p>清单校验：<strong>{_text(status['publish_manifest_status'])}</strong></p>\n"
        "    </section>\n"
        '    <section class="page-section"><h2>如何解释停摆</h2>\n'
        "      <p>静态状态页不会自行判定当前是否停摆。独立监控必须将当前时间与 "
        "<code>stale_after</code> 比较；超过边界即应告警，不能把最后一次成功时的布尔值当成实时健康状态。</p>\n"
        f"      <p>近 {_text(history['window_days'])} 天发布历史：<strong>{_text(history_status)}</strong>。</p>\n"
        f"{history_body}"
        "    </section>\n"
        "  </div></main></body>\n"
        "</html>\n"
    )


def _render_en(status: dict[str, Any]) -> str:
    history = dict(status["publication_history"])
    history_body = _history_rows(history, language="en")
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        "    <title>Publication status | LensOS Option</title>\n"
        '    <link rel="stylesheet" href="../static-page.css" />\n'
        "  </head>\n"
        '  <body><main><div class="page-shell">\n'
        '    <header class="page-header"><a href="../index.html">Back to public home</a>'
        '<nav aria-label="Language switch"><a href="../status.html">中文</a></nav></header>\n'
        '    <div class="page-title"><p>Status / Publication boundary</p><h1>Publication status</h1>'
        "<p>This page records the latest static edition, its expiry boundary, and the daily outcomes preserved in the evidence repository.</p></div>\n"
        '    <section class="page-section">\n'
        f"      <p>Published at: <code>{_text(status['published_at'])}</code></p>\n"
        f"      <p>Next expected at: <code>{_text(status['next_expected_at'])}</code></p>\n"
        f"      <p>Stale after: <code>{_text(status['stale_after'])}</code></p>\n"
        f"      <p>Research publication gate: <strong>{_text(status['research_publication_status'])}</strong></p>\n"
        f"      <p>Execution authorization: <strong>{_text(status['execution_authorization_status'])}</strong></p>\n"
        f"      <p>Stale when published: <strong>{'yes' if status['is_stale_at_publish'] else 'no'}</strong></p>\n"
        f"      <p>Manifest verification: <strong>{_text(status['publish_manifest_status'])}</strong></p>\n"
        "    </section>\n"
        '    <section class="page-section"><h2>How to detect a publication stall</h2>\n'
        "      <p>This static page cannot decide whether the site is stale now. An independent monitor must compare "
        "the current time with <code>stale_after</code>; a last-success boolean is not live health.</p>\n"
        f"      <p>Last {_text(history['window_days'])} days of publication history: <strong>{_text(history['status'])}</strong>.</p>\n"
        f"{history_body}"
        "    </section>\n"
        "  </div></main></body>\n"
        "</html>\n"
    )


def _history_rows(history: dict[str, Any], *, language: str) -> str:
    entries = list(history.get("history") or [])
    if not entries:
        message = (
            "近 30 天窗口内尚无持久化发布回执，状态页正在收集。"
            if language == "zh-CN"
            else str(history.get("reason") or "No durable publication receipts are available yet.")
        )
        return f'      <p class="history-empty">{_text(message)}</p>\n'

    rows = []
    for entry in reversed(entries):
        if language == "zh-CN":
            outcome = "成功" if entry["status"] == "success" else "失败"
            captured = entry["captured_at"] or "采集未完成"
            reason = entry["reason_code"] or "无"
            labels = (
                ("采集", captured),
                ("发布", entry["published_at"]),
                ("采集行数", entry["capture_row_count"]),
                ("质量门禁阻断", entry["quality_gate_blocked_count"]),
                ("排除快照", entry["excluded_snapshot_count"]),
                ("原因码", reason),
            )
        else:
            outcome = str(entry["status"])
            captured = entry["captured_at"] or "capture did not complete"
            reason = entry["reason_code"] or "none"
            labels = (
                ("Captured", captured),
                ("Published", entry["published_at"]),
                ("Capture rows", entry["capture_row_count"]),
                ("Quality blocks", entry["quality_gate_blocked_count"]),
                ("Excluded snapshots", entry["excluded_snapshot_count"]),
                ("Reason code", reason),
            )
        details = "".join(
            f"<dt>{_text(label)}</dt><dd>{_text(value)}</dd>" for label, value in labels
        )
        rows.append(
            '      <article class="history-entry">'
            f"<h3>{_text(entry['date'])} · {_text(outcome)}</h3>"
            f"<p>Research gate: <strong>{_text(entry['research_publication_status'])}</strong></p>"
            f"<dl>{details}</dl></article>\n"
        )
    return "".join(rows)


def _text(value: Any) -> str:
    return escape(str(value), quote=True)
