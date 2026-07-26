"""Article-reader feature registration."""

from __future__ import annotations

import asyncio
from typing import Dict, List

from fastmcp import FastMCP

from ..context import get_request_tools
from ..presentation import json_response


def _json_response(result: Dict) -> str:
    return json_response(result)


def register_reader_features(server: FastMCP) -> None:
    """Register single and batch article-reading tools."""

    @server.tool
    async def read_article(
        url: str,
        timeout: int = 30,
    ) -> str:
        """
        读取指定 URL 的文章内容，返回 LLM 友好的 Markdown 格式

        通过 Jina AI Reader 将网页转换为干净的 Markdown，自动去除广告、导航栏等噪音内容。
        适合用于：阅读新闻正文、获取文章详情、分析文章内容。

        **典型使用流程：**
        1. 先用 search_news(include_url=True) 搜索新闻获取链接
        2. 再用 read_article(url=链接) 读取正文内容
        3. AI 对 Markdown 正文进行分析、摘要、翻译等

        Args:
            url: 文章链接（必需），以 http:// 或 https:// 开头
            timeout: 请求超时时间（秒），默认 30，最大 60

        Returns:
            JSON格式的文章内容，包含完整 Markdown 正文

        Examples:
            - read_article(url="https://example.com/news/123")

        Note:
            - 使用 Jina AI Reader 免费服务（100 RPM 限制）
            - 每次请求间隔 5 秒（内置速率控制）
            - 部分付费墙/登录墙页面可能无法完整获取
        """
        tools = get_request_tools()
        timeout = min(max(timeout, 10), 60)
        result = await asyncio.to_thread(
            tools["article"].read_article,
            url=url,
            timeout=timeout,
        )
        return _json_response(result)

    @server.tool
    async def read_articles_batch(
        urls: List[str],
        timeout: int = 30,
    ) -> str:
        """
        批量读取多篇文章内容（最多 5 篇，间隔 5 秒）

        逐篇请求文章内容，每篇之间自动间隔 5 秒以遵守速率限制。

        **典型使用流程：**
        1. 先用 search_news(include_url=True) 搜索新闻获取多个链接
        2. 再用 read_articles_batch(urls=[...]) 批量读取正文
        3. AI 对多篇文章进行对比分析、综合报告

        Args:
            urls: 文章链接列表（必需），最多处理 5 篇
            timeout: 每篇的请求超时时间（秒），默认 30

        Returns:
            JSON格式的批量读取结果，包含每篇的完整内容和状态

        Examples:
            - read_articles_batch(urls=["https://a.com/1", "https://b.com/2"])

        Note:
            - 单次最多读取 5 篇，超出部分会被跳过
            - 5 篇约需 25-30 秒（每篇间隔 5 秒）
            - 单篇失败不影响其他篇的读取
        """
        tools = get_request_tools()
        timeout = min(max(timeout, 10), 60)
        result = await asyncio.to_thread(
            tools["article"].read_articles_batch,
            urls=urls,
            timeout=timeout,
        )
        return _json_response(result)
