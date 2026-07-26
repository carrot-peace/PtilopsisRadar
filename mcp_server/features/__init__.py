"""Feature-domain registration modules for the MCP application."""

from .analysis_search import register_analysis_search_features
from .crawl import register_crawl_features
from .management import register_management_features
from .query import register_query_features


__all__ = [
    "register_analysis_search_features",
    "register_crawl_features",
    "register_management_features",
    "register_query_features",
]
