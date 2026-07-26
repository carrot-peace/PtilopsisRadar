"""Feature-domain registration modules for the MCP application."""

from .analysis_search import register_analysis_search_features
from .query import register_query_features


__all__ = [
    "register_analysis_search_features",
    "register_query_features",
]
