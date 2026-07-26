"""Analysis, aggregation, related-news, and search feature registration."""

from __future__ import annotations

import asyncio
import json
from typing import Dict, List, Optional, Union

from fastmcp import FastMCP

from ..context import get_request_tools


def _json_response(result: Dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


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
        """分析话题趋势、生命周期、异常热度或未来趋势。"""
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
        """分析平台对比、平台活跃度或关键词共现。"""
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
        """生成情感分析所需的结构化新闻与提示词。"""
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
        """查找与参考标题相关的当天或历史新闻。"""
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
        """生成每日或每周热点摘要报告。"""
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
        """跨平台聚合相似新闻并计算覆盖与热度。"""
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
        """对比两个时期的新闻总量、话题变化或平台活跃度。"""
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
        """统一搜索热榜新闻，并可同时搜索 RSS。"""
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
