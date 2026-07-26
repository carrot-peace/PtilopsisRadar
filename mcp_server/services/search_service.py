"""Read boundary dedicated to MCP search use cases."""

from typing import Optional

from .parser_service import ParserService


class SearchService:
    """Expose only snapshot operations required by search tools."""

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

    def read_rss(self, *, date=None):
        return self._parser.read_all_titles_for_date(
            date=date,
            platform_ids=None,
            db_type="rss",
        )

    def get_available_date_range(self):
        return self._parser.get_available_date_range("news")
