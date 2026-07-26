"""
Ptilopsis Radar MCP Server - FastMCP 2.0 实现

使用 FastMCP 2.0 提供生产级 MCP 工具服务器。
支持 stdio 和 HTTP 两种传输模式。
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

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
from .transport import (
    BearerTokenVerifier,
    environment_flag,
    validate_http_exposure,
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
    allow_write: bool | None = None,
    expose_error_details: bool | None = None,
    auth: Any = None,
) -> FastMCP:
    """Create an isolated MCP application and its dependency lifecycle."""
    if project_root is not None and context is not None:
        raise ValueError("project_root and context are mutually exclusive")
    if context is not None and (
        allow_write is not None or expose_error_details is not None
    ):
        raise ValueError(
            "context is mutually exclusive with application policy options"
        )

    application_context = context or MCPContext.create(
        project_root,
        allow_write=True if allow_write is None else allow_write,
        expose_error_details=(
            True
            if expose_error_details is None
            else expose_error_details
        ),
    )

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield application_context
        finally:
            await application_context.aclose()

    server = FastMCP(
        "trendradar-news",
        lifespan=lifespan,
        auth=auth,
        mask_error_details=True,
    )
    server.mount(_surface, as_proxy=False)
    return server


# ==================== 启动入口 ====================

mcp = create_server()


def run_server(
    project_root: Optional[str] = None,
    transport: str = 'stdio',
    host: str = '127.0.0.1',
    port: int = 3333,
    allow_http_write: bool | None = None,
    http_bearer_token: str | None = None,
    http_publish_host: str | None = None,
    allow_insecure_public_http: bool | None = None,
):
    """
    启动 MCP 服务器

    Args:
        project_root: 项目根目录路径
        transport: 传输模式，'stdio' 或 'http'
        host: HTTP模式的监听地址，默认 127.0.0.1
        port: HTTP模式的监听端口，默认 3333
    """
    if transport not in {"stdio", "http"}:
        raise ValueError(f"不支持的传输模式: {transport}")

    if transport == "stdio":
        server = create_server(
            project_root=project_root,
            allow_write=True,
            expose_error_details=True,
        )
    else:
        bearer_token = (
            http_bearer_token
            if http_bearer_token is not None
            else os.environ.get("MCP_HTTP_BEARER_TOKEN", "")
        ).strip()
        publish_host = (
            http_publish_host
            if http_publish_host is not None
            else os.environ.get("MCP_HTTP_PUBLISH_HOST", "").strip()
        ) or None
        allow_insecure = (
            allow_insecure_public_http
            if allow_insecure_public_http is not None
            else environment_flag("MCP_HTTP_ALLOW_INSECURE_PUBLIC")
        )
        validate_http_exposure(
            bind_host=host,
            publish_host=publish_host,
            bearer_token=bearer_token,
            allow_insecure_public=allow_insecure,
        )
        write_enabled = (
            allow_http_write
            if allow_http_write is not None
            else environment_flag("MCP_HTTP_ALLOW_WRITE")
        )
        server = create_server(
            project_root=project_root,
            allow_write=write_enabled,
            expose_error_details=False,
            auth=(
                BearerTokenVerifier(bearer_token)
                if bearer_token
                else None
            ),
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
    from .cli import main

    main(run_server)
