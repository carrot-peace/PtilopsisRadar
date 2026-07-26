"""Typed hotlist/RSS filtering boundary."""

from dataclasses import dataclass
from typing import Optional

from trendradar.application.run_state import AnalysisRequest


@dataclass(frozen=True, slots=True)
class AnalysisSelection:
    """Content selected for downstream AI analysis and reporting."""

    stats: list[dict]
    total_titles: int
    rss_items: Optional[list[dict]]
    filter_method: str
    fell_back: bool = False


class AnalysisService:
    """Apply one configured filtering strategy to an analysis request."""

    def __init__(self, context):
        self._context = context

    def analyze(
        self,
        request: AnalysisRequest,
        *,
        filter_method: Optional[str],
        interests_file: Optional[str] = None,
        quiet: bool = False,
    ) -> AnalysisSelection:
        if filter_method == "ai":
            selection = self._analyze_with_ai(
                request,
                interests_file=interests_file,
            )
            if selection is not None:
                return selection

        stats, total_titles = self._context.count_frequency(
            request.results,
            request.word_groups,
            request.filter_words,
            request.id_to_name,
            request.title_info,
            request.new_titles,
            mode=request.mode,
            global_filters=request.global_filters,
            quiet=quiet,
        )
        return AnalysisSelection(
            stats=stats,
            total_titles=total_titles,
            rss_items=request.rss_items,
            filter_method="keyword",
            fell_back=filter_method == "ai",
        )

    def _analyze_with_ai(
        self,
        request: AnalysisRequest,
        *,
        interests_file: Optional[str],
    ) -> Optional[AnalysisSelection]:
        print("[筛选] 使用 AI 智能筛选策略")
        result = self._context.run_ai_filter(
            interests_file=interests_file
        )
        if not result or not result.success:
            error = result.error if result else "未知错误"
            print(
                f"[筛选] AI 筛选失败: {error}，回退到关键词匹配"
            )
            return None

        print(
            f"[筛选] AI 筛选完成: {result.total_matched} 条匹配, "
            f"{len(result.tags)} 个标签"
        )
        stats, ai_rss_stats = (
            self._context.convert_ai_filter_to_report_data(
                result,
                mode=request.mode,
                new_titles=request.new_titles,
                rss_new_urls=request.rss_new_urls,
            )
        )
        rss_items = ai_rss_stats or request.rss_items
        return AnalysisSelection(
            stats=stats,
            total_titles=sum(
                len(titles) for titles in request.results.values()
            ),
            rss_items=rss_items,
            filter_method="ai",
        )
