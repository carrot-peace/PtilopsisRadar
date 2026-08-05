"""Remote pull and storage-status feature registration."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP

from ..context import get_request_tools, write_access_error
from ..presentation import json_response


def register_storage_features(server: FastMCP) -> None:
    """Register remote synchronization and storage inspection tools."""

    @server.tool
    async def sync_from_remote(days: int = 7) -> str:
        """
        从远程存储拉取数据到本地

        用于 MCP Server 等场景：爬虫存到远程云存储（如 Cloudflare R2），
        MCP Server 拉取到本地进行分析查询。

        Args:
            days: 拉取最近 N 天的数据，默认 7 天
                  - 0: 不拉取
                  - 7: 拉取最近一周的数据
                  - 30: 拉取最近一个月的数据

        Returns:
            JSON格式的同步结果，包含：
            - success: 是否成功
            - synced_files: 成功同步的文件数量
            - synced_dates: 成功同步的日期列表
            - skipped_dates: 跳过的日期（本地已存在）
            - failed_dates: 失败的日期及错误信息
            - message: 操作结果描述

        Examples:
            - sync_from_remote()  # 拉取最近7天
            - sync_from_remote(days=30)  # 拉取最近30天

        Note:
            需要在 config/config.yaml 中配置远程存储（storage.remote）或设置环境变量：
            - S3_ENDPOINT_URL: 服务端点
            - S3_BUCKET_NAME: 存储桶名称
            - S3_ACCESS_KEY_ID: 访问密钥 ID
            - S3_SECRET_ACCESS_KEY: 访问密钥
        """
        denied = write_access_error()
        if denied is not None:
            return json_response(denied)
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["storage"].sync_from_remote,
            days=days,
        )
        return json_response(result)

    @server.tool
    async def get_storage_status() -> str:
        """
        获取存储配置和状态

        查看当前存储后端配置、本地和远程存储的状态信息。

        Returns:
            JSON格式的存储状态信息，包含本地/远程存储状态和拉取配置
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["storage"].get_storage_status
        )
        return json_response(result)

    @server.tool
    async def list_available_dates(
        source: str = "both",
    ) -> str:
        """
        列出本地/远程可用的日期范围

        查看本地和远程存储中有哪些日期的数据可用。

        Args:
            source: 数据来源
                - "local": 仅本地
                - "remote": 仅远程
                - "both": 同时列出并对比（默认）

        Returns:
            JSON格式的日期列表，包含各来源的日期信息和对比结果

        Examples:
            - list_available_dates()
            - list_available_dates(source="local")
        """
        tools = get_request_tools()
        result = await asyncio.to_thread(
            tools["storage"].list_available_dates,
            source=source,
        )
        return json_response(result)
