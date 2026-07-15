# coding=utf-8
"""Shared reader-facing content policy for every DR surface.

The analyzer owns evidence classification.  This module owns the narrower
editorial decision of whether a routine entertainment, sports, or esports item
belongs in the reader's main event stream.  Daily HTML, Telegram, and the
Dashboard must use the same policy so their visible items and counts agree.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional


ENTERTAINMENT_WORDS = (
    "明星", "综艺", "电视剧", "电影", "演唱会", "爱豆", "偶像", "粉丝",
    "饭圈", "塌房", "恋情", "官宣", "选秀", "晋级", "出道", "网红", "主播",
    "热恋", "分手", "结婚", "离婚", "代言", "新歌", "新剧", "票房", "颁奖",
)
SPORTS_WORDS = (
    "足球", "篮球", "NBA", "世界杯", "联赛", "球员", "夺冠", "进球", "奥运",
    "金牌", "比分", "球队", "中超", "欧冠", "决赛", "晋级八强", "羽毛球",
    "乒乓球", "网球", "马拉松", "教练", "C罗", "哈兰德", "VAR",
)
ESPORTS_WORDS = (
    "电竞", "LPL", "LCK", "S赛", "全球总决赛", "战队", "选手", "英雄联盟",
    "KPL", "MSI", "季中冠军赛", "DOTA", "CSGO", "无畏契约", "出装", "对线",
    "团战", "Ban", "BLG", "HLE", "T1", "G2", "TES", "EDG", "GEN", "LYON",
    "Bin", "赛后数据", "数据雷达图", "Steam夏促", "游戏攻略",
)
STRUCTURAL_PROMOTION_WORDS = (
    "封禁", "封号", "下架", "监管", "审查", "处罚", "罚款", "约谈", "整治",
    "禁赛", "官方通报", "通报", "警方", "刑事", "立案", "安全事故", "踩踏",
    "伤亡", "死亡", "政策", "国家", "外交", "制裁", "操纵", "水军", "控评",
    "大规模", "造假", "造谣", "谣言", "网信办", "停播", "停职", "调查",
)

CATEGORY_LABELS = {
    "entertainment": "娱乐",
    "sports": "体育",
    "esports": "电竞",
}

_UNCLASSIFIED_PREFIXES = ("高热未归类·", "未归类·")


def _contains_keyword(text: str, keyword: str) -> bool:
    """Match ASCII tokens as tokens and Chinese/mixed phrases by containment."""
    if keyword.isascii() and keyword.isalnum():
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])",
                text,
                re.IGNORECASE,
            )
        )
    return keyword.lower() in text.lower()


def _contains_any(text: str, words: Iterable[str]) -> bool:
    return any(_contains_keyword(text or "", word) for word in words)


def classify_reader_category(text: str) -> Optional[str]:
    """Return the routine-content category for ``text``, if any."""
    blob = text or ""
    if _contains_any(blob, ESPORTS_WORDS):
        return "esports"
    if _contains_any(blob, SPORTS_WORDS):
        return "sports"
    if _contains_any(blob, ENTERTAINMENT_WORDS):
        return "entertainment"
    return None


def reader_structural_reason(text: str) -> Optional[str]:
    """Return the first public-interest override found in ``text``."""
    blob = text or ""
    for word in STRUCTURAL_PROMOTION_WORDS:
        if _contains_keyword(blob, word):
            return word
    return None


def reader_item_blob(
    topic: str,
    samples: Optional[Iterable[Any]] = None,
) -> str:
    parts = [str(topic or "")]
    for sample in samples or ():
        if isinstance(sample, Mapping):
            parts.append(str(sample.get("title", "") or ""))
        else:
            parts.append(str(sample or ""))
    return " ".join(parts)


def reader_category(
    topic: str,
    samples: Optional[Iterable[Any]] = None,
) -> Optional[str]:
    """Classify an event, consulting samples only for an internal fallback title."""
    raw_topic = str(topic or "")
    blob = (
        reader_item_blob(raw_topic, samples)
        if raw_topic.startswith(_UNCLASSIFIED_PREFIXES)
        else raw_topic
    )
    return classify_reader_category(blob)


def is_reader_noise(
    topic: str,
    samples: Optional[Iterable[Any]] = None,
) -> bool:
    """Return whether routine content should stay outside the main DR stream."""
    raw_topic = str(topic or "")
    blob = (
        reader_item_blob(raw_topic, samples)
        if raw_topic.startswith(_UNCLASSIFIED_PREFIXES)
        else raw_topic
    )
    if reader_structural_reason(blob):
        return False
    return classify_reader_category(blob) is not None
