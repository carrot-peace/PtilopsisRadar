"""Application-scoped dependencies for the MCP server."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from fastmcp.server.dependencies import get_context

from .tools.analytics import AnalyticsTools
from .tools.article_reader import ArticleReaderTools
from .tools.config_mgmt import ConfigManagementTools
from .tools.crawl import CrawlTools
from .tools.data_query import DataQueryTools
from .tools.search_tools import SearchTools
from .tools.storage_sync import StorageSyncTools
from .tools.system import SystemManagementTools


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MCPContext:
    """Own the dependencies and project root for one MCP application."""

    project_root: Path
    tools: Mapping[str, Any]
    allow_write: bool = True
    expose_error_details: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "project_root",
            self.project_root.expanduser().resolve(),
        )
        object.__setattr__(
            self,
            "tools",
            MappingProxyType(dict(self.tools)),
        )

    @classmethod
    def create(
        cls,
        project_root: str | Path | None = None,
        *,
        allow_write: bool = True,
        expose_error_details: bool = True,
    ) -> "MCPContext":
        root = (
            Path(project_root)
            if project_root is not None
            else Path(__file__).resolve().parents[1]
        ).expanduser().resolve()
        root_text = str(root)
        return cls(
            project_root=root,
            allow_write=allow_write,
            expose_error_details=expose_error_details,
            tools={
                "data": DataQueryTools(root_text),
                "analytics": AnalyticsTools(root_text),
                "search": SearchTools(root_text),
                "config": ConfigManagementTools(root_text),
                "system": SystemManagementTools(root_text),
                "crawl": CrawlTools(root_text),
                "storage": StorageSyncTools(root_text),
                "article": ArticleReaderTools(root_text),
            },
        )

    @classmethod
    def from_tools(
        cls,
        *,
        project_root: str | Path,
        tools: Mapping[str, Any],
        allow_write: bool = True,
        expose_error_details: bool = True,
    ) -> "MCPContext":
        """Build a context from explicit dependencies for tests or embedding."""
        return cls(
            project_root=Path(project_root),
            tools=tools,
            allow_write=allow_write,
            expose_error_details=expose_error_details,
        )

    def get_tool(self, name: str) -> Any:
        try:
            return self.tools[name]
        except KeyError as exc:
            raise KeyError(f"MCP tool dependency is not configured: {name}") from exc

    async def aclose(self) -> None:
        """Release each owned dependency once when the application stops."""
        seen: set[int] = set()
        for name, tool in self.tools.items():
            identity = id(tool)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                callback = next(
                    (
                        getattr(tool, method_name)
                        for method_name in ("aclose", "close", "cleanup")
                        if inspect.getattr_static(tool, method_name, None)
                        is not None
                    ),
                    None,
                )
                if callback is None:
                    continue
                result = callback()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.warning(
                    "Failed to close MCP dependency %s: %s",
                    name,
                    exc,
                )


def get_request_context() -> MCPContext:
    """Return the active application's immutable dependency context."""
    request_context = get_context().request_context
    application_context = request_context.lifespan_context
    if not isinstance(application_context, MCPContext):
        raise RuntimeError("MCP application context is not configured")
    return application_context


def get_request_tools() -> Mapping[str, Any]:
    """Return dependencies owned by the active MCP application."""
    return get_request_context().tools


def write_access_error() -> dict[str, Any] | None:
    """Return a stable denial payload when this application is read-only."""
    if get_request_context().allow_write:
        return None
    return {
        "success": False,
        "error": {
            "code": "PERMISSION_DENIED",
            "message": "当前 MCP Transport 仅允许只读操作",
            "suggestion": (
                "仅在受信任且已认证的 HTTP 环境中启用写操作"
            ),
        },
    }
