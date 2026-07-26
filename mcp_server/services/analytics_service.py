"""Read boundary dedicated to MCP analytics use cases."""

from typing import Optional

from .parser_service import ParserService


class AnalyticsService:
    """Expose news snapshots without search or mutation responsibilities."""

    def __init__(
        self,
        project_root: Optional[str] = None,
        *,
        parser=None,
    ):
        self._parser = parser or ParserService(project_root)

    def read_news(self, *, date=None, platforms=None):
        return self._parser.read_all_titles_for_date(
            date=date,
            platform_ids=platforms,
        )
