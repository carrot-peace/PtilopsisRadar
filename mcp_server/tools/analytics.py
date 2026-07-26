"""Compatibility façade composing focused MCP analytics responsibilities."""

from ..services.analytics_service import AnalyticsService
from .analytics_aggregation import AnalyticsAggregationMixin
from .analytics_common import calculate_news_weight
from .analytics_insights import AnalyticsInsightsMixin
from .analytics_search import AnalyticsSearchMixin
from .analytics_trends import AnalyticsTrendsMixin


class AnalyticsTools(
    AnalyticsInsightsMixin,
    AnalyticsSearchMixin,
    AnalyticsTrendsMixin,
    AnalyticsAggregationMixin,
):
    """Public MCP analytics tool surface."""

    def __init__(
        self,
        project_root: str = None,
        *,
        analytics_service=None,
    ):
        """
        初始化分析工具

        Args:
            project_root: 项目根目录
        """
        self.analytics_service = (
            analytics_service or AnalyticsService(project_root)
        )
