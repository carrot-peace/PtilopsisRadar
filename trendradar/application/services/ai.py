"""AI analysis service with explicit scheduling and dedupe boundaries."""

import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from trendradar.ai import AIAnalysisResult, AIAnalyzer
from trendradar.core.analyzer import strip_background_groups
from trendradar.core.scheduler import ResolvedSchedule


@dataclass(frozen=True, slots=True)
class AIAnalysisRequest:
    stats: Sequence[Mapping[str, Any]]
    rss_items: Optional[list[dict]]
    mode: str
    report_type: str
    id_to_name: Optional[Mapping[str, str]]
    current_results: Optional[Mapping[str, Any]] = None


class AIAnalysisService:
    """Own AI mode selection, schedule dedupe, invocation, and result recording."""

    def __init__(
        self,
        context,
        *,
        prepare_mode_data: Callable,
        analyzer_factory: Callable = AIAnalyzer,
    ):
        self._context = context
        self._prepare_mode_data = prepare_mode_data
        self._analyzer_factory = analyzer_factory

    def run(
        self,
        request: AIAnalysisRequest,
        schedule=None,
    ) -> Optional[AIAnalysisResult]:
        analysis_config = self._context.config.get("AI_ANALYSIS", {})
        if not analysis_config.get("ENABLED", False):
            return None

        schedule = schedule or ResolvedSchedule(
            period_key=None,
            period_name=None,
            day_plan="manual",
            collect=True,
            analyze=True,
            report_mode=request.mode,
            ai_mode=request.mode,
            once_analyze=False,
        )
        if not schedule.analyze:
            print("[AI] 调度器: 当前时间段不执行 AI 分析")
            return None

        scheduler = None
        date_str = None
        if schedule.once_analyze and schedule.period_key:
            scheduler = self._context.create_scheduler()
            date_str = self._context.format_date()
            if scheduler.already_executed(
                schedule.period_key,
                "analyze",
                date_str,
            ):
                print(
                    f"[AI] 调度器: 时间段 "
                    f"{schedule.period_name or schedule.period_key} "
                    "今天已分析过，跳过"
                )
                return None
            print(
                f"[AI] 调度器: 时间段 "
                f"{schedule.period_name or schedule.period_key} 今天首次分析"
            )

        print("[AI] 正在进行 AI 分析...")
        try:
            analyzer = self._analyzer_factory(
                self._context.config.get("AI", {}),
                analysis_config,
                self._context.get_time,
                debug=self._context.config.get("DEBUG", False),
            )
            ai_mode, ai_stats, ai_id_to_name = self._select_mode_data(
                request,
                schedule,
                analysis_config,
            )
            ai_rss_items = request.rss_items
            if (
                self._context.config.get("BACKGROUND_PULL_ONLY", False)
                and ai_mode in ("current", "incremental")
            ):
                prefix = self._context.config.get(
                    "BACKGROUND_GROUP_PREFIX",
                    "背景-",
                )
                before = len(ai_stats or [])
                before_rss = len(ai_rss_items or [])
                ai_stats = strip_background_groups(ai_stats, prefix)
                ai_rss_items = strip_background_groups(ai_rss_items, prefix)
                removed = before - len(ai_stats or [])
                removed_rss = before_rss - len(ai_rss_items or [])
                if removed or removed_rss:
                    print(
                        "[AI] 背景表 pull-only：realtime 输入剔除背景组 "
                        f"热榜 {removed} / RSS {removed_rss}"
                    )

            report_type = (
                {
                    "daily": "当日汇总",
                    "current": "当前榜单",
                    "incremental": "增量更新",
                }.get(ai_mode, request.report_type)
                if ai_mode != request.mode
                else request.report_type
            )
            result = analyzer.analyze(
                stats=ai_stats,
                rss_stats=ai_rss_items,
                report_mode=ai_mode,
                report_type=report_type,
                platforms=(
                    list(ai_id_to_name.values())
                    if ai_id_to_name
                    else []
                ),
                keywords=(
                    [
                        item.get("word", "")
                        for item in ai_stats
                        if item.get("word")
                    ]
                    if ai_stats
                    else []
                ),
                source_tier_resolver=self._context.source_tier_resolver,
            )
            if result.success:
                result.ai_mode = ai_mode
                if result.error:
                    print(f"[AI] 分析完成（有警告: {result.error}）")
                else:
                    print("[AI] 分析完成")
                if scheduler is not None:
                    scheduler.record_execution(
                        schedule.period_key,
                        "analyze",
                        date_str,
                    )
            elif result.skipped:
                print(f"[AI] {result.error}")
            else:
                print(f"[AI] 分析失败: {result.error}")
            return result
        except Exception as exc:
            error_type = type(exc).__name__
            error_msg = str(exc)
            if len(error_msg) > 200:
                error_msg = error_msg[:200] + "..."
            print(f"[AI] 分析出错 ({error_type}): {error_msg}")
            print("[AI] 详细错误堆栈:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return AIAnalysisResult(
                success=False,
                error=f"{error_type}: {error_msg}",
            )

    def _select_mode_data(self, request, schedule, analysis_config):
        configured_mode = analysis_config.get("MODE", "follow_report")
        if configured_mode == "follow_report":
            ai_mode = getattr(schedule, "ai_mode", None) or request.mode
            if ai_mode == "follow_report":
                ai_mode = request.mode
            message = "调度"
        elif configured_mode in {"daily", "current", "incremental"}:
            ai_mode = configured_mode
            message = "独立"
        else:
            print(
                f"[AI] 警告: 无效的 ai_analysis.mode 配置 "
                f"'{configured_mode}'，使用当前运行模式 '{request.mode}'"
            )
            return request.mode, request.stats, request.id_to_name

        if ai_mode == request.mode:
            return ai_mode, request.stats, request.id_to_name

        print(
            f"[AI] 使用{message}分析模式: {ai_mode} "
            f"(运行模式: {request.mode})"
        )
        print(f"[AI] 正在准备 {ai_mode} 模式的数据...")
        stats, id_to_name = self._prepare_mode_data(
            ai_mode,
            request.current_results,
            request.id_to_name,
        )
        if stats:
            return ai_mode, stats, id_to_name
        print(
            f"[AI] 警告: 无法准备 {ai_mode} 模式的数据，"
            "回退到运行模式数据"
        )
        return request.mode, request.stats, request.id_to_name
