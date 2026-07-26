"""
Ptilopsis Radar MCP Server - FastMCP 2.0 实现

使用 FastMCP 2.0 提供生产级 MCP 工具服务器。
支持 stdio 和 HTTP 两种传输模式。
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastmcp import FastMCP

from .context import MCPContext
from .features import (
    register_analysis_search_features,
    register_crawl_features,
    register_management_features,
    register_query_features,
    register_reader_features,
    register_storage_features,
)


logger = logging.getLogger(__name__)

# Tool and resource handlers are registered once, then mounted into each
# application instance created by create_server().
_surface = FastMCP("trendradar-news-surface")
register_query_features(_surface)
register_analysis_search_features(_surface)
register_management_features(_surface)
register_crawl_features(_surface)
register_storage_features(_surface)
register_reader_features(_surface)


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
