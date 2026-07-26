"""Analysis, aggregation, related-news, and search feature registration."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Union

from fastmcp import FastMCP

from ..context import get_request_tools
from ..presentation import json_response


def _json_response(result: Dict) -> str:
    return json_response(result)


def register_analysis_search_features(server: FastMCP) -> None:
    """Register the public analysis and intelligent-search feature domain."""

    @server.tool
    async def analyze_topic_trend(
        topic: str,
        analysis_type: str = "trend",
        date_range: Optional[Union[Dict[str, str], str]] = None,
        granularity: str = "day",
        spike_threshold: float = 3.0,
        time_window: int = 24,
        lookahead_hours: int = 6,
        confidence_threshold: float = 0.7,
    ) -> str:
        """
        统一话题趋势分析工具 - 整合多种趋势分析模式

        建议：使用自然语言日期时，先调用 resolve_date_range 获取精确日期范围。

        Args:
            topic: 话题关键词（必需）
            analysis_type: 分析类型
                - "trend": 热度趋势分析（默认）
                - "lifecycle": 生命周期分析
                - "viral": 异常热度检测
                - "predict": 话题预测
            date_range: 日期范围，格式 {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}，默认最近7天
            granularity: 时间粒度，默认"day"
            spike_threshold: 热度突增倍数阈值（viral模式），默认3.0
            time_window: 检测时间窗口小时数（viral模式），默认24
            lookahead_hours: 预测未来小时数（predict模式），默认6
            confidence_threshold: 置信度阈值（predict模式），默认0.7

        Returns:
            JSON格式的趋势分析结果

        Examples:
            - analyze_topic_trend(topic="AI", date_range={"start": "2025-01-01", "end": "2025-01-07"})
            - analyze_topic_trend(topic="特斯拉", analysis_type="lifecycle")
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["analytics"].analyze_topic_trend_unified,
            topic=topic,
            analysis_type=analysis_type,
            date_range=date_range,
            granularity=granularity,
            threshold=spike_threshold,
            time_window=time_window,
            lookahead_hours=lookahead_hours,
            confidence_threshold=confidence_threshold,
        )
        return _json_response(result)

    @server.tool
    async def analyze_data_insights(
        insight_type: str = "platform_compare",
        topic: Optional[str] = None,
        date_range: Optional[Union[Dict[str, str], str]] = None,
        min_frequency: int = 3,
        top_n: int = 20,
    ) -> str:
        """
        统一数据洞察分析工具 - 整合多种数据分析模式

        Args:
            insight_type: 洞察类型，可选值：
                - "platform_compare": 平台对比分析（对比不同平台对话题的关注度）
                - "platform_activity": 平台活跃度统计（统计各平台发布频率和活跃时间）
                - "keyword_cooccur": 关键词共现分析（分析关键词同时出现的模式）
            topic: 话题关键词（可选，platform_compare模式适用）
            date_range: **【对象类型】** 日期范围（可选）
                        - **格式**: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                        - **示例**: {"start": "2025-01-01", "end": "2025-01-07"}
                        - **重要**: 必须是对象格式，不能传递整数
            min_frequency: 最小共现频次（keyword_cooccur模式），默认3
            top_n: 返回TOP N结果（keyword_cooccur模式），默认20

        Returns:
            JSON格式的数据洞察分析结果

        Examples:
            - analyze_data_insights(insight_type="platform_compare", topic="人工智能")
            - analyze_data_insights(insight_type="platform_activity", date_range={"start": "2025-01-01", "end": "2025-01-07"})
            - analyze_data_insights(insight_type="keyword_cooccur", min_frequency=5, top_n=15)
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["analytics"].analyze_data_insights_unified,
            insight_type=insight_type,
            topic=topic,
            date_range=date_range,
            min_frequency=min_frequency,
            top_n=top_n,
        )
        return _json_response(result)

    @server.tool
    async def analyze_sentiment(
        topic: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        date_range: Optional[Union[Dict[str, str], str]] = None,
        limit: int = 50,
        sort_by_weight: bool = True,
        include_url: bool = False,
    ) -> str:
        """
        分析新闻的情感倾向和热度趋势

        建议：使用自然语言日期时，先调用 resolve_date_range 获取精确日期范围。

        Args:
            topic: 话题关键词（可选）
            platforms: 平台ID列表，如 ['zhihu', 'weibo']，不指定则使用所有平台
            date_range: 日期范围，格式 {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}，默认今天
            limit: 返回新闻数量，默认50，最大100（会对标题去重）
            sort_by_weight: 是否按热度权重排序，默认True
            include_url: 是否包含URL链接，默认False（节省token）

        Returns:
            JSON格式的分析结果，包含情感分布、热度趋势和相关新闻

        Examples:
            - analyze_sentiment(topic="AI", date_range={"start": "2025-01-01", "end": "2025-01-07"})
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["analytics"].analyze_sentiment,
            topic=topic,
            platforms=platforms,
            date_range=date_range,
            limit=limit,
            sort_by_weight=sort_by_weight,
            include_url=include_url,
        )
        return _json_response(result)

    @server.tool
    async def find_related_news(
        reference_title: str,
        date_range: Optional[Union[Dict[str, str], str]] = None,
        threshold: float = 0.5,
        limit: int = 50,
        include_url: bool = False,
    ) -> str:
        """
        查找与指定新闻标题相关的其他新闻（支持当天和历史数据）

        Args:
            reference_title: 参考新闻标题（完整或部分）
            date_range: 日期范围（可选）
                - 不指定: 只查询今天的数据
                - "today", "yesterday", "last_week", "last_month": 预设值
                - {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}: 自定义范围
            threshold: 相似度阈值，0-1之间，默认0.5（越高匹配越严格）
            limit: 返回条数限制，默认50
            include_url: 是否包含URL链接，默认False（节省token）

        Returns:
            JSON格式的相关新闻列表，按相似度排序

        Examples:
            - find_related_news(reference_title="特斯拉降价")
            - find_related_news(reference_title="AI突破", date_range="last_week")
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["search"].find_related_news_unified,
            reference_title=reference_title,
            date_range=date_range,
            threshold=threshold,
            limit=limit,
            include_url=include_url,
        )
        return _json_response(result)

    @server.tool
    async def generate_summary_report(
        report_type: str = "daily",
        date_range: Optional[Union[Dict[str, str], str]] = None,
    ) -> str:
        """
        每日/每周摘要生成器 - 自动生成热点摘要报告

        Args:
            report_type: 报告类型（daily/weekly）
            date_range: **【对象类型】** 自定义日期范围（可选）
                        - **格式**: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                        - **示例**: {"start": "2025-01-01", "end": "2025-01-07"}
                        - **重要**: 必须是对象格式，不能传递整数

        Returns:
            JSON格式的摘要报告，包含Markdown格式内容
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["analytics"].generate_summary_report,
            report_type=report_type,
            date_range=date_range,
        )
        return _json_response(result)

    @server.tool
    async def aggregate_news(
        date_range: Optional[Union[Dict[str, str], str]] = None,
        platforms: Optional[List[str]] = None,
        similarity_threshold: float = 0.7,
        limit: int = 50,
        include_url: bool = False,
    ) -> str:
        """
        跨平台新闻聚合 - 对相似新闻进行去重合并

        将不同平台报道的同一事件合并为一条聚合新闻，显示跨平台覆盖情况和综合热度。

        Args:
            date_range: 日期范围，不指定则查询今天
            platforms: 平台ID列表，如 ['zhihu', 'weibo']，不指定则使用所有平台
            similarity_threshold: 相似度阈值，0.3-1.0，默认0.7（越高越严格）
            limit: 返回聚合新闻数量，默认50
            include_url: 是否包含URL链接，默认False

        Returns:
            JSON格式的聚合结果，包含去重统计、聚合新闻列表和平台覆盖统计

        Examples:
            - aggregate_news()
            - aggregate_news(similarity_threshold=0.8)
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["analytics"].aggregate_news,
            date_range=date_range,
            platforms=platforms,
            similarity_threshold=similarity_threshold,
            limit=limit,
            include_url=include_url,
        )
        return _json_response(result)

    @server.tool
    async def compare_periods(
        period1: Union[Dict[str, str], str],
        period2: Union[Dict[str, str], str],
        topic: Optional[str] = None,
        compare_type: str = "overview",
        platforms: Optional[List[str]] = None,
        top_n: int = 10,
    ) -> str:
        """
        时期对比分析 - 比较两个时间段的新闻数据

        对比不同时期的热点话题、平台活跃度、新闻数量等维度。

        **使用场景：**
        - 对比本周和上周的热点变化
        - 分析某个话题在两个时期的热度差异
        - 查看各平台活跃度的周期性变化

        Args:
            period1: 第一个时间段（基准期）
                - {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}: 日期范围
                - "today", "yesterday", "this_week", "last_week", "this_month", "last_month": 预设值
            period2: 第二个时间段（对比期，格式同 period1）
            topic: 可选的话题关键词（聚焦特定话题的对比）
            compare_type: 对比类型
                - "overview": 总体概览（默认）- 新闻数量、关键词变化、TOP新闻
                - "topic_shift": 话题变化分析 - 上升话题、下降话题、新出现话题
                - "platform_activity": 平台活跃度对比 - 各平台新闻数量变化
            platforms: 平台过滤列表，如 ['zhihu', 'weibo']
            top_n: 返回 TOP N 结果，默认10

        Returns:
            JSON格式的对比分析结果，包含：
            - periods: 两个时期的日期范围
            - compare_type: 对比类型
            - overview/topic_shift/platform_comparison: 具体对比结果（根据类型）

        Examples:
            - compare_periods(period1="last_week", period2="this_week")  # 周环比
            - compare_periods(period1="last_month", period2="this_month", compare_type="topic_shift")
            - compare_periods(
                period1={"start": "2025-01-01", "end": "2025-01-07"},
                period2={"start": "2025-01-08", "end": "2025-01-14"},
                topic="人工智能"
              )
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["analytics"].compare_periods,
            period1=period1,
            period2=period2,
            topic=topic,
            compare_type=compare_type,
            platforms=platforms,
            top_n=top_n,
        )
        return _json_response(result)

    @server.tool
    async def search_news(
        query: str,
        search_mode: str = "keyword",
        date_range: Optional[Union[Dict[str, str], str]] = None,
        platforms: Optional[List[str]] = None,
        limit: int = 50,
        sort_by: str = "relevance",
        threshold: float = 0.6,
        include_url: bool = False,
        include_rss: bool = False,
        rss_limit: int = 20,
    ) -> str:
        """
        统一搜索接口，支持多种搜索模式，可同时搜索热榜和RSS

        建议：使用自然语言日期时，先调用 resolve_date_range 获取精确日期范围。

        Args:
            query: 搜索关键词或内容片段
            search_mode: 搜索模式
                - "keyword": 精确关键词匹配（默认）
                - "fuzzy": 模糊内容匹配
                - "entity": 实体名称搜索（人物/地点/机构）
            date_range: 日期范围，格式 {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}，默认今天
            platforms: 平台ID列表，如 ['zhihu', 'weibo']，不指定则使用所有平台
            limit: 热榜返回条数限制，默认50
            sort_by: 排序方式 - "relevance"（相关度）/ "weight"（权重）/ "date"（日期）
            threshold: 相似度阈值（仅fuzzy模式），0-1，默认0.6
            include_url: 是否包含URL链接，默认False
            include_rss: 是否同时搜索RSS数据，默认False
            rss_limit: RSS返回条数限制，默认20

        Returns:
            JSON格式的搜索结果，包含热榜新闻列表和可选的RSS结果

        Examples:
            - search_news(query="AI")
            - search_news(query="AI", include_rss=True)
            - search_news(query="特斯拉", date_range={"start": "2025-01-01", "end": "2025-01-07"})
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["search"].search_news_unified,
            query=query,
            search_mode=search_mode,
            date_range=date_range,
            platforms=platforms,
            limit=limit,
            sort_by=sort_by,
            threshold=threshold,
            include_url=include_url,
            include_rss=include_rss,
            rss_limit=rss_limit,
        )
        return _json_response(result)
