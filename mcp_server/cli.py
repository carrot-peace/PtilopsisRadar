"""Command-line parsing for the MCP server."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ptilopsis Radar MCP Server - 新闻热点聚合 MCP 工具服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="详细配置教程请查看: README-Cherry-Studio.md",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="传输模式：stdio (默认) 或 http",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP 模式的监听地址，默认 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3333,
        help="HTTP 模式的监听端口，默认 3333",
    )
    parser.add_argument("--project-root", help="项目根目录路径")
    parser.add_argument(
        "--allow-http-write",
        action="store_true",
        default=None,
        help="允许 HTTP 客户端执行爬取和远端同步写操作",
    )
    parser.add_argument(
        "--allow-insecure-public-http",
        action="store_true",
        default=None,
        help="显式允许未认证的非回环 HTTP 暴露（不推荐）",
    )
    return parser


def main(
    run: Callable[..., Any] | None = None,
    argv: Sequence[str] | None = None,
) -> None:
    """Parse CLI options and delegate to the transport runtime."""
    if run is None:
        from .server import run_server

        run = run_server
    args = build_parser().parse_args(argv)
    run(
        project_root=args.project_root,
        transport=args.transport,
        host=args.host,
        port=args.port,
        allow_http_write=args.allow_http_write,
        allow_insecure_public_http=args.allow_insecure_public_http,
    )
