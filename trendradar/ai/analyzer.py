# coding=utf-8
"""
AI 分析器模块

调用 AI 大模型对热点新闻进行深度分析
基于 LiteLLM 统一接口，支持 100+ AI 提供商
"""

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from trendradar.ai.client import AIClient
from trendradar.ai.prompt_loader import load_prompt_template


ENVIRONMENT_SCHEMA_VERSION = "environment-events-v1"
_FALLBACK_SUMMARY_MAX_CHARS = 180
ENVIRONMENT_RESPONSE_FORMAT: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "environment_events_report",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "overview", "items", "background_notes"],
            "properties": {
                "schema_version": {
                    "type": "string",
                    "enum": [ENVIRONMENT_SCHEMA_VERSION],
                },
                "overview": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["topic_group", "events"],
                        "properties": {
                            "topic_group": {"type": "string"},
                            "events": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [
                                        "title",
                                        "summary",
                                        "analysis",
                                        "evidence_ids",
                                    ],
                                    "properties": {
                                        "title": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "analysis": {"type": "string"},
                                        "evidence_ids": {
                                            "type": "array",
                                            "minItems": 1,
                                            "maxItems": 3,
                                            "items": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
                "background_notes": {
                    "type": "array",
                    "maxItems": 0,
                    "items": {"type": "string"},
                },
            },
        },
    },
}


@dataclass
class AIAnalysisResult:
    """AI 分析结果"""
    # 唯一支持的报告风格：environment（信息环境异常监测日报）。
    report_style: str = "environment"

    # ── environment 风格：信息环境异常监测（程序定栏定标签，AI 只写文字） ──
    # 注：字段名为数据层 bucket key；各 renderer 负责映射呈现层名称。
    overview: str = ""                                                   # 今日盘面（AI 补一句）
    overview_stats: Dict[str, Any] = field(default_factory=dict)         # 程序盘面骨架
    cross_layer_verified: List[Dict] = field(default_factory=list)       # 跨层呼应（优先看）
    high_heat_unverified: List[Dict] = field(default_factory=list)       # 高热待核实（隔离看）
    sentiment_heavy: List[Dict] = field(default_factory=list)            # 低热情绪聚集（情绪降为属性，呈现层并入已抑制）
    silence_gap: List[Dict] = field(default_factory=list)                # 沉默温差（外热中静）
    chinese_only_hot: List[Dict] = field(default_factory=list)           # 中文独热（中热缺外）
    background_notes: List[str] = field(default_factory=list)            # 已抑制（未达异常阈值）
    method_note: str = ""                                                # 方法说明（固定）
    evidence_items: List[Dict] = field(default_factory=list)             # 程序证据（调试/HTML 详情）

    # 基础元数据
    raw_response: str = ""               # 原始响应
    ai_response_metadata: List[Dict[str, Any]] = field(default_factory=list)
    success: bool = False                # 是否成功
    skipped: bool = False                # 是否因无内容跳过（非失败）
    error: str = ""                      # 错误信息

    # 新闻数量统计
    total_news: int = 0                  # 总新闻数（热榜+RSS）
    analyzed_news: int = 0               # 实际分析的新闻数
    max_news_limit: int = 0              # 分析上限配置值
    hotlist_count: int = 0               # 热榜新闻数（总数）
    rss_count: int = 0                   # RSS 新闻数（总数）
    hotlist_analyzed: int = 0            # 热榜实际分析数
    rss_analyzed: int = 0               # RSS 实际分析数
    ai_mode: str = ""                    # AI 分析使用的模式 (daily/current/incremental)
    include_rss: bool = True             # 是否启用 RSS 分析


class AIAnalyzer:
    """AI 分析器"""

    def __init__(
        self,
        ai_config: Dict[str, Any],
        analysis_config: Dict[str, Any],
        get_time_func: Callable,
        debug: bool = False,
    ):
        """
        初始化 AI 分析器

        Args:
            ai_config: AI 模型配置（LiteLLM 格式）
            analysis_config: AI 分析功能配置（language, prompt_file 等）
            get_time_func: 获取当前时间的函数
            debug: 是否开启调试模式
        """
        self.ai_config = dict(ai_config)
        self.analysis_config = analysis_config
        self.get_time_func = get_time_func
        self.debug = debug

        # 从分析配置获取功能参数
        self.max_news = analysis_config.get("MAX_NEWS_FOR_ANALYSIS", 50)

        def positive_int(value: Any, default: int) -> int:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return default
            return parsed if parsed > 0 else default

        self.max_events = positive_int(analysis_config.get("MAX_EVENTS", 30), 30)
        self.batch_max_evidence = positive_int(
            analysis_config.get("BATCH_MAX_EVIDENCE", 12), 12
        )
        self.max_output_tokens = positive_int(
            analysis_config.get("MAX_OUTPUT_TOKENS", 16000), 16000
        )
        self.include_rss = analysis_config.get("INCLUDE_RSS", True)
        self.include_rank_timeline = analysis_config.get("INCLUDE_RANK_TIMELINE", False)
        self.language = analysis_config.get("LANGUAGE", "Chinese")

        # DR 的输出预算与生成参数独立于翻译/过滤等 AI 功能。
        client_config = dict(self.ai_config)
        client_config["MAX_TOKENS"] = self.max_output_tokens
        base_extra = client_config.get("EXTRA_PARAMS", {})
        analysis_extra = analysis_config.get("EXTRA_PARAMS", {})
        merged_extra = dict(base_extra) if isinstance(base_extra, dict) else {}
        if isinstance(analysis_extra, dict):
            merged_extra.update(analysis_extra)
        merged_extra.setdefault("response_format", copy.deepcopy(ENVIRONMENT_RESPONSE_FORMAT))
        model_name = str(client_config.get("MODEL", "")).lower()
        provider, _, provider_model = model_name.partition("/")
        native_gemini_3 = (
            provider in {"gemini", "vertex_ai"} and "gemini-3" in provider_model
        )
        if native_gemini_3:
            merged_extra.setdefault("reasoning_effort", "low")
        client_config["EXTRA_PARAMS"] = merged_extra
        # Gemini 3.x 的默认采样已针对 thinking 调优；DR 仅指定 low reasoning，
        # 不再额外发送全局 temperature。
        if native_gemini_3:
            client_config["TEMPERATURE"] = None

        # 创建 AI 客户端（基于 LiteLLM）
        self.client = AIClient(client_config)

        # 验证配置
        valid, error = self.client.validate_config()
        if not valid:
            print(f"[AI] 配置警告: {error}")

        # 唯一支持的信息环境异常监测报告风格；classic 已废弃。
        self.report_style = "environment"

        # 加载提示词模板（environment prompt）
        prompt_file = analysis_config.get(
            "ENVIRONMENT_PROMPT_FILE", "ai_environment_report_prompt.txt"
        )
        self.system_prompt, self.user_prompt_template = load_prompt_template(
            prompt_file,
            label="AI",
        )

    def analyze(
        self,
        stats: List[Dict],
        rss_stats: Optional[List[Dict]] = None,
        report_mode: str = "daily",
        report_type: str = "当日汇总",
        platforms: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        source_tier_resolver: Optional[Any] = None,
    ) -> AIAnalysisResult:
        """
        执行 AI 分析

        Args:
            stats: 热榜统计数据
            rss_stats: RSS 统计数据
            report_mode: 报告模式
            report_type: 报告类型
            platforms: 平台列表
            keywords: 关键词列表
            source_tier_resolver: 来源层级解析器

        Returns:
            AIAnalysisResult: 分析结果
        """
        
        # 打印配置信息方便调试
        model = self.ai_config.get("MODEL", "unknown")
        api_key = self.client.api_key or ""
        api_base = self.ai_config.get("API_BASE", "")
        masked_key = f"{api_key[:5]}******" if len(api_key) >= 5 else "******"
        model_display = model.replace("/", "/\u200b") if model else "unknown"

        print(f"[AI] 模型: {model_display}")
        print(f"[AI] Key : {masked_key}")

        if api_base:
            print(f"[AI] 接口: 存在自定义 API 端点")

        timeout = self.ai_config.get("TIMEOUT", 120)
        print(
            f"[AI] 参数: timeout={timeout}, dr_max_output_tokens={self.max_output_tokens}, "
            f"max_events={self.max_events}, batch_max_evidence={self.batch_max_evidence}"
        )

        if not self.client.api_key:
            return AIAnalysisResult(
                success=False,
                report_style="environment",
                error="未配置 AI API Key，请在 config.yaml 或环境变量 AI_API_KEY 中设置"
            )

        # 信息环境异常监测：走独立的 evidence-based 流程
        return self._analyze_environment(
            stats=stats,
            rss_stats=rss_stats,
            report_mode=report_mode,
            source_tier_resolver=source_tier_resolver,
        )

    def _call_ai(self, user_prompt: str) -> str:
        """调用 AI API（使用 LiteLLM）"""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        return self.client.chat(messages)

    # ════════════════════════════════════════════════════════════
    # 信息环境异常监测（environment 风格）
    # ════════════════════════════════════════════════════════════

    def _analyze_environment(
        self,
        stats: List[Dict],
        rss_stats: Optional[List[Dict]],
        report_mode: str,
        source_tier_resolver: Optional[Any],
    ) -> AIAnalysisResult:
        """
        信息环境异常监测流程：

        1. 程序构建结构化 evidence summary 并唯一裁定 label / 栏目（AI 无权更改）。
        2. AI 仅为已分栏议题补写 overview / summary / analysis 文字。
        3. 程序组装最终结果：栏目、验证状态、风险提示全部由程序写死。
        AI 失败时仍输出程序事实（prose 留空），不崩。
        """
        from trendradar.ai.evidence import (
            BUCKET_ORDER,
            LABELS,
            METHOD_NOTE,
            RISK_NOTE_HIGH_HEAT,
            SECTION_ORDER,
            SUPPRESSED_BUCKETS,
            bucketize,
            build_evidence,
            build_overview_stats,
            render_evidence_for_prompt,
            render_overview_stats_for_prompt,
        )

        # resolver 缺失时回退到全 unknown（不阻断）
        if source_tier_resolver is None:
            from trendradar.core.source_tiers import SourceTierResolver
            source_tier_resolver = SourceTierResolver()

        effective_rss_stats = rss_stats if self.include_rss else None
        items = build_evidence(
            stats, effective_rss_stats, source_tier_resolver, self.include_rank_timeline
        )
        buckets = bucketize(items)
        overview_stats = build_overview_stats(buckets)

        hotlist_total = sum(len(s.get("titles", [])) for s in stats) if stats else 0
        rss_total = sum(len(s.get("titles", [])) for s in (effective_rss_stats or []))

        # 无任何信号 -> 跳过
        if overview_stats["total_items"] == 0 and overview_stats["background_count"] == 0:
            return AIAnalysisResult(
                success=False,
                skipped=True,
                report_style="environment",
                error="本轮无可分栏的异常信号，跳过 AI 分析",
                total_news=hotlist_total + rss_total,
                hotlist_count=hotlist_total,
                rss_count=rss_total,
                method_note=METHOD_NOTE,
                overview_stats=overview_stats,
            )

        prompt_buckets = self._limit_environment_prompt_buckets(
            buckets, SECTION_ORDER, SUPPRESSED_BUCKETS
        )
        (
            ai_overview,
            ai_items,
            ai_error,
            raw_responses,
            response_metadata,
            blocking_ai_error,
        ) = self._execute_environment_batches(
            prompt_buckets=prompt_buckets,
            overview_stats=overview_stats,
            section_order=SECTION_ORDER,
            render_evidence_for_prompt=render_evidence_for_prompt,
            render_overview_stats_for_prompt=render_overview_stats_for_prompt,
        )

        result = AIAnalysisResult(
            # 截断、schema/JSON 错误、批次调用失败或覆盖缺失都不是可接受的
            # 成功；scheduler 必须能区分程序 fallback 与完整 AI 日报。
            success=not blocking_ai_error,
            report_style="environment",
            overview=ai_overview,
            overview_stats=overview_stats,
            method_note=METHOD_NOTE,
            evidence_items=items,
            total_news=hotlist_total + rss_total,
            hotlist_count=hotlist_total,
            rss_count=rss_total,
            analyzed_news=sum(
                len(item.get("sample_titles") or [])
                for label in SECTION_ORDER
                for item in prompt_buckets.get(label, [])
            ),
            max_news_limit=self.max_events,
            include_rss=self.include_rss,
            error=ai_error,
            raw_response="\n\n".join(raw_responses),
            ai_response_metadata=response_metadata,
        )

        # 程序组装各栏目。议题组只用于生成候选事件；每个事件必须按自己绑定
        # 的 evidence_ids 重新分桶，栏目、状态与事实边界不可继承关键词组。
        rendered_by_label: Dict[str, List[Dict[str, Any]]] = {
            label: [] for label in BUCKET_ORDER
        }
        # overview_stats initially describes the keyword groups sent to the AI.
        # The published report is event-first, so keep a second set of buckets
        # for the exact event evidence that survives program reclassification.
        event_buckets: Dict[str, List[Dict[str, Any]]] = {
            label: [] for label in BUCKET_ORDER
        }
        event_buckets["background"] = list(buckets.get("background", []))
        claimed_evidence_ids: set[str] = set()
        bg_notes: List[str] = [
            f"{item['topic_group']}（{item['source_layers']}）"
            for item in buckets.get("background", [])
        ]
        # Use the same reader-facing priority as prompt selection.  This makes
        # ownership deterministic when one captured headline matched multiple
        # keyword groups: the group shown to the AI is also the group allowed
        # to claim that evidence in the final event stream.
        assembly_order = list(dict.fromkeys([*SECTION_ORDER, *BUCKET_ORDER]))
        for label in assembly_order:
            for item in buckets.get(label, []):
                topic = item["topic_group"]
                prose = ai_items.get(topic) if isinstance(ai_items.get(topic), dict) else {}
                prose = prose or {}
                event_entries = self._build_event_entries(
                    group_topic=topic,
                    prose=prose,
                    evidence=item,
                    risk_note_high_heat=RISK_NOTE_HIGH_HEAT,
                    claimed_evidence_ids=claimed_evidence_ids,
                )
                # 每条未被 AI 认领的证据仍生成统一的事件级程序 fallback；禁止
                # 回退成关键词组摘要，也避免部分 events 成功时其余证据静默丢失。
                for sample in item.get("sample_titles") or []:
                    fallback = self._deterministic_event_fallback(
                        group_topic=topic,
                        evidence=item,
                        sample=sample,
                        risk_note_high_heat=RISK_NOTE_HIGH_HEAT,
                        claimed_evidence_ids=claimed_evidence_ids,
                    )
                    if fallback is not None:
                        event_entries.append(fallback)

                for entry in event_entries:
                    event_label = entry.pop("_bucket_label", None)
                    detail = entry.get("evidence_detail")
                    event_evidence = detail if isinstance(detail, dict) else {}
                    if event_label in rendered_by_label:
                        rendered_by_label[event_label].append(entry)
                        event_buckets[event_label].append(event_evidence)
                    else:
                        event_buckets["background"].append(event_evidence)
                        bg_notes.append(
                            f"{entry.get('topic', topic)}（{entry.get('source_layers', '-')}）"
                        )

        for label, rendered in rendered_by_label.items():
            setattr(result, label, rendered)
        final_overview_stats = build_overview_stats(event_buckets)
        # The model wrote its overview from keyword-group statistics, while the
        # published report is classified again at event granularity.  Keep the
        # prose only when both views describe the same structural categories;
        # renderers can otherwise generate a deterministic brief from the final
        # program-owned counts.
        def presence_snapshot(stats_value: Dict[str, Any]) -> tuple:
            counts = stats_value.get("label_counts", {}) or {}
            layers = stats_value.get("layer_distribution", {}) or {}
            return (
                tuple(bool(counts.get(label, 0)) for label in BUCKET_ORDER),
                bool(stats_value.get("background_count", 0)),
                tuple(bool(layers.get(tier, 0)) for tier in ("A", "B", "C", "D")),
            )

        if presence_snapshot(overview_stats) != presence_snapshot(final_overview_stats):
            result.overview = ""
        result.overview_stats = final_overview_stats
        result.background_notes = bg_notes

        return result

    @staticmethod
    def _base_environment_entry(
        *,
        topic: str,
        summary: str,
        analysis: str,
        evidence: Dict[str, Any],
        verification_status: str,
        factual_boundary: str,
    ) -> Dict[str, Any]:
        """Build one reader-facing entry from program-owned evidence."""
        return {
            "topic": topic,
            "summary": summary,
            "analysis": analysis,
            "source_layers": evidence.get("source_layers", "-"),
            "platforms": AIAnalyzer._platforms_str(evidence),
            "platform_count": int(evidence.get("platform_count", 0) or 0),
            "highest_heat": evidence.get("highest_heat", "-"),
            "verification_status": verification_status,
            "factual_boundary": factual_boundary,
            "sentiment_flag": bool(evidence.get("sentiment_flag")),
            "evidence_detail": evidence,
        }

    @staticmethod
    def _event_evidence(
        group_evidence: Dict[str, Any], evidence_ids: List[str]
    ) -> Optional[Dict[str, Any]]:
        """Narrow topic-group evidence to the exact program IDs cited by one event.

        Partial matches are rejected: one invented ID invalidates the event rather
        than silently broadening or narrowing its factual boundary.
        """
        allowed = {
            str(sample.get("evidence_id", "")).strip(): sample
            for sample in (group_evidence.get("sample_titles") or [])
            if isinstance(sample, dict) and str(sample.get("evidence_id", "")).strip()
        }
        requested = list(dict.fromkeys(value for value in evidence_ids if value))
        if not requested or any(value not in allowed for value in requested):
            return None
        matched_set = set(requested)
        samples = [
            dict(sample)
            for sample in (group_evidence.get("sample_titles") or [])
            if isinstance(sample, dict)
            and str(sample.get("evidence_id", "")).strip() in matched_set
        ]
        links = [
            dict(link)
            for link in (group_evidence.get("source_links") or [])
            if isinstance(link, dict)
            and str(link.get("evidence_id", "")).strip() in matched_set
        ]

        sources_by_tier: Dict[str, List[str]] = {}
        for record in [*samples, *links]:
            tier = str(record.get("tier", "unknown") or "unknown")
            source = str(record.get("source", "") or "").strip()
            if source and source not in sources_by_tier.setdefault(tier, []):
                sources_by_tier[tier].append(source)
        present = [tier for tier in ("A", "B", "C", "D") if sources_by_tier.get(tier)]
        source_names = {
            source for names in sources_by_tier.values() for source in names if source
        }

        ranked: List[tuple[int, str]] = []
        ranked_d: List[tuple[int, str]] = []
        for record in [*samples, *links]:
            rank = record.get("rank")
            source = str(record.get("source", "") or "").strip()
            if isinstance(rank, int) and rank > 0:
                ranked.append((rank, source))
                if record.get("tier") == "D":
                    ranked_d.append((rank, source))
        highest_heat = "-"
        if ranked:
            rank, source = min(ranked, key=lambda pair: pair[0])
            highest_heat = f"{source} 第{rank}名" if source else f"第{rank}名"
        highest_d_tier_rank = None
        if ranked_d:
            rank, source = min(ranked_d, key=lambda pair: pair[0])
            highest_d_tier_rank = {"platform": source, "rank": rank}

        return {
            "topic_group": group_evidence.get("topic_group", ""),
            "evidence_ids": requested,
            "source_tiers_present": present,
            "sources_by_tier": sources_by_tier,
            "source_layers": "/".join(present) or "-",
            "platform_count": len(source_names),
            "d_tier_platform_count": len(sources_by_tier.get("D", [])),
            "highest_d_tier_rank": highest_d_tier_rank,
            "highest_heat": highest_heat,
            "sentiment_flag": any(bool(sample.get("sentiment_flag")) for sample in samples),
            "sample_titles": samples,
            "source_links": links,
        }

    @classmethod
    def _bounded_fallback_summary(cls, lead: str, suffix: str = "") -> str:
        """Bound fallback prose while preserving a required factual boundary."""
        if len(lead) + len(suffix) <= _FALLBACK_SUMMARY_MAX_CHARS:
            return lead + suffix
        available = _FALLBACK_SUMMARY_MAX_CHARS - len(suffix)
        if available <= 1:
            return suffix[:_FALLBACK_SUMMARY_MAX_CHARS]
        clipped = lead[: available - 1].rstrip("，,；;：:。.!！？? ")
        return clipped + "…" + suffix

    @classmethod
    def _deterministic_summary_for_sample(cls, sample: Dict[str, Any]) -> str:
        """Write the most informative summary that one evidence record supports."""
        headline = str(sample.get("title", "") or "").strip()
        source = str(sample.get("source", "") or "未知来源").strip()
        tier = str(sample.get("tier", "unknown") or "unknown")
        rank = sample.get("rank")
        observed_at = str(sample.get("time", "") or "").strip()

        if tier == "D":
            where = (
                f"进入{source}榜单第{rank}名"
                if isinstance(rank, int) and rank > 0
                else f"出现在{source}榜单中"
            )
            time_text = f"，观测时间为{observed_at}" if observed_at else ""
            subject = f"“{headline}”相关内容" if headline else "相关内容"
            return cls._bounded_fallback_summary(
                f"{subject}{where}{time_text}。",
                "采集记录未附来源正文，因此无法补充标题之外的信息。",
            )

        excerpt = str(sample.get("source_excerpt", "") or "").strip()
        if excerpt:
            prefix = f"{source}的来源摘录显示，"
            available = max(1, _FALLBACK_SUMMARY_MAX_CHARS - len(prefix))
            needs_punctuation = excerpt[-1] not in "。.!！？?…"
            if len(excerpt) + int(needs_punctuation) > available:
                excerpt = excerpt[: max(1, available - 1)].rstrip(
                    "，,；;：:。.!！？? "
                ) + "…"
            elif needs_punctuation:
                excerpt += "。"
            return cls._bounded_fallback_summary(prefix + excerpt)

        record = (
            f"标题为『{headline}』的来源记录"
            if headline
            else "一条未提供标题的来源记录"
        )
        return cls._bounded_fallback_summary(
            f"{source}出现{record}。",
            "采集记录未附正文摘录。",
        )

    @classmethod
    def _build_event_entries(
        cls,
        *,
        group_topic: str,
        prose: Dict[str, Any],
        evidence: Dict[str, Any],
        risk_note_high_heat: str,
        claimed_evidence_ids: set[str],
    ) -> List[Dict[str, Any]]:
        from trendradar.ai.evidence import LABELS, assign_evidence_label

        raw_events = prose.get("events")
        if not isinstance(raw_events, list):
            return []

        entries: List[Dict[str, Any]] = []
        seen_titles = set()
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title", "") or "").strip()
            summary = str(raw.get("summary", "") or "").strip()
            analysis = str(raw.get("analysis", "") or "").strip()
            raw_evidence_ids = raw.get("evidence_ids") or []
            if not isinstance(raw_evidence_ids, list):
                continue
            exact_ids = [
                str(value).strip()
                for value in raw_evidence_ids
                if str(value).strip()
            ]
            detail = cls._event_evidence(evidence, exact_ids)
            if not title or detail is None or title in seen_titles:
                continue
            if not summary:
                samples = detail.get("sample_titles") or []
                if len(samples) == 1 and isinstance(samples[0], dict):
                    summary = cls._deterministic_summary_for_sample(samples[0])
            bound_ids = set(detail.get("evidence_ids") or [])
            if not bound_ids or bound_ids.intersection(claimed_evidence_ids):
                continue
            seen_titles.add(title)
            claimed_evidence_ids.update(bound_ids)
            event_label = assign_evidence_label(detail)
            event_meta = LABELS.get(event_label, {})
            status = event_meta.get("verification_status", "来源覆盖有限")
            boundary = event_meta.get(
                "factual_boundary", "现有证据未达到独立异常信号的展示阈值。"
            )
            entry = cls._base_environment_entry(
                topic=title,
                summary=summary,
                analysis=analysis,
                evidence=detail,
                verification_status=status,
                factual_boundary=boundary,
            )
            stable_material = "\x1f".join(sorted(bound_ids))
            entry["event_id"] = "evt_" + hashlib.sha256(
                stable_material.encode("utf-8")
            ).hexdigest()[:16]
            entry["topic_group"] = group_topic
            entry["_bucket_label"] = event_label
            if event_label == "high_heat_unverified":
                entry["risk_note"] = risk_note_high_heat
            entries.append(entry)
        return entries

    @classmethod
    def _deterministic_event_fallback(
        cls,
        *,
        group_topic: str,
        evidence: Dict[str, Any],
        sample: Dict[str, Any],
        risk_note_high_heat: str,
        claimed_evidence_ids: set[str],
    ) -> Optional[Dict[str, Any]]:
        """Create one grounded event when AI omitted or could not write it."""
        from trendradar.ai.evidence import LABELS, assign_evidence_label

        evidence_id = str(sample.get("evidence_id", "") or "").strip()
        if not evidence_id or evidence_id in claimed_evidence_ids:
            return None
        detail = cls._event_evidence(evidence, [evidence_id])
        if detail is None:
            return None
        claimed_evidence_ids.add(evidence_id)

        headline = str(sample.get("title", "") or "").strip()
        source = str(sample.get("source", "") or "未知来源").strip()
        tier = str(sample.get("tier", "unknown") or "unknown")
        if tier == "D":
            title = (
                f"{source}出现“{headline}”相关传播"
                if headline
                else f"{source}出现未提供标题的传播记录"
            )
            summary = cls._deterministic_summary_for_sample(sample)
        else:
            title = (
                f"{source}收录“{headline}”"
                if headline
                else f"{source}收录未提供标题的来源记录"
            )
            summary = cls._deterministic_summary_for_sample(sample)
        analysis = f"单一{tier}层来源，覆盖平台为{source}。"

        event_label = assign_evidence_label(detail)
        event_meta = LABELS.get(event_label, {})
        entry = cls._base_environment_entry(
            topic=title,
            summary=summary,
            analysis=analysis,
            evidence=detail,
            verification_status=event_meta.get("verification_status", "来源覆盖有限"),
            factual_boundary=event_meta.get(
                "factual_boundary", "现有证据未达到独立异常信号的展示阈值。"
            ),
        )
        entry["event_id"] = "evt_" + hashlib.sha256(
            evidence_id.encode("utf-8")
        ).hexdigest()[:16]
        entry["topic_group"] = group_topic
        entry["_bucket_label"] = event_label
        if event_label == "high_heat_unverified":
            entry["risk_note"] = risk_note_high_heat
        return entry

    def _limit_environment_prompt_buckets(
        self,
        buckets: Dict[str, List[Dict]],
        section_order: List[str],
        suppressed_buckets: List[str],
    ) -> Dict[str, List[Dict]]:
        """
        限制发给 AI 补写 prose 的 evidence 条目数。

        程序盘面统计与最终栏目仍基于全量 evidence；此限制只控制 prompt 体积。
        """
        try:
            group_limit = max(0, int(self.max_news))
        except (TypeError, ValueError):
            group_limit = 0
        try:
            event_limit = max(0, int(self.max_events))
        except (TypeError, ValueError):
            event_limit = 0
        limited = {k: [] for k in buckets.keys()}
        remaining_groups = group_limit or 10 ** 9
        remaining_evidence = event_limit or 10 ** 9
        selected_evidence_ids: set[str] = set()
        # background / suppressed 项不需要 AI 文字，盘面计数已通过 overview_stats
        # 单独提供；不再用它们占据输入容量。
        ordered_keys = list(section_order)
        seen = set()
        for key in ordered_keys:
            if key in seen or key not in buckets:
                continue
            seen.add(key)
            if remaining_groups <= 0 or remaining_evidence <= 0:
                break
            for item in buckets.get(key, []):
                if remaining_groups <= 0 or remaining_evidence <= 0:
                    break
                samples: List[Dict[str, Any]] = []
                for sample in item.get("sample_titles") or []:
                    if not isinstance(sample, dict):
                        continue
                    evidence_id = str(sample.get("evidence_id", "") or "").strip()
                    if not evidence_id or evidence_id in selected_evidence_ids:
                        continue
                    samples.append(sample)
                    selected_evidence_ids.add(evidence_id)
                    if len(samples) >= remaining_evidence:
                        break
                if not samples:
                    continue
                selected = self._copy_evidence_with_samples(item, samples)
                limited[key].append(selected)
                remaining_groups -= 1
                remaining_evidence -= len(samples)

        return limited

    @staticmethod
    def _copy_evidence_with_samples(
        item: Dict[str, Any], samples: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        selected = copy.deepcopy(item)
        selected["sample_titles"] = copy.deepcopy(samples)
        evidence_ids = {
            str(sample.get("evidence_id", "")) for sample in samples if sample.get("evidence_id")
        }
        selected["source_links"] = [
            copy.deepcopy(link)
            for link in (item.get("source_links") or [])
            if str(link.get("evidence_id", "")) in evidence_ids
        ]
        return selected

    def _chunk_environment_prompt_buckets(
        self,
        buckets: Dict[str, List[Dict[str, Any]]],
        section_order: List[str],
        max_evidence: int,
    ) -> List[Dict[str, List[Dict[str, Any]]]]:
        """Split prompt work by evidence count, including inside a large topic."""
        size = max(1, int(max_evidence or 1))
        chunks: List[Dict[str, List[Dict[str, Any]]]] = []
        current = {key: [] for key in buckets}
        current_size = 0

        def flush() -> None:
            nonlocal current, current_size
            if any(current.get(key) for key in section_order):
                chunks.append(current)
            current = {key: [] for key in buckets}
            current_size = 0

        for label in section_order:
            for item in buckets.get(label, []):
                samples = list(item.get("sample_titles") or [])
                offset = 0
                while offset < len(samples):
                    if current_size >= size:
                        flush()
                    take = min(size - current_size, len(samples) - offset)
                    piece_samples = samples[offset:offset + take]
                    current[label].append(
                        self._copy_evidence_with_samples(item, piece_samples)
                    )
                    current_size += take
                    offset += take
        flush()
        return chunks

    @staticmethod
    def _merge_environment_items(
        target: Dict[str, Dict[str, Any]], incoming: Dict[str, Dict[str, Any]]
    ) -> None:
        for topic, payload in incoming.items():
            existing = target.setdefault(topic, {"events": []})
            existing_events = existing.setdefault("events", [])
            for event in payload.get("events", []):
                if isinstance(event, dict):
                    existing_events.append(event)

    def _environment_user_prompt(
        self,
        prompt_buckets: Dict[str, List[Dict[str, Any]]],
        overview_stats: Dict[str, Any],
        render_evidence_for_prompt: Callable,
        render_overview_stats_for_prompt: Callable,
    ) -> str:
        user_prompt = self.user_prompt_template
        user_prompt = user_prompt.replace(
            "{current_time}", self.get_time_func().strftime("%Y-%m-%d %H:%M:%S")
        )
        user_prompt = user_prompt.replace("{language}", self.language)
        user_prompt = user_prompt.replace(
            "{overview_stats}", render_overview_stats_for_prompt(overview_stats)
        )
        user_prompt = user_prompt.replace(
            "{evidence_summary}",
            render_evidence_for_prompt(prompt_buckets, overview_stats),
        )
        return user_prompt

    @staticmethod
    def _is_token_truncation(metadata: Dict[str, Any]) -> bool:
        reason = str(metadata.get("finish_reason", "") or "").upper()
        return reason in {"MAX_TOKENS", "LENGTH", "TOKEN_LIMIT"}

    @staticmethod
    def _batch_topics(
        batch: Dict[str, List[Dict[str, Any]]], section_order: List[str]
    ) -> set[str]:
        return {
            str(item.get("topic_group", ""))
            for label in section_order
            for item in batch.get(label, [])
            if item.get("topic_group")
        }

    def _execute_environment_batches(
        self,
        *,
        prompt_buckets: Dict[str, List[Dict[str, Any]]],
        overview_stats: Dict[str, Any],
        section_order: List[str],
        render_evidence_for_prompt: Callable,
        render_overview_stats_for_prompt: Callable,
    ) -> tuple:
        """Run bounded structured-output batches, retrying truncation by halving."""
        try:
            batch_size = max(1, int(self.batch_max_evidence))
        except (TypeError, ValueError):
            batch_size = 12
        queue = self._chunk_environment_prompt_buckets(
            prompt_buckets, section_order, batch_size
        )
        if not queue:
            return "", {}, "", [], [], False
        overview = ""
        merged_items: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []
        raw_responses: List[str] = []
        metadata_log: List[Dict[str, Any]] = []
        blocking_error = False
        call_number = 0

        while queue:
            batch = queue.pop(0)
            call_number += 1
            user_prompt = self._environment_user_prompt(
                batch,
                overview_stats,
                render_evidence_for_prompt,
                render_overview_stats_for_prompt,
            )
            if self.debug:
                print(f"[AI 调试] environment batch {call_number}\n{user_prompt}")

            try:
                if hasattr(self.client, "last_response_metadata"):
                    self.client.last_response_metadata = {}
                response = self._call_ai(user_prompt)
            except Exception as exc:
                blocking_error = True
                errors.append(f"AI 批次调用失败 ({type(exc).__name__}): {str(exc)[:160]}")
                continue

            response = str(response or "")
            raw_responses.append(response)
            metadata = copy.deepcopy(
                getattr(self.client, "last_response_metadata", {}) or {}
            )
            metadata["call"] = call_number
            metadata["topic_groups"] = sorted(self._batch_topics(batch, section_order))
            metadata_log.append(metadata)
            usage = metadata.get("usage", {}) if isinstance(metadata.get("usage"), dict) else {}
            details = (
                usage.get("completion_tokens_details", {})
                if isinstance(usage.get("completion_tokens_details"), dict)
                else {}
            )
            thought_tokens = (
                usage.get("thoughts_token_count")
                or usage.get("reasoning_tokens")
                or details.get("reasoning_tokens")
                or 0
            )
            print(
                f"[AI] DR batch {call_number}: "
                f"finish={metadata.get('finish_reason') or '-'}, "
                f"prompt={usage.get('prompt_tokens', 0)}, "
                f"completion={usage.get('completion_tokens', 0)}, "
                f"thoughts={thought_tokens}"
            )

            if self._is_token_truncation(metadata):
                total_evidence = sum(
                    len(item.get("sample_titles") or [])
                    for label in section_order
                    for item in batch.get(label, [])
                )
                smaller = self._chunk_environment_prompt_buckets(
                    batch, section_order, max(1, total_evidence // 2)
                )
                if total_evidence > 1 and len(smaller) > 1:
                    metadata["discarded"] = True
                    metadata["retry_split"] = len(smaller)
                    queue = smaller + queue
                    continue
                blocking_error = True
                metadata["discarded"] = True
                errors.append("AI 输出因 MAX_TOKENS 截断；已拒绝残缺结果")
                continue

            batch_overview, batch_items, _background, parse_error = (
                self._parse_environment_response(response)
            )
            if parse_error:
                blocking_error = True
                errors.append(parse_error)
                continue

            expected = self._batch_topics(batch, section_order)
            returned = set(batch_items)
            if expected != returned:
                blocking_error = True
                missing = "、".join(sorted(expected - returned)) or "-"
                extra = "、".join(sorted(returned - expected)) or "-"
                errors.append(f"AI 批次覆盖不完整：缺失={missing}，额外={extra}")
            if any(not batch_items.get(topic, {}).get("events") for topic in expected):
                blocking_error = True
                errors.append("AI 批次存在空 events；已使用程序事件 fallback")
            expected_ids = {
                str(sample.get("evidence_id", ""))
                for label in section_order
                for item in batch.get(label, [])
                for sample in (item.get("sample_titles") or [])
                if sample.get("evidence_id")
            }
            returned_id_list = [
                str(evidence_id)
                for payload in batch_items.values()
                for event in payload.get("events", [])
                for evidence_id in (event.get("evidence_ids") or [])
            ]
            returned_ids = set(returned_id_list)
            if expected_ids != returned_ids:
                blocking_error = True
                missing_count = len(expected_ids - returned_ids)
                extra_count = len(returned_ids - expected_ids)
                errors.append(
                    f"AI 批次 evidence 覆盖不完整：缺失={missing_count}，额外={extra_count}"
                )
                metadata["missing_evidence_ids"] = sorted(expected_ids - returned_ids)
                metadata["extra_evidence_ids"] = sorted(returned_ids - expected_ids)
            if len(returned_id_list) != len(returned_ids):
                blocking_error = True
                errors.append("AI 批次重复使用 evidence_id；重复事件已拒绝")
            expected_by_topic: Dict[str, set[str]] = {}
            for label in section_order:
                for item in batch.get(label, []):
                    topic = str(item.get("topic_group", ""))
                    expected_by_topic.setdefault(topic, set()).update(
                        str(sample.get("evidence_id"))
                        for sample in (item.get("sample_titles") or [])
                        if sample.get("evidence_id")
                    )
            returned_by_topic: Dict[str, List[str]] = {
                topic: [
                    str(evidence_id)
                    for event in payload.get("events", [])
                    for evidence_id in (event.get("evidence_ids") or [])
                ]
                for topic, payload in batch_items.items()
            }
            for topic in expected | returned:
                topic_expected = expected_by_topic.get(topic, set())
                topic_returned_list = returned_by_topic.get(topic, [])
                topic_returned = set(topic_returned_list)
                if topic_expected != topic_returned:
                    blocking_error = True
                    errors.append(f"AI 批次议题 {topic} 的 evidence_ids 绑定错误")
                if len(topic_returned_list) != len(topic_returned):
                    blocking_error = True
                    errors.append(f"AI 批次议题 {topic} 重复使用 evidence_id")

            if not overview and batch_overview:
                overview = batch_overview
            self._merge_environment_items(merged_items, batch_items)

        if not metadata_log:
            blocking_error = True
            errors.append("未完成任何 AI 批次")
        # 任一 blocking error 都切换到全量程序 fallback；不能在 success=False
        # 的“仅展示程序采集内容”通知下继续混入部分 AI prose。
        safe_overview = "" if blocking_error else overview
        safe_items = {} if blocking_error else merged_items
        return (
            safe_overview,
            safe_items,
            "；".join(dict.fromkeys(errors)),
            raw_responses,
            metadata_log,
            blocking_error,
        )

    @staticmethod
    def _platforms_str(item: Dict) -> str:
        """从 evidence item 的 sources_by_tier 拼出可读平台列表。"""
        names: List[str] = []
        for tier in ("A", "B", "C", "D", "unknown"):
            for n in item.get("sources_by_tier", {}).get(tier, []):
                if n and n not in names:
                    names.append(n)
        return "、".join(names) if names else "-"

    def _parse_environment_response(self, response: str) -> tuple:
        """
        解析环境监测 AI 响应。

        Returns:
            tuple: (overview, items_dict, background_notes_list, error_str)
            error_str 非空表示解析有问题（但不致命，程序事实仍可输出）。
        """
        if not response or not response.strip():
            return "", {}, [], "AI 返回空响应"

        # Structured Output 必须直接返回标准 JSON；markdown 包裹也视为协议错误。
        json_str = response.strip()

        data = None
        error = ""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            error = f"JSON 解析错误: {e.msg}"
            # environment 使用 Structured Output。非标准 JSON 可能是 provider
            # 未暴露 finish_reason 时的截断，禁止 json_repair 后伪装成成功。

        if not isinstance(data, dict):
            return "", {}, [], (error or "AI 响应非 JSON 对象")

        schema_version = str(data.get("schema_version", "") or "")
        if schema_version != ENVIRONMENT_SCHEMA_VERSION:
            return (
                "",
                {},
                [],
                f"AI 响应 schema_version 不匹配: {schema_version or '缺失'}",
            )

        raw_overview = data.get("overview")
        if not isinstance(raw_overview, str):
            return "", {}, [], "AI 响应 overview 必须为字符串"
        overview = raw_overview.strip()

        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            return "", {}, [], "AI 响应 items 必须为数组"
        items: Dict[str, Dict[str, Any]] = {}
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                return "", {}, [], "AI 响应 items 包含非对象元素"
            raw_topic = raw_item.get("topic_group")
            if not isinstance(raw_topic, str):
                return "", {}, [], "AI 响应 topic_group 必须为字符串"
            topic = raw_topic.strip()
            raw_events = raw_item.get("events")
            if not topic or not isinstance(raw_events, list) or topic in items:
                return "", {}, [], "AI 响应 topic_group 缺失、重复或 events 非数组"
            events: List[Dict[str, Any]] = []
            for raw_event in raw_events:
                if not isinstance(raw_event, dict):
                    return "", {}, [], f"议题 {topic} 包含非对象 event"
                for field_name in ("title", "summary", "analysis"):
                    if not isinstance(raw_event.get(field_name), str):
                        return (
                            "",
                            {},
                            [],
                            f"议题 {topic} 的 event {field_name} 必须为字符串",
                        )
                raw_ids = raw_event.get("evidence_ids")
                if not isinstance(raw_ids, list):
                    return "", {}, [], f"议题 {topic} 的 evidence_ids 非数组"
                if not 1 <= len(raw_ids) <= 3:
                    return "", {}, [], f"议题 {topic} 的 event 必须绑定 1 至 3 个 evidence_id"
                if any(
                    not isinstance(value, str) or not value.strip()
                    for value in raw_ids
                ):
                    return "", {}, [], f"议题 {topic} 的 evidence_ids 必须为非空字符串"
                evidence_ids = [value.strip() for value in raw_ids]
                if len(set(evidence_ids)) != len(evidence_ids):
                    return "", {}, [], f"议题 {topic} 的 event 重复使用 evidence_id"
                title = raw_event["title"].strip()
                if not title:
                    return "", {}, [], f"议题 {topic} 的 event 缺少 title"
                summary = raw_event["summary"].strip()
                if len(summary) > _FALLBACK_SUMMARY_MAX_CHARS:
                    return (
                        "",
                        {},
                        [],
                        f"议题 {topic} 的 event summary 超过 "
                        f"{_FALLBACK_SUMMARY_MAX_CHARS} 个字符",
                    )
                events.append({
                    "title": title,
                    "summary": summary,
                    "analysis": raw_event["analysis"].strip(),
                    "evidence_ids": evidence_ids,
                })
            items[topic] = {"events": events}

        raw_bg = data.get("background_notes")
        if not isinstance(raw_bg, list):
            return "", {}, [], "AI 响应 background_notes 必须为数组"
        if raw_bg:
            return "", {}, [], "AI 响应 background_notes 必须为空数组"

        return overview, items, [], error
