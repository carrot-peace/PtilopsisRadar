# coding=utf-8
"""DR Telegram text formatter.

This module uses the compact daily digest shape: AI brief plus a
short, deduplicated topic list.  It has no delivery behavior and no dependency
on CR dispatch modules.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from typing import Any


DR_TITLE = "Ptilopsis Radar｜DR"
DR_FALLBACK_TEXT = (
    "Daily text is temporarily unavailable. "
    "DR HTML has been generated and attached when available."
)

_TOPIC_BUCKET_ORDER = (
    "cross_layer_verified",
    "high_heat_unverified",
    "chinese_only_hot",
    "silence_gap",
)

_STATUS_LABELS = {
    "cross_layer_verified": "cross_layer_verified",
    "high_heat_unverified": "high_heat_unverified",
    "chinese_only_hot": "chinese_only_hot",
    "silence_gap": "silence_gap",
}

_MAX_ITEMS = 5
_MAX_SUMMARY = 140
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _escape(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=False)


def _strip_urls(text: str) -> str:
    return _URL_RE.sub("", text or "").strip()


def _truncate_text(text: str, max_chars: int) -> str:
    text = _strip_urls(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _topic_key(topic: str) -> str:
    s = unicodedata.normalize("NFKC", str(topic or "")).strip().lower()
    out: list[str] = []
    for ch in s:
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("S"):
            continue
        out.append(ch)
    return "".join(out)


def _topic_entry(bucket: str, item: dict[str, Any]) -> dict[str, str]:
    status = _STATUS_LABELS.get(bucket) or str(
        item.get("verification_status", "") or ""
    ).strip()
    return {
        "topic": _strip_urls(str(item.get("topic", "") or "").strip()),
        "status_label": status,
        "source_layers": str(item.get("source_layers", "") or "").strip(),
        "highest_heat": str(item.get("highest_heat", "") or "").strip(),
        "summary": _strip_urls(
            str(
                item.get("summary")
                or item.get("analysis")
                or item.get("factual_boundary")
                or ""
            ).strip()
        ),
    }


def select_dr_digest_topics(
    ai_result: Any, max_items: int = _MAX_ITEMS
) -> list[dict[str, str]]:
    """Select DR text topics from an environment AI result.

    This applies the compact digest selection policy: primary anomaly buckets
    first, then silence gaps, with normalized topic dedupe.
    """
    if not ai_result or not getattr(ai_result, "success", False):
        return []
    if getattr(ai_result, "report_style", "environment") != "environment":
        return []

    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for bucket in _TOPIC_BUCKET_ORDER:
        for item in getattr(ai_result, bucket, []) or []:
            if len(selected) >= max_items:
                return selected
            if not isinstance(item, dict):
                continue
            entry = _topic_entry(bucket, item)
            key = _topic_key(entry["topic"])
            if not key or key in seen:
                continue
            seen.add(key)
            selected.append(entry)
    return selected


def render_dr_telegram_text(
    ai_result: Any,
    *,
    date: str,
    now: datetime | None = None,
    max_items: int = _MAX_ITEMS,
) -> str:
    """Render DR text for Telegram HTML parse mode.

    Text deliberately omits URLs, source links, expanded evidence, and Decision
    language.  HTML details live in the attached DR artifact.
    """
    lines = [f"<b>{_escape(DR_TITLE)}</b>", f"Date: {_escape(date)}", ""]

    usable_ai = (
        ai_result is not None
        and getattr(ai_result, "success", False)
        and getattr(ai_result, "report_style", "environment") == "environment"
        and bool(str(getattr(ai_result, "overview", "") or "").strip())
    )

    lines.append("<b>AI Brief</b>")
    if usable_ai:
        lines.append(_escape(_truncate_text(str(ai_result.overview), 700)))
    else:
        lines.append(_escape(DR_FALLBACK_TEXT))
    lines.append("")

    topics = select_dr_digest_topics(ai_result, max_items=max_items)
    if topics:
        lines.append("<b>Topics</b>")
        for idx, item in enumerate(topics, 1):
            lines.append(f"{idx}. <b>{_escape(item['topic'])}</b>")
            meta_parts = [
                part
                for part in (
                    item["status_label"],
                    item["source_layers"] if item["source_layers"] != "-" else "",
                    f"highest_heat {item['highest_heat']}"
                    if item["highest_heat"] and item["highest_heat"] != "-"
                    else "",
                )
                if part
            ]
            if meta_parts:
                lines.append(_escape(" | ".join(meta_parts)))
            if item["summary"]:
                lines.append(_escape(_truncate_text(item["summary"], _MAX_SUMMARY)))
            lines.append("")
    else:
        lines.extend(
            [
                "<b>Topics</b>",
                "No high-priority DR topics available in text. See attached DR HTML.",
                "",
            ]
        )

    lines.append("DR HTML: attached")
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"Updated: {_escape(ts)}")
    return "\n".join(lines).rstrip()
