"""
Ptilopsis Radar MCP Server - FastMCP 2.0 实现

使用 FastMCP 2.0 提供生产级 MCP 工具服务器。
支持 stdio 和 HTTP 两种传输模式。
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastmcp import FastMCP

from .context import MCPContext, get_request_tools
from .features import (
    register_analysis_search_features,
    register_crawl_features,
    register_management_features,
    register_query_features,
)


logger = logging.getLogger(__name__)

# Tool and resource handlers are registered once, then mounted into each
# application instance created by create_server().
_surface = FastMCP("trendradar-news-surface")
register_query_features(_surface)
register_analysis_search_features(_surface)
register_management_features(_surface)
register_crawl_features(_surface)


def _get_tools():
    return get_request_tools()


def create_server(
    *,
    project_root: Optional[str] = None,
    context: Optional[MCPContext] = None,
) -> FastMCP:
    """Create an isolated MCP application and its dependency lifecycle."""
    if project_root is not None and context is not None:
        raise ValueError("project_root and context are mutually exclusive")

    application_context = context or MCPContext.create(project_root)

    @asynccontextmanager
    async def lifespan(_server):
        yield application_context

    server = FastMCP(
        "trendradar-news",
        lifespan=lifespan,
        mask_error_details=True,
    )
    server.mount(_surface, as_proxy=False)
    return server


# ==================== 存储同步工具 ====================

@_surface.tool
async def sync_from_remote(
    days: int = 7
) -> str:
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
    tools = _get_tools()
    result = await asyncio.to_thread(tools['storage'].sync_from_remote, days=days)
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def get_storage_status() -> str:
    """
    获取存储配置和状态

    查看当前存储后端配置、本地和远程存储的状态信息。

    Returns:
        JSON格式的存储状态信息，包含本地/远程存储状态和拉取配置
    """
    tools = _get_tools()
    result = await asyncio.to_thread(tools['storage'].get_storage_status)
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def list_available_dates(
    source: str = "both"
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
    tools = _get_tools()
    result = await asyncio.to_thread(tools['storage'].list_available_dates, source=source)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ==================== 文章内容读取工具 ====================

@_surface.tool
async def read_article(
    url: str,
    timeout: int = 30
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
    tools = _get_tools()
    timeout = min(max(timeout, 10), 60)
    result = await asyncio.to_thread(
        tools['article'].read_article,
        url=url, timeout=timeout
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def read_articles_batch(
    urls: List[str],
    timeout: int = 30
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
    tools = _get_tools()
    timeout = min(max(timeout, 10), 60)
    result = await asyncio.to_thread(
        tools['article'].read_articles_batch,
        urls=urls, timeout=timeout
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ==================== 启动入口 ====================

mcp = create_server()


def run_server(
    project_root: Optional[str] = None,
    transport: str = 'stdio',
    host: str = '0.0.0.0',
    port: int = 3333
):
    """
    启动 MCP 服务器

    Args:
        project_root: 项目根目录路径
        transport: 传输模式，'stdio' 或 'http'
        host: HTTP模式的监听地址，默认 0.0.0.0
        port: HTTP模式的监听端口，默认 3333
    """
    if transport not in {"stdio", "http"}:
        raise ValueError(f"不支持的传输模式: {transport}")

    server = mcp if project_root is None else create_server(
        project_root=project_root
    )
    logger.info(
        "Starting Ptilopsis Radar MCP server transport=%s root=%s",
        transport,
        project_root or "<default>",
    )

    if transport == 'stdio':
        server.run(transport='stdio')
    else:
        server.run(
            transport='http',
            host=host,
            port=port,
            path='/mcp'  # HTTP 端点路径
        )


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Ptilopsis Radar MCP Server - 新闻热点聚合 MCP 工具服务器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
详细配置教程请查看: README-Cherry-Studio.md
        """
    )
    parser.add_argument(
        '--transport',
        choices=['stdio', 'http'],
        default='stdio',
        help='传输模式：stdio (默认) 或 http (生产环境)'
    )
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='HTTP模式的监听地址，默认 0.0.0.0'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=3333,
        help='HTTP模式的监听端口，默认 3333'
    )
    parser.add_argument(
        '--project-root',
        help='项目根目录路径'
    )

    args = parser.parse_args()

    run_server(
        project_root=args.project_root,
        transport=args.transport,
        host=args.host,
        port=args.port
    )
