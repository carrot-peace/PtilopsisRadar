"""News, RSS, date resolution, and read-only resource registration."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Union

from fastmcp import FastMCP

from ..context import get_request_tools
from ..presentation import json_response
from ..utils.date_parser import DateParser
from ..utils.errors import MCPError


def _json_response(result: Dict) -> str:
    return json_response(result)


def _config_payload(result: Dict) -> Dict:
    if result.get("success") is not True:
        return {}
    config = result.get("config")
    return config if isinstance(config, dict) else {}


def register_query_features(server: FastMCP) -> None:
    """Register the complete read-only query and resource feature domain."""

    @server.resource("config://platforms")
    async def get_platforms_resource() -> str:
        """获取 config.yaml 中启用的热榜平台。"""
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["config"].get_current_config,
            section="crawler",
        )
        config = _config_payload(result)
        return _json_response({
            "platforms": config.get("platforms", []),
            "description": "Ptilopsis Radar 支持的热榜平台列表",
        })

    @server.resource("config://rss-feeds")
    async def get_rss_feeds_resource() -> str:
        """获取当前配置的 RSS 订阅源及今日状态。"""
        tools = get_request_tools()
        status = await asyncio.to_thread(
            tools["data"].get_rss_feeds_status
        )
        return _json_response({
            "feeds": status.get("today_feeds", {}),
            "description": "Ptilopsis Radar 支持的 RSS 订阅源列表",
        })

    @server.resource("data://available-dates")
    async def get_available_dates_resource() -> str:
        """获取本地存储中可查询的数据日期。"""
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["storage"].list_available_dates,
            source="local",
        )
        return _json_response({
            "dates": (
                result.get("data", {})
                .get("local", {})
                .get("dates", [])
            ),
            "description": "本地存储中可查询的日期列表",
        })

    @server.resource("config://keywords")
    async def get_keywords_resource() -> str:
        """获取 frequency_words.txt 中的关注词分组。"""
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["config"].get_current_config,
            section="keywords",
        )
        config = _config_payload(result)
        return _json_response({
            "word_groups": config.get("word_groups", []),
            "total_groups": config.get("total_groups", 0),
            "description": "Ptilopsis Radar 关注词配置",
        })

    @server.tool
    async def resolve_date_range(expression: str) -> str:
        """
        将自然语言日期表达式解析为标准日期范围。

        expression 支持今天/昨天、本周/上周、本月/上月、最近 N 天，
        以及对应英文表达。返回的 date_range 可直接传给其他查询和分析工具，
        避免客户端自行计算相对日期。
        """
        try:
            result = await asyncio.to_thread(
                DateParser.resolve_date_range_expression,
                expression,
            )
            return _json_response(result)
        except MCPError as exc:
            return _json_response({
                "success": False,
                "error": exc.to_dict(),
            })
        except Exception as exc:
            return _json_response({
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                },
            })

    @server.tool
    async def get_latest_news(
        platforms: Optional[List[str]] = None,
        limit: int = 50,
        include_url: bool = False,
    ) -> str:
        """
        获取最新一批热榜新闻。

        platforms 可限制平台；limit 默认 50；include_url 默认关闭以节省 token。
        默认应展示全部返回数据，仅在用户明确要求总结时筛选。
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["data"].get_latest_news,
            platforms=platforms,
            limit=limit,
            include_url=include_url,
        )
        return _json_response(result)

    @server.tool
    async def get_trending_topics(
        top_n: int = 10,
        mode: str = "current",
        extract_mode: str = "keywords",
    ) -> str:
        """
        获取热点话题统计。

        mode 支持 current/daily；extract_mode 支持 keywords/auto_extract。
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["data"].get_trending_topics,
            top_n=top_n,
            mode=mode,
            extract_mode=extract_mode,
        )
        return _json_response(result)

    @server.tool
    async def get_latest_rss(
        feeds: Optional[List[str]] = None,
        days: int = 1,
        limit: int = 50,
        include_summary: bool = False,
    ) -> str:
        """
        获取最近若干天的 RSS 订阅数据。

        feeds 可限制订阅源；days 默认 1、范围 1-30；limit 默认 50；
        include_summary 默认关闭以节省 token。
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["data"].get_latest_rss,
            feeds=feeds,
            days=days,
            limit=limit,
            include_summary=include_summary,
        )
        return _json_response(result)

    @server.tool
    async def search_rss(
        keyword: str,
        feeds: Optional[List[str]] = None,
        days: int = 7,
        limit: int = 50,
        include_summary: bool = False,
    ) -> str:
        """
        在最近若干天的 RSS 订阅数据中搜索关键词。

        keyword 必填；feeds 可限制订阅源；days 默认 7、范围 1-30；
        limit 默认 50；include_summary 控制是否返回文章摘要。
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["data"].search_rss,
            keyword=keyword,
            feeds=feeds,
            days=days,
            limit=limit,
            include_summary=include_summary,
        )
        return _json_response(result)

    @server.tool
    async def get_rss_feeds_status() -> str:
        """
        获取 RSS 源、可用日期和今日条目统计。

        返回 available_dates、total_dates、today_feeds 和 generated_at。
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["data"].get_rss_feeds_status
        )
        return _json_response(result)

    @server.tool
    async def get_news_by_date(
        date_range: Optional[Union[Dict[str, str], str]] = None,
        platforms: Optional[List[str]] = None,
        limit: int = 50,
        include_url: bool = False,
    ) -> str:
        """
        获取单日或日期范围内的新闻，最多查询连续 31 天。

        date_range 支持 start/end 对象、JSON 对象字符串、自然语言或单日日期。
        platforms 可限制平台；limit 默认 50；include_url 默认关闭。
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["data"].get_news_by_date,
            date_range=date_range,
            platforms=platforms,
            limit=limit,
            include_url=include_url,
        )
        return _json_response(result)
