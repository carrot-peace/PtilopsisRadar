# coding=utf-8
"""
Current Dashboard 模块（newsletter 风格）

生成轻量"当前盘面"页面与发布安全的摘要缓存，用于远程主动查看当前盘面。

设计约束（见 plan）：
- 与 alert cooldown / notify_labels 解耦：直接读 AIAnalysisResult 全量 buckets，
  不调用 apply_alert_cooldown / select_environment_alert_items。
- 只复用数据层的 derive_radar_readout 与 SECTION_ORDER（evidence.py 的公开常量），
  渲染与 CSS 在本模块内自实现。
- build_dashboard_state 产出的是**发布安全摘要**：禁止包含 source_links、
  sample_titles、evidence_detail、sources_by_tier、原始 RSS/热榜 URL，
  以及任何 db/log/alert_state/secrets。
- dashboard HTML 是公开发布页：只透出热榜标题/来源/排名（公开榜单信息，无 URL）
  与 AI 分析文字（topic/highest_heat/risk_note，无敏感字段）。
"""

import html as _html_lib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from trendradar.ai.evidence import SECTION_ORDER, derive_radar_readout
from trendradar.content_policy import is_reader_noise

# state.json schema 版本（future /now 据此读取）。v2 将 ``label``
# 从关键词组 bucket 改为事件自身的读者状态。
DASHBOARD_SCHEMA_VERSION = 2

# 发布根落地页 output/public/index.html：静态、幂等。
# 路由：current → dashboard（current/index.html）；daily → full report（daily/full.html）。
PUBLIC_LANDING_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Ptilopsis Radar</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#fff;color:#111;padding:0 20px;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;line-height:1.6}
.wrap{max-width:680px;margin:0 auto;padding-top:48px}
.brand{font-size:12px;font-weight:600;color:#555}
h1{font-size:25px;font-weight:650;margin:10px 0 26px}
a.card{display:block;padding:8px 0;margin-bottom:10px;
  text-decoration:none;color:#111}
a.card:hover .t{text-decoration:underline;text-underline-offset:3px}
a.card .t{font-size:16px;font-weight:700}
a.card .d{font-size:13px;color:#777;margin-top:4px}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand">Ptilopsis Radar · 信息环境监测</div>
  <h1>盘面入口</h1>
  <a class="card" href="current/index.html">
    <div class="t">当前盘面 →</div>
    <div class="d">随刷新更新，远程查看当前榜单状态与异常信号</div>
  </a>
  <a class="card" href="daily/full.html">
    <div class="t">每日盘面 →</div>
    <div class="d">每日汇总完整报告</div>
  </a>
</div>
</body>
</html>"""

# bucket 只是历史产物的兼容兜底；新事件优先使用自身
# ``verification_status``，避免拆分后仍被旧议题组标签覆盖。
_BUCKET_STATUS_FALLBACKS: Dict[str, str] = {
    "cross_layer_verified": "多层来源呼应",
    "high_heat_unverified": "单点高热，来源待补",
    "chinese_only_hot": "中文平台热度上升",
    "silence_gap": "社交端响应偏弱",
}

_READER_STATUS_LABELS: Dict[str, str] = {
    "跨层有呼应": "多层来源呼应",
    "高热待核实": "单点高热，来源待补",
    "情绪聚集": "情绪传播集中",
    "沉默温差": "社交端响应偏弱",
    "中文源呼应(缺A/B背景)": "中文平台热度上升",
}

_ABSOLUTE_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_DASHBOARD_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --paper:#fff;--ink:#202327;--text:#454a51;--muted:#747b84;--faint:#9da2a9;--risk:#8a3b3b;
  --reading-size:15px;--max:720px;
}
body{
  background:var(--paper);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  font-size:15px;line-height:1.72;padding:0 20px;
}
.wrap{max-width:var(--max);margin:0 auto;padding-bottom:28px}
.cur-head{display:grid;grid-template-columns:1fr auto;grid-template-areas:"brand date" "title title";
  column-gap:24px;align-items:end;padding:34px 0 8px;margin-bottom:28px}
.cur-brand{grid-area:brand;font-size:12px;font-weight:600;color:var(--ink)}
.cur-ts{font-size:11px;color:var(--faint)}
.cur-head h1{grid-area:title;font-size:25px;font-weight:650;letter-spacing:-.02em;line-height:1.25;margin-top:12px}

.cur-lead{font-size:var(--reading-size);color:var(--text);margin-bottom:24px}
.cur-lead strong{font-size:var(--reading-size);font-weight:650;color:var(--ink)}
.cur-overview{margin-bottom:28px}
.cur-overview .sec-label{margin-bottom:4px}
.cur-overview p{font-size:var(--reading-size);line-height:1.8;color:var(--text)}

.sec-label{font-size:20px;font-weight:600;color:var(--ink);line-height:1.4;margin-bottom:10px}

.cur-row+.cur-row{margin-top:18px}
.cur-row,.track-row{min-width:0}
.cur-topic{font-size:var(--reading-size);font-weight:650;color:var(--ink);line-height:1.45}
.cur-summary{font-size:var(--reading-size);color:var(--text);line-height:1.68}
.cur-topic,.cur-summary,.track-title{overflow-wrap:anywhere}
.cur-meta{font-size:11px;color:var(--faint);line-height:1.45;margin-top:6px}
.cur-risk{font-size:11px;color:var(--muted);line-height:1.55;margin-top:5px}
.t-new{font-size:9px;font-weight:700;color:var(--risk);padding:0 3px;
  border:1px solid var(--risk);border-radius:2px}

.cur-track{margin-top:26px}
.cur-track>summary{font-size:var(--reading-size);font-weight:400;color:var(--muted);cursor:pointer;list-style:none}
.cur-track>summary::-webkit-details-marker{display:none}
.cur-track>summary::marker{content:""}
.track-body{margin-top:9px}
.track-row+.track-row{margin-top:12px}
.track-title{font-size:var(--reading-size);font-weight:600;color:var(--ink);line-height:1.5}
.track-meta{font-size:10px;color:var(--faint);line-height:1.5;margin-top:2px}

.cur-sup{font-size:11px;color:var(--faint);margin-top:24px;line-height:1.7}

.cur-empty{font-size:var(--reading-size);color:var(--muted);padding:4px 0}

a{color:var(--ink);text-decoration:underline}
@media(max-width:560px){
  body{padding:0 18px}
  .cur-head{grid-template-columns:1fr;grid-template-areas:"brand" "title" "date";padding-top:25px}
  .cur-ts{margin-top:7px}
}
"""


def _esc(text: Any) -> str:
    """转义 HTML 特殊字符。"""
    if text is None:
        return ""
    return _html_lib.escape(str(text))


def _public_text(text: Any) -> str:
    """Normalize a scalar for public HTML/state and remove absolute URLs."""
    if text is None:
        return ""
    return _ABSOLUTE_URL_RE.sub("", str(text)).strip()


def _group_for_mode(mode: str) -> str:
    """run mode → 发布 group。current/incremental → current；daily → daily。"""
    return "daily" if mode == "daily" else "current"


def _is_environment(ai_analysis: Optional[Any]) -> bool:
    """Accept deterministic event fallbacks as environment results.

    ``success`` gates AI-authored prose, not analyzer-owned evidence entries.
    """
    return bool(
        ai_analysis is not None
        and getattr(ai_analysis, "report_style", "") == "environment"
    )


def _is_ai_backed(ai_analysis: Optional[Any]) -> bool:
    return bool(
        _is_environment(ai_analysis)
        and getattr(ai_analysis, "success", False) is True
        and str(getattr(ai_analysis, "overview", "") or "").strip()
    )


def _analysis_status(ai_analysis: Optional[Any]) -> str:
    if not _is_environment(ai_analysis):
        return "unavailable"
    if bool(getattr(ai_analysis, "skipped", False)):
        return "skipped"
    if _is_ai_backed(ai_analysis):
        return "ok"
    return "degraded"


def _program_overview(radar: Dict[str, Any]) -> str:
    """Build a deterministic lead without reusing partial model prose."""
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
    return f"本轮识别 {anomaly} 个异常事件：{detail}。"


def _reader_status(item: Dict[str, Any], bucket: str) -> str:
    """使用事件自身核验状态；仅对旧产物回退到 bucket。"""
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


def _event_bucket(item: Dict[str, Any], fallback: str) -> str:
    """把事件状态映射回统计维度，不继承错置的议题组 bucket。"""
    status = str(item.get("verification_status", "") or "").strip()
    return {
        "跨层有呼应": "cross_layer_verified",
        "高热待核实": "high_heat_unverified",
        "中文源呼应(缺A/B背景)": "chinese_only_hot",
        "中文专业来源": "chinese_only_hot",
        "沉默温差": "silence_gap",
    }.get(status, fallback)


def _event_summary(item: Dict[str, Any]) -> str:
    """只返回事件级摘要，拒绝旧的分类组统一文案。"""
    text = _public_text(item.get("summary", ""))
    if text and not text.startswith(("本组", "该组", "此组")):
        return text
    return ""


def _evidence_samples(item: Dict[str, Any]) -> List[Any]:
    detail = item.get("evidence_detail")
    if not isinstance(detail, dict):
        return []
    samples = detail.get("sample_titles") or []
    return samples if isinstance(samples, list) else []


def _iter_environment_items(ai_analysis: Any):
    for bucket in SECTION_ORDER:
        for item in (getattr(ai_analysis, bucket, None) or []):
            if isinstance(item, dict):
                yield bucket, item


def _is_visible_item(item: Dict[str, Any]) -> bool:
    return not is_reader_noise(
        str(item.get("topic", "") or ""), _evidence_samples(item)
    )


def _iter_visible_items(ai_analysis: Any):
    for bucket, item in _iter_environment_items(ai_analysis):
        if _is_visible_item(item):
            yield bucket, item


def _safe_item(item: Dict[str, Any], bucket: str) -> Dict[str, Any]:
    """从 bucket item 中**按白名单**挑出发布安全字段，绝不透传原始 dict。"""
    out: Dict[str, Any] = {"label": _public_text(_reader_status(item, bucket))}
    topic = _public_text(item.get("topic", ""))
    if topic:
        out["topic"] = topic
    summary = _event_summary(item)
    if summary:
        out["summary"] = summary
    for key in ("highest_heat", "source_layers"):
        value = _public_text(item.get(key, ""))
        if value:
            out[key] = value
    platform_count = item.get("platform_count")
    if isinstance(platform_count, int) and not isinstance(platform_count, bool):
        out["platform_count"] = platform_count
    if "sentiment_flag" in item:
        out["sentiment_flag"] = bool(item.get("sentiment_flag"))
    return out


def _collect_safe_items(ai_analysis: Any) -> List[Dict[str, Any]]:
    """按 SECTION_ORDER 收集各栏目 item 的发布安全摘要（扁平，带 label）。"""
    return [
        _safe_item(item, bucket)
        for bucket, item in _iter_visible_items(ai_analysis)
    ]


def _event_radar(ai_analysis: Any) -> Dict[str, Any]:
    """从实际事件条目重算可见计数，避免沿用拆分前议题组数。"""
    radar = derive_radar_readout(getattr(ai_analysis, "overview_stats", {}) or {})
    counts = {bucket: 0 for bucket in SECTION_ORDER}
    total = 0
    noise_count = 0
    for fallback, item in _iter_environment_items(ai_analysis):
        if not _is_visible_item(item):
            noise_count += 1
            continue
        total += 1
        bucket = _event_bucket(item, fallback)
        if bucket in counts:
            counts[bucket] += 1
    radar.update({
        "anomaly": total,
        "cross_layer": counts.get("cross_layer_verified", 0),
        "high_heat": counts.get("high_heat_unverified", 0),
        "chinese_only": counts.get("chinese_only_hot", 0),
        "silence_gap": counts.get("silence_gap", 0),
        "suppressed": int(radar.get("suppressed", 0) or 0) + noise_count,
    })
    return radar


def _fmt_display(generated_at: datetime) -> str:
    return generated_at.strftime("%Y-%m-%d %H:%M")


def _rep_rank(title: Dict[str, Any]) -> Optional[int]:
    """从 ranks 历史列表取代表位次（最高位 = 最小数字）。"""
    ranks = title.get("ranks") or []
    nums = [r for r in ranks if isinstance(r, int)]
    return min(nums) if nums else None


# ── 公开 API ──────────────────────────────────────────────────────────────


def build_dashboard_state(
    ai_analysis: Optional[Any],
    report_metadata: Optional[Dict[str, Any]],
    generated_at: datetime,
    mode: str,
) -> Dict[str, Any]:
    """
    构建 current/daily 盘面的**发布安全摘要缓存**（future /now 数据源）。

    禁止包含 source_links / sample_titles / evidence_detail / sources_by_tier /
    原始 URL / db / log / alert_state / secrets。
    """
    meta = report_metadata or {}
    radar: Dict[str, Any] = {}
    overview = ""
    top_items: List[Dict[str, Any]] = []
    analysis_status = _analysis_status(ai_analysis)

    if _is_environment(ai_analysis):
        radar = _event_radar(ai_analysis)
        overview = (
            (getattr(ai_analysis, "overview", "") or "").strip()
            if _is_ai_backed(ai_analysis)
            else _program_overview(radar)
        )
        overview = _public_text(overview)
        top_items = _collect_safe_items(ai_analysis)

    return {
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "mode": mode,
        "group": _group_for_mode(mode),
        "generated_at": generated_at.isoformat(),
        "analysis_status": analysis_status,
        "report_style": getattr(ai_analysis, "report_style", "environment")
        if ai_analysis is not None
        else "none",
        "overview": overview,
        "radar": radar,
        "top_items": top_items,
        "counts": {
            "hotlist_total": meta.get("hotlist_total", 0),
            "platform_total": meta.get("platform_total", 0),
            "rss_matched_count": meta.get("rss_matched_count", 0),
        },
    }


def _render_signal_rows(ai_analysis: Any) -> str:
    """事件列表：逐条标题 + 详细摘要，状态放入次要元数据。"""
    rows: List[str] = []
    for bucket, item in _iter_visible_items(ai_analysis):
        safe = _safe_item(item, bucket)
        topic = _esc(safe.get("topic", ""))
        summary = _esc(safe.get("summary", ""))
        heat = _esc(safe.get("highest_heat", ""))
        risk = _public_text(item.get("risk_note", ""))
        status = _esc(safe.get("label", ""))
        count = safe.get("platform_count")
        meta_parts = [status] if status else []
        if isinstance(count, int) and count > 0:
            meta_parts.append(f"{count} 个来源")
        if heat and heat != "-":
            meta_parts.append(heat)
        meta_html = (
            f'<div class="cur-meta">{" · ".join(meta_parts)}</div>'
            if any(meta_parts)
            else ""
        )
        summary_html = f'<div class="cur-summary">{summary}</div>' if summary else ""
        risk_html = f'<div class="cur-risk">{_esc(risk)}</div>' if risk else ""
        rows.append(
            f'<article class="cur-row"><h3 class="cur-topic">{topic}</h3>'
            f'{summary_html}{meta_html}{risk_html}</article>'
        )
    return "\n".join(rows)


def _render_hotlist_rows(stats: Optional[List[Dict[str, Any]]]) -> str:
    """热榜追踪：每个关键词组取最热标题 + 来源摘要行（source #rank [新]）。"""
    rows: List[str] = []
    for grp in (stats or []):
        word = _esc(_public_text(grp.get("word", "")))
        titles = grp.get("titles", []) or []
        if not titles:
            continue
        top_title = _esc(_public_text(titles[0].get("title", "")))
        src_parts: List[str] = []
        for t in titles[:3]:
            src = _esc(_public_text(t.get("source_name", "")))
            rank = _rep_rank(t)
            rank_str = f"&nbsp;#{rank}" if rank is not None else ""
            badge = ' <span class="t-new">新</span>' if t.get("is_new") else ""
            src_parts.append(f"{src}{rank_str}{badge}")
        extra = (
            f" <span style=\"color:var(--faint)\">+{len(titles) - 3}条</span>"
            if len(titles) > 3
            else ""
        )
        src_line = " · ".join(src_parts) + extra
        rows.append(
            f'<div class="track-row"><div class="track-title">{top_title}</div>'
            f'<div class="track-meta">{word} · {src_line}</div>'
            f"</div>"
        )
    return "\n".join(rows)


def _render_rss_rows(rss_items: Optional[List[Dict[str, Any]]]) -> str:
    """RSS 追踪：每个 RSS 关键词组取最新一条 + 来源/时间。"""
    rows: List[str] = []
    for grp in (rss_items or []):
        word = _esc(_public_text(grp.get("word", "")))
        titles = grp.get("titles", []) or []
        if not titles:
            continue
        top = titles[0]
        top_title = _esc(_public_text(top.get("title", "")))
        src = _esc(_public_text(top.get("source_name", "")))
        time_d = _esc(_public_text(top.get("time_display", "")))
        extra = (
            f" <span style=\"color:var(--faint)\">+{len(titles) - 1}条</span>"
            if len(titles) > 1
            else ""
        )
        rows.append(
            f'<div class="track-row"><div class="track-title">{top_title}</div>'
            f'<div class="track-meta">{word} · {src}&nbsp;{time_d}{extra}</div>'
            f"</div>"
        )
    return "\n".join(rows)


def render_current_dashboard_html(
    ai_analysis: Optional[Any],
    report_metadata: Optional[Dict[str, Any]],
    generated_at: datetime,
    mode: str,
    stats: Optional[List[Dict[str, Any]]] = None,
    rss_items: Optional[List[Dict[str, Any]]] = None,
    full_href: str = "full.html",
) -> str:
    """
    渲染自包含的轻量盘面页（newsletter 风格、单文件、内联 CSS、无外部引用）。

    - environment 样式：异常信号列表 + 热榜/RSS 追踪 + 已抑制脚注。
    - 无异常信号：lead 改"未检测到异常信号"，仍展示热榜/RSS 追踪。
    - ai_analysis is None：降级提示 + 热榜/RSS 追踪。

    stats / rss_items 为发布安全的追踪数据（公开榜单信息，无 URL）。
    任何 mode 都能出页，不受 cooldown / notify_labels 影响。
    """
    group = _group_for_mode(mode)
    title = "每日盘面" if group == "daily" else "当前盘面"
    page_title = "信息环境日报" if group == "daily" else "信息环境盘面"
    display_time = _fmt_display(generated_at)

    # ── lead + 异常信号区 ──
    anomaly = 0
    signal_section = ""
    sup_html = ""
    overview_html = ""
    if _is_environment(ai_analysis):
        analysis_status = _analysis_status(ai_analysis)
        radar = _event_radar(ai_analysis)
        anomaly = radar.get("anomaly", 0)
        suppressed_n = radar.get("suppressed", 0)
        overview = (
            str(getattr(ai_analysis, "overview", "") or "").strip()
            if _is_ai_backed(ai_analysis)
            else _program_overview(radar)
        )
        overview = _public_text(overview)
        if overview:
            overview_html = (
                '<section class="cur-overview"><h2 class="sec-label">导读</h2>'
                f'<p>{_esc(overview)}</p></section>'
            )

        if anomaly > 0:
            signals_html = _render_signal_rows(ai_analysis)
            signal_section = (
                '<section><h2 class="sec-label">重点</h2>'
                f'<div class="cur-signals">{signals_html}</div></section>'
            )
            degraded_note = (
                " AI 摘要不可用，当前正文为程序证据回退。"
                if analysis_status == "degraded"
                else ""
            )
            lead_html = (
                f'<div class="cur-lead">{_esc(title)}共有 '
                f'<strong>{anomaly} 个事件</strong>进入重点。{degraded_note}</div>'
            )
        elif analysis_status in {"ok", "skipped"}:
            lead_html = f'<div class="cur-lead">{_esc(title)} · 未检测到异常信号</div>'
        else:
            lead_html = (
                f'<div class="cur-lead">{_esc(title)} · '
                "AI 摘要不可用，当前没有可展示的事件</div>"
            )

        # 已抑制脚注
        sup_names: List[str] = []
        for _bucket, item in _iter_environment_items(ai_analysis):
            if not _is_visible_item(item):
                topic = _public_text(item.get("topic", ""))
                if topic:
                    sup_names.append(_esc(topic))
        for item in (getattr(ai_analysis, "sentiment_heavy", None) or []):
            t = _public_text(item.get("topic", "")) if isinstance(item, dict) else ""
            if t:
                sup_names.append(_esc(t))
        for note in (getattr(ai_analysis, "background_notes", None) or []):
            note = _public_text(note)
            if note:
                short = note[:28] + ("…" if len(note) > 28 else "")
                sup_names.append(_esc(short))
        if sup_names:
            sup_html = (
                f'<div class="cur-sup">已抑制 {suppressed_n} · '
                f'{"　·　".join(sup_names)}</div>'
            )
    else:
        lead_html = (
            f'<div class="cur-lead">{_esc(title)} · '
            "本次未生成信息环境监测盘面</div>"
        )

    # ── 热榜 / RSS 追踪区 ──
    hotlist_rows = _render_hotlist_rows(stats)
    rss_rows = _render_rss_rows(rss_items)
    tracking_html = ""
    if hotlist_rows or rss_rows:
        inner = "\n".join(x for x in (hotlist_rows, rss_rows) if x)
        tracking_html = (
            '<details class="cur-track"><summary>数据附录 · 原始热榜</summary>'
            f'<div class="track-body">{inner}</div></details>'
        )

    # 完全无内容时的兜底
    if not signal_section and not tracking_html:
        tracking_html = '<div class="cur-empty">当前暂无可展示的盘面数据。</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{_esc(title)} · Ptilopsis Radar</title>
<style>{_DASHBOARD_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="cur-head">
    <span class="cur-brand">Ptilopsis Radar</span>
    <span class="cur-ts">{_esc(display_time)}</span>
    <h1>{_esc(page_title)}</h1>
  </div>
  {lead_html}
  {overview_html}
  {signal_section}
  {tracking_html}
  {sup_html}
</div>
</body>
</html>"""


def write_dashboard(
    output_dir: str,
    mode: str,
    ai_analysis: Optional[Any],
    report_metadata: Optional[Dict[str, Any]],
    generated_at: datetime,
    stats: Optional[List[Dict[str, Any]]] = None,
    rss_items: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    渲染并写发布根的盘面产物（纯文件 IO，便于单测）：
    - output/public/{group}/index.html（盘面页）
    - output/public/{group}/state.json（发布安全摘要缓存）
    - output/public/index.html（落地页，幂等）

    **不写 full.html**（由 generate_html_report 负责）。

    stats / rss_items 为发布安全的追踪数据（公开榜单信息，无 URL），
    用于盘面页热榜/RSS 追踪区；不写入 state.json。

    Returns:
        str: 盘面页路径 output/public/{group}/index.html
    """
    group = _group_for_mode(mode)
    dashboard_html = render_current_dashboard_html(
        ai_analysis=ai_analysis,
        report_metadata=report_metadata,
        generated_at=generated_at,
        mode=mode,
        stats=stats,
        rss_items=rss_items,
    )
    state = build_dashboard_state(
        ai_analysis=ai_analysis,
        report_metadata=report_metadata,
        generated_at=generated_at,
        mode=mode,
    )

    public_dir = Path(output_dir) / "public"
    group_dir = public_dir / group
    group_dir.mkdir(parents=True, exist_ok=True)

    index_file = group_dir / "index.html"
    index_file.write_text(dashboard_html, encoding="utf-8")
    (group_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (public_dir / "index.html").write_text(PUBLIC_LANDING_HTML, encoding="utf-8")

    return str(index_file)
