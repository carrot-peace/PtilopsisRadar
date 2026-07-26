"""One-off crawl feature registration."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from fastmcp import FastMCP

from ..context import get_request_tools, write_access_error
from ..presentation import json_response


def register_crawl_features(server: FastMCP) -> None:
    """Register the temporary crawl command."""

    @server.tool
    async def trigger_crawl(
        platforms: Optional[List[str]] = None,
        save_to_local: bool = False,
        include_url: bool = False,
    ) -> str:
        """
        手动触发一次爬取任务（可选持久化）

        Args:
            platforms: 平台ID列表，如 ['zhihu', 'weibo']，不指定则使用所有平台
            save_to_local: 是否保存到本地 output 目录，默认 False
            include_url: 是否包含URL链接，默认False（节省token）

        Returns:
            JSON格式的任务状态信息，包含成功/失败平台列表和新闻数据

        Examples:
            - trigger_crawl(platforms=['zhihu'])
            - trigger_crawl(save_to_local=True)
        """
        denied = write_access_error()
        if denied is not None:
            return json_response(denied)
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["crawl"].trigger_crawl,
            platforms=platforms,
            save_to_local=save_to_local,
            include_url=include_url,
        )
        return json_response(result)
