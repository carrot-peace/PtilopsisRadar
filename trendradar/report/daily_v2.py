# coding=utf-8
"""
Daily Report v2 — artifact-only report model and renderer.

DR v2 belongs strictly to the Generation Plane. It turns the program-decided
evidence buckets + AI prose (``AIAnalysisResult``) and the collected
``report_data`` into a clean, structured daily artifact, then renders that
model to self-contained HTML.

Hard boundary (see ``docs/transport_boundaries.md``):
- This module does not import Telegram transport packages.
- It does not invoke a dispatch plan or sender.
- It does not use the CR or DR Telegram sink or environment configuration.
- It produces artifacts only; DR delivery is owned by the separate DR dispatch
  pipeline, with its own plan, gate, receipts, and cooldown policy.

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
    derive_radar_readout,
)
from trendradar.content_policy import (
    CATEGORY_LABELS as _CATEGORY_LABELS,
    classify_reader_category as classify_category,
    is_reader_noise as is_noise_item,
    reader_category as _category_for_item,
    reader_structural_reason as structural_reason,
)

# ─────────────────────────────────────────────────────────────
# Deterministic notices / labels (sober, not Telegram fallback text)
# ─────────────────────────────────────────────────────────────

#: Shown when an AI-backed report is missing its overview (Rule 1).
DEGRADED_OVERVIEW_NOTICE = (
    "AI 总览不可用；今日盘面改由程序统计生成，议题正文仅展示可核对的传播文本与元数据。"
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
    # Evidence is aggregated at topic-group level, so user-facing labels must
    # describe source coverage rather than imply event-level confirmation.
    DOMESTIC_CONFIRMED: "中文多源覆盖",
    DOMESTIC_HIGH_CONFIDENCE: "中文多平台覆盖",
    DOMESTIC_PUBLIC_EVENT: "中文源有呼应",
}

_READER_STATUS_LABELS: Dict[str, str] = {
    "跨层有呼应": "多层来源呼应",
    "高热待核实": "单点高热，来源待补",
    "情绪聚集": "情绪传播集中",
    "沉默温差": "社交端响应偏弱",
    "中文源呼应(缺A/B背景)": "中文平台热度上升",
}

_BUCKET_STATUS_FALLBACKS: Dict[str, str] = {
    "cross_layer_verified": "多层来源呼应",
    "high_heat_unverified": "单点高热，来源待补",
    "chinese_only_hot": "中文平台热度上升",
    "silence_gap": "社交端响应偏弱",
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

_NEWSLETTER_REDUNDANT_RISK_FRAGMENTS = (
    "当前仅能确认传播正在发生",
    "缺少一手或国际背景源",
    "不宜直接视为同一项重大事件",
    "不宜直接视为事实性重大事件",
    "背景源有信息，但中文社交平台未明显响应",
)


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
    # Old category-first prose is not an event summary.  Treat it as degraded
    # so the renderer falls back to one evidence headline per event instead of
    # leaking "group" language into the newsletter.
    if body.startswith(("本组", "该组", "此组")):
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


def _show_item_risk(text: str) -> bool:
    """Keep concrete cautions inline; leave repeated method caveats to the footer."""
    note = (text or "").strip()
    if not note or note in _PROGRAM_TEMPLATE_TEXTS:
        return False
    return not any(fragment in note for fragment in _NEWSLETTER_REDUNDANT_RISK_FRAGMENTS)


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


def _domestic_status_from_evidence(detail: Any) -> Optional[str]:
    if not isinstance(detail, dict):
        return None
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
    analysis: str = ""         # propagation structure; separate from summary
    risk_note: str = ""        # why verification/propagation risk exists
    evidence_note: str = ""    # source/platform spread
    status: str = ""           # confidence / status label
    next_watch: str = ""       # why it matters / next watch (when available)
    section: str = ""          # originating section key
    degraded: bool = False     # no concrete summary available
    samples: List[Dict[str, Any]] = field(default_factory=list)
    source_links: List[Dict[str, Any]] = field(default_factory=list)


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
    """Structured Daily Report v2 artifact model without transport behavior."""

    ai_backed: bool = False
    degraded: bool = False
    degraded_notice: str = ""
    overview: str = ""
    radar: Dict[str, Any] = field(default_factory=dict)
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


def _is_environment_result(ai_analysis: Any) -> bool:
    """Return true for both AI-backed and deterministic event results.

    A failed/truncated model response can still carry analyzer-owned event
    fallbacks.  Rendering those entries is safe; only AI-authored prose is
    gated by ``success``.
    """
    return bool(
        ai_analysis is not None
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


def _status_for(entry: Dict[str, Any], section: str = "") -> str:
    """Status label, upgraded to a domestic-confidence status when applicable."""
    raw_detail = entry.get("evidence_detail")
    detail = raw_detail if isinstance(raw_detail, dict) else {}
    domestic = _domestic_status_from_evidence(detail)
    if domestic:
        return _DOMESTIC_STATUS_LABELS.get(domestic, domestic)
    status = (entry.get("verification_status") or "").strip()
    if status:
        return _READER_STATUS_LABELS.get(status, status)
    return _BUCKET_STATUS_FALLBACKS.get(section, "")


def _program_overview(radar: Dict[str, Any]) -> str:
    """Render a deterministic brief from program-owned counts only."""
    if not radar:
        return ""
    anomaly = int(radar.get("anomaly", 0) or 0)
    parts: List[str] = []
    for key, label in (
        ("cross_layer", "多层来源呼应"),
        ("chinese_only", "中文源内部升温"),
        ("high_heat", "社交平台单点高热"),
        ("silence_gap", "背景源热、社交端静"),
    ):
        count = int(radar.get(key, 0) or 0)
        if count:
            parts.append(f"{count} 个{label}")
    detail = "、".join(parts) if parts else "未发现达到异常阈值的主信号"
    suppressed = int(radar.get("suppressed", 0) or 0)
    suffix = f"；另有 {suppressed} 个非重点项已折叠" if suppressed else ""
    return f"今日识别 {anomaly} 个异常信号：{detail}{suffix}。"


def _copy_samples(detail: Any) -> List[Dict[str, Any]]:
    if not isinstance(detail, dict):
        return []
    samples: List[Dict[str, Any]] = []
    for raw in detail.get("sample_titles", []) or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "") or "").strip()
        if not title:
            continue
        samples.append({
            "title": title,
            "source": str(raw.get("source", "") or "").strip(),
            "tier": str(raw.get("tier", "") or "").strip(),
            "trend": str(raw.get("trend", "") or "").strip(),
        })
        if len(samples) >= 3:
            break
    return samples


def _copy_source_links(detail: Any) -> List[Dict[str, Any]]:
    if not isinstance(detail, dict):
        return []
    links: List[Dict[str, Any]] = []
    for raw in detail.get("source_links", []) or []:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url", "") or "").strip()
        title = str(raw.get("title", "") or "").strip()
        if not url or not title:
            continue
        links.append({
            "title": title,
            "url": url,
            "source": str(raw.get("source", "") or "").strip(),
            "tier": str(raw.get("tier", "") or "").strip(),
            "rank": raw.get("rank"),
            "time": str(raw.get("time", "") or "").strip(),
        })
        if len(links) >= 5:
            break
    return links


def _build_main_item(entry: Dict[str, Any], section: str) -> DailyItem:
    topic = str(entry.get("topic", "")).strip()
    # Rule 2: the event/propagation summary and structural interpretation are
    # separate.  A generic risk boundary is accepted in neither field.
    body = (entry.get("summary") or "").strip()
    degraded = is_generic_risk_template(body)
    if degraded:
        body = ""
    analysis = (entry.get("analysis") or "").strip()
    if is_generic_risk_template(analysis):
        analysis = ""
    # Rule 3: risk/boundary text is a separate field.
    risk = (entry.get("risk_note") or entry.get("factual_boundary") or "").strip()
    raw_detail = entry.get("evidence_detail")
    detail = raw_detail if isinstance(raw_detail, dict) else {}
    return DailyItem(
        topic=topic,
        summary=body,
        analysis=analysis,
        risk_note=risk,
        evidence_note=_evidence_note(entry),
        status=_status_for(entry, section),
        section=section,
        degraded=degraded,
        samples=_copy_samples(detail),
        source_links=_copy_source_links(detail),
    )


def _samples_of(entry: Dict[str, Any]) -> List[Dict]:
    detail = entry.get("evidence_detail")
    if not isinstance(detail, dict):
        return []
    samples = detail.get("sample_titles") or []
    return samples if isinstance(samples, list) else []


def _refresh_radar_from_visible_content(model: DailyReportV2) -> None:
    """Make DR dashboard counts reflect post-filter visible content."""
    counts = {section: 0 for section in SECTION_ORDER}
    status_sections = {
        "多层来源呼应": "cross_layer_verified",
        "单点高热，来源待补": "high_heat_unverified",
        "中文平台热度上升": "chinese_only_hot",
        "中文专业来源": "chinese_only_hot",
        "中文多源覆盖": "chinese_only_hot",
        "中文多平台覆盖": "chinese_only_hot",
        "中文源有呼应": "chinese_only_hot",
        "社交端响应偏弱": "silence_gap",
    }
    for item in model.main_items:
        section = status_sections.get(item.status, item.section)
        if section in counts:
            counts[section] += 1
    model.radar.update({
        "anomaly": len(model.main_items),
        "cross_layer": counts.get("cross_layer_verified", 0),
        "high_heat": counts.get("high_heat_unverified", 0),
        "chinese_only": counts.get("chinese_only_hot", 0),
        "silence_gap": counts.get("silence_gap", 0),
        "suppressed": max(
            int(model.radar.get("suppressed", 0) or 0),
            model.suppressed_count,
        ),
    })


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

    environment_result = _is_environment_result(ai_analysis)
    ai_backed = _is_usable_environment_ai(ai_analysis)
    model.ai_backed = ai_backed
    overview_stats = (
        (getattr(ai_analysis, "overview_stats", {}) or {}) if ai_analysis else {}
    )
    if isinstance(overview_stats, dict) and overview_stats:
        model.radar = derive_radar_readout(overview_stats)

    if environment_result:
        if ai_backed:
            model.method_note = (getattr(ai_analysis, "method_note", "") or "").strip()
            overview = (getattr(ai_analysis, "overview", "") or "").strip()
            model.overview = overview
            # Rule 1: AI-backed reports require an overview.
            if not overview:
                model.degraded = True
                model.degraded_notice = DEGRADED_OVERVIEW_NOTICE
                model.overview = _program_overview(model.radar)
        else:
            # Preserve analyzer-owned event fallbacks, but never present a
            # partial/invalid model overview as completed AI analysis.
            overview = ""
            model.degraded = not bool(getattr(ai_analysis, "skipped", False))
            if model.degraded:
                model.degraded_notice = NO_AI_NOTICE
            model.overview = _program_overview(model.radar)

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
                    cat = _category_for_item(topic, samples) or "noise"
                    bucket = noise.setdefault(cat, {"count": 0, "examples": []})
                    bucket["count"] += 1
                    if len(bucket["examples"]) < SUPPRESSED_EXAMPLE_CAP and topic:
                        bucket["examples"].append(topic)
                    continue
                model.main_items.append(_build_main_item(entry, section))

        model.suppressed = _build_suppressed(ai_analysis, noise)
        _refresh_radar_from_visible_content(model)
        if not overview:
            model.overview = _program_overview(model.radar)
    else:
        # No usable AI result: artifact-only, evidence/appendix shown, no
        # fabricated conclusions. This is distinct from the degraded state.
        model.degraded_notice = NO_AI_NOTICE
        model.overview = _program_overview(model.radar)

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
  --paper:#fff;--ink:#202327;--text:#454a51;--muted:#747b84;--faint:#9da2a9;
  --link:#1d4ed8;--reading-size:15px;--max:720px;
}
html,body{background:var(--paper)}
body{color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  font-size:15px;line-height:1.72;padding:0 20px}
.wrap{max-width:var(--max);margin:0 auto;padding-bottom:28px}
.page-header{display:grid;grid-template-columns:1fr auto;grid-template-areas:"brand date" "title title";
  column-gap:24px;align-items:end;padding:34px 0 8px;margin-bottom:30px}
.brand{grid-area:brand;font-size:12px;font-weight:600;color:var(--ink)}
.page-header h1{grid-area:title;font-size:27px;font-weight:650;letter-spacing:-.025em;line-height:1.22;margin-top:13px}
.dateline{grid-area:date;font-size:11px;color:var(--faint);font-variant-numeric:tabular-nums}
.degraded-notice,.no-ai-notice{font-size:var(--reading-size);color:var(--text);margin:0 0 34px;line-height:1.75}
.degraded-notice::before,.no-ai-notice::before{content:"编者说明";display:inline-block;margin-right:9px;color:var(--text);font-weight:600}
.overview-label,.sec-label{font-size:20px;font-weight:600;color:var(--ink);line-height:1.4}
.overview-label{margin-bottom:4px}
.overview-text{font-size:var(--reading-size);line-height:1.8;color:var(--text)}
.sec{margin-top:30px}
.sec-label{margin-bottom:10px}
.item{padding:0}
.item+.item{margin-top:18px}
.item-topic{font-weight:650;font-size:var(--reading-size);line-height:1.45}
.item-summary{font-size:var(--reading-size);color:var(--text);line-height:1.65;margin-top:0}
.item-topic,.item-summary,.signal-row,.source-row{overflow-wrap:anywhere}
.item-degraded{font-size:var(--reading-size);color:var(--text);line-height:1.65}
.item-details{margin-top:7px}
.item-details>summary{font-size:11px;font-weight:500;line-height:1.4;color:var(--muted);cursor:pointer;list-style:none}
.item-details>summary::-webkit-details-marker{display:none}
.item-details>summary::marker{content:""}
.item-details>summary:hover{color:var(--ink)}
.item-meta{font-size:11px;color:var(--faint);margin-top:10px;font-variant-numeric:tabular-nums}
.item-analysis{font-size:12px;color:var(--text);margin-top:9px;line-height:1.65}
.item-label{display:inline-block;font-size:11px;font-weight:500;color:var(--muted);margin-right:8px}
.item-risk,.item-watch{font-size:12px;color:var(--muted);margin-top:9px;line-height:1.65}
.signals,.source-links{margin-top:13px}
.signals-label{font-size:11px;font-weight:500;color:var(--muted);margin-bottom:5px}
.signal-row,.source-row{font-size:12px;color:var(--text);line-height:1.55;padding:4px 0}
.signal-row+.signal-row,.source-row+.source-row{margin-top:5px}
.signal-meta,.source-meta{display:block;font-size:10px;color:var(--faint);margin-top:2px}
.source-links-label{font-size:11px;font-weight:500;color:var(--muted);margin-bottom:5px}
details.raw summary,.cut-details summary{font-size:var(--reading-size);font-weight:400;color:var(--muted);cursor:pointer;list-style:none}
details.raw summary::-webkit-details-marker,.cut-details summary::-webkit-details-marker{display:none}
details.raw summary::marker,.cut-details summary::marker{content:""}
details.raw summary:hover,.cut-details summary:hover{color:var(--text)}
.editorial-cut{font-size:var(--reading-size);color:var(--text);line-height:1.8}
.cut-details{margin-top:3px}
.cut-item{padding:4px 0}
.cut-item+.cut-item{margin-top:9px}
.cut-title{font-size:var(--reading-size);font-weight:600;color:var(--ink)}
.cut-detail{font-size:var(--reading-size);color:var(--text);line-height:1.75;margin-top:3px}
details.raw{margin-top:12px}
.raw-trunc{font-size:11px;color:var(--faint);margin-top:8px}
.kw-group{margin-top:18px}
.kw-label{font-weight:600;font-size:var(--reading-size);margin-bottom:5px}
.kw-count{font-size:10px;color:var(--faint);font-weight:400;margin-left:6px}
.title-row{font-size:var(--reading-size);padding:4px 0}
.title-row+.title-row{margin-top:5px}
.t-title{display:block;color:var(--text);line-height:1.55}
.t-source{display:block;font-size:10px;color:var(--faint);margin-top:2px}
.notes-zone{margin-top:34px;font-size:11px;color:var(--faint);line-height:1.7}
footer{margin-top:34px;padding-bottom:18px;font-size:10px;color:var(--faint);
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
a{color:var(--link);text-decoration:none}
a:hover{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
@media(max-width:560px){
  body{padding:0 18px}
  .page-header{grid-template-areas:"brand" "title" "date";grid-template-columns:1fr;padding-top:25px}
  .page-header h1{font-size:21px;margin-top:10px}
  .dateline{margin-top:7px}
}
@media print{body{padding:0}.wrap{max-width:none;padding:0 22px}details{break-inside:avoid}}
"""


def _e(text: Any) -> str:
    if text is None:
        return ""
    return _html_lib.escape(str(text))


def _display_topic(topic: str) -> str:
    for prefix in ("高热未归类·", "未归类·", "背景-"):
        if topic.startswith(prefix):
            return topic[len(prefix):].strip() or topic
    return topic


def _render_samples(item: DailyItem) -> str:
    if not item.samples:
        return ""
    rows: List[str] = []
    for sample in item.samples:
        meta = " · ".join(
            part for part in (
                sample.get("source", ""),
                sample.get("trend", ""),
            ) if part
        )
        meta_html = f'<span class="signal-meta">{_e(meta)}</span>' if meta else ""
        rows.append(
            f'<div class="signal-row">{_e(sample.get("title", ""))}{meta_html}</div>'
        )
    return (
        f'<div class="signals"><div class="signals-label">代表性传播文本 · {len(rows)}</div>'
        f'{"".join(rows)}</div>'
    )


def _render_source_links(
    item: DailyItem,
    source_links: Optional[List[Dict[str, Any]]] = None,
) -> str:
    links = item.source_links if source_links is None else source_links
    if not links:
        return ""
    rows: List[str] = []
    for source in links:
        url = str(source.get("url", "") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        meta = " · ".join(
            str(part) for part in (
                source.get("source", ""),
                f"第{source.get('rank')}名" if source.get("rank") else "",
                source.get("time", ""),
            ) if part
        )
        meta_html = f'<span class="source-meta">{_e(meta)}</span>' if meta else ""
        rows.append(
            f'<div class="source-row"><a href="{_e(url)}" target="_blank" rel="noopener noreferrer">'
            f'{_e(source.get("title", ""))}</a>{meta_html}</div>'
        )
    if not rows:
        return ""
    return (
        f'<div class="source-links"><div class="source-links-label">证据链接 · {len(rows)}</div>'
        f'{"".join(rows)}</div>'
    )


def _render_item_details(
    item: DailyItem,
    *,
    include_samples: bool = True,
    source_links: Optional[List[Dict[str, Any]]] = None,
    extra_meta: Optional[List[str]] = None,
) -> str:
    meta_parts = [
        part for part in [*(extra_meta or []), item.status, item.evidence_note]
        if part
    ]
    meta = f'<div class="item-meta">{_e(" · ".join(meta_parts))}</div>' if meta_parts else ""
    analysis = (
        f'<div class="item-analysis"><span class="item-label">传播结构：</span>{_e(item.analysis)}</div>'
        if item.analysis
        else ""
    )
    risk = (
        f'<div class="item-risk"><span class="item-label">核验提示：</span>{_e(item.risk_note)}</div>'
        if _show_item_risk(item.risk_note)
        else ""
    )
    watch = (
        f'<div class="item-watch"><span class="item-label">后续关注：</span>{_e(item.next_watch)}</div>'
        if item.next_watch
        else ""
    )
    samples = _render_samples(item) if include_samples else ""
    links = _render_source_links(item, source_links)
    content = f"{meta}{analysis}{risk}{watch}{samples}{links}"
    if not content:
        return ""
    return f'<details class="item-details"><summary>来源与核验</summary>{content}</details>'


def _render_item(item: DailyItem) -> str:
    if (item.degraded or not item.summary) and item.samples:
        articles: List[str] = []
        for sample in item.samples:
            sample_title = str(sample.get("title", "") or "").strip()
            if not sample_title:
                continue
            matching_links = [
                source for source in item.source_links
                if str(source.get("title", "") or "").strip() == sample_title
            ]
            sample_meta = [
                str(part) for part in (sample.get("source", ""), sample.get("trend", ""))
                if part
            ]
            details = _render_item_details(
                item,
                include_samples=False,
                source_links=matching_links,
                extra_meta=sample_meta,
            )
            articles.append(
                f'<article class="item"><h3 class="item-topic">{_e(sample_title)}</h3>'
                f'<div class="item-summary">暂无可用摘要；仅保留平台原标题供核对。</div>'
                f'{details}</article>'
            )
        if articles:
            return "".join(articles)

    topic = f'<h3 class="item-topic">{_e(_display_topic(item.topic))}</h3>'
    if item.degraded or not item.summary:
        body = f'<div class="item-degraded">{_e(DEGRADED_ITEM_NOTICE)}</div>'
    else:
        body = f'<div class="item-summary">{_e(item.summary)}</div>'
    details = _render_item_details(item)
    return f'<article class="item">{topic}{body}{details}</article>'


def _render_main_sections(model: DailyReportV2) -> str:
    if not model.main_items:
        return ""
    # Reader-facing content is one event stream.  Program buckets remain on
    # the model for evidence policy and counting, but never become categories
    # in the newsletter.
    rows = "".join(_render_item(it) for it in model.main_items)
    return f'<section class="sec"><h2 class="sec-label">重点</h2>{rows}</section>'


def _render_suppressed(model: DailyReportV2) -> str:
    if not model.suppressed:
        return ""
    rows: List[str] = []
    for g in model.suppressed:
        examples = "；".join(g.examples)
        detail = g.reason
        if examples:
            detail = f"{g.reason}。例：{examples}" if g.reason else examples
        rows.append(
            f'<article class="cut-item">'
            f'<h3 class="cut-title">{_e(g.category)} · {g.count} 条</h3>'
            f'<p class="cut-detail">{_e(detail)}</p>'
            f"</article>"
        )
    body = "".join(rows)
    return (
        f'<section class="sec"><h2 class="sec-label">编辑取舍</h2>'
        f'<p class="editorial-cut">今日另有 {model.suppressed_count} 个条目未进入正文。它们以常规娱乐、体育、电竞内容或未达异常阈值的背景项为主。</p>'
        f'<details class="cut-details"><summary>查看折叠原因与示例</summary>{body}</details></section>'
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
        f'<details class="raw"><summary>数据附录 · 原始热榜</summary>'
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
    artifact renderer. It contains no scripts or transport behavior.
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
        editorial += '<h2 class="overview-label">导读</h2>\n'
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
<header class="page-header">
  <div class="brand">Ptilopsis Radar · 信息环境监测</div>
  <h1>信息环境日报</h1>
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
