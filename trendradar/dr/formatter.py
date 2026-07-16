# coding=utf-8
"""DR Telegram text formatter.

This module renders the compact DR skim layer: a program/AI brief followed by
a short, deduplicated event list. It has no delivery behavior or dependency on
CR dispatch modules; expanded evidence and source links remain in the attached
HTML artifact.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from typing import Any

from trendradar.content_policy import is_reader_noise


DR_TITLE = "Ptilopsis Radar｜DR"
DR_FALLBACK_TEXT = (
    "本轮 AI 摘要不可用；以下内容仅依据程序统计与已采集证据整理。"
)

_TOPIC_BUCKET_ORDER = (
    "cross_layer_verified",
    "high_heat_unverified",
    "chinese_only_hot",
    "silence_gap",
)

_BUCKET_STATUS_FALLBACKS = {
    "cross_layer_verified": "多层来源呼应",
    "high_heat_unverified": "单点高热，来源待补",
    "chinese_only_hot": "中文平台热度上升",
    "silence_gap": "社交端响应偏弱",
}

_READER_STATUS_LABELS = {
    "跨层有呼应": "多层来源呼应",
    "高热待核实": "单点高热，来源待补",
    "情绪聚集": "情绪传播集中",
    "沉默温差": "社交端响应偏弱",
    "中文源呼应(缺A/B背景)": "中文平台热度上升",
    "中文专业来源": "中文专业来源",
    "来源覆盖有限": "来源覆盖有限",
}

_MAX_ITEMS = 5
_MAX_SUMMARY = 240
_MAX_TOPIC = 160
_MAX_STATUS = 64
_MAX_HEAT = 80
_MAX_SOURCE_LAYERS = 48
_MAX_DATE = 32
_TELEGRAM_MAX_CHARS = 4096
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_UNCLASSIFIED_PREFIX_RE = re.compile(r"^(?:高热未归类|未归类)\s*[·:：|｜-]\s*")
_GENERIC_SUMMARIES = {
    "该事件存在传播风险",
    "事实仍待核验",
    "需关注后续信息",
    "当前仅能确认传播正在发生，不能确认事件已经成立。",
}
_BUCKET_SCORE = {
    "cross_layer_verified": 400,
    "chinese_only_hot": 320,
    "high_heat_unverified": 240,
    "silence_gap": 160,
}


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


def _display_topic(topic: str) -> str:
    """Remove internal classifier prefixes from a user-facing topic title."""
    raw = _strip_urls(str(topic or "").strip())
    cleaned = _UNCLASSIFIED_PREFIX_RE.sub("", raw).strip()
    return cleaned or raw


def _is_noise_topic(topic: str, samples: list[str] | None = None) -> bool:
    return is_reader_noise(_strip_urls(str(topic or "").strip()), samples)


def _bounded_item_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _MAX_ITEMS
    return max(0, min(parsed, _MAX_ITEMS))


def _telegram_visible_length(text: str) -> int:
    """Telegram's 4096 limit is measured after HTML entities are parsed."""
    without_tags = re.sub(r"<[^>]+>", "", text or "")
    return len(html.unescape(without_tags))


def _is_generic_summary(text: str) -> bool:
    body = str(text or "").strip()
    if not body or body in _GENERIC_SUMMARIES:
        return True
    if body.startswith(("本组", "该组", "此组")):
        return True
    return body in {s.rstrip("。") for s in _GENERIC_SUMMARIES}


def _topic_similarity(left: str, right: str) -> float:
    """Containment-oriented bigram similarity for near-duplicate headlines."""
    a, b = _topic_key(_display_topic(left)), _topic_key(_display_topic(right))
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    if min(len(a), len(b)) < 8:
        return 0.0
    aa = {a[i:i + 2] for i in range(max(1, len(a) - 1))}
    bb = {b[i:i + 2] for i in range(max(1, len(b) - 1))}
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / min(len(aa), len(bb))


def _sample_titles(item: dict[str, Any]) -> list[str]:
    detail = item.get("evidence_detail") or {}
    samples = (detail.get("sample_titles") or []) if isinstance(detail, dict) else []
    out: list[str] = []
    for sample in samples:
        title = sample.get("title", "") if isinstance(sample, dict) else str(sample)
        title = _strip_urls(str(title or "").strip())
        if title and title not in out:
            out.append(title)
    return out


def _reader_status(bucket: str, item: dict[str, Any]) -> str:
    """Return the event's own reader-facing status.

    ``bucket`` is only a compatibility fallback for old analysis artifacts.  A
    split event can carry a different evidence shape from its former keyword
    group, so its ``verification_status`` must win in every reader channel.
    """
    detail = item.get("evidence_detail") or {}
    if isinstance(detail, dict):
        present = set(detail.get("source_tiers_present") or [])
        by_tier = detail.get("sources_by_tier") or {}
        if isinstance(by_tier, dict):
            present.update(tier for tier in ("A", "B", "C", "D") if by_tier.get(tier))
        if not present.intersection({"A", "B"}) and {"C", "D"}.issubset(present):
            d_count = int(detail.get("d_tier_platform_count", 0) or 0)
            platform_count = int(detail.get("platform_count", 0) or 0)
            if d_count >= 3 or platform_count >= 5:
                return "中文多源覆盖"
            if d_count >= 2 or platform_count >= 3:
                return "中文多平台覆盖"
            return "中文源有呼应"

    raw = str(item.get("verification_status", "") or "").strip()
    if raw:
        return _READER_STATUS_LABELS.get(raw, raw)
    return _BUCKET_STATUS_FALLBACKS.get(bucket, "")


def _is_high_heat_event(bucket: str, item: dict[str, Any]) -> bool:
    raw = str(item.get("verification_status", "") or "").strip()
    if raw:
        return raw == "高热待核实"
    return bucket == "high_heat_unverified"


def _event_bucket(bucket: str, item: dict[str, Any]) -> str:
    """Map an event status to the count/ranking dimension used by DR."""
    raw = str(item.get("verification_status", "") or "").strip()
    return {
        "跨层有呼应": "cross_layer_verified",
        "中文源呼应(缺A/B背景)": "chinese_only_hot",
        "中文专业来源": "chinese_only_hot",
        "高热待核实": "high_heat_unverified",
        "沉默温差": "silence_gap",
    }.get(raw, bucket)


def _fallback_topic_summary(bucket: str, item: dict[str, Any]) -> str:
    """Build a factual, visibly non-AI fallback from collected metadata."""
    topic = _display_topic(item.get("topic", ""))
    heat = str(item.get("highest_heat", "") or "").strip()
    samples = _sample_titles(item)

    if _is_high_heat_event(bucket, item) and topic:
        where = f"进入{heat}" if heat and heat != "-" else "形成高热传播"
        return f"“{topic}”{where}；目前只能确认传播热度，不能据此确认标题中的说法。"
    if samples:
        shown = "；".join(f"“{title}”" for title in samples[:2])
        if len(samples) > 1:
            return f"当前可核对的标题包括{shown}；它们可能指向不同事件。"
        return f"当前可核对的标题为{shown}。"
    return ""


def _deterministic_brief(ai_result: Any) -> str:
    stats = (getattr(ai_result, "overview_stats", {}) or {}) if ai_result else {}
    counts = stats.get("label_counts", {}) or {} if isinstance(stats, dict) else {}
    background = int(stats.get("background_count", 0) or 0) if isinstance(stats, dict) else 0
    visible_counts: dict[str, int] = {bucket: 0 for bucket in _TOPIC_BUCKET_ORDER}
    noise_count = 0
    if ai_result is not None:
        for bucket in _TOPIC_BUCKET_ORDER:
            for item in getattr(ai_result, bucket, []) or []:
                if not isinstance(item, dict):
                    continue
                if _is_noise_topic(
                    str(item.get("topic", "") or ""), _sample_titles(item)
                ):
                    noise_count += 1
                else:
                    status_bucket = _event_bucket(bucket, item)
                    if status_bucket in visible_counts:
                        visible_counts[status_bucket] += 1

    def _count(bucket: str) -> int:
        if ai_result is not None:
            return visible_counts.get(bucket, 0)
        return int(counts.get(bucket, 0) or 0)

    cross = _count("cross_layer_verified")
    high = _count("high_heat_unverified")
    chinese = _count("chinese_only_hot")
    silence = _count("silence_gap")
    sentiment = int(counts.get("sentiment_heavy", 0) or 0)
    anomaly = cross + high + chinese + silence
    if not anomaly and not background and not sentiment:
        if ai_result is not None and getattr(ai_result, "skipped", False):
            return "本轮未识别达到异常阈值的事件。"
        return DR_FALLBACK_TEXT

    clauses: list[str] = []
    for count, label in (
        (cross, "多层来源呼应"),
        (chinese, "中文源内部升温"),
        (high, "社交平台单点高热"),
        (silence, "背景源热、社交端静"),
    ):
        if count:
            clauses.append(f"{count} 个{label}")
    detail = "、".join(clauses) if clauses else "未发现达到异常阈值的主信号"
    suppressed = background + sentiment + noise_count
    suffix = f"；另有 {suppressed} 个非重点项已折叠" if suppressed else ""
    return f"今日识别 {anomaly} 个异常信号：{detail}{suffix}。"


def _topic_entry(bucket: str, item: dict[str, Any]) -> dict[str, str]:
    status = _reader_status(bucket, item)
    raw_summary = _strip_urls(str(item.get("summary") or "").strip())
    summary = (
        _fallback_topic_summary(bucket, item)
        if _is_generic_summary(raw_summary)
        else raw_summary
    )
    platform_count = item.get("platform_count")
    return {
        "topic": _truncate_text(
            _display_topic(str(item.get("topic", "") or "")), _MAX_TOPIC
        ),
        "status_label": _truncate_text(status, _MAX_STATUS),
        "source_layers": _truncate_text(
            str(item.get("source_layers", "") or "").strip(), _MAX_SOURCE_LAYERS
        ),
        "highest_heat": _truncate_text(
            str(item.get("highest_heat", "") or "").strip(), _MAX_HEAT
        ),
        "platform_count": (
            _truncate_text(str(platform_count), 16)
            if isinstance(platform_count, int)
            else ""
        ),
        "summary": summary,
    }


def _topic_entries(bucket: str, item: dict[str, Any]) -> list[dict[str, str]]:
    """Return event-first entries, including a non-AI per-headline fallback."""
    raw_summary = _strip_urls(str(item.get("summary") or "").strip())
    samples = _sample_titles(item)
    if not _is_generic_summary(raw_summary) or not samples:
        return [_topic_entry(bucket, item)]

    base = _topic_entry(bucket, item)
    heat = str(item.get("highest_heat", "") or "").strip()
    entries: list[dict[str, str]] = []
    for title in samples:
        entry = dict(base)
        entry["topic"] = _truncate_text(title, _MAX_TOPIC)
        if _is_high_heat_event(bucket, item):
            where = f"进入{heat}" if heat and heat != "-" else "形成高热传播"
            entry["summary"] = (
                f"“{title}”{where}；目前只能确认传播热度，"
                "不能据此确认标题中的说法。"
            )
        else:
            entry["summary"] = (
                f"当前仅采集到题为“{title}”的传播文本，"
                "未生成额外事件摘要。"
            )
        entries.append(entry)
    return entries


def select_dr_digest_topics(
    ai_result: Any, max_items: int = _MAX_ITEMS
) -> list[dict[str, str]]:
    """Select DR text topics from an environment AI result.

    This applies the compact digest selection policy: primary anomaly buckets
    first, then silence gaps, with normalized topic dedupe.
    """
    if not ai_result:
        return []
    if getattr(ai_result, "report_style", "environment") != "environment":
        return []

    max_items = _bounded_item_count(max_items)
    if max_items == 0:
        return []

    candidates: list[tuple[int, int, dict[str, str]]] = []
    sequence = 0
    for bucket in _TOPIC_BUCKET_ORDER:
        for item in getattr(ai_result, bucket, []) or []:
            if not isinstance(item, dict):
                continue
            if _is_noise_topic(
                str(item.get("topic", "") or ""), _sample_titles(item)
            ):
                continue
            for entry in _topic_entries(bucket, item):
                if _is_noise_topic(entry["topic"]) or not _topic_key(entry["topic"]):
                    continue
                # Rank by the event's evidence status.  The originating bucket
                # is only a fallback for pre-event artifacts.
                status_bucket = _event_bucket(bucket, item)
                score = _BUCKET_SCORE.get(status_bucket, 0)
                if entry["summary"]:
                    score += 12
                try:
                    score += min(int(item.get("platform_count", 0) or 0), 8)
                except (TypeError, ValueError):
                    pass
                candidates.append((score, sequence, entry))
                sequence += 1

    selected: list[dict[str, str]] = []
    for _score, _seq, entry in sorted(candidates, key=lambda x: (-x[0], x[1])):
        if any(_topic_similarity(entry["topic"], old["topic"]) >= 0.72 for old in selected):
            continue
        selected.append(entry)
        if len(selected) >= max_items:
            break
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
    safe_date = _truncate_text(str(date or ""), _MAX_DATE)
    lines = [f"<b>{_escape(DR_TITLE)}</b>", f"日期：{_escape(safe_date)}", ""]

    usable_ai = (
        ai_result is not None
        and getattr(ai_result, "success", False)
        and getattr(ai_result, "report_style", "environment") == "environment"
        and bool(str(getattr(ai_result, "overview", "") or "").strip())
    )

    lines.append("<b>导读</b>")
    if usable_ai:
        lines.append(_escape(_truncate_text(str(ai_result.overview), 700)))
    else:
        program_brief = _truncate_text(_deterministic_brief(ai_result), 700)
        lines.append(_escape(program_brief))
        if (
            program_brief != DR_FALLBACK_TEXT
            and not bool(getattr(ai_result, "skipped", False))
        ):
            lines.append(_escape(DR_FALLBACK_TEXT))
    lines.append("")

    topics = select_dr_digest_topics(
        ai_result, max_items=_bounded_item_count(max_items)
    )
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    footer = ["完整报告：见随附 HTML", f"更新：{_escape(ts)}"]
    if topics:
        lines.append("<b>重点</b>")
        added = 0
        for idx, item in enumerate(topics, 1):
            block = [f"{idx}. <b>{_escape(item['topic'])}</b>"]
            meta_parts = [
                part
                for part in (
                    item["status_label"],
                    f"{item['platform_count']} 个来源" if item["platform_count"] else "",
                    item["highest_heat"] if item["highest_heat"] != "-" else "",
                )
                if part
            ]
            if meta_parts:
                block.append(_escape(" | ".join(meta_parts)))
            if item["summary"]:
                block.append(_escape(_truncate_text(item["summary"], _MAX_SUMMARY)))
            block.append("")
            candidate = "\n".join([*lines, *block, *footer]).rstrip()
            if _telegram_visible_length(candidate) > _TELEGRAM_MAX_CHARS:
                break
            lines.extend(block)
            added += 1
        if not added:
            lines.extend(["重点事件文本过长，完整内容见随附报告。", ""])
    else:
        lines.extend(
            [
                "<b>重点</b>",
                "暂无可展示的重点事件，完整证据见随附报告。",
                "",
            ]
        )

    lines.extend(footer)
    rendered = "\n".join(lines).rstrip()
    if _telegram_visible_length(rendered) <= _TELEGRAM_MAX_CHARS:
        return rendered

    # Defensive final guard for pathological program metadata.  Every HTML tag
    # is rebuilt rather than truncating markup in-place, so parse mode remains
    # valid while the full event detail stays available in the attachment.
    compact_brief = _escape(
        _truncate_text(_deterministic_brief(ai_result), _MAX_SUMMARY)
    )
    return "\n".join([
        f"<b>{_escape(DR_TITLE)}</b>",
        f"日期：{_escape(safe_date)}",
        "",
        "<b>导读</b>",
        compact_brief,
        "",
        "<b>重点</b>",
        "正文已压缩，完整事件与证据见随附报告。",
        "",
        *footer,
    ]).rstrip()
