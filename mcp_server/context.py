"""Application-scoped dependencies for the MCP server."""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class MCPContext:
    """Own the dependencies and project root for one MCP application."""

    project_root: Path
    tools: Mapping[str, Any]

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
    def create(cls, project_root: str | Path | None = None) -> "MCPContext":
        root = (
            Path(project_root)
            if project_root is not None
            else Path(__file__).resolve().parents[1]
        ).expanduser().resolve()
        root_text = str(root)
        return cls(
            project_root=root,
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
    ) -> "MCPContext":
        """Build a context from explicit dependencies for tests or embedding."""
        return cls(project_root=Path(project_root), tools=tools)

    def get_tool(self, name: str) -> Any:
        try:
            return self.tools[name]
        except KeyError as exc:
            raise KeyError(f"MCP tool dependency is not configured: {name}") from exc


def get_request_tools() -> Mapping[str, Any]:
    """Return dependencies owned by the active MCP application."""
    request_context = get_context().request_context
    application_context = request_context.lifespan_context
    if not isinstance(application_context, MCPContext):
        raise RuntimeError("MCP application context is not configured")
    return application_context.tools
