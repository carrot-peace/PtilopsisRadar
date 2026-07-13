# coding=utf-8
"""
AI 分析器模块

调用 AI 大模型对热点新闻进行深度分析
基于 LiteLLM 统一接口，支持 100+ AI 提供商
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from trendradar.ai.client import AIClient
from trendradar.ai.prompt_loader import load_prompt_template


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
        self.ai_config = ai_config
        self.analysis_config = analysis_config
        self.get_time_func = get_time_func
        self.debug = debug

        # 创建 AI 客户端（基于 LiteLLM）
        self.client = AIClient(ai_config)

        # 验证配置
        valid, error = self.client.validate_config()
        if not valid:
            print(f"[AI] 配置警告: {error}")

        # 从分析配置获取功能参数
        self.max_news = analysis_config.get("MAX_NEWS_FOR_ANALYSIS", 50)
        self.include_rss = analysis_config.get("INCLUDE_RSS", True)
        self.include_rank_timeline = analysis_config.get("INCLUDE_RANK_TIMELINE", False)
        self.language = analysis_config.get("LANGUAGE", "Chinese")

        # 唯一支持的信息环境异常监测报告风格。
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
        max_tokens = self.ai_config.get("MAX_TOKENS", 5000)
        print(f"[AI] 参数: timeout={timeout}, max_tokens={max_tokens}")

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
        evidence_summary = render_evidence_for_prompt(prompt_buckets, overview_stats)
        overview_stats_text = render_overview_stats_for_prompt(overview_stats)
        current_time = self.get_time_func().strftime("%Y-%m-%d %H:%M:%S")

        user_prompt = self.user_prompt_template
        user_prompt = user_prompt.replace("{current_time}", current_time)
        user_prompt = user_prompt.replace("{language}", self.language)
        user_prompt = user_prompt.replace("{overview_stats}", overview_stats_text)
        user_prompt = user_prompt.replace("{evidence_summary}", evidence_summary)

        if self.debug:
            print("\n" + "=" * 80)
            print("[AI 调试] 信息环境监测 —— 发送给 AI 的完整提示词")
            print("=" * 80)
            if self.system_prompt:
                print("\n--- System Prompt ---")
                print(self.system_prompt)
            print("\n--- User Prompt ---")
            print(user_prompt)
            print("=" * 80 + "\n")

        # 调用 AI（容错：失败仍输出程序事实）
        ai_overview, ai_items, ai_background, ai_error = "", {}, [], ""
        try:
            response = self._call_ai(user_prompt)
            ai_overview, ai_items, ai_background, ai_error = self._parse_environment_response(response)
        except Exception as e:
            ai_error = f"AI 调用失败 ({type(e).__name__}): {str(e)[:200]}"
            print(f"[AI] 环境监测 AI 调用失败，仅输出程序证据: {ai_error}")

        result = AIAnalysisResult(
            success=True,
            report_style="environment",
            overview=ai_overview,
            overview_stats=overview_stats,
            method_note=METHOD_NOTE,
            evidence_items=items,
            total_news=hotlist_total + rss_total,
            hotlist_count=hotlist_total,
            rss_count=rss_total,
            analyzed_news=overview_stats["total_items"],
            max_news_limit=self.max_news,
            include_rss=self.include_rss,
            error=ai_error,
        )

        # 程序组装各栏目：事实由程序写死，文字取 AI（按议题名匹配）
        for label in BUCKET_ORDER:
            meta = LABELS[label]
            rendered = []
            for item in buckets.get(label, []):
                topic = item["topic_group"]
                prose = ai_items.get(topic) if isinstance(ai_items.get(topic), dict) else {}
                prose = prose or {}
                entry = {
                    "topic": topic,
                    "summary": str(prose.get("summary", "")).strip(),
                    "analysis": str(prose.get("analysis", "")).strip(),
                    "source_layers": item["source_layers"],
                    "platforms": self._platforms_str(item),
                    "platform_count": item["platform_count"],
                    "highest_heat": item["highest_heat"],
                    "verification_status": meta["verification_status"],
                    "factual_boundary": meta["factual_boundary"],
                    "sentiment_flag": bool(item.get("sentiment_flag")),
                    "evidence_detail": item,
                }
                if label == "high_heat_unverified":
                    entry["risk_note"] = RISK_NOTE_HIGH_HEAT
                rendered.append(entry)
            setattr(result, label, rendered)

        # 已抑制（背景源）：程序事实 + AI 文字
        bg_notes: List[str] = []
        for item in buckets.get("background", []):
            bg_notes.append(f"{item['topic_group']}（{item['source_layers']}）")
        for note in ai_background:
            if note and str(note).strip():
                bg_notes.append(str(note).strip())
        result.background_notes = bg_notes

        return result

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
            limit = int(self.max_news)
        except (TypeError, ValueError):
            limit = 0
        if limit <= 0:
            return buckets

        limited = {k: [] for k in buckets.keys()}
        remaining = limit
        ordered_keys = list(section_order) + ["background"] + list(suppressed_buckets)
        seen = set()
        for key in ordered_keys:
            if key in seen or key not in buckets:
                continue
            seen.add(key)
            if remaining <= 0:
                break
            selected = buckets.get(key, [])[:remaining]
            limited[key] = selected
            remaining -= len(selected)

        return limited

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

        # 提取 JSON 文本（去 markdown 代码块标记）
        json_str = response
        if "```json" in response:
            parts = response.split("```json", 1)
            if len(parts) > 1:
                code_block = parts[1]
                end_idx = code_block.find("```")
                json_str = code_block[:end_idx] if end_idx != -1 else code_block
        elif "```" in response:
            parts = response.split("```", 2)
            if len(parts) >= 2:
                json_str = parts[1]
        json_str = json_str.strip()

        data = None
        error = ""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            error = f"JSON 解析错误: {e.msg}"
            try:
                from json_repair import repair_json
                repaired = repair_json(json_str, return_objects=True)
                if isinstance(repaired, dict):
                    data = repaired
                    error = ""
                    print("[AI] 环境监测 JSON 本地修复成功（json_repair）")
            except Exception:
                pass

        if not isinstance(data, dict):
            return "", {}, [], (error or "AI 响应非 JSON 对象")

        overview = str(data.get("overview", "") or "").strip()

        items = {}
        raw_items = data.get("items", {})
        if isinstance(raw_items, dict):
            for k, v in raw_items.items():
                if isinstance(v, dict):
                    items[str(k)] = {
                        "summary": str(v.get("summary", "") or "").strip(),
                        "analysis": str(v.get("analysis", "") or "").strip(),
                    }

        background = []
        raw_bg = data.get("background_notes", [])
        if isinstance(raw_bg, list):
            background = [str(x) for x in raw_bg if x]
        elif isinstance(raw_bg, str) and raw_bg.strip():
            background = [raw_bg.strip()]

        return overview, items, background, error
