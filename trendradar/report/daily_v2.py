# coding=utf-8
"""
Daily Report v2 — artifact-only report model and renderer.

DR v2 belongs strictly to the Generation Plane. It turns the program-decided
evidence buckets + AI prose (``AIAnalysisResult``) and the collected
``report_data`` into a clean, structured daily artifact, then renders that
model to self-contained HTML.

Hard boundary (see ``docs/legacy_push_removal_plan.md`` PR-D):
- This module MUST NOT import the legacy notification package.
- It MUST NOT call any legacy dispatch / sender entrypoint.
- It MUST NOT use the CR Telegram sink or env.
- It produces artifacts only. It never pushes. Any future DR push requires a
  separate explicit DR dispatch plan, gate, receipt model, and cooldown policy.

The exact forbidden symbol names are intentionally omitted from this source so
the literal Legacy-Push source guard stays clean; they are enumerated in the
canonical plan and asserted in ``tests/test_daily_report_v2_artifact.py``.

The module is split into a pure model layer (``build_daily_report_v2`` and the
classification helpers) and a renderer (``render_daily_report_v2``) so the
policy rules are unit-testable without HTML or I/O.

DR v2 fixes the known artifact-quality problems:
1. AI-backed reports require an overview; a missing overview yields a
   deterministic degraded-artifact notice instead of a normal-looking report.
2. A main item must carry a concrete event summary; a generic risk /
   factual-boundary template is never used as the item body.
3. Risk / factual-boundary text is a separate ``risk_note`` field, never the
   event summary.
4. Entertainment / sports / esports items are not promoted to the top anomaly
   section by default; they go to the noise / suppressed section unless they
   carry an explicit structural reason.
5. Domestic Chinese public events can receive an explicit domestic-confidence
   status from C+D multi-platform evidence, without an A/B international source.
6. The suppressed section is compact (category + count + reason + capped
   examples) and never duplicates label / explanation rows.
7. Raw hotlist data is capped and collapsed into an appendix, never dumped into
   the main digest.
"""

import html as _html_lib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from trendradar.ai.evidence import (
    LABELS,
    RISK_NOTE_HIGH_HEAT,
    SECTION_ORDER,
)

# ─────────────────────────────────────────────────────────────
# Deterministic notices / labels (sober, not Telegram fallback text)
# ─────────────────────────────────────────────────────────────

#: Shown when an AI-backed report is missing its overview (Rule 1).
DEGRADED_OVERVIEW_NOTICE = (
    "本次日报缺少可用总览，以下内容仅作为结构化候选与证据附录展示。"
)

#: Shown when there is no usable environment AI result at all (no-AI artifact).
NO_AI_NOTICE = (
    "本轮 AI 分析不可用；本报告仅展示程序已采集内容和可用元数据，不生成额外结论。"
)

#: Marker rendered in place of a fabricated body for a degraded main item.
DEGRADED_ITEM_NOTICE = "暂无可用的具体事件摘要，仅保留证据与状态。"

# Domestic public-event confidence statuses (Rule 5). These are explicit
# domestic labels; they do NOT claim global confirmation.
DOMESTIC_CONFIRMED = "domestic_confirmed"
DOMESTIC_HIGH_CONFIDENCE = "domestic_high_confidence"
DOMESTIC_PUBLIC_EVENT = "domestic_public_event"

_DOMESTIC_STATUS_LABELS: Dict[str, str] = {
    DOMESTIC_CONFIRMED: "国内已确认",
    DOMESTIC_HIGH_CONFIDENCE: "国内高可信",
    DOMESTIC_PUBLIC_EVENT: "国内公共事件",
}

_SECTION_TITLES: Dict[str, str] = {
    "cross_layer_verified": "跨层来源共振",
    "high_heat_unverified": "高热待核实",
    "chinese_only_hot": "中文独热",
    "silence_gap": "沉默温差",
}

# Caps (Rule 6 / Rule 7).
SUPPRESSED_EXAMPLE_CAP = 3
RAW_APPENDIX_MAX_GROUPS = 8
RAW_APPENDIX_MAX_TITLES = 5


# ─────────────────────────────────────────────────────────────
# Rule 2: generic risk / factual-boundary template detection
# ─────────────────────────────────────────────────────────────

# Generic risk/boundary phrases that, on their own, do not describe what
# happened. A body built only from these must not be used as an event summary.
_GENERIC_RISK_FRAGMENTS = (
    "该事件存在传播风险",
    "存在传播风险",
    "事实仍待核验",
    "事实待核验",
    "仍待核验",
    "待核实",
    "待核验",
    "需关注后续信息",
    "需关注后续",
    "关注后续",
)


def _program_template_texts() -> frozenset:
    """All program-constant risk/boundary strings that are never an event body."""
    texts = {RISK_NOTE_HIGH_HEAT}
    for meta in LABELS.values():
        boundary = meta.get("factual_boundary")
        if boundary:
            texts.add(boundary)
    return frozenset(t.strip() for t in texts if t)


_PROGRAM_TEMPLATE_TEXTS = _program_template_texts()


def is_generic_risk_template(text: Optional[str]) -> bool:
    """True if ``text`` is empty or only a generic risk/factual-boundary template.

    A concrete event summary describes *what happened*. This returns True for
    empty bodies, for exact matches against program-constant boundary text, and
    for short bodies dominated by a generic risk phrase. It returns False for a
    body that adds concrete event content beyond the template.
    """
    body = (text or "").strip()
    if not body:
        return True
    if body in _PROGRAM_TEMPLATE_TEXTS:
        return True
    for frag in _GENERIC_RISK_FRAGMENTS:
        if frag in body:
            # Dominated by the risk phrase (no real event content beyond it).
            stripped = body.replace(frag, "").strip(" 。，、；：;:,.　\"'“”‘’")
            if len(stripped) <= 4:
                return True
    return False


# ─────────────────────────────────────────────────────────────
# Rule 4: entertainment / sports / esports noise classification
# ─────────────────────────────────────────────────────────────

_ENTERTAINMENT_WORDS = (
    "明星", "综艺", "电视剧", "电影", "演唱会", "爱豆", "偶像", "粉丝",
    "饭圈", "塌房", "恋情", "官宣", "选秀", "晋级", "出道", "网红", "主播",
    "热恋", "分手", "结婚", "离婚", "代言", "新歌", "新剧", "票房", "颁奖",
)
_SPORTS_WORDS = (
    "足球", "篮球", "NBA", "世界杯", "联赛", "球员", "夺冠", "进球", "奥运",
    "金牌", "比分", "球队", "中超", "欧冠", "决赛", "晋级八强", "羽毛球",
    "乒乓球", "网球", "马拉松", "教练",
)
_ESPORTS_WORDS = (
    "电竞", "LPL", "LCK", "S赛", "全球总决赛", "战队", "选手", "英雄联盟",
    "KPL", "DOTA", "CSGO", "无畏契约", "出装", "对线", "团战", "Ban",
)

# Structural-relevance overrides: when present, an item may be promoted even if
# it is entertainment / sports / esports (platform governance, public safety,
# state/media policy, major censorship, geopolitical/institutional conflict,
# large-scale coordinated manipulation).
_STRUCTURAL_PROMOTION_WORDS = (
    "封禁", "封号", "下架", "监管", "审查", "处罚", "罚款", "约谈", "整治",
    "禁赛", "官方通报", "通报", "警方", "刑事", "立案", "安全事故", "踩踏",
    "伤亡", "死亡", "政策", "国家", "外交", "制裁", "操纵", "水军", "控评",
    "大规模", "造假", "造谣", "谣言", "网信办", "停播", "停职", "调查",
)

_CATEGORY_WORDS = {
    "entertainment": _ENTERTAINMENT_WORDS,
    "sports": _SPORTS_WORDS,
    "esports": _ESPORTS_WORDS,
}

_CATEGORY_LABELS = {
    "entertainment": "娱乐",
    "sports": "体育",
    "esports": "电竞",
}


def _contains_any(text: str, words) -> bool:
    low = text.lower()
    for w in words:
        if w.lower() in low:
            return True
    return False


def classify_category(text: str) -> Optional[str]:
    """Return ``entertainment`` / ``sports`` / ``esports`` for ``text`` or None."""
    blob = text or ""
    # esports before sports/entertainment: it overlaps with both vocabularies.
    if _contains_any(blob, _ESPORTS_WORDS):
        return "esports"
    if _contains_any(blob, _SPORTS_WORDS):
        return "sports"
    if _contains_any(blob, _ENTERTAINMENT_WORDS):
        return "entertainment"
    return None


def structural_reason(text: str) -> Optional[str]:
    """Return the first structural-promotion keyword found in ``text`` or None."""
    blob = (text or "").lower()
    for w in _STRUCTURAL_PROMOTION_WORDS:
        if w.lower() in blob:
            return w
    return None


def _item_blob(topic: str, samples: Optional[List[Dict]]) -> str:
    parts = [topic or ""]
    for s in samples or []:
        if isinstance(s, dict):
            parts.append(str(s.get("title", "")))
    return " ".join(parts)


def is_noise_item(topic: str, samples: Optional[List[Dict]] = None) -> bool:
    """True if the item is entertainment/sports/esports noise with no structural reason.

    A structural reason (governance, public safety, policy, censorship,
    geopolitical/institutional conflict, coordinated manipulation) keeps the
    item out of the noise bucket so it can be promoted.
    """
    blob = _item_blob(topic, samples)
    if structural_reason(blob):
        return False
    return classify_category(blob) is not None


# ─────────────────────────────────────────────────────────────
# Rule 5: domestic public-event confidence
# ─────────────────────────────────────────────────────────────


def domestic_confidence_status(
    *,
    has_A: bool,
    has_B: bool,
    has_C: bool,
    has_D: bool,
    d_tier_platform_count: int = 0,
    platform_count: int = 0,
) -> Optional[str]:
    """Derive a domestic-confidence status from evidence spread.

    DR v2 does not require an A/B international source before recognizing a
    domestic public event. When there is enough domestic public-source spread
    (a C-tier serious source plus D-tier social platforms), the item gets an
    explicit domestic status instead of being downgraded only because A/B is
    absent. Returns None when A/B is present (not a domestic-only case) or when
    the domestic spread is insufficient.
    """
    if has_A or has_B:
        return None
    if not (has_C and has_D):
        return None
    # C + D domestic public-source spread present.
    if d_tier_platform_count >= 3 or platform_count >= 5:
        return DOMESTIC_CONFIRMED
    if d_tier_platform_count >= 2 or platform_count >= 3:
        return DOMESTIC_HIGH_CONFIDENCE
    return DOMESTIC_PUBLIC_EVENT


def _domestic_status_from_evidence(detail: Dict[str, Any]) -> Optional[str]:
    present = set(detail.get("source_tiers_present", []) or [])
    by_tier = detail.get("sources_by_tier", {}) or {}
    return domestic_confidence_status(
        has_A="A" in present or bool(by_tier.get("A")),
        has_B="B" in present or bool(by_tier.get("B")),
        has_C="C" in present or bool(by_tier.get("C")),
        has_D="D" in present or bool(by_tier.get("D")),
        d_tier_platform_count=int(detail.get("d_tier_platform_count", 0) or 0),
        platform_count=int(detail.get("platform_count", 0) or 0),
    )


# ─────────────────────────────────────────────────────────────
# Model
# ─────────────────────────────────────────────────────────────


@dataclass
class DailyItem:
    """One main item in the digest, with risk separated from the event summary."""

    topic: str
    summary: str = ""          # what happened (concrete; never a risk template)
    risk_note: str = ""        # why verification/propagation risk exists
    evidence_note: str = ""    # source/platform spread
    status: str = ""           # confidence / status label
    next_watch: str = ""       # why it matters / next watch (when available)
    section: str = ""          # originating section key
    degraded: bool = False     # no concrete summary available


@dataclass
class SuppressedGroup:
    """A compact suppressed entry: one row per category (no label/explanation split)."""

    category: str
    count: int
    reason: str = ""
    examples: List[str] = field(default_factory=list)  # capped


@dataclass
class RawAppendix:
    """Capped, collapsed raw hotlist appendix."""

    collapsed: bool = True
    total_groups: int = 0
    shown_groups: int = 0
    truncated: bool = False
    groups: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DailyReportV2:
    """Structured Daily Report v2 artifact model (no Transport, no push)."""

    ai_backed: bool = False
    degraded: bool = False
    degraded_notice: str = ""
    overview: str = ""
    main_items: List[DailyItem] = field(default_factory=list)
    suppressed: List[SuppressedGroup] = field(default_factory=list)
    raw_appendix: RawAppendix = field(default_factory=RawAppendix)
    method_note: str = ""
    failed_ids: List[str] = field(default_factory=list)

    @property
    def suppressed_count(self) -> int:
        """Logical suppressed count = sum of group counts (must match rendering)."""
        return sum(g.count for g in self.suppressed)


# ─────────────────────────────────────────────────────────────
# Build (pure transformation)
# ─────────────────────────────────────────────────────────────


def _is_usable_environment_ai(ai_analysis: Any) -> bool:
    """Mirror of the newsletter predicate: usable environment AI result."""
    return (
        ai_analysis is not None
        and getattr(ai_analysis, "success", False) is True
        and getattr(ai_analysis, "report_style", "") == "environment"
    )


def _evidence_note(entry: Dict[str, Any]) -> str:
    parts: List[str] = []
    layers = (entry.get("source_layers") or "").strip()
    if layers and layers != "-":
        parts.append(f"层级 {layers}")
    count = entry.get("platform_count")
    if isinstance(count, int) and count > 0:
        parts.append(f"{count} 个来源")
    heat = (entry.get("highest_heat") or "").strip()
    if heat and heat != "-":
        parts.append(heat)
    if entry.get("sentiment_flag"):
        parts.append("情绪聚集")
    return " · ".join(parts)


def _status_for(entry: Dict[str, Any]) -> str:
    """Status label, upgraded to a domestic-confidence status when applicable."""
    detail = entry.get("evidence_detail") or {}
    domestic = _domestic_status_from_evidence(detail)
    if domestic:
        return _DOMESTIC_STATUS_LABELS.get(domestic, domestic)
    status = (entry.get("verification_status") or "").strip()
    return status


def _build_main_item(entry: Dict[str, Any], section: str) -> DailyItem:
    topic = str(entry.get("topic", "")).strip()
    # Rule 2: concrete body only from summary/analysis — never factual_boundary.
    body = (entry.get("summary") or entry.get("analysis") or "").strip()
    degraded = is_generic_risk_template(body)
    if degraded:
        body = ""
    # Rule 3: risk/boundary text is a separate field.
    risk = (entry.get("risk_note") or entry.get("factual_boundary") or "").strip()
    return DailyItem(
        topic=topic,
        summary=body,
        risk_note=risk,
        evidence_note=_evidence_note(entry),
        status=_status_for(entry),
        section=section,
        degraded=degraded,
    )


def _samples_of(entry: Dict[str, Any]) -> List[Dict]:
    detail = entry.get("evidence_detail") or {}
    return detail.get("sample_titles") or []


def build_daily_report_v2(
    ai_analysis: Optional[Any],
    report_data: Optional[Dict[str, Any]] = None,
) -> DailyReportV2:
    """Build the DR v2 model from an ``AIAnalysisResult`` and ``report_data``.

    Pure transformation: no I/O, no Transport, no notification import. Applies
    the overview, item-body, risk-separation, noise, domestic-confidence,
    suppressed-compactness, and raw-cap rules.
    """
    report_data = report_data or {}
    model = DailyReportV2()
    model.failed_ids = list(report_data.get("failed_ids") or [])

    ai_backed = _is_usable_environment_ai(ai_analysis)
    model.ai_backed = ai_backed

    if ai_backed:
        model.method_note = (getattr(ai_analysis, "method_note", "") or "").strip()
        overview = (getattr(ai_analysis, "overview", "") or "").strip()
        model.overview = overview
        # Rule 1: AI-backed reports require an overview.
        if not overview:
            model.degraded = True
            model.degraded_notice = DEGRADED_OVERVIEW_NOTICE

        # Per-category noise tally: real total count + capped examples. The
        # count must reflect every suppressed noise item, not just the examples.
        noise: Dict[str, Dict[str, Any]] = {}

        for section in SECTION_ORDER:
            entries = getattr(ai_analysis, section, None) or []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                topic = str(entry.get("topic", "")).strip()
                samples = _samples_of(entry)
                # Rule 4: entertainment/sports/esports → noise unless structural.
                if is_noise_item(topic, samples):
                    cat = classify_category(_item_blob(topic, samples)) or "noise"
                    bucket = noise.setdefault(cat, {"count": 0, "examples": []})
                    bucket["count"] += 1
                    if len(bucket["examples"]) < SUPPRESSED_EXAMPLE_CAP and topic:
                        bucket["examples"].append(topic)
                    continue
                model.main_items.append(_build_main_item(entry, section))

        model.suppressed = _build_suppressed(ai_analysis, noise)
    else:
        # No usable AI result: artifact-only, evidence/appendix shown, no
        # fabricated conclusions. This is distinct from the degraded state.
        model.degraded_notice = NO_AI_NOTICE

    model.raw_appendix = _build_raw_appendix(report_data.get("stats"))
    return model


def _build_suppressed(
    ai_analysis: Any,
    noise: Dict[str, Dict[str, Any]],
) -> List[SuppressedGroup]:
    """Build a compact suppressed list (Rule 6): one row per category."""
    groups: List[SuppressedGroup] = []

    # Sentiment-heavy items (program-suppressed by default).
    sentiment = [
        it for it in (getattr(ai_analysis, "sentiment_heavy", None) or [])
        if isinstance(it, dict)
    ]
    if sentiment:
        examples = [
            str(it.get("topic", "")).strip()
            for it in sentiment
            if str(it.get("topic", "")).strip()
        ]
        groups.append(
            SuppressedGroup(
                category="情绪聚集",
                count=len(sentiment),
                reason="主要是情绪聚集，不代表事实增量",
                examples=examples[:SUPPRESSED_EXAMPLE_CAP],
            )
        )

    # Noise pulled out of the main sections (entertainment/sports/esports).
    # count is the real per-category total; examples stay capped.
    for cat, bucket in noise.items():
        label = _CATEGORY_LABELS.get(cat, cat)
        groups.append(
            SuppressedGroup(
                category=label,
                count=int(bucket.get("count", 0)),
                reason="非信息环境结构性异常，默认不进入主榜",
                examples=list(bucket.get("examples", []))[:SUPPRESSED_EXAMPLE_CAP],
            )
        )

    # Background notes (below-threshold). These are already compact strings.
    notes = [
        str(n).strip()
        for n in (getattr(ai_analysis, "background_notes", None) or [])
        if str(n).strip()
    ]
    if notes:
        groups.append(
            SuppressedGroup(
                category="未达异常阈值",
                count=len(notes),
                reason="来源/热度未达异常阈值，仅计入盘面",
                examples=notes[:SUPPRESSED_EXAMPLE_CAP],
            )
        )

    return groups


def _build_raw_appendix(stats: Optional[List[Dict[str, Any]]]) -> RawAppendix:
    """Cap and collapse the raw hotlist into an appendix (Rule 7)."""
    stats = stats or []
    total = len(stats)
    shown = stats[:RAW_APPENDIX_MAX_GROUPS]
    groups: List[Dict[str, Any]] = []
    for grp in shown:
        titles = (grp.get("titles") or [])[:RAW_APPENDIX_MAX_TITLES]
        groups.append(
            {
                "word": grp.get("word", ""),
                "count": grp.get("count", 0),
                "titles": titles,
                "titles_truncated": len(grp.get("titles") or []) > RAW_APPENDIX_MAX_TITLES,
            }
        )
    return RawAppendix(
        collapsed=True,
        total_groups=total,
        shown_groups=len(groups),
        truncated=total > RAW_APPENDIX_MAX_GROUPS,
        groups=groups,
    )


# ─────────────────────────────────────────────────────────────
# Render (self-contained HTML, no scripts, no Transport)
# ─────────────────────────────────────────────────────────────

_MODE_LABELS = {
    "current": "当前盘面",
    "incremental": "当前盘面",
    "daily": "每日盘面",
}

_DR2_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#fff;--text:#111;--muted:#555;--faint:#999;
  --border:#e5e5e5;--risk:#b91c1c;--warn:#b45309;--link:#1d4ed8;--max:680px;
}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,"PingFang SC","Microsoft YaHei",sans-serif;
  font-size:15px;line-height:1.72;padding:0 20px}
.wrap{max-width:var(--max);margin:0 auto}
header{padding:32px 0 22px;border-bottom:2px solid var(--text);margin-bottom:36px}
.brand{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--faint)}
header h1{font-size:20px;font-weight:700;line-height:1.3;margin-top:6px}
.dateline{font-size:12px;color:var(--faint);margin-top:5px}
.degraded-notice{font-size:13px;color:var(--warn);margin-bottom:28px;padding:10px 12px;
  border:1px solid var(--warn);border-radius:3px;line-height:1.6}
.no-ai-notice{font-size:12px;color:var(--faint);margin-bottom:28px;padding:10px 0;border-bottom:1px solid var(--border)}
.overview-text{font-size:15px;line-height:1.8;color:var(--muted);margin-bottom:26px}
.sec{border-top:1px solid var(--border);padding-top:28px;margin-top:34px}
.sec-label{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);margin-bottom:14px}
.item{padding:16px 0;border-bottom:1px solid var(--border)}
.item:last-child{border-bottom:none}
.item-topic{font-weight:700;font-size:15px;line-height:1.4;margin-bottom:3px}
.item-status{font-size:11px;color:var(--faint);margin-bottom:6px}
.item-summary{font-size:14px;color:var(--muted);line-height:1.65}
.item-degraded{font-size:13px;color:var(--faint);font-style:italic;line-height:1.6}
.item-evidence{font-size:11px;color:var(--faint);margin-top:6px}
.item-risk{font-size:12px;color:var(--risk);margin-top:6px}
.item-risk::before{content:"\\2691  "}
.item-watch{font-size:12px;color:var(--muted);margin-top:6px}
.sup-row{display:flex;gap:8px;align-items:baseline;font-size:12px;padding:5px 0;border-bottom:1px solid #f5f5f5}
.sup-row:last-child{border-bottom:none}
.sup-cat{font-weight:600;color:var(--text);flex-shrink:0;min-width:88px}
.sup-count{font-size:11px;color:var(--faint);flex-shrink:0}
.sup-detail{flex:1;color:var(--muted)}
details.raw{margin-top:34px;border-top:1px solid var(--border);padding-top:20px}
details.raw summary{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);cursor:pointer}
.raw-trunc{font-size:11px;color:var(--faint);margin-top:10px}
.kw-group{margin-top:16px}
.kw-label{font-weight:600;font-size:13px;margin-bottom:5px}
.kw-count{font-size:11px;color:var(--faint);font-weight:400;margin-left:6px}
.title-row{display:flex;gap:8px;align-items:baseline;font-size:12px;padding:3px 0;border-bottom:1px solid #f5f5f5}
.t-title{flex:1;color:var(--muted)}
.t-source{font-size:10px;color:var(--faint);flex-shrink:0}
.notes-zone{margin-top:36px;padding-top:16px;border-top:1px solid var(--border);font-size:11px;color:var(--faint);line-height:1.7}
footer{margin-top:40px;padding:16px 0 28px;border-top:1px solid var(--border);
  font-size:11px;color:var(--faint);display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
"""


def _e(text: Any) -> str:
    if text is None:
        return ""
    return _html_lib.escape(str(text))


def _render_item(item: DailyItem) -> str:
    topic = f'<div class="item-topic">{_e(item.topic)}</div>'
    status = f'<div class="item-status">{_e(item.status)}</div>' if item.status else ""
    if item.degraded or not item.summary:
        body = f'<div class="item-degraded">{_e(DEGRADED_ITEM_NOTICE)}</div>'
    else:
        body = f'<div class="item-summary">{_e(item.summary)}</div>'
    evidence = (
        f'<div class="item-evidence">{_e(item.evidence_note)}</div>'
        if item.evidence_note
        else ""
    )
    risk = (
        f'<div class="item-risk">{_e(item.risk_note)}</div>'
        if item.risk_note
        else ""
    )
    watch = (
        f'<div class="item-watch">{_e(item.next_watch)}</div>'
        if item.next_watch
        else ""
    )
    return (
        f'<div class="item">{topic}{status}{body}{evidence}{risk}{watch}</div>'
    )


def _render_main_sections(model: DailyReportV2) -> str:
    if not model.main_items:
        return ""
    by_section: Dict[str, List[DailyItem]] = {}
    for it in model.main_items:
        by_section.setdefault(it.section, []).append(it)
    out: List[str] = []
    for section in SECTION_ORDER:
        items = by_section.get(section)
        if not items:
            continue
        label = _SECTION_TITLES.get(section, section)
        rows = "".join(_render_item(it) for it in items)
        out.append(f'<div class="sec"><div class="sec-label">{_e(label)}</div>{rows}</div>')
    return "\n".join(out)


def _render_suppressed(model: DailyReportV2) -> str:
    if not model.suppressed:
        return ""
    rows: List[str] = []
    for g in model.suppressed:
        detail = "；".join(g.examples) if g.examples else g.reason
        rows.append(
            f'<div class="sup-row">'
            f'<span class="sup-cat">{_e(g.category)}</span>'
            f'<span class="sup-count">{g.count}</span>'
            f'<span class="sup-detail">{_e(detail)}</span>'
            f"</div>"
        )
    body = "".join(rows)
    return (
        f'<div class="sec"><div class="sec-label">已抑制 · 合计 {model.suppressed_count}</div>'
        f"{body}</div>"
    )


def _render_raw_appendix(raw: RawAppendix) -> str:
    if not raw.groups:
        return ""
    parts: List[str] = []
    for grp in raw.groups:
        rows = ""
        for t in grp.get("titles", []):
            title = _e(t.get("title", "")) if isinstance(t, dict) else _e(t)
            source = _e(t.get("source_name", "")) if isinstance(t, dict) else ""
            rows += (
                f'<div class="title-row"><span class="t-title">{title}</span>'
                f'<span class="t-source">{source}</span></div>'
            )
        if grp.get("titles_truncated"):
            rows += '<div class="raw-trunc">… 更多条目已折叠</div>'
        parts.append(
            f'<div class="kw-group"><div class="kw-label">{_e(grp.get("word", ""))}'
            f'<span class="kw-count">{_e(grp.get("count", 0))} 条</span></div>{rows}</div>'
        )
    trunc = (
        f'<div class="raw-trunc">仅展示前 {raw.shown_groups} / {raw.total_groups} 组，余下已折叠</div>'
        if raw.truncated
        else ""
    )
    return (
        f'<details class="raw"><summary>原始热榜（已折叠 · 附录）</summary>'
        f"{''.join(parts)}{trunc}</details>"
    )


def render_daily_report_v2(
    report_data: Dict[str, Any],
    total_titles: int = 0,
    mode: str = "daily",
    update_info: Optional[Dict] = None,
    *,
    rss_items: Optional[List[Dict]] = None,
    rss_new_items: Optional[List[Dict]] = None,
    ai_analysis: Optional[Any] = None,
    get_time_func: Optional[Any] = None,
    **_ignored: Any,
) -> str:
    """Render the DR v2 artifact to self-contained HTML.

    Signature mirrors ``render_newsletter_report`` so DR v2 is a drop-in daily
    artifact renderer. Artifact-only: no scripts, no Transport, no push.
    """
    model = build_daily_report_v2(ai_analysis, report_data)
    generated_at: datetime = (
        get_time_func() if callable(get_time_func) else datetime.now()
    )
    mode_label = _MODE_LABELS.get(mode, mode)
    date_str = generated_at.strftime("%Y-%m-%d %H:%M")

    editorial = ""
    if model.degraded and model.degraded_notice:
        editorial += f'<div class="degraded-notice">{_e(model.degraded_notice)}</div>\n'
    elif not model.ai_backed and model.degraded_notice:
        editorial += f'<div class="no-ai-notice">{_e(model.degraded_notice)}</div>\n'

    if model.overview:
        editorial += f'<div class="overview-text">{_e(model.overview)}</div>\n'

    editorial += _render_main_sections(model)
    editorial += _render_suppressed(model)

    raw_html = _render_raw_appendix(model.raw_appendix)

    notes_parts: List[str] = []
    if model.failed_ids:
        notes_parts.append("获取失败：" + "、".join(_e(x) for x in model.failed_ids))
    if model.method_note:
        notes_parts.append(_e(model.method_note))
    notes_zone = (
        '<div class="notes-zone">' + "<br>".join(notes_parts) + "</div>"
        if notes_parts
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Ptilopsis Radar · {_e(mode_label)} · {_e(date_str)}</title>
<style>{_DR2_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand">Ptilopsis Radar · 信息环境监测</div>
  <h1>{_e(mode_label)} · v2</h1>
  <div class="dateline">{_e(date_str)}</div>
</header>
{editorial}
{raw_html}
{notes_zone}
<footer>
  <span>Ptilopsis Radar</span>
  <span>{_e(date_str)}</span>
</footer>
</div>
</body>
</html>"""
