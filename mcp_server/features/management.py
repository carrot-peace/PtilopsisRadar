"""Configuration and read-only system management feature registration."""

from __future__ import annotations

import asyncio
import json
from typing import Dict, Optional

from fastmcp import FastMCP

from ..context import get_request_tools


def _json_response(result: Dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def register_management_features(server: FastMCP) -> None:
    """Register configuration, health, and version-query tools."""

    @server.tool
    async def get_current_config(section: str = "all") -> str:
        """
        获取当前系统配置

        Args:
            section: 配置节，可选值：
                - "all": 所有配置（默认）
                - "crawler": 爬虫配置
                - "keywords": 关键词配置
                - "weights": 权重配置

        Returns:
            JSON格式的配置信息
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["config"].get_current_config,
            section=section,
        )
        return _json_response(result)

    @server.tool
    async def get_system_status() -> str:
        """
        获取系统运行状态和健康检查信息

        返回系统版本、数据统计、缓存状态等信息

        Returns:
            JSON格式的系统状态信息
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["system"].get_system_status
        )
        return _json_response(result)

    @server.tool
    async def check_version(
        proxy_url: Optional[str] = None,
    ) -> str:
        """
        检查版本更新（同时检查 Ptilopsis Radar 和 MCP Server）

        比较本地版本与 GitHub 远程版本，判断是否需要更新。

        Args:
            proxy_url: 可选的代理URL，用于访问 GitHub（如 http://127.0.0.1:7890）

        Returns:
            JSON格式的版本检查结果，包含两个组件的版本对比和是否需要更新

        Examples:
            - check_version()
            - check_version(proxy_url="http://127.0.0.1:7890")
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["system"].check_version,
            proxy_url=proxy_url,
        )
        return _json_response(result)
