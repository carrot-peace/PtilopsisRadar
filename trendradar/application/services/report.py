"""Report translation and rendering service."""

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence


@dataclass(frozen=True, slots=True)
class ReportCounters:
    platform_total: int
    rss_total_count: int
    rss_source_total: int
    rss_source_failed: int


@dataclass(frozen=True, slots=True)
class ReportRequest:
    mode: str
    stats: Sequence[Mapping[str, Any]]
    total_titles: int
    failed_ids: Sequence[str]
    new_titles: Mapping[str, Any]
    id_to_name: Mapping[str, str]
    rss_items: Optional[list[dict]]
    rss_new_items: Optional[list[dict]]
    ai_analysis: Any
    update_info: Optional[Mapping[str, Any]]
    frequency_file: Optional[str]
    counters: ReportCounters


@dataclass(frozen=True, slots=True)
class ReportResult:
    html_file: Optional[str]
    rss_items: Optional[list[dict]]
    rss_new_items: Optional[list[dict]]
    rss_matched_count: int


class ContextReportGateway:
    """Narrow rendering port over the legacy application context."""

    def __init__(self, context):
        self._context = context

    @property
    def html_enabled(self) -> bool:
        return bool(
            self._context.config["STORAGE"]["FORMATS"]["HTML"]
        )

    @property
    def translation_enabled(self) -> bool:
        return bool(
            self._context.config.get("AI_TRANSLATION", {}).get(
                "ENABLED",
                False,
            )
        )

    @property
    def debug(self) -> bool:
        return bool(self._context.config.get("DEBUG", False))

    @property
    def show_version_update(self) -> bool:
        return bool(self._context.config.get("SHOW_VERSION_UPDATE", False))

    def create_translator(self):
        return self._context.create_artifact_translator()

    def generate_html(self, *args, **kwargs):
        return self._context.generate_html(*args, **kwargs)

    def generate_dashboard(self, **kwargs):
        return self._context.generate_dashboard(**kwargs)


class ReportService:
    """Translate report content and route it to exactly one renderer."""

    def __init__(self, gateway, *, translate_content: Optional[Callable] = None):
        self._gateway = gateway
        self._translate_content = translate_content

    def _translator(self) -> Callable:
        if self._translate_content is not None:
            return self._translate_content
        from trendradar.report.translation import translate_report_content

        return translate_report_content

    def render(self, request: ReportRequest) -> ReportResult:
        rss_items = request.rss_items
        rss_new_items = request.rss_new_items
        if self._gateway.translation_enabled:
            _, rss_items, rss_new_items = self._translator()(
                report_data={"stats": [], "new_titles": []},
                rss_items=rss_items,
                rss_new_items=rss_new_items,
                translator=self._gateway.create_translator(),
                debug=self._gateway.debug,
            )

        rss_matched_count = (
            sum(item.get("count", 0) for item in rss_items)
            if rss_items
            else 0
        )
        html_file = None
        if self._gateway.html_enabled:
            metadata = {
                "hotlist_total": request.total_titles,
                "platform_total": request.counters.platform_total,
                "rss_matched_count": rss_matched_count,
                "rss_total_count": request.counters.rss_total_count,
                "rss_source_total": request.counters.rss_source_total,
                "rss_source_failed": request.counters.rss_source_failed,
            }
            if request.mode == "daily":
                html_file = self._gateway.generate_html(
                    request.stats,
                    request.total_titles,
                    failed_ids=request.failed_ids,
                    new_titles=request.new_titles,
                    id_to_name=request.id_to_name,
                    mode=request.mode,
                    update_info=(
                        request.update_info
                        if self._gateway.show_version_update
                        else None
                    ),
                    rss_items=rss_items,
                    rss_new_items=rss_new_items,
                    ai_analysis=request.ai_analysis,
                    frequency_file=request.frequency_file,
                    report_metadata=metadata,
                )
            else:
                self._gateway.generate_dashboard(
                    mode=request.mode,
                    ai_analysis=request.ai_analysis,
                    report_metadata=metadata,
                    stats=request.stats,
                    rss_items=rss_items,
                )

        return ReportResult(
            html_file=html_file,
            rss_items=rss_items,
            rss_new_items=rss_new_items,
            rss_matched_count=rss_matched_count,
        )
